/* Difficulty color-coding for Quests tables and Random Quests cards.
   Easy = green, Medium = yellow, Hard = red
   Robust to markup differences.
*/
(function () {
  function norm(s){
    return (s||"").toString().trim().toLowerCase();
  }
  function difficultyInfo(raw){
    const d = norm(raw);
    if (d === "e" || d.startsWith("easy")) return {key:"easy", label:"Easy"};
    if (d.startsWith("medium") || d === "med" || d === "m") return {key:"medium", label:"Medium"};
    if (d.startsWith("hard") || d === "h") return {key:"hard", label:"Hard"};
    return null;
  }

  function ensureStyles(){
    if (document.getElementById("difficulty-colors-style")) return;
    const style = document.createElement("style");
    style.id = "difficulty-colors-style";
    style.textContent = `
      .difficulty-pill{
        display:inline-flex;
        align-items:center;
        gap:.45rem;
        padding:.2rem .55rem;
        border-radius:999px;
        border:1px solid rgba(255,255,255,.12);
        font-weight:600;
        font-size:.85rem;
        line-height:1.2;
        white-space:nowrap;
      }
      .difficulty-dot{ width:.45rem;height:.45rem;border-radius:999px; background:currentColor; opacity:.9; }

      /* Table row accent */
      tr.difficulty-easy{ box-shadow: inset 3px 0 0 rgba(35,166,80,.9); }
      tr.difficulty-medium{ box-shadow: inset 3px 0 0 rgba(255,196,0,.9); }
      tr.difficulty-hard{ box-shadow: inset 3px 0 0 rgba(240,68,56,.9); }

      /* Card accent */
      .quest-card.difficulty-easy, .card.difficulty-easy, .result-card.difficulty-easy{ box-shadow: inset 4px 0 0 rgba(35,166,80,.9); }
      .quest-card.difficulty-medium, .card.difficulty-medium, .result-card.difficulty-medium{ box-shadow: inset 4px 0 0 rgba(255,196,0,.9); }
      .quest-card.difficulty-hard, .card.difficulty-hard, .result-card.difficulty-hard{ box-shadow: inset 4px 0 0 rgba(240,68,56,.9); }

      /* Pill colors */
      .difficulty-easy .difficulty-pill{ background: rgba(35,166,80,.18); border-color: rgba(35,166,80,.55); color:#d7ffe4; }
      .difficulty-medium .difficulty-pill{ background: rgba(255,196,0,.18); border-color: rgba(255,196,0,.55); color:#fff0bf; }
      .difficulty-hard .difficulty-pill{ background: rgba(240,68,56,.18); border-color: rgba(240,68,56,.55); color:#ffe0dd; }
    `;
    document.head.appendChild(style);
  }

  function findDifficultyColumn(table){
    const thead = table.querySelector("thead");
    const headerCells = (thead ? thead.querySelectorAll("th") : table.querySelectorAll("tr th"));
    if (!headerCells || headerCells.length === 0) return -1;
    let idx = -1;
    headerCells.forEach((th, i) => {
      const t = norm(th.textContent);
      if (t === "difficulty" || t.includes("difficulty")) idx = i;
    });
    return idx;
  }

  function makePill(label){
    const pill = document.createElement("span");
    pill.className = "difficulty-pill";
    const dot = document.createElement("span");
    dot.className = "difficulty-dot";
    pill.appendChild(dot);
    const txt = document.createElement("span");
    txt.textContent = label;
    pill.appendChild(txt);
    return pill;
  }

  function prettifyTableQuests(){
    const tables = Array.from(document.querySelectorAll("table"));
    if (!tables.length) return;
    ensureStyles();

    tables.forEach(table => {
      const idx = findDifficultyColumn(table);
      if (idx < 0) return;

      const rows = Array.from(table.querySelectorAll("tbody tr"));
      rows.forEach(tr => {
        const cells = tr.querySelectorAll("td");
        if (!cells || cells.length <= idx) return;
        const cell = cells[idx];
        const info = difficultyInfo(cell.textContent);
        if (!info) return;

        tr.classList.add("difficulty-" + info.key);

        const pill = makePill((cell.textContent || info.label).trim() || info.label);
        cell.textContent = "";
        cell.appendChild(pill);
      });
    });
  }

  function styleCard(card, info){
    if (!card || !info) return;
    card.classList.add("difficulty-" + info.key);
  }

  function prettifyRandomQuests(){
    ensureStyles();

    // 1) data-difficulty attribute
    const nodes = Array.from(document.querySelectorAll("[data-difficulty]"));
    nodes.forEach(el => {
      const info = difficultyInfo(el.getAttribute("data-difficulty"));
      if (!info) return;
      const card = el.closest(".quest-card, .card, .result-card, .panel") || el.parentElement;
      styleCard(card, info);

      // Replace badge contents with our pill
      if (!el.classList.contains("difficulty-pill")){
        const pill = makePill((el.textContent || info.label).trim() || info.label);
        el.replaceWith(pill);
      }
    });

    // 2) "Difficulty: X" lines
    const textEls = Array.from(document.querySelectorAll("body *")).filter(el => {
      if (el.children && el.children.length) return false;
      const t = (el.textContent || "").trim();
      return /^difficulty\s*[:\-]/i.test(t);
    });

    textEls.forEach(el => {
      const t = el.textContent || "";
      const m = t.match(/difficulty\s*[:\-]\s*(easy|medium|med|hard)/i);
      if (!m) return;
      const info = difficultyInfo(m[1]);
      if (!info) return;

      const card = el.closest(".quest-card, .card, .result-card, .panel") || el.parentElement;
      styleCard(card, info);

      el.textContent = "Difficulty: ";
      el.appendChild(makePill(info.label));
    });

    // 3) Existing small badges with just "Easy/Medium/Hard" (your Random Quests layout)
    const candidateBadges = Array.from(document.querySelectorAll(".quest-card *, .card *, .result-card *")).filter(el => {
      if (el.children && el.children.length) return false;
      const t = (el.textContent || "").trim();
      if (!t) return false;
      const info = difficultyInfo(t);
      if (!info) return false;
      // heuristics: badge-like: short text and either has a class hint or is a <span>
      const tag = (el.tagName || "").toLowerCase();
      const cls = (el.className || "").toString().toLowerCase();
      const looksBadge = tag === "span" || cls.includes("badge") || cls.includes("pill") || cls.includes("tag") || cls.includes("difficulty");
      return looksBadge;
    });

    candidateBadges.forEach(el => {
      const info = difficultyInfo((el.textContent || "").trim());
      if (!info) return;
      const card = el.closest(".quest-card, .card, .result-card, .panel") || el.parentElement;
      styleCard(card, info);

      // Replace the element itself with our pill
      const pill = makePill(info.label);
      el.replaceWith(pill);
    });
  }

  function run(){
    prettifyTableQuests();
    prettifyRandomQuests();
  }

  if (document.readyState === "loading"){
    document.addEventListener("DOMContentLoaded", run);
  } else {
    run();
  }
})();
