#!/usr/bin/env python3
import re
from pathlib import Path
from textwrap import dedent

root = Path(".").resolve()
app_path = root / "app.py"
tpl_dir = root / "templates"
static_dir = root / "static"
static_dir.mkdir(exist_ok=True)

if not app_path.exists():
    raise SystemExit("ERROR: app.py not found.")

# --- Read app.py ---
src = app_path.read_text(encoding="utf-8", errors="ignore")

# Ensure imports
def ensure_import_line(s, module, names):
    pat = re.compile(rf"from\s+{re.escape(module)}\s+import\s+([^\n]+)")
    m = pat.search(s)
    if m:
        existing = [x.strip() for x in m.group(1).split(",")]
        changed = False
        for n in names:
            if n not in existing:
                existing.append(n); changed = True
        if changed:
            s = s.replace(m.group(0), f"from {module} import {', '.join(existing)}", 1)
    else:
        s = f"from {module} import {', '.join(names)}\n" + s
    return s

# Flask imports (session, request already added in earlier patches, but keep safe)
s = src
s = ensure_import_line(s, "flask", ["Flask","render_template","redirect","url_for","session","request"])
s = ensure_import_line(s, "flask_socketio", ["SocketIO","emit","join_room","leave_room"])
if "from datetime import datetime" not in s:
    s = "from datetime import datetime\n" + s
if "import html" not in s:
    s = "import html\n" + s
if "from collections import deque" not in s:
    s = "from collections import deque\n" + s

# Find app = Flask(...)
app_create = re.search(r"\bapp\s*=\s*Flask\([^)]*\)", s)
if not app_create:
    raise SystemExit("ERROR: Could not find `app = Flask(...)` in app.py.")

# Add/ensure socketio = SocketIO(app, ...)
if "SocketIO(" not in s:
    insert_at = app_create.end()
    s = s[:insert_at] + "\n\n# --- Socket.IO setup ---\nsocketio = SocketIO(app, async_mode='threading', cors_allowed_origins='*')\n" + s[insert_at:]
elif re.search(r"\bsocketio\s*=\s*SocketIO\(", s) is None:
    # SocketIO used elsewhere but instance not defined — define it after app
    insert_at = app_create.end()
    s = s[:insert_at] + "\n\n# --- Socket.IO setup ---\nsocketio = SocketIO(app, async_mode='threading', cors_allowed_origins='*')\n" + s[insert_at:]

# Add chat history + helpers if missing
if "CHAT_HISTORY =" not in s:
    chat_helpers = dedent("""
    # --- Global Chat state ---
    CHAT_HISTORY = deque(maxlen=100)  # keep last 100 messages
    CONNECTED = {}  # sid -> username

    def _display_name_from_session():
        name = session.get("username")
        if not name:
            email = session.get("email")
            if email:
                name = email.split("@")[0]
        return name or "Adventurer"
    """).strip("\n") + "\n"
    # Insert right after socketio init
    m_si = re.search(r"\bsocketio\s*=\s*SocketIO\([^)]*\)\s*", s)
    if m_si:
        s = s[:m_si.end()] + "\n\n" + chat_helpers + s[m_si.end():]
    else:
        s = s + "\n\n" + chat_helpers

# Add event handlers if not present
if "@socketio.on('connect')" not in s:
    handlers = dedent("""
    # --- Socket.IO events for Global Chat ---
    @socketio.on('connect')
    def on_connect():
        user = _display_name_from_session()
        CONNECTED[request.sid] = user
        # Send history to the newly connected client
        emit('chat_history', list(CHAT_HISTORY))
        # Announce join
        join_room('global')
        emit('chat_message', {'user': 'System', 'text': f"{user} joined the chat."}, to='global')

    @socketio.on('disconnect')
    def on_disconnect():
        user = CONNECTED.pop(request.sid, None) or 'Someone'
        emit('chat_message', {'user': 'System', 'text': f"{user} left the chat."}, to='global')

    @socketio.on('chat_message')
    def on_chat_message(data):
        # data: {'text': '...'}
        user = CONNECTED.get(request.sid) or _display_name_from_session()
        text = (data.get('text') or '').strip()
        if not text:
            return
        # Prevent basic HTML injection in message text
        safe_text = html.escape(text)
        msg = {'user': user, 'text': safe_text, 'ts': datetime.utcnow().isoformat()}
        CHAT_HISTORY.append(msg)
        emit('chat_message', msg, to='global')
    """).strip("\n") + "\n"
    s = s + "\n\n" + handlers

# Replace app.run(...) with socketio.run(...)
def replace_run_block(code):
    # Find __main__ block
    m = re.search(r"\nif\s+__name__\s*==\s*['\"]__main__['\"]\s*:\s*(.+)$", code, re.S)
    if not m:
        # Append a fresh one
        return code.rstrip() + dedent("""

        if __name__ == "__main__":
            # Use Socket.IO server
            socketio.run(app, host="0.0.0.0", port=5000, debug=True)
        """)
    block = m.group(0)
    # Replace app.run with socketio.run inside the block
    new_block = re.sub(r"app\.run\([^)]*\)", 'socketio.run(app, host="0.0.0.0", port=5000, debug=True)', block)
    if new_block == block and "socketio.run" not in block:
        # No run call found, insert one
        new_block = block + '\n    socketio.run(app, host="0.0.0.0", port=5000, debug=True)\n'
    return code.replace(block, new_block)

s = replace_run_block(s)

# Write app.py backup + save
app_path.with_suffix(".py.bak_chat").write_text(src, encoding="utf-8")
app_path.write_text(s, encoding="utf-8")

# --- Write static/chat.css ---
chat_css = dedent("""
#global-chat {
  position: fixed;
  right: 16px;
  top: 110px; /* adjust if your header is taller */
  width: 320px;
  max-height: calc(100vh - 140px);
  display: flex;
  flex-direction: column;
  background: rgba(30,30,30,0.9);
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 12px;
  overflow: hidden;
  z-index: 9999;
  box-shadow: 0 8px 24px rgba(0,0,0,0.35);
  font-family: system-ui, -apple-system, Segoe UI, Roboto, Ubuntu, Cantarell, "Helvetica Neue", Arial, "Noto Sans", "Apple Color Emoji","Segoe UI Emoji","Noto Color Emoji", sans-serif;
}
.chat-header {
  padding: 10px 12px;
  font-weight: 700;
  letter-spacing: .4px;
  background: linear-gradient(90deg, #c14916, #8f2c12);
  color: #fff;
}
#chat-messages {
  padding: 10px;
  overflow-y: auto;
  flex: 1 1 auto;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.chat-msg {
  background: rgba(255,255,255,0.06);
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 8px;
  padding: 6px 8px;
  color: #eee;
  font-size: 14px;
}
.chat-msg .u { font-weight: 700; margin-right: 6px; color: #ffd9c8; }
#chat-form {
  display: flex; gap: 8px; padding: 10px; border-top: 1px solid rgba(255,255,255,0.1);
}
#chat-input {
  flex: 1 1 auto;
  background: rgba(0,0,0,0.3);
  color: #fff;
  border: 1px solid rgba(255,255,255,0.15);
  border-radius: 8px;
  padding: 8px 10px;
  outline: none;
}
#chat-send {
  background: #c14916; border: none; color: #fff; border-radius: 8px; padding: 8px 12px; cursor: pointer;
}
@media (max-width: 1024px) {
  #global-chat { width: 280px; }
}
@media (max-width: 820px) {
  #global-chat { display:none; } /* hide on small screens; tweak if you want a toggle */
}
""").strip("\n")
(static_dir / "chat.css").write_text(chat_css, encoding="utf-8")

# --- Write static/chat.js ---
chat_js = dedent("""
(function(){
  function el(id){return document.getElementById(id);}
  function msg(node, u, t){
    const d=document.createElement('div'); d.className='chat-msg';
    d.innerHTML='<span class="u">'+escapeHtml(u)+':</span><span class="t">'+t+'</span>';
    node.appendChild(d); node.scrollTop = node.scrollHeight;
  }
  function escapeHtml(s){var d=document.createElement('div'); d.innerText=s; return d.innerHTML;}

  function init(){
    const wrap = document.getElementById('global-chat');
    if(!wrap) return;
    const list = el('chat-messages');
    const input = el('chat-input');
    const form = el('chat-form');

    // Use server-rendered name if provided, else fallback fetch /whoami, else 'Adventurer'
    let who = (window.CURRENT_USER_NAME || '').trim();
    function ensureName(cb){
      if(who){ cb(); return; }
      fetch('/whoami', {cache:'no-store'})
        .then(r => r.json()).then(j => { who = (j.name || 'Adventurer'); cb(); })
        .catch(()=>{ who='Adventurer'; cb(); });
    }

    // Socket.IO client
    const socket = io();

    socket.on('connect', ()=>{ /* server will hydrate and push history */ });
    socket.on('chat_history', (items)=>{
      list.innerHTML = '';
      (items||[]).forEach(m => msg(list, m.user, m.text));
    });
    socket.on('chat_message', (m)=>{
      msg(list, m.user, m.text);
    });

    form.addEventListener('submit', function(e){
      e.preventDefault();
      const text = (input.value||'').trim();
      if(!text) return;
      ensureName(function(){
        socket.emit('chat_message', {text});
        input.value='';
      });
    });
  }
  if(document.readyState==='loading'){document.addEventListener('DOMContentLoaded', init);} else {init();}
})();
""").strip("\n")
(static_dir / "chat.js").write_text(chat_js, encoding="utf-8")

# --- Inject panel + includes into base/layout/index (idempotent) ---
def inject_into_html(file: Path):
    txt = file.read_text(encoding="utf-8", errors="ignore")
    orig = txt
    if 'id="global-chat"' not in txt:
        panel = dedent("""
        <!-- Global Chat Panel -->
        <div id="global-chat">
          <div class="chat-header">Global Chat</div>
          <div id="chat-messages"></div>
          <form id="chat-form">
            <input id="chat-input" type="text" placeholder="Message the world..." autocomplete="off" />
            <button id="chat-send" type="submit">Send</button>
          </form>
        </div>
        """).strip("\n")
        # Insert before </body> if possible
        if re.search(r"</body\s*>", txt, re.I):
            txt = re.sub(r"</body\s*>", panel + "\n</body>", txt, count=1, flags=re.I)
        else:
            txt = txt + "\n" + panel + "\n"

    # Add CSS to <head>
    if "chat.css" not in txt:
        link = "{{ url_for('static', filename='chat.css') }}"
        head_link = f'<link rel="stylesheet" href="{link}">'
        if re.search(r"</head\s*>", txt, re.I):
            txt = re.sub(r"</head\s*>", head_link + "\n</head>", txt, count=1, flags=re.I)
        else:
            txt = head_link + "\n" + txt

    # Add Socket.IO client + chat.js before </body>
    need_socket = "cdn.socket.io" not in txt
    need_chatjs = "chat.js" not in txt
    if need_socket or need_chatjs:
        inj = []
        if need_socket:
            inj.append('<script src="https://cdn.socket.io/4.7.5/socket.io.min.js"></script>')
        if need_chatjs:
            inj.append('<script>window.CURRENT_USER_NAME = "{{ current_user_name }}";</script>')
            inj.append('<script src="{{ url_for(\'static\', filename=\'chat.js\') }}"></script>')
        inj_block = "\n".join(inj)
        if re.search(r"</body\s*>", txt, re.I):
            txt = re.sub(r"</body\s*>", inj_block + "\n</body>", txt, count=1, flags=re.I)
        else:
            txt = txt + "\n" + inj_block + "\n"

    if txt != orig:
        file.with_suffix(file.suffix + ".bak_chatui").write_text(orig, encoding="utf-8")
        file.write_text(txt, encoding="utf-8")
        return True
    return False

changed = []
if tpl_dir.exists():
    candidates = [
        tpl_dir / "base.html",
        tpl_dir / "layout.html",
        tpl_dir / "index.html",
        tpl_dir / "home.html",
    ]
    # Add any other .html with a </body> if the above don't exist
    if not any(p.exists() for p in candidates):
        candidates = list(tpl_dir.rglob("*.html"))

    for f in candidates:
        try:
            if f.exists() and inject_into_html(f):
                changed.append(str(f.relative_to(root)))
        except Exception as e:
            print("Skipped", f, "->", e)

print("Patched app.py and added chat assets.")
if changed:
    print("Updated templates:")
    for c in changed:
        print(" -", c)
else:
    print("No template files were modified (UI may already be injected).")
