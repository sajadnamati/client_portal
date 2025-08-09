your_root_folder/
│
├── webenv/                     # Virtual environment folder
│
└── render/                     # Main project folder (linked to GitHub + Render)
    ├── .git/                   # Git repo for version control + Render deployment
    ├── app.py                  # Flask application
    ├── requirements.txt        # Python dependencies
    │
    ├── static/
    │   └── styles/
    │       └── style.css       # Your custom CSS
    │
    └── templates/
        ├── base.html
        ├── dashboard.html
        ├── index.html
        └── login.html
🔁 NEXT TIME: Restart Guide
🥾 1. Open PowerShell in the render/ folder
Navigate from your root folder:

powershell
Copy
Edit
cd "D:\Sajjad Personal\Backup-Necessary\My Career\Website\render"
🐍 2. Activate the virtual environment
From the parent folder (one level up), run:

powershell
Copy
Edit
cd ..
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\webenv\Scripts\Activate.ps1
You should see something like:

scss
Copy
Edit
(webenv) PS D:\Sajjad...\Website>
Then return into the render folder:

powershell
Copy
Edit
cd render
📦 3. Install dependencies (once)
If Flask isn’t already installed, run:

powershell
Copy
Edit
pip install -r requirements.txt
🚀 4. Run your Flask app
powershell
Copy
Edit
python app.py
Then go to:

cpp
Copy
Edit
http://127.0.0.1:5000/
You can access:

/ → index

/login

/dashboard

🧠 Notes
CSS is in: static/styles/style.css

Link it in base.html like this:

html
Copy
Edit
<link rel="stylesheet" href="{{ url_for('static', filename='styles/style.css') }}">
Your app.py should route to the templates in templates/

Example minimal app.py:

python
Copy
Edit
from flask import Flask, render_template

app = Flask(__name__)

@app.route('/')
def home():
    return render_template("index.html")

@app.route('/login')
def login():
    return render_template("login.html")

@app.route('/dashboard')
def dashboard():
    return render_template("dashboard.html")

if __name__ == '__main__':
    app.run(debug=True)
