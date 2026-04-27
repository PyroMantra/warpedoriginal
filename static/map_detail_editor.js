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
  const heroActionsEl = document.getElementById('detail-hero-actions');
  const heroVisionButtons = heroActionsEl ? Array.from(heroActionsEl.querySelectorAll('[data-vision-range]')) : [];
  const heroCountInput = document.getElementById('detail-hero-count');
  const heroPathfinderInput = document.getElementById('detail-hero-pathfinder');
  const heroKillBtn = document.getElementById('detail-hero-kill');

  const GAP_X = 4;
  const GAP_Y = 4;
  const MIN_HEX_W = 34;
  const MAX_HEX_W = 82;
  const currentEditorName = (window.CURRENT_USER_NAME || 'Anonymous').trim() || 'Anonymous';
  const VISION_EXPORT_SCALE = 2.8;

  let selectedKey = null;
  const selectedKeys = new Set();
  let overlayPaletteKind = 'landmark';
  let socket = null;
  let activeHeroKey = null;

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
      if (activeHeroKey && state.cellsByKey[activeHeroKey]) syncHeroPanelForSelection(state.cellsByKey[activeHeroKey]);
      else closeHeroActions();
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

  function isHeroEntityAsset(asset) {
    if (!asset) return false;
    const npc = String(asset.npc || '').trim().toLowerCase();
    const fileName = String(asset.file_name || '').trim().toLowerCase();
    return npc === 'hero' || fileName.startsWith('npc=hero');
  }

  function isGuardedEligible(kind, asset) {
    if (!asset) return false;
    const keyName = String(asset.name_key || '').toLowerCase();
    if (kind === 'landmark') return guardedLandmarkKeys.has(keyName);
    if (kind === 'entity') return guardedEntityKeys.has(keyName);
    return false;
  }

  function isProtectedHeroTraversalOverlay(cell) {
    if (!cell || !cell.overlay_kind || !cell.overlay_file_name) return false;
    const nameKey = String(cell.overlay_name_key || '').trim().toLowerCase();
    const label = String(cell.overlay_label || '').trim().toLowerCase();
    const group = String(cell.overlay_group || '').trim().toLowerCase();
    return (
      group === 'zone' ||
      nameKey === 'portal' ||
      nameKey === 'ward' ||
      nameKey === 'constructionyard' ||
      label.includes('portal') ||
      label.includes('ward') ||
      label.includes('construction yard')
    );
  }

  function textureUrl(cell) {
    return cell.texture_file_name ? `/static/mapgen/textures/${encodeURIComponent(cell.texture_file_name)}` : '';
  }

  function overlayUrl(cell) {
    if (!cell.overlay_kind || !cell.overlay_file_name) return '';
    const folder = cell.overlay_kind === 'entity' ? 'entities' : 'landmarks';
    return `/static/mapgen/${folder}/${encodeURIComponent(cell.overlay_file_name)}`;
  }

  function heroUrl(cell) {
    return cell.hero_file_name ? `/static/mapgen/entities/${encodeURIComponent(cell.hero_file_name)}` : '';
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
        if (type === 'entity' && isHeroEntityAsset(asset)) {
          const cells = getSelectedCells();
          cells.forEach((cell) => {
            cell.hero_file_name = asset.file_name;
            cell.hero_name_key = asset.name_key || null;
            cell.hero_label = asset.label || null;
            cell.hero_count = 1;
            cell.hero_pathfinder = false;
          });
          emitCellPatch(cells);
          renderGrid();
          syncPaletteSelection();
          return;
        }
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

  function clearHeroFields(cell) {
    if (!cell) return;
    cell.hero_file_name = null;
    cell.hero_name_key = null;
    cell.hero_label = null;
    cell.hero_count = 0;
    cell.hero_pathfinder = false;
  }

  function hasHero(cell) {
    return !!(cell && cell.hero_file_name);
  }

  function closeHeroActions() {
    activeHeroKey = null;
    if (heroActionsEl) heroActionsEl.classList.remove('visible');
  }

  function openHeroActions(cell, targetEl) {
    if (!heroActionsEl || !cell || !targetEl) return;
    activeHeroKey = key(cell.row, cell.col);
    if (heroCountInput) heroCountInput.value = String(Math.max(1, Number(cell.hero_count || 1)));
    if (heroPathfinderInput) heroPathfinderInput.checked = !!cell.hero_pathfinder;
    const rect = targetEl.getBoundingClientRect();
    const panelWidth = heroActionsEl.offsetWidth || 138;
    const preferredLeft = rect.left + rect.width / 2;
    const left = clamp(preferredLeft, panelWidth / 2 + 8, window.innerWidth - panelWidth / 2 - 8);
    const top = Math.max(8, rect.top - 2);
    heroActionsEl.style.left = `${left}px`;
    heroActionsEl.style.top = `${top}px`;
    heroActionsEl.classList.add('visible');
  }

  function syncHeroPanelForSelection(cell) {
    if (!cell || !hasHero(cell)) {
      closeHeroActions();
      return;
    }
    const heroNode = document.querySelector(`.detail-hero[data-hero-key="${key(cell.row, cell.col)}"]`);
    if (!heroNode) {
      closeHeroActions();
      return;
    }
    openHeroActions(cell, heroNode);
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
      hero_file_name: cell.hero_file_name,
      hero_name_key: cell.hero_name_key,
      hero_label: cell.hero_label,
      hero_count: Math.max(0, Math.min(99, Number(cell.hero_count || 0))),
      hero_pathfinder: !!cell.hero_pathfinder,
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
    if (activeHeroKey && state.cellsByKey[activeHeroKey]) syncHeroPanelForSelection(state.cellsByKey[activeHeroKey]);
    else closeHeroActions();
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
    const selectedCell = selectedKey ? state.cellsByKey[selectedKey] : null;
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
      heroFileName: selectedCell?.hero_file_name || null,
      heroLabel: selectedCell?.hero_label || null,
      heroCount: Math.max(0, Number(selectedCell?.hero_count || 0)),
      heroPathfinder: !!selectedCell?.hero_pathfinder,
    };
  }

  function getSelectedCells() {
    return Array.from(selectedKeys)
      .map(k => state.cellsByKey[k])
      .filter(Boolean);
  }

  function getVisionMetrics() {
    const styles = window.getComputedStyle(shellEl);
    const baseW = parseFloat(styles.getPropertyValue('--hex-w')) || 58;
    const baseH = parseFloat(styles.getPropertyValue('--hex-h')) || 66;
    const baseGapX = parseFloat(styles.getPropertyValue('--hex-gap-x')) || GAP_X;
    const baseOffset = parseFloat(styles.getPropertyValue('--hex-row-offset')) || ((baseW + baseGapX) / 2);
    const baseOverlap = parseFloat(styles.getPropertyValue('--hex-overlap')) || 12;
    const scale = VISION_EXPORT_SCALE;
    return {
      hexW: baseW * scale,
      hexH: baseH * scale,
      colStep: (baseW + baseGapX) * scale,
      rowOffset: baseOffset * scale,
      rowStep: (baseH - baseOverlap) * scale,
    };
  }

  function oddrToCube(row, col) {
    const x = col - ((row - (row & 1)) / 2);
    const z = row;
    const y = -x - z;
    return { x, y, z };
  }

  function hexDistance(aRow, aCol, bRow, bCol) {
    const a = oddrToCube(aRow, aCol);
    const b = oddrToCube(bRow, bCol);
    return Math.max(Math.abs(a.x - b.x), Math.abs(a.y - b.y), Math.abs(a.z - b.z));
  }

  function cubeToOddr(cube) {
    const row = cube.z;
    const col = cube.x + ((cube.z - (cube.z & 1)) / 2);
    return { row, col };
  }

  function cubeRound(frac) {
    let rx = Math.round(frac.x);
    let ry = Math.round(frac.y);
    let rz = Math.round(frac.z);

    const xDiff = Math.abs(rx - frac.x);
    const yDiff = Math.abs(ry - frac.y);
    const zDiff = Math.abs(rz - frac.z);

    if (xDiff > yDiff && xDiff > zDiff) {
      rx = -ry - rz;
    } else if (yDiff > zDiff) {
      ry = -rx - rz;
    } else {
      rz = -rx - ry;
    }
    return { x: rx, y: ry, z: rz };
  }

  function cubeLerp(a, b, t) {
    return {
      x: a.x + (b.x - a.x) * t,
      y: a.y + (b.y - a.y) * t,
      z: a.z + (b.z - a.z) * t,
    };
  }

  function hexLine(aRow, aCol, bRow, bCol) {
    const a = oddrToCube(aRow, aCol);
    const b = oddrToCube(bRow, bCol);
    const distance = hexDistance(aRow, aCol, bRow, bCol);
    if (distance === 0) return [{ row: aRow, col: aCol }];
    const points = [];
    for (let i = 0; i <= distance; i++) {
      const t = distance === 0 ? 0 : i / distance;
      const rounded = cubeRound(cubeLerp(a, b, t));
      const oddr = cubeToOddr(rounded);
      const prev = points.at(-1);
      if (!prev || prev.row !== oddr.row || prev.col !== oddr.col) {
        points.push(oddr);
      }
    }
    return points;
  }

  function textureTag(cell) {
    return String(cell?.texture_file_name || '').toLowerCase();
  }

  function isVisionBlockingCell(cell) {
    const tag = textureTag(cell);
    return tag.includes('type=forest') || tag.includes('mountain');
  }

  function isVisibleToHero(originCell, targetCell, radius) {
    if (!originCell || !targetCell) return false;
    if (radius <= 1 || originCell.hero_pathfinder) return true;
    const distance = hexDistance(originCell.row, originCell.col, targetCell.row, targetCell.col);
    if (distance <= 1) return true;
    const seen = new Set();

    function nextSteps(row, col, targetRow, targetCol) {
      const odd = row & 1;
      const deltas = odd
        ? [[-1, 0], [-1, 1], [0, -1], [0, 1], [1, 0], [1, 1]]
        : [[-1, -1], [-1, 0], [0, -1], [0, 1], [1, -1], [1, 0]];
      return deltas
        .map(([dr, dc]) => ({ row: row + dr, col: col + dc }))
        .filter((next) => next.row >= 0 && next.col >= 0 && next.row < state.height && next.col < state.width)
        .filter((next) => hexDistance(next.row, next.col, targetRow, targetCol) === hexDistance(row, col, targetRow, targetCol) - 1);
    }

    function hasClearPath(row, col) {
      const memoKey = `${row}:${col}->${targetCell.row}:${targetCell.col}`;
      if (seen.has(memoKey)) return false;
      seen.add(memoKey);
      if (row === targetCell.row && col === targetCell.col) return true;
      const candidates = nextSteps(row, col, targetCell.row, targetCell.col);
      for (const next of candidates) {
        const isTarget = next.row === targetCell.row && next.col === targetCell.col;
        const nextCell = state.cellsByKey[key(next.row, next.col)];
        if (!isTarget && nextCell && isVisionBlockingCell(nextCell)) {
          continue;
        }
        if (hasClearPath(next.row, next.col)) {
          return true;
        }
      }
      return false;
    }

    return hasClearPath(originCell.row, originCell.col);
  }

  function drawHexPath(ctx, x, y, w, h) {
    ctx.beginPath();
    ctx.moveTo(x + w * 0.5, y + h * 0.015);
    ctx.lineTo(x + w * 0.95, y + h * 0.25);
    ctx.lineTo(x + w * 0.95, y + h * 0.75);
    ctx.lineTo(x + w * 0.5, y + h * 0.985);
    ctx.lineTo(x + w * 0.05, y + h * 0.75);
    ctx.lineTo(x + w * 0.05, y + h * 0.25);
    ctx.closePath();
  }

  const imageCache = new Map();
  function loadImage(src) {
    if (!src) return Promise.resolve(null);
    if (imageCache.has(src)) return imageCache.get(src);
    const promise = new Promise((resolve) => {
      const img = new Image();
      img.crossOrigin = 'anonymous';
      img.onload = () => resolve(img);
      img.onerror = () => resolve(null);
      img.src = src;
    });
    imageCache.set(src, promise);
    return promise;
  }

  async function captureHeroVision(cell, range) {
    const radius = Math.max(1, Math.min(3, Number(range) || 1));
    const metrics = getVisionMetrics();
    const visibleCells = [];
    for (let row = 0; row < state.height; row++) {
      for (let col = 0; col < state.width; col++) {
        if (hexDistance(cell.row, cell.col, row, col) <= radius) {
          const target = state.cellsByKey[key(row, col)];
          if (target) visibleCells.push(target);
        }
      }
    }
    if (!visibleCells.length) {
      showToast('No visible hexes found', false);
      return;
    }

    const positioned = visibleCells.map((target) => {
      const x = target.col * metrics.colStep + (target.row % 2 ? metrics.rowOffset : 0);
      const y = target.row * metrics.rowStep;
      return { cell: target, x, y };
    });
    const minX = Math.min(...positioned.map((item) => item.x));
    const minY = Math.min(...positioned.map((item) => item.y));
    const maxX = Math.max(...positioned.map((item) => item.x + metrics.hexW));
    const maxY = Math.max(...positioned.map((item) => item.y + metrics.hexH));
    const padding = 24;

    const canvas = document.createElement('canvas');
    canvas.width = Math.ceil(maxX - minX + padding * 2);
    canvas.height = Math.ceil(maxY - minY + padding * 2);
    const ctx = canvas.getContext('2d');
    if (!ctx) {
      showToast('Could not render vision image', false);
      return;
    }
    ctx.fillStyle = '#2f2f32';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    const inactiveFill = '#9ca3af';

    for (const item of positioned) {
      const target = item.cell;
      const x = item.x - minX + padding;
      const y = item.y - minY + padding;
      const visibleToHero = isVisibleToHero(cell, target, radius);
      const textureSrc = textureUrl(target);
      const overlaySrc = overlayUrl(target);
      const heroSrc = heroUrl(target);
      const addonSrc = addonUrl(target);

      ctx.save();
      drawHexPath(ctx, x, y, metrics.hexW, metrics.hexH);
      ctx.clip();
      if (!visibleToHero) {
        ctx.fillStyle = '#111111';
        ctx.fillRect(x, y, metrics.hexW, metrics.hexH);
      } else if (target.active && textureSrc) {
        const textureImg = await loadImage(textureSrc);
        if (textureImg) {
          ctx.drawImage(textureImg, x, y, metrics.hexW, metrics.hexH);
        }
      } else {
        ctx.fillStyle = inactiveFill;
        ctx.fillRect(x, y, metrics.hexW, metrics.hexH);
      }
      ctx.restore();

      if (visibleToHero && overlaySrc) {
        const overlayImg = await loadImage(overlaySrc);
        if (overlayImg) {
          ctx.drawImage(overlayImg, x - metrics.hexW * 0.01, y - metrics.hexH * 0.01, metrics.hexW * 1.02, metrics.hexH * 1.02);
        }
      }
      if (visibleToHero && heroSrc) {
        const heroImg = await loadImage(heroSrc);
        if (heroImg) {
          ctx.drawImage(heroImg, x - metrics.hexW * 0.03, y - metrics.hexH * 0.03, metrics.hexW * 1.06, metrics.hexH * 1.06);
        }
      }
      if (visibleToHero && (target.hero_count || 0) > 1) {
        ctx.fillStyle = 'rgba(17,24,39,0.92)';
        const badgeW = Math.max(30, metrics.hexW * 0.19);
        const badgeH = Math.max(18, metrics.hexH * 0.11);
        const badgeX = x + metrics.hexW * 0.12;
        const badgeY = y + metrics.hexH * 0.74;
        ctx.beginPath();
        const radiusPx = Math.min(8, badgeH / 2);
        ctx.moveTo(badgeX + radiusPx, badgeY);
        ctx.lineTo(badgeX + badgeW - radiusPx, badgeY);
        ctx.quadraticCurveTo(badgeX + badgeW, badgeY, badgeX + badgeW, badgeY + radiusPx);
        ctx.lineTo(badgeX + badgeW, badgeY + badgeH - radiusPx);
        ctx.quadraticCurveTo(badgeX + badgeW, badgeY + badgeH, badgeX + badgeW - radiusPx, badgeY + badgeH);
        ctx.lineTo(badgeX + radiusPx, badgeY + badgeH);
        ctx.quadraticCurveTo(badgeX, badgeY + badgeH, badgeX, badgeY + badgeH - radiusPx);
        ctx.lineTo(badgeX, badgeY + radiusPx);
        ctx.quadraticCurveTo(badgeX, badgeY, badgeX + radiusPx, badgeY);
        ctx.closePath();
        ctx.fill();
        ctx.fillStyle = '#ffffff';
        ctx.font = `bold ${Math.max(12, Math.round(metrics.hexW * 0.075))}px sans-serif`;
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(String(target.hero_count), badgeX + badgeW / 2, badgeY + badgeH / 2 + 0.5);
      }
      if (visibleToHero && addonSrc) {
        const addonImg = await loadImage(addonSrc);
        if (addonImg) {
          const inset = metrics.hexW * 0.26;
          ctx.drawImage(addonImg, x + inset, y + inset - metrics.hexH * 0.08, metrics.hexW - inset * 2, metrics.hexH - inset * 2);
        }
      }
      if (visibleToHero && (target.overlay_count || 0) > 1) {
        ctx.fillStyle = 'rgba(17,24,39,0.92)';
        const badgeW = Math.max(30, metrics.hexW * 0.19);
        const badgeH = Math.max(18, metrics.hexH * 0.11);
        const badgeX = x + metrics.hexW * 0.5 - badgeW / 2;
        const badgeY = y + metrics.hexH * 0.74;
        ctx.beginPath();
        const radiusPx = Math.min(8, badgeH / 2);
        ctx.moveTo(badgeX + radiusPx, badgeY);
        ctx.lineTo(badgeX + badgeW - radiusPx, badgeY);
        ctx.quadraticCurveTo(badgeX + badgeW, badgeY, badgeX + badgeW, badgeY + radiusPx);
        ctx.lineTo(badgeX + badgeW, badgeY + badgeH - radiusPx);
        ctx.quadraticCurveTo(badgeX + badgeW, badgeY + badgeH, badgeX + badgeW - radiusPx, badgeY + badgeH);
        ctx.lineTo(badgeX + radiusPx, badgeY + badgeH);
        ctx.quadraticCurveTo(badgeX, badgeY + badgeH, badgeX, badgeY + badgeH - radiusPx);
        ctx.lineTo(badgeX, badgeY + radiusPx);
        ctx.quadraticCurveTo(badgeX, badgeY, badgeX + radiusPx, badgeY);
        ctx.closePath();
        ctx.fill();
        ctx.fillStyle = '#ffffff';
        ctx.font = `bold ${Math.max(12, Math.round(metrics.hexW * 0.075))}px sans-serif`;
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(String(target.overlay_count), badgeX + badgeW / 2, badgeY + badgeH / 2 + 0.5);
      }
    }

    try {
      const blob = await new Promise((resolve) => canvas.toBlob(resolve, 'image/png'));
      if (!blob) throw new Error('No image blob');
      if (navigator.clipboard && window.ClipboardItem) {
        await navigator.clipboard.write([new ClipboardItem({ 'image/png': blob })]);
        showToast(`Vision ${radius} copied to clipboard`);
      } else {
        throw new Error('Clipboard image unsupported');
      }
    } catch (err) {
      console.error(err);
      showToast('Clipboard image export is not supported here', false);
    }
  }

  function renderInspectorPreview() {
    const draft = currentDraft();
    previewStageEl.style.backgroundImage = draft.textureFileName ? `url("${`/static/mapgen/textures/${encodeURIComponent(draft.textureFileName)}`}")` : '';
    const previewSrc = draft.heroFileName
      ? `/static/mapgen/entities/${encodeURIComponent(draft.heroFileName)}`
      : (draft.overlayKind && draft.overlayFileName
        ? `/static/mapgen/${draft.overlayKind === 'entity' ? 'entities' : 'landmarks'}/${encodeURIComponent(draft.overlayFileName)}`
        : '');
    if (previewSrc) {
      previewOverlayImgEl.src = previewSrc;
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
    const previewCount = draft.heroLabel ? draft.heroCount : draft.overlayCount;
    if (previewCount > 1) {
      previewCountEl.textContent = String(previewCount);
      previewCountEl.classList.remove('hidden');
    } else {
      previewCountEl.classList.add('hidden');
    }
    const parts = [];
    if (draft.textureFileName) parts.push(draft.textureFileName);
    if (draft.heroLabel) parts.push(draft.heroCount > 1 ? `Hero: ${draft.heroLabel} x${draft.heroCount}` : `Hero: ${draft.heroLabel}`);
    if (draft.heroLabel && draft.heroPathfinder) parts.push('Pathfinder');
    if (!draft.heroLabel && draft.overlayLabel) parts.push(draft.overlayCount > 1 ? `${draft.overlayLabel} x${draft.overlayCount}` : draft.overlayLabel);
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
        const heroSrc = heroUrl(cell);
        el.innerHTML = `
          ${overlaySrc ? `<div class="detail-overlay"><img src="${overlaySrc}" alt=""></div>` : ''}
          ${cell?.overlay_count > 1 ? `<div class="detail-count-badge">${cell.overlay_count}</div>` : ''}
          ${addonSrc ? `<div class="detail-addon"><img src="${addonSrc}" alt=""></div>` : ''}
          ${heroSrc ? `<div class="detail-hero" draggable="true" data-hero-key="${key(row, col)}"><img src="${heroSrc}" alt="${cell.hero_label || 'Hero'}"></div>` : ''}
          ${cell?.hero_count > 1 ? `<div class="detail-count-badge detail-hero-count-badge">${cell.hero_count}</div>` : ''}
        `;
        el.title = `Row ${row}, Col ${col} | Role: ${cell?.role || 'empty'}${cell?.texture_file_name ? ` | Texture: ${cell.texture_file_name}` : ''}${cell?.overlay_label ? ` | Overlay: ${cell.overlay_label}${cell.overlay_count > 1 ? ` x${cell.overlay_count}` : ''}` : ''}${cell?.hero_label ? ` | Hero: ${cell.hero_label}${cell.hero_count > 1 ? ` x${cell.hero_count}` : ''}` : ''}`;
        const heroEl = el.querySelector('.detail-hero');
        if (heroEl) {
          heroEl.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            selectCell(row, col);
            openHeroActions(cell, heroEl);
          });
          heroEl.addEventListener('dragstart', (e) => {
            e.stopPropagation();
            e.dataTransfer.setData('application/json', JSON.stringify({
              type: 'hero',
              row,
              col,
              file_name: cell.hero_file_name,
              name_key: cell.hero_name_key,
              label: cell.hero_label,
              count: cell.hero_count,
            }));
            e.dataTransfer.effectAllowed = 'move';
          });
        }
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
          if (!payload || !payload.type) return;
          if (!(selectedKeys.has(key(row, col)) && selectedKeys.size > 1)) {
            selectCell(row, col);
          }
          let handledDirectly = false;
          if (payload.type === 'hero') {
            const sourceKey = key(payload.row, payload.col);
            const sourceCell = state.cellsByKey[sourceKey];
            const targetCell = state.cellsByKey[key(row, col)];
          if (!sourceCell || !targetCell) return;
          if (sourceKey === key(row, col)) return;
          if (hasHero(targetCell)) {
            showToast('That hex already has a hero', false);
            return;
          }
          if (!isProtectedHeroTraversalOverlay(targetCell)) {
            clearOverlayFields(targetCell);
          }
          targetCell.hero_file_name = payload.file_name || sourceCell.hero_file_name;
          targetCell.hero_name_key = payload.name_key || sourceCell.hero_name_key;
          targetCell.hero_label = payload.label || sourceCell.hero_label;
          targetCell.hero_count = Math.max(1, Number(payload.count || sourceCell.hero_count || 1));
          targetCell.hero_pathfinder = !!sourceCell.hero_pathfinder;
          clearHeroFields(sourceCell);
            closeHeroActions();
            emitCellPatch([sourceCell, targetCell]);
            handledDirectly = true;
          } else if (payload.type === 'texture') {
            textureSelect.value = payload.file_name;
          } else if (payload.type === 'landmark' || payload.type === 'entity') {
            overlayKindSelect.value = payload.type;
            renderOverlayAssetOptions(payload.type);
            overlayAssetSelect.value = payload.file_name;
            overlayCountInput.value = 1;
            guardedInput.checked = false;
            const droppedAsset = overlayAssetByFile(payload.type, payload.file_name);
            if (payload.type === 'entity' && isHeroEntityAsset(droppedAsset)) {
              const targetCell = state.cellsByKey[key(row, col)];
              if (!targetCell) return;
              targetCell.hero_file_name = droppedAsset.file_name;
              targetCell.hero_name_key = droppedAsset.name_key || null;
              targetCell.hero_label = droppedAsset.label || null;
              targetCell.hero_count = 1;
              targetCell.hero_pathfinder = false;
              guardedInput.disabled = true;
              guardedInput.checked = false;
              emitCellPatch([targetCell]);
              handledDirectly = true;
            } else {
              guardedInput.disabled = !isGuardedEligible(payload.type, droppedAsset);
            }
          }
          if (handledDirectly) {
            renderGrid();
            syncPaletteSelection();
            return;
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
      closeHeroActions();
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
    syncHeroPanelForSelection(cell);
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

  function updateActiveHeroPathfinder(enabled) {
    if (!activeHeroKey || !state.cellsByKey[activeHeroKey]) return;
    const cell = state.cellsByKey[activeHeroKey];
    if (!hasHero(cell)) return;
    cell.hero_pathfinder = !!enabled;
    emitCellPatch([cell]);
    renderInspectorPreview();
    renderGrid();
    syncHeroPanelForSelection(cell);
  }

  function updateActiveHeroCount(value) {
    if (!activeHeroKey || !state.cellsByKey[activeHeroKey]) return;
    const cell = state.cellsByKey[activeHeroKey];
    if (!hasHero(cell)) return;
    const normalized = Math.max(1, Math.min(99, parseInt(value || '1', 10) || 1));
    cell.hero_count = normalized;
    if (heroCountInput) heroCountInput.value = String(normalized);
    emitCellPatch([cell]);
    renderInspectorPreview();
    renderGrid();
    syncHeroPanelForSelection(cell);
  }

  function removeActiveHero() {
    if (!activeHeroKey || !state.cellsByKey[activeHeroKey]) return;
    const cell = state.cellsByKey[activeHeroKey];
    if (!hasHero(cell)) {
      closeHeroActions();
      return;
    }
    clearHeroFields(cell);
    emitCellPatch([cell]);
    closeHeroActions();
    renderGrid();
    renderInspectorPreview();
    showToast('Hero removed');
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
  window.addEventListener('resize', () => {
    if (activeHeroKey && state.cellsByKey[activeHeroKey]) {
      syncHeroPanelForSelection(state.cellsByKey[activeHeroKey]);
    }
  });

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

  const presenceTimer = window.setInterval(() => {
    if (socket && socket.connected) {
      socket.emit('detail_map_presence_ping', { map_name: state.name, seed: state.seed });
    }
  }, 20000);

  window.addEventListener('beforeunload', () => {
    if (socket && socket.connected) {
      socket.emit('detail_map_leave', { map_name: state.name, seed: state.seed });
    }
    window.clearInterval(presenceTimer);
  });

  heroVisionButtons.forEach((btn) => {
    btn.addEventListener('click', async () => {
      if (!activeHeroKey || !state.cellsByKey[activeHeroKey]) {
        closeHeroActions();
        return;
      }
      const cell = state.cellsByKey[activeHeroKey];
      const range = Number(btn.dataset.visionRange || 1);
      closeHeroActions();
      await captureHeroVision(cell, range);
    });
  });

  heroPathfinderInput?.addEventListener('change', () => {
    updateActiveHeroPathfinder(heroPathfinderInput.checked);
  });

  [heroCountInput].forEach((el) => {
    el?.addEventListener('input', () => {
      updateActiveHeroCount(el.value);
    });
    el?.addEventListener('change', () => {
      updateActiveHeroCount(el.value);
    });
  });

  heroKillBtn?.addEventListener('click', () => {
    removeActiveHero();
  });

  document.addEventListener('click', (e) => {
    if (!heroActionsEl || !heroActionsEl.classList.contains('visible')) return;
    if (heroActionsEl.contains(e.target)) return;
    if (e.target && e.target.closest && e.target.closest('.detail-hero')) return;
    closeHeroActions();
  });
})();
