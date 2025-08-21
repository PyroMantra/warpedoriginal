#!/usr/bin/env python3
from pathlib import Path

ROOT = Path('.').resolve()
app_path = ROOT / 'app.py'
if not app_path.exists():
    print("ERROR: app.py not found in", ROOT)
    raise SystemExit(1)

src = app_path.read_text(encoding='utf-8', errors='ignore')

start_marker = '@app.route("/auth/google/callback"'
alt_marker   = "@app.route('/auth/google/callback'"
def_marker   = 'def '
next_route_marker = '\n@app.route('
main_marker = '\nif __name__'

# locate start
start = src.find(start_marker)
if start == -1:
    start = src.find(alt_marker)
if start == -1:
    print("Callback route not found. Nothing changed.")
    raise SystemExit(0)

# find the start of the def line after the route decorator
def_idx = src.find('\n', start)
if def_idx == -1:
    print("Malformed route decorator line; aborting.")
    raise SystemExit(1)

# find the end: next @app.route or if __name__
nr = src.find(next_route_marker, def_idx)
nm = src.find(main_marker, def_idx)
candidates = [i for i in [nr, nm] if i != -1]
end = min(candidates) if candidates else len(src)

clean_block = """@app.route("/auth/google/callback", endpoint="auth_google_callback")
def google_login_callback():
    token = google.authorize_access_token()
    resp = google.get("https://openidconnect.googleapis.com/v1/userinfo")
    info = resp.json()

    email = (info.get("email") or "").lower()
    sub = info.get("sub")

    if not email or not sub:
        return redirect(url_for("login"))

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE email = ?", (email,))
    u = cur.fetchone()

    if u:
        if not u["google_id"]:
            cur.execute("UPDATE users SET google_id = ? WHERE id = ?", (sub, u["id"]))
            conn.commit()
        user_id = u["id"]
        username = u["username"]
    else:
        cur.execute(
            "INSERT INTO users (email, google_id, created_at) VALUES (?, ?, ?)",
            (email, sub, datetime.utcnow().isoformat())
        )
        conn.commit()
        user_id = cur.lastrowid
        username = None

    conn.close()

    session["user_id"] = user_id
    session["email"] = email
    session["username"] = username

    if not username:
        return redirect(url_for("pick_username"))
    return redirect(url_for("home"))
"""

new_src = src[:start] + clean_block + src[end:]

# Ensure single /logout
if '@app.route("/logout")' in new_src:
    # Remove duplicates by keeping the first occurrence only
    first = new_src.find('@app.route("/logout")')
    second = new_src.find('@app.route("/logout")', first + 1)
    while second != -1:
        # Remove the duplicate function starting at 'second' up to next route or __main__
        dup_def = new_src.find('\n', second)
        next_r = new_src.find('\n@app.route(', dup_def)
        next_m = new_src.find('\nif __name__', dup_def)
        candidates = [i for i in [next_r, next_m] if i != -1]
        end_dup = min(candidates) if candidates else len(new_src)
        new_src = new_src[:second] + new_src[end_dup:]
        second = new_src.find('@app.route("/logout")', first + 1)

# Ensure imports (minimal)
if "from functools import wraps" not in new_src:
    new_src = new_src.replace("import os", "import os\nfrom functools import wraps")
if "import re" not in new_src and "re.match(" in new_src:
    new_src = new_src.replace("import os", "import os\nimport re")
if "from flask import " in new_src and "request" not in new_src.split("from flask import ",1)[1]:
    new_src = new_src.replace("from flask import ", "from flask import ").replace(
        "Flask, render_template, redirect, url_for, session",
        "Flask, render_template, redirect, url_for, session, request"
    )

# Write backup and save
backup = app_path.with_suffix('.py.bak2')
app_path.write_text(new_src, encoding='utf-8')
print("Patched app.py successfully.")
print("Backup saved to:", backup)
backup.write_text(src, encoding='utf-8')
