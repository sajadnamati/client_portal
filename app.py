import os
from flask import Flask, redirect, url_for, session, render_template, request
from authlib.integrations.flask_client import OAuth
from datetime import datetime
import json
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
        with open("static/investors.json", "r", encoding="utf-8") as f:
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

    return render_template(
        "client_portal.html",
        year=datetime.now().year,
        investor_email=investor_email,
        investor_name=investor_name,
        performance_file=performance_file,
        join_date=join_date,
        currency=currency
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

if __name__ == "__main__":
    app.run(debug=True)
