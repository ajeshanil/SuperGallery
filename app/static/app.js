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
  favoritesOnly: false,
  personFilter: null,       // { id, name } when viewing a person's photos
  albumFilter: null,        // { id, name } when viewing an album's photos
  searchIds: null,          // Set of photo IDs from server-side search, or null
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
  lightboxScale: 1,
  lightboxPinchDist: null,
  sdPairs: [],
  sdIdx: 0,
  renamingPerson: null,
  sseSource: null,
  runningOp: null,    // current SSE operation string while running
  runningProgress: { done: 0, total: 0 },
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
  analyzePhotoBtn:$('analyze-photo-btn'),
  progressWrap:   $('progress-bar-wrap'),
  progressFill:   $('progress-fill'),
  progressOp:     $('progress-op'),
  progressFile:   $('progress-file'),
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
  filterChipsBar:$('filter-chips-bar'),
  galleryControls:$('gallery-controls'),
  sortSelect:    $('sort-select'),
  galleryCount:  $('gallery-count'),
  photoGrid:     $('photo-grid'),
  loadSentinel:  $('load-sentinel'),
  peopleGrid:    $('people-grid'),
  mapFrame:      $('map-frame'),
  detailPanel:   $('detail-panel'),
  closeDetail:   $('close-detail'),
  detailPrev:    $('detail-prev'),
  detailNext:    $('detail-next'),
  detailFav:     $('detail-fav'),
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
  importDialog:   $('import-dialog'),
  importOverlay:  $('import-overlay'),
  importPath:     $('import-path'),
  importCancel:   $('import-cancel'),
  importConfirm:  $('import-confirm'),
  resetAnalysisBtn: $('reset-analysis-btn'),
  resetAllBtn:      $('reset-all-btn'),
  renameDialog:  $('rename-dialog'),
  renameOverlay: $('rename-overlay'),
  renameInput:   $('rename-input'),
  renameCancel:  $('rename-cancel'),
  renameConfirm: $('rename-confirm'),
  lightbox:      $('lightbox'),
  lightboxImg:   $('lightbox-img'),
  lightboxClose: $('lightbox-close'),
  lightboxPrev:  $('lightbox-prev'),
  lightboxNext:  $('lightbox-next'),
  runQualityTagsBtn: $('run-quality-tags-btn'),
  viewAlbums:        $('view-albums'),
  albumsGrid:        $('albums-grid'),
  generateEventsBtn: $('generate-events-btn'),
  createAlbumBtn:    $('create-album-btn'),
  albumDialog:       $('album-dialog'),
  albumOverlay:      $('album-overlay'),
  albumNameInput:    $('album-name-input'),
  albumCancel:       $('album-cancel'),
  albumConfirm:      $('album-confirm'),
  cleanupPeopleBtn:  $('cleanup-people-btn'),
  cleanupDialog:     $('cleanup-dialog'),
  cleanupOverlay:    $('cleanup-overlay'),
  cleanupThreshold:  $('cleanup-threshold'),
  cleanupList:       $('cleanup-list'),
  cleanupCancel:     $('cleanup-cancel'),
  cleanupConfirm:    $('cleanup-confirm'),
  // Timeline
  viewTimeline:      $('view-timeline'),
  timelineContainer: $('timeline-container'),
  // Duplicates
  viewDuplicates:      $('view-duplicates'),
  duplicatesContainer: $('duplicates-container'),
  dupGroupCount:       $('dup-group-count'),
  findDuplicatesBtn:   $('find-duplicates-btn'),
  // Person inline rename
  phRenameBtn:       $('ph-rename-btn'),
};

// ── Scroll observer ───────────────────────────────────────
function initScrollObserver() {
  const obs = new IntersectionObserver(entries => {
    if (entries[0].isIntersecting) loadMorePhotos();
  }, { rootMargin: '300px' });
  obs.observe(D.loadSentinel);
}

// ── Tag browser ───────────────────────────────────────────
const TAG_CAT_ORDER = ['People','Objects','Scenes','Camera','Date','Location','PhotoType'];
let _tagCounts = {};       // { category: [{label, count}, …] }
let _activeCat = 'Objects';

async function loadTagCounts() {
  try {
    _tagCounts = await fetch('/api/tags/counts').then(r => r.json());
    renderTagBrowser();
  } catch(_) {}
}

function renderTagBrowser() {
  const catTabs = $('tag-cat-tabs');
  const chipsRow = $('tag-chips-row');
  const clearBtn = $('tag-clear-btn');

  // Category tabs — only show categories that have data
  const cats = TAG_CAT_ORDER.filter(c => _tagCounts[c] && _tagCounts[c].length > 0);
  catTabs.innerHTML = cats.map(c => {
    const activeFilters = state.tagFilters[c] && state.tagFilters[c].length > 0;
    return `<button class="tag-cat-btn${_activeCat === c ? ' active' : ''}" data-cat="${c}">
      ${c}${activeFilters ? ' ●' : ''}
    </button>`;
  }).join('');
  catTabs.querySelectorAll('.tag-cat-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      _activeCat = btn.dataset.cat;
      renderTagBrowser();
    });
  });

  // Chips for active category
  const items = _tagCounts[_activeCat] || [];
  const activeFiltersForCat = state.tagFilters[_activeCat] || [];
  chipsRow.innerHTML = items.map(({label, count}) => {
    const isActive = activeFiltersForCat.includes(label);
    return `<button class="tag-chip${isActive ? ' active' : ''}" data-label="${label}">
      ${label} <span class="chip-cnt">${count}</span>
    </button>`;
  }).join('');
  chipsRow.querySelectorAll('.tag-chip').forEach(btn => {
    btn.addEventListener('click', () => toggleTagFilter(_activeCat, btn.dataset.label));
  });

  // Clear button visibility
  const hasFilters = Object.values(state.tagFilters).some(arr => arr.length > 0);
  clearBtn.hidden = !hasFilters;
}

function toggleTagFilter(category, label) {
  if (!state.tagFilters[category]) state.tagFilters[category] = [];
  const idx = state.tagFilters[category].indexOf(label);
  if (idx >= 0) {
    state.tagFilters[category].splice(idx, 1);
    if (state.tagFilters[category].length === 0) delete state.tagFilters[category];
  } else {
    state.tagFilters[category].push(label);
  }
  renderTagBrowser();
  resetAndLoad();
}

function clearAllTagFilters() {
  state.tagFilters = {};
  renderTagBrowser();
  resetAndLoad();
}

// ── Navigation ────────────────────────────────────────────
function switchView(v) {
  state.view = v;

  // Nav buttons
  document.querySelectorAll('[data-view]').forEach(b =>
    b.classList.toggle('active', b.dataset.view === v));

  // Views — use both hidden + active class (CSS uses .view.active)
  const viewMap = {
    gallery:    D.viewGallery,
    people:     D.viewPeople,
    map:        D.viewMap,
    albums:     D.viewAlbums,
    timeline:   D.viewTimeline,
    duplicates: D.viewDuplicates,
  };
  Object.entries(viewMap).forEach(([name, el]) => {
    if (!el) return;
    const on = name === v;
    el.hidden = !on;
    el.classList.toggle('active', on);
  });

  // Hide same/diff bar when leaving People view
  if (v !== 'people') D.sameDiffBar.hidden = true;

  if (v === 'gallery' && !state.personFilter && !state.albumFilter) {
    // Normal gallery — reset only if no photos loaded yet
    if (state.photos.length === 0) resetAndLoad();
  } else if (v === 'people') {
    closeDetail();
    loadPeople();
  } else if (v === 'map') {
    closeDetail();
    loadMap();
  } else if (v === 'albums') {
    closeDetail();
    loadAlbums();
  } else if (v === 'timeline') {
    closeDetail();
    loadTimeline();
  } else if (v === 'duplicates') {
    closeDetail();
    loadDuplicates();
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

// ── Skeleton tiles ────────────────────────────────────────
function showSkeletons() {
  D.photoGrid.innerHTML = '';
  const tileSize = parseInt(getComputedStyle(document.documentElement).getPropertyValue('--tile-size')) || 160;
  // Fill roughly 2 rows worth of skeletons
  const cols  = Math.max(1, Math.floor((D.photoGrid.clientWidth || 800) / (tileSize + 6)));
  const count = cols * 3;
  for (let i = 0; i < count; i++) {
    const tile = document.createElement('div');
    tile.className = 'photo-tile skeleton';
    tile.style.width  = tileSize + 'px';
    tile.style.height = tileSize + 'px';
    D.photoGrid.appendChild(tile);
  }
}

// ── Photo loading ─────────────────────────────────────────
function resetAndLoad() {
  state.page = 1;
  state.totalPages = 1;
  state.photos = [];
  state.lastMonthLabel = null;
  showSkeletons();
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
  if (state.favoritesOnly) params.set('favorite', 'true');

  try {
    const res  = await fetch(`/api/photos?${params}`);
    const data = await res.json();

    state.totalPages = data.pages || 1;

    let photos = data.photos || [];
    // Server-side search: filter by matching IDs
    if (state.searchIds !== null) {
      photos = photos.filter(p => state.searchIds.has(p.id));
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
  tile.dataset.photoId = photo.id;

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

  // Retry thumbnail if it failed (e.g. requested before bulk generation finished)
  let _thumbRetries = 0;
  img.onerror = () => {
    if (_thumbRetries < 4) {
      _thumbRetries++;
      setTimeout(() => { img.src = `/api/photos/${photo.id}/thumb?r=${_thumbRetries}`; }, 2000 * _thumbRetries);
    }
  };

  // Favorite button overlay
  const favBtn = document.createElement('button');
  favBtn.className = 'tile-fav-btn' + (photo.is_favorite ? ' favorited' : '');
  favBtn.dataset.id = photo.id;
  favBtn.setAttribute('aria-label', 'Favorite');
  favBtn.innerHTML = '<svg viewBox="0 0 24 24" width="16" height="16"><path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"/></svg>';
  favBtn.addEventListener('click', e => {
    e.stopPropagation();
    toggleFavorite(photo.id);
  });

  tile.appendChild(img);
  tile.appendChild(favBtn);
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
  D.detailFav.classList.toggle('favorited', !!photo.is_favorite);

  // Update nav arrow availability
  const idx = state.photos.findIndex(p => p.id === photoId);
  D.detailPrev.disabled = idx <= 0;
  D.detailNext.disabled = idx < 0 || idx >= state.photos.length - 1;

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

  // Remove old click listener by cloning
  const newCanvas = canvas.cloneNode(true);
  wrap.replaceChild(newCanvas, canvas);
  D.photoCanvas = newCanvas;
  const ctx2 = newCanvas.getContext('2d');

  const img = new Image();
  img.src = `/api/photos/${photoId}/image`;
  state.detailImg = img;

  img.onload = () => {
    const maxW  = wrap.clientWidth  || 400;
    const maxH  = wrap.clientHeight || 500;
    const scale = Math.min(maxW / img.naturalWidth, maxH / img.naturalHeight, 1);
    newCanvas.width  = Math.round(img.naturalWidth  * scale);
    newCanvas.height = Math.round(img.naturalHeight * scale);
    ctx2.drawImage(img, 0, 0, newCanvas.width, newCanvas.height);
    if (state.showBboxes) paintBboxes(ctx2, newCanvas.width, newCanvas.height);
  };

  newCanvas.style.cursor = 'zoom-in';
  newCanvas.addEventListener('click', openLightbox);
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

// ── Photo navigation ──────────────────────────────────────
function navPhoto(delta) {
  if (state.selectedPhotoId === null) return;
  const idx = state.photos.findIndex(p => p.id === state.selectedPhotoId);
  if (idx === -1) return;
  const next = state.photos[idx + delta];
  if (next) openDetail(next.id, next);
}

// ── Favorites ─────────────────────────────────────────────
async function toggleFavorite(photoId) {
  try {
    const res  = await fetch(`/api/photos/${photoId}/favorite`, { method: 'POST' });
    const data = await res.json();
    // Sync state
    const photo = state.photos.find(p => p.id === photoId);
    if (photo) photo.is_favorite = data.is_favorite;
    // Update tile button
    const tileFavBtn = D.photoGrid.querySelector(`.tile-fav-btn[data-id="${photoId}"]`);
    if (tileFavBtn) tileFavBtn.classList.toggle('favorited', data.is_favorite);
    // Update detail fav button
    if (state.selectedPhotoId === photoId) {
      D.detailFav.classList.toggle('favorited', data.is_favorite);
    }
    // In favorites-only mode, remove the tile if un-favorited
    if (state.favoritesOnly && !data.is_favorite) {
      const tile = D.photoGrid.querySelector(`.photo-tile[data-photo-id="${photoId}"]`);
      if (tile) tile.remove();
    }
  } catch (_) { toast('Failed to update favorite.', 'error'); }
}

// ── Lightbox ──────────────────────────────────────────────
function openLightbox() {
  if (!state.selectedPhotoId) return;
  state.lightboxScale = 1;
  D.lightboxImg.style.transform = 'scale(1)';
  D.lightboxImg.classList.remove('zoomed');
  D.lightboxImg.src = `/api/photos/${state.selectedPhotoId}/image`;
  D.lightbox.hidden = false;
}

function closeLightbox() {
  D.lightbox.hidden = true;
  D.lightboxImg.src = '';
  state.lightboxScale = 1;
}

function initLightboxZoom() {
  // Scroll to zoom
  D.lightboxImg.addEventListener('wheel', e => {
    e.preventDefault();
    const delta = e.deltaY > 0 ? -0.15 : 0.15;
    state.lightboxScale = Math.max(1, Math.min(6, state.lightboxScale + delta));
    D.lightboxImg.style.transform = `scale(${state.lightboxScale})`;
    D.lightboxImg.classList.toggle('zoomed', state.lightboxScale > 1);
  }, { passive: false });

  // Click to toggle zoom
  D.lightboxImg.addEventListener('click', e => {
    e.stopPropagation();
    if (state.lightboxScale > 1) {
      state.lightboxScale = 1;
      D.lightboxImg.classList.remove('zoomed');
    } else {
      state.lightboxScale = 2.5;
      D.lightboxImg.classList.add('zoomed');
    }
    D.lightboxImg.style.transform = `scale(${state.lightboxScale})`;
  });

  // Pinch to zoom
  D.lightbox.addEventListener('touchstart', e => {
    if (e.touches.length === 2) {
      state.lightboxPinchDist = Math.hypot(
        e.touches[0].clientX - e.touches[1].clientX,
        e.touches[0].clientY - e.touches[1].clientY,
      );
    }
  }, { passive: true });
  D.lightbox.addEventListener('touchmove', e => {
    if (e.touches.length === 2 && state.lightboxPinchDist) {
      const dist = Math.hypot(
        e.touches[0].clientX - e.touches[1].clientX,
        e.touches[0].clientY - e.touches[1].clientY,
      );
      state.lightboxScale = Math.max(1, Math.min(6, state.lightboxScale * (dist / state.lightboxPinchDist)));
      state.lightboxPinchDist = dist;
      D.lightboxImg.style.transform = `scale(${state.lightboxScale})`;
      D.lightboxImg.classList.toggle('zoomed', state.lightboxScale > 1);
    }
  }, { passive: true });
  D.lightbox.addEventListener('touchend', () => { state.lightboxPinchDist = null; }, { passive: true });
}

// ── Swipe gestures on detail panel (mobile) ───────────────
function initSwipe() {
  let sx = 0, sy = 0;
  D.detailPanel.addEventListener('touchstart', e => {
    sx = e.touches[0].clientX;
    sy = e.touches[0].clientY;
  }, { passive: true });
  D.detailPanel.addEventListener('touchend', e => {
    const dx = e.changedTouches[0].clientX - sx;
    const dy = e.changedTouches[0].clientY - sy;
    if (Math.abs(dy) > 80 && Math.abs(dy) > Math.abs(dx) && dy > 0) {
      closeDetail();                          // swipe down → close
    } else if (Math.abs(dx) > 50 && Math.abs(dx) > Math.abs(dy)) {
      navPhoto(dx < 0 ? 1 : -1);             // swipe left = next, right = prev
    }
  }, { passive: true });
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
  const hasPeopleTags = tags.some(t => t.category === 'People');
  tags.forEach(t => {
    // Suppress the generic "person" object tag when named People tags exist —
    // face processing already shows who the person is.
    if (hasPeopleTags && t.category === 'Objects' && t.label.toLowerCase() === 'person') return;
    (grouped[t.category] = grouped[t.category] || []).push(t);
  });

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
  // If face processing is actively scanning, show live progress instead of
  // the misleading "No people identified yet" message.
  if (state.runningOp === 'faces') {
    const { done, total } = state.runningProgress;
    const pct = total > 0 ? Math.round((done / total) * 100) : 0;
    D.peopleGrid.innerHTML =
      `<div class="loading-msg">
         Scanning faces… ${done.toLocaleString()} / ${total.toLocaleString()} photos (${pct}%)<br>
         <small style="color:var(--text3)">People will appear here once clustering is complete.</small>
       </div>`;
    return;
  }
  D.peopleGrid.innerHTML = '<div class="loading-msg">Loading…</div>';
  try {
    const data = await fetch('/api/people').then(r => r.json());
    renderPeopleGrid(Array.isArray(data) ? data : (data.people || []));
    loadSimilarPairs();
  } catch (e) {
    D.peopleGrid.innerHTML = '<div class="empty-msg">Could not load people.</div>';
  }
}

async function loadSimilarFaces() {
  const grid = $('similar-grid');
  grid.innerHTML = '<div class="loading-msg">Loading similar faces\u2026</div>';
  try {
    const pairs = await fetch('/api/people/similar').then(r => r.json());
    if (!pairs.length) {
      grid.innerHTML = '<div class="empty-msg">No similar face pairs found.<br><small>As more people are identified, potential matches will appear here for review.</small></div>';
      return;
    }
    grid.innerHTML = pairs.map((p, idx) => `
      <div class="sim-pair" data-idx="${idx}">
        <div class="sim-face">
          <img src="/api/people/${p.person_a}/thumb" onerror="this.style.opacity=0.3">
          <span>${escHtml(p.name_a)}</span>
        </div>
        <div class="sim-vs">\u2194</div>
        <div class="sim-face">
          <img src="/api/people/${p.person_b}/thumb" onerror="this.style.opacity=0.3">
          <span>${escHtml(p.name_b)}</span>
        </div>
        <div class="sim-actions">
          <button class="sim-same-btn" data-keep="${p.person_a}" data-remove="${p.person_b}">Same Person</button>
          <button class="sim-diff-btn">Not Same</button>
          <div class="sim-score">${Math.round(p.similarity * 100)}% similar</div>
        </div>
      </div>
    `).join('');
    grid.querySelectorAll('.sim-same-btn').forEach(btn => {
      btn.addEventListener('click', async () => {
        const pair = btn.closest('.sim-pair');
        btn.disabled = true; btn.textContent = 'Merging\u2026';
        try {
          await fetch('/api/people/merge', {
            method: 'POST', headers: {'Content-Type':'application/json'},
            body: JSON.stringify({ keep_id: +btn.dataset.keep, remove_id: +btn.dataset.remove }),
          });
          pair.style.opacity = '0'; pair.style.transition = 'opacity .3s';
          setTimeout(() => pair.remove(), 300);
          loadPeople();
        } catch(_) { btn.disabled = false; btn.textContent = 'Same Person'; }
      });
    });
    grid.querySelectorAll('.sim-diff-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const pair = btn.closest('.sim-pair');
        pair.style.opacity = '0'; pair.style.transition = 'opacity .3s';
        setTimeout(() => pair.remove(), 300);
      });
    });
  } catch(_) {
    grid.innerHTML = '<div class="empty-msg">Could not load similar faces.</div>';
  }
}

async function deletePerson(id) {
  if (!confirm('Delete this person? All their face links and tags will be removed.')) return;
  try {
    const r = await fetch(`/api/people/${id}`, { method: 'DELETE' });
    if (r.ok) { loadPeople(); toast('Person deleted'); }
    else toast('Delete failed', 'error');
  } catch(_) { toast('Delete failed', 'error'); }
}

function renderPeopleGrid(people) {
  if (!people.length) {
    D.peopleGrid.innerHTML =
      '<div class="empty-msg">No people identified yet.<br>Import photos and run face processing.</div>';
    return;
  }

  D.peopleGrid.innerHTML = people.map(p =>
    `<div class="person-card" data-id="${p.id}" data-name="${escAttr(p.name || '')}">
      <button class="person-delete-btn" data-id="${p.id}" aria-label="Delete person">&times;</button>
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
  D.peopleGrid.querySelectorAll('.person-delete-btn').forEach(btn => {
    btn.addEventListener('click', e => {
      e.stopPropagation();
      deletePerson(+btn.dataset.id);
    });
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
  state.albumFilter  = null;
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

async function onSearchInput() {
  const q = D.searchInput.value.trim();
  state.search = q;
  D.searchClear.hidden = !q;
  clearTimeout(searchTimer);
  if (!q) {
    state.searchIds = null;
    if (state.view === 'gallery') resetAndLoad();
    return;
  }
  searchTimer = setTimeout(async () => {
    if (state.view !== 'gallery') switchView('gallery');
    try {
      const data = await fetch(`/api/search?q=${encodeURIComponent(q)}`).then(r => r.json());
      state.searchIds = new Set(data.photo_ids || []);
    } catch (_) {
      state.searchIds = null;
    }
    resetAndLoad();
  }, 300);
}

// ── Live refresh during operations ────────────────────────
// Polls every 2.5 s while an op is running:
//   • gallery  – appends newly imported/analysed photos without clearing the grid
//   • detail   – refreshes tags for the currently open photo (live AI tagging)
let _liveTimer = null;

function startLiveRefresh() {
  if (_liveTimer) return;
  _liveTimer = setInterval(liveRefreshTick, 2500);
}

function stopLiveRefresh() {
  clearInterval(_liveTimer);
  _liveTimer = null;
}

async function liveRefreshTick() {
  // ── New photos (import) ──────────────────────────────
  if (state.view === 'gallery' && !state.loading) {
    try {
      const params = new URLSearchParams({
        sort: state.sort, filters: JSON.stringify(buildFilters()),
        page: 1, page_size: 1,
      });
      const { total, pages } = await fetch(`/api/photos?${params}`).then(r => r.json());
      // Unlock pagination if server has more pages than we know about
      if (pages > state.totalPages) state.totalPages = pages;
      // Append any pages we haven't fetched yet
      if (total > state.photos.length) loadMorePhotos();
      D.galleryCount.textContent = `${total.toLocaleString()} photos`;
    } catch (_) {}
  }

  // ── Live tag refresh for open detail panel ───────────
  if (state.selectedPhotoId && !D.detailPanel.hidden) {
    try {
      const tags = await fetch(`/api/photos/${state.selectedPhotoId}/tags`).then(r => r.json());
      renderTags(tags, state.selectedPhotoId);
    } catch (_) {}
  }
}

// ── SSE Progress ──────────────────────────────────────────
function startSSE() {
  if (state.sseSource) { state.sseSource.close(); state.sseSource = null; }
  const src = new EventSource('/api/status/stream');
  state.sseSource = src;
  let wasRunning = false;
  // Ensure progress bar is hidden until we know something is running
  hideProgress();

  src.onmessage = e => {
    const d = JSON.parse(e.data);
    if (d.running) {
      if (!wasRunning) {
        wasRunning = true;
        startLiveRefresh();   // begin incremental updates
      }
      state.runningOp = d.operation;
      state.runningProgress = { done: d.done, total: d.total };
      showProgress(d);
      // While face-scanning, update People tab with a live status message
      if (d.operation === 'faces' && state.view === 'people') {
        const pct = d.total > 0 ? Math.round((d.done / d.total) * 100) : 0;
        D.peopleGrid.innerHTML =
          `<div class="loading-msg">
             Scanning faces… ${d.done.toLocaleString()} / ${d.total.toLocaleString()} photos (${pct}%)<br>
             <small style="color:var(--text3)">People will appear here once clustering is complete.</small>
           </div>`;
      }
    } else {
      state.runningOp = null;
      state.runningProgress = { done: 0, total: 0 };
      if (wasRunning) {
        wasRunning = false;
        stopLiveRefresh();    // stop polling
        showProgress(d);      // briefly show completion label
        setTimeout(() => {
          hideProgress();
          const done = ['import_done','analyze_done','faces_done','thumbs_done','quality_tags_done','duplicates_done'];
          if (done.includes(d.operation)) {
            if (state.view === 'gallery') resetAndLoad();  // final full refresh
            if (d.operation === 'faces_done') loadPeople();
            else if (state.view === 'people') loadPeople();
            if (d.operation === 'duplicates_done' && state.view === 'duplicates') loadDuplicates();
            // Refresh tag browser so new tags from analysis appear as chips
            loadTagCounts();
          }
        }, 2200);
      }
    }
  };

  src.onerror = () => {
    src.close();
    state.sseSource = null;
    stopLiveRefresh();
    setTimeout(startSSE, 4000);
  };
}

const OP_LABELS = {
  import:            'Importing photos',
  analyze:           'AI Analysis',
  faces:             'Face Processing',
  thumbs:            'Generating thumbnails',
  import_done:       'Import complete',
  analyze_done:      'Analysis complete',
  faces_done:        'Face processing complete',
  thumbs_done:       'Thumbnails ready',
  quality_tags:      'Quality tag backfill',
  quality_tags_done: 'Quality tags complete',
  duplicates:        'Finding duplicates',
  duplicates_done:   'Duplicate scan complete',
  error:             'Error',
};

function showProgress(d) {
  D.progressWrap.hidden = false;
  document.body.classList.add('progress-active');
  const label = d.op_label || OP_LABELS[d.operation] || d.operation || '';
  D.progressOp.textContent = label;
  // Show current filename being processed
  const fileEl = $('progress-file');
  if (fileEl) fileEl.textContent = d.current_file || '';
  if (d.total > 0) {
    D.progressCounts.textContent = `${d.done.toLocaleString()} / ${d.total.toLocaleString()}`;
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
  $('import-random-chk').checked = false;
  $('import-random-wrap').hidden = true;
}
async function confirmImport() {
  const folder = D.importPath.value.trim();
  if (!folder) return;
  const useRandom = $('import-random-chk').checked;
  const randomN   = useRandom ? (parseInt($('import-random-n').value) || 30) : 0;
  closeImportDialog();
  try {
    const res  = await fetch('/api/import', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ folder, random_limit: randomN }),
    });
    const data = await res.json();
    if (data.error) toast(data.error, 'error');
    else toast(randomN ? `Importing ${randomN} random photos…` : 'Import started…');
  } catch (_) { toast('Import request failed.', 'error'); }
}

// ── Admin resets ──────────────────────────────────────────
async function resetAnalysis() {
  if (!confirm('This will delete all AI tags (Objects, Scenes, People) and face data, then let you re-run analysis. EXIF tags (Date, Camera, Location) are kept.\n\nContinue?')) return;
  try {
    const data = await fetch('/api/admin/reset-analysis', { method: 'POST' }).then(r => r.json());
    if (data.error) { toast(data.error, 'error'); return; }
    toast(`Reset done — ${data.deleted_tags} tags removed, ${data.deleted_persons} people cleared`);
    // Refresh the current view
    if (state.view === 'gallery') resetAndLoad();
    else if (state.view === 'people') loadPeople();
  } catch (_) { toast('Reset request failed.', 'error'); }
}
async function resetAll() {
  if (!confirm('⚠️  HARD RESET\n\nThis will delete ALL photos, tags, and people from the database. You will need to re-import everything.\n\nAre you absolutely sure?')) return;
  try {
    const data = await fetch('/api/admin/reset-all', { method: 'POST' }).then(r => r.json());
    if (data.error) { toast(data.error, 'error'); return; }
    toast('Hard reset complete — database cleared');
    state.photos = [];
    state.page = 1;
    state.totalPages = 1;
    resetAndLoad();
  } catch (_) { toast('Reset request failed.', 'error'); }
}

// ── Analyse ───────────────────────────────────────────────
async function startAnalyze() {
  try {
    const data = await fetch('/api/analyze', { method: 'POST' }).then(r => r.json());
    if (data.error) toast(data.error, 'error');
    else toast('AI analysis started…');
  } catch (_) { toast('Request failed.', 'error'); }
}

// ── Per-photo analysis ────────────────────────────────────
async function analyzeCurrentPhoto() {
  const id = state.selectedPhotoId;
  if (!id) return;
  const btn = D.analyzePhotoBtn;
  btn.disabled = true;
  btn.title = 'Analysing…';
  toast('Analysing photo…');
  try {
    const tags = await fetch(`/api/photos/${id}/analyze`, { method: 'POST' }).then(r => {
      if (!r.ok) throw new Error(r.status);
      return r.json();
    });
    renderTags(tags, id);
    // Refresh tag browser counts after single-photo analysis
    loadTagCounts();
    toast('Analysis complete');
  } catch (_) {
    toast('Analysis failed.', 'error');
  } finally {
    btn.disabled = false;
    btn.title = 'Re-analyse this photo';
  }
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

// ── Albums ──────────────────────────────────────────────────────────────────

async function loadAlbums() {
  D.albumsGrid.innerHTML = '<div class="loading-msg">Loading albums\u2026</div>';
  try {
    const albums = await fetch('/api/albums').then(r => r.json());
    renderAlbumsGrid(albums);
  } catch (_) {
    D.albumsGrid.innerHTML = '<div class="empty-msg">Could not load albums.</div>';
  }
}

function renderAlbumsGrid(albums) {
  if (!albums.length) {
    D.albumsGrid.innerHTML =
      '<div class="empty-msg">No albums yet.<br>Click "Auto-group Events" to create event albums automatically.</div>';
    return;
  }
  D.albumsGrid.innerHTML = albums.map(a =>
    `<div class="album-card" data-id="${a.id}" data-name="${escAttr(a.name)}">
      <div class="album-cover">
        ${a.cover_photo_id
          ? `<img src="/api/photos/${a.cover_photo_id}/thumb" alt="" loading="lazy">`
          : '<div class="album-cover-placeholder"></div>'}
      </div>
      <div class="album-name">${escHtml(a.name)}</div>
      <div class="album-count">${a.photo_count} photo${a.photo_count === 1 ? '' : 's'}</div>
      <button class="album-delete-btn" data-id="${a.id}" aria-label="Delete album">&times;</button>
    </div>`
  ).join('');

  D.albumsGrid.querySelectorAll('.album-card').forEach(el => {
    el.addEventListener('click', e => {
      if (e.target.classList.contains('album-delete-btn')) return;
      openAlbumGallery({ id: +el.dataset.id, name: el.dataset.name });
    });
  });
  D.albumsGrid.querySelectorAll('.album-delete-btn').forEach(btn => {
    btn.addEventListener('click', e => {
      e.stopPropagation();
      deleteAlbum(+btn.dataset.id);
    });
  });
}

async function openAlbumGallery(album) {
  state.albumFilter = album;
  state.personFilter = null;
  state.tagFilters = {};
  state.searchIds = null;

  if (D.personHeader) {
    D.personHeader.hidden = false;
    if (D.phName) D.phName.textContent = escHtml(album.name);
    if (D.phCount) D.phCount.textContent = '';
    if (D.phChips) D.phChips.innerHTML = '';
  }

  switchView('gallery');

  state.photos = [];
  showSkeletons();
  D.galleryCount.textContent = '';

  try {
    const photos = await fetch(`/api/albums/${album.id}/photos`).then(r => r.json());
    appendPhotos(photos, true);
    state.photos = photos;
    D.galleryCount.textContent = `${photos.length} photo${photos.length === 1 ? '' : 's'}`;
  } catch (_) {
    D.photoGrid.innerHTML = '<div class="empty-msg">Could not load album photos.</div>';
  }
}

async function deleteAlbum(id) {
  if (!confirm('Delete this album? Photos are not deleted.')) return;
  try {
    const r = await fetch(`/api/albums/${id}`, { method: 'DELETE' });
    if (r.ok) { loadAlbums(); toast('Album deleted'); }
    else toast('Delete failed', 'error');
  } catch (_) { toast('Delete failed', 'error'); }
}

async function generateEventAlbums() {
  D.generateEventsBtn.disabled = true;
  D.generateEventsBtn.textContent = 'Generating\u2026';
  try {
    const data = await fetch('/api/albums/generate-events', { method: 'POST' }).then(r => r.json());
    if (data.error) toast(data.error, 'error');
    else {
      toast(`Created ${data.albums_created} event album${data.albums_created === 1 ? '' : 's'}`);
      loadAlbums();
    }
  } catch (_) { toast('Request failed.', 'error'); }
  finally {
    D.generateEventsBtn.disabled = false;
    D.generateEventsBtn.textContent = 'Auto-group Events';
  }
}

function openAlbumCreateDialog() {
  D.albumNameInput.value = '';
  D.albumDialog.hidden = false;
  setTimeout(() => D.albumNameInput.focus(), 50);
}
function closeAlbumDialog() { D.albumDialog.hidden = true; }
async function confirmAlbumCreate() {
  const name = D.albumNameInput.value.trim();
  if (!name) return;
  closeAlbumDialog();
  try {
    await fetch('/api/albums', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    });
    toast(`Album "${name}" created`);
    loadAlbums();
  } catch (_) { toast('Create failed.', 'error'); }
}

function backToAlbums() {
  state.albumFilter = null;
  if (D.personHeader) D.personHeader.hidden = true;
  switchView('albums');
}

// ── Cleanup people ───────────────────────────────────────────────────────────

let _cleanupCandidates = [];

async function openCleanupDialog() {
  const threshold = parseInt(D.cleanupThreshold.value) || 2;
  await _loadCleanupCandidates(threshold);
  D.cleanupDialog.hidden = false;
}

async function _loadCleanupCandidates(threshold) {
  D.cleanupList.innerHTML = '<div class="loading-msg">Loading\u2026</div>';
  try {
    const people = await fetch('/api/people').then(r => r.json());
    _cleanupCandidates = people.filter(p => (p.photo_count || 0) < threshold);
    if (!_cleanupCandidates.length) {
      D.cleanupList.innerHTML =
        `<div class="empty-msg">No people with fewer than ${threshold} photo${threshold === 1 ? '' : 's'}.</div>`;
      return;
    }
    D.cleanupList.innerHTML = _cleanupCandidates.map(p =>
      `<label class="cleanup-row">
        <input type="checkbox" class="cleanup-chk" data-id="${p.id}" checked>
        <span class="cleanup-avatar">
          ${p.has_thumb
            ? `<img src="/api/people/${p.id}/thumb" width="32" height="32" style="border-radius:50%;object-fit:cover">`
            : `<span class="cleanup-initial">${avatarInitial(p.name)}</span>`}
        </span>
        <span class="cleanup-name">${escHtml(p.name)}</span>
        <span class="cleanup-cnt">${p.photo_count} photo${p.photo_count === 1 ? '' : 's'}</span>
      </label>`
    ).join('');
  } catch (_) {
    D.cleanupList.innerHTML = '<div class="empty-msg">Could not load people.</div>';
  }
}

function closeCleanupDialog() { D.cleanupDialog.hidden = true; }

async function confirmCleanup() {
  const checked = [...D.cleanupList.querySelectorAll('.cleanup-chk:checked')]
    .map(cb => +cb.dataset.id);
  if (!checked.length) { closeCleanupDialog(); return; }
  if (!confirm(`Delete ${checked.length} person${checked.length === 1 ? '' : 's'}? This cannot be undone.`)) return;
  closeCleanupDialog();
  try {
    const data = await fetch('/api/people/bulk-delete', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ person_ids: checked }),
    }).then(r => r.json());
    toast(`Deleted ${data.deleted} person${data.deleted === 1 ? '' : 's'}`);
    loadPeople();
    loadTagCounts();
  } catch (_) { toast('Bulk delete failed.', 'error'); }
}

// ── Quality tags ─────────────────────────────────────────────────────────────

async function runQualityTagsBackfill() {
  try {
    const data = await fetch('/api/admin/run-quality-tags', { method: 'POST' }).then(r => r.json());
    if (data.error) toast(data.error, 'error');
    else toast('Quality tag backfill started\u2026');
  } catch (_) { toast('Request failed.', 'error'); }
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

// ── Inline person rename ──────────────────────────────────
function startInlineRename() {
  const el = D.phName;
  const person = state.personFilter;
  if (!person || el.contentEditable === 'true') return;

  const originalName = person.name;
  el.contentEditable = 'true';
  el.focus();
  const range = document.createRange();
  range.selectNodeContents(el);
  range.collapse(false);
  const sel = window.getSelection();
  sel.removeAllRanges();
  sel.addRange(range);
  el.classList.add('ph-editing');
  D.phRenameBtn.textContent = 'Save';

  async function saveRename() {
    const newName = el.textContent.trim();
    el.contentEditable = 'false';
    el.classList.remove('ph-editing');
    D.phRenameBtn.textContent = 'Rename';
    cleanup();
    if (!newName || newName === originalName) { el.textContent = originalName; return; }
    try {
      const res = await fetch(`/api/people/${person.id}/rename`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: newName }),
      });
      const data = await res.json();
      if (data.ok) {
        state.personFilter.name = data.name;
        el.textContent = data.name;
        toast(`Renamed to "${data.name}"`);
        resetAndLoad();
      } else { el.textContent = originalName; toast('Rename failed', 'error'); }
    } catch (_) { el.textContent = originalName; toast('Rename failed', 'error'); }
  }

  function cancelRename() {
    el.textContent = originalName;
    el.contentEditable = 'false';
    el.classList.remove('ph-editing');
    D.phRenameBtn.textContent = 'Rename';
    cleanup();
  }

  function onKey(e) {
    if (e.key === 'Enter') { e.preventDefault(); saveRename(); }
    if (e.key === 'Escape') cancelRename();
  }

  function cleanup() {
    el.removeEventListener('keydown', onKey);
  }

  el.addEventListener('keydown', onKey);
  D.phRenameBtn.addEventListener('click', saveRename, { once: true });
}

// ── Timeline ──────────────────────────────────────────────
async function loadTimeline() {
  D.timelineContainer.innerHTML = '<div class="loading-msg">Loading timeline…</div>';
  try {
    const groups = await fetch('/api/timeline').then(r => r.json());
    renderTimeline(groups);
  } catch (_) {
    D.timelineContainer.innerHTML = '<div class="empty-msg">Could not load timeline.</div>';
  }
}

function renderTimeline(groups) {
  if (!groups.length) {
    D.timelineContainer.innerHTML =
      '<div class="empty-msg">No photos with date information found.</div>';
    return;
  }
  const allIds = groups.flatMap(g => g.photo_ids);
  D.timelineContainer.innerHTML = '';

  groups.forEach(group => {
    const hdr = document.createElement('div');
    hdr.className = 'timeline-month-hdr';
    hdr.textContent = `${group.label}  ·  ${group.count} photo${group.count === 1 ? '' : 's'}`;
    D.timelineContainer.appendChild(hdr);

    const row = document.createElement('div');
    row.className = 'timeline-row';

    group.photo_ids.forEach(photoId => {
      const tile = document.createElement('div');
      tile.className = 'photo-tile timeline-tile';
      tile.dataset.id = photoId;

      const img = document.createElement('img');
      img.alt = '';
      img.loading = 'lazy';

      const obs = new IntersectionObserver(entries => {
        if (entries[0].isIntersecting) {
          img.src = `/api/photos/${photoId}/thumb`;
          obs.disconnect();
        }
      }, { rootMargin: '400px' });
      obs.observe(tile);

      tile.appendChild(img);
      tile.addEventListener('click', () => {
        state.photos = allIds.map(id => ({ id }));
        openDetail(photoId);
      });
      row.appendChild(tile);
    });

    D.timelineContainer.appendChild(row);
  });
}

// ── Duplicates ────────────────────────────────────────────
async function startFindDuplicates() {
  D.findDuplicatesBtn.disabled = true;
  D.findDuplicatesBtn.textContent = 'Scanning…';
  try {
    const data = await fetch('/api/admin/find-duplicates', { method: 'POST' }).then(r => r.json());
    if (data.error) toast(data.error, 'error');
    else toast('Duplicate scan started — check Duplicates view when done.');
  } catch (_) { toast('Request failed.', 'error'); }
  finally {
    D.findDuplicatesBtn.disabled = false;
    D.findDuplicatesBtn.textContent = 'Find Duplicates';
  }
}

async function loadDuplicates() {
  D.duplicatesContainer.innerHTML = '<div class="loading-msg">Loading…</div>';
  D.dupGroupCount.textContent = '';
  try {
    const groups = await fetch('/api/duplicates').then(r => r.json());
    renderDuplicates(groups);
  } catch (_) {
    D.duplicatesContainer.innerHTML = '<div class="empty-msg">Could not load duplicates.</div>';
  }
}

function renderDuplicates(groups) {
  if (!groups.length) {
    D.dupGroupCount.textContent = '';
    D.duplicatesContainer.innerHTML =
      '<div class="empty-msg">No duplicate groups found.<br>' +
      '<small>Click "Find Duplicates" in the sidebar to scan your library.</small></div>';
    return;
  }
  D.dupGroupCount.textContent = `${groups.length} group${groups.length === 1 ? '' : 's'}`;
  D.duplicatesContainer.innerHTML = '';

  groups.forEach(group => {
    const card = document.createElement('div');
    card.className = 'dup-group';

    const photosHtml = group.photos.map(p =>
      `<div class="dup-photo" data-photo-id="${p.id}">
        <img src="${p.thumb}" alt="${escAttr(p.filename)}" loading="lazy">
        <div class="dup-photo-name">${escHtml(p.filename)}</div>
        <div class="dup-photo-meta">
          ${p.date_taken ? new Date(p.date_taken).toLocaleDateString('en-GB', {dateStyle:'medium'}) : 'No date'}
          ${p.file_size ? ' · ' + Math.round(p.file_size / 1024) + ' KB' : ''}
        </div>
        <button class="btn-accent dup-keep-btn" data-id="${p.id}">Keep this</button>
      </div>`
    ).join('');

    card.innerHTML =
      `<div class="dup-photos">${photosHtml}</div>
       <div class="dup-actions">
         <button class="btn-ghost dup-dismiss-btn">Dismiss (keep all)</button>
       </div>`;

    card.querySelectorAll('.dup-keep-btn').forEach(btn => {
      btn.addEventListener('click', async () => {
        const keepId = +btn.dataset.id;
        const deleteIds = group.photos.map(p => p.id).filter(id => id !== keepId);
        if (!confirm(`Permanently delete ${deleteIds.length} photo${deleteIds.length === 1 ? '' : 's'}? This cannot be undone.`)) return;
        try {
          const res = await fetch('/api/photos/delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ photo_ids: deleteIds }),
          });
          const data = await res.json();
          if (data.ok) {
            toast(`Deleted ${data.deleted} photo${data.deleted === 1 ? '' : 's'}`);
            card.style.transition = 'opacity .3s';
            card.style.opacity = '0';
            setTimeout(() => card.remove(), 320);
          } else toast('Delete failed', 'error');
        } catch (_) { toast('Delete failed', 'error'); }
      });
    });

    card.querySelector('.dup-dismiss-btn').addEventListener('click', () => {
      card.style.transition = 'opacity .3s';
      card.style.opacity = '0';
      setTimeout(() => card.remove(), 320);
    });

    D.duplicatesContainer.appendChild(card);
  });
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
    state.searchIds = null;
    state.albumFilter = null;
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

  // Analyse (full library) + per-photo analyse
  D.analyzeBtn.addEventListener('click', startAnalyze);
  D.analyzePhotoBtn.addEventListener('click', analyzeCurrentPhoto);

  // Admin reset buttons
  D.resetAnalysisBtn.addEventListener('click', resetAnalysis);
  D.resetAllBtn.addEventListener('click', resetAll);

  // Random import toggle
  $('import-random-chk').addEventListener('change', function() {
    $('import-random-wrap').hidden = !this.checked;
  });

  // Detail panel
  D.closeDetail.addEventListener('click', closeDetail);
  D.detailPrev.addEventListener('click', () => navPhoto(-1));
  D.detailNext.addEventListener('click', () => navPhoto(1));
  D.detailFav.addEventListener('click', () => toggleFavorite(state.selectedPhotoId));
  D.bboxToggle.addEventListener('click', () => {
    state.showBboxes = !state.showBboxes;
    D.bboxToggle.textContent = state.showBboxes ? 'Hide boxes' : 'Show boxes';
    repaintCanvas();
  });
  D.addTagBtn.addEventListener('click', addTag);
  D.newTagInput.addEventListener('keydown', e => { if (e.key === 'Enter') addTag(); });

  // Back button — goes to albums if albumFilter set, else people
  D.backToPeople.addEventListener('click', () => {
    if (state.albumFilter) backToAlbums();
    else backToPeople();
  });

  // Albums
  D.generateEventsBtn.addEventListener('click', generateEventAlbums);
  D.createAlbumBtn.addEventListener('click', openAlbumCreateDialog);
  D.albumOverlay.addEventListener('click', closeAlbumDialog);
  D.albumCancel.addEventListener('click', closeAlbumDialog);
  D.albumConfirm.addEventListener('click', confirmAlbumCreate);
  D.albumNameInput.addEventListener('keydown', e => { if (e.key === 'Enter') confirmAlbumCreate(); });

  // Cleanup people
  D.cleanupPeopleBtn.addEventListener('click', openCleanupDialog);
  D.cleanupOverlay.addEventListener('click', closeCleanupDialog);
  D.cleanupCancel.addEventListener('click', closeCleanupDialog);
  D.cleanupConfirm.addEventListener('click', confirmCleanup);
  D.cleanupThreshold.addEventListener('change', () => {
    _loadCleanupCandidates(parseInt(D.cleanupThreshold.value) || 2);
  });

  // Quality tags
  D.runQualityTagsBtn.addEventListener('click', runQualityTagsBackfill);

  // Find duplicates
  if (D.findDuplicatesBtn) D.findDuplicatesBtn.addEventListener('click', startFindDuplicates);

  // Person inline rename
  if (D.phRenameBtn) D.phRenameBtn.addEventListener('click', startInlineRename);

  // People tabs
  document.querySelectorAll('.people-tab').forEach(tab => {
    tab.addEventListener('click', () => {
      document.querySelectorAll('.people-tab').forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      if (tab.dataset.tab === 'all') {
        $('people-grid').hidden = false;
        $('similar-grid').hidden = true;
      } else {
        $('people-grid').hidden = true;
        $('similar-grid').hidden = false;
        loadSimilarFaces();
      }
    });
  });

  // Same/diff bar
  D.sdSame.addEventListener('click', onSamePerson);
  D.sdDiff.addEventListener('click', dismissPair);
  D.sdDismiss.addEventListener('click', () => {
    state.sdPairs = [];
    state.sdIdx = 0;
    D.sameDiffBar.hidden = true;
  });

  // Rename
  D.renameOverlay.addEventListener('click', closeRenameDialog);
  D.renameCancel.addEventListener('click', closeRenameDialog);
  D.renameConfirm.addEventListener('click', confirmRename);
  D.renameInput.addEventListener('keydown', e => { if (e.key === 'Enter') confirmRename(); });

  // Keyboard shortcuts
  document.addEventListener('keydown', e => {
    // Don't fire when typing in an input
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;

    if (e.key === 'Escape') {
      if (!D.lightbox.hidden)      { closeLightbox();       return; }
      if (!D.albumDialog.hidden)   { closeAlbumDialog();    return; }
      if (!D.cleanupDialog.hidden) { closeCleanupDialog();  return; }
      if (!D.importDialog.hidden)  { closeImportDialog();   return; }
      if (!D.renameDialog.hidden)  { closeRenameDialog();   return; }
      if (!D.detailPanel.hidden)   { closeDetail();          return; }
    }
    if (!D.lightbox.hidden) {
      if (e.key === 'ArrowLeft')  { navPhoto(-1); D.lightboxImg.src = `/api/photos/${state.selectedPhotoId}/image`; return; }
      if (e.key === 'ArrowRight') { navPhoto(1);  D.lightboxImg.src = `/api/photos/${state.selectedPhotoId}/image`; return; }
    }
    if (!D.detailPanel.hidden) {
      if (e.key === 'ArrowLeft')  { navPhoto(-1); return; }
      if (e.key === 'ArrowRight') { navPhoto(1);  return; }
      if (e.key === 'f' || e.key === 'F') { toggleFavorite(state.selectedPhotoId); return; }
      if (e.key === 'Enter')      { openLightbox(); return; }
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

  // Lightbox
  D.lightboxClose.addEventListener('click', closeLightbox);
  D.lightboxOverlay = $('lightbox-overlay');
  D.lightboxOverlay.addEventListener('click', closeLightbox);
  D.lightboxPrev.addEventListener('click', e => {
    e.stopPropagation();
    navPhoto(-1);
    if (state.selectedPhotoId) D.lightboxImg.src = `/api/photos/${state.selectedPhotoId}/image`;
  });
  D.lightboxNext.addEventListener('click', e => {
    e.stopPropagation();
    navPhoto(1);
    if (state.selectedPhotoId) D.lightboxImg.src = `/api/photos/${state.selectedPhotoId}/image`;
  });
  initLightboxZoom();

  // Swipe gestures on detail panel
  initSwipe();

  // Filter chips bar
  D.filterChipsBar.querySelectorAll('.filter-chip').forEach(btn => {
    btn.addEventListener('click', () => {
      D.filterChipsBar.querySelectorAll('.filter-chip').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      state.favoritesOnly = btn.dataset.filter === 'favorites';
      resetAndLoad();
    });
  });

  // Infinite scroll sentinel
  initScrollObserver();

  // SSE for progress
  startSSE();

  // Tag browser
  loadTagCounts();
  $('tag-clear-btn').addEventListener('click', clearAllTagFilters);

  // Listen for postMessage from the map iframe — clicking a photo thumbnail
  // in a map popup sends { photoId } so we can open the detail panel.
  window.addEventListener('message', e => {
    if (e.data && e.data.photoId) {
      const id = e.data.photoId;
      // If we have the photo in memory open it straight away, otherwise
      // switch to gallery, let photos load, then open.
      const found = state.photos.find(p => p.id === id);
      if (found) {
        openDetail(found);
      } else {
        switchView('gallery');
        // Wait briefly for photos to render then open the detail
        setTimeout(async () => {
          const res = await fetch(`/api/photos?page=1&page_size=1&filters=${encodeURIComponent(JSON.stringify({}))}`).then(r=>r.json());
          // Fetch the specific photo metadata
          const single = await fetch(`/api/photos?page=1&page_size=9999`).then(r=>r.json());
          const p = (single.photos || []).find(x => x.id === id);
          if (p) openDetail(p);
        }, 500);
      }
    }
  });

  // Initial view
  switchView('gallery');
}

document.addEventListener('DOMContentLoaded', init);
