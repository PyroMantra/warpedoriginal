#!/usr/bin/env python3
import re
from pathlib import Path

APP = Path("app.py")
src = APP.read_text(encoding="utf-8", errors="ignore")

changed = False

def add_imports(s):
    global changed
    needed = [
        ("from flask_socketio import SocketIO, emit", r"flask_socketio\s+import\s+SocketIO\s*,\s*emit"),
        ("import sqlite3", r"^\s*import\s+sqlite3\s*$"),
        ("from datetime import datetime", r"from\s+datetime\s+import\s+datetime"),
        ("from pathlib import Path", r"from\s+pathlib\s+import\s+Path"),
        ("from flask import session, g, request", r"from\s+flask\s+import\s+session\s*,\s*g\s*,\s*request"),
    ]
    for line, pat in needed:
        if not re.search(pat, s, re.M):
            s = line + "\n" + s
            changed = True
    return s

def insert_after_app_creation(s):
    """After the Flask app is created, insert SocketIO init and DB helpers if missing."""
    global changed
    # Try to find `app = Flask(__name__ ... )`
    m = re.search(r'^\s*app\s*=\s*Flask\([^)]*\)\s*$', s, re.M)
    if not m:
        return s  # can't find the anchor safely; skip
    anchor_end = m.end()

    # What to insert (only if not present)
    block = r'''
# ==== Chat storage (SQLite) and Socket.IO ====
CHAT_DB_PATH = Path(__file__).with_name("chat.db")

def _chat_db():
    conn = sqlite3.connect(str(CHAT_DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn

def ensure_chat_schema():
    conn = _chat_db()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS messages(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user TEXT NOT NULL,
                text TEXT NOT NULL,
                ts   TEXT NOT NULL
            );
        """)
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
        # return oldest->newest
        out = [{"user": r["user"], "text": r["text"], "ts": r["ts"]} for r in rows][::-1]
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

# Create schema at startup
ensure_chat_schema()

# Initialize Socket.IO (threading mode is fine; eventlet/gevent optional)
socketio = SocketIO(app, cors_allowed_origins="*")

@socketio.on("connect")
def _on_connect():
    # send last 100 messages only to this client
    emit("chat_history", get_last_messages(100))

@socketio.on("chat_message")
def _on_chat_message(data):
    text = (data or {}).get("text", "").strip()
    if not text:
        return
    # 2k chars max
    if len(text) > 2000:
        text = text[:2000]
    # Try to get a friendly username from session/g; fall back to "Anonymous"
    user = (session.get("display_name")
            or session.get("username")
            or getattr(g, "user_name", None)
            or "Anonymous")
    save_message(user, text)
    # broadcast to everyone
    emit("chat_message", {"user": user, "text": text}, broadcast=True)
# ==== end chat backend ====
'''.strip("\n")

    # Insert only if not already present
    if "socketio = SocketIO(app" not in s and "def get_last_messages(" not in s:
        s = s[:anchor_end] + "\n\n" + block + "\n\n" + s[anchor_end:]
        changed = True
    return s

def swap_app_run(s):
    """Replace app.run(...) with socketio.run(app, ...) if needed."""
    global changed
    if "socketio.run(app" in s:
        return s
    # Common patterns: app.run(), app.run(host="...", port=..., debug=True)
    def repl(m):
        args = (m.group(1) or "").strip()
        if args:
            return f"socketio.run(app, {args})"
        return "socketio.run(app)"
    new_s = re.sub(r'\bapp\.run\s*\(\s*(.*?)\s*\)', repl, s)
    if new_s != s:
        changed = True
    return new_s

src = add_imports(src)
src = insert_after_app_creation(src)
src = swap_app_run(src)

if changed:
    APP.with_suffix(".py.chatbak").write_text(src, encoding="utf-8")
    # We wrote the patched version to the .chatbak; now write to app.py
    Path("app.py").write_text(src, encoding="utf-8")
    print("app.py patched (Socket.IO + history + run).")
else:
    print("No changes needed; backend looked ready.")
