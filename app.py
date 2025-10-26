# app.py (patched)

import os
from flask import Flask, redirect, url_for, session, render_template, request, jsonify
from authlib.integrations.flask_client import OAuth
from datetime import datetime
from werkzeug.middleware.proxy_fix import ProxyFix
import re
from flask import send_from_directory, abort
from werkzeug.utils import safe_join
# (optional) server-side sessions are more robust behind VPNs/ad-blockers
try:
    from flask_session import Session
    HAVE_FLASK_SESSION = True
except Exception:
    HAVE_FLASK_SESSION = False

from analysis_functions import (
    performance_metrics,
    compute_rebased_indices,
    compute_lockedin_projection,
    compensation_chart_data,
    performance_metric_public
)
import numpy as np
import math
import json
import pandas as pd

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
# -------- Per-user documents configuration --------
DOCS_ROOT = os.path.join(BASE_DIR, "static", "user_docs")  # where files live on disk
DOC_CATEGORIES = {
    "Contracts": "Contracts",
    "Correspondence": "Correspondence",
    "Financial Receipts": "Financial Receipts",
}
ALLOWED_EXT = {".pdf", ".png", ".jpg", ".jpeg", ".docx", ".xlsx", ".csv", ".txt", ".zip"}

def _current_user_email():
    # Works with MOCK_MODE or real OAuth
    user = session.get("user") or {}
    return user.get("email")

def _user_key_from_email(email: str) -> str:
    if email.endswith("@gmail.com"):
        local = email[:-10]
    else:
        local = email.split("@", 1)[0]
    # keep only safe chars; hyphen is allowed
    local = re.sub(r"[^a-zA-Z0-9_.-]", "_", local)
    # BEFORE: return f"{local}_data"
    return f"{local}-data"   # ← hyphen to match your folder name

def _user_docs_root(email: str) -> str:
    return os.path.join(DOCS_ROOT, _user_key_from_email(email))

app = Flask(__name__)

# ---- Security & proxy awareness
# Use a stable secret in production; fail fast if missing on Render
if os.environ.get("RENDER"):
    app.config["SECRET_KEY"] = os.environ["SECRET_KEY"]  # must be set in Render env
else:
    # local/dev fallback only
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev_secret_key")

# Cookies that survive Google redirect; HTTPS only on Render
app.config.update(
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',  # 'Lax' is correct for top-level OAuth redirects
    PREFERRED_URL_SCHEME='https',
)

# Trust Render's proxy headers so url_for builds https:// and correct host
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

# (optional) Server-side sessions (recommended if VPN causes random cookie drops)
if HAVE_FLASK_SESSION:
    app.config.update(
        SESSION_TYPE=os.environ.get("SESSION_TYPE", "filesystem"),
        SESSION_PERMANENT=False,
    )
    Session(app)

# --- Toggle this for mock login ---
MOCK_MODE = True

oauth = OAuth(app)
google = oauth.register(
    name='google',
    client_id=os.environ.get("GOOGLE_CLIENT_ID"),
    client_secret=os.environ.get("GOOGLE_CLIENT_SECRET"),
    api_base_url='https://www.googleapis.com/oauth2/v2/',
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'}
)

@app.context_processor
def inject_user():
    return dict(user=session.get("user"))

# --- Routes ---
@app.route("/")
def homepage():
    return render_template("index.html", year=datetime.now().year)

@app.route("/fund")
def fund():
    return render_template("fund.html", year=datetime.now().year)

@app.route("/client-portal")
def client_portal():
    if not session.get("user"):
        return redirect(url_for("login", next="client_portal"))
    selected_year = (request.args.get("year") or "").strip() or None  # 👈 NEW
    investor_email = session["user"].get("email")

    try:
        json_path = os.path.join(BASE_DIR, "static", "investors.json")
        with open(json_path, "r", encoding="utf-8") as f:
            investors = json.load(f)
    except FileNotFoundError:
        investors = {}

    investor_info = investors.get(investor_email, {})

    # Fallbacks
    investor_name = investor_info.get("name", session["user"].get("name", "Investor"))
    performance_file = investor_info.get(
        "performance_file",
        investor_email.replace("@", "-").replace(".", "-") + "-data.csv"
    )
    join_date = investor_info.get("join_date", None)
    currency = investor_info.get("currency", "USD")

    try:
        metrics = performance_metrics(investor_email, "static/investors.json",year=selected_year)
    except Exception as e:
        print("⚠️ Metrics calculation failed:", e)
        metrics = {
            "portfolio_value_nav": None,
            "management_fees_total": None,
            "performance_fees_total": None,
            "irr": None,
            "ytd_return": None,
            "locked_in_return": None
        }

    return render_template(
        "client_portal.html",
        year=datetime.now().year,
        investor_email=investor_email,
        investor_name=investor_name,
        performance_file=performance_file,
        join_date=join_date,
        selected_year=selected_year,
        currency=currency,
        metrics=metrics,
        cf_data=metrics.get("cashflow_chart")
    )

@app.route("/login")
def login():
    next_page = request.args.get("next", "homepage")
    session["next_page"] = next_page

    if MOCK_MODE:
        session["user"] = {
            "name": "Test Investor",
            "email": "sajjadnoun@gmail.com",
            "picture": "https://via.placeholder.com/150"
        }
        return redirect(url_for(next_page))
    else:
        # Build an HTTPS redirect_uri on the current host
        redirect_uri = url_for('authorize', _external=True, _scheme='https')
        return google.authorize_redirect(redirect_uri)

@app.route("/authorize")
def authorize():
    # Graceful auto-retry if state/cookie got dropped (VPN, double-click, etc.)
    try:
        token = google.authorize_access_token()
    except Exception as e:
        print("⚠️ authorize_access_token failed:", repr(e))
        return redirect(url_for('login'))
    resp = google.get('userinfo')
    user_info = resp.json()
    session['user'] = user_info
    next_page = session.pop("next_page", "homepage")
    return redirect(url_for(next_page))

@app.route("/logout")
def logout():
    session.pop('user', None)
    return redirect(url_for("homepage"))

def _clean_for_json(obj, path="root"):
    if isinstance(obj, dict):
        return {k: _clean_for_json(v, f"{path}.{k}") for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_clean_for_json(x, f"{path}[{i}]") for i, x in enumerate(obj)]
    elif isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        print(f"⚠️ Found invalid float at {path}: {obj}, replacing with None")
        return None
    elif isinstance(obj, (np.floating, np.integer)) and (np.isnan(obj) or np.isinf(obj)):
        print(f"⚠️ Found invalid numpy value at {path}: {obj}, replacing with None")
        return None
    return obj

@app.get("/api/fund-series")
def api_fund_series():
    if not session.get("user"):
        return jsonify({"error": "unauthorized"}), 401

    investor_email = session["user"].get("email")
    json_path = os.path.join(BASE_DIR, "static", "investors.json")
    with open(json_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    inv = cfg.get(investor_email, {})

    # 👇 NEW: pick year-specific link if provided (e.g., "2024-Link"), else fallback to "link" or local file
    year = (request.args.get("year") or "").strip()
    if year:
        csv_path = inv.get(f"{year}-Link") \
            or inv.get("link") \
            or os.path.join(BASE_DIR, "static", inv.get("performance_file", ""))
    else:
        csv_path = inv.get("link") \
            or os.path.join(BASE_DIR, "static", inv.get("performance_file", ""))

    fees = inv.get("fees", {})
    fixed   = float(fees.get("management_fee", 0.02))
    hurdle  = float(fees.get("hurdle_rate", 0.50))
    perffee = float(fees.get("performance_fee", 0.25))

    start = request.args.get("start") or inv.get("Fiscal_year_start", "2024-10-01")
    end   = request.args.get("end") or datetime.now().strftime("%Y-%m-%d")

    payload = compute_rebased_indices(
        csv_path=csv_path,
        start_date=start,
        end_date=end,
        fixed=fixed,
        hurdle=hurdle,
        perf_fee=perffee
    )
    payload["fiscal_year_start"] = inv.get("Fiscal_year_start")
    return jsonify(_clean_for_json(payload))

@app.get("/api/fund-projection")
def api_fund_projection():
    if not session.get("user"):
        return jsonify({"error": "unauthorized"}), 401

    investor_email = session["user"].get("email")
    year = (request.args.get("year") or "").strip() or None  # 👈 NEW
    json_path = os.path.join(BASE_DIR, "static", "investors.json")
    with open(json_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    inv = cfg.get(investor_email, {})

    fees = inv.get("fees", {})
    fixed   = float(fees.get("management_fee", 0.02))
    hurdle  = float(fees.get("hurdle_rate", 0.50))
    perffee = float(fees.get("performance_fee", 0.25))

    metrics = performance_metrics(investor_email, "static/investors.json", year=year)  # 👈 CHANGED
    current_nav = metrics.get("portfolio_value_nav", 1000.0)
    locked_in_after_fee = metrics.get("locked_in_after_fee", 0.0)

    payload = compute_lockedin_projection(
        current_nav=current_nav,
        locked_in_after_fee=locked_in_after_fee,
        years=1/4
    )
    return jsonify(payload)

@app.get("/api/compensation-chart")
def api_compensation_chart():
    if not session.get("user"):
        return jsonify({"error": "unauthorized"}), 401

    investor_email = session["user"].get("email")
    json_path = os.path.join(BASE_DIR, "static", "investors.json")
    with open(json_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    inv = cfg.get(investor_email, {})

    fees   = inv.get("fees", {})
    hurdle = float(fees.get("hurdle_rate", 0.50))
    mgmt   = float(fees.get("management_fee", 0.02))
    perf   = float(fees.get("performance_fee", 0.25))

    df = compensation_chart_data(hurdle_rate=hurdle, mgmt_fee=mgmt, perf_fee=perf)
    payload = {
        "Ret": (df["Ret"] * 100).tolist(),
        "Investor": (df["Investor"] * 100).tolist(),
        "Fund": (df["Fund"] * 100).tolist()
    }
    return jsonify(payload)

@app.get("/api/public-fund-series")
def api_public_fund_series():
    csv_path = "https://docs.google.com/spreadsheets/d/1-f9vZ7zGOg2vrViKBlxo07AwiYXLhg2rmlowyU7OKBo/gviz/tq?tqx=out:csv&sheet=Inv0"
    start = request.args.get("start") or "2020-10-17"
    end   = request.args.get("end") or datetime.now().strftime("%Y-%m-%d")
    payload = compute_rebased_indices(
        csv_path=csv_path,
        start_date=start,
        end_date=end,
        fixed=0.02,
        hurdle=0.50,
        perf_fee=0.25
    )
    if "series" in payload:
        payload["series_names"] = list(payload["series"].keys())
    return jsonify(_clean_for_json(payload))

@app.get("/api/public-fund-metrics")
def api_public_fund_metrics():
    csv_path = "https://docs.google.com/spreadsheets/d/1-f9vZ7zGOg2vrViKBlxo07AwiYXLhg2rmlowyU7OKBo/gviz/tq?tqx=out:csv&sheet=Inv0"
    try:
        metrics = performance_metric_public(csv_path)
        payload = {
            "ytd_return": metrics.get("ytd_return"),
            "locked_in_return": metrics.get("locked_in_return"),
        }
    except Exception as e:
        print("⚠️ Metrics calculation failed:", e)
        payload = {"ytd_return": None, "locked_in_return": None}
    return jsonify(payload)

@app.get("/api/public-compensation-chart")
def api_public_compensation_chart():
    df = compensation_chart_data(hurdle_rate=0.50, mgmt_fee=0.02, perf_fee=0.25)
    payload = {
        "Ret": (df["Ret"] * 100).tolist(),
        "Investor": (df["Investor"] * 100).tolist(),
        "Fund": (df["Fund"] * 100).tolist()
    }
    return jsonify(payload)


@app.get("/api/docs")
def api_list_docs():
    email = _current_user_email()
    if not email:
        return jsonify({"error": "not_authenticated"}), 401

    root = _user_docs_root(email)
    payload = {}

    for cat_label, subdir in DOC_CATEGORIES.items():
        dir_path = os.path.join(root, subdir)
        # Optionally create empty folders so UI shows "No files yet"
        os.makedirs(dir_path, exist_ok=True)

        files = []
        try:
            for name in os.listdir(dir_path):
                if name.startswith("."):
                    continue
                ext = os.path.splitext(name)[1].lower()
                if ext not in ALLOWED_EXT:
                    continue
                fp = os.path.join(dir_path, name)
                if not os.path.isfile(fp):
                    continue
                st = os.stat(fp)
                files.append({
                    "name": name,
                    "size": st.st_size,
                    "modified": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
                    "url": url_for("serve_user_doc", category=cat_label, filename=name),
                })
        except FileNotFoundError:
            pass

        files.sort(key=lambda x: x["modified"], reverse=True)
        payload[cat_label] = files

    return jsonify(payload)

@app.get("/docs/<category>/<path:filename>")
def serve_user_doc(category, filename):
    email = _current_user_email()
    if not email:
        abort(401)
    if category not in DOC_CATEGORIES:
        abort(404)

    base = os.path.join(_user_docs_root(email), DOC_CATEGORIES[category])
    safe_path = safe_join(base, filename)
    if not safe_path or not os.path.isfile(safe_path):
        abort(404)

    return send_from_directory(base, filename, as_attachment=False)
if __name__ == "__main__":
    app.run(debug=True)
