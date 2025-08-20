import os
from flask import Flask, redirect, url_for, session, render_template, request
from authlib.integrations.flask_client import OAuth
from datetime import datetime
from analysis_functions import performance_metrics
import json
from flask import jsonify, request
from analysis_functions import compute_rebased_indices  # import the function above
import numpy as np
import math
from analysis_functions import compute_lockedin_projection
import pandas as pd
from analysis_functions import compensation_chart_data
from analysis_functions import performance_metric_public

# Base directory = the folder where app.py is located
BASE_DIR = os.path.abspath(os.path.dirname(__file__))

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev_secret_key")  # fallback for local

# --- Toggle this for mock login ---
MOCK_MODE = True  # True for local testing without Google OAuth

oauth = OAuth(app)
google = oauth.register(
    name='google',
    client_id=os.environ.get("GOOGLE_CLIENT_ID"),
    client_secret=os.environ.get("GOOGLE_CLIENT_SECRET"),
    api_base_url='https://www.googleapis.com/oauth2/v2/',
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'}    
)

# --- Context processor: make 'user' available in all templates ---
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
    # If not logged in, go to login and then return here
    if not session.get("user"):
        return redirect(url_for("login", next="client_portal"))
    
    # Extract the email from the session (assuming your login sets it there)
    investor_email = session["user"].get("email")

    # Load investor metadata from JSON
    try:
        json_path = os.path.join(BASE_DIR, "static", "investors.json")
        with open(json_path, "r", encoding="utf-8") as f:
            investors = json.load(f)
    except FileNotFoundError:
        investors = {}

    # Look up current investor in the mapping
    investor_info = investors.get(investor_email, {})

    # Fallback values in case JSON is missing entries
    investor_name = investor_info.get("name", session["user"].get("name", "Investor"))
    performance_file = investor_info.get(
        "performance_file",
        investor_email.replace("@", "-").replace(".", "-") + "-data.csv"
    )
    join_date = investor_info.get("join_date", None)
    currency = investor_info.get("currency", "USD")

     # Compute performance metrics for this investor
    try:
        metrics = performance_metrics(investor_email, "static/investors.json")
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
        currency=currency,
        metrics=metrics,
        cf_data=metrics.get("cashflow_chart")
        
    )


@app.route("/login")
def login():
    # Store where the user was trying to go
    next_page = request.args.get("next", "homepage")
    session["next_page"] = next_page
    
    if MOCK_MODE:
        # Mock login for local testing
        session["user"] = {
            "name": "Test Investor",
            "email": "investor@example.com",
            "picture": "https://via.placeholder.com/150"
        }
        return redirect(url_for(next_page))
    else:
        redirect_uri = url_for('authorize', _external=True)
        return google.authorize_redirect(redirect_uri)

@app.route("/authorize")
def authorize():
    token = google.authorize_access_token()
    resp = google.get('userinfo')
    user_info = resp.json()
    session['user'] = user_info

    # After login, go to the page user intended
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
    # locate the investor CSV + fee params from your existing JSON map
    json_path = os.path.join(BASE_DIR, "static", "investors.json")
    with open(json_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    inv = cfg.get(investor_email, {})
    csv_path = os.path.join(BASE_DIR, "static", inv.get("performance_file", ""))

    fees = inv.get("fees", {})
    fixed   = float(fees.get("management_fee", 0.02))
    hurdle  = float(fees.get("hurdle_rate", 0.50))
    perffee = float(fees.get("performance_fee", 0.25))

    start = request.args.get("start")
    end   = request.args.get("end")

    # Default handling if missing
    if not start:
        start = inv.get("Fiscal_year_start", "2024-10-01")
        print (start)
    if not end:
        end = datetime.now().strftime("%Y-%m-%d")

    payload = compute_rebased_indices(
        csv_path=csv_path,
        start_date=start,
        end_date=end,
        fixed=fixed,
        hurdle=hurdle,
        perf_fee=perffee
    )

    # attach fiscal year start into payload
    # attach fiscal year start into payload
    payload["fiscal_year_start"] = inv.get("Fiscal_year_start")
    cleaned = _clean_for_json(payload)
    print("✅ Cleaned payload sample:", str(cleaned)[:300])  # show first 300 chars

    return jsonify(payload)


@app.get("/api/fund-projection")
def api_fund_projection():
    if not session.get("user"):
        return jsonify({"error": "unauthorized"}), 401

    investor_email = session["user"].get("email")
    json_path = os.path.join(BASE_DIR, "static", "investors.json")
    with open(json_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    inv = cfg.get(investor_email, {})

    fees = inv.get("fees", {})
    fixed   = float(fees.get("management_fee", 0.02))
    hurdle  = float(fees.get("hurdle_rate", 0.50))
    perffee = float(fees.get("performance_fee", 0.25))

    # current NAV + locked-in return from metrics
    metrics = performance_metrics(investor_email, "static/investors.json")
    current_nav = metrics.get("portfolio_value_nav", 1000.0)  # fallback
    locked_in_after_fee = metrics.get("locked_in_after_fee", 0.0)      # already annualized

    # new simpler projection
    payload = compute_lockedin_projection(
        current_nav=current_nav,
        locked_in_after_fee=locked_in_after_fee,
        years=1/4   # or however many years you want
    )

    return jsonify(payload)



@app.get("/api/compensation-chart")
def api_compensation_chart():
    if not session.get("user"):
        return jsonify({"error": "unauthorized"}), 401

    investor_email = session["user"].get("email")

    # 🔹 Load this investor’s fee parameters
    json_path = os.path.join(BASE_DIR, "static", "investors.json")
    with open(json_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    inv = cfg.get(investor_email, {})

    fees   = inv.get("fees", {})
    hurdle = float(fees.get("hurdle_rate", 0.50))    # fallback 50%
    mgmt   = float(fees.get("management_fee", 0.02)) # fallback 2%
    perf   = float(fees.get("performance_fee", 0.25))# fallback 25%

    # 🔹 Compute series in Python
    df = compensation_chart_data(
        hurdle_rate=hurdle,
        mgmt_fee=mgmt,
        perf_fee=perf
    )

    # 🔹 Convert decimals → percent
    payload = {
        "Ret": (df["Ret"] * 100).tolist(),
        "Investor": (df["Investor"] * 100).tolist(),
        "Fund": (df["Fund"] * 100).tolist()
    }
    return jsonify(payload)


@app.get("/api/public-fund-series")
def api_public_fund_series():
    csv_path = os.path.join(BASE_DIR, "static", "fund-data.csv")
    print("📂 Using CSV path:", csv_path)

    start = request.args.get("start")
    end   = request.args.get("end")
    print("📅 Query args:", start, end)

    if not start:
        start = "2020-10-17"
    if not end:
        end = datetime.now().strftime("%Y-%m-%d")

    payload = compute_rebased_indices(
        csv_path=csv_path,
        start_date=start,
        end_date=end,
        fixed=0.02,    # or whatever your defaults are
        hurdle=0.50,
        perf_fee=0.25
    )

    print("✅ Payload keys:", payload.keys())
    print("📊 Dates count:", len(payload.get("dates", [])))
    if "series" in payload:
        for k, v in payload["series"].items():
            print(f"  Series {k}: {len(v)} points")
        payload["series_names"] = list(payload["series"].keys())  # <-- add this
    return jsonify(_clean_for_json(payload))


@app.get("/api/public-fund-metrics")
def api_public_fund_metrics():
    csv_path = os.path.join(BASE_DIR, "static", "fund-data.csv")
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
    # Default fee parameters (public info)
    hurdle = 0.50    # 50% hurdle
    mgmt   = 0.02    # 2% mgmt fee
    perf   = 0.25    # 25% perf fee

    df = compensation_chart_data(
        hurdle_rate=hurdle,
        mgmt_fee=mgmt,
        perf_fee=perf
    )

    payload = {
        "Ret": (df["Ret"] * 100).tolist(),
        "Investor": (df["Investor"] * 100).tolist(),
        "Fund": (df["Fund"] * 100).tolist()
    }
    return jsonify(payload)









if __name__ == "__main__":
    app.run(debug=True)

