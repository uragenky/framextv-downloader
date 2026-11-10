// StreamDown Web Application Logic v2.0.0 (Batch Multi-Episode Checkboxes + Subtitles + Local Downloads)

let currentMediaType = 'movie';
let selectedItem = null;
let itemDetails = null;
let hlsInstance = null;

let selectedEpisodes = new Set([1]);
let currentSeasonEpisodeCount = 24;

let githubConfig = {
  configured: false,
  github_repo: ''
};

let gdriveConfig = {
  authenticated: false,
  email: '',
  gdrive_folder: 'frameXTV_Downloads'
};

let cloudQuotaData = null;

// Initialization
document.addEventListener('DOMContentLoaded', () => {
  if (window.lucide && typeof window.lucide.createIcons === 'function') {
    lucide.createIcons();
  }

  // Initialize view from URL hash (#downloads vs #browse)
  const initialHash = (window.location.hash || '').replace('#', '');
  if (initialHash === 'downloads') {
    switchMainView('downloads', false);
  } else {
    switchMainView('browse', false);
  }

  // Bind click events directly for navigation tabs (desktop & mobile)
  const bindTab = (id, targetView) => {
    const el = document.getElementById(id);
    if (el) {
      el.addEventListener('click', (e) => {
        e.preventDefault();
        switchMainView(targetView);
      });
    }
  };
  bindTab('navTabBrowse', 'browse');
  bindTab('navTabDownloads', 'downloads');
  bindTab('navTabBrowseMobile', 'browse');
  bindTab('navTabDownloadsMobile', 'downloads');

  // Handle browser back/forward or hash changes
  window.addEventListener('hashchange', () => {
    const hash = (window.location.hash || '').replace('#', '');
    if (hash === 'downloads' || hash === 'browse') {
      switchMainView(hash, false);
    }
  });

  fetchInitialCatalog();
  fetchGithubStatus();
  fetchGdriveStatus();
  fetchCloudQuota();
  fetchLocalDownloadsCount();
  startQueuePolling();
});

function showToast(message, isError = false) {
  const toast = document.getElementById('toast');
  const toastMsg = document.getElementById('toastMessage');
  toastMsg.textContent = message;
  
  if (isError) {
    toast.classList.add('border-red-500/50', 'text-red-200');
  } else {
    toast.classList.remove('border-red-500/50', 'text-red-200');
  }

  toast.classList.remove('translate-y-20', 'opacity-0');
  setTimeout(() => {
    toast.classList.add('translate-y-20', 'opacity-0');
  }, 3500);
}

// Media Type Selector
function setMediaType(type) {
  currentMediaType = type;
  const tabs = {
    movie: document.getElementById('btnTabMovie'),
    tv: document.getElementById('btnTabTv'),
    anime: document.getElementById('btnTabAnime')
  };

  Object.keys(tabs).forEach(k => {
    if (k === type) {
      tabs[k].className = 'flex-1 py-1 px-3 text-xs font-semibold rounded-lg transition bg-white text-black shadow';
    } else {
      tabs[k].className = 'flex-1 py-1 px-3 text-xs font-semibold rounded-lg transition text-zinc-400 hover:text-white';
    }
  });

  const query = document.getElementById('searchInput').value.trim();
  if (query) {
    triggerSearch();
  } else {
    fetchInitialCatalog();
  }
}

function resetSearch() {
  document.getElementById('searchInput').value = '';
  fetchInitialCatalog();
}

function quickSearch(title, type) {
  document.getElementById('searchInput').value = title;
  setMediaType(type);
  triggerSearch();
}

// Search & Catalog
async function fetchInitialCatalog() {
  const defaultQueries = {
    movie: 'Inception',
    tv: 'Pokemon',
    anime: 'Attack on Titan'
  };
  searchMedia(defaultQueries[currentMediaType] || 'Pokemon', true);
}

function triggerSearch() {
  const query = document.getElementById('searchInput').value.trim();
  if (!query) {
    showToast('Ketik judul film/series terlebih dahulu', true);
    return;
  }
  searchMedia(query, false);
}

async function searchMedia(query, isDefault = false) {
  const loading = document.getElementById('loadingIndicator');
  const grid = document.getElementById('resultsGrid');
  const empty = document.getElementById('emptyState');
  const heading = document.getElementById('resultsHeading');
  const count = document.getElementById('resultsCount');

  loading.classList.remove('hidden');
  grid.innerHTML = '';
  empty.classList.add('hidden');

  heading.innerHTML = isDefault 
    ? `<span>Katalog Populer (${currentMediaType.toUpperCase()})</span>`
    : `<span>Hasil Pencarian: "${query}"</span>`;

  try {
    const res = await fetch(`/api/search?q=${encodeURIComponent(query)}&type=${currentMediaType}`);
    const data = await res.json();
    loading.classList.add('hidden');

    if (!data.success || !data.results || data.results.length === 0) {
      empty.classList.remove('hidden');
      count.textContent = '0 judul';
      return;
    }

    count.textContent = `${data.results.length} judul ditemukan`;
    renderResults(data.results);
  } catch (err) {
    loading.classList.add('hidden');
    empty.classList.remove('hidden');
    showToast(`Error: ${err.message}`, true);
  }
}

function renderResults(items) {
  const grid = document.getElementById('resultsGrid');
  grid.innerHTML = '';

  items.forEach(item => {
    const id = item.id;
    const title = item.title || item.name || 'Tanpa Judul';
    const year = item.year || (item.releaseDate ? item.releaseDate.substring(0, 4) : '-');
    const rating = item.rating ? Number(item.rating).toFixed(1) : (item.voteAverage ? Number(item.voteAverage).toFixed(1) : null);
    const poster = item.poster || item.poster_path || 'https://via.placeholder.com/300x450/18181b/71717a?text=No+Poster';

    const card = document.createElement('div');
    card.className = 'group relative rounded-xl overflow-hidden bg-zinc-900 border border-zinc-800/80 hover:border-emerald-500/50 transition-all duration-300 hover:shadow-xl hover:shadow-emerald-500/10 cursor-pointer flex flex-col';
    
    card.onclick = () => openDetailModal(item);

    card.innerHTML = `
      <div class="aspect-[2/3] w-full overflow-hidden bg-zinc-950 relative">
        <img src="${poster}" alt="${title}" loading="lazy" class="w-full h-full object-cover transition-transform duration-500 group-hover:scale-105" />
        <div class="absolute inset-0 bg-gradient-to-t from-black/80 via-transparent to-black/30 opacity-60 group-hover:opacity-80 transition-opacity"></div>
        
        <div class="absolute top-2 left-2 flex gap-1">
          <span class="text-[9px] font-mono uppercase font-bold px-1.5 py-0.5 rounded bg-black/60 backdrop-blur-md text-zinc-300 border border-white/10">
            ${currentMediaType}
          </span>
        </div>

        ${rating ? `
          <div class="absolute top-2 right-2 flex items-center space-x-1 px-1.5 py-0.5 rounded bg-black/70 backdrop-blur-md text-[10px] font-bold text-amber-400 border border-amber-500/20">
            <span>★</span>
            <span>${rating}</span>
          </div>
        ` : ''}

        <div class="absolute inset-0 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity bg-black/40 backdrop-blur-[2px]">
          <span class="px-3.5 py-1.5 rounded-lg bg-emerald-600 text-white text-xs font-bold shadow-lg">Pilih Media</span>
        </div>
      </div>

      <div class="p-3 flex-1 flex flex-col justify-between">
        <h3 class="text-xs font-bold text-white line-clamp-1 group-hover:text-emerald-400 transition">${title}</h3>
        <span class="text-[10px] font-mono text-zinc-500 mt-1">${year}</span>
      </div>
    `;

    grid.appendChild(card);
  });

  lucide.createIcons();
}

// ==========================================
// Detail Modal & Checkbox Controls
// ==========================================

async function openDetailModal(item) {
  selectedItem = item;
  closePlayerPreview();

  const modal = document.getElementById('detailModal');
  const title = item.title || item.name || 'Tanpa Judul';
  const year = item.year || (item.releaseDate ? item.releaseDate.substring(0, 4) : '');
  const rating = item.rating || item.voteAverage || '-';
  const poster = item.poster || item.poster_path || 'https://via.placeholder.com/300x450/18181b/71717a?text=No+Poster';
  const backdrop = item.backdrop || item.backdrop_path || poster;

  document.getElementById('modalTitle').textContent = title;
  document.getElementById('modalYear').textContent = year;
  document.getElementById('modalRating').innerHTML = `<span>★</span> <span>${rating}</span>`;
  document.getElementById('modalTypeBadge').textContent = currentMediaType.toUpperCase();
  document.getElementById('modalPoster').src = poster;
  document.getElementById('modalBackdrop').style.backgroundImage = `url('${backdrop}')`;
  document.getElementById('modalOverview').textContent = item.overview || 'Sedang mengambil informasi sinopsis dan episode...';
  document.getElementById('modalTagline').textContent = '';

  selectedEpisodes = new Set([1]);

  // Reset & Handle TV / Anime controls
  const tvSection = document.getElementById('tvControlsSection');
  if (currentMediaType === 'tv' || currentMediaType === 'anime') {
    tvSection.classList.remove('hidden');
    loadSeasonsAndEpisodes(item.id);
  } else {
    tvSection.classList.add('hidden');
    updateBatchUI();
  }

  // Fetch full details
  fetchMediaDetails(item.id);
  updateModalQuotaBadge();

  const modalEmail = document.getElementById('modalTargetEmail');
  if (modalEmail) {
    modalEmail.textContent = gdriveConfig.email || gdriveConfig.google_account || 'Belum Terhubung';
  }

  // Restore Subtitle Mode Preference
  try {
    const savedSubMode = localStorage.getItem('streamdown_sub_mode') || 'translate_id';
    const subSel = document.getElementById('selectSubtitleMode');
    if (subSel) {
      subSel.value = savedSubMode;
    }
  } catch (e) {}
  onSubtitleModeChange();
  updateCloudUIState();

  modal.classList.remove('hidden');
  lucide.createIcons();
}

function updateCloudUIState() {
  const btn = document.getElementById('btnExecuteCloud');
  const icon = document.getElementById('btnExecuteCloudIcon');
  const text = document.getElementById('btnExecuteCloudText');
  const badge = document.getElementById('btnExecuteCloudBadge');
  const notice = document.getElementById('cloudSetupNotice');
  const quotaPill = document.getElementById('navQuotaPill');

  const isConfigured = Boolean(githubConfig && githubConfig.configured);

  if (isConfigured) {
    if (btn) {
      btn.className = 'flex-1 flex items-center justify-center space-x-2 py-3 px-4 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white font-extrabold text-xs shadow-lg shadow-emerald-600/30 transition cursor-pointer active:scale-95';
    }
    if (icon) icon.setAttribute('data-lucide', 'cloud-lightning');
    if (text) text.textContent = 'Kirim ke Cloud';
    if (badge) badge.classList.add('hidden');
    if (notice) notice.classList.add('hidden');
  } else {
    if (btn) {
      btn.className = 'flex-1 flex items-center justify-center space-x-2 py-3 px-4 rounded-xl bg-zinc-900 hover:bg-zinc-800 text-zinc-400 hover:text-white border border-zinc-800 text-xs font-bold transition cursor-pointer';
    }
    if (icon) icon.setAttribute('data-lucide', 'cloud-off');
    if (text) text.textContent = 'Kirim ke Cloud';
    if (badge) {
      badge.classList.remove('hidden');
      badge.textContent = 'Setup';
    }
    if (notice) notice.classList.remove('hidden');

    if (quotaPill && (!cloudQuotaData || !cloudQuotaData.configured)) {
      quotaPill.textContent = 'Mode Lokal';
    }
  }

  if (window.lucide && typeof window.lucide.createIcons === 'function') {
    window.lucide.createIcons();
  }
}

function onSubtitleModeChange() {
  const sel = document.getElementById('selectSubtitleMode');
  const desc = document.getElementById('subSelectedDescription');
  if (!sel) return;

  const val = sel.value;
  try {
    localStorage.setItem('streamdown_sub_mode', val);
  } catch (e) {}

  const descriptions = {
    translate_id: '✨ Otomatis terjemahkan subtitle ke Indonesia',
    original: '📄 Gunakan subtitle asli tanpa proses terjemahan',
    translate_en: '✨ Terjemahkan subtitle ke Bahasa Inggris',
    translate_ja: '✨ Terjemahkan subtitle ke Bahasa Jepang',
    translate_es: '✨ Terjemahkan subtitle ke Bahasa Spanyol',
    none: '⚡ Unduh cepat video saja tanpa file subtitle'
  };

  if (desc) {
    desc.textContent = descriptions[val] || '✨ Pengaturan subtitle siap';
  }
}

function closeDetailModal() {
  document.getElementById('detailModal').classList.add('hidden');
  closePlayerPreview();
}

async function fetchMediaDetails(id) {
  try {
    const res = await fetch(`/api/details?id=${id}&type=${currentMediaType}`);
    const json = await res.json();
    if (json.success && json.data) {
      itemDetails = json.data;
      if (itemDetails.overview) {
        document.getElementById('modalOverview').textContent = itemDetails.overview;
      }
      if (itemDetails.tagline) {
        document.getElementById('modalTagline').textContent = `"${itemDetails.tagline}"`;
      }
    }
  } catch (err) {
    console.warn('Gagal memuat detail:', err);
  }
}

async function loadSeasonsAndEpisodes(id) {
  const selectSeason = document.getElementById('selectSeason');
  selectSeason.innerHTML = '<option value="1">Season 1</option>';
  selectedEpisodes = new Set([1]);

  try {
    const res = await fetch(`/api/details?id=${id}&type=${currentMediaType}`);
    const json = await res.json();
    if (json.success && json.data) {
      const details = json.data;
      itemDetails = details;
      const seasons = details.seasons || [];

      if (seasons.length > 0) {
        selectSeason.innerHTML = '';
        seasons.forEach((s, idx) => {
          const sNum = s.number !== undefined ? s.number : (s.season_number !== undefined ? s.season_number : idx + 1);
          if (sNum > 0 || seasons.length === 1) {
            const opt = document.createElement('option');
            opt.value = sNum;
            opt.textContent = `Season ${sNum} ${s.name ? `— ${s.name}` : ''}`;
            selectSeason.appendChild(opt);
          }
        });
      }
      onSeasonChange();
    }
  } catch (e) {
    onSeasonChange();
  }
}

let currentSeasonEpisodesList = [];

async function onSeasonChange() {
  const selectSeason = document.getElementById('selectSeason');
  const chosenSeason = Number(selectSeason.value) || 1;

  let epCount = 24;
  if (itemDetails && itemDetails.seasons) {
    const found = itemDetails.seasons.find(s => (s.number === chosenSeason || s.season_number === chosenSeason));
    if (found) {
      epCount = found.episodeCount || found.episode_count || found.episodes || 24;
    }
  }

  currentSeasonEpisodeCount = epCount;
  selectedEpisodes = new Set([1]);
  currentSeasonEpisodesList = [];
  renderEpisodesCheckboxes(epCount);
  updateBatchUI();

  if (itemDetails && itemDetails.id && currentMediaType !== 'movie') {
    try {
      const res = await fetch(`/api/season?id=${itemDetails.id}&season=${chosenSeason}`);
      const json = await res.json();
      if (json.success && json.data && json.data.episodes) {
        currentSeasonEpisodesList = json.data.episodes;
        if (json.data.episodes.length > 0) {
          currentSeasonEpisodeCount = json.data.episodes.length;
        }
        renderEpisodesCheckboxes(currentSeasonEpisodeCount);
        updateBatchUI();
      }
    } catch (e) {
      console.debug('Failed to load season details:', e);
    }
  }
}

function renderEpisodesCheckboxes(totalEpisodes) {
  const container = document.getElementById('episodesCheckboxesContainer');
  if (!container) return;
  container.innerHTML = '';
  const now = new Date();

  for (let i = 1; i <= totalEpisodes; i++) {
    const isChecked = selectedEpisodes.has(i);
    const epItem = currentSeasonEpisodesList.find(e => (e.episode_number === i || e.number === i));
    const isUnreleased = epItem && epItem.air_date && new Date(epItem.air_date) > now;
    const dateBadge = epItem && epItem.air_date ? epItem.air_date.slice(5) : '';

    const label = document.createElement('label');
    label.id = `epCard_${i}`;

    if (isUnreleased) {
      label.className = `flex items-center justify-between p-2 rounded-lg border text-xs cursor-pointer select-none transition ${isChecked ? 'bg-amber-950/60 border-amber-500/80 text-amber-300' : 'bg-zinc-950/40 hover:bg-zinc-900 border-zinc-850 text-zinc-400 opacity-80'}`;
      label.title = `Episode ${i} belum tayang (Jadwal rilis: ${epItem.air_date})`;
      label.innerHTML = `
        <div class="flex items-center space-x-1.5 overflow-hidden">
          <input 
            type="checkbox" 
            value="${i}" 
            ${isChecked ? 'checked' : ''} 
            onchange="toggleEpisodeCheckbox(${i})" 
            class="w-3.5 h-3.5 accent-amber-500 rounded bg-zinc-900 border-zinc-700 cursor-pointer"
          />
          <span class="font-mono text-[11px] font-bold">Ep ${i}</span>
        </div>
        <span class="text-[9px] font-mono px-1 py-0.2 rounded bg-zinc-800 text-amber-400/90 border border-amber-800/40" title="Jadwal rilis">${dateBadge}</span>
      `;
    } else {
      label.className = `flex items-center space-x-1.5 p-2 rounded-lg border text-xs cursor-pointer select-none transition ${isChecked ? 'bg-emerald-950/70 border-emerald-500/80 text-emerald-300' : 'bg-zinc-950/80 hover:bg-zinc-900 border-zinc-800 text-zinc-400'}`;
      label.innerHTML = `
        <input 
          type="checkbox" 
          value="${i}" 
          ${isChecked ? 'checked' : ''} 
          onchange="toggleEpisodeCheckbox(${i})" 
          class="w-3.5 h-3.5 accent-emerald-500 rounded bg-zinc-900 border-zinc-700 cursor-pointer"
        />
        <span class="font-mono text-[11px] font-bold">Ep ${i}</span>
      `;
    }

    container.appendChild(label);
  }
}

function toggleEpisodeCheckbox(epNum) {
  if (selectedEpisodes.has(epNum)) {
    if (selectedEpisodes.size > 1) {
      selectedEpisodes.delete(epNum);
    }
  } else {
    selectedEpisodes.add(epNum);
    const epItem = currentSeasonEpisodesList.find(e => (e.episode_number === epNum || e.number === epNum));
    if (epItem && epItem.air_date && new Date(epItem.air_date) > new Date()) {
      showToast(`ℹ️ Episode ${epNum} baru tayang pada ${epItem.air_date} dan kemungkinan belum ada di server stream.`);
    }
  }

  const card = document.getElementById(`epCard_${epNum}`);
  if (card) {
    const isChecked = selectedEpisodes.has(epNum);
    const epItem = currentSeasonEpisodesList.find(e => (e.episode_number === epNum || e.number === epNum));
    const isUnreleased = epItem && epItem.air_date && new Date(epItem.air_date) > new Date();

    if (isUnreleased) {
      card.className = `flex items-center justify-between p-2 rounded-lg border text-xs cursor-pointer select-none transition ${isChecked ? 'bg-amber-950/60 border-amber-500/80 text-amber-300' : 'bg-zinc-950/40 hover:bg-zinc-900 border-zinc-850 text-zinc-400 opacity-80'}`;
    } else {
      card.className = `flex items-center space-x-1.5 p-2 rounded-lg border text-xs cursor-pointer select-none transition ${isChecked ? 'bg-emerald-950/70 border-emerald-500/80 text-emerald-300' : 'bg-zinc-950/80 hover:bg-zinc-900 border-zinc-800 text-zinc-400'}`;
    }
  }

  updateBatchUI();
}

function selectAllEpisodes() {
  selectedEpisodes = new Set();
  const now = new Date();
  let selectedAny = false;

  for (let i = 1; i <= currentSeasonEpisodeCount; i++) {
    const epItem = currentSeasonEpisodesList.find(e => (e.episode_number === i || e.number === i));
    const isUnreleased = epItem && epItem.air_date && new Date(epItem.air_date) > now;
    if (!isUnreleased) {
      selectedEpisodes.add(i);
      selectedAny = true;
    }
  }

  // Fallback jika semua unreleased atau data tidak ada, pilih semua
  if (!selectedAny) {
    for (let i = 1; i <= currentSeasonEpisodeCount; i++) {
      selectedEpisodes.add(i);
    }
  }

  renderEpisodesCheckboxes(currentSeasonEpisodeCount);
  updateBatchUI();
}

function deselectAllEpisodes() {
  selectedEpisodes = new Set([1]);
  renderEpisodesCheckboxes(currentSeasonEpisodeCount);
  updateBatchUI();
}

function updateBatchUI() {
  const counter = document.getElementById('selectedEpisodesCounter');
  const btnText = document.querySelector('#btnExecuteCloud span');
  const filenameEl = document.getElementById('modalFilenamePreview');

  if (!selectedItem) return;
  const title = (selectedItem.title || selectedItem.name || 'video').replace(/[\\/*?:"<>|]/g, '').trim();
  const year = selectedItem.year || (selectedItem.releaseDate ? selectedItem.releaseDate.substring(0, 4) : '');
  const season = Number(document.getElementById('selectSeason')?.value) || 1;

  if (currentMediaType === 'movie') {
    if (counter) counter.classList.add('hidden');
    if (btnText) btnText.textContent = '🚀 1-Klik Kirim Film ke Cloud (Termasuk Subtitle)';
    if (filenameEl) filenameEl.textContent = year ? `${title} (${year}).mp4` : `${title}.mp4`;
    return;
  }

  if (counter) {
    counter.classList.remove('hidden');
    counter.textContent = `${selectedEpisodes.size} Episode Dipilih`;
  }

  const sortedEps = Array.from(selectedEpisodes).sort((a, b) => a - b);

  if (sortedEps.length === 1) {
    if (btnText) btnText.textContent = `🚀 1-Klik Kirim Episode ${sortedEps[0]} ke Cloud (Termasuk Subtitle)`;
    if (filenameEl) filenameEl.textContent = `${title} - S${String(season).padStart(2, '0')}E${String(sortedEps[0]).padStart(2, '0')}.mp4`;
  } else {
    if (btnText) btnText.textContent = `🚀 1-Klik Kirim ${sortedEps.length} Episode Sekaligus ke Cloud (Termasuk Subtitle)`;
    if (filenameEl) filenameEl.textContent = `${title} - S${String(season).padStart(2, '0')} (Batch ${sortedEps.length} Episode MP4 + Subtitle VTT)`;
  }
}

function updateModalQuotaBadge() {
  const el = document.getElementById('modalQuotaInfo');
  if (!el) return;

  if (cloudQuotaData && cloudQuotaData.success) {
    el.textContent = `${cloudQuotaData.remaining_minutes.toLocaleString()} / 2.000 menit riil (~${cloudQuotaData.est_remaining_items} judul)`;
  } else {
    el.textContent = '2.000 menit gratis/bulan (~1.000 judul)';
  }
}

// ==========================================
// 1-Click Cloud Runner Dispatch Trigger (Batch Support)
// ==========================================

async function triggerCloudTransfer() {
  if (!selectedItem) return;

  if (!githubConfig.configured) {
    showToast('Fitur Cloud Runner belum disetel. Silakan isi konfigurasi GitHub untuk mengaktifkan.', true);
    openGithubConfigModal();
    return;
  }

  const title = selectedItem.title || selectedItem.name;
  const season = Number(document.getElementById('selectSeason')?.value) || 1;
  const sortedEps = Array.from(selectedEpisodes).sort((a, b) => a - b);
  const episodesStr = currentMediaType === 'movie' ? "1" : sortedEps.join(',');

  const countLabel = currentMediaType === 'movie' ? title : `${title} S${season} (${sortedEps.length} Episode: ${sortedEps.join(', ')})`;
  showToast(`Memicu cloud untuk: ${countLabel}...`);

  const payload = {
    title: title,
    media_type: currentMediaType,
    season: season,
    episode: sortedEps[0] || 1,
    episodes: episodesStr,
    gdrive_folder: 'frameXTV_Downloads'
  };

  try {
    const res = await fetch('/api/cloud-dispatch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const json = await res.json();

    if (json.success) {
      closeDetailModal();
      document.getElementById('successTitle').textContent = countLabel;
      document.getElementById('cloudSuccessModal').classList.remove('hidden');
      lucide.createIcons();

      setTimeout(fetchCloudQuota, 5000);
    } else {
      showToast(`Gagal: ${json.detail || 'Terjadi kesalahan'}`, true);
    }
  } catch (err) {
    showToast(`Error: ${err.message}`, true);
  }
}

// ==========================================
// Cloud Quota Tracking & GitHub Status
// ==========================================

async function fetchCloudQuota() {
  try {
    const res = await fetch('/api/cloud-quota');
    const json = await res.json();
    if (json.success) {
      cloudQuotaData = json;
      renderCloudQuotaUI(json);
    }
  } catch (e) {
    console.warn('Gagal mengambil data kuota cloud:', e);
  }
}

function renderCloudQuotaUI(data) {
  const brief = document.getElementById('navQuotaBrief');
  const pill = document.getElementById('navQuotaPill');

  if (brief) {
    brief.textContent = `${data.remaining_minutes.toLocaleString()} / ${data.free_tier_minutes.toLocaleString()} m`;
  }
  if (pill) {
    pill.textContent = `~${data.est_remaining_items.toLocaleString()} film`;
  }

  const pLabel = document.getElementById('quotaPercentLabel');
  const pBar = document.getElementById('quotaProgressBar');
  const uText = document.getElementById('quotaUsedText');
  const tText = document.getElementById('quotaTotalText');

  if (pLabel) pLabel.textContent = `${data.percent_used}% Terpakai`;
  if (pBar) pBar.style.width = `${Math.max(1, Math.min(100, data.percent_used))}%`;
  if (uText) uText.textContent = `${data.total_minutes_used} menit terpakai (${data.current_month_runs} transfer)`;
  if (tText) tText.textContent = `Batas: ${data.free_tier_minutes.toLocaleString()} menit/bln`;

  const sUsed = document.getElementById('statUsedMin');
  const sRemain = document.getElementById('statRemainingMin');
  const sItems = document.getElementById('statEstItems');
  const sReset = document.getElementById('statResetDate');
  const sRuns = document.getElementById('statMonthRuns');

  if (sUsed) sUsed.textContent = `${data.total_minutes_used} m`;
  if (sRemain) sRemain.textContent = `${data.remaining_minutes.toLocaleString()} m`;
  if (sItems) sItems.textContent = `~${data.est_remaining_items.toLocaleString()}`;
  if (sReset) sReset.textContent = data.next_reset_str;
  if (sRuns) sRuns.textContent = `${data.recent_transfers ? data.recent_transfers.length : 0} transfer`;

  // Render repository breakdown
  const repoContainer = document.getElementById('repoBreakdownContainer');
  const accountRunsLabel = document.getElementById('statAccountTotalRuns');
  if (accountRunsLabel) {
    accountRunsLabel.textContent = `Total: ${data.total_minutes_used} m (${data.total_account_runs} runs)`;
  }

  if (repoContainer && data.repo_breakdown) {
    repoContainer.innerHTML = '';
    data.repo_breakdown.forEach(item => {
      const row = document.createElement('div');
      row.className = 'p-2 rounded-lg bg-zinc-950 border border-zinc-800/80 flex items-center justify-between text-[11px] font-mono';
      row.innerHTML = `
        <div class="flex items-center space-x-2 truncate pr-2">
          <span class="text-zinc-200 font-bold truncate">${item.repo}</span>
          <span class="text-zinc-500 text-[10px]">(${item.runs} runs)</span>
        </div>
        <div class="text-emerald-400 font-bold shrink-0">
          ${item.minutes} menit
        </div>
      `;
      repoContainer.appendChild(row);
    });
  }

  const histContainer = document.getElementById('recentTransfersContainer');
  if (histContainer && data.recent_transfers) {
    if (data.recent_transfers.length === 0) {
      histContainer.innerHTML = '<div class="text-[11px] text-zinc-500 py-2">Belum ada riwayat transfer.</div>';
    } else {
      histContainer.innerHTML = '';
      data.recent_transfers.forEach(t => {
        const item = document.createElement('div');
        item.className = 'p-2 rounded-lg bg-zinc-950 border border-zinc-800 flex items-center justify-between text-[11px] font-mono';
        const isSuccess = t.conclusion === 'success';
        const durMin = (t.duration_sec / 60).toFixed(1);

        item.innerHTML = `
          <div class="flex items-center space-x-2 truncate pr-2">
            <span class="w-2 h-2 rounded-full ${isSuccess ? 'bg-emerald-400' : 'bg-amber-400'} shrink-0"></span>
            <span class="text-zinc-200 truncate">${t.title || 'Workflow Run'}</span>
          </div>
          <div class="flex items-center space-x-2 shrink-0 text-zinc-400">
            <span>${durMin} m</span>
            <span class="${isSuccess ? 'text-emerald-400' : 'text-amber-400'} font-bold uppercase">${t.conclusion || t.status}</span>
          </div>
        `;
        histContainer.appendChild(item);
      });
    }
  }

  updateModalQuotaBadge();
}

function openCloudQuotaModal() {
  fetchCloudQuota();
  document.getElementById('cloudQuotaModal').classList.remove('hidden');
}

function closeCloudQuotaModal() {
  document.getElementById('cloudQuotaModal').classList.add('hidden');
}

async function fetchGithubStatus() {
  try {
    const res = await fetch('/api/github/status');
    const json = await res.json();
    if (json.success) {
      githubConfig = json;
      const text = document.getElementById('githubStatusText');
      const btn = document.getElementById('btnGithubStatus');
      if (json.configured) {
        text.textContent = 'Cloud Aktif';
        btn.className = 'flex items-center space-x-1.5 px-3 py-1.5 rounded-xl bg-emerald-950/80 border border-emerald-500/50 text-xs text-emerald-300 transition cursor-pointer';
      } else {
        text.textContent = 'Setup Cloud';
        btn.className = 'flex items-center space-x-1.5 px-3 py-1.5 rounded-xl bg-zinc-900 hover:bg-zinc-800 border border-zinc-700 text-xs text-zinc-300 hover:text-white transition cursor-pointer';
      }
      updateCloudUIState();
    }
  } catch (e) {}
}

async function fetchGdriveStatus() {
  try {
    const res = await fetch('/api/gdrive/status');
    const json = await res.json();
    if (json.success) {
      gdriveConfig = json;
      const email = json.email || json.google_account || 'Belum Terhubung';
      const folder = json.gdrive_folder || 'frameXTV_Downloads';

      const navEmail = document.getElementById('navGdriveEmail');
      if (navEmail) navEmail.textContent = email;

      const navFolder = document.getElementById('navGdriveFolder');
      if (navFolder) navFolder.textContent = `📁 ${folder}`;

      const modalEmail = document.getElementById('modalTargetEmail');
      if (modalEmail) modalEmail.textContent = email;

      const successEmail = document.getElementById('successGdriveEmail');
      if (successEmail) successEmail.textContent = email;
    }
  } catch (e) {
    console.warn('Gagal memuat status Google Drive:', e);
  }
}

function openGoogleDriveModal() {
  const email = gdriveConfig.email || gdriveConfig.google_account || 'Belum Terhubung';
  const folder = gdriveConfig.gdrive_folder || 'frameXTV_Downloads';
  showToast(`Akun Google Drive: ${email} | Folder: ${folder}`);
}

function openGithubConfigModal() {
  document.getElementById('inputGithubRepo').value = githubConfig.github_repo || '';
  document.getElementById('githubConfigModal').classList.remove('hidden');
}

function closeGithubConfigModal() {
  document.getElementById('githubConfigModal').classList.add('hidden');
}

async function saveGithubConfig() {
  const repo = document.getElementById('inputGithubRepo').value.trim();
  const token = document.getElementById('inputGithubToken').value.trim();

  if (!repo || !token) {
    showToast('Harap isi Nama Repository dan Token GitHub', true);
    return;
  }

  try {
    const res = await fetch('/api/github/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ github_repo: repo, github_token: token })
    });
    const json = await res.json();
    if (json.success) {
      showToast('Konfigurasi GitHub Cloud Runner berhasil disimpan!');
      closeGithubConfigModal();
      fetchGithubStatus();
      fetchCloudQuota();
    }
  } catch (e) {
    showToast(`Gagal menyimpan: ${e.message}`, true);
  }
}

// ==========================================
// Preview Video
// ==========================================

async function previewStreamVideo() {
  if (!selectedItem) return;
  const container = document.getElementById('playerPreviewContainer');
  const video = document.getElementById('previewVideoPlayer');
  const season = Number(document.getElementById('selectSeason')?.value) || 1;
  const sortedEps = Array.from(selectedEpisodes).sort((a, b) => a - b);
  const episode = sortedEps[0] || 1;

  showToast('Mengambil link stream untuk preview...');

  try {
    const url = `/api/stream?id=${selectedItem.id}&type=${currentMediaType}&season=${season}&episode=${episode}`;
    const res = await fetch(url);
    const json = await res.json();

    if (!json.success || !json.data || !json.data.sources || json.data.sources.length === 0) {
      showToast('Stream tidak dapat diputar saat ini', true);
      return;
    }

    const streamUrl = json.data.sources[0].url;
    container.classList.remove('hidden');

    if (Hls.isSupported()) {
      if (hlsInstance) hlsInstance.destroy();
      hlsInstance = new Hls();
      hlsInstance.loadSource(streamUrl);
      hlsInstance.attachMedia(video);
      hlsInstance.on(Hls.Events.MANIFEST_PARSED, () => {
        video.play().catch(() => {});
      });
    } else if (video.canPlayType('application/vnd.apple.mpegurl')) {
      video.src = streamUrl;
      video.play().catch(() => {});
    }

    showToast(`Preview Episode ${episode} aktif!`);
  } catch (e) {
    showToast(`Gagal memutar preview: ${e.message}`, true);
  }
}

function closePlayerPreview() {
  const container = document.getElementById('playerPreviewContainer');
  const video = document.getElementById('previewVideoPlayer');
  if (video) {
    video.pause();
    video.removeAttribute('src');
    video.load();
  }
  if (hlsInstance) {
    hlsInstance.destroy();
    hlsInstance = null;
  }
  if (container) container.classList.add('hidden');
}

// ==========================================
// Local Download & Downloads Manager
// ==========================================

let activeLocalDownloadTaskId = null;
let localDownloadEventSource = null;

async function fetchLocalDownloadsCount() {
  try {
    const res = await fetch('/api/downloads');
    const json = await res.json();
    if (json.success) {
      const cnt = json.count !== undefined ? json.count : (json.files ? json.files.length : 0);
      const countEl = document.getElementById('navDownloadsCount');
      const badgeEl = document.getElementById('navDownloadsCountBadge');
      const badgeMobileEl = document.getElementById('navDownloadsCountBadgeMobile');
      if (countEl) countEl.textContent = cnt;
      if (badgeEl) badgeEl.textContent = cnt;
      if (badgeMobileEl) badgeMobileEl.textContent = cnt;
    }
  } catch (e) {
    console.debug('Failed to fetch local downloads count:', e);
  }
}

let queuePollInterval = null;

async function triggerLocalDownload() {
  if (!selectedItem) return;

  const title = selectedItem.title || selectedItem.name;
  const season = Number(document.getElementById('selectSeason')?.value) || 1;
  const sortedEps = Array.from(selectedEpisodes).sort((a, b) => a - b);
  const eps = currentMediaType === 'movie' ? [1] : (sortedEps.length > 0 ? sortedEps : [1]);

  const label = currentMediaType === 'movie' ? title : `${title} S${season} (${eps.length} Ep: ${eps.join(', ')})`;
  showToast(`Menyiapkan unduhan lokal: ${label}...`);

  const origLang = (itemDetails && itemDetails.original_language) || (selectedItem && selectedItem.original_language) || null;

  const subModeSelect = document.getElementById('selectSubtitleMode');
  const subMode = subModeSelect ? subModeSelect.value : 'translate_id';

  let targetSubLang = 'id';
  let autoTranslate = true;

  if (subMode === 'none') {
    targetSubLang = 'none';
    autoTranslate = false;
  } else if (subMode === 'original') {
    targetSubLang = 'original';
    autoTranslate = false;
  } else if (subMode.startsWith('translate_')) {
    targetSubLang = subMode.replace('translate_', '');
    autoTranslate = true;
  }

  const payload = {
    id: String(selectedItem.id),
    title: title,
    media_type: currentMediaType,
    season: season,
    episode: eps[0] || 1,
    episodes: eps,
    provider: null,
    filename: null,
    target_sub_lang: targetSubLang,
    auto_translate_sub: autoTranslate,
    original_language: origLang
  };

  try {
    const res = await fetch('/api/download/local', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const json = await res.json();

    if (json.success && json.tasks && json.tasks.length > 0) {
      closeDetailModal();
      showToast(`📥 ${json.tasks.length} unduhan ditambahkan ke antrean!`);
      startQueuePolling();
      // Pantau task pertama
      trackLocalDownloadProgress(json.tasks[0].task_id, json.tasks[0].filename || title);
      refreshQueueData();
    } else {
      showToast(`Gagal memulai unduhan: ${json.detail || 'Terjadi kesalahan'}`, true);
    }
  } catch (err) {
    showToast(`Error: ${err.message}`, true);
  }
}

function startQueuePolling() {
  if (queuePollInterval) clearInterval(queuePollInterval);
  refreshQueueData();
  queuePollInterval = setInterval(refreshQueueData, 2000);
}

function stopQueuePolling() {
  if (queuePollInterval) {
    clearInterval(queuePollInterval);
    queuePollInterval = null;
  }
}

async function refreshQueueData() {
  try {
    const res = await fetch('/api/download/queue');
    const json = await res.json();
    if (json.success && json.queue) {
      renderQueueDrawer(json.queue);
    }
  } catch (e) {
    console.debug('Failed to refresh queue data:', e);
  }
}

function renderQueueDrawer(queue) {
  const badge = document.getElementById('dlQueueBadge');
  const itemsContainer = document.getElementById('dlQueueItemsList');
  const widget = document.getElementById('liveDownloadWidget');

  const tasks = queue.tasks || [];
  const queuedCount = queue.queued_count || 0;
  const activeTask = queue.active;

  const pendingTotal = queuedCount + (activeTask ? 1 : 0);
  if (badge) {
    badge.textContent = `Antrean (${pendingTotal})`;
  }

  // Jika widget tersembunyi tapi ada task aktif/antre, munculkan
  if (pendingTotal > 0 && widget && widget.classList.contains('hidden')) {
    widget.classList.remove('hidden');
    if (activeTask && (!activeLocalDownloadTaskId || activeLocalDownloadTaskId !== activeTask.task_id)) {
      trackLocalDownloadProgress(activeTask.task_id, activeTask.filename);
    }
  }

  if (!itemsContainer) return;

  if (tasks.length === 0) {
    itemsContainer.innerHTML = '<div class="text-[11px] text-zinc-500 italic py-1">Tidak ada riwayat unduhan</div>';
    return;
  }

  // Tampilkan maksimal 8 task terbaru
  itemsContainer.innerHTML = tasks.slice(0, 8).map(t => {
    let statusBadge = '';
    let actionBtn = '';

    if (t.status === 'downloading') {
      statusBadge = `<span class="px-1.5 py-0.5 rounded text-[10px] bg-indigo-950 text-indigo-300 font-mono font-bold animate-pulse border border-indigo-800/80">${t.percent.toFixed(0)}%</span>`;
      actionBtn = `<button onclick="cancelSpecificTask('${t.task_id}')" class="text-zinc-400 hover:text-red-400 text-[10px] px-1.5 py-0.5 rounded bg-zinc-800 transition">Batal</button>`;
    } else if (t.status === 'resolving') {
      statusBadge = `<span class="px-1.5 py-0.5 rounded text-[10px] bg-amber-950/70 text-amber-300 border border-amber-800/50">Mencari</span>`;
      actionBtn = `<button onclick="cancelSpecificTask('${t.task_id}')" class="text-zinc-400 hover:text-red-400 text-[10px] px-1.5 py-0.5 rounded bg-zinc-800 transition">Batal</button>`;
    } else if (t.status === 'translating_sub' || t.status === 'embedding') {
      statusBadge = `<span class="px-1.5 py-0.5 rounded text-[10px] bg-purple-950/70 text-purple-300 border border-purple-800/50">Subtitle</span>`;
    } else if (t.status === 'queued') {
      statusBadge = `<span class="px-1.5 py-0.5 rounded text-[10px] bg-zinc-800 text-zinc-400">Menunggu</span>`;
      actionBtn = `<button onclick="cancelSpecificTask('${t.task_id}')" class="text-zinc-400 hover:text-red-400 text-[10px] px-1.5 py-0.5 rounded bg-zinc-800 transition">Batal</button>`;
    } else if (t.status === 'completed') {
      statusBadge = `<span class="px-1.5 py-0.5 rounded text-[10px] bg-emerald-950/80 text-emerald-400 font-medium border border-emerald-800/60">✓ Selesai</span>`;
    } else if (t.status === 'failed') {
      statusBadge = `<span class="px-1.5 py-0.5 rounded text-[10px] bg-red-950/80 text-red-400 font-medium border border-red-800/60" title="${t.error || ''}">✗ Gagal</span>`;
      actionBtn = `<button onclick="retrySpecificTask('${t.task_id}')" class="text-indigo-400 hover:text-indigo-300 text-[10px] px-1.5 py-0.5 rounded bg-indigo-950/90 border border-indigo-800 transition font-mono">Ulangi</button>`;
    } else if (t.status === 'cancelled') {
      statusBadge = `<span class="px-1.5 py-0.5 rounded text-[10px] bg-zinc-800 text-zinc-500">Dibatalkan</span>`;
      actionBtn = `<button onclick="retrySpecificTask('${t.task_id}')" class="text-indigo-400 hover:text-indigo-300 text-[10px] px-1.5 py-0.5 rounded bg-indigo-950/90 border border-indigo-800 transition font-mono">Ulangi</button>`;
    }

    return `
      <div class="flex items-center justify-between p-1.5 rounded-lg bg-zinc-950/60 border border-zinc-800/60 text-xs">
        <div class="truncate max-w-[170px] sm:max-w-[210px]">
          <p class="font-medium text-white truncate text-[11px]">${t.filename || t.title}</p>
          <p class="text-[9px] text-zinc-400 font-mono">${t.downloaded_str || '0 B'} • ${t.speed_str || ''}</p>
        </div>
        <div class="flex items-center space-x-1.5 shrink-0">
          ${statusBadge}
          ${actionBtn}
        </div>
      </div>
    `;
  }).join('');
}

function toggleQueueDrawer() {
  const drawer = document.getElementById('dlQueueDrawer');
  const chevron = document.getElementById('dlQueueChevron');
  if (!drawer) return;
  const isHidden = drawer.classList.contains('hidden');
  if (isHidden) {
    drawer.classList.remove('hidden');
    if (chevron) chevron.style.transform = 'rotate(180deg)';
    refreshQueueData();
  } else {
    drawer.classList.add('hidden');
    if (chevron) chevron.style.transform = 'rotate(0deg)';
  }
}

async function cancelSpecificTask(taskId) {
  try {
    await fetch(`/api/download/cancel/${taskId}`, { method: 'POST' });
    showToast('Tugas unduhan dibatalkan.');
    refreshQueueData();
  } catch (e) {
    console.error('Cancel task error:', e);
  }
}

async function retrySpecificTask(taskId) {
  try {
    const res = await fetch(`/api/download/retry/${taskId}`, { method: 'POST' });
    const json = await res.json();
    if (json.success) {
      showToast('Tugas dimasukkan kembali ke antrean unduhan!');
      startQueuePolling();
      const widget = document.getElementById('liveDownloadWidget');
      if (widget) widget.classList.remove('hidden');
      refreshQueueData();
    }
  } catch (e) {
    console.error('Retry task error:', e);
  }
}

async function cancelAllDownloads() {
  try {
    const res = await fetch('/api/download/cancel-all', { method: 'POST' });
    const json = await res.json();
    showToast(`${json.cancelled_count || 0} tugas unduhan dibatalkan.`);
    refreshQueueData();
  } catch (e) {
    console.error('Cancel all error:', e);
  }
}

function trackLocalDownloadProgress(taskId, filename) {
  if (localDownloadEventSource) {
    localDownloadEventSource.close();
    localDownloadEventSource = null;
  }

  activeLocalDownloadTaskId = taskId;

  const widget = document.getElementById('liveDownloadWidget');
  const titleEl = document.getElementById('dlWidgetTitle');
  const statusEl = document.getElementById('dlWidgetStatus');
  const percentEl = document.getElementById('dlWidgetProgressPercent');
  const speedEtaEl = document.getElementById('dlWidgetSpeedEta');
  const progressBar = document.getElementById('dlWidgetProgressBar');

  if (widget) widget.classList.remove('hidden');
  if (titleEl) titleEl.textContent = filename || 'Mengunduh...';
  if (statusEl) statusEl.textContent = 'Menghubungkan ke server stream...';
  if (percentEl) percentEl.textContent = '0%';
  if (progressBar) progressBar.style.width = '0%';

  localDownloadEventSource = new EventSource(`/api/download/progress/${taskId}`);

  localDownloadEventSource.onmessage = async (event) => {
    try {
      const data = JSON.parse(event.data);
      if (titleEl && data.filename) titleEl.textContent = data.filename;

      if (data.status === 'resolving') {
        if (statusEl) statusEl.textContent = data.speed_str || 'Mencari server stream aktif...';
      } else if (data.status === 'downloading') {
        const pct = Math.max(0, Math.min(100, data.percent || 0));
        if (statusEl) statusEl.textContent = `Menyedot video (${data.downloaded_str || ''} / ${data.total_str || ''})`;
        if (percentEl) percentEl.textContent = `${pct.toFixed(1)}%`;
        if (progressBar) progressBar.style.width = `${pct}%`;
        if (speedEtaEl) speedEtaEl.textContent = `${data.speed_str || '0 KB/s'} • ETA ${data.eta_str || '--:--'}`;
      } else if (data.status === 'translating_sub') {
        if (statusEl) statusEl.textContent = `🌐 ${data.speed_str || 'Menerjemahkan subtitle ke Indonesia...'}`;
        if (percentEl) percentEl.textContent = `${(data.percent || 99).toFixed(1)}%`;
        if (progressBar) progressBar.style.width = `${data.percent || 99}%`;
        if (speedEtaEl) speedEtaEl.textContent = 'Auto-Translate • Sedang memproses';
      } else if (data.status === 'embedding') {
        if (statusEl) statusEl.textContent = 'Menanamkan subtitle ke video MP4...';
        if (percentEl) percentEl.textContent = '99%';
        if (progressBar) progressBar.style.width = '99%';
      } else if (data.status === 'completed' || data.status === 'failed' || data.status === 'cancelled') {
        // Task ini selesai, gagal, atau dibatalkan
        if (data.status === 'completed') {
          if (statusEl) statusEl.textContent = '✅ Selesai! Tersimpan di downloads/';
          if (percentEl) percentEl.textContent = '100%';
          if (progressBar) progressBar.style.width = '100%';
          if (speedEtaEl) speedEtaEl.textContent = `${data.downloaded_str || ''} • Tuntas`;
          showToast(`🎉 Sukses mengunduh: ${data.output_file || filename}`);
          fetchLocalDownloadsCount();
          if (currentMainView === 'downloads') {
            loadLocalDownloadsList();
          }
        } else if (data.status === 'failed') {
          if (statusEl) statusEl.textContent = `❌ Gagal: ${data.error || 'Gagal'}`;
          showToast(`Episode ${filename} gagal diunduh: ${data.error || ''}`, true);
        } else if (data.status === 'cancelled') {
          if (statusEl) statusEl.textContent = '⚠️ Unduhan dibatalkan.';
        }

        if (localDownloadEventSource) {
          localDownloadEventSource.close();
          localDownloadEventSource = null;
        }

        refreshQueueData();

        // Cek apakah ada antrean berikutnya yang sedang berjalan atau mengantre
        setTimeout(async () => {
          try {
            const res = await fetch('/api/download/queue');
            const json = await res.json();
            if (json.success && json.queue) {
              const active = json.queue.active;
              if (active && active.task_id !== taskId) {
                // Ada episode berikutnya yang sedang diproses! Auto-advance live tracking
                showToast(`Melanjutkan antrean: ${active.filename || active.title}...`);
                trackLocalDownloadProgress(active.task_id, active.filename || active.title);
              } else if (json.queue.queued_count > 0) {
                // Masih ada yang queued di backend, tunggu sebentar worker mengambilnya
                setTimeout(() => refreshQueueData(), 1500);
              } else {
                // Semua antrean tuntas
                activeLocalDownloadTaskId = null;
                stopQueuePolling();
                setTimeout(() => {
                  if (!activeLocalDownloadTaskId && widget) widget.classList.add('hidden');
                }, 8000);
              }
            }
          } catch (e) {
            console.debug('Error checking next queue task:', e);
          }
        }, 1200);
      }
    } catch (e) {
      console.error('Error parsing progress SSE:', e);
    }
  };

  localDownloadEventSource.onerror = () => {
    if (localDownloadEventSource) {
      localDownloadEventSource.close();
      localDownloadEventSource = null;
    }
  };
}

async function cancelActiveDownload() {
  if (!activeLocalDownloadTaskId) {
    const widget = document.getElementById('liveDownloadWidget');
    if (widget) widget.classList.add('hidden');
    return;
  }

  try {
    await fetch(`/api/download/cancel/${activeLocalDownloadTaskId}`, { method: 'POST' });
    showToast('Membatalkan unduhan...');
    refreshQueueData();
  } catch (e) {
    console.error('Cancel error:', e);
  }
}

// ==========================================
// View Switcher: Browse vs Download Manager (Full-Screen)
// ==========================================
let currentMainView = 'browse';

function switchMainView(viewName, updateHash = true) {
  currentMainView = viewName;
  const viewBrowse = document.getElementById('viewBrowse');
  const viewDownloads = document.getElementById('viewDownloads');

  const tabBrowse = document.getElementById('navTabBrowse');
  const tabDownloads = document.getElementById('navTabDownloads');
  const tabBrowseMobile = document.getElementById('navTabBrowseMobile');
  const tabDownloadsMobile = document.getElementById('navTabDownloadsMobile');

  const activeBrowseClass = 'flex items-center space-x-2 px-3.5 py-1.5 rounded-xl text-xs font-bold transition bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 shadow-sm cursor-pointer';
  const inactiveBrowseClass = 'flex items-center space-x-2 px-3.5 py-1.5 rounded-xl text-xs font-semibold text-zinc-400 hover:text-white hover:bg-zinc-800/80 transition cursor-pointer';

  const activeDlClass = 'flex items-center space-x-2 px-3.5 py-1.5 rounded-xl text-xs font-bold transition bg-indigo-500/20 text-indigo-400 border border-indigo-500/30 shadow-sm cursor-pointer';
  const inactiveDlClass = 'flex items-center space-x-2 px-3.5 py-1.5 rounded-xl text-xs font-semibold text-zinc-400 hover:text-white hover:bg-zinc-800/80 transition cursor-pointer';

  const activeBrowseMobileClass = 'flex-1 flex items-center justify-center space-x-1.5 px-3 py-1.5 rounded-lg text-xs font-bold transition bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 shadow-sm cursor-pointer';
  const inactiveBrowseMobileClass = 'flex-1 flex items-center justify-center space-x-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold text-zinc-400 hover:text-white transition cursor-pointer';

  const activeDlMobileClass = 'flex-1 flex items-center justify-center space-x-1.5 px-3 py-1.5 rounded-lg text-xs font-bold transition bg-indigo-500/20 text-indigo-400 border border-indigo-500/30 shadow-sm cursor-pointer';
  const inactiveDlMobileClass = 'flex-1 flex items-center justify-center space-x-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold text-zinc-400 hover:text-white transition cursor-pointer';

  if (viewName === 'downloads') {
    if (viewBrowse) viewBrowse.classList.add('hidden');
    if (viewDownloads) viewDownloads.classList.remove('hidden');

    if (tabBrowse) tabBrowse.className = inactiveBrowseClass;
    if (tabDownloads) tabDownloads.className = activeDlClass;
    if (tabBrowseMobile) tabBrowseMobile.className = inactiveBrowseMobileClass;
    if (tabDownloadsMobile) tabDownloadsMobile.className = activeDlMobileClass;

    if (updateHash && window.location.hash !== '#downloads') {
      try { history.replaceState(null, '', '#downloads'); } catch (e) {}
    }

    try { window.scrollTo({ top: 0, behavior: 'smooth' }); } catch (e) {}
    loadLocalDownloadsList();
  } else {
    if (viewBrowse) viewBrowse.classList.remove('hidden');
    if (viewDownloads) viewDownloads.classList.add('hidden');

    if (tabBrowse) tabBrowse.className = activeBrowseClass;
    if (tabDownloads) tabDownloads.className = inactiveDlClass;
    if (tabBrowseMobile) tabBrowseMobile.className = activeBrowseMobileClass;
    if (tabDownloadsMobile) tabDownloadsMobile.className = inactiveDlMobileClass;

    if (updateHash && window.location.hash !== '#browse' && window.location.hash !== '') {
      try { history.replaceState(null, '', '#browse'); } catch (e) {}
    }
  }

  if (window.lucide && typeof window.lucide.createIcons === 'function') {
    window.lucide.createIcons();
  }
}

function openLocalDownloadsModal() {
  switchMainView('downloads');
}

function closeLocalDownloadsModal() {
  switchMainView('browse');
}

// ==========================================
// Full-Screen Download Manager Logic
// ==========================================
let dlRawFiles = [];
let dlSearchQuery = '';
let dlActiveFilter = 'all'; // 'all', 'video', 'sub'
let dlSortBy = 'newest';     // 'newest', 'oldest', 'size_desc', 'size_asc', 'name_asc'
let dlSelectedFilenames = new Set();

function formatBytes(bytes) {
  if (!bytes || bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function handleDlSearchInput(val) {
  dlSearchQuery = (val || '').trim().toLowerCase();
  const clearBtn = document.getElementById('dlSearchClearBtn');
  if (clearBtn) {
    if (dlSearchQuery) clearBtn.classList.remove('hidden');
    else clearBtn.classList.add('hidden');
  }
  renderDlFiles();
}

function clearDlSearch() {
  const input = document.getElementById('dlSearchInput');
  if (input) input.value = '';
  handleDlSearchInput('');
}

function setDlFilter(filterType) {
  dlActiveFilter = filterType;
  const btnAll = document.getElementById('dlFilterBtnAll');
  const btnVideo = document.getElementById('dlFilterBtnVideo');
  const btnSub = document.getElementById('dlFilterBtnSub');

  const activeClass = 'px-3 py-1.5 rounded-lg text-xs font-bold transition bg-indigo-600 text-white shadow cursor-pointer';
  const inactiveClass = 'px-3 py-1.5 rounded-lg text-xs font-semibold text-zinc-400 hover:text-white transition cursor-pointer';

  if (btnAll) btnAll.className = filterType === 'all' ? activeClass : inactiveClass;
  if (btnVideo) btnVideo.className = filterType === 'video' ? activeClass : inactiveClass;
  if (btnSub) btnSub.className = filterType === 'sub' ? activeClass : inactiveClass;

  renderDlFiles();
}

function handleDlSortChange(sortVal) {
  dlSortBy = sortVal;
  renderDlFiles();
}

async function loadLocalDownloadsList() {
  const container = document.getElementById('dlFilesList');
  if (!container) return;

  container.innerHTML = '<div class="py-12 text-center text-xs text-zinc-500 font-mono"><div class="w-8 h-8 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin mx-auto mb-3"></div>Memuat daftar berkas tersimpan...</div>';

  try {
    const res = await fetch('/api/downloads');
    const json = await res.json();

    if (!json.success || !json.files) {
      dlRawFiles = [];
    } else {
      dlRawFiles = json.files;
    }

    // Update Stats di Banner Dashboard
    const totalFilesEl = document.getElementById('dlStatTotalFiles');
    const totalSizeEl = document.getElementById('dlStatTotalSize');
    const countsEl = document.getElementById('dlStatCounts');
    if (totalFilesEl) totalFilesEl.textContent = `${json.count !== undefined ? json.count : dlRawFiles.length} File`;
    if (totalSizeEl) totalSizeEl.textContent = json.total_size_str || '0 B';
    if (countsEl) countsEl.textContent = `${json.video_count || 0} Video / ${json.subtitle_count || 0} Sub`;

    // Update Counter di Tab Filter
    const fCountAll = document.getElementById('filterCountAll');
    const fCountVideo = document.getElementById('filterCountVideo');
    const fCountSub = document.getElementById('filterCountSub');
    if (fCountAll) fCountAll.textContent = dlRawFiles.length;
    if (fCountVideo) fCountVideo.textContent = json.video_count !== undefined ? json.video_count : dlRawFiles.filter(f => ['mp4', 'mkv', 'webm', 'avi'].includes(f.ext)).length;
    if (fCountSub) fCountSub.textContent = json.subtitle_count !== undefined ? json.subtitle_count : dlRawFiles.filter(f => ['vtt', 'srt', 'ass'].includes(f.ext)).length;

    // Update Nav Count
    const navCount = document.getElementById('navDownloadsCount');
    const navBadge = document.getElementById('navDownloadsCountBadge');
    const navBadgeMobile = document.getElementById('navDownloadsCountBadgeMobile');
    if (navCount) navCount.textContent = dlRawFiles.length;
    if (navBadge) navBadge.textContent = dlRawFiles.length;
    if (navBadgeMobile) navBadgeMobile.textContent = dlRawFiles.length;

    // Prune seleksi yang file-nya sudah tidak ada
    const existingNames = new Set(dlRawFiles.map(f => f.filename));
    for (const name of dlSelectedFilenames) {
      if (!existingNames.has(name)) dlSelectedFilenames.delete(name);
    }

    renderDlFiles();
  } catch (err) {
    container.innerHTML = `<div class="py-8 text-center text-xs text-red-400 font-mono">Gagal memuat file: ${err.message}</div>`;
  }
}

function getFilteredAndSortedFiles() {
  let list = [...dlRawFiles];

  // 1. Filter by Search Query
  if (dlSearchQuery) {
    list = list.filter(f => f.filename.toLowerCase().includes(dlSearchQuery));
  }

  // 2. Filter by Type
  if (dlActiveFilter === 'video') {
    list = list.filter(f => ['mp4', 'mkv', 'webm', 'avi'].includes(f.ext));
  } else if (dlActiveFilter === 'sub') {
    list = list.filter(f => ['vtt', 'srt', 'ass'].includes(f.ext));
  }

  // 3. Sort
  if (dlSortBy === 'newest') {
    list.sort((a, b) => (b.modified_at || 0) - (a.modified_at || 0));
  } else if (dlSortBy === 'oldest') {
    list.sort((a, b) => (a.modified_at || 0) - (b.modified_at || 0));
  } else if (dlSortBy === 'size_desc') {
    list.sort((a, b) => (b.size_bytes || 0) - (a.size_bytes || 0));
  } else if (dlSortBy === 'size_asc') {
    list.sort((a, b) => (a.size_bytes || 0) - (b.size_bytes || 0));
  } else if (dlSortBy === 'name_asc') {
    list.sort((a, b) => a.filename.localeCompare(b.filename));
  }

  return list;
}

function renderDlFiles() {
  const container = document.getElementById('dlFilesList');
  if (!container) return;

  const files = getFilteredAndSortedFiles();

  if (files.length === 0) {
    if (dlRawFiles.length === 0) {
      container.innerHTML = `
        <div class="py-16 text-center space-y-3 bg-zinc-900/40 border border-zinc-800 rounded-3xl">
          <div class="w-14 h-14 rounded-2xl bg-zinc-800 text-zinc-500 flex items-center justify-center mx-auto">
            <i data-lucide="folder-open" class="w-7 h-7"></i>
          </div>
          <div class="text-sm font-semibold text-zinc-300">Belum ada file di folder <code class="text-indigo-400 font-mono">downloads/</code></div>
          <div class="text-xs text-zinc-500 max-w-sm mx-auto">Silakan pilih film atau episode di halaman Jelajah Media, lalu klik tombol "Unduh ke Komputer".</div>
          <div class="pt-2">
            <button onclick="switchMainView('browse')" class="px-4 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white font-bold text-xs transition cursor-pointer">
              Cari & Unduh Media
            </button>
          </div>
        </div>
      `;
    } else {
      container.innerHTML = `
        <div class="py-16 text-center space-y-2 bg-zinc-900/40 border border-dashed border-zinc-800 rounded-3xl">
          <i data-lucide="search-x" class="w-8 h-8 text-zinc-500 mx-auto mb-1"></i>
          <div class="text-sm font-semibold text-zinc-300">Tidak ada berkas yang cocok</div>
          <div class="text-xs text-zinc-500">Tidak ditemukan file dengan kata kunci atau filter saat ini.</div>
          <div class="pt-2">
            <button onclick="clearDlSearch(); setDlFilter('all');" class="px-3.5 py-1.5 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-zinc-300 text-xs font-mono transition cursor-pointer">
              Reset Filter & Pencarian
            </button>
          </div>
        </div>
      `;
    }
    updateSelectionToolbar(files);
    lucide.createIcons();
    return;
  }

  container.innerHTML = files.map(f => {
    const isVideo = ['mp4', 'mkv', 'webm', 'avi'].includes(f.ext);
    const icon = isVideo ? 'video' : 'subtitles';
    const isChecked = dlSelectedFilenames.has(f.filename);

    const dateObj = new Date(f.modified_at * 1000);
    const dateFormatted = dateObj.toLocaleString('id-ID', {
      day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit'
    });

    const isRecent = f.is_recent || (Date.now() / 1000 - f.modified_at < 86400);

    const formatBadge = isVideo 
      ? `<span class="px-1.5 py-0.5 rounded text-[10px] font-mono font-bold bg-indigo-950 text-indigo-300 border border-indigo-800/80 uppercase">${f.ext}</span>`
      : `<span class="px-1.5 py-0.5 rounded text-[10px] font-mono font-bold bg-teal-950 text-teal-300 border border-teal-800/80 uppercase">${f.ext}</span>`;

    const recentBadge = isRecent 
      ? `<span class="px-2 py-0.5 rounded text-[10px] font-semibold bg-emerald-950/90 text-emerald-300 border border-emerald-800/80 flex items-center gap-1 shrink-0"><span class="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></span> Baru</span>`
      : '';

    const safeFn = encodeURIComponent(f.filename).replace(/'/g, '%27');
    const safeUrl = encodeURIComponent(f.url).replace(/'/g, '%27');

    return `
      <div class="flex items-center justify-between p-3.5 rounded-2xl ${isChecked ? 'bg-indigo-950/30 border-indigo-500/50' : 'bg-zinc-950/80 border-zinc-800/80 hover:border-zinc-700'} border transition gap-3 group shadow-sm">
        <div class="flex items-center space-x-3.5 overflow-hidden">
          <input
            type="checkbox"
            ${isChecked ? 'checked' : ''}
            onchange="toggleFileSelection(decodeURIComponent('${safeFn}'), this.checked)"
            class="w-4 h-4 rounded bg-zinc-900 border-zinc-700 text-indigo-600 focus:ring-0 focus:ring-offset-0 cursor-pointer shrink-0"
          />
          <div class="w-10 h-10 rounded-xl ${isVideo ? 'bg-indigo-500/20 text-indigo-400 border border-indigo-500/30' : 'bg-teal-500/20 text-teal-400 border border-teal-500/30'} flex items-center justify-center shrink-0">
            <i data-lucide="${icon}" class="w-5 h-5"></i>
          </div>
          <div class="overflow-hidden">
            <div class="flex items-center gap-2 flex-wrap">
              <span class="text-xs sm:text-sm font-bold text-white truncate max-w-xs sm:max-w-lg md:max-w-xl group-hover:text-indigo-300 transition" title="${escapeHtml(f.filename)}">
                ${escapeHtml(f.filename)}
              </span>
              ${formatBadge}
              ${recentBadge}
            </div>
            <div class="text-[11px] text-zinc-500 font-mono flex items-center gap-2 mt-1">
              <span class="font-bold text-zinc-300">${f.size_str}</span>
              <span>•</span>
              <span>${dateFormatted}</span>
            </div>
          </div>
        </div>

        <!-- Action Buttons -->
        <div class="flex items-center space-x-1.5 sm:space-x-2 shrink-0">
          <a
            href="${f.url}"
            download="${escapeHtml(f.filename)}"
            class="px-3.5 py-1.5 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white font-bold text-xs flex items-center space-x-1.5 transition shadow-sm cursor-pointer"
            title="Download file ke browser"
          >
            <i data-lucide="download" class="w-3.5 h-3.5"></i>
            <span class="hidden sm:inline">Unduh</span>
          </a>
          <button
            onclick="copyFileLink(window.location.origin + decodeURIComponent('${safeUrl}'))"
            class="p-2 rounded-xl bg-zinc-900 hover:bg-zinc-800 text-zinc-400 hover:text-white border border-zinc-800 transition cursor-pointer"
            title="Salin tautan download"
          >
            <i data-lucide="copy" class="w-3.5 h-3.5"></i>
          </button>
          <button
            onclick="deleteDownloadedFile(decodeURIComponent('${safeFn}'))"
            class="p-2 rounded-xl bg-zinc-900 hover:bg-red-950/80 text-zinc-400 hover:text-red-400 border border-zinc-800 hover:border-red-800/60 transition cursor-pointer"
            title="Hapus file ini"
          >
            <i data-lucide="trash-2" class="w-3.5 h-3.5"></i>
          </button>
        </div>
      </div>
    `;
  }).join('');

  updateSelectionToolbar(files);
  lucide.createIcons();
}

function updateSelectionToolbar(visibleFiles) {
  const summaryEl = document.getElementById('dlSelectionSummary');
  const deleteBtn = document.getElementById('dlBtnDeleteSelected');
  const selectAllCb = document.getElementById('dlSelectAllCheckbox');

  const count = dlSelectedFilenames.size;

  if (summaryEl) {
    if (count === 0) {
      summaryEl.textContent = '0 file terpilih';
      summaryEl.className = 'text-zinc-500 font-mono';
    } else {
      let selectedBytes = 0;
      dlRawFiles.forEach(f => {
        if (dlSelectedFilenames.has(f.filename)) {
          selectedBytes += (f.size_bytes || 0);
        }
      });
      summaryEl.textContent = `${count} file terpilih (${formatBytes(selectedBytes)})`;
      summaryEl.className = 'text-indigo-400 font-bold font-mono';
    }
  }

  if (deleteBtn) {
    deleteBtn.disabled = count === 0;
  }

  if (selectAllCb) {
    if (visibleFiles && visibleFiles.length > 0) {
      const allVisibleSelected = visibleFiles.every(f => dlSelectedFilenames.has(f.filename));
      selectAllCb.checked = allVisibleSelected;
      selectAllCb.indeterminate = (!allVisibleSelected && visibleFiles.some(f => dlSelectedFilenames.has(f.filename)));
    } else {
      selectAllCb.checked = false;
      selectAllCb.indeterminate = false;
    }
  }
}

function toggleFileSelection(filename, isChecked) {
  if (isChecked) {
    dlSelectedFilenames.add(filename);
  } else {
    dlSelectedFilenames.delete(filename);
  }
  const visible = getFilteredAndSortedFiles();
  updateSelectionToolbar(visible);
  renderDlFiles();
}

function toggleSelectAllFiles(checked) {
  const visible = getFilteredAndSortedFiles();
  if (checked) {
    visible.forEach(f => dlSelectedFilenames.add(f.filename));
  } else {
    visible.forEach(f => dlSelectedFilenames.delete(f.filename));
  }
  renderDlFiles();
}

async function deleteSelectedFiles() {
  if (dlSelectedFilenames.size === 0) return;

  const count = dlSelectedFilenames.size;
  let totalBytes = 0;
  dlRawFiles.forEach(f => {
    if (dlSelectedFilenames.has(f.filename)) totalBytes += (f.size_bytes || 0);
  });

  const msg = `Apakah Anda yakin ingin menghapus ${count} berkas terpilih (${formatBytes(totalBytes)}) dari komputer?`;
  if (!confirm(msg)) return;

  try {
    showToast(`Menghapus ${count} berkas...`);
    const filenamesArray = Array.from(dlSelectedFilenames);
    const res = await fetch('/api/files/bulk-delete', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ filenames: filenamesArray })
    });
    const json = await res.json();
    if (json.success) {
      dlSelectedFilenames.clear();
      showToast(`🎉 Sukses menghapus ${json.deleted_count} berkas (${json.freed_str} dibebaskan).`);
      loadLocalDownloadsList();
      fetchLocalDownloadsCount();
    } else {
      showToast(`Gagal menghapus sebagian file: ${json.detail || 'Terjadi kesalahan'}`, true);
    }
  } catch (err) {
    showToast(`Error: ${err.message}`, true);
  }
}

async function cleanRedundantSubtitles() {
  const subFiles = dlRawFiles.filter(f => ['vtt', 'srt', 'ass'].includes(f.ext));
  if (subFiles.length === 0) {
    showToast('Tidak ada berkas subtitle sisa di folder downloads/.');
    return;
  }

  const count = subFiles.length;
  const msg = `Hapus ${count} berkas subtitle sisa (.vtt / .srt)?\n\nCatatan: Subtitle Indonesia sudah otomatis tertanam (embedded) di dalam file video .mp4, sehingga berkas teks ini aman dihapus untuk merapikan daftar.`;
  if (!confirm(msg)) return;

  try {
    showToast(`Membersihkan ${count} berkas subtitle...`);
    const res = await fetch('/api/files/cleanup-subtitles', { method: 'POST' });
    const json = await res.json();
    if (json.success) {
      showToast(`✨ Bersih! ${json.deleted_count} berkas subtitle dihapus (${json.freed_str} ruang dibebaskan).`);
      loadLocalDownloadsList();
      fetchLocalDownloadsCount();
    } else {
      showToast(`Gagal membersihkan: ${json.detail || 'Error'}`, true);
    }
  } catch (err) {
    showToast(`Error: ${err.message}`, true);
  }
}

function copyFileLink(link) {
  navigator.clipboard.writeText(link).then(() => {
    showToast('Tautan unduhan disalin ke clipboard!');
  }).catch(() => {
    showToast(link);
  });
}

async function deleteDownloadedFile(filename) {
  if (!confirm(`Hapus berkas "${filename}" dari komputer?`)) return;

  try {
    const res = await fetch(`/api/files/${encodeURIComponent(filename)}`, { method: 'DELETE' });
    const json = await res.json();
    if (json.success) {
      showToast(`Berkas "${filename}" berhasil dihapus.`);
      dlSelectedFilenames.delete(filename);
      loadLocalDownloadsList();
      fetchLocalDownloadsCount();
    } else {
      showToast(`Gagal menghapus: ${json.detail || 'Error'}`, true);
    }
  } catch (e) {
    showToast(`Error: ${e.message}`, true);
  }
}

// Global scope bindings for inline HTML handlers & external callers
window.switchMainView = switchMainView;
window.setMediaType = setMediaType;
window.setDlFilter = setDlFilter;
window.handleDlSortChange = handleDlSortChange;
window.handleDlSearchInput = handleDlSearchInput;
window.clearDlSearch = clearDlSearch;
window.toggleSelectAllFiles = toggleSelectAllFiles;
window.toggleFileSelection = toggleFileSelection;
window.deleteSelectedFiles = deleteSelectedFiles;
window.cleanRedundantSubtitles = cleanRedundantSubtitles;
window.loadLocalDownloadsList = loadLocalDownloadsList;
window.deleteDownloadedFile = deleteDownloadedFile;
window.copyFileLink = copyFileLink;
window.triggerSearch = triggerSearch;
window.resetSearch = resetSearch;
window.quickSearch = quickSearch;
window.openLocalDownloadsModal = openLocalDownloadsModal;
window.closeLocalDownloadsModal = closeLocalDownloadsModal;
window.openCloudQuotaModal = openCloudQuotaModal;
window.closeCloudQuotaModal = closeCloudQuotaModal;
window.openGoogleDriveModal = openGoogleDriveModal;
window.openGithubConfigModal = openGithubConfigModal;
window.closeGithubConfigModal = closeGithubConfigModal;
window.onSubtitleModeChange = onSubtitleModeChange;
window.updateCloudUIState = updateCloudUIState;
