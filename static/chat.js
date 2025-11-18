(function(){
  function byId(id){return document.getElementById(id);}
  function escapeHtml(s){var d=document.createElement("div"); d.innerText=s; return d.innerHTML;}
  function appendMsg(list, u, t, ts, id){
    if(!list) return;
    var d=document.createElement("div");
    d.className="chat-msg";
    if(id) { try{ d.dataset.id = id; }catch(_){ d.setAttribute("data-id", id); } }
    if(ts) { try{ d.dataset.ts = ts; }catch(_){ d.setAttribute("data-ts", ts); } }
    d.innerHTML='<span class="u">'+escapeHtml(u)+':</span><span class="t">'+escapeHtml(t)+'</span>';
    list.appendChild(d);
    list.scrollTop=list.scrollHeight;
  }
  function init(){
    const box = byId("global-chat"); if(!box) return;
    const list = box.querySelector("#chat-messages") || byId("chat-messages");
    window.__chatSeenIds = window.__chatSeenIds || new Set();
    function genId(){ return Date.now().toString(36)+Math.random().toString(36).slice(2,7); }
    function markSeen(id){ if(id) try{ window.__chatSeenIds.add(id); }catch(_){ window.__chatSeenIds[id]=true; } }
    function hasSeen(id){ if(!id) return false; try{ return window.__chatSeenIds.has(id); }catch(_){ return !!window.__chatSeenIds[id]; } }
    const form = byId("chat-form");
    const input = byId("chat-input");
    const me = (window.CURRENT_USER_NAME || "Anonymous");
    const socket = io({transports:["websocket","polling"]});

    let gotHistory = false;

    socket.on("connect", ()=>{ window.__chatSquelchUnread = true;
      console.log("[chat] connected", socket.id);
      if(box.classList.contains('minimized') && typeof setUnread==='function'){ setUnread(0); }
      // fallback: if no history after 1s, explicitly ask for it
      setTimeout(()=>{ if(!gotHistory) { console.log("[chat] requesting history"); socket.emit("chat_history_request"); }}, 1000);
    });
    socket.on("connect_error", e=> console.error("[chat] connect_error", e));

    socket.on("chat_ready", ()=> console.log("[chat] ready"));
    socket.on("chat_history", items=>{ window.__chatSquelchUnread = true;
      window.__chatSquelchUnread = true;
gotHistory = true;
      console.log("[chat] history", items?.length||0);
      if(list) list.innerHTML="";
      (items||[]).forEach(m=>appendMsg(list, m.user, m.text));
      if(box.classList.contains('minimized') && typeof setUnread==='function'){ setUnread(0); }
      window.__chatSquelchUnread = false;
    });
    socket.on("chat_message", m=>{
      console.log("[chat] message", m);
      const id = m && m.id;
      if(id && hasSeen(id)) return;
      if(id) markSeen(id);
      let updated = false;
      if(id && list){
        const exist = list.querySelector('.chat-msg[data-id="'+id+'"]');
        if(exist){
          const uEl = exist.querySelector('.u');
          const tEl = exist.querySelector('.t');
          if(uEl) uEl.textContent = (m.user||'')+":";
          if(tEl) tEl.textContent = m.text || "";
          try{ exist.dataset.ts = m.ts || new Date().toISOString(); }catch(_){ exist.setAttribute("data-ts", m.ts || new Date().toISOString()); }
          exist.classList.remove("pending");
          updated = true;
        }
      }
      if(!updated){ appendMsg(list, m.user, m.text, m.ts, id); }
    });

    form.addEventListener("submit", e=>{
      e.preventDefault();
      const text=(input.value||"").trim();
      if(!text) return;
      const id = genId();
      socket.emit("chat_message", {text, id});
      appendMsg(list, me, text, new Date().toISOString(), id);
      const last = list && list.lastElementChild; if(last) last.classList.add("pending");
      markSeen(id);
      input.value="";
    });
  }
  if(document.readyState==="loading"){ document.addEventListener("DOMContentLoaded", init); }
  else { init(); }
})();

//
// [drag-movable-chat] v1 — draggable global chat by header (mouse + touch)
//
(function(){
  function initDraggable(){
    var el = document.getElementById('global-chat');
    if(!el) return;
    var handle = el.querySelector('.chat-header') || el;

    try{
      var pos = JSON.parse(localStorage.getItem('globalChatPos') || 'null');
      if(pos && typeof pos.left==='number' && typeof pos.top==='number'){
        el.style.right = 'auto'; el.style.bottom = 'auto';
        el.style.left  = pos.left + 'px';
        el.style.top   = pos.top  + 'px';
      }
    }catch(e){}

    function clamp(v,min,max){ return Math.max(min, Math.min(max, v)); }

    var dragging=false, sx=0, sy=0, startL=0, startT=0, pid=null;

    function startFromRect(){
      var r = el.getBoundingClientRect();
      if(!el.style.left || !el.style.top){
        el.style.left = r.left + 'px';
        el.style.top  = r.top  + 'px';
        el.style.right='auto';
        el.style.bottom='auto';
      }
      startL = parseFloat(el.style.left) || r.left;
      startT = parseFloat(el.style.top)  || r.top;
    }

    function onDown(e){
      dragging = true;
      var cx = (e.clientX != null) ? e.clientX : (e.touches && e.touches[0].clientX) || 0;
      var cy = (e.clientY != null) ? e.clientY : (e.touches && e.touches[0].clientY) || 0;
      sx = cx; sy = cy;
      startFromRect();
      handle.classList.add('dragging');
      if(e.target && e.target.setPointerCapture && e.pointerId !== undefined){
        pid = e.pointerId; try{ e.target.setPointerCapture(pid); }catch(_){}
      }
      e.preventDefault();
    }

    function onMove(e){
      if(!dragging) return;
      var cx = (e.clientX != null) ? e.clientX : (e.touches && e.touches[0].clientX) || 0;
      var cy = (e.clientY != null) ? e.clientY : (e.touches && e.touches[0].clientY) || 0;
      var nl = startL + (cx - sx);
      var nt = startT + (cy - sy);
      var maxL = window.innerWidth  - el.offsetWidth;
      var maxT = window.innerHeight - el.offsetHeight;
      el.style.left = clamp(nl, 0, maxL) + 'px';
      el.style.top  = clamp(nt, 0, maxT) + 'px';
    }

    function onUp(){
      if(!dragging) return;
      dragging = false;
      handle.classList.remove('dragging');
      try{
        localStorage.setItem('globalChatPos', JSON.stringify({
          left: parseFloat(el.style.left) || 0,
          top:  parseFloat(el.style.top)  || 0
        }));
      }catch(_){}
    }

    if(window.PointerEvent){
      handle.addEventListener('pointerdown', onDown);
      window.addEventListener('pointermove', onMove);
      window.addEventListener('pointerup', onUp);
      window.addEventListener('pointercancel', onUp);
    } else {
      handle.addEventListener('mousedown', onDown);
      window.addEventListener('mousemove', onMove);
      window.addEventListener('mouseup', onUp);
      handle.addEventListener('touchstart', onDown, {passive:false});
      window.addEventListener('touchmove', onMove, {passive:false});
      window.addEventListener('touchend', onUp);
      window.addEventListener('touchcancel', onUp);
    }

    handle.style.userSelect = 'none';
    handle.style.touchAction = 'none';
    if(!handle.style.cursor) handle.style.cursor = 'move';
  }

  if(document.readyState === 'loading'){
    document.addEventListener('DOMContentLoaded', initDraggable);
  } else {
    initDraggable();
  }
})();


//
// [chat-minimize-enter-send] — adds Minimize toggle + Enter-to-send (keeps Shift+Enter for newline)
//
(function(){
  function initMinimizeAndEnterSend(){
    var box = document.getElementById('global-chat');
    if(!box) return;

    var header = box.querySelector('.chat-header') || box;
    var stateKey = 'globalChatMinimized';
    // Bubble minimization
    var bubbleId = 'global-chat-bubble';
    var unread = 0;
    var bubble = null;
    var list = box.querySelector('#chat-messages') || box.querySelector('.messages');

    function injectBubbleStyles(){
      if(document.getElementById('chat-bubble-styles')) return;
      var css = [
        '#'+bubbleId+'{position:fixed;bottom:16px;right:16px;width:56px;height:56px;border-radius:9999px;',
        'background:rgba(255,255,255,0.12);backdrop-filter:blur(6px);color:#fff;display:flex;align-items:center;justify-content:center;',
        'box-shadow:0 6px 20px rgba(0,0,0,0.35);cursor:pointer;user-select:none;z-index:99999;',
        'border:1px solid rgba(255,255,255,0.2);}',
        '#'+bubbleId+':hover{background:rgba(255,255,255,0.18);}',
        '#'+bubbleId+' .dot{position:absolute;top:-4px;right:-4px;min-width:22px;height:22px;padding:0 6px;border-radius:9999px;',
        'background:#ef4444;display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:700;}'
      ].join('');
      var style = document.createElement('style');
      style.id = 'chat-bubble-styles';
      style.textContent = css;
      document.head.appendChild(style);
    }

    function setUnread(n){
      unread = Math.max(0, n|0);
      if(!bubble) return;
      var dot = bubble.querySelector('.dot');
      if(unread > 0){
        if(!dot){ dot = document.createElement('div'); dot.className = 'dot'; bubble.appendChild(dot); }
        dot.textContent = String(unread);
      } else if(dot){ dot.remove(); }
    }

    function ensureBubble(){
      injectBubbleStyles();
      if(bubble) return bubble;
      bubble = document.createElement('div');
      bubble.id = bubbleId;
      bubble.setAttribute('aria-label','Open chat');
      bubble.title = 'Open chat';
      bubble.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="26" height="26" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M20 2H4a2 2 0 0 0-2 2v14l4-4h14a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2z"/></svg>';
      bubble.addEventListener('click', function(){
        setMinimized(false);
      });
      document.body.appendChild(bubble);
      setUnread(unread);
      return bubble;
    }

    function removeBubble(){
      if(bubble && bubble.parentNode){ bubble.parentNode.removeChild(bubble); }
      bubble = null;
      setUnread(0);
    }


    // Heuristics to find parts
    var body = box.querySelector('.chat-body') ||
               box.querySelector('.chat-content') ||
               box.querySelector('.messages') ||
               box.querySelector('.chat-inner') ||
               null;

    // Try to find the Minimize button by common hooks or its label text
    function findButtonByText(root, text){
      text = (text||'').toLowerCase();
      var nodes = root.querySelectorAll('button,[role="button"],.btn');
      for (var i=0;i<nodes.length;i++){
        var n = nodes[i];
        var d = (n.getAttribute('data-action')||'').toLowerCase();
        var t = (n.textContent||'').trim().toLowerCase();
        if (d.indexOf('minimize')>-1 || d.indexOf('minimise')>-1 || t === 'minimize' || t === 'minimise') return n;
      }
      return null;
    }
   var minimizeBtn = header.querySelector('#chat-min, [data-action="minimize"], .minimize')
  || findButtonByText(header, 'minimize');

    // Restore minimized state
    try {
      var saved = localStorage.getItem(stateKey);
      if(saved === '1' || saved === 'true'){ setMinimized(true); }
      else { setMinimized(false); }
    } catch(e){}

    function setMinimized(min){
      if(min){
        box.classList.add('minimized');
        header.setAttribute('aria-expanded','false');
        try{ localStorage.setItem(stateKey,'1'); }catch(_){}
        box.style.display = 'none';
        ensureBubble();
      } else {
        box.classList.remove('minimized');
        header.setAttribute('aria-expanded','true');
        try{ localStorage.setItem(stateKey,'0'); }catch(_){}
        box.style.display = '';
        removeBubble();
      }
    }

    // Click to toggle
    if(minimizeBtn){
      minimizeBtn.addEventListener('click', function(ev){ ev.preventDefault(); setMinimized(!box.classList.contains('minimized')); });
      minimizeBtn.classList.add('minimize-toggle');
      if(!minimizeBtn.getAttribute('title')) minimizeBtn.setAttribute('title','Minimize/Expand chat');
      minimizeBtn.setAttribute('aria-controls','global-chat');
      minimizeBtn.setAttribute('aria-expanded', !box.classList.contains('minimized'));
    } else {
      // Fallback: double-click header toggles
      header.addEventListener('dblclick', function(){ setMinimized(!box.classList.contains('minimized')); });
    }

    // ENTER to send (Shift+Enter = newline)
    var input = box.querySelector('textarea, input[type="text"], [contenteditable="true"]');
    var sendBtn = box.querySelector('#chat-send, [data-action="send"], button[type="submit"]') || findButtonByText(box, 'send');
    var form = input ? input.closest && input.closest('form') : null;
    // Unread counter via DOM observer
    if(list && 'MutationObserver' in window){
      window.__chatSquelchUnread = false;
      var obs = new MutationObserver(function(muts){
        if(!box.classList.contains('minimized')) return;
        if(window.__chatSquelchUnread) return;
        var inc = 0;
        muts.forEach(function(m){ if(m.addedNodes && m.addedNodes.length){ inc += m.addedNodes.length; } });
        if(inc>0){ setUnread(unread + inc); ensureBubble(); }
      });
      obs.observe(list, {childList:true});
    }


    function doSend(){
      // Prefer form submission if present
      if(form){
        var ev = new Event('submit', {bubbles:true, cancelable:true});
        var notCanceled = form.dispatchEvent(ev) !== false;
        return;
      }
      if(sendBtn){ sendBtn.click(); return; }
      // Last resort: emit a custom event the app can listen for
      box.dispatchEvent(new CustomEvent('chat:send', {bubbles:true}));
    }

    if(input){
      input.addEventListener('keydown', function(e){
        // Ignore IME composition
        if(e.isComposing) return;
        if(e.key === 'Enter' && !e.shiftKey && !e.ctrlKey && !e.altKey && !e.metaKey){
          e.preventDefault();
          doSend();
        }
      });
    }
  }

  if(document.readyState === 'loading'){
    document.addEventListener('DOMContentLoaded', initMinimizeAndEnterSend);
  } else {
    initMinimizeAndEnterSend();
  }
})();

