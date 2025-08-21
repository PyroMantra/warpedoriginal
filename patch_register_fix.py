#!/usr/bin/env python3
import re
from pathlib import Path
from textwrap import dedent

APP = Path("app.py")
src = APP.read_text(encoding="utf-8", errors="ignore")

# Ensure imports
def ensure_line(s, needle, add):
    return s if needle in s else add + ("\n" if not add.endswith("\n") else "") + s

if "from werkzeug.security import generate_password_hash" not in src:
    src = ensure_line(src, "from werkzeug.security import generate_password_hash", 
                      "from werkzeug.security import generate_password_hash, check_password_hash")
if "from datetime import datetime" not in src:
    src = ensure_line(src, "from datetime import datetime", "from datetime import datetime")
if "from flask import " in src and " request" not in src.split("from flask import ",1)[1]:
    src = re.sub(r"from flask import ([^\n]+)", r"from flask import \1, request", src, count=1)

# Replace the /register route function
pattern = re.compile(
    r'@app\.route\(["\']/register["\'].*?\)\s*def\s+register\([^)]*\):.*?(?=\n@app\.route\(|\nif __name__|$)',
    re.S
)
new_block = dedent(r"""
@app.route("/register", methods=["GET", "POST"], endpoint="register")
def register():
    if session.get("user_id"):
        return redirect(url_for("home"))

    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""

        if not email or not username or not password:
            return render_template("register.html", error="Email, username and password are required.")

        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM users WHERE email = ? OR username = ?", (email, username))
        exists = cur.fetchone()
        if exists:
            conn.close()
            return render_template("register.html", error="Email or username already exists.")

        pw_hash = generate_password_hash(password)

        cur.execute(
            "INSERT INTO users (email, username, password_hash, created_at) VALUES (?, ?, ?, ?)",
            (email, username, pw_hash, datetime.utcnow().isoformat()),
        )
        conn.commit()
        user_id = cur.lastrowid
        conn.close()

        session["user_id"] = user_id
        session["email"] = email
        session["username"] = username

        return redirect(url_for("home"))

    return render_template("register.html")
""").strip("\n") + "\n"

if pattern.search(src):
    src = pattern.sub(new_block, src)
else:
    # Append before __main__
    guard = "\nif __name__"
    gpos = src.find(guard)
    if gpos == -1:
        src = src.rstrip() + "\n\n" + new_block + "\n"
    else:
        src = src[:gpos] + new_block + "\n\n" + src[gpos:]

APP.write_text(src, encoding="utf-8")
print("Register route patched.")
