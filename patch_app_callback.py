#!/usr/bin/env python3
import re, shutil, sys, os
from pathlib import Path

ROOT = Path('.').resolve()
app_file = ROOT / 'app.py'
if not app_file.exists():
    print("ERROR: app.py not found in current folder:", ROOT)
    sys.exit(1)

src = app_file.read_text(encoding='utf-8', errors='ignore')
orig = src

# 1) Ensure imports
def ensure_imports(s: str) -> str:
    if 'from functools import wraps' not in s:
        s = s.replace('import os', 'import os\nfrom functools import wraps')
    if 'import re' not in s and re.search(r'\\bre\\.match\\(', s):
        s = s.replace('import os', 'import os\nimport re')
    s = re.sub(
        r'from flask import ([^\\n]+)',
        lambda m: 'from flask import ' + (m.group(1) + ', request' if 'request' not in m.group(1) else m.group(1)),
        s, count=1
    )
    return s

# 2) Canonical google callback (no try/except)
callback_clean = '''@app.route("/auth/google/callback", endpoint="auth_google_callback")
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
'''

def fix_callback(s: str) -> str:
    # Replace any existing callback block with the clean one
    pat = re.compile(r'@app\\.route\\("/auth/google/callback"[^)]*\\)\\s*def\\s+\\w+\\s*\\([\\s\\S]*?(?=\\n@app\\.route|\\nif __name__|$)')
    if pat.search(s):
        s = pat.sub(callback_clean, s)
    else:
        s = s.replace('if __name__ == "__main__":', callback_clean + '\\n\\nif __name__ == "__main__":')
    return s

# 3) Ensure only one logout route
logout_canonical = '''@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))
'''
def fix_logout(s: str) -> str:
    s = re.sub(
        r'@app\\.route\\(["\\\']/logout["\\\'].*?\\)\\s*\\ndef\\s+logout\\([\\s\\S]*?\\n(?=@app\\.route|\\nif __name__|$)',
        '',
        s, flags=re.DOTALL
    )
    if '@app.route("/logout")' not in s:
        s = s.replace('if __name__ == "__main__":', logout_canonical + '\\n\\nif __name__ == "__main__":')
    return s

src = ensure_imports(src)
src = fix_callback(src)
src = fix_logout(src)

if src == orig:
    print("No changes were necessary; your app.py already looked good.")
    sys.exit(0)

# Backup and write
backup = app_file.with_suffix('.py.bak')
shutil.copyfile(app_file, backup)
app_file.write_text(src, encoding='utf-8')
print("Patched app.py successfully.")
print("A backup was saved to:", backup)
