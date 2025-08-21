#!/usr/bin/env python3
import re
from pathlib import Path

p = Path("app.py")
s = p.read_text(encoding="utf-8", errors="ignore")
orig = s
changed = False

def ensure(line, rx):
    global s, changed
    if not re.search(rx, s, re.M):
        s = line + "\n" + s
        changed = True

ensure("from flask_socketio import SocketIO, emit", r"flask_socketio\s+import\s+SocketIO\s*,\s*emit")
ensure("import sqlite3", r"^\s*import\s+sqlite3\s*$")
ensure("from datetime import datetime", r"from\s+datetime\s+import\s+datetime")
ensure("from pathlib import Path", r"from\s+pathlib\s+import\s+Path")
ensure("from flask import session, g, request", r"from\s+flask\s+import\s+session\s*,\s*g\s*,\s*request")

BEGIN = "# ==== CHAT BACKEND START (AUTOPATCH) ===="
END   = "# ==== CHAT BACKEND END (AUTOPATCH) ===="

if BEGIN not in s:
    m = re.search(r"^\s*app\s*=\s*Flask\([^)]*\)\s*$", s, re.M)
    if m:
        s = s[:m.end()] + "\n\n" + BEGIN + "\n# (block will be filled below)\n" + END + "\n\n" + s[m.end():]
        changed = True

def put_block(body):
    global s, changed
    if BEGIN in s and END in s:
        new = re.sub(rf"{re.escape(BEGIN)}[\s\S]*?{re.escape(END)}",
            BEGIN + "\n" + body.strip() + "\n" + END, s, count=1, flags=re.M)
        if new != s:
            s = new
            changed = True

block = r"""
# noisy + defensive chat backend
print("[chat] backend loaded")

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
        cur = conn.execute("SELECT user, text, ts FROM messages ORDER BY id DESC LIMIT ?;", (limit,))
        rows = cur.fetchall()
        return [{"user": r["user"], "text": r["text"], "ts": r["ts"]} for r in rows][::-1]
    finally:
        conn.close()

def save_message(user, text):
    conn = _chat_db()
    try:
        conn.execute("INSERT INTO messages(user, text, ts) VALUES(?,?,?);",
            (user, text, datetime.utcnow().isoformat(timespec="seconds")+"Z"))
        conn.commit()
    finally:
        conn.close()

ensure_chat_schema()

socketio = globals().get("socketio") or SocketIO(app, cors_allowed_origins="*", logger=True, engineio_logger=True)

@socketio.on("connect", namespace="/")
def _chat_on_connect():
    try:
        print("[chat] connect:", request.sid)
    except Exception as e:
        print("[chat] connect (no sid):", e)
    emit("chat_ready", {"ok": True})
    emit("chat_history", get_last_messages(100))

@socketio.on("chat_history_request", namespace="/")
def _chat_history_request():
    emit("chat_history", get_last_messages(100))

@socketio.on("chat_message", namespace="/")
def _chat_on_message(data):
    text = (data or {}).get("text", "").strip()
    if not text:
        return
    if len(text) > 2000:
        text = text[:2000]
    user = (session.get("display_name") or session.get("username")
            or getattr(g, "user_name", None) or "Anonymous")
    print(f"[chat] msg from {user}: {text}")
    try:
        save_message(user, text)
    except Exception as e:
        print("[chat] save error:", e)
    emit("chat_message", {"user": user, "text": text}, broadcast=True)

print("[chat] backend ready")
"""

put_block(block)

def swap_run(s):
    if "socketio.run(app" in s:
        return s
    return re.sub(r"\bapp\.run\s*\(\s*(.*?)\s*\)",
                  r"socketio.run(app, \1, allow_unsafe_werkzeug=True)", s)
new = swap_run(s)
if new != s:
    s = new
    changed = True

if changed:
    p.with_suffix(".py.chatforcebak").write_text(orig, encoding="utf-8")
    p.write_text(s, encoding="utf-8")
    print("app.py updated (chat handlers forced, history route added).")
else:
    print("No changes needed.")
