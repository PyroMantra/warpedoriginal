(() => {
  const norm = (s) => (s || '').toString().trim().toLowerCase();

  const rarityStyles = {
    common:    { bg: 'rgba(255,255,255,0.04)', border: 'rgba(255,255,255,0.16)', text: 'rgba(255,255,255,0.9)' },
    uncommon:  { bg: 'rgba(34,197,94,0.12)',  border: 'rgba(34,197,94,0.38)',  text: 'rgba(220,252,231,0.95)' },
    rare:      { bg: 'rgba(59,130,246,0.14)', border: 'rgba(59,130,246,0.42)', text: 'rgba(219,234,254,0.95)' },
    epic:      { bg: 'rgba(168,85,247,0.14)', border: 'rgba(168,85,247,0.42)', text: 'rgba(243,232,255,0.95)' },
    legendary: { bg: 'rgba(245,158,11,0.14)', border: 'rgba(245,158,11,0.45)', text: 'rgba(255,247,237,0.95)' },
    mythic:    { bg: 'rgba(239,68,68,0.14)',  border: 'rgba(239,68,68,0.45)',  text: 'rgba(254,226,226,0.95)' },
    astral:    { bg: 'rgba(139,92,246,0.16)', border: 'rgba(139,92,246,0.55)', text: 'rgba(237,233,254,0.98)' },
  };

  function applyPill(el, key) {
    const st = rarityStyles[key];
    if (!st) return;
    el.style.background = st.bg;
    el.style.border = `1px solid ${st.border}`;
    el.style.color = st.text;
    el.style.padding = '0.15rem 0.55rem';
    el.style.borderRadius = '9999px';
    el.style.display = 'inline-flex';
    el.style.alignItems = 'center';
    el.style.gap = '0.35rem';
    el.style.fontSize = '0.75rem';
    el.style.lineHeight = '1.1';
    el.style.whiteSpace = 'nowrap';
  }

  function colorCodeRarityTokens(root=document) {
    // Targets small tokens/badges that are exactly a rarity word.
    const candidates = root.querySelectorAll('span,div,p,small');
    for (const el of candidates) {
      const t = norm(el.textContent);
      if (!t) continue;
      if (rarityStyles[t]) {
        // don't restyle large blocks
        if ((el.textContent || '').length > 20) continue;
        applyPill(el, t);
      }
    }
  }

  function removeRollingLog(root=document) {
    // Remove any card/section that looks like "Rolling Log".
    const all = root.querySelectorAll('*');
    for (const el of all) {
      const t = norm(el.textContent);
      if (t === 'rolling log' || t === 'rolling-log' || t.includes('rolling log')) {
        // Find a reasonable container to remove.
        const container = el.closest('details') || el.closest('section') || el.closest('div');
        if (container) {
          // avoid deleting the whole page
          if (container.querySelectorAll('h1,h2').length) continue;
          container.remove();
          return; // usually only one
        }
      }
    }
  }

  function expandAbilities(root=document) {
    // Try to let Abilities card span full width if it lives in a grid.
    const headings = root.querySelectorAll('h1,h2,h3,h4,div,span');
    for (const el of headings) {
      const t = norm(el.textContent);
      if (t === 'abilities' || t.includes('abilities')) {
        const card = el.closest('section') || el.closest('div');
        if (!card) continue;
        // If card is in a CSS grid, spanning all columns helps.
        card.style.gridColumn = '1 / -1';
        card.style.minHeight = 'unset';
        break;
      }
    }
  }

  function injectSmallStyle() {
    const id = 'sentient-pretty-style';
    if (document.getElementById(id)) return;
    const style = document.createElement('style');
    style.id = id;
    style.textContent = `
      /* make abilities text breathe a bit */
      .abilities-card, [data-section="abilities"] { line-height: 1.35; }
    `;
    document.head.appendChild(style);
  }

  function run() {
    injectSmallStyle();
    removeRollingLog();
    colorCodeRarityTokens();
    expandAbilities();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', run);
  } else {
    run();
  }
})();
