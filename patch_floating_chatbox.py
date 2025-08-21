#!/usr/bin/env python3
import re, time
from pathlib import Path
from textwrap import dedent

root = Path(".").resolve()
tpl_dir = root / "templates"
static_dir = root / "static"
static_dir.mkdir(exist_ok=True)

STAMP = str(int(time.time()))  # cache-bust

# ----------------- static/chat.css -----------------
chat_css = dedent("""
/* Remove any previous hover-FAB UI */
#chat-fab, #chat-popover { display:none !important; }

/* Remove any legacy grounded chat forms/panels */
form#chat-form:not(#global-chat form#chat-form),
textarea#chat-input:not(#global-chat #chat-input),
#global-chat.legacy-hidden { display:none !important; }

/* Floating chat panel */
#global-chat{
  position:fixed; right:16px; bottom:16px;
  width:380px; max-height:70vh;
  background:rgba(30,30,30,.96);
  border:1px solid rgba(255,255,255,.12);
  border-radius:12px;
  display:flex; flex-direction:column;
  overflow:hidden; z-index:10000;
  box-shadow:0 16px 40px rgba(0,0,0,.45);
  color:#eee;
}
#global-chat .chat-header{
  padding:10px 12px;
  background:linear-gradient(90deg,#c14916,#8f2c12);
  color:#fff; font-weight:700;
  cursor:move; user-select:none;
  display:flex; align-items:center; justify-content:space-between;
}
#global-chat .chat-header .title{ pointer-events:none; }
#global-chat .chat-header .controls{ display:flex; gap:6px; }
#global-chat .btn{
  appearance:none; border:none; color:#fff; background:rgba(255,255,255,.2);
  padding:6px 8px; border-radius:6px; cursor:pointer;
}
#global-chat .btn:hover{ background:rgba(255,255,255,.3); }

#chat-messages{
  flex:1 1 auto;
  overflow-y:auto;
  padding:10px;
  display:flex; flex-direction:column; gap:6px;
}
.chat-msg{
  background:rgba(255,255,255,.06);
  border:1px solid rgba(255,255,255,.08);
  border-radius:8px; padding:6px 8px; color:#eee; font-size:14px;
  word-wrap:break-word; overflow-wrap:anywhere;
}
.chat-msg .u{ font-weight:700; margin-right:6px; color:#ffd9c8; }

#global-chat form#chat-form{
  order:1; display:flex; flex-direction:column; gap:8px;
  padding:10px; border-top:1px solid rgba(255,255,255,.1);
}
#chat-input{
  min-height:64px; background:rgba(0,0,0,.3); color:#fff;
  border:1px solid rgba(255,255,255,.15); border-radius:8px; padding:8px 10px;
}
#chat-send{
  background:#c14916; color:#fff; border:none; border-radius:8px; padding:10px 12px;
  cursor:pointer;
}

@media (max-width:820px){
  #global-chat{ width:92vw; right:4vw; bottom:12px; }
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
  function makeDraggable(panel, handle){
    let dragging=false, sx=0, sy=0, sl=0, st=0;
    try{
      const saved = JSON.parse(localStorage.getItem("global_chat_pos")||"null");
      if(saved && typeof saved.left==="number" && typeof saved.top==="number"){
        panel.style.left = saved.left + "px";
        panel.style.top  = saved.top  + "px";
        panel.style.right = "auto"; // switch to left/top
      }
    }catch(e){}
    function down(e){
      dragging=true;
      const r = panel.getBoundingClientRect();
      sl=r.left; st=r.top;
      sx = (e.touches? e.touches[0].clientX : e.clientX);
      sy = (e.touches? e.touches[0].clientY : e.clientY);
      panel.style.right="auto";
      document.addEventListener('mousemove', move);
      document.addEventListener('mouseup', up);
      document.addEventListener('touchmove', move, {passive:false});
      document.addEventListener('touchend', up);
    }
    function move(e){
      if(!dragging) return;
      const x=(e.touches? e.touches[0].clientX : e.clientX);
      const y=(e.touches? e.touches[0].clientY : e.clientY);
      const dx=x-sx, dy=y-sy;
      const left=Math.max(6, Math.min(window.innerWidth - panel.offsetWidth - 6, sl+dx));
      const top =Math.max(6, Math.min(window.innerHeight - panel.offsetHeight - 6, st+dy));
      panel.style.left=left+"px"; panel.style.top=top+"px";
      e.preventDefault && e.preventDefault();
    }
    function up(){
      if(!dragging) return;
      dragging=false;
      document.removeEventListener('mousemove', move);
      document.removeEventListener('mouseup', up);
      document.removeEventListener('touchmove', move);
      document.removeEventListener('touchend', up);
      try{
        const r = panel.getBoundingClientRect();
        localStorage.setItem("global_chat_pos", JSON.stringify({left:r.left, top:r.top}));
      }catch(e){}
    }
    handle.addEventListener('mousedown', down);
    handle.addEventListener('touchstart', down, {passive:false});
  }

  function init(){
    const box = document.getElementById('global-chat');
    if(!box) return;
    const header = box.querySelector('.chat-header');
    const list = document.getElementById('chat-messages');
    const form = document.getElementById('chat-form');
    const input = document.getElementById('chat-input');
    const btn = document.getElementById('chat-send');
    const btnMin = document.getElementById('chat-min');

    makeDraggable(box, header);

    // Minimize (collapse to header only)
    btnMin && btnMin.addEventListener('click', function(){
      if(box.classList.contains('min')){
        box.classList.remove('min');
        list.style.display='flex'; form.style.display='flex';
      }else{
        box.classList.add('min');
        list.style.display='none'; form.style.display='none';
      }
    });

    const socket = io(); // root namespace
    socket.on('chat_history', items=>{
      list.innerHTML='';
      (items||[]).forEach(m=>appendMsg(list, m.user, m.text));
    });
    socket.on('chat_message', m=> appendMsg(list, m.user, m.text));

    form.addEventListener('submit', e=>{
      e.preventDefault();
      const text=(input.value||'').trim();
      if(!text) return;
      socket.emit('chat_message', {text});
      input.value='';
    });
    input.addEventListener('keydown', (e)=>{ if((e.ctrlKey||e.metaKey)&&e.key==='Enter'){ form.requestSubmit(); } });
  }

  if(document.readyState==='loading'){ document.addEventListener('DOMContentLoaded', init); }
  else { init(); }
})();
""").strip()+"\n"

# ----------------- canonical floating panel markup -----------------
PANEL = dedent("""
<div id="global-chat">
  <div class="chat-header">
    <div class="title">Global Chat</div>
    <div class="controls">
      <button id="chat-min" class="btn" type="button">–</button>
    </div>
  </div>
  <div id="chat-messages"></div>
  <form id="chat-form">
    <textarea id="chat-input" placeholder="Type a message..." autocomplete="off"></textarea>
    <button id="chat-send" type="submit">Send</button>
  </form>
</div>
""").strip()

# ----------------- write static assets -----------------
(static_dir / "chat.css").write_text(chat_css, encoding="utf-8")
(static_dir / "chat.js").write_text(chat_js, encoding="utf-8")

# ----------------- template helpers -----------------
def remove_old(html: str) -> str:
  # nuke FAB, popover, legacy panel, and stray grounded chat bits
  html = re.sub(r'<div[^>]*id\s*=\s*"chat-fab"[\s\S]*?</div>', '', html, flags=re.I)
  html = re.sub(r'<div[^>]*id\s*=\s*"chat-popover"[\s\S]*?</div>', '', html, flags=re.I)
  html = re.sub(r'<div[^>]*id\s*=\s*"global-chat"[\s\S]*?</div>', '', html, flags=re.I)
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

def inject_panel(html: str) -> str:
  cleaned = remove_old(html)
  if re.search(r"</body\s*>", cleaned, re.I):
    return re.sub(r"</body\s*>", lambda m: PANEL + "\n</body>", cleaned, count=1, flags=re.I)
  return cleaned + "\n" + PANEL + "\n"

changed = []
if not tpl_dir.exists():
  raise SystemExit("No templates/ directory found.")

for f in sorted(tpl_dir.rglob("*.html")):
  txt = f.read_text(encoding="utf-8", errors="ignore")
  orig = txt

  # Fix any lingering "1{{ ... }}" from earlier
  txt = re.sub(r"(?:\\1|(?<!\\)\b1)\s*(\{\{[^}]+\}\})", r"\1", txt)

  txt = ensure_head_css(txt)
  txt = ensure_footer_scripts(txt)
  txt = inject_panel(txt)

  if txt != orig:
    f.with_suffix(f.suffix + ".bak_floatchat").write_text(orig, encoding="utf-8")
    f.write_text(txt, encoding="utf-8")
    changed.append(str(f.relative_to(root)))

print("Floating chatbox installed. Templates updated:", len(changed))
for c in changed:
  print(" -", c)
