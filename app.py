from flask import Flask, render_template, request, redirect, url_for, flash, session
import sqlite3
from functools import wraps
from datetime import datetime
import os
import urllib.request
import urllib.parse
import json

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret-key")
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(os.path.dirname(__file__), "data"))
os.makedirs(DATA_DIR, exist_ok=True)
DB = os.path.join(DATA_DIR, "store.db")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")

def db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS registrations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bracelet_number TEXT NOT NULL UNIQUE,
            sender_name TEXT NOT NULL,
            sender_birthdate TEXT NOT NULL,
            recipient_name TEXT NOT NULL,
            recipient_birthdate TEXT NOT NULL,
            phone TEXT NOT NULL,
            delivery TEXT NOT NULL,
            comment TEXT,
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

def send_telegram_notification(registration):
    """Send a registration alert to the store owner's Telegram, if configured."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        app.logger.warning("Telegram notifications are not configured.")
        return False

    message = (
        "💎 Новая регистрация — One & Only Store\n\n"
        f"Номер браслета: {registration['bracelet_number']}\n"
        f"Отправитель: {registration['sender_name']}\n"
        f"Дата рождения отправителя: {registration['sender_birthdate']}\n"
        f"Получатель: {registration['recipient_name']}\n"
        f"Дата рождения получателя: {registration['recipient_birthdate']}\n"
        f"Телефон: {registration['phone']}\n"
        f"Доставка: {registration['delivery']}\n"
        f"Комментарий: {registration['comment'] or '—'}\n"
        f"Дата регистрации: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
    )
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = urllib.parse.urlencode({"chat_id": chat_id, "text": message}).encode("utf-8")
    try:
        req = urllib.request.Request(url, data=payload, method="POST")
        with urllib.request.urlopen(req, timeout=8) as response:
            result = json.loads(response.read().decode("utf-8"))
            return bool(result.get("ok"))
    except Exception:
        app.logger.exception("Could not send Telegram notification")
        return False

def admin_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not session.get("admin"):
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return wrapped

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        data = {
            "bracelet_number": request.form.get("bracelet_number", "").strip(),
            "sender_name": request.form.get("sender_name", "").strip(),
            "sender_birthdate": request.form.get("sender_birthdate", "").strip(),
            "recipient_name": request.form.get("recipient_name", "").strip(),
            "recipient_birthdate": request.form.get("recipient_birthdate", "").strip(),
            "phone": request.form.get("phone", "").strip(),
            "delivery": request.form.get("delivery", "").strip(),
            "comment": request.form.get("comment", "").strip(),
        }

        if not all([data["bracelet_number"], data["sender_name"], data["sender_birthdate"],
                    data["recipient_name"], data["recipient_birthdate"], data["phone"],
                    data["delivery"]]):
            flash("Заполните все обязательные поля.", "error")
            return render_template("register.html", data=data)

        conn = db()
        try:
            conn.execute("""
                INSERT INTO registrations
                (bracelet_number, sender_name, sender_birthdate, recipient_name,
                 recipient_birthdate, phone, delivery, comment, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (*data.values(), datetime.now().strftime("%d.%m.%Y %H:%M")))
            conn.commit()
        except sqlite3.IntegrityError:
            conn.close()
            flash("Этот номер браслета уже зарегистрирован. Повторная регистрация невозможна.", "error")
            return render_template("register.html", data=data)
        finally:
            try:
                conn.close()
            except:
                pass

        # Notification failure must not cancel a valid registration.
        send_telegram_notification(data)
        return render_template("success.html", number=data["bracelet_number"])

    return render_template("register.html", data={})

@app.route("/check/<bracelet_number>")
def check(bracelet_number):
    conn = db()
    row = conn.execute(
        "SELECT id FROM registrations WHERE bracelet_number = ?",
        (bracelet_number.strip(),)
    ).fetchone()
    conn.close()
    return {"registered": bool(row), "bracelet_number": bracelet_number}

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        if request.form.get("password") == ADMIN_PASSWORD:
            session["admin"] = True
            return redirect(url_for("admin"))
        flash("Неверный пароль.", "error")
    return render_template("admin_login.html")

@app.route("/admin/logout")
def admin_logout():
    session.clear()
    return redirect(url_for("index"))

@app.route("/admin")
@admin_required
def admin():
    conn = db()
    rows = conn.execute("SELECT * FROM registrations ORDER BY id DESC").fetchall()
    conn.close()
    return render_template("admin.html", registrations=rows)

@app.route("/admin/delete/<int:registration_id>", methods=["POST"])
@admin_required
def delete_registration(registration_id):
    conn = db()
    conn.execute("DELETE FROM registrations WHERE id = ?", (registration_id,))
    conn.commit()
    conn.close()
    flash("Регистрация удалена.", "success")
    return redirect(url_for("admin"))

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
