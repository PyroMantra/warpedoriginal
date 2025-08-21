#!/usr/bin/env python3
import re, time
from pathlib import Path
from textwrap import dedent

root = Path(".").resolve()
tpl_dir = root / "templates"
static_dir = root / "static"
static_dir.mkdir(exist_ok=True)

STAMP = str(int(time.time()))  # cache bust

# --- Canonical chat panel (messages above input) ---
CANON_PANEL = dedent("""
<!-- Global Chat Panel (canonical) -->
<div id="global-chat">
  <div class="chat-header">Global Chat</div>
  <div id="chat-messages"></div>
  <form id="chat-form">
    <textarea id="chat-input" placeholder="Type a message..." autocomplete="off"></textarea>
    <button id="chat-send" type="submit">Send</button>
  </form>
</div>
""").strip()

# --- Ensure chat.css has layout ordering (messages above form) ---
css_path = static_dir / "chat.css"
append_css = dedent("""
/* --- Chat layout enforcement (messages above input) --- */
#global-chat { display:flex; flex-direction:column; }
#chat-messages { order:0; flex:1 1 auto; overflow-y:auto; }
#chat-form { order:1; display:flex; flex-direction:column; gap:8px; }
/* --- end layout enforcement --- */
""").strip()+"\n"

if css_path.exists():
    css = css_path.read_text(encoding="utf-8", errors="ignore")
    if "#chat-messages { order:" not in css:
        css_path.with_suffix(".css.bak_order").write_text(css, encoding="utf-8")
        css = css.rstrip()+"\n\n"+append_css
        css_path.write_text(css, encoding="utf-8")
else:
    css = dedent("""
    #global-chat { position:fixed; right:16px; top:110px; width:340px; max-height:calc(100vh - 140px);
      background:rgba(30,30,30,.92); border:1px solid rgba(255,255,255,.12); border-radius:12px; display:flex; flex-direction:column; overflow:hidden; z-index:9999;}
    .chat-header { padding:10px 12px; font-weight:700; background:linear-gradient(90deg,#c14916,#8f2c12); color:#fff; cursor:move; user-select:none;}
    #chat-messages { padding:10px; gap:6px; display:flex; flex-direction:column; }
    #chat-form { padding:10px; border-top:1px solid rgba(255,255,255,.1); display:flex; flex-direction:column; gap:8px;}
    #chat-input { min-height:64px; background:rgba(0,0,0,.3); color:#fff; border:1px solid rgba(255,255,255,.15); border-radius:8px; padding:8px 10px;}
    #chat-send { background:#c14916; color:#fff; border:none; border-radius:8px; padding:10px 12px; cursor:pointer;}
    """).strip()+"\n"+append_css
    css_path.write_text(css, encoding="utf-8")

# --- Make sure chat.js exists (draggable + Socket.IO events assumed from your previous step) ---
js_path = static_dir / "chat.js"
if not js_path.exists():
    js_path.write_text(dedent("""
    (function(){
      function el(id){return document.getElementById(id);}
      function msg(node, u, t){
        const d=document.createElement('div'); d.className='chat-msg';
        d.innerHTML='<span class="u">'+escapeHtml(u)+':</span><span class="t">'+t+'</span>';
        node.appendChild(d); node.scrollTop = node.scrollHeight;
      }
      function escapeHtml(s){var d=document.createElement('div'); d.innerText=s; return d.innerHTML;}
      function makeDraggable(panel, handle){
        let dragging=false, sx=0, sy=0, sl=0, st=0;
        try{
          const saved = JSON.parse(localStorage.getItem("global_chat_pos")||"null");
          if(saved && typeof saved.left==="number" && typeof saved.top==="number"){
            panel.style.left = saved.left + "px";
            panel.style.top  = saved.top  + "px";
            panel.style.right = "auto";
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
        const wrap=document.getElementById('global-chat');
        if(!wrap) return;
        const header=wrap.querySelector('.chat-header');
        const list=el('chat-messages');
        const form=el('chat-form');
        const input=el('chat-input');
        makeDraggable(wrap, header);
        const socket = io();
        socket.on('chat_history', items=>{
          list.innerHTML=''; (items||[]).forEach(m=>msg(list, m.user, m.text));
        });
        socket.on('chat_message', m=> msg(list, m.user, m.text));
        form.addEventListener('submit', e=>{
          e.preventDefault();
          const text=(input.value||'').trim();
          if(!text) return;
          socket.emit('chat_message', {text});
          input.value='';
        });
        input.addEventListener('keydown', (e)=>{ if((e.ctrlKey||e.metaKey)&&e.key==='Enter'){ form.requestSubmit(); } });
      }
      if(document.readyState==='loading'){document.addEventListener('DOMContentLoaded', init);} else {init();}
    })();
    """).strip(), encoding="utf-8")

# --- Templating surgery: remove old panels, inject canonical, ensure links with cache-busting, brand->home, and JS fallback ---
if not tpl_dir.exists():
    raise SystemExit("No templates/ directory found.")

def remove_existing_panels(html):
    # Remove all occurrences of #global-chat block
    return re.sub(r'<div[^>]*id\s*=\s*"global-chat"[\s\S]*?</div>', '', html, flags=re.I)

def ensure_head_css(html):
    link_pat = re.compile(r'href\s*=\s*"\{\{\s*url_for\(\s*[\'"]static[\'"]\s*,\s*filename\s*=\s*[\'"]chat\.css[\'"]\s*\)\s*\}\}[^"]*"', re.I)
    if link_pat.search(html):
        # Add/replace cache buster
        html = re.sub(r'(chat\.css\}\})[^"]*', r'\1?v=' + STAMP, html)
        return html
    # Insert link before </head>
    link_tag = f'<link rel="stylesheet" href="{{{{ url_for(\'static\', filename=\'chat.css\') }}}}?v={STAMP}">'
    if re.search(r"</head\s*>", html, re.I):
        return re.sub(r"</head\s*>", link_tag + "\n</head>", html, count=1, flags=re.I)
    return link_tag + "\n" + html

def ensure_footer_scripts(html):
    # Socket.IO client
    if "cdn.socket.io" not in html:
        html = re.sub(r"</body\s*>", '<script src="https://cdn.socket.io/4.7.5/socket.io.min.js"></script>\n</body>', html, count=1, flags=re.I) or (html + '\n<script src="https://cdn.socket.io/4.7.5/socket.io.min.js"></script>\n')

    # chat.js with cache bust + CURRENT_USER_NAME hint
    if "chat.js" in html:
        html = re.sub(r'(chat\.js\}\})[^"]*', r'\1?v=' + STAMP, html)
    else:
        inj = f'<script>window.CURRENT_USER_NAME = "{{{{ current_user_name }}}}";</script>\n<script src="{{{{ url_for(\'static\', filename=\'chat.js\') }}}}?v={STAMP}"></script>'
        html = re.sub(r"</body\s*>", inj + "\n</body>", html, count=1, flags=re.I) or (html + "\n" + inj + "\n")
    return html

def ensure_brand_goes_home(html):
    # Rewrite <a ...>Across the Planes</a> to href="{{ url_for('home') }}"
    def anchor_repl(m):
        attrs = m.group("attrs") or ""
        inner = m.group("inner")
        attrs = re.sub(r'\s+href\s*=\s*(["\']).*?\1', '', attrs, flags=re.I)  # drop existing href
        new_attrs = f' href="{{{{ url_for(\'home\') }}}}"' + attrs
        return f"<a{new_attrs}>{inner}</a>"
    html2 = re.sub(r"<a(?P<attrs>[^>]*)>(?P<inner>.*?Across\s*the\s*Planes.*?)</a>", anchor_repl, html, flags=re.I|re.S)

    # Add JS fallback: if brand not an <a>, make any matching element clickable to home
    if "data-brand-fallback" not in html2:
        fallback = """<script data-brand-fallback="1">
document.addEventListener('DOMContentLoaded', function(){
  document.querySelectorAll('a, .brand, .navbar-brand, header *, [data-brand]').forEach(function(el){
    if (/Across\\s*the\\s*Planes/i.test((el.textContent||'').trim())) {
      if (el.tagName && el.tagName.toLowerCase()==='a') { el.setAttribute('href', "{{ url_for('home') }}"); }
      else { el.style.cursor='pointer'; el.addEventListener('click', function(){ window.location = "{{ url_for('home') }}"; }); }
    }
  });
});
</script>"""
        if re.search(r"</body\s*>", html2, re.I):
            html2 = re.sub(r"</body\s*>", fallback + "\n</body>", html2, count=1, flags=re.I)
        else:
            html2 += "\n" + fallback + "\n"
    return html2

def inject_panel(html):
    cleaned = remove_existing_panels(html)
    # Insert canonical panel before </body>
    if re.search(r"</body\s*>", cleaned, re.I):
        return re.sub(r"</body\s*>", CANON_PANEL + "\n</body>", cleaned, count=1, flags=re.I)
    return cleaned + "\n" + CANON_PANEL + "\n"

changed = []
for html_file in sorted(tpl_dir.rglob("*.html")):
    txt = html_file.read_text(encoding="utf-8", errors="ignore")
    orig = txt

    # 1) Fix lingering 1{{ current_user_name }} or \1{{ ... }} anywhere
    txt = re.sub(r"(?:\\1|(?<!\\)\b1)\s*(\{\{[^}]+\}\})", r"\1", txt)

    # 2) Ensure CSS + scripts + brand behavior
    txt = ensure_head_css(txt)
    txt = ensure_footer_scripts(txt)
    txt = ensure_brand_goes_home(txt)

    # 3) Inject canonical panel markup (messages above input)
    txt = inject_panel(txt)

    if txt != orig:
        html_file.with_suffix(html_file.suffix + ".bak_apply").write_text(orig, encoding="utf-8")
        html_file.write_text(txt, encoding="utf-8")
        changed.append(str(html_file.relative_to(root)))

print("Patched templates:", len(changed), "file(s) updated.")
for c in changed:
    print(" -", c)
