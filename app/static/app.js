/* ============================================================
   SuperGallery — app.js   vanilla SPA, no build step
   ============================================================ */
'use strict';

// ── Constants ─────────────────────────────────────────────
const PAGE_SIZE = 120;

// ── State ─────────────────────────────────────────────────
const state = {
  view: 'gallery',
  sort: 'month_desc',
  search: '',
  personFilter: null,       // { id, name } when viewing a person's photos
  tagFilters: {},           // { category: [label, …] } active chip filters
  page: 1,                  // 1-based, matches API
  totalPages: 1,
  loading: false,
  photos: [],               // all photos loaded so far
  lastMonthLabel: null,     // for month-header grouping
  selectedPhotoId: null,
  detailImg: null,
  detailDetections: [],
  showBboxes: true,
  sdPairs: [],
  sdIdx: 0,
  renamingPerson: null,
  sseSource: null,
};

// ── DOM shortcuts ─────────────────────────────────────────
const $ = id => document.getElementById(id);

const D = {
  menuBtn:       $('menu-btn'),
  sidebar:       $('sidebar'),
  searchInput:   $('search-input'),
  searchClear:   $('search-clear'),
  importBtn:      $('import-btn'),
  analyzeBtn:     $('analyze-btn'),
  facesBtn:       $('faces-btn'),
  progressWrap:   $('progress-bar-wrap'),
  progressFill:   $('progress-fill'),
  progressOp:     $('progress-op'),
  progressCounts: $('progress-counts'),
  tileSlider:     $('tile-slider'),
  viewGallery:   $('view-gallery'),
  viewPeople:    $('view-people'),
  viewMap:       $('view-map'),
  personHeader:  $('person-header'),
  backToPeople:  $('back-to-people'),
  phName:        $('ph-name'),
  phCount:       $('ph-count'),
  phChips:       $('ph-chips'),
  galleryControls:$('gallery-controls'),
  sortSelect:    $('sort-select'),
  galleryCount:  $('gallery-count'),
  photoGrid:     $('photo-grid'),
  loadSentinel:  $('load-sentinel'),
  peopleGrid:    $('people-grid'),
  mapFrame:      $('map-frame'),
  detailPanel:   $('detail-panel'),
  closeDetail:   $('close-detail'),
  detailFilename:$('detail-filename'),
  bboxToggle:    $('bbox-toggle'),
  photoCanvas:   $('photo-canvas'),
  detailMeta:    $('detail-meta'),
  detailTags:    $('detail-tags'),
  newTagInput:   $('new-tag-input'),
  newTagCat:     $('new-tag-cat'),
  addTagBtn:     $('add-tag-btn'),
  sameDiffBar:   $('same-diff-bar'),
  sdFaceA:       $('sd-face-a'),
  sdFaceB:       $('sd-face-b'),
  sdNames:       $('sd-names'),
  sdSame:        $('sd-same'),
  sdDiff:        $('sd-diff'),
  sdDismiss:     $('sd-dismiss'),
  importDialog:  $('import-dialog'),
  importOverlay: $('import-overlay'),
  importPath:    $('import-path'),
  importCancel:  $('import-cancel'),
  importConfirm: $('import-confirm'),
  renameDialog:  $('rename-dialog'),
  renameOverlay: $('rename-overlay'),
  renameInput:   $('rename-input'),
  renameCancel:  $('rename-cancel'),
  renameConfirm: $('rename-confirm'),
};

// ── Scroll observer ───────────────────────────────────────
function initScrollObserver() {
  const obs = new IntersectionObserver(entries => {
    if (entries[0].isIntersecting) loadMorePhotos();
  }, { rootMargin: '300px' });
  obs.observe(D.loadSentinel);
}

// ── Navigation ────────────────────────────────────────────
function switchView(v) {
  state.view = v;

  // Nav buttons
  document.querySelectorAll('[data-view]').forEach(b =>
    b.classList.toggle('active', b.dataset.view === v));

  // Views — use both hidden + active class (CSS uses .view.active)
  const viewMap = { gallery: D.viewGallery, people: D.viewPeople, map: D.viewMap };
  Object.entries(viewMap).forEach(([name, el]) => {
    const on = name === v;
    el.hidden = !on;
    el.classList.toggle('active', on);
  });

  if (v === 'gallery' && !state.personFilter) {
    // Normal gallery — reset only if no photos loaded yet
    if (state.photos.length === 0) resetAndLoad();
  } else if (v === 'people') {
    closeDetail();
    loadPeople();
  } else if (v === 'map') {
    closeDetail();
    loadMap();
  }
}

// ── Build filters object for API ──────────────────────────
function buildFilters() {
  const f = {};
  if (state.personFilter) {
    f['People'] = [state.personFilter.name];
  }
  for (const [cat, labels] of Object.entries(state.tagFilters)) {
    if (f[cat]) {
      f[cat] = [...new Set([...f[cat], ...labels])];
    } else {
      f[cat] = [...labels];
    }
  }
  return f;
}

// ── Month label from ISO date string ─────────────────────
function monthLabel(dateStr) {
  if (!dateStr) return 'Unknown date';
  const d = new Date(dateStr);
  if (isNaN(d)) return 'Unknown date';
  return d.toLocaleDateString('en-GB', { month: 'long', year: 'numeric' });
}

// ── Photo loading ─────────────────────────────────────────
function resetAndLoad() {
  state.page = 1;
  state.totalPages = 1;
  state.photos = [];
  state.lastMonthLabel = null;
  D.photoGrid.innerHTML = '';
  D.galleryCount.textContent = '';
  loadMorePhotos();
}

async function loadMorePhotos() {
  if (state.loading || state.page > state.totalPages) return;
  state.loading = true;

  const filters = buildFilters();
  const params  = new URLSearchParams({
    sort:      state.sort,
    filters:   JSON.stringify(filters),
    page:      state.page,
    page_size: PAGE_SIZE,
  });

  try {
    const res  = await fetch(`/api/photos?${params}`);
    const data = await res.json();

    state.totalPages = data.pages || 1;

    // Client-side text search on filename
    let photos = data.photos || [];
    if (state.search) {
      const q = state.search.toLowerCase();
      photos = photos.filter(p => (p.filename || '').toLowerCase().includes(q));
    }

    appendPhotos(photos, state.page === 1);
    state.photos.push(...photos);
    state.page++;
    D.galleryCount.textContent = `${state.photos.length.toLocaleString()} photos`;
  } catch (e) {
    console.error('load photos', e);
  } finally {
    state.loading = false;
  }
}

// ── Render photo tiles ────────────────────────────────────
function appendPhotos(photos, isFirst) {
  if (isFirst) {
    D.photoGrid.innerHTML = '';
    state.lastMonthLabel = null;
  }
  if (photos.length === 0 && isFirst) {
    D.photoGrid.innerHTML = '<div class="empty-msg">No photos found.</div>';
    return;
  }

  photos.forEach(photo => {
    const ml = monthLabel(photo.date_taken);
    if (ml !== state.lastMonthLabel) {
      state.lastMonthLabel = ml;
      const hdr = document.createElement('div');
      hdr.className = 'month-header';
      hdr.textContent = ml;
      D.photoGrid.appendChild(hdr);
    }
    D.photoGrid.appendChild(makeTile(photo));
  });
}

function makeTile(photo) {
  const tile = document.createElement('div');
  tile.className = 'photo-tile';

  const img = document.createElement('img');
  img.alt = photo.filename || '';
  img.draggable = false;

  // Lazy-load thumbnail via IntersectionObserver
  const obs = new IntersectionObserver(entries => {
    if (entries[0].isIntersecting) {
      img.src = `/api/photos/${photo.id}/thumb`;
      obs.disconnect();
    }
  }, { rootMargin: '200px' });
  obs.observe(tile);

  tile.appendChild(img);
  tile.addEventListener('click', () => openDetail(photo.id, photo));
  return tile;
}

// ── Photo detail panel ────────────────────────────────────
async function openDetail(photoId, photoHint) {
  state.selectedPhotoId = photoId;
  state.detailImg       = null;
  state.detailDetections = [];

  const photo = photoHint || state.photos.find(p => p.id === photoId) || { id: photoId };

  D.detailFilename.textContent = photo.filename || `Photo ${photoId}`;
  D.detailPanel.hidden = false;

  // Fetch tags + detections in parallel
  const [tags, dets] = await Promise.all([
    fetch(`/api/photos/${photoId}/tags`).then(r => r.json()),
    fetch(`/api/photos/${photoId}/detections`).then(r => r.json()),
  ]);

  state.detailDetections = dets;

  D.bboxToggle.hidden = dets.length === 0;
  D.bboxToggle.textContent = state.showBboxes ? 'Hide boxes' : 'Show boxes';

  renderMeta(photo);
  renderTags(tags, photoId);
  drawCanvas(photoId);
}

function drawCanvas(photoId) {
  const canvas = D.photoCanvas;
  const ctx    = canvas.getContext('2d');
  const wrap   = canvas.parentElement;

  const img = new Image();
  img.src = `/api/photos/${photoId}/image`;
  state.detailImg = img;

  img.onload = () => {
    const maxW  = wrap.clientWidth  || 400;
    const maxH  = wrap.clientHeight || 500;
    const scale = Math.min(maxW / img.naturalWidth, maxH / img.naturalHeight, 1);
    canvas.width  = Math.round(img.naturalWidth  * scale);
    canvas.height = Math.round(img.naturalHeight * scale);
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
    if (state.showBboxes) paintBboxes(ctx, canvas.width, canvas.height);
  };
}

const BOX_COLORS = [
  '#FF5252', '#FF6D00', '#FFD740', '#69F0AE',
  '#40C4FF', '#E040FB', '#F06292', '#80CBC4',
];

function paintBboxes(ctx, W, H) {
  state.detailDetections.forEach((det, i) => {
    const [bx, by, bw, bh] = det.bbox;
    const x = bx * W, y = by * H, w = bw * W, h = bh * H;
    const color = BOX_COLORS[i % BOX_COLORS.length];

    ctx.strokeStyle = color;
    ctx.lineWidth   = 2;
    ctx.strokeRect(x, y, w, h);

    const pct   = Math.round((det.confidence || 0) * 100);
    const label = `${det.label} ${pct}%`;
    ctx.font     = 'bold 11px system-ui, sans-serif';
    const tw     = ctx.measureText(label).width;
    ctx.fillStyle = color;
    ctx.fillRect(x, y > 18 ? y - 18 : y + h, tw + 8, 18);
    ctx.fillStyle = '#000';
    ctx.fillText(label, x + 4, y > 18 ? y - 4 : y + h + 14);
  });
}

function repaintCanvas() {
  if (!state.detailImg || !state.detailImg.complete) return;
  const canvas = D.photoCanvas;
  const ctx    = canvas.getContext('2d');
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(state.detailImg, 0, 0, canvas.width, canvas.height);
  if (state.showBboxes) paintBboxes(ctx, canvas.width, canvas.height);
}

function renderMeta(photo) {
  const rows = [];
  if (photo.date_taken) {
    rows.push(['Date', new Date(photo.date_taken).toLocaleDateString('en-GB', { dateStyle: 'long' })]);
  }
  if (photo.camera_model) rows.push(['Camera', photo.camera_model]);
  if (photo.width && photo.height) rows.push(['Size', `${photo.width} × ${photo.height}`]);
  D.detailMeta.innerHTML = rows.map(([k, v]) =>
    `<div class="meta-row"><span class="meta-key">${k}</span><span class="meta-val">${escHtml(String(v))}</span></div>`
  ).join('');
}

function renderTags(tags, photoId) {
  const grouped = {};
  tags.forEach(t => { (grouped[t.category] = grouped[t.category] || []).push(t); });

  D.detailTags.innerHTML = Object.entries(grouped).map(([cat, list]) =>
    `<div class="tag-group">
      <div class="tag-group-label">${escHtml(cat)}</div>
      <div class="tag-chips">
        ${list.map(t =>
          `<span class="tag-chip cat-${escHtml(cat)}">
            ${escHtml(t.label)}
            <button class="del-btn" data-tag-id="${t.id}" aria-label="Remove tag">×</button>
          </span>`
        ).join('')}
      </div>
    </div>`
  ).join('');

  D.detailTags.querySelectorAll('.del-btn').forEach(btn => {
    btn.addEventListener('click', async e => {
      e.stopPropagation();
      await fetch(`/api/tags/${btn.dataset.tagId}`, { method: 'DELETE' });
      openDetail(photoId);
    });
  });
}

function closeDetail() {
  D.detailPanel.hidden = true;
  state.selectedPhotoId = null;
  state.detailImg = null;
}

// ── People view ───────────────────────────────────────────
async function loadPeople() {
  D.peopleGrid.innerHTML = '<div class="loading-msg">Loading…</div>';
  try {
    const data = await fetch('/api/people').then(r => r.json());
    renderPeopleGrid(Array.isArray(data) ? data : (data.people || []));
    loadSimilarPairs();
  } catch (e) {
    D.peopleGrid.innerHTML = '<div class="empty-msg">Could not load people.</div>';
  }
}

function renderPeopleGrid(people) {
  if (!people.length) {
    D.peopleGrid.innerHTML =
      '<div class="empty-msg">No people identified yet.<br>Import photos and run face processing.</div>';
    return;
  }

  D.peopleGrid.innerHTML = people.map(p =>
    `<div class="person-card" data-id="${p.id}" data-name="${escAttr(p.name || '')}">
      ${p.has_thumb
        ? `<img class="person-avatar" src="/api/people/${p.id}/thumb"
               alt="${escAttr(p.name || '?')}" loading="lazy"
               onerror="this.style.display='none';this.nextElementSibling.style.display='flex'">`
        : ''
      }
      <div class="person-avatar-placeholder" style="${p.has_thumb ? 'display:none' : ''}">
        <span>${avatarInitial(p.name)}</span>
      </div>
      <div class="person-name">${escHtml(p.name || 'Unknown')}</div>
      <div class="person-count">${p.photo_count || 0} photo${(p.photo_count || 0) === 1 ? '' : 's'}</div>
    </div>`
  ).join('');

  D.peopleGrid.querySelectorAll('.person-card').forEach(el => {
    el.addEventListener('click', () =>
      openPersonGallery({ id: +el.dataset.id, name: el.dataset.name }));
  });
}

function avatarInitial(name) {
  return (name || '?').trim()[0].toUpperCase();
}

// Called by inline onerror — must be global
window.makeAvatarFallback = function(name) {
  const d = document.createElement('div');
  d.className = 'person-avatar-fallback';
  d.textContent = avatarInitial(name);
  return d;
};

// ── Person gallery (gallery view filtered to one person) ──
async function openPersonGallery(person) {
  state.personFilter = person;
  state.tagFilters   = {};
  D.personHeader.hidden = false;
  D.phName.textContent  = escHtml(person.name || 'Unknown');
  D.phCount.textContent = '';
  D.phChips.innerHTML   = '';

  switchView('gallery');
  resetAndLoad();

  // Update count after load
  setTimeout(() => {
    D.phCount.textContent = state.photos.length
      ? `${state.photos.length} photo${state.photos.length === 1 ? '' : 's'}`
      : '';
  }, 1200);

  // Load tag chips for this person
  try {
    const tags = await fetch(`/api/people/${person.id}/top-tags`).then(r => r.json());
    renderPersonChips(tags, person);
  } catch (_) {}
}

function renderPersonChips(tags, person) {
  const arr = Array.isArray(tags) ? tags : (tags.tags || []);

  const chipsHtml = arr.map(t =>
    `<button class="filter-chip cat-${escHtml(t.category)}"
             data-cat="${escAttr(t.category)}" data-label="${escAttr(t.label)}">
      ${escHtml(t.label)}
    </button>`
  ).join('');

  D.phChips.innerHTML =
    chipsHtml +
    `<button class="filter-chip rename-chip" data-person-id="${person.id}">Rename…</button>`;

  D.phChips.querySelectorAll('.filter-chip[data-cat]').forEach(btn => {
    btn.addEventListener('click', () => {
      btn.classList.toggle('active');
      const cat   = btn.dataset.cat;
      const label = btn.dataset.label;
      if (btn.classList.contains('active')) {
        state.tagFilters[cat] = [...(state.tagFilters[cat] || []), label];
      } else {
        state.tagFilters[cat] = (state.tagFilters[cat] || []).filter(l => l !== label);
        if (!state.tagFilters[cat].length) delete state.tagFilters[cat];
      }
      resetAndLoad();
    });
  });

  D.phChips.querySelectorAll('.rename-chip').forEach(btn => {
    btn.addEventListener('click', () => openRenameDialog(person));
  });
}

function backToPeople() {
  state.personFilter = null;
  state.tagFilters   = {};
  D.personHeader.hidden = true;
  state.photos = [];
  switchView('people');
}

// ── Same / Different person bar ───────────────────────────
async function loadSimilarPairs() {
  try {
    const pairs = await fetch('/api/people/similar').then(r => r.json());
    state.sdPairs = Array.isArray(pairs) ? pairs : [];
    state.sdIdx   = 0;
    showNextPair();
  } catch (_) {
    D.sameDiffBar.hidden = true;
  }
}

function showNextPair() {
  while (state.sdIdx < state.sdPairs.length) {
    const pair = state.sdPairs[state.sdIdx];
    if (pair) { showPair(pair); return; }
    state.sdIdx++;
  }
  D.sameDiffBar.hidden = true;
}

function showPair(pair) {
  D.sdFaceA.src  = `/api/people/${pair.person_a}/thumb`;
  D.sdFaceB.src  = `/api/people/${pair.person_b}/thumb`;
  D.sdFaceA.onerror = () => { D.sdFaceA.src = ''; D.sdFaceA.style.background = '#333'; };
  D.sdFaceB.onerror = () => { D.sdFaceB.src = ''; D.sdFaceB.style.background = '#333'; };
  D.sdNames.textContent = `${pair.name_a || 'Person A'} & ${pair.name_b || 'Person B'}`;
  D.sameDiffBar.hidden  = false;
}

async function onSamePerson() {
  const pair = state.sdPairs[state.sdIdx];
  if (!pair) return;
  try {
    await fetch('/api/people/merge', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ keep_id: pair.person_a, remove_id: pair.person_b }),
    });
    toast('People merged.');
    if (state.view === 'people') loadPeople();
  } catch (_) { toast('Merge failed.', 'error'); }
  dismissPair();
}

function dismissPair() {
  state.sdIdx++;
  showNextPair();
}

// ── Map view ──────────────────────────────────────────────
function loadMap() {
  // The API returns an HTML page — load it directly in the iframe
  if (!D.mapFrame.src || D.mapFrame.src === 'about:blank') {
    D.mapFrame.src = '/api/map';
  }
}

// ── Search ────────────────────────────────────────────────
let searchTimer = null;

function onSearchInput() {
  const q = D.searchInput.value.trim();
  state.search = q;
  D.searchClear.hidden = !q;
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    if (state.view === 'gallery') resetAndLoad();
  }, 320);
}

// ── SSE Progress ──────────────────────────────────────────
function startSSE() {
  if (state.sseSource) { state.sseSource.close(); state.sseSource = null; }
  const src = new EventSource('/api/status/stream');
  state.sseSource = src;
  let wasRunning = false;

  src.onmessage = e => {
    const d = JSON.parse(e.data);
    if (d.running) {
      wasRunning = true;
      showProgress(d);
    } else {
      showProgress(d); // briefly show completion label
      if (wasRunning) {
        wasRunning = false;
        setTimeout(() => {
          hideProgress();
          const done = ['import_done','analyze_done','faces_done','thumbs_done'];
          if (done.includes(d.operation)) {
            if (state.view === 'gallery') resetAndLoad();
            if (d.operation === 'faces_done') loadPeople();
            else if (state.view === 'people') loadPeople();
          }
        }, 2200);
      }
    }
  };

  src.onerror = () => {
    src.close();
    state.sseSource = null;
    setTimeout(startSSE, 4000);
  };
}

const OP_LABELS = {
  import:       'Importing photos',
  analyze:      'AI Analysis',
  faces:        'Face Processing',
  thumbs:       'Generating thumbnails',
  import_done:  'Import complete',
  analyze_done: 'Analysis complete',
  faces_done:   'Face processing complete',
  thumbs_done:  'Thumbnails ready',
  error:        'Error',
};

function showProgress(d) {
  D.progressWrap.hidden = false;
  document.body.classList.add('progress-active');
  const label = d.op_label || OP_LABELS[d.operation] || d.operation || '';
  D.progressOp.textContent = label;
  if (d.total > 0) {
    D.progressCounts.textContent = `${d.done.toLocaleString()} / ${d.total.toLocaleString()} photos`;
  } else {
    D.progressCounts.textContent = d.message || '';
  }
  const pct = d.total > 0 ? (d.done / d.total) * 100 : (d.running ? 40 : 100);
  D.progressFill.style.width = pct + '%';
}

function hideProgress() {
  D.progressWrap.hidden = true;
  document.body.classList.remove('progress-active');
  D.progressFill.style.width = '0';
  D.progressOp.textContent = '';
  D.progressCounts.textContent = '';
}

// ── Import ────────────────────────────────────────────────
function openImportDialog() {
  D.importDialog.hidden = false;
  setTimeout(() => D.importPath.focus(), 50);
}
function closeImportDialog() {
  D.importDialog.hidden = true;
  D.importPath.value = '';
}
async function confirmImport() {
  const folder = D.importPath.value.trim();
  if (!folder) return;
  closeImportDialog();
  try {
    const res  = await fetch('/api/import', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ folder }),
    });
    const data = await res.json();
    if (data.error) toast(data.error, 'error');
    else toast('Import started…');
  } catch (_) { toast('Import request failed.', 'error'); }
}

// ── Analyse ───────────────────────────────────────────────
async function startAnalyze() {
  try {
    const data = await fetch('/api/analyze', { method: 'POST' }).then(r => r.json());
    if (data.error) toast(data.error, 'error');
    else toast('AI analysis started…');
  } catch (_) { toast('Request failed.', 'error'); }
}

// ── Face processing ───────────────────────────────────────
async function startFaces() {
  try {
    const data = await fetch('/api/faces', { method: 'POST' }).then(r => r.json());
    if (data.error) toast(data.error, 'error');
    else toast('Face processing started…');
  } catch (_) { toast('Request failed.', 'error'); }
}

// ── Rename dialog ─────────────────────────────────────────
function openRenameDialog(person) {
  state.renamingPerson = person;
  D.renameInput.value  = person.name || '';
  D.renameDialog.hidden = false;
  setTimeout(() => { D.renameInput.focus(); D.renameInput.select(); }, 50);
}
function closeRenameDialog() {
  D.renameDialog.hidden = true;
  state.renamingPerson  = null;
}
async function confirmRename() {
  const p    = state.renamingPerson;
  const name = D.renameInput.value.trim();
  if (!p || !name) return;
  closeRenameDialog();
  try {
    await fetch(`/api/people/${p.id}/rename`, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ name }),
    });
    toast(`Renamed to "${name}"`);
    if (state.personFilter && state.personFilter.id === p.id) {
      state.personFilter.name = name;
      D.phName.textContent = name;
    }
    if (state.view === 'people') loadPeople();
  } catch (_) { toast('Rename failed.', 'error'); }
}

// ── Add tag ───────────────────────────────────────────────
async function addTag() {
  const photoId = state.selectedPhotoId;
  if (!photoId) return;
  const label    = D.newTagInput.value.trim();
  const category = D.newTagCat.value;
  if (!label) return;
  await fetch('/api/tags', {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify({ photo_id: photoId, label, category }),
  });
  D.newTagInput.value = '';
  openDetail(photoId);   // refresh tags
}

// ── Toast ─────────────────────────────────────────────────
let _toastEl = null, _toastTimer = null;

function toast(msg, type = 'info') {
  if (!_toastEl) {
    _toastEl = document.createElement('div');
    _toastEl.className = 'toast';
    document.body.appendChild(_toastEl);
  }
  _toastEl.textContent = msg;
  _toastEl.className   = `toast toast-${type} show`;
  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => _toastEl.classList.remove('show'), 3200);
}

// ── Helpers ───────────────────────────────────────────────
function escHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
function escAttr(s) {
  return String(s).replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

// ── Event wiring ──────────────────────────────────────────
function init() {
  // View nav buttons (sidebar + bottom nav)
  document.querySelectorAll('[data-view]').forEach(btn => {
    btn.addEventListener('click', () => switchView(btn.dataset.view));
  });

  // Hamburger
  D.menuBtn.addEventListener('click', () => D.sidebar.classList.toggle('open'));

  // Close sidebar when nav item clicked (mobile)
  D.sidebar.querySelectorAll('.nav-btn').forEach(btn => {
    btn.addEventListener('click', () => D.sidebar.classList.remove('open'));
  });

  // Search
  D.searchInput.addEventListener('input', onSearchInput);
  D.searchClear.addEventListener('click', () => {
    D.searchInput.value = '';
    D.searchClear.hidden = true;
    state.search = '';
    if (state.view === 'gallery') resetAndLoad();
  });

  // Sort
  D.sortSelect.addEventListener('change', () => {
    state.sort = D.sortSelect.value;
    resetAndLoad();
  });

  // Import
  D.importBtn.addEventListener('click', openImportDialog);
  D.importOverlay.addEventListener('click', closeImportDialog);
  D.importCancel.addEventListener('click', closeImportDialog);
  D.importConfirm.addEventListener('click', confirmImport);
  D.importPath.addEventListener('keydown', e => { if (e.key === 'Enter') confirmImport(); });

  // Analyse
  D.analyzeBtn.addEventListener('click', startAnalyze);

  // Faces
  D.facesBtn.addEventListener('click', startFaces);

  // Detail panel
  D.closeDetail.addEventListener('click', closeDetail);
  D.bboxToggle.addEventListener('click', () => {
    state.showBboxes = !state.showBboxes;
    D.bboxToggle.textContent = state.showBboxes ? 'Hide boxes' : 'Show boxes';
    repaintCanvas();
  });
  D.addTagBtn.addEventListener('click', addTag);
  D.newTagInput.addEventListener('keydown', e => { if (e.key === 'Enter') addTag(); });

  // Back to people
  D.backToPeople.addEventListener('click', backToPeople);

  // Same/diff bar
  D.sdSame.addEventListener('click', onSamePerson);
  D.sdDiff.addEventListener('click', dismissPair);
  D.sdDismiss.addEventListener('click', dismissPair);

  // Rename
  D.renameOverlay.addEventListener('click', closeRenameDialog);
  D.renameCancel.addEventListener('click', closeRenameDialog);
  D.renameConfirm.addEventListener('click', confirmRename);
  D.renameInput.addEventListener('keydown', e => { if (e.key === 'Enter') confirmRename(); });

  // Keyboard shortcuts
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') {
      if (!D.importDialog.hidden)  { closeImportDialog();  return; }
      if (!D.renameDialog.hidden)  { closeRenameDialog();  return; }
      if (!D.detailPanel.hidden)   { closeDetail();         return; }
    }
    // Close sidebar overlay on outside click (mobile)
    if (D.sidebar.classList.contains('open') &&
        !D.sidebar.contains(document.activeElement)) {
      D.sidebar.classList.remove('open');
    }
  });

  // Close sidebar when clicking outside (mobile)
  document.addEventListener('click', e => {
    if (D.sidebar.classList.contains('open') &&
        !D.sidebar.contains(e.target) &&
        e.target !== D.menuBtn) {
      D.sidebar.classList.remove('open');
    }
  });

  // Tile size slider
  const savedSize = localStorage.getItem('tileSize');
  if (savedSize && D.tileSlider) {
    D.tileSlider.value = savedSize;
    document.documentElement.style.setProperty('--tile-size', savedSize + 'px');
  }
  if (D.tileSlider) {
    D.tileSlider.addEventListener('input', () => {
      const v = D.tileSlider.value;
      document.documentElement.style.setProperty('--tile-size', v + 'px');
      localStorage.setItem('tileSize', v);
    });
  }

  // Infinite scroll sentinel
  initScrollObserver();

  // SSE for progress
  startSSE();

  // Initial view
  switchView('gallery');
}

document.addEventListener('DOMContentLoaded', init);
