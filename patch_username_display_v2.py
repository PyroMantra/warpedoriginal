#!/usr/bin/env python3
import re
from pathlib import Path
from textwrap import dedent

root = Path(".").resolve()
app_path = root / "app.py"
if not app_path.exists():
    raise SystemExit(f"ERROR: app.py not found at {app_path}")

src = app_path.read_text(encoding="utf-8", errors="ignore")

# --- Ensure Flask imports contain session (and request is OK to include) ---
m = re.search(r"from\s+flask\s+import\s+([^\n]+)", src)
if m:
    imports = [p.strip() for p in m.group(1).split(",")]
    changed = False
    if "session" not in imports:
        imports.append("session"); changed = True
    if "request" not in imports:
        imports.append("request"); changed = True
    if changed:
        new_line = "from flask import " + ", ".join(imports)
        src = src.replace(m.group(0), new_line, 1)
else:
    # Add a base import if none exists
    src = "from flask import Flask, render_template, redirect, url_for, session, request\n" + src

# --- Ensure we can use datetime (for any fallback logic you might have) ---
if "from datetime import datetime" not in src:
    src = "from datetime import datetime\n" + src

# --- Insert/replace context processor providing nice display name ---
cp_re = re.compile(r"@app\.context_processor\s*def\s+\w+\s*\([^)]*\):.*?return\s*\{[^\}]*\}[ \t]*\n", re.S)
new_cp = dedent("""
@app.context_processor
def inject_current_user_display():
    # Compute a friendly display name once, expose as multiple aliases
    name = session.get('username')
    if not name:
        email = session.get('email')
        if email:
            name = email.split('@')[0]
    name = name or "Adventurer"
    return {
        "current_user_name": name,   # recommended in templates
        "username": name,            # legacy templates using {{ username }}
        "display_name": name,        # optional alias
    }
""").strip("\n") + "\n"

if cp_re.search(src):
    src = cp_re.sub(new_cp, src, count=1)
else:
    guard = "\nif __name__"
    gpos = src.find(guard)
    src = (src.rstrip() + "\n\n" + new_cp + "\n") if gpos == -1 else (src[:gpos] + new_cp + "\n" + src[gpos:])

# --- Insert before_request to hydrate session['username'] from DB if missing ---
br_re = re.compile(r"@app\.before_request\s*def\s+hydrate_username_in_session\s*\([^)]*\):", re.S)
if not br_re.search(src):
    br_block = dedent("""
    @app.before_request
    def hydrate_username_in_session():
        try:
            if session.get("user_id") and not session.get("username"):
                conn = get_db()
                cur = conn.cursor()
                cur.execute("SELECT username, email FROM users WHERE id = ?", (session["user_id"],))
                u = cur.fetchone()
                conn.close()
                if u:
                    if u.get("username"):
                        session["username"] = u["username"]
                    elif u.get("email") and not session.get("email"):
                        session["email"] = u["email"]
        except Exception:
            # Never block a request on a best-effort hydration
            pass
    """).strip("\n") + "\n"
    guard = "\nif __name__"
    gpos = src.find(guard)
    src = (src.rstrip() + "\n\n" + br_block + "\n") if gpos == -1 else (src[:gpos] + br_block + "\n" + src[gpos:])

# Save app.py backup + write
app_path.with_suffix(".py.bak_namepatch").write_text(app_path.read_text(encoding="utf-8", errors="ignore"), encoding="utf-8")
app_path.write_text(src, encoding="utf-8")

# --- Update templates that say 'Welcome, None' or variants to {{ current_user_name }} ---
tpl_dir = root / "templates"
changed = []
if tpl_dir.exists():
    for html in tpl_dir.rglob("*.html"):
        text = html.read_text(encoding="utf-8", errors="ignore")
        orig = text
        lines = text.splitlines()
        new = []
        for line in lines:
            # Only modify lines that contain some form of "Welcome"
            if re.search(r"\bWelcome\b", line, flags=re.I):
                # Replace literal None after Welcome,
                line = re.sub(r"(Welcome\s*,\s*)(None|\{\{\s*None\s*\}\})", r"\\1{{ current_user_name }}", line, flags=re.I)
                # Replace common session username references on Welcome lines
                line = re.sub(r"\{\{\s*session\.get\(\s*['\"]username['\"]\s*\)\s*\}\}", "{{ current_user_name }}", line)
                line = re.sub(r"\{\{\s*session\.username\s*\}\}", "{{ current_user_name }}", line)
                line = re.sub(r"\{\{\s*user\.username\s*\}\}", "{{ current_user_name }}", line)
                # If someone wrote just {{ username }} on the welcome line, keep it mapped
                line = re.sub(r"\{\{\s*username\s*\}\}", "{{ current_user_name }}", line)
            new.append(line)
        new_text = "\n".join(new)
        if new_text != orig:
            html.with_suffix(".html.bak_namepatch").write_text(orig, encoding="utf-8")
            html.write_text(new_text, encoding="utf-8")
            changed.append(str(html.relative_to(root)))

print("Patched app.py (context processor + before_request).")
if changed:
    print("Updated templates:")
    for c in changed:
        print(" -", c)
else:
    print("No template lines required changes (may already be using current_user_name).")
