/* StreamDown v1.3 — Frontend Application Logic */

(function () {
  "use strict";

  // ── DOM References ─────────────────────────────────────────────────────
  const $ = (sel) => document.querySelector(sel);
  const inputUrl = $("#input-url");
  const inputSeason = $("#input-season");
  const inputEpisode = $("#input-episode");
  const inputFilename = $("#input-filename");
  const tvFields = $("#tv-fields");
  const btnInspect = $("#btn-inspect");
  const btnDownload = $("#btn-download");
  const btnDownloadText = $("#btn-download-text");
  const btnSelectAllSubs = $("#btn-select-all-subs");
  const errorBox = $("#error-box");
  const errorText = $("#error-text");
  const loadingBox = $("#loading-box");
  const resultsSection = $("#results-section");

  // Tab Navigation
  const tabBtnDownloader = $("#tab-btn-downloader");
  const tabBtnSaved = $("#tab-btn-saved");
  const tabDownloader = $("#tab-downloader");
  const tabSavedFiles = $("#tab-saved-files");
  const navDownloadsCount = $("#nav-downloads-count");

  // Episodes & Sources
  const episodeSelectorCard = $("#episode-selector-card");
  const seasonsContainer = $("#seasons-container");
  const seasonsBar = $("#seasons-bar");
  const episodesGrid = $("#episodes-grid");
  const episodeCountBadge = $("#episode-count-badge");
  const sourcesList = $("#sources-list");
  const sourcesLoading = $("#sources-loading");
  const sourcesEmptyHint = $("#sources-empty-hint");
  const activeProvidersCount = $("#active-providers-count");

  // Active Downloads (Non-blocking queue)
  const activeDownloadsCard = $("#active-downloads-card");
  const activeTasksList = $("#active-tasks-list");
  const activeTasksCount = $("#active-tasks-count");

  // Saved Files Tab
  const btnRefreshSavedTab = $("#btn-refresh-saved-tab");
  const searchSavedFiles = $("#search-saved-files");
  const savedSummary = $("#saved-summary");
  const downloadsList = $("#downloads-list");

  // Toast
  const toast = $("#toast");
  const toastText = $("#toast-text");

  // State
  let currentTab = "downloader";
  let inspectData = null;
  let currentBaseTitle = "";
  let selectedSeason = null;
  let selectedEpisode = null;
  let allSubsSelected = false;
  let toastTimer = null;
  let activeEventSources = new Map(); // taskId -> EventSource
  let cachedSavedFiles = [];

  // ── Tab Navigation ─────────────────────────────────────────────────────
  function switchTab(tab) {
    currentTab = tab;
    if (tab === "downloader") {
      tabDownloader.classList.remove("hidden");
      tabSavedFiles.classList.add("hidden");
      tabBtnDownloader.className =
        "tab-btn flex items-center space-x-2 px-3.5 py-1.5 rounded-lg text-xs font-semibold transition-all cursor-pointer bg-white text-zinc-950 shadow-sm";
      tabBtnSaved.className =
        "tab-btn flex items-center space-x-2 px-3.5 py-1.5 rounded-lg text-xs font-medium text-zinc-400 hover:text-white transition-all cursor-pointer";
    } else {
      tabDownloader.classList.add("hidden");
      tabSavedFiles.classList.remove("hidden");
      tabBtnSaved.className =
        "tab-btn flex items-center space-x-2 px-3.5 py-1.5 rounded-lg text-xs font-semibold transition-all cursor-pointer bg-white text-zinc-950 shadow-sm";
      tabBtnDownloader.className =
        "tab-btn flex items-center space-x-2 px-3.5 py-1.5 rounded-lg text-xs font-medium text-zinc-400 hover:text-white transition-all cursor-pointer";
      loadDownloads();
    }
  }

  tabBtnDownloader.addEventListener("click", () => switchTab("downloader"));
  tabBtnSaved.addEventListener("click", () => switchTab("saved"));
  btnRefreshSavedTab.addEventListener("click", () => {
    loadDownloads();
    showToast("Daftar file diperbarui");
  });

  // ── Toast Notification ─────────────────────────────────────────────────
  function showToast(message) {
    if (toastTimer) clearTimeout(toastTimer);
    toastText.textContent = message;
    toast.classList.remove("hidden");
    toastTimer = setTimeout(() => {
      toast.classList.add("hidden");
    }, 3200);
  }

  // ── Utilities ──────────────────────────────────────────────────────────
  function showError(msg) {
    errorText.textContent = msg;
    errorBox.classList.remove("hidden");
    setTimeout(() => errorBox.classList.add("hidden"), 8000);
  }

  function formatBytes(bytes) {
    if (!bytes || bytes <= 0) return "0 B";
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
    if (bytes < 1024 * 1024 * 1024)
      return (bytes / (1024 * 1024)).toFixed(1) + " MB";
    return (bytes / (1024 * 1024 * 1024)).toFixed(2) + " GB";
  }

  function formatSpeed(bps) {
    if (bps <= 0) return "—";
    return formatBytes(bps) + "/s";
  }

  function formatETA(seconds) {
    if (seconds <= 0 || !isFinite(seconds)) return "—";
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    if (m > 0) return `${m}m ${s}s`;
    return `${s}s`;
  }

  function formatDate(epochSec) {
    const d = new Date(epochSec * 1000);
    const now = new Date();
    const diff = Math.floor((now - d) / 1000);
    if (diff < 60) return "baru saja";
    if (diff < 3600) return `${Math.floor(diff / 60)}m lalu`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}j lalu`;
    return d.toLocaleDateString("id-ID", {
      day: "numeric",
      month: "short",
      year: "numeric",
    });
  }

  function cleanQualityString(raw) {
    if (!raw) return "video";
    const match = raw.match(/(\d{3,4}p|4k|auto)/i);
    if (match) return match[1].toLowerCase();
    return raw.split("|")[0].trim().replace(/\s+/g, "_");
  }

  const statusLabels = {
    pending: "Menunggu...",
    fetching_playlist: "Mengambil playlist...",
    downloading: "Mengunduh segmen...",
    merging: "Menggabungkan ke MP4...",
    downloading_subtitles: "Mengunduh subtitle...",
    completed: "Selesai",
    failed: "Gagal",
    cancelled: "Dibatalkan",
  };

  // ── Inspect ────────────────────────────────────────────────────────────
  btnInspect.addEventListener("click", async () => {
    const url = inputUrl.value.trim();
    if (!url) {
      showError("Masukkan link FrameX atau TMDB/AniList ID.");
      inputUrl.focus();
      return;
    }

    errorBox.classList.add("hidden");
    loadingBox.classList.remove("hidden");
    btnInspect.disabled = true;
    btnInspect.textContent = "Memproses...";

    const body = { url };

    try {
      const resp = await fetch("/api/inspect", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await resp.json();

      loadingBox.classList.add("hidden");
      btnInspect.disabled = false;
      btnInspect.textContent = "Cek Link";

      if (!data.success) {
        showError(data.error || "Gagal mengambil informasi stream.");
        return;
      }

      inspectData = data;
      renderResults(data);
    } catch (err) {
      loadingBox.classList.add("hidden");
      btnInspect.disabled = false;
      btnInspect.textContent = "Cek Link";
      showError("Network error: " + err.message);
    }
  });

  inputUrl.addEventListener("keydown", (e) => {
    if (e.key === "Enter") btnInspect.click();
  });

  // ── Render Results ─────────────────────────────────────────────────────
  function renderResults(data) {
    resultsSection.classList.remove("hidden");

    // 1. Poster & Details
    const details = data.details || {};
    const title = details.title || data.default_title || `Media ${data.tmdb_id}`;
    currentBaseTitle = data.default_title || title;
    selectedEpisode = data.selected_episode || null;

    $("#media-title").textContent = title;

    // Type badge
    const typeMap = { movie: "Film", tv: "Serial TV", anime: "Anime" };
    $("#badge-media-type").textContent =
      typeMap[data.media_type] || data.media_type;

    // Year
    const year = details.year;
    const badgeYear = $("#badge-year");
    if (year) {
      badgeYear.textContent = year;
      badgeYear.classList.remove("hidden");
    } else {
      badgeYear.classList.add("hidden");
    }

    // Rating
    const badgeRating = $("#badge-rating");
    if (details.rating && parseFloat(details.rating) > 0) {
      $("#text-rating").textContent = parseFloat(details.rating).toFixed(1);
      badgeRating.classList.remove("hidden");
    } else {
      badgeRating.classList.add("hidden");
    }

    // Provider / Category
    $("#badge-provider").textContent = `kategori: ${data.media_type}`;

    // Poster
    const posterImg = $("#media-poster");
    const placeholder = $("#media-poster-placeholder");
    if (details.poster) {
      posterImg.src = details.poster;
      posterImg.classList.remove("hidden");
      placeholder.classList.add("hidden");
      posterImg.onerror = () => {
        posterImg.classList.add("hidden");
        placeholder.classList.remove("hidden");
      };
    } else {
      posterImg.classList.add("hidden");
      placeholder.classList.remove("hidden");
    }

    // Genres
    const genresContainer = $("#media-genres");
    genresContainer.innerHTML = "";
    if (details.genres && details.genres.length > 0) {
      details.genres.slice(0, 4).forEach((g) => {
        const span = document.createElement("span");
        span.className =
          "text-[10px] bg-zinc-800 text-zinc-300 px-2 py-0.5 rounded-full";
        span.textContent = g;
        genresContainer.appendChild(span);
      });
    }

    // Overview
    const overviewEl = $("#media-overview");
    if (details.overview) {
      overviewEl.textContent = details.overview;
      overviewEl.classList.remove("hidden");
    } else {
      overviewEl.classList.add("hidden");
    }

    // 2. Episode & Season Selector
    selectedSeason = data.selected_season || (details.seasons?.[0]?.season_number ?? 1);
    selectedEpisode = data.selected_episode || null;

    const seasons = (data.media_type === "tv" && details.seasons) ? details.seasons : [];
    const isTV = data.media_type === "tv";

    // Handle Season selector if TV has seasons
    if (isTV && seasons.length > 0) {
      seasonsContainer.classList.remove("hidden");
      renderSeasonsBar(seasons, selectedSeason);
    } else {
      seasonsContainer.classList.add("hidden");
    }

    // Determine total episodes for the active season
    let activeSeasonEpCount = data.total_episodes || 1;
    if (isTV && seasons.length > 0) {
      const curSeasonObj = seasons.find((s) => s.season_number === selectedSeason);
      if (curSeasonObj) {
        activeSeasonEpCount = curSeasonObj.episode_count;
      }
    }

    const isMultiEpisode = activeSeasonEpCount > 1 || seasons.length > 1;
    if (isMultiEpisode) {
      episodeSelectorCard.classList.remove("hidden");
      episodeCountBadge.textContent = isTV
        ? `Season ${selectedSeason}: ${activeSeasonEpCount} Episode`
        : `Total ${activeSeasonEpCount} Episode`;
      renderEpisodeGrid(activeSeasonEpCount, selectedEpisode);
    } else {
      episodeSelectorCard.classList.add("hidden");
    }

    // 3. Render Sources & Subtitles
    if (data.needs_episode_selection && (!data.sources || data.sources.length === 0)) {
      sourcesEmptyHint.textContent = isTV
        ? `Pilih nomor episode Season ${selectedSeason} di atas untuk memuat daftar server stream.`
        : "Pilih nomor episode di atas untuk memuat daftar server stream.";
      sourcesEmptyHint.classList.remove("hidden");
      sourcesList.innerHTML = "";
      activeProvidersCount.textContent = "Pilih episode";
      btnDownload.disabled = true;
      btnDownload.classList.add("opacity-50", "pointer-events-none");
      $("#subtitles-section").classList.add("hidden");
    } else {
      sourcesEmptyHint.classList.add("hidden");
      btnDownload.disabled = false;
      btnDownload.classList.remove("opacity-50", "pointer-events-none");
      renderSourcesAndSubtitles(data);
    }
  }

  // ── Render Seasons Bar ─────────────────────────────────────────────────
  function renderSeasonsBar(seasons, curSeason) {
    seasonsBar.innerHTML = "";
    seasons.forEach((s) => {
      const isCur = s.season_number === curSeason;
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = isCur
        ? "px-3 py-1.5 rounded-lg text-xs font-mono font-bold bg-indigo-600 text-white shadow-sm shadow-indigo-600/30 transition-all cursor-pointer whitespace-nowrap"
        : "px-3 py-1.5 rounded-lg text-xs font-mono bg-zinc-900 hover:bg-zinc-800 text-zinc-400 border border-zinc-800 hover:text-white transition-all cursor-pointer whitespace-nowrap";
      btn.textContent = `${s.name} (${s.episode_count} Ep)`;
      btn.addEventListener("click", () => switchSeason(s.season_number, s.episode_count));
      seasonsBar.appendChild(btn);
    });
  }

  // ── Switch Season ──────────────────────────────────────────────────────
  function switchSeason(seasonNum, epCount) {
    selectedSeason = seasonNum;
    selectedEpisode = null;

    if (inspectData && inspectData.details && inspectData.details.seasons) {
      renderSeasonsBar(inspectData.details.seasons, selectedSeason);
    }

    episodeCountBadge.textContent = `Season ${selectedSeason}: ${epCount} Episode`;
    renderEpisodeGrid(epCount, null);

    sourcesEmptyHint.textContent = `Pilih nomor episode Season ${selectedSeason} di atas untuk memuat daftar server stream.`;
    sourcesEmptyHint.classList.remove("hidden");
    sourcesList.innerHTML = "";
    activeProvidersCount.textContent = "Pilih episode";
    btnDownload.disabled = true;
    btnDownload.classList.add("opacity-50", "pointer-events-none");
    $("#subtitles-section").classList.add("hidden");
  }

  // ── Render Episode Grid ────────────────────────────────────────────────
  function renderEpisodeGrid(total, activeEp) {
    episodesGrid.innerHTML = "";
    for (let i = 1; i <= total; i++) {
      const isCur = activeEp === i;
      const btn = document.createElement("button");
      btn.type = "button";
      btn.dataset.ep = i;
      btn.className = isCur
        ? "ep-btn px-2 py-1.5 min-h-[34px] rounded-lg text-xs font-mono font-bold bg-rose-600 text-white shadow-md shadow-rose-600/30 transition-all cursor-pointer"
        : "ep-btn px-2 py-1.5 min-h-[34px] rounded-lg text-xs font-mono bg-zinc-900 hover:bg-zinc-800 text-zinc-400 border border-zinc-800 hover:text-white transition-all cursor-pointer";
      btn.textContent = `EP ${i}`;
      btn.addEventListener("click", () => selectEpisode(i));
      episodesGrid.appendChild(btn);
    }
  }

  // ── Select Episode Event (NON-BLOCKING: keeps downloads running) ───────
  async function selectEpisode(epNum) {
    if (!inspectData) return;
    selectedEpisode = epNum;

    // Highlight button
    document.querySelectorAll(".ep-btn").forEach((btn) => {
      const isCurrent = parseInt(btn.dataset.ep, 10) === epNum;
      btn.className = isCurrent
        ? "ep-btn px-2 py-1.5 min-h-[34px] rounded-lg text-xs font-mono font-bold bg-rose-600 text-white shadow-md shadow-rose-600/30 transition-all cursor-pointer"
        : "ep-btn px-2 py-1.5 min-h-[34px] rounded-lg text-xs font-mono bg-zinc-900 hover:bg-zinc-800 text-zinc-400 border border-zinc-800 hover:text-white transition-all cursor-pointer";
    });

    sourcesLoading.classList.remove("hidden");
    sourcesEmptyHint.classList.add("hidden");
    sourcesList.innerHTML = "";
    activeProvidersCount.textContent = "Memeriksa...";
    btnDownload.disabled = true;
    btnDownload.classList.add("opacity-50", "pointer-events-none");

    try {
      const body = {
        url: inputUrl.value.trim(),
        episode: epNum,
      };
      if (inspectData.media_type === "tv" && selectedSeason !== null) {
        body.season = selectedSeason;
      }
      const resp = await fetch("/api/inspect", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await resp.json();

      sourcesLoading.classList.add("hidden");

      if (!data.success) {
        showError(data.error || `Gagal mengambil stream untuk Episode ${epNum}.`);
        return;
      }

      inspectData.sources = data.sources;
      inspectData.subtitles = data.subtitles;
      inspectData.default_title = data.default_title;
      currentBaseTitle = data.default_title;

      btnDownload.disabled = false;
      btnDownload.classList.remove("opacity-50", "pointer-events-none");

      renderSourcesAndSubtitles(data);
      const epLabel = (inspectData.media_type === "tv" && selectedSeason !== null)
        ? `Season ${selectedSeason} Episode ${epNum}`
        : `Episode ${epNum}`;
      showToast(`${epLabel} dimuat: ${data.sources.length} server aktif.`);
    } catch (err) {
      sourcesLoading.classList.add("hidden");
      showError("Network error: " + err.message);
    }
  }

  // ── Render Sources & Subtitles ─────────────────────────────────────────
  function renderSourcesAndSubtitles(data) {
    sourcesList.innerHTML = "";
    activeProvidersCount.textContent = `${data.sources.length} server aktif`;

    function updateFilenameForSource(src) {
      const cleanQ = cleanQualityString(src.quality);
      inputFilename.value = `${currentBaseTitle} [${cleanQ}]`;
    }

    data.sources.forEach((src, i) => {
      const id = `source-${i}`;
      const div = document.createElement("div");
      div.className =
        "check-item flex items-center space-x-3 px-3.5 py-2.5 rounded-lg cursor-pointer border border-zinc-800/80 bg-zinc-950 hover:border-zinc-700 transition-all";

      const audioBadge = src.audio
        ? `<span class="text-[9px] font-mono font-bold uppercase px-1.5 py-0.5 rounded ${src.audio === 'dub' ? 'bg-amber-500/20 text-amber-300 border border-amber-500/30' : 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'}">${src.audio}</span>`
        : "";

      div.innerHTML = `
        <input type="radio" name="source" id="${id}" value="${i}" class="accent-indigo-500 w-3.5 h-3.5 cursor-pointer" ${i === 0 ? "checked" : ""}>
        <label for="${id}" class="flex-1 cursor-pointer flex items-center justify-between">
          <div class="flex items-center space-x-2">
            <span class="text-sm font-semibold text-white">${src.quality}</span>
            <span class="text-xs text-zinc-400 font-medium">${src.server}</span>
            ${audioBadge}
          </div>
          <span class="text-[10px] text-zinc-500 mono uppercase px-1.5 py-0.5 rounded bg-zinc-900 border border-zinc-800">${src.type}</span>
        </label>
      `;

      div.addEventListener("click", () => {
        const radio = div.querySelector("input");
        radio.checked = true;
        updateFilenameForSource(src);
      });

      sourcesList.appendChild(div);
    });

    if (data.sources.length > 0) {
      updateFilenameForSource(data.sources[0]);
    } else {
      inputFilename.value = currentBaseTitle;
    }

    // Subtitles
    const subsList = $("#subtitles-list");
    subsList.innerHTML = "";
    const subsSection = $("#subtitles-section");
    if (!data.subtitles || data.subtitles.length === 0) {
      subsSection.classList.add("hidden");
    } else {
      subsSection.classList.remove("hidden");
      data.subtitles.forEach((sub, i) => {
        const id = `sub-${i}`;
        const div = document.createElement("div");
        div.className =
          "check-item flex items-center space-x-2 px-2.5 py-1.5 rounded-lg cursor-pointer border border-transparent hover:border-zinc-800";
        div.innerHTML = `
          <input type="checkbox" id="${id}" value="${i}" class="accent-indigo-500 w-3 h-3 cursor-pointer" ${sub.is_default ? "checked" : ""}>
          <label for="${id}" class="text-xs text-zinc-300 cursor-pointer truncate flex-1">${sub.label}</label>
          <span class="text-[9px] text-zinc-600 uppercase font-mono">${sub.format}</span>
        `;
        div.addEventListener("click", (e) => {
          if (e.target.tagName !== "INPUT") {
            const cb = div.querySelector("input");
            cb.checked = !cb.checked;
          }
        });
        subsList.appendChild(div);
      });
    }

    allSubsSelected = false;
  }

  // Toggle all subtitles
  btnSelectAllSubs.addEventListener("click", () => {
    allSubsSelected = !allSubsSelected;
    document
      .querySelectorAll('#subtitles-list input[type="checkbox"]')
      .forEach((cb) => (cb.checked = allSubsSelected));
  });

  // ── Start Download (NON-BLOCKING: Stays on page so user can pick next EP) ─
  btnDownload.addEventListener("click", async () => {
    if (!inspectData) return;

    const selectedSource = document.querySelector('input[name="source"]:checked');
    if (!selectedSource) {
      showError("Pilih salah satu sumber resolusi/provider.");
      return;
    }

    const checkedSubs = [
      ...document.querySelectorAll('#subtitles-list input[type="checkbox"]:checked'),
    ].map((cb) => parseInt(cb.value, 10));

    const filename = inputFilename.value.trim();

    const body = {
      url: inputUrl.value.trim(),
      source_index: parseInt(selectedSource.value, 10),
      subtitle_indices: checkedSubs,
      filename: filename,
    };

    if (selectedEpisode !== null) {
      body.episode = selectedEpisode;
    }
    if (inspectData && inspectData.media_type === "tv" && selectedSeason !== null) {
      body.season = selectedSeason;
    }

    btnDownload.disabled = true;
    btnDownloadText.textContent = "Mempersiapkan...";

    try {
      const resp = await fetch("/api/download", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });

      if (!resp.ok) {
        const err = await resp.json();
        throw new Error(err.detail || "Download request failed");
      }

      const data = await resp.json();

      // Non-blocking notification
      showToast(`Download dimulai: ${filename || "Film/Episode"}`);
      btnDownloadText.textContent = "✓ Download Dimulai!";

      // Re-enable download button after 1.5 seconds so user can immediately download next episode
      setTimeout(() => {
        btnDownload.disabled = false;
        btnDownloadText.textContent = "Mulai Download Sekarang";
      }, 1500);

      // Start task tracking widget (without hiding the page!)
      createTaskTracker(data.task_id, filename || currentBaseTitle);

    } catch (err) {
      showError("Error: " + err.message);
      btnDownload.disabled = false;
      btnDownloadText.textContent = "Mulai Download Sekarang";
    }
  });

  // ── Non-Blocking Active Task Widget ────────────────────────────────────
  function createTaskTracker(taskId, title) {
    activeDownloadsCard.classList.remove("hidden");

    const taskCard = document.createElement("div");
    taskCard.id = `task-card-${taskId}`;
    taskCard.className =
      "bg-zinc-900/90 border border-zinc-800 rounded-xl p-4 space-y-3 fade-in";

    taskCard.innerHTML = `
      <div class="flex items-center justify-between">
        <div class="flex items-center space-x-2.5 min-w-0 mr-2">
          <div class="task-indicator w-2 h-2 rounded-full bg-indigo-400 animate-pulse shrink-0"></div>
          <span class="text-xs font-bold text-white truncate max-w-sm sm:max-w-md">${title}</span>
        </div>
        <div class="flex items-center space-x-2 shrink-0">
          <span class="task-status text-[10px] font-mono uppercase font-semibold text-zinc-400">Memulai...</span>
          <button onclick="window.StreamDown.cancelTask('${taskId}')" class="task-cancel-btn text-xs text-red-400 hover:text-red-300 font-mono transition-colors cursor-pointer ml-1">Batal</button>
        </div>
      </div>

      <!-- Progress Bar -->
      <div class="w-full bg-zinc-800 rounded-full h-2 overflow-hidden">
        <div class="task-bar h-full bg-gradient-to-r from-indigo-600 to-indigo-400 rounded-full transition-all" style="width: 0%"></div>
      </div>

      <!-- Stats row -->
      <div class="flex items-center justify-between text-[11px] font-mono text-zinc-400">
        <span class="task-percent font-bold text-white">0%</span>
        <span class="task-speed text-zinc-500">—</span>
        <span class="task-eta text-zinc-500">—</span>
        <span class="task-segments text-zinc-500">0/0</span>
      </div>

      <!-- Actions on completion (hidden initially) -->
      <div class="task-actions hidden flex items-center justify-between pt-2 border-t border-zinc-800/80">
        <span class="text-xs text-emerald-400 font-medium flex items-center space-x-1">
          <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
          <span>Selesai diunduh!</span>
        </span>
        <div class="flex items-center space-x-2">
          <button onclick="window.StreamDown.openSavedTab()" class="px-2.5 py-1 text-xs bg-zinc-800 hover:bg-zinc-700 text-zinc-300 rounded transition-colors cursor-pointer">Lihat di File Tersimpan</button>
          <a class="task-dl-btn px-3 py-1 text-xs bg-indigo-600 hover:bg-indigo-500 text-white font-medium rounded transition-colors" href="#" download>Unduh</a>
        </div>
      </div>
    `;

    activeTasksList.prepend(taskCard);
    updateActiveTasksCount();

    // Start SSE stream for this task
    const es = new EventSource(`/api/progress/${taskId}`);
    activeEventSources.set(taskId, es);

    es.onmessage = (event) => {
      const d = JSON.parse(event.data);
      if (d.error && !d.status) {
        es.close();
        activeEventSources.delete(taskId);
        taskCard.querySelector(".task-status").textContent = "Gagal";
        taskCard.querySelector(".task-status").classList.add("text-red-400");
        return;
      }

      // Update UI in widget
      const statusText = statusLabels[d.status] || d.status;
      taskCard.querySelector(".task-status").textContent = statusText;
      taskCard.querySelector(".task-bar").style.width = d.percent + "%";
      taskCard.querySelector(".task-percent").textContent = d.percent.toFixed(1) + "%";
      taskCard.querySelector(".task-speed").textContent = formatSpeed(d.speed_bps);
      taskCard.querySelector(".task-eta").textContent = formatETA(d.eta_seconds);
      taskCard.querySelector(".task-segments").textContent =
        d.downloaded_segments + "/" + d.total_segments;

      if (d.status === "completed") {
        es.close();
        activeEventSources.delete(taskId);
        taskCard.querySelector(".task-indicator").classList.replace("bg-indigo-400", "bg-emerald-400");
        taskCard.querySelector(".task-indicator").classList.remove("animate-pulse");
        taskCard.querySelector(".task-bar").className = "task-bar h-full bg-emerald-500 rounded-full";
        taskCard.querySelector(".task-status").textContent = "Selesai";
        taskCard.querySelector(".task-status").classList.add("text-emerald-400");
        taskCard.querySelector(".task-cancel-btn").classList.add("hidden");

        const actions = taskCard.querySelector(".task-actions");
        actions.classList.remove("hidden");
        if (d.output_file) {
          actions.querySelector(".task-dl-btn").href = `/api/files/${encodeURIComponent(d.output_file)}`;
        }

        updateActiveTasksCount();
        loadDownloads();
        showToast(`Selesai diunduh: ${d.filename || "File"}`);

      } else if (d.status === "failed") {
        es.close();
        activeEventSources.delete(taskId);
        taskCard.querySelector(".task-status").textContent = "Gagal";
        taskCard.querySelector(".task-status").classList.add("text-red-400");
        taskCard.querySelector(".task-indicator").classList.replace("bg-indigo-400", "bg-red-400");
        updateActiveTasksCount();

      } else if (d.status === "cancelled") {
        es.close();
        activeEventSources.delete(taskId);
        taskCard.querySelector(".task-status").textContent = "Dibatalkan";
        taskCard.querySelector(".task-status").classList.add("text-zinc-500");
        taskCard.querySelector(".task-indicator").classList.replace("bg-indigo-400", "bg-zinc-600");
        updateActiveTasksCount();
      }
    };

    es.onerror = () => {
      es.close();
      activeEventSources.delete(taskId);
      updateActiveTasksCount();
    };
  }

  function updateActiveTasksCount() {
    const running = activeEventSources.size;
    activeTasksCount.textContent = `${running} berjalan`;
    if (activeTasksList.children.length === 0) {
      activeDownloadsCard.classList.add("hidden");
    }
  }

  // ── Downloads Manager (List, Search & Delete) ──────────────────────────
  async function loadDownloads() {
    try {
      const resp = await fetch("/api/downloads");
      const files = await resp.json();
      cachedSavedFiles = files;

      navDownloadsCount.textContent = files.length;
      renderSavedFilesList(files);
    } catch (err) {
      console.warn("Failed to load downloads:", err);
    }
  }

  function renderSavedFilesList(files) {
    const totalBytes = files.reduce((acc, f) => acc + (f.size_bytes || 0), 0);
    savedSummary.textContent = `${files.length} file (${formatBytes(totalBytes)})`;

    if (files.length === 0) {
      downloadsList.innerHTML = `
        <div class="py-12 text-center text-zinc-500 space-y-2">
          <svg class="w-8 h-8 mx-auto opacity-50" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M20.25 7.5l-.625 10.632a2.25 2.25 0 01-2.247 2.118H6.622a2.25 2.25 0 01-2.247-2.118L3.75 7.5M10 11.25h4M3.375 7.5h17.25c.621 0 1.125-.504 1.125-1.125v-1.5c0-.621-.504-1.125-1.125-1.125H3.375c-.621 0-1.125.504-1.125 1.125v1.5c0 .621.504 1.125 1.125 1.125z"/></svg>
          <p class="text-xs">Belum ada file di folder downloads.</p>
        </div>
      `;
      return;
    }

    downloadsList.innerHTML = "";
    files.forEach((f) => {
      const isVideo = f.ext === "mp4" || f.ext === "mkv";
      const iconColor = isVideo ? "text-indigo-400" : "text-yellow-400";
      const icon = isVideo
        ? `<svg class="w-5 h-5 ${iconColor} shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M15.75 10.5l4.72-4.72a.75.75 0 011.28.53v11.38a.75.75 0 01-1.28.53l-4.72-4.72M4.5 18.75h9a2.25 2.25 0 002.25-2.25v-9a2.25 2.25 0 00-2.25-2.25h-9A2.25 2.25 0 002.25 7.5v9a2.25 2.25 0 002.25 2.25z"/></svg>`
        : `<svg class="w-5 h-5 ${iconColor} shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z"/></svg>`;

      const div = document.createElement("div");
      div.className =
        "flex items-center justify-between px-3.5 py-2.5 bg-zinc-900 border border-zinc-800 rounded-lg hover:border-zinc-700/80 transition-all";
      div.innerHTML = `
        <div class="flex items-center space-x-3 min-w-0 mr-3">
          ${icon}
          <div class="min-w-0">
            <p class="text-xs font-semibold text-white truncate max-w-[260px] sm:max-w-md">${f.filename}</p>
            <div class="flex items-center space-x-2 text-[10px] text-zinc-500 font-mono mt-0.5">
              <span>${formatBytes(f.size_bytes)}</span>
              <span>&bull;</span>
              <span>${formatDate(f.modified_at)}</span>
            </div>
          </div>
        </div>
        <div class="flex items-center space-x-1.5 shrink-0">
          <a href="${f.url}" download class="px-2.5 py-1 text-xs bg-indigo-600/90 hover:bg-indigo-500 text-white font-medium rounded transition-colors cursor-pointer flex items-center space-x-1">
            <svg class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3"/></svg>
            <span>Unduh</span>
          </a>
          <button onclick="window.StreamDown.copyLink('${f.url}')" class="px-2.5 py-1 text-xs bg-zinc-800 hover:bg-zinc-700 text-zinc-300 rounded transition-colors cursor-pointer flex items-center space-x-1">
            <svg class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"/></svg>
            <span>Salin</span>
          </button>
          <button onclick="window.StreamDown.deleteFile('${encodeURIComponent(f.filename)}')" class="p-1 text-xs text-zinc-500 hover:text-red-400 hover:bg-red-500/10 rounded transition-colors cursor-pointer" title="Hapus file">
            <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/></svg>
          </button>
        </div>
      `;
      downloadsList.appendChild(div);
    });
  }

  // Filter search
  searchSavedFiles.addEventListener("input", (e) => {
    const q = e.target.value.toLowerCase().trim();
    if (!q) {
      renderSavedFilesList(cachedSavedFiles);
      return;
    }
    const filtered = cachedSavedFiles.filter((f) =>
      f.filename.toLowerCase().includes(q)
    );
    renderSavedFilesList(filtered);
  });

  // Global namespace for inline onclick handlers
  window.StreamDown = {
    openSavedTab: () => {
      switchTab("saved");
    },

    cancelTask: async (taskId) => {
      try {
        await fetch(`/api/cancel/${taskId}`, { method: "POST" });
        const es = activeEventSources.get(taskId);
        if (es) {
          es.close();
          activeEventSources.delete(taskId);
        }
        updateActiveTasksCount();
        showToast("Unduhan dibatalkan.");
      } catch (err) {
        console.warn("Cancel task failed:", err);
      }
    },

    copyLink: (relativeUrl) => {
      const fullUrl = window.location.origin + relativeUrl;
      navigator.clipboard.writeText(fullUrl).then(() => {
        showToast("Link unduhan berhasil disalin!");
      });
    },

    deleteFile: async (encodedFilename) => {
      const filename = decodeURIComponent(encodedFilename);
      if (!confirm(`Hapus permanen file ini?\n\n${filename}`)) {
        return;
      }
      try {
        const resp = await fetch(`/api/files/${encodedFilename}`, {
          method: "DELETE",
        });
        if (resp.ok) {
          showToast(`File ${filename} berhasil dihapus.`);
          loadDownloads();
        } else {
          const err = await resp.json();
          showError("Gagal menghapus file: " + (err.detail || "Unknown error"));
        }
      } catch (err) {
        showError("Network error saat menghapus file: " + err.message);
      }
    },
  };

  // Initial load
  loadDownloads();
})();
