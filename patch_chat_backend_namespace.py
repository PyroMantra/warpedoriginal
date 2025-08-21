#!/usr/bin/env python3
import re
from pathlib import Path

p = Path("app.py")
s = p.read_text(encoding="utf-8", errors="ignore")
orig = s

# Ensure explicit namespace on handlers
s = re.sub(r'@socketio\.on\("connect"\)', r'@socketio.on("connect", namespace="/")', s)
s = re.sub(r'@socketio\.on\("chat_message"\)', r'@socketio.on("chat_message", namespace="/")', s)

# Make sure connect emits history
if "emit(\"chat_history\"" not in s:
    s = re.sub(r'@socketio\.on\("connect"[^)]*\)[\s\S]*?def\s+\w+\s*\([^)]*\):',
               r'@socketio.on("connect", namespace="/")\ndef _chat_on_connect():',
               s, count=1)
    s = re.sub(r'def\s+_chat_on_connect\(\):\s*\n',
               r'def _chat_on_connect():\n    emit("chat_history", get_last_messages(100))\n',
               s, count=1)

# Ensure the send handler doesn’t depend on returning an ack
s = re.sub(
    r'def\s+_chat_on_message\([^)]*\):\s*\n([\s\S]*?)\n\s*return\s+\{[^}]+\}\s*$',
    r'def _chat_on_message(data):\n\1\n    emit("chat_message", {"user": user, "text": text}, broadcast=True)\n    # no ack return\n',
    s, flags=re.M
)

if s != orig:
    p.with_suffix(".py.chatnsbak").write_text(orig, encoding="utf-8")
    p.write_text(s, encoding="utf-8")
    print("app.py updated (namespace explicit, no ack required).")
else:
    print("No backend edits needed.")
