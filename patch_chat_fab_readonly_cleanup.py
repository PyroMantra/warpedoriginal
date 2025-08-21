#!/usr/bin/env python3
import re, time
from pathlib import Path
from textwrap import dedent

root = Path(".").resolve()
tpl_dir = root / "templates"
static_dir = root / "static"
static_dir.mkdir(exist_ok=True)

STAMP = str(int(time.time()))  # cache bust for static files

# ----------------- static/chat.css -----------------
chat_css = dedent("""
/* Hide any legacy chat UI (old panel or forms) */
#global-chat { display:none !important; }
form#chat-form, textarea#chat-input { display:none !important; }

/* Floating chat button (FAB) */
#chat-fab{
  position:fixed; right:20px; bottom:20px;
  width:56px; height:56px; border-radius:50%;
  display:flex; align-items:center; justify-content:center;
  background:linear-gradient(135deg,#c14916,#8f2c12); color:#fff;
  box-shadow:0 10px 20px rgba(0,0,0,.35);
  cursor:pointer; user-select:none; font-size:22px;
  z-index:9999;
}
#chat-badge{
  position:absolute; top:-6px; right:-6px;
  min-width:18px; height:18px; padding:0 5px; border-radius:9px;
  background:#ff4757; color:#fff; font-size:12px; display:none;
  align-items:center; justify-content:center;
}

/* Popover sits separately (fixed), toggled via body class .chat-open */
#chat-popover{
  position:fixed; right:20px; bottom:84px; /* above FAB */
  width:360px; max-height:360px;
  display:flex; flex-direction:column;
  background:rgba(30,30,30,.96);
  border:1px solid rgba(255,255,255,.12);
  border-radius:12px; overflow:hidden;
  opacity:0; pointer-events:none; transform:translateY(8px);
  transition:opacity .15s ease, transform .15s ease;
  box-shadow:0 12px 32px rgba(0,0,0,.45);
  color:#eee; z-index:10000;
}
.chat-open #chat-popover{
  opacity:1; pointer-events:auto; transform:translateY(0);
}
#chat-popover .chat-popover-header{
  background:linear-gradient(90deg,#c14916,#8f2c12);
  color:#fff; font-weight:700; padding:10px 12px;
}
#chat-popover-messages{
  flex:1 1 auto; overflow-y:auto; padding:10px;
  display:flex; flex-direction:column; gap:6px;
}
.chat-msg{
  background:rgba(255,255,255,.06);
  border:1px solid rgba(255,255,255,.08);
  border-radius:8px; padding:6px 8px; color:#eee; font-size:14px;
  word-wrap:break-word; overflow-wrap:anywhere;
}
.chat-msg .u{ font-weight:700; margin-right:6px; color:#ffd9c8; }

@media (max-width:820px){
  #chat-popover{ width:300px; max-height:300px; }
}
""").strip()+"\n"

# ----------------- static/chat.js -----------------
chat_js = dedent(r"""
(function(){
  function el(id){return document.getElementById(id);}
  function escapeHtml(s){var d=document.createElement('div'); d.innerText=s; return d.innerHTML;}
  function appendMsg(list, user, text){
    var d=document.createElement('div');
    d.className='chat-msg';
    d.innerHTML='<span class="u">'+escapeHtml(user)+':</span><span class="t">'+text+'</span>';
    list.appendChild(d);
    list.scrollTop = list.scrollHeight;
  }

  function init(){
    var fab = el('chat-fab');
    var pop = el('chat-popover');
    var list = el('chat-popover-messages');
    var badge = el('chat-badge');
    if(!fab || !pop || !list) return;

    // Toggle popover on click
    function openChat(){ document.body.classList.add('chat-open'); clearUnread(); }
    function closeChat(){ document.body.classList.remove('chat-open'); }
    function isOpen(){ return document.body.classList.contains('chat-open'); }

    fab.addEventListener('click', function(e){
      e.stopPropagation();
      if(isOpen()) closeChat(); else openChat();
    });
    // click outside closes
    document.addEventListener('click', function(e){
      if(!isOpen()) return;
      if(!pop.contains(e.target) && !fab.contains(e.target)) closeChat();
    });
    // Esc closes
    document.addEventListener('keydown', function(e){
      if(e.key === 'Escape') closeChat();
    });

    // Unread badge logic
    var unread = 0;
    function showBadge(){
      if(!badge) return;
      if(unread>0){ badge.style.display='flex'; badge.textContent=String(unread); }
      else { badge.style.display='none'; }
    }
    function clearUnread(){ unread=0; showBadge(); }

    // Socket.IO
    var socket = io();  // root namespace — should match your server handlers

    socket.on('connect', function(){ /* server should emit chat_history soon after */ });

    socket.on('chat_history', function(items){
      list.innerHTML='';
      (items||[]).forEach(function(m){ appendMsg(list, m.user, m.text); });
      // no unread for history
    });

    socket.on('chat_message', function(m){
      appendMsg(list, m.user, m.text);
      if(!isOpen()){ unread++; showBadge(); }
    });
  }

  if(document.readyState==='loading'){ document.addEventListener('DOMContentLoaded', init); }
  else { init(); }
})();
""").strip()+"\n"

# ----------------- Markup to inject (two siblings) -----------------
FAB = dedent("""
<div id="chat-fab" title="Global Chat" aria-label="Global Chat">
  <span id="chat-badge"></span>
  <span aria-hidden="true">💬</span>
</div>
""").strip()

POPOVER = dedent("""
<div id="chat-popover" role="dialog" aria-label="Global Chat History">
  <div class="chat-popover-header">Global Chat</div>
  <div id="chat-popover-messages"></div>
</div>
""").strip()

# ----------------- write static -----------------
(static_dir / "chat.css").write_text(chat_css, encoding="utf-8")
(static_dir / "chat.js").write_text(chat_js, encoding="utf-8")

# ----------------- template helpers -----------------
def nuke_legacy(html: str) -> str:
  # remove full panels
  html = re.sub(r'<div[^>]*id\s*=\s*"global-chat"[\s\S]*?</div>', '', html, flags=re.I)
  # remove any prior FAB/Popover we injected
  html = re.sub(r'<div[^>]*id\s*=\s*"chat-fab"[\s\S]*?</div>', '', html, flags=re.I)
  html = re.sub(r'<div[^>]*id\s*=\s*"chat-popover"[\s\S]*?</div>', '', html, flags=re.I)
  # remove any legacy chat forms
  html = re.sub(r'<form[^>]*id\s*=\s*"chat-form"[\s\S]*?</form>', '', html, flags=re.I)
  html = re.sub(r'<textarea[^>]*id\s*=\s*"chat-input"[^>]*>[\s\S]*?</textarea>', '', html, flags=re.I)
  html = re.sub(r'<input[^>]*id\s*=\s*"chat-input"[^>]*>', '', html, flags=re.I)
  return html

def ensure_head_css(html: str) -> str:
  if re.search(r'href\s*=\s*"\{\{\s*url_for\(\s*[\'"]static[\'"]\s*,\s*filename\s*=\s*[\'"]chat\.css[\'"]\s*\)\s*\}\}', html, re.I):
    html = re.sub(r'(chat\.css\}\})[^"]*', r'\1?v=' + STAMP, html)
  else:
    link = f'<link rel="stylesheet" href="{{{{ url_for(\'static\', filename=\'chat.css\') }}}}?v={STAMP}">'
    if re.search(r"</head\s*>", html, re.I):
      html = re.sub(r"</head\s*>", lambda m: link + "\n</head>", html, count=1, flags=re.I)
    else:
      html = link + "\n" + html
  return html

def ensure_footer_scripts(html: str) -> str:
  if "cdn.socket.io" not in html:
    html = re.sub(r"</body\s*>", lambda m: '<script src="https://cdn.socket.io/4.7.5/socket.io.min.js"></script>\n</body>', html, count=1, flags=re.I) or (html + '\n<script src="https://cdn.socket.io/4.7.5/socket.io.min.js"></script>\n')
  if "chat.js" in html:
    html = re.sub(r'(chat\.js\}\})[^"]*', r'\1?v=' + STAMP, html)
  else:
    inj = f'<script src="{{{{ url_for(\'static\', filename=\'chat.js\') }}}}?v={STAMP}"></script>'
    html = re.sub(r"</body\s*>", lambda m: inj + "\n</body>", html, count=1, flags=re.I) or (html + "\n" + inj + "\n")
  return html

def inject_hover(html: str) -> str:
  cleaned = nuke_legacy(html)
  # inject FAB + POPOVER just before </body>
  if re.search(r"</body\s*>", cleaned, re.I):
    cleaned = re.sub(r"</body\s*>", lambda m: FAB + "\n" + POPOVER + "\n</body>", cleaned, count=1, flags=re.I)
  else:
    cleaned = cleaned + "\n" + FAB + "\n" + POPOVER + "\n"
  return cleaned

changed = []
if not tpl_dir.exists():
  raise SystemExit("No templates/ directory found.")

for f in sorted(tpl_dir.rglob("*.html")):
  txt = f.read_text(encoding="utf-8", errors="ignore")
  orig = txt

  # cleanup any lingering '1{{ ... }}' artifacts
  txt = re.sub(r"(?:\\1|(?<!\\)\b1)\s*(\{\{[^}]+\}\})", r"\1", txt)

  txt = ensure_head_css(txt)
  txt = ensure_footer_scripts(txt)
  txt = inject_hover(txt)

  if txt != orig:
    f.with_suffix(f.suffix + ".bak_chatfab").write_text(orig, encoding="utf-8")
    f.write_text(txt, encoding="utf-8")
    changed.append(str(f.relative_to(root)))

print("Applied FAB + read-only popover and removed legacy chat snippets.")
if changed:
  print("Templates updated:")
  for c in changed:
    print(" -", c)
else:
  print("No template changes were needed.")
