#!/usr/bin/env python3
import re
from pathlib import Path
from textwrap import dedent

root = Path(".").resolve()
app_path = root / "app.py"
if not app_path.exists():
    raise SystemExit(f"ERROR: app.py not found at {app_path}")

src = app_path.read_text(encoding="utf-8", errors="ignore")

# --- Ensure Flask imports contain session & request ---
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
    src = "from flask import Flask, render_template, redirect, url_for, session, request\n" + src

# --- Ensure datetime (harmless if unused) ---
if "from datetime import datetime" not in src:
    src = "from datetime import datetime\n" + src

# --- Inject/replace a context processor that exposes a friendly name ---
cp_re = re.compile(r"@app\.context_processor\s*def\s+\w+\s*\([^)]*\):.*?return\s*\{[^\}]*\}[ \t]*\n", re.S)
new_cp = dedent("""
@app.context_processor
def inject_current_user_display():
    # Resolve a nice display name
    name = session.get('username')
    if not name:
        email = session.get('email')
        if email:
            name = email.split('@')[0]
    name = name or "Adventurer"
    return {
        "current_user_name": name,   # preferred
        "username": name,            # legacy alias
        "display_name": name,        # optional alias
    }
""").strip("\n") + "\n"

if cp_re.search(src):
    src = cp_re.sub(new_cp, src, count=1)
else:
    guard = "\nif __name__"
    gpos = src.find(guard)
    src = (src.rstrip() + "\n\n" + new_cp + "\n") if gpos == -1 else (src[:gpos] + new_cp + "\n" + src[gpos:])

# --- Add a before_request that hydrates session['username'] from DB if missing ---
br_re = re.compile(r"@app\.before_request\s*def\s+hydrate_username_in_session\s*\(", re.S)
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
            # best-effort; don't block request on failure
            pass
    """).strip("\n") + "\n"
    guard = "\nif __name__"
    gpos = src.find(guard)
    src = (src.rstrip() + "\n\n" + br_block + "\n") if gpos == -1 else (src[:gpos] + br_block + "\n" + src[gpos:])

# Save backup and write app.py
app_path.with_suffix(".py.bak_name_ui").write_text(app_path.read_text(encoding="utf-8", errors="ignore"), encoding="utf-8")
app_path.write_text(src, encoding="utf-8")

# --- Patch templates ---
tpl_dir = root / "templates"
changed_files = []
removed_brands = []

if tpl_dir.exists():
    for html in tpl_dir.rglob("*.html"):
        text = html.read_text(encoding="utf-8", errors="ignore")
        original = text

        # 1) Fix "Welcome, None" or "Welcome, {{ ... }}"
        #    Replace any Welcome line variants with current_user_name
        def fix_welcome_line(line: str) -> str:
            if re.search(r"\bWelcome\b", line, flags=re.I):
                # Welcome, None (literal or templated)
                line = re.sub(r"(Welcome\s*,\s*)(?:None|\{\{\s*None\s*\}\})", r"\\1{{ current_user_name }}", line, flags=re.I)
                # Welcome, {{ anything }}
                line = re.sub(r"(Welcome\s*,\s*)\{\{[^}]+\}\}", r"\\1{{ current_user_name }}", line)
                # Common username expressions on welcome line
                line = re.sub(r"\{\{\s*session\.get\(\s*['\"]username['\"]\s*\)\s*\}\}", "{{ current_user_name }}", line)
                line = re.sub(r"\{\{\s*session\.username\s*\}\}", "{{ current_user_name }}", line)
                line = re.sub(r"\{\{\s*user\.username\s*\}\}", "{{ current_user_name }}", line)
                line = re.sub(r"\{\{\s*username\s*\}\}", "{{ current_user_name }}", line)
            return line

        lines = text.splitlines()
        lines = [fix_welcome_line(ln) for ln in lines]
        text = "\n".join(lines)

        # 2) Remove duplicate "Across the Planes" brand anchors (keep first)
        #    Only removes link anchors (<a ...>Across the Planes</a>), not <title> tags.
        pattern_anchor = re.compile(r"<a\b[^>]*>\s*Across the Planes\s*</a>", re.I)
        found = list(pattern_anchor.finditer(text))
        if len(found) > 1:
            # Keep the first, remove the rest
            spans = [m.span() for m in found[1:]]
            # Remove from end to start to keep indices valid
            for s, e in reversed(spans):
                text = text[:s] + "" + text[e:]
            removed_brands.append(str(html.relative_to(root)))

        if text != original:
            html.with_suffix(".html.bak_name_ui").write_text(original, encoding="utf-8")
            html.write_text(text, encoding="utf-8")
            changed_files.append(str(html.relative_to(root)))

print("Patched app.py (context processor + before_request).")
if changed_files:
    print("Updated templates (welcome/brand):")
    for c in changed_files:
        print(" -", c)
if removed_brands:
    print("Removed duplicate brand anchors in:")
    for c in removed_brands:
        print(" -", c)
