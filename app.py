import os
import re
import sqlite3
import requests
import smtplib
import ssl
from flask import Flask, request, render_template_string
from datetime import datetime

###############################################################################
# CONFIGURATION
###############################################################################
DB_FILE = "email_app.db"

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
SENDER_EMAIL = os.getenv("SENDER_EMAIL")
SENDER_PASSWORD = os.getenv("SENDER_PASSWORD")

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEEPSEEK_MODEL = "google/gemini-2.5-pro-exp-03-25:free"

###############################################################################
# FLASK SETUP
###############################################################################
app = Flask(__name__)

###############################################################################
# DATABASE HELPERS
###############################################################################
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS emails (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recipient TEXT,
            subject TEXT,
            body TEXT,
            status TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

init_db()  # Ensures DB is ready in Render/gunicorn environment

def log_email(recipient, subject, body, status):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO emails (recipient, subject, body, status)
        VALUES (?, ?, ?, ?)
    """, (recipient, subject, body, status))
    conn.commit()
    conn.close()

###############################################################################
# PARSING AI OUTPUT
###############################################################################
def parse_email_output(raw_text):
    cleaned = re.sub(r"\\boxed\{|\{|\}|```python|```", "", raw_text)
    subj_match = re.search(r'subject\s*=\s*"([^"]+)"', cleaned, re.IGNORECASE)
    subject = subj_match.group(1).strip() if subj_match else "Generated Email"
    body_match = re.search(r'body\s*=\s*"""([\s\S]+?)"""', cleaned, re.IGNORECASE)
    body = body_match.group(1).strip() if body_match else cleaned.strip()
    return subject, body

###############################################################################
# AI GENERATION
###############################################################################
def generate_email_content(user_prompt):
    try:
        headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json"
        }
        data = {
            "model": DEEPSEEK_MODEL,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are an AI email generator. When given a prompt, "
                        "write a clear, complete, and professional email body. "
                        "If you also propose a subject, do so in code style with "
                        "subject = \"...\" and body = \"\"\"...\"\"\"."
                    )
                },
                {
                    "role": "user",
                    "content": user_prompt
                }
            ]
        }
        resp = requests.post(f"{OPENROUTER_BASE_URL}/chat/completions", headers=headers, json=data)
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"]
        print("OpenRouter error:", resp.status_code, resp.text)
        return ""
    except Exception as e:
        print("Error generating email content:", e)
        return ""

###############################################################################
# SMTP SENDING
###############################################################################
def send_email_smtp(recipient, subject, body):
    try:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as server:
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            message = f"""From: {SENDER_EMAIL}
To: {recipient}
Subject: {subject}

{body}
"""
            server.sendmail(SENDER_EMAIL, recipient, message)
        return True
    except Exception as e:
        print("Error sending email:", e)
        return False

###############################################################################
# HTML TEMPLATES
###############################################################################

home_template = """
<!DOCTYPE html>
<html>
<head>
  <title>Email Generator</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 1.5rem; }
    h1 { color: #444; }
    label { font-weight: bold; }
    textarea { width: 100%; }
    .container { max-width: 600px; margin: auto; }
    .btn { padding: 0.5rem 1rem; margin: 0.5rem 0; cursor: pointer; }
    .success { color: green; }
    .error { color: red; }
  </style>
</head>
<body>
  <div class="container">
    <h1>OpenRouter + DeepSeek: Email Generator</h1>
    <form method="POST" action="/generate">
      <label for="recipient">Recipient Email:</label><br>
      <input type="email" id="recipient" name="recipient" required><br><br>

      <label for="subject">Subject (optional):</label><br>
      <input type="text" id="subject" name="subject" placeholder="Generated Email"><br><br>

      <label for="prompt">Prompt for AI:</label><br>
      <textarea id="prompt" name="prompt" rows="5" placeholder="Enter instructions..." required></textarea><br><br>

      <button class="btn" type="submit">Generate Email</button>
    </form>
  </div>
</body>
</html>
"""

edit_template = """
<!DOCTYPE html>
<html>
<head>
  <title>Review & Edit Email</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 1.5rem; }
    .container { max-width: 700px; margin: auto; }
    label { font-weight: bold; }
    .btn { padding: 0.5rem 1rem; margin: 0.5rem 0; cursor: pointer; }
    textarea { width: 100%; }
  </style>
</head>
<body>
  <div class="container">
    <h1>Review & Edit Email</h1>
    <form method="POST" action="/send">
      <label for="recipient">Recipient:</label><br>
      <input type="text" id="recipient" name="recipient" value="{{ recipient }}" readonly><br><br>

      <label for="subject">Subject:</label><br>
      <input type="text" id="subject" name="subject" value="{{ subject }}"><br><br>

      <label for="body">Email Body:</label><br>
      <textarea id="body" name="body" rows="10">{{ body }}</textarea><br><br>

      <button class="btn" type="submit">Send Email</button>
    </form>
    <br>
    <a href="/">Go back Home</a>
  </div>
</body>
</html>
"""

sent_template = """
<!DOCTYPE html>
<html>
<head>
  <title>Email Status</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 1.5rem; }
    .container { max-width: 600px; margin: auto; }
    .success { color: green; }
    .error { color: red; }
    .btn { padding: 0.5rem 1rem; margin: 0.5rem 0; cursor: pointer; }
  </style>
</head>
<body>
  <div class="container">
    {% if success %}
      <h1 class="success">{{ message }}</h1>
    {% else %}
      <h1 class="error">{{ message }}</h1>
    {% endif %}
    <p><a href="/">Go back Home</a></p>
  </div>
</body>
</html>
"""

###############################################################################
# FLASK ROUTES
###############################################################################
@app.route("/", methods=["GET"])
def home():
    return render_template_string(home_template)

@app.route("/generate", methods=["POST"])
def generate():
    recipient = request.form.get("recipient", "").strip()
    subject_input = request.form.get("subject", "").strip()
    prompt = request.form.get("prompt", "").strip()

    if not recipient or not prompt:
        return render_template_string(sent_template, success=False, message="Missing recipient or prompt.")

    raw_ai_text = generate_email_content(prompt)
    if not raw_ai_text:
        return render_template_string(sent_template, success=False, message="Failed to generate email content.")

    parsed_subject, parsed_body = parse_email_output(raw_ai_text)
    final_subject = subject_input if subject_input else parsed_subject

    return render_template_string(edit_template, recipient=recipient, subject=final_subject, body=parsed_body)

@app.route("/send", methods=["POST"])
def send():
    recipient = request.form.get("recipient", "").strip()
    subject = request.form.get("subject", "").strip()
    body = request.form.get("body", "").strip()

    if not recipient or not body:
        return render_template_string(sent_template, success=False, message="Missing recipient or body.")

    success = send_email_smtp(recipient, subject, body)
    log_email(recipient, subject, body, "SENT" if success else "FAILED")

    return render_template_string(sent_template, success=success, message="Email sent successfully!" if success else "Failed to send email.")

###############################################################################
# MAIN
###############################################################################
if __name__ == "__main__":
    app.run(debug=True, port=5000)
