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
  const overlayOwnerColorSelect = document.getElementById('detail-overlay-owner-color');
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
  const VISION_EXPORT_ASPECT_SQUASH = 0.9;
  const MIN_EDITOR_ZOOM = 0.65;
  const MAX_EDITOR_ZOOM = 2.2;
  const EDITOR_ZOOM_STEP = 0.12;
  const OWNER_COLORS = [
    { key: '', label: 'Unowned', color: '' },
    { key: 'yellow', label: 'Yellow', color: '#facc15' },
    { key: 'blue', label: 'Blue', color: '#60a5fa' },
    { key: 'green', label: 'Green', color: '#4ade80' },
    { key: 'orange', label: 'Orange', color: '#fb923c' },
    { key: 'pink', label: 'Pink', color: '#f472b6' },
    { key: 'purple', label: 'Purple', color: '#a78bfa' },
    { key: 'black', label: 'Black', color: '#111111' },
    { key: 'red', label: 'Red', color: '#f87171' },
    { key: 'teal', label: 'Teal', color: '#2dd4bf' },
    { key: 'white', label: 'White', color: '#f8fafc' },
  ];

  let selectedKey = null;
  const selectedKeys = new Set();
  let overlayPaletteKind = 'landmark';
  let socket = null;
  let activeUnitKey = null;
  let activeUnitKind = null;
  let editorZoom = 1;
  let editorPanX = 0;
  let editorPanY = 0;
  let panState = null;
  let suppressNextMapClick = false;

  function key(row, col) { return `${row}:${col}`; }
  function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }

  function applyEditorViewportTransform() {
    if (!shellEl) return;
    shellEl.style.setProperty('--detail-zoom', String(editorZoom));
    shellEl.style.setProperty('--detail-pan-x', `${editorPanX}px`);
    shellEl.style.setProperty('--detail-pan-y', `${editorPanY}px`);
  }

  function setEditorZoomOriginFromEvent(event) {
    if (!shellEl || !event) return;
    const rect = shellEl.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    const xPct = clamp(((event.clientX - rect.left) / rect.width) * 100, 0, 100);
    const yPct = clamp(((event.clientY - rect.top) / rect.height) * 100, 0, 100);
    shellEl.style.setProperty('--detail-zoom-origin-x', `${xPct}%`);
    shellEl.style.setProperty('--detail-zoom-origin-y', `${yPct}%`);
  }

  function handleEditorZoom(event) {
    if (!event.ctrlKey || !shellEl || !shellEl.contains(event.target)) return;
    event.preventDefault();
    setEditorZoomOriginFromEvent(event);
    const direction = event.deltaY < 0 ? 1 : -1;
    const nextZoom = clamp(editorZoom + direction * EDITOR_ZOOM_STEP, MIN_EDITOR_ZOOM, MAX_EDITOR_ZOOM);
    if (nextZoom === editorZoom) return;
    editorZoom = Math.round(nextZoom * 100) / 100;
    applyEditorViewportTransform();
  }

  function beginEditorPan(event) {
    if (!shellEl || !event.altKey || event.button !== 0) return;
    panState = {
      pointerId: event.pointerId,
      startClientX: event.clientX,
      startClientY: event.clientY,
      startPanX: editorPanX,
      startPanY: editorPanY,
      moved: false,
    };
    suppressNextMapClick = false;
    shellEl.classList.add('is-panning');
    shellEl.setPointerCapture?.(event.pointerId);
    event.preventDefault();
  }

  function updateEditorPan(event) {
    if (!shellEl || !panState || event.pointerId !== panState.pointerId) return;
    const deltaX = event.clientX - panState.startClientX;
    const deltaY = event.clientY - panState.startClientY;
    if (!panState.moved && (Math.abs(deltaX) > 3 || Math.abs(deltaY) > 3)) {
      panState.moved = true;
      suppressNextMapClick = true;
    }
    editorPanX = panState.startPanX + deltaX;
    editorPanY = panState.startPanY + deltaY;
    applyEditorViewportTransform();
    event.preventDefault();
  }

  function endEditorPan(event) {
    if (!shellEl || !panState) return;
    if (event && event.pointerId != null && event.pointerId !== panState.pointerId) return;
    shellEl.classList.remove('is-panning');
    if (panState.pointerId != null) {
      shellEl.releasePointerCapture?.(panState.pointerId);
    }
    panState = null;
  }

  function swallowPanClick(event) {
    if (!suppressNextMapClick) return;
    event.preventDefault();
    event.stopPropagation();
    suppressNextMapClick = false;
  }

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
        syncOwnerSelect(cell);
        overlayCountInput.value = cell.overlay_count || 0;
        guardedInput.checked = !!cell.guarded;
        const asset = overlayAssetByFile(cell.overlay_kind, cell.overlay_file_name);
        guardedInput.disabled = !canUseGuardedMarker(cell, cell.overlay_kind, asset);
        summaryEl.textContent = selectedKeys.size > 1
          ? `${selectedKeys.size} hexes selected · anchor Row ${cell.row}, Col ${cell.col} · ${cell.role}${cell.region ? ` · ${cell.region}` : ''}`
          : `Row ${cell.row}, Col ${cell.col} · ${cell.role}${cell.region ? ` · ${cell.region}` : ''}`;
      }
      renderInspectorPreview();
      syncPaletteSelection();
      if (activeUnitKey && state.cellsByKey[activeUnitKey]) syncHeroPanelForSelection(state.cellsByKey[activeUnitKey]);
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

  function ownerColorValue(keyName) {
    const normalized = String(keyName || '').trim().toLowerCase();
    return OWNER_COLORS.find((entry) => entry.key === normalized)?.color || '';
  }

  function populateOwnerSelect(selectEl) {
    if (!selectEl) return;
    selectEl.innerHTML = OWNER_COLORS.map((entry) => `<option value="${entry.key}">${entry.label}</option>`).join('');
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

  function isForestCell(cell) {
    return textureTag(cell).includes('type=forest');
  }

  function canUseGuardedMarker(cell, kind = null, asset = null, unitKind = null) {
    if (isGuardedEligible(kind, asset)) return true;
    if (unitKind === 'hero') return hasHero(cell);
    return hasHero(cell);
  }

  function isBoatOverlayCell(cell) {
    if (!cell || cell.overlay_kind !== 'landmark') return false;
    const nameKey = String(cell.overlay_name_key || '').trim().toLowerCase();
    const label = String(cell.overlay_label || '').trim().toLowerCase();
    const fileName = String(cell.overlay_file_name || '').trim().toLowerCase();
    return nameKey === 'boat' || label === 'boat' || fileName.startsWith('landmark=boat');
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

  function heroGuardedAddonUrl(cell) {
    return cell.guarded && hasHero(cell) ? addonUrl(cell) : '';
  }

  function overlayGuardedAddonUrl(cell) {
    return cell.guarded && !hasHero(cell) ? addonUrl(cell) : '';
  }

  function isBoatAssetSrc(src) {
    return /landmark=boat/i.test(String(src || ''));
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
            cell.hero_owner_color = String(overlayOwnerColorSelect?.value || '').trim().toLowerCase() || null;
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
        guardedInput.disabled = !canUseGuardedMarker(state.cellsByKey[selectedKey], type, selectedAsset);
        if (guardedInput.disabled) guardedInput.checked = false;
        if (type !== 'entity' && overlayOwnerColorSelect) overlayOwnerColorSelect.value = '';
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
    cell.overlay_owner_color = null;
    cell.overlay_pathfinder = false;
    cell.overlay_count = 0;
    cell.guarded = false;
  }

  function clearHeroFields(cell) {
    if (!cell) return;
    cell.hero_file_name = null;
    cell.hero_name_key = null;
    cell.hero_label = null;
    cell.hero_count = 0;
    cell.hero_owner_color = null;
    cell.hero_pathfinder = false;
  }

  function hasHero(cell) {
    return !!(cell && cell.hero_file_name);
  }

  function hasOwnedEntity(cell) {
    return !!(
      cell &&
      cell.overlay_kind === 'entity' &&
      cell.overlay_file_name &&
      !String(cell.overlay_file_name || '').trim().toLowerCase().startsWith('npc=hero') &&
      cell.overlay_owner_color
    );
  }

  function hasOwnedMovableOverlay(cell) {
    return !!(
      cell &&
      cell.overlay_file_name &&
      cell.overlay_owner_color &&
      (cell.overlay_kind === 'entity' || isBoatOverlayCell(cell))
    );
  }

  function hasMovableUnit(cell) {
    return hasHero(cell) || hasOwnedMovableOverlay(cell);
  }

  function getUnitOwnerColorKey(cell, kind = null) {
    const resolvedKind = kind || (hasHero(cell) ? 'hero' : (hasOwnedMovableOverlay(cell) ? 'overlay' : null));
    if (resolvedKind === 'hero') return String(cell?.hero_owner_color || '').trim().toLowerCase() || null;
    if (resolvedKind === 'entity' || resolvedKind === 'overlay') return String(cell?.overlay_owner_color || '').trim().toLowerCase() || null;
    return null;
  }

  function getUnitPathfinder(cell, kind = null) {
    const resolvedKind = kind || (hasHero(cell) ? 'hero' : (hasOwnedMovableOverlay(cell) ? 'overlay' : null));
    if (resolvedKind === 'hero') return !!cell?.hero_pathfinder;
    if (resolvedKind === 'entity' || resolvedKind === 'overlay') return !!cell?.overlay_pathfinder;
    return false;
  }

  function getUnitCount(cell, kind = null) {
    const resolvedKind = kind || (hasHero(cell) ? 'hero' : (hasOwnedMovableOverlay(cell) ? 'overlay' : null));
    if (resolvedKind === 'hero') return Math.max(1, Number(cell?.hero_count || 1));
    if (resolvedKind === 'entity' || resolvedKind === 'overlay') return Math.max(1, Number(cell?.overlay_count || 1));
    return 1;
  }

  function getUnitLabel(cell, kind = null) {
    const resolvedKind = kind || (hasHero(cell) ? 'hero' : (hasOwnedMovableOverlay(cell) ? 'overlay' : null));
    if (resolvedKind === 'hero') return cell?.hero_label || 'Hero';
    if (resolvedKind === 'entity' || resolvedKind === 'overlay') return cell?.overlay_label || 'Entity';
    return 'Unit';
  }

  function getUnitImageUrl(cell, kind = null) {
    const resolvedKind = kind || (hasHero(cell) ? 'hero' : (hasOwnedMovableOverlay(cell) ? 'overlay' : null));
    if (resolvedKind === 'hero') return heroUrl(cell);
    if (resolvedKind === 'entity' || resolvedKind === 'overlay') return overlayUrl(cell);
    return '';
  }

  function getUnitKindForCell(cell) {
    if (hasHero(cell)) return 'hero';
    if (hasOwnedMovableOverlay(cell)) return 'overlay';
    return null;
  }

  function setUnitPathfinder(cell, kind, enabled) {
    if (!cell) return;
    if (kind === 'hero') cell.hero_pathfinder = !!enabled;
    if (kind === 'entity' || kind === 'overlay') cell.overlay_pathfinder = !!enabled;
  }

  function setUnitCount(cell, kind, value) {
    if (!cell) return;
    const normalized = Math.max(1, Math.min(99, parseInt(value || '1', 10) || 1));
    if (kind === 'hero') cell.hero_count = normalized;
    if (kind === 'entity' || kind === 'overlay') cell.overlay_count = normalized;
  }

  function setUnitOwnerColor(cell, kind, value) {
    if (!cell) return;
    const normalized = String(value || '').trim().toLowerCase() || null;
    if (kind === 'hero') cell.hero_owner_color = normalized;
    if (kind === 'entity' || kind === 'overlay') cell.overlay_owner_color = normalized;
  }

  function clearUnitFields(cell, kind) {
    if (kind === 'hero') clearHeroFields(cell);
    if (kind === 'entity' || kind === 'overlay') clearOverlayFields(cell);
  }

  function closeHeroActions() {
    activeUnitKey = null;
    activeUnitKind = null;
    if (heroActionsEl) heroActionsEl.classList.remove('visible');
  }

  function openHeroActions(cell, targetEl, kind = null, anchorPoint = null) {
    if (!heroActionsEl || !cell || !targetEl) return;
    const resolvedKind = kind || getUnitKindForCell(cell);
    if (!resolvedKind) return;
    activeUnitKey = key(cell.row, cell.col);
    activeUnitKind = resolvedKind;
    if (heroCountInput) heroCountInput.value = String(getUnitCount(cell, resolvedKind));
    if (heroPathfinderInput) heroPathfinderInput.checked = getUnitPathfinder(cell, resolvedKind);
    if (heroKillBtn) heroKillBtn.title = resolvedKind === 'hero' ? 'Remove hero' : 'Remove unit';
    syncOwnerSelect(cell);
    const panelWidth = heroActionsEl.offsetWidth || 138;
    const rect = targetEl.getBoundingClientRect();
    const preferredLeft = anchorPoint?.x ?? (rect.left + rect.width / 2);
    const left = clamp(preferredLeft, panelWidth / 2 + 8, window.innerWidth - panelWidth / 2 - 8);
    const top = anchorPoint
      ? clamp(anchorPoint.y - 10, 44, window.innerHeight - 52)
      : Math.max(8, rect.top - 2);
    heroActionsEl.style.left = `${left}px`;
    heroActionsEl.style.top = `${top}px`;
    heroActionsEl.classList.add('visible');
  }

  function syncHeroPanelForSelection(cell) {
    if (!cell || !activeUnitKey || !activeUnitKind) {
      closeHeroActions();
      return;
    }
    const node = document.querySelector(`[data-unit-kind="${activeUnitKind}"][data-unit-key="${key(cell.row, cell.col)}"]`);
    if (!node) {
      closeHeroActions();
      return;
    }
    openHeroActions(cell, node, activeUnitKind);
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
      overlay_owner_color: cell.overlay_owner_color,
      overlay_pathfinder: !!cell.overlay_pathfinder,
      overlay_count: cell.overlay_count,
      guarded: !!cell.guarded,
      hero_file_name: cell.hero_file_name,
      hero_name_key: cell.hero_name_key,
      hero_label: cell.hero_label,
      hero_count: Math.max(0, Math.min(99, Number(cell.hero_count || 0))),
      hero_owner_color: cell.hero_owner_color,
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
        syncOwnerSelect(cell);
        overlayCountInput.value = cell.overlay_count || 0;
        guardedInput.checked = !!cell.guarded;
        const asset = overlayAssetByFile(cell.overlay_kind, cell.overlay_file_name);
        guardedInput.disabled = !canUseGuardedMarker(cell, cell.overlay_kind, asset);
        summaryEl.textContent = selectedKeys.size > 1
          ? `${selectedKeys.size} hexes selected · anchor Row ${cell.row}, Col ${cell.col} · ${cell.role}${cell.region ? ` · ${cell.region}` : ''}`
          : `Row ${cell.row}, Col ${cell.col} · ${cell.role}${cell.region ? ` · ${cell.region}` : ''}`;
      }
    }
    renderInspectorPreview();
    syncPaletteSelection();
    if (activeUnitKey && state.cellsByKey[activeUnitKey]) syncHeroPanelForSelection(state.cellsByKey[activeUnitKey]);
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
    const selectedUnitKind = selectedCell && activeUnitKey === selectedKey ? activeUnitKind : null;
    const kind = overlayKindSelect.value || null;
    const asset = overlayAssetByFile(kind, overlayAssetSelect.value);
    const count = kind ? Math.max(1, Math.min(99, parseInt(overlayCountInput.value || '1', 10) || 1)) : 0;
    const guarded = !!(guardedInput.checked && canUseGuardedMarker(selectedCell, kind, asset, selectedUnitKind));
    const ownerColor = String(overlayOwnerColorSelect?.value || '').trim().toLowerCase() || null;
    const selectedIsBoat = isBoatOverlayCell(selectedCell);
    const draftIsBoat = kind === 'landmark' && String(asset?.name_key || '').trim().toLowerCase() === 'boat';
    return {
      textureFileName: textureSelect.value || null,
      overlayKind: kind,
      overlayFileName: asset?.file_name || null,
      overlayLabel: asset?.label || null,
      overlayCount: count,
      overlayOwnerColor: (kind === 'entity' || draftIsBoat || selectedIsBoat) ? ownerColor : null,
      guarded,
      heroFileName: selectedUnitKind === 'overlay' ? null : (selectedCell?.hero_file_name || null),
      heroLabel: selectedUnitKind === 'overlay' ? null : (selectedCell?.hero_label || null),
      heroCount: selectedUnitKind === 'overlay' ? 0 : Math.max(0, Number(selectedCell?.hero_count || 0)),
      heroOwnerColor: selectedUnitKind === 'overlay' ? null : (hasHero(selectedCell) ? ownerColor : (selectedCell?.hero_owner_color || null)),
      heroPathfinder: selectedUnitKind === 'overlay' ? false : !!selectedCell?.hero_pathfinder,
    };
  }

  function getSelectedCells() {
    return Array.from(selectedKeys)
      .map(k => state.cellsByKey[k])
      .filter(Boolean);
  }

  function syncOwnerSelect(cell) {
    if (!overlayOwnerColorSelect) return;
    const preferredKind = cell && activeUnitKey === key(cell.row, cell.col) ? activeUnitKind : null;
    if (preferredKind === 'overlay' && cell?.overlay_file_name) {
      overlayOwnerColorSelect.value = String(cell.overlay_owner_color || '').trim().toLowerCase();
      return;
    }
    if (preferredKind === 'hero' && hasHero(cell)) {
      overlayOwnerColorSelect.value = String(cell.hero_owner_color || '').trim().toLowerCase();
      return;
    }
    if (hasHero(cell)) {
      overlayOwnerColorSelect.value = String(cell.hero_owner_color || '').trim().toLowerCase();
      return;
    }
    if (cell?.overlay_kind === 'entity' || isBoatOverlayCell(cell)) {
      overlayOwnerColorSelect.value = String(cell.overlay_owner_color || '').trim().toLowerCase();
      return;
    }
    overlayOwnerColorSelect.value = '';
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
      hexH: baseH * scale * VISION_EXPORT_ASPECT_SQUASH,
      colStep: (baseW + baseGapX) * scale,
      rowOffset: baseOffset * scale,
      rowStep: (baseH - baseOverlap) * scale * VISION_EXPORT_ASPECT_SQUASH,
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
    return isForestCell(cell) || tag.includes('mountain');
  }

  function shouldHideHeroFromCapture(cell) {
    return hasHero(cell) && isForestCell(cell);
  }

  function isVisibleToHero(originCell, targetCell, radius, unitKind = null) {
    if (!originCell || !targetCell) return false;
    if (radius <= 1 || getUnitPathfinder(originCell, unitKind)) return true;
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

  async function loadOwnedTokenImage(src, ownerColor) {
    if (!src || !ownerColor) return loadImage(src);
    const cacheKey = `owned:${ownerColor}:${src}`;
    if (imageCache.has(cacheKey)) return imageCache.get(cacheKey);
    const promise = (async () => {
      const base = await loadImage(src);
      if (!base) return null;
      const canvas = document.createElement('canvas');
      canvas.width = base.naturalWidth || base.width;
      canvas.height = base.naturalHeight || base.height;
      const ctx = canvas.getContext('2d');
      if (!ctx) return base;
      ctx.drawImage(base, 0, 0, canvas.width, canvas.height);
      const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
      const data = imageData.data;
      const isBoat = isBoatAssetSrc(src);
      const ownerHex = ownerColor.replace('#', '');
      const ownerRgb = {
        r: parseInt(ownerHex.slice(0, 2), 16),
        g: parseInt(ownerHex.slice(2, 4), 16),
        b: parseInt(ownerHex.slice(4, 6), 16),
      };
      for (let i = 0; i < data.length; i += 4) {
        const alpha = data[i + 3];
        if (!alpha) continue;
        const r = data[i];
        const g = data[i + 1];
        const b = data[i + 2];
        const max = Math.max(r, g, b);
        const min = Math.min(r, g, b);
        const spread = max - min;
        const luminance = (r + g + b) / 3;
        const isGrayBand = spread <= 36 && luminance >= 60;
        const saturation = max === 0 ? 0 : spread / max;
        const pixelIndex = i / 4;
        const y = Math.floor(pixelIndex / canvas.width);
        const x = pixelIndex % canvas.width;
        const withinBoatSailColumn = x >= canvas.width * 0.16 && x <= canvas.width * 0.84;
        const isBoatSailBand =
          isBoat &&
          y >= canvas.height * 0.04 &&
          y <= canvas.height * 0.74 &&
          withinBoatSailColumn &&
          (
            (luminance >= 148 && spread <= 118) ||
            (r >= 145 && g >= 125 && b >= 80) ||
            (luminance >= 112 && saturation <= 0.28) ||
            (spread <= 56 && luminance >= 78)
          );
        if (!isGrayBand && !isBoatSailBand) continue;
        const shade = Math.max(0.58, Math.min(1.06, luminance / 220));
        data[i] = Math.round(ownerRgb.r * shade);
        data[i + 1] = Math.round(ownerRgb.g * shade);
        data[i + 2] = Math.round(ownerRgb.b * shade);
      }
      ctx.putImageData(imageData, 0, 0);
      const img = new Image();
      await new Promise((resolve) => {
        img.onload = resolve;
        img.onerror = resolve;
        img.src = canvas.toDataURL('image/png');
      });
      return img;
    })();
    imageCache.set(cacheKey, promise);
    return promise;
  }

  async function applyOwnedTokenTint(imgEl) {
    if (!imgEl) return;
    const baseSrc = imgEl.dataset.ownedSrc || imgEl.dataset.baseSrc || imgEl.getAttribute('src') || '';
    const ownerColor = imgEl.dataset.ownerColor || '';
    if (!baseSrc) return;
    imgEl.dataset.baseSrc = baseSrc;
    const tinted = await loadOwnedTokenImage(baseSrc, ownerColor);
    if (!tinted) return;
    const resolvedSrc = tinted.currentSrc || tinted.src || baseSrc;
    if (imgEl.dataset.baseSrc === baseSrc && imgEl.dataset.ownerColor === ownerColor) {
      imgEl.src = resolvedSrc;
    }
  }

  function hydrateOwnedTokens(scope = document) {
    scope.querySelectorAll('img[data-owned-src]').forEach((imgEl) => {
      void applyOwnedTokenTint(imgEl);
    });
  }

  async function captureHeroVision(cell, range, unitKind = null) {
    const radius = Math.max(1, Math.min(3, Number(range) || 1));
    const originKind = unitKind || getUnitKindForCell(cell) || 'hero';
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
      const visibleToHero = isVisibleToHero(cell, target, radius, originKind);
      const textureSrc = textureUrl(target);
      const overlaySrc = overlayUrl(target);
      const overlayOwnedColor = ownerColorValue(target.overlay_owner_color);
      const ownedBoat = isBoatOverlayCell(target) && overlayOwnedColor;
      const heroHiddenInForest = shouldHideHeroFromCapture(target);
      const heroSrc = heroHiddenInForest ? '' : heroUrl(target);
      const heroOwnedColor = ownerColorValue(target.hero_owner_color);
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
        const overlayImg = await loadOwnedTokenImage(overlaySrc, (target.overlay_kind === 'entity' || ownedBoat) ? overlayOwnedColor : '');
        if (overlayImg) {
          if (ownedBoat) {
            ctx.drawImage(overlayImg, x + metrics.hexW * 0.12, y + metrics.hexH * 0.12, metrics.hexW * 0.76, metrics.hexH * 0.76);
          } else if (target.overlay_kind === 'entity') {
            ctx.drawImage(overlayImg, x + metrics.hexW * 0.16, y + metrics.hexH * 0.16, metrics.hexW * 0.68, metrics.hexH * 0.68);
          } else {
            ctx.drawImage(overlayImg, x - metrics.hexW * 0.01, y - metrics.hexH * 0.01, metrics.hexW * 1.02, metrics.hexH * 1.02);
          }
        }
      }
      if (visibleToHero && heroSrc) {
        const heroImg = await loadOwnedTokenImage(heroSrc, heroOwnedColor);
        if (heroImg) {
          ctx.drawImage(heroImg, x + metrics.hexW * 0.16, y + metrics.hexH * 0.16, metrics.hexW * 0.68, metrics.hexH * 0.68);
        }
      }
      if (visibleToHero && !heroHiddenInForest && (target.hero_count || 0) > 1) {
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
      if (visibleToHero && addonSrc && !(heroHiddenInForest && !target.overlay_file_name)) {
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
      previewOverlayImgEl.dataset.ownedSrc = previewSrc;
      previewOverlayImgEl.dataset.ownerColor = ownerColorValue(
        draft.heroFileName
          ? draft.heroOwnerColor
          : ((draft.overlayKind === 'entity' || (draft.overlayKind === 'landmark' && draft.overlayLabel && String(draft.overlayLabel).trim().toLowerCase() === 'boat'))
            ? draft.overlayOwnerColor
            : '')
      );
      previewOverlayEl.classList.toggle('entity', !!draft.heroFileName || draft.overlayKind === 'entity' || (draft.overlayKind === 'landmark' && draft.overlayLabel && String(draft.overlayLabel).trim().toLowerCase() === 'boat'));
      previewOverlayEl.classList.toggle('boat', !draft.heroFileName && draft.overlayKind === 'landmark' && draft.overlayLabel && String(draft.overlayLabel).trim().toLowerCase() === 'boat');
      previewOverlayEl.classList.remove('hidden');
      void applyOwnedTokenTint(previewOverlayImgEl);
    } else {
      previewOverlayImgEl.removeAttribute('src');
      delete previewOverlayImgEl.dataset.ownedSrc;
      delete previewOverlayImgEl.dataset.ownerColor;
      previewOverlayEl.classList.remove('entity');
      previewOverlayEl.classList.remove('boat');
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
    if (draft.heroLabel && draft.heroOwnerColor) parts.push(`Owner: ${draft.heroOwnerColor}`);
    if (draft.heroLabel && draft.heroPathfinder) parts.push('Pathfinder');
    if (!draft.heroLabel && draft.overlayLabel) parts.push(draft.overlayCount > 1 ? `${draft.overlayLabel} x${draft.overlayCount}` : draft.overlayLabel);
    if (!draft.heroLabel && draft.overlayLabel && draft.overlayOwnerColor) parts.push(`Owner: ${draft.overlayOwnerColor}`);
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
        const addonSrc = overlayGuardedAddonUrl(cell);
        const heroAddonSrc = heroGuardedAddonUrl(cell);
        const heroSrc = heroUrl(cell);
        const overlayOwnerColor = ownerColorValue(cell?.overlay_owner_color);
        const heroOwnerColor = ownerColorValue(cell?.hero_owner_color);
        const ownedMovableOverlay = hasOwnedMovableOverlay(cell);
        const movableOverlayIsEntity = cell?.overlay_kind === 'entity';
        const movableOverlayIsBoat = isBoatOverlayCell(cell);
        el.innerHTML = `
          ${overlaySrc ? `<div class="detail-overlay ${(movableOverlayIsEntity || movableOverlayIsBoat) ? 'entity' : ''} ${movableOverlayIsBoat ? 'boat' : ''} ${ownedMovableOverlay ? 'detail-unit-overlay' : ''}" ${ownedMovableOverlay ? `draggable="true" data-unit-kind="overlay" data-unit-key="${key(row, col)}"` : ''}><img src="${overlaySrc}" alt="" ${overlayOwnerColor ? `data-owned-src="${overlaySrc}" data-owner-color="${overlayOwnerColor}"` : ''}></div>` : ''}
          ${cell?.overlay_count > 1 ? `<div class="detail-count-badge">${cell.overlay_count}</div>` : ''}
          ${addonSrc ? `<div class="detail-addon"><img src="${addonSrc}" alt=""></div>` : ''}
          ${heroSrc ? `<div class="detail-hero" draggable="true" data-unit-kind="hero" data-unit-key="${key(row, col)}"><img src="${heroSrc}" alt="${cell.hero_label || 'Hero'}" ${heroOwnerColor ? `data-owned-src="${heroSrc}" data-owner-color="${heroOwnerColor}"` : ''}></div>` : ''}
          ${heroAddonSrc ? `<div class="detail-addon detail-hero-addon"><img src="${heroAddonSrc}" alt=""></div>` : ''}
          ${cell?.hero_count > 1 ? `<div class="detail-count-badge detail-hero-count-badge">${cell.hero_count}</div>` : ''}
        `;
        el.title = `Row ${row}, Col ${col} | Role: ${cell?.role || 'empty'}${cell?.texture_file_name ? ` | Texture: ${cell.texture_file_name}` : ''}${cell?.overlay_label ? ` | Overlay: ${cell.overlay_label}${cell.overlay_count > 1 ? ` x${cell.overlay_count}` : ''}${cell?.overlay_owner_color ? ` | Owner: ${cell.overlay_owner_color}` : ''}` : ''}${cell?.hero_label ? ` | Hero: ${cell.hero_label}${cell.hero_count > 1 ? ` x${cell.hero_count}` : ''}${cell?.hero_owner_color ? ` | Owner: ${cell.hero_owner_color}` : ''}` : ''}`;
        const heroEl = el.querySelector('.detail-hero');
        if (heroEl) {
          heroEl.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            selectCell(row, col);
            openHeroActions(cell, heroEl, 'hero');
          });
          heroEl.addEventListener('dragstart', (e) => {
            e.stopPropagation();
            e.dataTransfer.setData('application/json', JSON.stringify({
              type: 'unit',
              unit_kind: 'hero',
              row,
              col,
              file_name: cell.hero_file_name,
              name_key: cell.hero_name_key,
              label: cell.hero_label,
              count: cell.hero_count,
              owner_color: cell.hero_owner_color,
              pathfinder: !!cell.hero_pathfinder,
            }));
            e.dataTransfer.effectAllowed = 'move';
          });
        }
        const entityUnitEl = el.querySelector('.detail-unit-overlay');
        if (entityUnitEl) {
          entityUnitEl.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            selectCell(row, col);
            openHeroActions(cell, entityUnitEl, 'entity');
          });
          entityUnitEl.addEventListener('dragstart', (e) => {
            e.stopPropagation();
            e.dataTransfer.setData('application/json', JSON.stringify({
              type: 'unit',
              unit_kind: 'overlay',
              row,
              col,
              file_name: cell.overlay_file_name,
              name_key: cell.overlay_name_key,
              label: cell.overlay_label,
              group: cell.overlay_group,
              count: cell.overlay_count,
              owner_color: cell.overlay_owner_color,
              pathfinder: !!cell.overlay_pathfinder,
            }));
            e.dataTransfer.effectAllowed = 'move';
          });
        }
        el.addEventListener('click', (e) => selectCell(row, col, { multi: e.shiftKey }));
        el.addEventListener('contextmenu', (e) => {
          e.preventDefault();
          selectCell(row, col);
          const unitKind = getUnitKindForCell(cell);
          if (unitKind) {
            const refreshedHex = document.querySelector(`.detail-hex[data-k="${key(row, col)}"]`);
            const unitNode = refreshedHex?.querySelector(`[data-unit-kind="${unitKind}"]`);
            if (unitNode) {
              openHeroActions(cell, unitNode, unitKind, { x: e.clientX, y: e.clientY });
              return;
            }
          }
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
          if (payload.type === 'unit') {
            const sourceKey = key(payload.row, payload.col);
            const sourceCell = state.cellsByKey[sourceKey];
            const targetCell = state.cellsByKey[key(row, col)];
            if (!sourceCell || !targetCell) return;
            if (sourceKey === key(row, col)) return;
            if (payload.unit_kind === 'hero' && hasHero(targetCell)) {
              showToast('That hex already has a hero', false);
              return;
            }
            if (payload.unit_kind === 'overlay' && hasOwnedMovableOverlay(targetCell)) {
              showToast('That hex already has an owned unit', false);
              return;
            }
            if (!isProtectedHeroTraversalOverlay(targetCell)) {
              clearOverlayFields(targetCell);
            }
            if (payload.unit_kind === 'hero') {
              const carriedGuarded = !!sourceCell.guarded;
              targetCell.hero_file_name = payload.file_name || sourceCell.hero_file_name;
              targetCell.hero_name_key = payload.name_key || sourceCell.hero_name_key;
              targetCell.hero_label = payload.label || sourceCell.hero_label;
              targetCell.hero_count = Math.max(1, Number(payload.count || sourceCell.hero_count || 1));
              targetCell.hero_owner_color = payload.owner_color || sourceCell.hero_owner_color || null;
              targetCell.hero_pathfinder = !!(payload.pathfinder ?? sourceCell.hero_pathfinder);
              targetCell.guarded = carriedGuarded;
              clearHeroFields(sourceCell);
              sourceCell.guarded = false;
            } else {
              targetCell.overlay_kind = sourceCell.overlay_kind || 'entity';
              targetCell.overlay_file_name = payload.file_name || sourceCell.overlay_file_name;
              targetCell.overlay_name_key = payload.name_key || sourceCell.overlay_name_key;
              targetCell.overlay_label = payload.label || sourceCell.overlay_label;
              targetCell.overlay_group = payload.group || sourceCell.overlay_group;
              targetCell.overlay_owner_color = payload.owner_color || sourceCell.overlay_owner_color || null;
              targetCell.overlay_pathfinder = !!(payload.pathfinder ?? sourceCell.overlay_pathfinder);
              targetCell.overlay_count = Math.max(1, Number(payload.count || sourceCell.overlay_count || 1));
              targetCell.guarded = false;
              clearOverlayFields(sourceCell);
            }
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
              targetCell.hero_owner_color = String(overlayOwnerColorSelect?.value || '').trim().toLowerCase() || null;
              targetCell.hero_pathfinder = false;
              guardedInput.disabled = !canUseGuardedMarker(targetCell, null, null, 'hero');
              guardedInput.checked = !!targetCell.guarded;
              emitCellPatch([targetCell]);
              handledDirectly = true;
            } else {
              guardedInput.disabled = !canUseGuardedMarker(state.cellsByKey[key(row, col)], payload.type, droppedAsset);
            }
          }
          if (handledDirectly) {
            renderGrid();
            renderInspectorPreview();
            syncPaletteSelection();
            const selectedCell = state.cellsByKey[selectedKey];
            if (selectedCell) syncHeroPanelForSelection(selectedCell);
            return;
          }
          applySelectionSilent();
          syncPaletteSelection();
        });
        rowEl.appendChild(el);
      }
      gridEl.appendChild(rowEl);
    }
    hydrateOwnedTokens(gridEl);
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
    syncOwnerSelect(cell);
    overlayCountInput.value = cell.overlay_count || 0;
    guardedInput.checked = !!cell.guarded;
    const asset = overlayAssetByFile(cell.overlay_kind, cell.overlay_file_name);
    guardedInput.disabled = !canUseGuardedMarker(cell, cell.overlay_kind, asset, activeUnitKind);
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
    const ownerValue = String(overlayOwnerColorSelect?.value || '').trim().toLowerCase() || null;
    cells.forEach(cell => {
      const focusedKind = activeUnitKey === key(cell.row, cell.col) ? activeUnitKind : null;
      cell.texture_file_name = draft.textureFileName;
      cell.overlay_kind = draft.overlayKind;
      cell.overlay_file_name = draft.overlayFileName;
      cell.overlay_name_key = asset?.name_key || null;
      cell.overlay_label = asset?.label || null;
      cell.overlay_group = asset?.group || null;
      cell.overlay_owner_color = (
        draft.overlayKind === 'entity' ||
        (draft.overlayKind === 'landmark' && asset && String(asset.name_key || '').trim().toLowerCase() === 'boat')
      ) ? ownerValue : null;
      cell.overlay_count = draft.overlayCount;
      cell.overlay_pathfinder = (
        draft.overlayKind === 'entity' ||
        (draft.overlayKind === 'landmark' && asset && String(asset.name_key || '').trim().toLowerCase() === 'boat')
      ) ? !!cell.overlay_pathfinder : false;
      cell.guarded = !!(guardedInput.checked && canUseGuardedMarker(cell, draft.overlayKind, asset, focusedKind));
      if (focusedKind === 'hero') {
        cell.hero_owner_color = ownerValue;
      } else if (!focusedKind && hasHero(cell)) {
        cell.hero_owner_color = ownerValue;
      }
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
    if (hasOwnedMovableOverlay(cell)) {
      if (toast) showToast('Owned units must be removed from the unit controls', false);
      return;
    }
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
    const clearable = cells.filter((cell) => !hasOwnedMovableOverlay(cell));
    if (!clearable.length) {
      if (toast) showToast('Owned units must be removed from the unit controls', false);
      return;
    }
    clearable.forEach(clearOverlayFields);
    emitCellPatch(clearable);
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
        guardedInput.disabled = !canUseGuardedMarker(cell, cell.overlay_kind, asset);
        renderInspectorPreview();
        syncPaletteSelection();
      }
    }
    if (toast) showToast(clearable.length !== cells.length ? 'Cleared non-owned overlays' : 'Overlay cleared');
  }

  function updateActiveHeroPathfinder(enabled) {
    if (!activeUnitKey || !state.cellsByKey[activeUnitKey] || !activeUnitKind) return;
    const cell = state.cellsByKey[activeUnitKey];
    if (!hasMovableUnit(cell)) return;
    setUnitPathfinder(cell, activeUnitKind, enabled);
    emitCellPatch([cell]);
    renderInspectorPreview();
    renderGrid();
    syncHeroPanelForSelection(cell);
  }

  function updateActiveHeroCount(value) {
    if (!activeUnitKey || !state.cellsByKey[activeUnitKey] || !activeUnitKind) return;
    const cell = state.cellsByKey[activeUnitKey];
    if (!hasMovableUnit(cell)) return;
    setUnitCount(cell, activeUnitKind, value);
    if (heroCountInput) heroCountInput.value = String(getUnitCount(cell, activeUnitKind));
    emitCellPatch([cell]);
    renderInspectorPreview();
    renderGrid();
    syncHeroPanelForSelection(cell);
  }

  function removeActiveHero() {
    if (!activeUnitKey || !state.cellsByKey[activeUnitKey] || !activeUnitKind) return;
    const cell = state.cellsByKey[activeUnitKey];
    if (!hasMovableUnit(cell)) {
      closeHeroActions();
      return;
    }
    clearUnitFields(cell, activeUnitKind);
    emitCellPatch([cell]);
    closeHeroActions();
    renderGrid();
    renderInspectorPreview();
    showToast(activeUnitKind === 'hero' ? 'Hero removed' : 'Unit removed');
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
    const selectedCell = selectedKey ? state.cellsByKey[selectedKey] : null;
    const asset = overlayAssetByFile(overlayKindSelect.value, overlayAssetSelect.value);
    guardedInput.disabled = !canUseGuardedMarker(selectedCell, overlayKindSelect.value, asset, activeUnitKind);
    guardedInput.checked = guardedInput.disabled ? false : !!selectedCell?.guarded;
    if (overlayKindSelect.value !== 'entity' && overlayOwnerColorSelect) overlayOwnerColorSelect.value = '';
    applySelectionSilent();
  });

  overlayAssetSelect?.addEventListener('change', () => {
    const asset = overlayAssetByFile(overlayKindSelect.value, overlayAssetSelect.value);
    const selectedCell = selectedKey ? state.cellsByKey[selectedKey] : null;
    guardedInput.disabled = !canUseGuardedMarker(selectedCell, overlayKindSelect.value, asset, activeUnitKind);
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

  [textureSelect, overlayCountInput, guardedInput, overlayOwnerColorSelect].forEach(el => {
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
    if (activeUnitKey && state.cellsByKey[activeUnitKey]) {
      syncHeroPanelForSelection(state.cellsByKey[activeUnitKey]);
    }
  });

  buildIndex();
  populateOwnerSelect(overlayOwnerColorSelect);
  renderTextureOptions();
  renderOverlayAssetOptions('');
  renderTexturePalette();
  renderOverlayPalette();
  renderInspectorPreview();
  applyEditorViewportTransform();
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

  shellEl?.addEventListener('wheel', handleEditorZoom, { passive: false });
  shellEl?.addEventListener('pointerdown', beginEditorPan);
  shellEl?.addEventListener('pointermove', updateEditorPan);
  shellEl?.addEventListener('pointerup', endEditorPan);
  shellEl?.addEventListener('pointercancel', endEditorPan);
  shellEl?.addEventListener('lostpointercapture', endEditorPan);
  shellEl?.addEventListener('click', swallowPanClick, true);
  shellEl?.addEventListener('dragstart', (event) => {
    if (!panState) return;
    event.preventDefault();
  });

  heroVisionButtons.forEach((btn) => {
    btn.addEventListener('click', async () => {
      if (!activeUnitKey || !state.cellsByKey[activeUnitKey]) {
        closeHeroActions();
        return;
      }
      const cell = state.cellsByKey[activeUnitKey];
      const range = Number(btn.dataset.visionRange || 1);
      const unitKind = activeUnitKind;
      closeHeroActions();
      await captureHeroVision(cell, range, unitKind);
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
    if (e.target && e.target.closest && e.target.closest('[data-unit-kind]')) return;
    closeHeroActions();
  });
})();
