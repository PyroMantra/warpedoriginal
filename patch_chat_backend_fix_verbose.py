#!/usr/bin/env python3
import re
from pathlib import Path

app_py = Path("app.py")
src = app_py.read_text(encoding="utf-8", errors="ignore")
orig = src
changed = False

def ensure_import(line, rx):
    global src, changed
    if not re.search(rx, src, re.M):
        src = line + "\n" + src
        changed = True

# Make sure we have the imports we need
ensure_import("from flask_socketio import SocketIO, emit", r"flask_socketio\s+import\s+SocketIO\s*,\s*emit")
ensure_import("import sqlite3", r"^\s*import\s+sqlite3\s*$")
ensure_import("from datetime import datetime", r"from\s+datetime\s+import\s+datetime")
ensure_import("from pathlib import Path", r"from\s+pathlib\s+import\s+Path")
ensure_import("from flask import session, g, request", r"from\s+flask\s+import\s+session\s*,\s*g\s*,\s*request")

# Insert/replace a clearly marked backend block
BEGIN = "# ==== CHAT BACKEND START (AUTOPATCH) ===="
END   = "# ==== CHAT BACKEND END (AUTOPATCH) ===="
block = f"""{BEGIN}
# noisy backend so we can see what's going on
print("[chat] backend loaded")

CHAT_DB_PATH = Path(__file__).with_name("chat.db")

def _chat_db():
    conn = sqlite3.connect(str(CHAT_DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn

def ensure_chat_schema():
    conn = _chat_db()
    try:
        conn.execute(\"\"\"
            CREATE TABLE IF NOT EXISTS messages(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user TEXT NOT NULL,
                text TEXT NOT NULL,
                ts   TEXT NOT NULL
            );
        \"\"\")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_ts ON messages(ts);")
        conn.commit()
    finally:
        conn.close()

def get_last_messages(limit=100):
    conn = _chat_db()
    try:
        cur = conn.execute(
            "SELECT user, text, ts FROM messages ORDER BY id DESC LIMIT ?;", (limit,)
        )
        rows = cur.fetchall()
        out = [{{"user": r["user"], "text": r["text"], "ts": r["ts"]}} for r in rows][::-1]
        return out
    finally:
        conn.close()

def save_message(user, text):
    conn = _chat_db()
    try:
        conn.execute(
            "INSERT INTO messages(user, text, ts) VALUES(?,?,?);",
            (user, text, datetime.utcnow().isoformat(timespec="seconds")+"Z"),
        )
        conn.commit()
    finally:
        conn.close()

ensure_chat_schema()

# Reuse a prior socketio instance if one exists; otherwise create one (with logs)
socketio = globals().get("socketio") or SocketIO(app, cors_allowed_origins="*", logger=True, engineio_logger=True)

@socketio.on("connect")
def _chat_on_connect():
    try:
        print("[chat] connect:", request.sid)
    except Exception as e:
        print("[chat] connect (no sid):", e)
    emit("chat_history", get_last_messages(100))

@socketio.on("chat_message")
def _chat_on_message(data):
    text = (data or {{}}).get("text", "").strip()
    if not text:
        return {{"ok": False}}
    if len(text) > 2000:
        text = text[:2000]
    user = (session.get("display_name") or session.get("username")
            or getattr(g, "user_name", None) or "Anonymous")
    print(f"[chat] msg from {{user}}:", text)
    try:
        save_message(user, text)
    except Exception as e:
        print("[chat] save error:", e)
    # broadcast back out to everyone (including sender)
    emit("chat_message", {{"user": user, "text": text}}, broadcast=True)
    return {{"ok": True}}

print("[chat] backend ready")
{END}
"""

if BEGIN in src and END in src:
    # Replace the whole block so it's always current
    src = re.sub(rf"{re.escape(BEGIN)}[\\s\\S]*?{re.escape(END)}", block, src, count=1, flags=re.M)
    changed = True
else:
    # Find app = Flask(...) and insert block immediately after
    m = re.search(r"^\\s*app\\s*=\\s*Flask\\([^\\)]*\\)\\s*$", src, re.M)
    if m:
        pos = m.end()
        src = src[:pos] + "\\n\\n" + block + "\\n\\n" + src[pos:]
        changed = True
    else:
        print("WARNING: Could not find `app = Flask(...)` to anchor the chat block. Skipping block insert.")

# Force socketio.run(app, ...) at the end
def swap_run(s):
    if "socketio.run(app" in s:
        return s
    def repl(m):
        args = (m.group(1) or "").strip()
        if args:
            return f"socketio.run(app, {args}, allow_unsafe_werkzeug=True)"
        return "socketio.run(app, allow_unsafe_werkzeug=True)"
    return re.sub(r"\\bapp\\.run\\s*\\(\\s*(.*?)\\s*\\)", repl, s)

new_src = swap_run(src)
if new_src != src:
    src = new_src
    changed = True

if changed:
    app_py.with_suffix(".py.chatfixbak").write_text(orig, encoding="utf-8")
    app_py.write_text(src, encoding="utf-8")
    print("app.py updated (backend wired, history + broadcast + logs).")
else:
    print("No backend changes were necessary.")
