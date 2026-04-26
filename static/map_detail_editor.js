(function () {
  const root = document.getElementById('detail-editor-root');
  if (!root) return;

  const state = JSON.parse(root.dataset.detailMap || '{}');
  const textures = JSON.parse(root.dataset.textures || '[]');
  const landmarks = JSON.parse(root.dataset.landmarks || '[]');
  const entities = JSON.parse(root.dataset.entities || '[]');
  const guardedLandmarkKeys = new Set(JSON.parse(root.dataset.guardedLandmarkKeys || '[]'));
  const guardedEntityKeys = new Set(JSON.parse(root.dataset.guardedEntityKeys || '[]'));

  const gridEl = document.getElementById('detail-grid');
  const shellEl = document.getElementById('detail-editor-shell');
  const saveBtn = document.getElementById('detail-save-btn');
  const saveLabelInput = document.getElementById('detail-save-label');
  const clearBtn = document.getElementById('detail-clear-btn');
  const summaryEl = document.getElementById('detail-selected-summary');
  const textureSelect = document.getElementById('detail-texture-select');
  const overlayKindSelect = document.getElementById('detail-overlay-kind');
  const overlayAssetSelect = document.getElementById('detail-overlay-asset');
  const overlayCountInput = document.getElementById('detail-overlay-count');
  const guardedInput = document.getElementById('detail-guarded');
  const texturePaletteEl = document.getElementById('detail-texture-palette');
  const overlayPaletteEl = document.getElementById('detail-overlay-palette');
  const tabLandmarksBtn = document.getElementById('detail-tab-landmarks');
  const tabEntitiesBtn = document.getElementById('detail-tab-entities');
  const previewStageEl = document.getElementById('detail-preview-stage');
  const previewOverlayEl = document.getElementById('detail-preview-overlay');
  const previewOverlayImgEl = document.getElementById('detail-preview-overlay-img');
  const previewAddonEl = document.getElementById('detail-preview-addon');
  const previewAddonImgEl = document.getElementById('detail-preview-addon-img');
  const previewCountEl = document.getElementById('detail-preview-count');
  const previewMetaEl = document.getElementById('detail-preview-meta');
  const liveStatusEl = document.getElementById('detail-live-status');
  const liveEditorsEl = document.getElementById('detail-live-editors');
  const liveCountEl = document.getElementById('detail-live-count');

  const GAP_X = 4;
  const GAP_Y = 4;
  const MIN_HEX_W = 34;
  const MAX_HEX_W = 82;
  const currentEditorName = (window.CURRENT_USER_NAME || 'Anonymous').trim() || 'Anonymous';

  let selectedKey = null;
  const selectedKeys = new Set();
  let overlayPaletteKind = 'landmark';
  let socket = null;

  function key(row, col) { return `${row}:${col}`; }
  function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }

  function roomPayload() {
    return {
      map_name: state.name,
      seed: state.seed,
      detail_map: detailMapPayload(),
    };
  }

  function setLiveStatus(text, ok = true) {
    if (!liveStatusEl) return;
    liveStatusEl.textContent = text;
    liveStatusEl.className = `text-xs mt-2 ${ok ? 'text-emerald-300/80' : 'text-amber-300/80'}`;
  }

  function renderEditors(editors) {
    const names = Array.isArray(editors) ? editors.filter(Boolean) : [];
    if (liveCountEl) liveCountEl.textContent = String(names.length);
    if (!liveEditorsEl) return;
    if (!names.length) {
      liveEditorsEl.textContent = 'No one else is here yet.';
      return;
    }
    liveEditorsEl.innerHTML = names
      .map((name) => `<span class="inline-flex items-center rounded-full bg-black/20 ring-1 ring-white/10 px-2 py-1 mr-1 mb-1 ${name === currentEditorName ? 'text-emerald-200' : 'text-white/80'}">${name === currentEditorName ? `${name} (You)` : name}</span>`)
      .join('');
  }

  function detailMapPayload() {
    return {
      name: state.name,
      description: state.description || '',
      save_label: state.save_label || '',
      seed: state.seed,
      width: state.width,
      height: state.height,
      region_biomes: state.region_biomes || {},
      cells: (state.cells || []).map(serializeCell),
    };
  }

  function wireSocketEvents() {
    if (!socket) return;
    socket.on('connect', () => {
      setLiveStatus('Live sync: connected');
      socket.emit('detail_map_join', roomPayload());
    });
    socket.on('disconnect', () => {
      setLiveStatus('Live sync: disconnected', false);
      renderEditors([]);
    });
    socket.on('connect_error', () => {
      setLiveStatus('Live sync: connection error', false);
    });
    socket.on('detail_map_state', (payload) => {
      if (!payload || payload.map_name !== state.name || Number(payload.seed) !== Number(state.seed)) return;
      replaceStateFromServer(payload.detail_map);
      renderEditors(payload.editors || []);
      setLiveStatus('Live sync: connected');
    });
    socket.on('detail_map_presence', (payload) => {
      if (!payload || payload.map_name !== state.name || Number(payload.seed) !== Number(state.seed)) return;
      renderEditors(payload.editors || []);
    });
    socket.on('detail_map_patch', (payload) => {
      if (!payload || payload.map_name !== state.name || Number(payload.seed) !== Number(state.seed)) return;
      if (Array.isArray(payload.cells) && payload.cells.length) {
        payload.cells.forEach((raw) => {
          const cellKey = key(raw.row, raw.col);
          state.cellsByKey[cellKey] = { ...(state.cellsByKey[cellKey] || {}), ...raw };
        });
        state.cells = Object.values(state.cellsByKey).sort((a, b) => (a.row - b.row) || (a.col - b.col));
      }
      if (Object.prototype.hasOwnProperty.call(payload, 'save_label')) {
        state.save_label = payload.save_label || '';
        if (saveLabelInput) saveLabelInput.value = state.save_label;
      }
      renderGrid();
      if (selectedKey && state.cellsByKey[selectedKey]) {
        const cell = state.cellsByKey[selectedKey];
        textureSelect.value = cell.texture_file_name || (textures[0]?.file_name || '');
        overlayKindSelect.value = cell.overlay_kind || '';
        renderOverlayAssetOptions(cell.overlay_kind || '');
        overlayAssetSelect.value = cell.overlay_file_name || '';
        overlayCountInput.value = cell.overlay_count || 0;
        guardedInput.checked = !!cell.guarded;
        const asset = overlayAssetByFile(cell.overlay_kind, cell.overlay_file_name);
        guardedInput.disabled = !isGuardedEligible(cell.overlay_kind, asset);
        summaryEl.textContent = selectedKeys.size > 1
          ? `${selectedKeys.size} hexes selected · anchor Row ${cell.row}, Col ${cell.col} · ${cell.role}${cell.region ? ` · ${cell.region}` : ''}`
          : `Row ${cell.row}, Col ${cell.col} · ${cell.role}${cell.region ? ` · ${cell.region}` : ''}`;
      }
      renderInspectorPreview();
      syncPaletteSelection();
    });
  }

  function initRealtime() {
    if (socket) return true;
    if (typeof io !== 'function') return false;
    socket = io({ transports: ['websocket', 'polling'] });
    wireSocketEvents();
    return true;
  }

  function showToast(text, ok = true) {
    let el = document.getElementById('detail-editor-toast');
    if (!el) {
      el = document.createElement('div');
      el.id = 'detail-editor-toast';
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

  function buildIndex() {
    state.cellsByKey = {};
    (state.cells || []).forEach(cell => {
      state.cellsByKey[key(cell.row, cell.col)] = cell;
    });
  }

  function textureByFile(fileName) {
    return textures.find(x => x.file_name === fileName) || null;
  }

  function overlayAssetsForKind(kind) {
    if (kind === 'landmark') return landmarks;
    if (kind === 'entity') return entities;
    return [];
  }

  function overlayAssetByFile(kind, fileName) {
    return overlayAssetsForKind(kind).find(x => x.file_name === fileName) || null;
  }

  function isGuardedEligible(kind, asset) {
    if (!asset) return false;
    const keyName = String(asset.name_key || '').toLowerCase();
    if (kind === 'landmark') return guardedLandmarkKeys.has(keyName);
    if (kind === 'entity') return guardedEntityKeys.has(keyName);
    return false;
  }

  function textureUrl(cell) {
    return cell.texture_file_name ? `/static/mapgen/textures/${encodeURIComponent(cell.texture_file_name)}` : '';
  }

  function overlayUrl(cell) {
    if (!cell.overlay_kind || !cell.overlay_file_name) return '';
    const folder = cell.overlay_kind === 'entity' ? 'entities' : 'landmarks';
    return `/static/mapgen/${folder}/${encodeURIComponent(cell.overlay_file_name)}`;
  }

  function addonUrl(cell) {
    if (!cell.guarded) return '';
    return '/static/mapgen/addons/Guarded.png';
  }

  function computeDims() {
    const cols = Math.max(1, state.width || 1);
    const available = Math.max(420, shellEl.clientWidth || 1200);
    const usable = available - GAP_X * Math.max(0, cols - 1);
    const hexW = clamp(Math.floor(usable / (cols + 0.52)), MIN_HEX_W, MAX_HEX_W);
    const hexH = Math.round((hexW * 2 / Math.sqrt(3)) * 100) / 100;
    const rowOffset = (hexW + GAP_X) / 2;
    const rowStep = hexH * 0.75 + GAP_Y;
    const overlap = Math.max(0, hexH - rowStep);
    shellEl.style.setProperty('--hex-w', `${hexW}px`);
    shellEl.style.setProperty('--hex-h', `${hexH}px`);
    shellEl.style.setProperty('--hex-gap-x', `${GAP_X}px`);
    shellEl.style.setProperty('--hex-row-offset', `${rowOffset}px`);
    shellEl.style.setProperty('--hex-overlap', `${overlap}px`);
  }

  function renderTextureOptions() {
    textureSelect.innerHTML = '';
    textures.forEach(asset => {
      const option = document.createElement('option');
      option.value = asset.file_name;
      option.textContent = `${asset.label} [${asset.biome}/${asset.variant}]`;
      textureSelect.appendChild(option);
    });
  }

  function renderOverlayAssetOptions(kind) {
    overlayAssetSelect.innerHTML = '';
    const none = document.createElement('option');
    none.value = '';
    none.textContent = kind ? 'Choose asset' : 'No overlay';
    overlayAssetSelect.appendChild(none);

    overlayAssetsForKind(kind).forEach(asset => {
      const option = document.createElement('option');
      option.value = asset.file_name;
      option.textContent = asset.label;
      overlayAssetSelect.appendChild(option);
    });
  }

  function createAssetCard(asset, type, active, imgUrl) {
    const card = document.createElement('button');
    card.type = 'button';
    card.className = `detail-asset-card ${type === 'texture' ? 'texture-only' : ''} ${active ? 'active' : ''}`;
    card.draggable = true;
    card.title = asset.label || '';
    card.innerHTML = `
      <div class="detail-asset-thumb">${imgUrl ? `<img src="${imgUrl}" alt="">` : ''}</div>
      <div class="detail-asset-label">${asset.label}</div>
    `;
    card.addEventListener('dragstart', (e) => {
      e.dataTransfer.setData('application/json', JSON.stringify({
        type,
        file_name: asset.file_name,
      }));
      e.dataTransfer.effectAllowed = 'copy';
    });
    card.addEventListener('click', () => {
      if (!selectedKey) {
        showToast('Select a hex first', false);
        return;
      }
      if (type === 'texture') {
        textureSelect.value = asset.file_name;
      } else {
        const isSameOverlay = overlayKindSelect.value === type && overlayAssetSelect.value === asset.file_name;
        if (isSameOverlay) {
          clearOverlayAtSelected(false);
          return;
        }
        overlayKindSelect.value = type;
        renderOverlayAssetOptions(type);
        overlayAssetSelect.value = asset.file_name;
        const selectedAsset = overlayAssetByFile(type, asset.file_name);
        guardedInput.disabled = !isGuardedEligible(type, selectedAsset);
        if (guardedInput.disabled) guardedInput.checked = false;
      }
      applySelectionSilent();
      syncPaletteSelection();
    });
    return card;
  }

  function clearOverlayFields(cell) {
    if (!cell) return;
    cell.overlay_kind = null;
    cell.overlay_file_name = null;
    cell.overlay_name_key = null;
    cell.overlay_label = null;
    cell.overlay_group = null;
    cell.overlay_count = 0;
    cell.guarded = false;
  }

  function serializeCell(cell) {
    return {
      row: cell.row,
      col: cell.col,
      active: !!cell.active,
      role: cell.role,
      role_color: cell.role_color,
      region: cell.region,
      spawn: !!cell.spawn,
      special: cell.special,
      biome: cell.biome,
      texture_file_name: cell.texture_file_name,
      overlay_kind: cell.overlay_kind,
      overlay_file_name: cell.overlay_file_name,
      overlay_name_key: cell.overlay_name_key,
      overlay_label: cell.overlay_label,
      overlay_group: cell.overlay_group,
      overlay_count: cell.overlay_count,
      guarded: !!cell.guarded,
    };
  }

  function emitCellPatch(cells) {
    if (!socket || !socket.connected || !cells.length) return;
    socket.emit('detail_map_patch', {
      map_name: state.name,
      seed: state.seed,
      save_label: (saveLabelInput?.value || '').trim(),
      cells: cells.map(serializeCell),
    });
  }

  function replaceStateFromServer(detailMap) {
    if (!detailMap || !Array.isArray(detailMap.cells)) return;
    state.name = detailMap.name || state.name;
    state.description = detailMap.description || state.description;
    state.save_label = detailMap.save_label || '';
    state.seed = detailMap.seed || state.seed;
    state.width = detailMap.width || state.width;
    state.height = detailMap.height || state.height;
    state.region_biomes = detailMap.region_biomes || state.region_biomes || {};
    state.cells = detailMap.cells;
    if (saveLabelInput) saveLabelInput.value = state.save_label || '';
    buildIndex();
    if (selectedKey && !state.cellsByKey[selectedKey]) {
      selectedKey = null;
      selectedKeys.clear();
    }
    renderGrid();
    if (selectedKey) {
      const cell = state.cellsByKey[selectedKey];
      if (cell) {
        textureSelect.value = cell.texture_file_name || (textures[0]?.file_name || '');
        overlayKindSelect.value = cell.overlay_kind || '';
        renderOverlayAssetOptions(cell.overlay_kind || '');
        overlayAssetSelect.value = cell.overlay_file_name || '';
        overlayCountInput.value = cell.overlay_count || 0;
        guardedInput.checked = !!cell.guarded;
        const asset = overlayAssetByFile(cell.overlay_kind, cell.overlay_file_name);
        guardedInput.disabled = !isGuardedEligible(cell.overlay_kind, asset);
        summaryEl.textContent = selectedKeys.size > 1
          ? `${selectedKeys.size} hexes selected · anchor Row ${cell.row}, Col ${cell.col} · ${cell.role}${cell.region ? ` · ${cell.region}` : ''}`
          : `Row ${cell.row}, Col ${cell.col} · ${cell.role}${cell.region ? ` · ${cell.region}` : ''}`;
      }
    }
    renderInspectorPreview();
    syncPaletteSelection();
  }

  function renderTexturePalette() {
    texturePaletteEl.innerHTML = '';
    const current = textureSelect.value || '';
    textures.forEach(asset => {
      texturePaletteEl.appendChild(
        createAssetCard(asset, 'texture', current === asset.file_name, `/static/mapgen/textures/${encodeURIComponent(asset.file_name)}`)
      );
    });
  }

  function renderOverlayPalette() {
    overlayPaletteEl.innerHTML = '';
    const currentKind = overlayKindSelect.value || '';
    const currentFile = overlayAssetSelect.value || '';
    const assets = overlayPaletteKind === 'entity' ? entities : landmarks;
    assets.forEach(asset => {
      overlayPaletteEl.appendChild(
        createAssetCard(
          asset,
          overlayPaletteKind,
          currentKind === overlayPaletteKind && currentFile === asset.file_name,
          `/static/mapgen/${overlayPaletteKind === 'entity' ? 'entities' : 'landmarks'}/${encodeURIComponent(asset.file_name)}`
        )
      );
    });
    tabLandmarksBtn.classList.toggle('active', overlayPaletteKind === 'landmark');
    tabEntitiesBtn.classList.toggle('active', overlayPaletteKind === 'entity');
  }

  function syncPaletteSelection() {
    renderTexturePalette();
    renderOverlayPalette();
  }

  function currentDraft() {
    const kind = overlayKindSelect.value || null;
    const asset = overlayAssetByFile(kind, overlayAssetSelect.value);
    const count = kind ? Math.max(1, Math.min(99, parseInt(overlayCountInput.value || '1', 10) || 1)) : 0;
    const guarded = kind ? (guardedInput.checked && isGuardedEligible(kind, asset)) : false;
    return {
      textureFileName: textureSelect.value || null,
      overlayKind: kind,
      overlayFileName: asset?.file_name || null,
      overlayLabel: asset?.label || null,
      overlayCount: count,
      guarded,
    };
  }

  function getSelectedCells() {
    return Array.from(selectedKeys)
      .map(k => state.cellsByKey[k])
      .filter(Boolean);
  }

  function renderInspectorPreview() {
    const draft = currentDraft();
    previewStageEl.style.backgroundImage = draft.textureFileName ? `url("${`/static/mapgen/textures/${encodeURIComponent(draft.textureFileName)}`}")` : '';
    if (draft.overlayKind && draft.overlayFileName) {
      const folder = draft.overlayKind === 'entity' ? 'entities' : 'landmarks';
      previewOverlayImgEl.src = `/static/mapgen/${folder}/${encodeURIComponent(draft.overlayFileName)}`;
      previewOverlayEl.classList.remove('hidden');
    } else {
      previewOverlayImgEl.removeAttribute('src');
      previewOverlayEl.classList.add('hidden');
    }
    if (draft.guarded) {
      previewAddonImgEl.src = '/static/mapgen/addons/Guarded.png';
      previewAddonEl.classList.remove('hidden');
    } else {
      previewAddonImgEl.removeAttribute('src');
      previewAddonEl.classList.add('hidden');
    }
    if (draft.overlayCount > 1) {
      previewCountEl.textContent = String(draft.overlayCount);
      previewCountEl.classList.remove('hidden');
    } else {
      previewCountEl.classList.add('hidden');
    }
    const parts = [];
    if (draft.textureFileName) parts.push(draft.textureFileName);
    if (draft.overlayLabel) parts.push(draft.overlayCount > 1 ? `${draft.overlayLabel} x${draft.overlayCount}` : draft.overlayLabel);
    if (draft.guarded) parts.push('Guarded');
    previewMetaEl.textContent = parts.length ? parts.join(' · ') : 'No texture or overlay selected.';
  }

  function renderGrid() {
    computeDims();
    gridEl.innerHTML = '';
    for (let row = 0; row < state.height; row++) {
      const rowEl = document.createElement('div');
      rowEl.className = 'detail-row';
      rowEl.style.marginLeft = row % 2 ? 'var(--hex-row-offset)' : '0px';
      for (let col = 0; col < state.width; col++) {
        const cell = state.cellsByKey[key(row, col)];
        const el = document.createElement('button');
        el.type = 'button';
        el.className = `detail-hex ${cell?.active ? '' : 'inactive'} ${selectedKeys.has(key(row, col)) ? 'selected' : ''}`;
        el.dataset.k = key(row, col);
        el.style.backgroundColor = cell?.role_color || '#111827';
        if (cell?.texture_file_name) {
          el.style.backgroundImage = `url("${textureUrl(cell)}")`;
        }
        const overlaySrc = overlayUrl(cell);
        const addonSrc = addonUrl(cell);
        el.innerHTML = `
          ${overlaySrc ? `<div class="detail-overlay"><img src="${overlaySrc}" alt=""></div>` : ''}
          ${cell?.overlay_count > 1 ? `<div class="detail-count-badge">${cell.overlay_count}</div>` : ''}
          ${addonSrc ? `<div class="detail-addon"><img src="${addonSrc}" alt=""></div>` : ''}
        `;
        el.title = `Row ${row}, Col ${col} | Role: ${cell?.role || 'empty'}${cell?.texture_file_name ? ` | Texture: ${cell.texture_file_name}` : ''}${cell?.overlay_label ? ` | Overlay: ${cell.overlay_label}${cell.overlay_count > 1 ? ` x${cell.overlay_count}` : ''}` : ''}`;
        el.addEventListener('click', (e) => selectCell(row, col, { multi: e.shiftKey }));
        el.addEventListener('contextmenu', (e) => {
          e.preventDefault();
          clearOverlayAt(row, col, true);
        });
        el.addEventListener('dragover', (e) => {
          e.preventDefault();
          el.classList.add('drop-target');
        });
        el.addEventListener('dragleave', () => {
          el.classList.remove('drop-target');
        });
        el.addEventListener('drop', (e) => {
          e.preventDefault();
          el.classList.remove('drop-target');
          let payload = null;
          try {
            payload = JSON.parse(e.dataTransfer.getData('application/json') || '{}');
          } catch (_) {
            payload = null;
          }
          if (!payload || !payload.type || !payload.file_name) return;
          if (!(selectedKeys.has(key(row, col)) && selectedKeys.size > 1)) {
            selectCell(row, col);
          }
          if (payload.type === 'texture') {
            textureSelect.value = payload.file_name;
          } else if (payload.type === 'landmark' || payload.type === 'entity') {
            overlayKindSelect.value = payload.type;
            renderOverlayAssetOptions(payload.type);
            overlayAssetSelect.value = payload.file_name;
            overlayCountInput.value = 1;
            guardedInput.checked = false;
            const droppedAsset = overlayAssetByFile(payload.type, payload.file_name);
            guardedInput.disabled = !isGuardedEligible(payload.type, droppedAsset);
          }
          applySelectionSilent();
          syncPaletteSelection();
        });
        rowEl.appendChild(el);
      }
      gridEl.appendChild(rowEl);
    }
  }

  function selectCell(row, col, options = {}) {
    const { multi = false } = options;
    const cellKey = key(row, col);
    if (multi) {
      if (selectedKeys.has(cellKey)) {
        selectedKeys.delete(cellKey);
        if (selectedKey === cellKey) {
          selectedKey = selectedKeys.size ? Array.from(selectedKeys).at(-1) : null;
        }
      } else {
        selectedKeys.add(cellKey);
        selectedKey = cellKey;
      }
    } else {
      selectedKeys.clear();
      selectedKeys.add(cellKey);
      selectedKey = cellKey;
    }

    const cell = selectedKey ? state.cellsByKey[selectedKey] : null;
    if (!cell) {
      summaryEl.textContent = 'Click a hex to edit it.';
      renderGrid();
      return;
    }
    summaryEl.textContent = selectedKeys.size > 1
      ? `${selectedKeys.size} hexes selected · anchor Row ${cell.row}, Col ${cell.col} · ${cell.role}${cell.region ? ` · ${cell.region}` : ''}`
      : `Row ${cell.row}, Col ${cell.col} · ${cell.role}${cell.region ? ` · ${cell.region}` : ''}`;
    textureSelect.value = cell.texture_file_name || (textures[0]?.file_name || '');
    overlayKindSelect.value = cell.overlay_kind || '';
    renderOverlayAssetOptions(cell.overlay_kind || '');
    overlayAssetSelect.value = cell.overlay_file_name || '';
    overlayCountInput.value = cell.overlay_count || 0;
    guardedInput.checked = !!cell.guarded;
    const asset = overlayAssetByFile(cell.overlay_kind, cell.overlay_file_name);
    guardedInput.disabled = !isGuardedEligible(cell.overlay_kind, asset);
    renderInspectorPreview();
    syncPaletteSelection();
    renderGrid();
  }

  function applySelectionSilent() {
    const cells = getSelectedCells();
    if (!cells.length) return;

    const draft = currentDraft();
    const asset = overlayAssetByFile(draft.overlayKind, draft.overlayFileName);
    cells.forEach(cell => {
      cell.texture_file_name = draft.textureFileName;
      cell.overlay_kind = draft.overlayKind;
      cell.overlay_file_name = draft.overlayFileName;
      cell.overlay_name_key = asset?.name_key || null;
      cell.overlay_label = asset?.label || null;
      cell.overlay_group = asset?.group || null;
      cell.overlay_count = draft.overlayCount;
      cell.guarded = draft.guarded;
    });

    emitCellPatch(cells);
    renderGrid();
    renderInspectorPreview();
    syncPaletteSelection();
  }

  function clearOverlay() {
    if (!selectedKeys.size) {
      showToast('Select a hex first', false);
      return;
    }
    clearOverlayAtSelected(true);
  }

  function clearOverlayAt(row, col, toast) {
    const cell = state.cellsByKey[key(row, col)];
    if (!cell) return;
    clearOverlayFields(cell);
    emitCellPatch([cell]);
    renderGrid();
    if (selectedKey === key(row, col)) {
      selectCell(row, col);
    }
    if (toast) showToast('Overlay cleared');
  }

  function clearOverlayAtSelected(toast) {
    const cells = getSelectedCells();
    if (!cells.length) return;
    cells.forEach(clearOverlayFields);
    emitCellPatch(cells);
    renderGrid();
    if (selectedKey) {
      const cell = state.cellsByKey[selectedKey];
      if (cell) {
        summaryEl.textContent = selectedKeys.size > 1
          ? `${selectedKeys.size} hexes selected · anchor Row ${cell.row}, Col ${cell.col} · ${cell.role}${cell.region ? ` · ${cell.region}` : ''}`
          : `Row ${cell.row}, Col ${cell.col} · ${cell.role}${cell.region ? ` · ${cell.region}` : ''}`;
        textureSelect.value = cell.texture_file_name || (textures[0]?.file_name || '');
        overlayKindSelect.value = cell.overlay_kind || '';
        renderOverlayAssetOptions(cell.overlay_kind || '');
        overlayAssetSelect.value = cell.overlay_file_name || '';
        overlayCountInput.value = cell.overlay_count || 0;
        guardedInput.checked = !!cell.guarded;
        const asset = overlayAssetByFile(cell.overlay_kind, cell.overlay_file_name);
        guardedInput.disabled = !isGuardedEligible(cell.overlay_kind, asset);
        renderInspectorPreview();
        syncPaletteSelection();
      }
    }
    if (toast) showToast('Overlay cleared');
  }

  async function save() {
    try {
      state.save_label = (saveLabelInput?.value || '').trim();
      if (socket && socket.connected) {
        socket.emit('detail_map_patch', {
          map_name: state.name,
          seed: state.seed,
          save_label: state.save_label,
          cells: [],
        });
      }
      const res = await fetch(`/api/map-skeletons/${encodeURIComponent(state.name)}/detail-save`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(detailMapPayload()),
      });
      const data = await res.json();
      if (!res.ok || !data.ok) throw new Error(data.error || 'Save failed');
      showToast(state.save_label ? `Saved as ${state.save_label}` : 'Detail map saved');
    } catch (err) {
      console.error(err);
      showToast(err.message || 'Save failed', false);
    }
  }

  overlayKindSelect?.addEventListener('change', () => {
    renderOverlayAssetOptions(overlayKindSelect.value);
    guardedInput.checked = false;
    guardedInput.disabled = true;
    applySelectionSilent();
  });

  overlayAssetSelect?.addEventListener('change', () => {
    const asset = overlayAssetByFile(overlayKindSelect.value, overlayAssetSelect.value);
    guardedInput.disabled = !isGuardedEligible(overlayKindSelect.value, asset);
    if (guardedInput.disabled) guardedInput.checked = false;
    applySelectionSilent();
  });

  saveLabelInput?.addEventListener('change', () => {
    state.save_label = (saveLabelInput.value || '').trim();
    if (socket && socket.connected) {
      socket.emit('detail_map_patch', {
        map_name: state.name,
        seed: state.seed,
        save_label: state.save_label,
        cells: [],
      });
    }
  });

  [textureSelect, overlayCountInput, guardedInput].forEach(el => {
    el?.addEventListener('input', applySelectionSilent);
    el?.addEventListener('change', applySelectionSilent);
  });
  clearBtn?.addEventListener('click', clearOverlay);
  saveBtn?.addEventListener('click', save);
  tabLandmarksBtn?.addEventListener('click', () => {
    overlayPaletteKind = 'landmark';
    renderOverlayPalette();
  });
  tabEntitiesBtn?.addEventListener('click', () => {
    overlayPaletteKind = 'entity';
    renderOverlayPalette();
  });
  window.addEventListener('resize', renderGrid);

  buildIndex();
  renderTextureOptions();
  renderOverlayAssetOptions('');
  renderTexturePalette();
  renderOverlayPalette();
  renderInspectorPreview();
  renderGrid();
  renderEditors([]);

  setLiveStatus('Live sync: connecting...');
  let realtimeAttempts = 0;
  const realtimeTimer = window.setInterval(() => {
    realtimeAttempts += 1;
    if (initRealtime()) {
      window.clearInterval(realtimeTimer);
      return;
    }
    if (realtimeAttempts >= 20) {
      window.clearInterval(realtimeTimer);
      setLiveStatus('Live sync: unavailable', false);
    }
  }, 250);

  window.addEventListener('beforeunload', () => {
    if (socket && socket.connected) {
      socket.emit('detail_map_leave', { map_name: state.name, seed: state.seed });
    }
  });
})();
