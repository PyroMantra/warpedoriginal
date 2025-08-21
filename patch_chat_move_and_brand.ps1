#!/usr/bin/env python3
import re, json
from pathlib import Path
from textwrap import dedent

root = Path(".").resolve()
tpl_dir = root / "templates"
static_dir = root / "static"
static_dir.mkdir(exist_ok=True)

# --- 1) Replace chat.css with draggable-friendly, vertical form (textarea over Send) ---
chat_css = dedent("""
#global-chat {
  position: fixed;
  right: 16px;
  top: 110px; /* adjust if your header is taller */
  width: 340px;
  max-height: calc(100vh - 140px);
  display: flex;
  flex-direction: column;
  background: rgba(30,30,30,0.92);
  border: 1px solid rgba(255,255,255,0.12);
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
  cursor: move; /* show draggable */
  user-select: none;
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
  word-wrap: break-word;
  overflow-wrap: anywhere;
}
.chat-msg .u { font-weight: 700; margin-right: 6px; color: #ffd9c8; }
#chat-form {
  display: flex;
  flex-direction: column;  /* textarea above the button */
  gap: 8px;
  padding: 10px;
  border-top: 1px solid rgba(255,255,255,0.1);
}
#chat-input {
  flex: 1 1 auto;
  min-height: 64px;
  max-height: 160px;
  resize: vertical;
  background: rgba(0,0,0,0.3);
  color: #fff;
  border: 1px solid rgba(255,255,255,0.15);
  border-radius: 8px;
  padding: 8px 10px;
  outline: none;
}
#chat-send {
  background: #c14916;
  border: none;
  color: #fff;
  border-radius: 8px;
  padding: 10px 12px;
  cursor: pointer;
}
@media (max-width: 1024px) { #global-chat { width: 300px; } }
@media (max-width: 820px)  { #global-chat { display:none; } } /* hide on small screens */
""").strip("\n")
(static_dir / "chat.css").write_text(chat_css, encoding="utf-8")


# --- 2) Replace chat.js with draggable + textarea + saved position (localStorage) ---
chat_js = dedent(r"""
(function(){
  function el(id){return document.getElementById(id);}
  function msg(node, u, t){
    const d=document.createElement('div'); d.className='chat-msg';
    d.innerHTML='<span class="u">'+escapeHtml(u)+':</span><span class="t">'+t+'</span>';
    node.appendChild(d); node.scrollTop = node.scrollHeight;
  }
  function escapeHtml(s){var d=document.createElement('div'); d.innerText=s; return d.innerHTML;}

  // --- Drag handling for #global-chat (remember position) ---
  function makeDraggable(panel, handle){
    let dragging=false, startX=0, startY=0, startLeft=0, startTop=0;

    // restore position
    try{
      const saved = JSON.parse(localStorage.getItem("global_chat_pos")||"null");
      if(saved && typeof saved.left==="number" && typeof saved.top==="number"){
        panel.style.left = saved.left + "px";
        panel.style.top  = saved.top  + "px";
        panel.style.right = "auto";
      }
    }catch(e){}

    function onDown(e){
      dragging=true;
      const rect = panel.getBoundingClientRect();
      startLeft = rect.left;
      startTop  = rect.top;
      startX = (e.touches? e.touches[0].clientX : e.clientX);
      startY = (e.touches? e.touches[0].clientY : e.clientY);
      panel.style.right = "auto"; // switch to left/top anchoring while dragging
      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup', onUp);
      document.addEventListener('touchmove', onMove, {passive:false});
      document.addEventListener('touchend', onUp);
    }
    function onMove(e){
      if(!dragging) return;
      const x = (e.touches? e.touches[0].clientX : e.clientX);
      const y = (e.touches? e.touches[0].clientY : e.clientY);
      const dx = x - startX;
      const dy = y - startY;
      const left = Math.max(6, Math.min(window.innerWidth - panel.offsetWidth - 6, startLeft + dx));
      const top  = Math.max(6, Math.min(window.innerHeight - panel.offsetHeight - 6, startTop + dy));
      panel.style.left = left + "px";
      panel.style.top  = top  + "px";
      e.preventDefault && e.preventDefault();
    }
    function onUp(){
      if(!dragging) return;
      dragging=false;
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
      document.removeEventListener('touchmove', onMove);
      document.removeEventListener('touchend', onUp);
      // save
      try{
        const rect = panel.getBoundingClientRect();
        localStorage.setItem("global_chat_pos", JSON.stringify({left: rect.left, top: rect.top}));
      }catch(e){}
    }
    handle.addEventListener('mousedown', onDown);
    handle.addEventListener('touchstart', onDown, {passive:false});
  }

  function init(){
    const wrap = document.getElementById('global-chat');
    if(!wrap) return;
    const list = el('chat-messages');
    const input = el('chat-input');
    const form = el('chat-form');
    const header = wrap.querySelector('.chat-header');

    // make draggable
    makeDraggable(wrap, header);

    // Use server-rendered name if provided, else fetch /whoami, else 'Adventurer'
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

    // Submit: textarea above button
    form.addEventListener('submit', function(e){
      e.preventDefault();
      const text = (input.value||'').trim();
      if(!text) return;
      ensureName(function(){
        socket.emit('chat_message', {text});
        input.value='';
      });
    });

    // Ctrl+Enter to send
    input.addEventListener('keydown', function(e){
      if((e.ctrlKey || e.metaKey) && e.key === 'Enter'){
        form.requestSubmit();
      }
    });
  }
  if(document.readyState==='loading'){document.addEventListener('DOMContentLoaded', init);} else {init();}
})();
""").strip("\n")
(static_dir / "chat.js").write_text(chat_js, encoding="utf-8")


# --- 3) Ensure the chat panel uses a <textarea> above the button (update templates that contain the panel) ---
def upgrade_panel_markup(text: str) -> str:
  # Replace an <input id="chat-input"...> with a <textarea id="chat-input">...</textarea>
  text2 = re.sub(
      r'<input[^>]*id\s*=\s*"chat-input"[^>]*>',
      '<textarea id="chat-input" placeholder="Type a message..." autocomplete="off"></textarea>',
      text,
      flags=re.I
  )
  return text2

changed_tpl = []

if tpl_dir.exists():
    for html in tpl_dir.rglob("*.html"):
        txt = html.read_text(encoding="utf-8", errors="ignore")
        orig = txt
        if 'id="global-chat"' in txt:
            txt = upgrade_panel_markup(txt)
        if txt != orig:
            html.with_suffix(".html.bak_chatmove").write_text(orig, encoding="utf-8")
            html.write_text(txt, encoding="utf-8")
            changed_tpl.append(str(html.relative_to(root)))


# --- 4) Make sure clicking "Across the Planes" goes Home: replace/ensure href for that anchor ---
def fix_brand_links(file: Path):
    t = file.read_text(encoding="utf-8", errors="ignore")
    o = t

    # Replace any <a ...>Across the Planes</a> with same anchor but href="{{ url_for('home') }}"
    def repl(m):
        attrs = m.group(1)
        text  = m.group(2)
        # remove existing href=... if present
        attrs = re.sub(r'\s+href\s*=\s*("|\')[^"\']*\1', '', attrs, flags=re.I)
        # Reinsert href at front (preserve other attributes)
        attrs = ' href="{{ url_for(\'home\') }}"' + attrs
        return f"<a{attrs}>{text}</a>"

    # anchor version
    t = re.sub(r'<a([^>]*?)>\s*(Across the Planes)\s*</a>', repl, t, flags=re.I)

    if t != o:
        file.with_suffix(file.suffix + ".bak_brandlink").write_text(o, encoding="utf-8")
        file.write_text(t, encoding="utf-8")
        return True
    return False

brand_fixed = []
if tpl_dir.exists():
    for f in tpl_dir.rglob("*.html"):
        try:
            if fix_brand_links(f):
                brand_fixed.append(str(f.relative_to(root)))
        except Exception:
            pass

print("Chat UI updated (draggable + textarea).")
if changed_tpl:
    print("Templates adjusted for chat panel:")
    for c in changed_tpl:
        print(" -", c)
if brand_fixed:
    print("Brand anchors updated (go Home):")
    for c in brand_fixed:
        print(" -", c)
