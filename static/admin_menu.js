
/* admin_menu.js (v2) — robust dropdown on existing username chip
   - Stops default navigation on the chip (even if it's a link)
   - Stops event bubbling so header/global handlers don't fire
   - Keeps dropdown open until you click elsewhere or press Esc
*/
(function(){
  function ready(fn){ if(document.readyState!=='loading'){fn();} else {document.addEventListener('DOMContentLoaded',fn);}}
  function text(node){ return (node.textContent||'').replace(/\s+/g,' ').trim(); }

  function findChip(name){
    if(!name) return null;
    const all = Array.from(document.querySelectorAll('a,button,[role="button"],.chip,.tag,div,span'));
    const candidates = all.filter(n => text(n) === name);
    if(!candidates.length) return null;
    // Prefer the one closest to the top-right
    candidates.sort((a,b)=>{
      const ra=a.getBoundingClientRect(), rb=b.getBoundingClientRect();
      const ar = (window.innerWidth - ra.right), br = (window.innerWidth - rb.right);
      return (ar - br) || (ra.top - rb.top);
    });
    return candidates[0];
  }

  function buildDropdown(isAdmin){
    const dd = document.createElement('div');
    dd.className = 'user-dd';
    dd.setAttribute('role','menu');
    dd.setAttribute('aria-hidden','true');
    dd.innerHTML = (isAdmin ? '<a href="/admin" role="menuitem">⚙️ Admin Panel</a>' : '')
                 + '<a href="/logout" role="menuitem">🚪 Log out</a>';
    document.body.appendChild(dd);

    const css = `.user-dd{position:absolute;min-width:220px;display:none;
      background:#1f1f1f;color:#fff;border:1px solid #333;border-radius:10px;
      box-shadow:0 10px 30px rgba(0,0,0,.4);z-index:3000}
      .user-dd a{display:block;padding:10px 12px;text-decoration:none;color:#fff;border-bottom:1px solid #2a2a2a}
      .user-dd a:last-child{border-bottom:none}`;
    const s = document.createElement('style'); s.textContent = css; document.head.appendChild(s);
    return dd;
  }

  ready(function(){
    const name = (window.CURRENT_USER_NAME || '').trim();
    const isAdmin = !!window.IS_ADMIN;
    const chip = findChip(name);
    if(!chip) return;

    // ensure the chip looks/acts like a button
    chip.setAttribute('aria-haspopup','true');
    chip.setAttribute('aria-expanded','false');
    chip.style.cursor = 'pointer';

    const dd = buildDropdown(isAdmin);
    let open = false;

    function position(){
      const r = chip.getBoundingClientRect();
      const top = r.bottom + 8 + window.scrollY;
      const left = Math.max(8, Math.min(window.scrollX + r.right - dd.offsetWidth, window.scrollX + r.left));
      dd.style.top = top + 'px';
      dd.style.left = left + 'px';
    }
    function setOpen(v){
      open = v;
      chip.setAttribute('aria-expanded', String(v));
      if(v){ position(); dd.style.display = 'block'; dd.setAttribute('aria-hidden','false'); }
      else { dd.style.display = 'none';  dd.setAttribute('aria-hidden','true'); }
    }

    // Prevent navigation + bubbling on the chip completely
    ['click','mousedown','mouseup'].forEach(evt=>{
      chip.addEventListener(evt, function(e){
        e.preventDefault();
        e.stopPropagation();
        if(evt === 'click') setOpen(!open);
      }, true); // capture so we beat other handlers
    });

    // Stop bubbling inside dropdown so it doesn't close itself
    ['click','mousedown','mouseup'].forEach(evt=>{
      dd.addEventListener(evt, function(e){ e.stopPropagation(); }, true);
    });

    // Global close
    document.addEventListener('click', function(){ if(open) setOpen(false); }, true);
    document.addEventListener('keydown', function(e){ if(e.key === 'Escape') setOpen(false); });

    window.addEventListener('resize', function(){ if(open) position(); });
    window.addEventListener('scroll', function(){ if(open) position(); }, true);
  });
})();
