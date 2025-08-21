#!/usr/bin/env python3
import re
from pathlib import Path
from textwrap import dedent

root = Path(".").resolve()
app_path = root / "app.py"
if not app_path.exists():
    raise SystemExit(f"ERROR: app.py not found at {app_path}")

src = app_path.read_text(encoding="utf-8", errors="ignore")

# --- Ensure Flask import contains session ---
m = re.search(r"from\s+flask\s+import\s+([^\n]+)", src)
if m:
    imports = [p.strip() for p in m.group(1).split(",")]
    if "session" not in imports:
        new_imports = m.group(1) + ", session"
        src = src.replace(m.group(0), f"from flask import {new_imports}", 1)
else:
    # Add a base import if none exists (very unlikely in your app)
    src = "from flask import Flask, render_template, redirect, url_for, session, request\n" + src

# --- Inject context processor if missing ---
cp_pat = re.compile(r"@app\.context_processor\s*def\s+inject_current_user_name\s*\(", re.S)
if not cp_pat.search(src):
    block = dedent("""
    @app.context_processor
    def inject_current_user_name():
        name = session.get('username')
        if not name:
            email = session.get('email')
            if email:
                name = email.split('@')[0]
        return {"current_user_name": name or "Adventurer"}
    """).strip("\n") + "\n"
    guard = "\nif __name__"
    gpos = src.find(guard)
    if gpos == -1:
        src = src.rstrip() + "\n\n" + block + "\n"
    else:
        src = src[:gpos] + block + "\n" + src[gpos:]

# Write backup and update app.py
app_path.with_suffix(".py.bak_welcome").write_text(app_path.read_text(encoding="utf-8", errors="ignore"), encoding="utf-8")
app_path.write_text(src, encoding="utf-8")

# --- Update templates to use {{ current_user_name }} on 'Welcome,' lines ---
tpl_dir = root / "templates"
changed = []
if tpl_dir.exists():
    for html in tpl_dir.rglob("*.html"):
        text = html.read_text(encoding="utf-8", errors="ignore")
        orig = text
        new_lines = []
        for line in text.splitlines():
            if "Welcome" in line or "welcome" in line:
                # Replace "Welcome, None" directly
                line = re.sub(r"(Welcome,\s*)None", r"\1{{ current_user_name }}", line, flags=re.I)

                # Replace welcome-line username variables with current_user_name
                line = re.sub(r"\{\{\s*session\.get\(\s*['\"]username['\"]\s*\)\s*\}\}", "{{ current_user_name }}", line)
                line = re.sub(r"\{\{\s*session\.username\s*\}\}", "{{ current_user_name }}", line)
                # Very safe: only if line contains 'Welcome', replace a bare {{ username }} with current_user_name
                line = re.sub(r"\{\{\s*username\s*\}\}", "{{ current_user_name }}", line)

            new_lines.append(line)
        new_text = "\n".join(new_lines)
        if new_text != orig:
            html.with_suffix(".html.bak_welcome").write_text(orig, encoding="utf-8")
            html.write_text(new_text, encoding="utf-8")
            changed.append(str(html.relative_to(root)))

print("Patched app.py (context processor injected).")
if changed:
    print("Updated templates:")
    for c in changed:
        print(" -", c)
else:
    print("No template changes detected (maybe already good).")
