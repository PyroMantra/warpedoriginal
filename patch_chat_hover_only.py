#!/usr/bin/env python3
import re, time
from pathlib import Path
from textwrap import dedent

root = Path(".").resolve()
tpl_dir = root / "templates"
static_dir = root / "static"
static_dir.mkdir(exist_ok=True)

STAMP = str(int(time.time()))

# ---------- Files we create/overwrite ----------
chat_css = dedent("""
/* Hide any legacy full chat panel if it exists */
#global-chat { display: none !important; }

/* Floating chat button */
#chat-fab {
  position: fixed;
  right: 20px;
  bottom: 20px;
  width: 56px;
  height: 56px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #c14916, #8f2c12);
  color: #fff;
  box-shadow: 0 10px 20px rgba(0,0,0,.35);
  cursor: pointer;
  z-index: 9999;
  user-select: none;
  font-size: 22px;
}

/* Unread badge (optional) */
#chat-badge {
  position: absolute;
  top: -6px;
  right: -6px;
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  border-radius: 9px;
  background: #ff4757;
  color: #fff;
  font-size: 12px;
  display: none;
  align-items: center;
  justify-content: center;
}

/* Popover anchored to the fab */
#chat-popover {
  position: absolute;
  right: 0;
  bottom: 64px; /* just above the fab */
  width: 360px;
  max-height: 360px;
  display: flex;
  flex-direction: column;
  background: rgba(30,30,30,.96);
  border: 1px solid rgba(255,255,255,.12);
  border-radius: 12px;
  overflow: hidden;
  opacity: 0;
  pointer-events: none;
  transform: translateY(8px);
  transition: opacity .15s ease, transform .15s ease;
  box-shadow: 0 12px 32px rgba(0,0,0,.45);
  color: #eee;
  z-index: 10000;
}

/* Show popover when hovering the fab or the popover itself */
#chat-fab:hover #chat-popover,
#chat-popover:hover {
  opacity: 1;
  pointer-events: auto;
  transform: translateY(0);
}

#chat-popover .chat-popover-header {
  background: linear-gradient(90deg, #c14916, #8f2c12);
  color: #fff;
  font-weight: 700;
  padding: 10px 12px;
}

#chat-popover-messages {
  flex: 1 1 auto;
  overflow-y: auto;
  padding: 10px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.chat-msg {
  background: rgba(255,255,255,.06);
  border: 1px solid rgba(255,255,255,.08);
  border-radius: 8px;
  padding: 6px 8px;
  color: #eee;
  font-size: 14px;
  word-wrap: break-word;
  overflow-wrap: anywhere;
}
.chat-msg .u { font-weight: 700; margin-right: 6px; color: #ffd9c8; }

/* Mobile: keep the button; users can tap and keep finger to read (hover) */
@media (max-width: 820px){
  #chat-popover { width: 300px; max-height: 300px; }
}
""").strip() + "\n"

chat_js = dedent(r"""
(function(){
  function el(id){return document.getElementById(id);}
  function escapeHtml(s){var d=document.createElement('div'); d.innerText=s; return d.innerHTML;}

  function appendMsg(list, user, text){
    var d = document.createElement('div');
    d.className = 'chat-msg';
    d.innerHTML = '<span class="u">'+escapeHtml(user)+':</span><span class="t">'+text+'</span>';
    list.appendChild(d);
    list.scrollTop = list.scrollHeight;
  }

  function init(){
    var fab = document.getElementById('chat-fab');
    var pop = document.getElementById('chat-popover');
    var list = document.getElementById('chat-popover-messages');
    var badge = document.getElementById('chat-badge');
    if(!fab || !pop || !list) return;

    var unread = 0;
    function showBadge(){
      if(!badge) return;
      if(unread > 0){ badge.style.display='flex'; badge.textContent = String(unread); }
      else { badge.style.display='none'; }
    }
    function clearUnread(){ unread = 0; showBadge(); }

    // Clear unread when user hovers the button or the popover
    fab.addEventListener('mouseenter', clearUnread);
    pop.addEventListener('mouseenter', clearUnread);

    // Socket.IO
    var socket = io();

    socket.on('chat_history', function(items){
      list.innerHTML = '';
      (items || []).forEach(function(m){
        appendMsg(list, m.user, m.text);
      });
      // no unread for history
    });

    socket.on('chat_message', function(m){
      appendMsg(list, m.user, m.text);
      // count unread if not hovered
      if(!(fab.matches(':hover') || pop.matches(':hover'))){
        unread++;
        showBadge();
      }
    });
  }

  if(document.readyState==='loading'){
    document.addEventListener('DOMContentLoaded', init);
  }else{
    init();
  }
})();
""").strip() + "\n"

# ---------- Canonical hover markup to inject ----------
FAB_MARKUP = dedent("""
<!-- Global Chat Hover Button -->
<div id="chat-fab" title="Global Chat" aria-label="Global Chat">
  <span id="chat-badge"></span>
  <!-- icon -->
  <span aria-hidden="true">💬</span>
  <!-- popover -->
  <div id="chat-popover">
    <div class="chat-popover-header">Global Chat</div>
    <div id="chat-popover-messages"></div>
  </div>
</div>
""").strip()

# ---------- Write static assets ----------
(chat_css_path := static_dir / "chat.css").write_text(chat_css, encoding="utf-8")
(chat_js_path := static_dir / "chat.js").write_text(chat_js, encoding="utf-8")

# ---------- Template helpers ----------
def strip_legacy_panels(html: str) -> str:
  # remove any previous full-panel we might have injected
  html = re.sub(r'<div[^>]*id\s*=\s*"global-chat"[\s\S]*?</div>', '', html, flags=re.I)
  # remove any existing hover fab duplicates so we inject once
  html = re.sub(r'<div[^>]*id\s*=\s*"chat-fab"[\s\S]*?</div>', '', html, flags=re.I)
  return html

def ensure_head_css(html: str) -> str:
  # add/replace chat.css with cache buster
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
  # Socket.IO client
  if "cdn.socket.io" not in html:
    html = re.sub(r"</body\s*>", lambda m: '<script src="https://cdn.socket.io/4.7.5/socket.io.min.js"></script>\n</body>', html, count=1, flags=re.I) or (html + '\n<script src="https://cdn.socket.io/4.7.5/socket.io.min.js"></script>\n')
  # chat.js with cache buster, preserve CURRENT_USER_NAME hint if already present
  if "chat.js" in html:
    html = re.sub(r'(chat\.js\}\})[^"]*', r'\1?v=' + STAMP, html)
  else:
    inj = f'<script>window.CURRENT_USER_NAME = "{{{{ current_user_name }}}}";</script>\n<script src="{{{{ url_for(\'static\', filename=\'chat.js\') }}}}?v={STAMP}"></script>'
    html = re.sub(r"</body\s*>", lambda m: inj + "\n</body>", html, count=1, flags=re.I) or (html + "\n" + inj + "\n")
  return html

def inject_fab(html: str) -> str:
  cleaned = strip_legacy_panels(html)
  if re.search(r"</body\s*>", cleaned, re.I):
    return re.sub(r"</body\s*>", lambda m: FAB_MARKUP + "\n</body>", cleaned, count=1, flags=re.I)
  return cleaned + "\n" + FAB_MARKUP + "\n"

changed = []
if not tpl_dir.exists():
  raise SystemExit("No templates/ directory found.")

for file in sorted(tpl_dir.rglob("*.html")):
  txt = file.read_text(encoding="utf-8", errors="ignore")
  orig = txt

  # remove any stray "1{{ ... }}" artifacts once more
  txt = re.sub(r"(?:\\1|(?<!\\)\b1)\s*(\{\{[^}]+\}\})", r"\1", txt)

  txt = ensure_head_css(txt)
  txt = ensure_footer_scripts(txt)
  txt = inject_fab(txt)

  if txt != orig:
    file.with_suffix(file.suffix + ".bak_hover").write_text(orig, encoding="utf-8")
    file.write_text(txt, encoding="utf-8")
    changed.append(str(file.relative_to(root)))

print("Hover chat UI applied.")
if changed:
  print("Templates updated:")
  for c in changed:
    print(" -", c)
else:
  print("No template changes were needed (UI may already be injected).")
