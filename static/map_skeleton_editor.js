(function () {
  const root = document.getElementById('map-editor-root');
  if (!root) return;

  const mapName = root.dataset.mapName;
  const roleColors = JSON.parse(root.dataset.roleColors || '{}');
  const roleDefaults = JSON.parse(root.dataset.roleDefaults || '{}');
  const gridEl = document.getElementById('hex-grid');
  const gridWrapEl = document.getElementById('hex-grid-wrap');
  const paletteEl = document.getElementById('role-palette');
  const saveBtn = document.getElementById('save-map-btn');
  const applyBtn = document.getElementById('apply-cell-btn');
  const descEl = document.getElementById('map-description');
  const summaryEl = document.getElementById('selected-summary');
  const modePaintBtn = document.getElementById('mode-paint-btn');
  const modeSelectBtn = document.getElementById('mode-select-btn');
  const modeHelpPaint = document.getElementById('mode-help-paint');
  const modeHelpSelect = document.getElementById('mode-help-select');

  const regionEl = document.getElementById('cell-region');
  const specialEl = document.getElementById('cell-special');
  const spawnEl = document.getElementById('cell-spawn');
  const biomesEl = document.getElementById('cell-allow-biomes');
  const landmarksEl = document.getElementById('cell-allow-landmarks');
  const entitiesEl = document.getElementById('cell-allow-entities');

  const GAP_X = 4;
  const GAP_Y = 4;
  const MIN_HEX_W = 34;
  const MAX_HEX_W = 82;
  const HEX_BORDER = '1.5px solid rgba(22, 22, 26, 0.88)';
  const HEX_CLIP = 'polygon(50% 1.5%, 95% 25%, 95% 75%, 50% 98.5%, 5% 75%, 5% 25%)';
  const HEX_SHADOW_NORMAL = 'inset 0 1px 0 rgba(255,255,255,0.05)';
  const HEX_SHADOW_SELECTED = 'inset 0 0 0 2px rgba(255,255,255,0.98), inset 0 0 0 6px rgba(59,130,246,0.78), 0 0 0 2px rgba(255,255,255,0.92), 0 0 0 5px rgba(59,130,246,0.45), 0 0 14px rgba(59,130,246,0.42)';

  let state = null;
  let currentRole = 'outer_area';
  let selectedKey = null;
  let selectedKeys = new Set();
  let isPainting = false;
  let editorMode = 'paint';
  let inspectorDirty = new Set();
  let dims = {
    hexW: 56,
    hexH: 64,
    rowOffset: 30,
    rowOverlap: 12,
    coordFont: 8,
    labelFont: 14,
  };

  function key(row, col) { return `${row}:${col}`; }

  function clamp(v, lo, hi) {
    return Math.max(lo, Math.min(hi, v));
  }

  function computeDims() {
    const available = Math.max(420, (gridWrapEl?.clientWidth || root.clientWidth || 1200) - 8);
    const cols = Math.max(1, state?.width || 1);
    const usable = available - GAP_X * Math.max(0, cols - 1);
    const hexW = clamp(Math.floor(usable / (cols + 0.52)), MIN_HEX_W, MAX_HEX_W);
    const hexH = Math.round((hexW * 2 / Math.sqrt(3)) * 100) / 100;
    const rowOffset = (hexW + GAP_X) / 2;
    const rowStep = hexH * 0.75 + GAP_Y;
    const rowOverlap = Math.max(0, hexH - rowStep);
    const coordFont = clamp(Math.round(hexW * 0.15), 7, 12);
    const labelFont = clamp(Math.round(hexW * 0.26), 11, 20);
    dims = { hexW, hexH, rowOffset, rowOverlap, coordFont, labelFont };
  }

  function showToast(text, ok = true) {
    let el = document.getElementById('map-editor-toast');
    if (!el) {
      el = document.createElement('div');
      el.id = 'map-editor-toast';
      el.style.position = 'fixed';
      el.style.right = '20px';
      el.style.bottom = '20px';
      el.style.zIndex = '9999';
      el.style.padding = '12px 16px';
      el.style.borderRadius = '14px';
      el.style.fontWeight = '700';
      el.style.boxShadow = '0 20px 40px rgba(0,0,0,.35)';
      document.body.appendChild(el);
    }
    el.textContent = text;
    el.style.background = ok ? 'rgba(16,185,129,.95)' : 'rgba(239,68,68,.95)';
    el.style.color = '#111827';
    clearTimeout(el._t);
    el._t = setTimeout(() => {
      el.textContent = '';
      el.style.padding = '0';
    }, 1800);
  }

  function buildMapIndex() {
    state.cellsByKey = {};
    state.cells.forEach(c => {
      if (c.role === 'void') c.role = 'empty';
      state.cellsByKey[key(c.row, c.col)] = c;
    });
  }

  function setMode(mode) {
    editorMode = mode === 'select' ? 'select' : 'paint';
    const paintActive = editorMode === 'paint';
    modePaintBtn.className = paintActive
      ? 'rounded-xl px-3 py-3 text-sm font-semibold text-white bg-violet-500/90 ring-1 ring-violet-300/40'
      : 'rounded-xl px-3 py-3 text-sm font-semibold text-white bg-white/5 ring-1 ring-white/10';
    modeSelectBtn.className = !paintActive
      ? 'rounded-xl px-3 py-3 text-sm font-semibold text-white bg-violet-500/90 ring-1 ring-violet-300/40'
      : 'rounded-xl px-3 py-3 text-sm font-semibold text-white bg-white/5 ring-1 ring-white/10';
    modeHelpPaint.classList.toggle('hidden', !paintActive);
    modeHelpSelect.classList.toggle('hidden', paintActive);
  }

  function paintCell(cell, role) {
    const defaults = roleDefaults[role] || roleDefaults['empty'];
    cell.role = role;
    if (role === 'connector') {
      cell.region = '';
    }
    cell.active = !!defaults.active;
    cell.spawn = !!defaults.spawn;
    cell.allow_biomes = !!defaults.allow_biomes;
    cell.allow_landmarks = !!defaults.allow_landmarks;
    cell.allow_entities = !!defaults.allow_entities;
    if (defaults.special !== undefined) {
      cell.special = defaults.special;
    }
    updateHexVisual(cell);
    if (selectedKeys.has(key(cell.row, cell.col))) fillInspectorFromSelection();
  }

  function hexLabel(cell) {
    if (cell.role === 'spawn') return 'S';
    if (cell.role === 'center_core') return 'C';
    if (cell.role === 'center_ring') return 'R';
    if (cell.role === 'connector') return 'X';
    if (cell.role === 'core_area') return 'M';
    return '';
  }

  function updateHexVisual(cell) {
    const el = gridEl.querySelector(`[data-k="${key(cell.row, cell.col)}"]`);
    if (!el) return;
    const color = roleColors[cell.role] || '#334155';
    const isSelected = selectedKeys.has(key(cell.row, cell.col));
    el.style.background = color;
    el.style.opacity = cell.active ? '1' : '0.28';
    el.querySelector('.hex-label').textContent = hexLabel(cell);
    el.querySelector('.hex-coord').textContent = `${cell.row},${cell.col}`;
    el.style.border = isSelected ? '2px solid rgba(255,255,255,0.98)' : HEX_BORDER;
    el.style.boxShadow = isSelected ? HEX_SHADOW_SELECTED : HEX_SHADOW_NORMAL;
    el.style.zIndex = isSelected ? '6' : '1';
  }

  function renderPalette() {
    paletteEl.innerHTML = '';
    Object.keys(roleDefaults).forEach(role => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'rounded-xl px-3 py-3 text-sm font-semibold text-white ring-1 ring-white/10 hover:ring-white/30 transition text-left';
      btn.style.background = roleColors[role] || '#334155';
      btn.textContent = role;
      btn.addEventListener('click', () => {
        currentRole = role;
        [...paletteEl.children].forEach(x => x.classList.remove('outline', 'outline-2', 'outline-white'));
        btn.classList.add('outline', 'outline-2', 'outline-white');
      });
      if (role === currentRole) btn.classList.add('outline', 'outline-2', 'outline-white');
      paletteEl.appendChild(btn);
    });
  }

  function updateSelection(cell, additive) {
    const k = key(cell.row, cell.col);
    selectedKey = k;
    if (additive) {
      if (selectedKeys.has(k)) selectedKeys.delete(k);
      else selectedKeys.add(k);
      if (selectedKeys.size === 0) selectedKeys.add(k);
    } else {
      selectedKeys = new Set([k]);
    }
    renderSelection();
  }

  function renderGrid() {
    computeDims();
    gridEl.innerHTML = '';

    for (let row = 0; row < state.height; row++) {
      const rowEl = document.createElement('div');
      rowEl.className = 'hex-row flex';
      rowEl.style.columnGap = `${GAP_X}px`;
      rowEl.style.marginLeft = (row % 2 ? `${dims.rowOffset}px` : '0px');
      rowEl.style.marginBottom = `-${dims.rowOverlap}px`;

      for (let col = 0; col < state.width; col++) {
        const cell = state.cellsByKey[key(row, col)];
        const cellEl = document.createElement('button');
        cellEl.type = 'button';
        cellEl.dataset.k = key(row, col);
        cellEl.className = 'relative font-bold text-zinc-950 focus:outline-none';
        cellEl.style.width = `${dims.hexW}px`;
        cellEl.style.height = `${dims.hexH}px`;
        cellEl.style.minWidth = `${dims.hexW}px`;
        cellEl.style.clipPath = HEX_CLIP;
        cellEl.style.border = HEX_BORDER;
        cellEl.style.boxSizing = 'border-box';
        cellEl.style.boxShadow = HEX_SHADOW_NORMAL;
        cellEl.innerHTML = `
          <span class="hex-label absolute inset-x-0 text-center leading-none" style="top:${Math.round(dims.hexH * 0.33)}px;font-size:${dims.labelFont}px"></span>
          <span class="hex-coord absolute inset-x-0 text-center leading-none text-black/65" style="bottom:${Math.round(dims.hexH * 0.15)}px;font-size:${dims.coordFont}px"></span>`;
        cellEl.addEventListener('mousedown', (e) => {
          e.preventDefault();
          if (editorMode === 'paint') {
            selectedKey = key(cell.row, cell.col);
            selectedKeys = new Set([selectedKey]);
            if (e.button === 2) {
              paintCell(cell, 'empty');
            } else {
              paintCell(cell, currentRole);
            }
            isPainting = true;
            renderSelection();
          } else {
            updateSelection(cell, !!e.shiftKey);
          }
        });
        cellEl.addEventListener('mouseenter', (e) => {
          if (!isPainting || editorMode !== 'paint') return;
          if (e.buttons === 2) paintCell(cell, 'empty');
          else paintCell(cell, currentRole);
        });
        rowEl.appendChild(cellEl);
      }

      gridEl.appendChild(rowEl);
    }

    gridEl.style.paddingBottom = `${Math.ceil(dims.hexH * 0.25)}px`;
    [...gridEl.querySelectorAll('.hex-row')].forEach(rowEl => rowEl.addEventListener('contextmenu', e => e.preventDefault()));
    state.cells.forEach(updateHexVisual);
  }

  function commonValue(cells, getter) {
    if (!cells.length) return { same: false, value: '' };
    const first = getter(cells[0]);
    const same = cells.every(c => getter(c) === first);
    return { same, value: same ? first : '' };
  }

  function setCheckboxAggregate(el, cells, getter) {
    const values = cells.map(getter);
    const allTrue = values.every(Boolean);
    const allFalse = values.every(v => !v);
    el.indeterminate = !(allTrue || allFalse);
    el.checked = allTrue;
  }

  function fillInspectorFromSelection() {
    const cells = [...selectedKeys].map(k => state.cellsByKey[k]).filter(Boolean);
    inspectorDirty.clear();

    if (!cells.length) {
      summaryEl.textContent = 'Nothing selected yet.';
      regionEl.value = '';
      specialEl.value = '';
      spawnEl.checked = false;
      biomesEl.checked = false;
      landmarksEl.checked = false;
      entitiesEl.checked = false;
      [spawnEl, biomesEl, landmarksEl, entitiesEl].forEach(el => { el.indeterminate = false; });
      return;
    }

    if (cells.length === 1) {
      const cell = cells[0];
      summaryEl.textContent = `Row ${cell.row}, Col ${cell.col} · ${cell.role}`;
    } else {
      const roleInfo = commonValue(cells, c => c.role);
      summaryEl.textContent = `${cells.length} hexes selected · ${roleInfo.same ? roleInfo.value : 'mixed roles'}`;
    }

    const regionInfo = commonValue(cells, c => c.region || '');
    const specialInfo = commonValue(cells, c => c.special || '');
    regionEl.value = regionInfo.value;
    regionEl.placeholder = regionInfo.same ? '' : 'multiple values (type to overwrite)';
    specialEl.value = specialInfo.value;
    specialEl.placeholder = specialInfo.same ? 'boss / player_spawn / relic' : 'multiple values (type to overwrite)';

    setCheckboxAggregate(spawnEl, cells, c => !!c.spawn);
    setCheckboxAggregate(biomesEl, cells, c => !!c.allow_biomes);
    setCheckboxAggregate(landmarksEl, cells, c => !!c.allow_landmarks);
    setCheckboxAggregate(entitiesEl, cells, c => !!c.allow_entities);
  }

  function renderSelection() {
    state.cells.forEach(updateHexVisual);
    fillInspectorFromSelection();
  }

  function applyInspector() {
    const cells = [...selectedKeys].map(k => state.cellsByKey[k]).filter(Boolean);
    if (!cells.length) return;

    const touched = inspectorDirty.size > 0;
    if (!touched) {
      showToast('No inspector changes to apply', false);
      return;
    }

    cells.forEach(cell => {
      if (inspectorDirty.has('region')) cell.region = regionEl.value.trim();
      if (inspectorDirty.has('special')) cell.special = specialEl.value.trim() || null;
      if (inspectorDirty.has('spawn')) cell.spawn = !!spawnEl.checked;
      if (inspectorDirty.has('allow_biomes')) cell.allow_biomes = !!biomesEl.checked;
      if (inspectorDirty.has('allow_landmarks')) cell.allow_landmarks = !!landmarksEl.checked;
      if (inspectorDirty.has('allow_entities')) cell.allow_entities = !!entitiesEl.checked;
      updateHexVisual(cell);
    });

    fillInspectorFromSelection();
    showToast(cells.length === 1 ? 'Hex updated' : `${cells.length} hexes updated`);
  }

  function payload() {
    return {
      name: state.name,
      description: descEl.value || '',
      width: state.width,
      height: state.height,
      cells: state.cells,
    };
  }

  async function save() {
    try {
      const res = await fetch(`/api/map-skeletons/${encodeURIComponent(state.name)}/save`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload()),
      });
      const data = await res.json();
      if (!res.ok || !data.ok) throw new Error(data.error || 'Save failed');
      showToast('Map saved');
    } catch (err) {
      console.error(err);
      showToast(err.message || 'Save failed', false);
    }
  }

  async function load() {
    const res = await fetch(`/api/map-skeletons/${encodeURIComponent(mapName)}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Failed to load map');
    state = data;
    if (!state.description) state.description = 'Skeleton exported from CSV';
    buildMapIndex();
    renderPalette();
    renderGrid();
    descEl.value = state.description || '';
    setMode('paint');
  }

  [
    [regionEl, 'region', 'input'],
    [specialEl, 'special', 'input'],
    [spawnEl, 'spawn', 'change'],
    [biomesEl, 'allow_biomes', 'change'],
    [landmarksEl, 'allow_landmarks', 'change'],
    [entitiesEl, 'allow_entities', 'change'],
  ].forEach(([el, name, evt]) => {
    el?.addEventListener(evt, () => {
      inspectorDirty.add(name);
      if ('indeterminate' in el) el.indeterminate = false;
    });
  });

  applyBtn?.addEventListener('click', applyInspector);
  saveBtn?.addEventListener('click', save);
  modePaintBtn?.addEventListener('click', () => setMode('paint'));
  modeSelectBtn?.addEventListener('click', () => setMode('select'));
  window.addEventListener('mouseup', () => { isPainting = false; });
  window.addEventListener('resize', () => { if (state) renderGrid(); });

  load().catch(err => {
    console.error(err);
    showToast(err.message || 'Load failed', false);
  });
})();
