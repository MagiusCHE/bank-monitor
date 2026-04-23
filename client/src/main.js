// Bank Monitor - frontend
// Stato globale
const state = {
  serverUrl: "",
  accounts: [],         // [{id, account_number, holder_name, initial_balance, ...}]
  selectedIds: new Set(),
  view: "cumulative",   // cumulative | per-account | groups
  includeAuthorized: false,
  excludeTrading: true,
  dateFrom: "",
  dateTo: "",
  // Canonical (ultima versione letta dal server)
  rules: [],
  groups: [],
  // Working copy editabile (cambia quando l'utente edita la tabella)
  rulesWorking: [],
  groupsWorking: [],
  rulesDirty: false,
  groupsDirty: false,
  theme: "system",
};

let chart = null;
const TRASH_ICON = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/></svg>';
const SAVE_ICON = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg>';
const RESET_ICON = '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/></svg>';
const txCache = new Map(); // key = `${date}|${accountsCsv}|${includeAuth}` -> [transactions]
const txPending = new Set(); // richieste in corso

// -------- Tauri bindings (con fallback per browser puro) --------
const hasTauri = typeof window.__TAURI__ !== "undefined";

async function tauriInvoke(cmd, args) {
  if (!hasTauri) return null;
  return await window.__TAURI__.core.invoke(cmd, args || {});
}

async function tauriDialogOpen(options) {
  if (!hasTauri) return null;
  const m = window.__TAURI__.dialog || window.__TAURI__.plugin?.dialog;
  if (!m || !m.open) return null;
  return await m.open(options);
}

// -------- Tema --------
const THEME_ICONS = { system: "◐", light: "☀️", dark: "🌙" };
const THEME_CYCLE = ["system", "light", "dark"];

function effectiveTheme(theme) {
  if (theme === "system") {
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  return theme;
}

function applyTheme(theme) {
  state.theme = theme;
  document.documentElement.setAttribute("data-theme", effectiveTheme(theme));
  const btn = document.querySelector("#theme-toggle");
  if (btn) {
    btn.textContent = THEME_ICONS[theme] || THEME_ICONS.system;
    btn.title = `Tema: ${theme === "system" ? "sistema" : theme === "light" ? "chiaro" : "scuro"}`;
  }
}

// -------- Config persistente --------
async function loadConfig() {
  let theme = "system";
  if (hasTauri) {
    try {
      const cfg = await tauriInvoke("get_config");
      if (cfg) {
        state.serverUrl = cfg.server_url || "";
        theme = cfg.theme || "system";
        applyTheme(theme);
        return;
      }
    } catch (e) { console.warn("get_config:", e); }
  }
  state.serverUrl = localStorage.getItem("bank-monitor.serverUrl") || "";
  theme = localStorage.getItem("bank-monitor.theme") || "system";
  applyTheme(theme);
}

async function saveConfig() {
  if (hasTauri) {
    try {
      await tauriInvoke("set_config", {
        serverUrl: state.serverUrl,
        theme: state.theme || "system",
      });
      return;
    } catch (e) { console.warn("set_config:", e); }
  }
  localStorage.setItem("bank-monitor.serverUrl", state.serverUrl);
  localStorage.setItem("bank-monitor.theme", state.theme || "system");
}

// -------- API client --------
function apiUrl(path) {
  const base = (state.serverUrl || "").replace(/\/+$/, "");
  return base + path;
}

async function apiGet(path) {
  const r = await fetch(apiUrl(path), { method: "GET" });
  if (!r.ok) throw new Error(`HTTP ${r.status}: ${await r.text()}`);
  return await r.json();
}

async function apiPost(path, body) {
  const r = await fetch(apiUrl(path), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}: ${await r.text()}`);
  return await r.json();
}

async function apiDelete(path) {
  const r = await fetch(apiUrl(path), { method: "DELETE" });
  if (!r.ok) throw new Error(`HTTP ${r.status}: ${await r.text()}`);
  return await r.json();
}

async function apiPut(path, body) {
  const r = await fetch(apiUrl(path), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}: ${await r.text()}`);
  return await r.json();
}

async function apiUpload(file) {
  const fd = new FormData();
  fd.append("file", file);
  const r = await fetch(apiUrl("/api/upload"), { method: "POST", body: fd });
  if (!r.ok) throw new Error(`HTTP ${r.status}: ${await r.text()}`);
  return await r.json();
}

// -------- UI helpers --------
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

function setStatus(msg, cls = "") {
  const el = $("#status-msg");
  el.textContent = msg || "";
  el.className = "status-msg" + (cls ? " " + cls : "");
}

function fmtEur(n) {
  if (n == null || isNaN(n)) return "-";
  return new Intl.NumberFormat("it-IT", {
    style: "currency", currency: "EUR", minimumFractionDigits: 2,
  }).format(n);
}

function fmtItDate(iso) {
  if (!iso) return "";
  const d = new Date(iso + "T00:00:00");
  return new Intl.DateTimeFormat("it-IT", { day: "2-digit", month: "short", year: "numeric" }).format(d);
}

// Estrae "HH:MM" dalla descrizione Fineco quando presente (es. "Pag. del 20/04/26 ora 08:02 presso...")
function extractTimeFromDesc(s) {
  if (!s) return null;
  const m = s.match(/\b(?:ora|ore|h\.?)\s*(\d{1,2}[:\.]\d{2})/i) || s.match(/\b(\d{1,2}:\d{2})(?::\d{2})?\b/);
  if (!m) return null;
  return m[1].replace(".", ":");
}

function txCacheKey(date) {
  const ids = state.selectedIds.size < state.accounts.length
    ? [...state.selectedIds].sort().join(",") : "all";
  return `${date}|${ids}|${state.includeAuthorized ? 1 : 0}|${state.excludeTrading ? 1 : 0}`;
}

function prefetchTransactions(date) {
  const key = txCacheKey(date);
  if (txCache.has(key) || txPending.has(key)) return;
  txPending.add(key);
  const params = new URLSearchParams({ date });
  if (state.selectedIds.size < state.accounts.length) {
    params.set("accounts", [...state.selectedIds].join(","));
  }
  if (state.includeAuthorized) params.set("include_authorized", "true");
  if (state.excludeTrading) params.set("exclude_trading", "true");
  fetch(apiUrl(`/api/transactions?${params.toString()}`))
    .then(r => r.ok ? r.json() : [])
    .then(list => {
      txCache.set(key, list);
      txPending.delete(key);
      // Se il tooltip è ancora aperto su questa data, aggiorna
      if (chart && chart.tooltip && chart.tooltip.getActiveElements().length > 0) {
        chart.update("none");
      }
    })
    .catch(() => { txPending.delete(key); });
}

function getCachedTransactions(date) {
  return txCache.get(txCacheKey(date));
}

// -------- Settings --------
function openSettings() {
  $("#server-url-input").value = state.serverUrl;
  $("#test-connection-status").textContent = "";
  $("#settings-panel").classList.remove("hidden");
  renderSettingsAccounts();
}

function renderSettingsAccounts() {
  const tbody = $("#settings-accounts-table tbody");
  if (!tbody) return;
  tbody.innerHTML = "";
  if (!state.accounts || state.accounts.length === 0) {
    tbody.innerHTML = '<tr><td colspan="5" class="hint">Nessun conto caricato</td></tr>';
    return;
  }
  for (const a of state.accounts) {
    const tr = document.createElement("tr");
    const period = (a.first_tx && a.last_tx)
      ? `${fmtItDate(a.first_tx)} → ${fmtItDate(a.last_tx)}`
      : "-";
    tr.innerHTML = `
      <td>${escHtml(a.holder_name)}</td>
      <td>${escHtml(a.account_number)}</td>
      <td>${a.transaction_count}</td>
      <td class="date-col">${period}</td>
      <td>
        <button class="icon-btn danger" title="Elimina conto" aria-label="Elimina">${TRASH_ICON}</button>
      </td>
    `;
    tr.querySelector("button").onclick = async () => {
      const msg = `Eliminare il conto ${a.account_number} (${a.holder_name})?\n\n` +
                  `Verranno cancellati DEFINITIVAMENTE ${a.transaction_count} movimenti dal server.\n` +
                  `Questa operazione non può essere annullata.`;
      if (!confirm(msg)) return;
      try {
        await apiDelete(`/api/accounts/${a.id}`);
        state.selectedIds.delete(a.id);
        setStatus(`Conto ${a.account_number} eliminato`, "ok");
        await refreshAll();
        renderSettingsAccounts();
      } catch (err) {
        setStatus("Errore eliminazione: " + err.message, "err");
      }
    };
    tbody.appendChild(tr);
  }
}

function closeSettings() {
  $("#settings-panel").classList.add("hidden");
}

function toggleSettings() {
  if ($("#settings-panel").classList.contains("hidden")) openSettings();
  else closeSettings();
}

async function testConnection() {
  const url = $("#server-url-input").value.trim();
  if (!url) { $("#test-connection-status").textContent = "URL mancante"; return; }
  $("#test-connection-status").textContent = "Connessione in corso...";
  try {
    const prev = state.serverUrl;
    state.serverUrl = url;
    const r = await apiGet("/api/health");
    state.serverUrl = prev;
    if (r.status === "ok") $("#test-connection-status").textContent = "✓ OK";
    else $("#test-connection-status").textContent = "Risposta inattesa";
  } catch (e) {
    $("#test-connection-status").textContent = "✗ " + e.message;
  }
}

async function saveSettings() {
  const url = $("#server-url-input").value.trim();
  state.serverUrl = url;
  await saveConfig();
  closeSettings();
  await refreshAll();
}

// -------- Accounts --------
async function reloadAccounts() {
  if (!state.serverUrl) return;
  state.accounts = await apiGet("/api/accounts");
  // se nessun conto è selezionato, seleziono tutti
  if (state.selectedIds.size === 0) {
    state.accounts.forEach(a => state.selectedIds.add(a.id));
  } else {
    // rimuovo id che non esistono più
    const existing = new Set(state.accounts.map(a => a.id));
    [...state.selectedIds].forEach(id => { if (!existing.has(id)) state.selectedIds.delete(id); });
  }
  renderAccountPicker();
  syncDateInputs();
}

function syncDateInputs() {
  // Calcola range min/max reale dei conti selezionati (o di tutti)
  const pool = state.accounts.filter(a => state.selectedIds.has(a.id));
  const source = pool.length > 0 ? pool : state.accounts;
  const firsts = source.map(a => a.first_tx).filter(Boolean);
  const lasts = source.map(a => a.last_tx).filter(Boolean);
  const minDate = firsts.length ? firsts.reduce((a, b) => a < b ? a : b) : "";
  const maxDate = lasts.length ? lasts.reduce((a, b) => a > b ? a : b) : "";

  const fromEl = $("#date-from");
  const toEl = $("#date-to");
  fromEl.min = minDate || "";
  fromEl.max = maxDate || "";
  toEl.min = minDate || "";
  toEl.max = maxDate || "";
  // Primo caricamento: default ultimi 12 mesi (o tutto il range se più corto)
  if (!state.dateTo) {
    state.dateTo = maxDate || "";
    toEl.value = state.dateTo;
  }
  if (!state.dateFrom) {
    const defaultFrom = minusOneYear(state.dateTo);
    state.dateFrom = (minDate && defaultFrom < minDate) ? minDate : defaultFrom;
    fromEl.value = state.dateFrom;
  }
}

function minusOneYear(isoDate) {
  if (!isoDate) return "";
  const d = new Date(isoDate + "T00:00:00");
  d.setFullYear(d.getFullYear() - 1);
  return d.toISOString().slice(0, 10);
}

function renderAccountPicker() {
  const host = $("#account-picker");
  host.innerHTML = "";
  if (state.accounts.length === 0) {
    host.innerHTML = '<span class="hint">Nessun conto. Carica un file per iniziare.</span>';
    return;
  }
  state.accounts.forEach(a => {
    const chip = document.createElement("span");
    chip.className = "account-chip" + (state.selectedIds.has(a.id) ? " active" : "");
    chip.title = `${a.holder_name} — ${a.account_number}\n${a.transaction_count} movimenti`;
    const label = document.createElement("span");
    label.textContent = `${a.holder_name} (${a.account_number})`;
    chip.appendChild(label);

    chip.onclick = () => {
      if (state.selectedIds.has(a.id)) state.selectedIds.delete(a.id);
      else state.selectedIds.add(a.id);
      txCache.clear();
      renderAccountPicker();
      syncDateInputs();
      refreshChart();
    };
    host.appendChild(chip);
  });
}

// -------- Upload --------
async function doUpload() {
  if (!state.serverUrl) {
    setStatus("Configura prima l'indirizzo del server", "err");
    openSettings();
    return;
  }
  $("#file-input").click();
}

async function onFileSelected(e) {
  const file = e.target.files[0];
  if (!file) return;
  e.target.value = "";
  setStatus(`Caricamento ${file.name}...`);
  try {
    const res = await apiUpload(file);
    const msg = res.created_account
      ? `Conto ${res.account.account_number} creato. ${res.inserted} movimenti inseriti.`
      : `${res.inserted} nuovi movimenti (${res.skipped_duplicates} già presenti).`;
    setStatus(msg, "ok");
    showUploadResult(res);
    await refreshAll();
  } catch (err) {
    setStatus("Upload fallito: " + err.message, "err");
  }
}

function showUploadResult(res) {
  const host = $("#upload-result");
  host.classList.remove("hidden");
  host.innerHTML = `
    <h2>Risultato caricamento</h2>
    <table>
      <tr><td>Template</td><td>${res.template}</td></tr>
      <tr><td>Conto</td><td>${res.account.account_number} — ${res.account.holder_name}</td></tr>
      <tr><td>Periodo file</td><td>${res.period_from || "?"} → ${res.period_to || "?"}</td></tr>
      <tr><td>Saldo iniziale</td><td>${fmtEur(res.account.initial_balance)} (dal ${res.account.initial_balance_date || "?"})</td></tr>
      <tr><td>Movimenti nel file</td><td>${res.total_in_file}</td></tr>
      <tr><td>Nuovi inseriti</td><td class="value-positive">${res.inserted}</td></tr>
      <tr><td>Duplicati ignorati</td><td>${res.skipped_duplicates}</td></tr>
      <tr><td>Conto creato</td><td>${res.created_account ? "sì" : "no"}</td></tr>
      <tr><td>Saldo iniziale aggiornato</td><td>${res.initial_balance_updated ? "sì" : "no"}</td></tr>
    </table>
  `;
  setTimeout(() => host.classList.add("hidden"), 15000);
}

// -------- Chart --------
function queryArgs() {
  const params = new URLSearchParams();
  // Se l'utente ha deselezionato alcuni (o tutti) i conti passo la lista esatta.
  // Omesso solo quando TUTTI i conti sono selezionati (server default = tutti).
  if (state.selectedIds.size < state.accounts.length) {
    params.set("accounts", [...state.selectedIds].join(","));
  }
  if (state.includeAuthorized) params.set("include_authorized", "true");
  if (state.excludeTrading) params.set("exclude_trading", "true");
  if (state.dateFrom) params.set("date_from", state.dateFrom);
  if (state.dateTo) params.set("date_to", state.dateTo);
  const s = params.toString();
  return s ? ("?" + s) : "";
}

async function refreshChart() {
  if (!state.serverUrl) { showChart(false); return; }
  if (state.accounts.length === 0) { showChart(false); return; }

  // Vista "groups" mostra il pannello CRUD gruppi + bar chart dei gruppi
  if (state.view === "groups") {
    $("#groups-panel").classList.remove("hidden");
    await renderBarChart();
    // Se la sezione "non classificate" è aperta la aggiorno coi filtri correnti
    if ($("#section-untagged").open) loadUntagged();
    return;
  } else {
    $("#groups-panel").classList.add("hidden");
    closeDrill();
  }

  await renderLineChart();
}

function showChart(visible) {
  $("#chart-section").classList.toggle("hidden", !visible);
}

function setTabsVisible(visible) {
  $(".view-tabs").classList.toggle("hidden", !visible);
}

async function renderLineChart() {
  const mode = state.view === "per-account" ? "per-account" : "cumulative";
  const q = queryArgs();
  const sep = q ? "&" : "?";
  const url = `/api/series${q}${sep}mode=${mode}`;
  let data;
  try { data = await apiGet(url); }
  catch (e) { setStatus("Errore caricamento serie: " + e.message, "err"); showChart(false); return; }

  const datasets = [];
  if (data.mode === "cumulative") {
    datasets.push({
      label: "Saldo totale",
      data: data.points.map(p => ({ x: p.date, y: p.balance })),
      borderColor: palette(0),
      backgroundColor: palette(0, 0.15),
      fill: true,
      tension: 0.1,
      pointRadius: 0,
      pointHoverRadius: 4,
    });
  } else {
    data.accounts.forEach((a, i) => {
      datasets.push({
        label: `${a.holder_name} (${a.account_number})`,
        data: a.points.map(p => ({ x: p.date, y: p.balance })),
        borderColor: palette(i),
        backgroundColor: palette(i, 0.08),
        fill: false,
        tension: 0.1,
        pointRadius: 0,
        pointHoverRadius: 4,
      });
    });
  }

  showChart(true);
  destroyChart();
  chart = new Chart($("#main-chart"), {
    type: "line",
    data: { datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      scales: {
        x: { type: "time", time: { unit: "month" }, grid: { color: gridColor() } },
        y: { grid: { color: gridColor() }, ticks: { callback: (v) => fmtEur(v) } },
      },
      plugins: {
        legend: { display: datasets.length > 1 },
        tooltip: {
          callbacks: {
            title: (items) => {
              if (!items || items.length === 0) return "";
              const raw = items[0].raw;
              const date = typeof raw.x === "string" ? raw.x : new Date(raw.x).toISOString().slice(0, 10);
              return fmtItDate(date);
            },
            label: (ctx) => `${ctx.dataset.label}: ${fmtEur(ctx.parsed.y)}`,
            afterBody: (items) => {
              if (!items || items.length === 0) return "";
              const raw = items[0].raw;
              const date = typeof raw.x === "string" ? raw.x : new Date(raw.x).toISOString().slice(0, 10);
              const txs = getCachedTransactions(date);
              if (txs === undefined) {
                prefetchTransactions(date);
                return ["", "Movimenti: caricamento…"];
              }
              if (txs.length === 0) return ["", "Nessun movimento in questa data"];
              const lines = ["", `Movimenti (${txs.length}):`];
              const maxShow = 8;
              for (const t of txs.slice(0, maxShow)) {
                const sign = t.amount >= 0 ? "+" : "";
                const time = extractTimeFromDesc(t.full_description || t.description || "");
                const timeStr = time ? ` [${time}]` : "";
                const desc = (t.full_description || t.description || "").slice(0, 80);
                lines.push(`  ${sign}${fmtEur(t.amount)}${timeStr} — ${desc}`);
              }
              if (txs.length > maxShow) lines.push(`  … e altri ${txs.length - maxShow}`);
              return lines;
            },
          },
        },
      },
    },
  });

  const last = data.mode === "cumulative"
    ? data.points[data.points.length - 1]
    : data.accounts[0]?.points[data.accounts[0].points.length - 1];
  if (last) {
    const note = state.excludeTrading ? " — escluse compravendite titoli" : "";
    setStatus(`Saldo al ${last.date}: ${fmtEur(last.balance)}${note}`, "ok");
  } else if (state.selectedIds.size === 0) {
    setStatus("Nessun conto selezionato", "warn");
  } else {
    setStatus("Nessun dato nel periodo selezionato", "warn");
  }
}

async function renderBarChart() {
  const q = queryArgs();
  let data;
  try { data = await apiGet(`/api/group-stats${q}`); }
  catch (e) { setStatus("Errore caricamento gruppi: " + e.message, "err"); showChart(false); return; }

  const visible = data.groups.filter(g => g.count > 0);
  const labels = visible.map(g => g.name);
  // Due dataset impilati: prima uscite (|amount|), poi entrate
  const expenseData = visible.map(g => g.expense_abs_total || 0);
  const incomeData  = visible.map(g => g.income_total || 0);

  // metadati per il tooltip e il drill-down (una riga meta per label)
  const groupMeta = visible.map(g => ({
    id: g.id, count: g.count, name: g.name, total: g.total,
    income: g.income_total || 0, expense_abs: g.expense_abs_total || 0,
    income_count: g.income_count || 0, expense_count: g.expense_count || 0,
    tags: g.tags || [],
  }));

  // Non classificati: una colonna per "entrate non classificate", una per "uscite non classificate"
  const inc = data.uncategorized_income || { count: 0, total: 0 };
  const exp = data.uncategorized_expense || { count: 0, total: 0 };
  if (inc.count > 0) {
    labels.push(`Non classificati entrate (${inc.count})`);
    expenseData.push(0);
    incomeData.push(inc.total);
    groupMeta.push({ id: 0, uncategorized_kind: "income", count: inc.count,
                     name: "Non classificati entrate", total: inc.total,
                     income: inc.total, expense_abs: 0,
                     income_count: inc.count, expense_count: 0, tags: [] });
  }
  if (exp.count > 0) {
    labels.push(`Non classificati uscite (${exp.count})`);
    expenseData.push(-exp.total); // exp.total è negativo → valore assoluto
    incomeData.push(0);
    groupMeta.push({ id: 0, uncategorized_kind: "expense", count: exp.count,
                     name: "Non classificati uscite", total: exp.total,
                     income: 0, expense_abs: -exp.total,
                     income_count: 0, expense_count: exp.count, tags: [] });
  }

  showChart(true);
  destroyChart();
  chart = new Chart($("#main-chart"), {
    type: "bar",
    data: {
      labels,
      datasets: [
        // Segmento rosso (uscite) in basso, verde (entrate) sopra
        { label: "Uscite",  data: expenseData, backgroundColor: "rgba(220,38,38,0.75)",  borderWidth: 0, stack: "g" },
        { label: "Entrate", data: incomeData,  backgroundColor: "rgba(22,163,74,0.75)", borderWidth: 0, stack: "g" },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false, axis: "x" },
      onClick: (_evt, elements, chartInstance) => {
        let idx = elements && elements[0] ? elements[0].index : null;
        if (idx == null) {
          const active = chartInstance.tooltip && chartInstance.tooltip.getActiveElements();
          if (active && active.length) idx = active[0].index;
        }
        if (idx == null) return;
        const meta = groupMeta[idx];
        if (!meta) return;
        openDrill(meta);
      },
      scales: {
        x: { stacked: true, grid: { color: gridColor() } },
        y: { stacked: true, grid: { color: gridColor() }, ticks: { callback: (v) => fmtEur(v) } },
      },
      plugins: {
        legend: { display: true, position: "bottom" },
        tooltip: {
          callbacks: {
            title: (items) => items && items[0] ? items[0].label : "",
            label: () => null, // una singola entry sintetica invece di due righe duplicate
            afterBody: (items) => {
              if (!items || items.length === 0) return "";
              const meta = groupMeta[items[0].dataIndex];
              if (!meta) return "";
              const lines = [];
              if (meta.income_count > 0) lines.push(`↑ Entrate: ${fmtEur(meta.income)} (${meta.income_count})`);
              if (meta.expense_count > 0) lines.push(`↓ Uscite: ${fmtEur(-meta.expense_abs)} (${meta.expense_count})`);
              lines.push(`Netto: ${fmtEur(meta.total)}`);
              lines.push("click per dettaglio");
              return lines;
            },
          },
          filter: (item) => item.raw > 0, // nel tooltip mostra solo il dataset col valore != 0
        },
      },
    },
  });
  $("#main-chart").style.cursor = "pointer";
  if (state.selectedIds.size === 0) {
    setStatus("Nessun conto selezionato", "warn");
  } else if (visible.length === 0 && data.uncategorized.count === 0) {
    setStatus("Nessun dato nel periodo selezionato", "warn");
  } else {
    setStatus(`${visible.length} gruppi attivi${data.uncategorized.count ? `, ${data.uncategorized.count} non classificati` : ""}`, "ok");
  }
}

function destroyChart() {
  if (chart) { chart.destroy(); chart = null; }
}

function palette(i, alpha = 1) {
  const colors = [
    [13, 148, 136],    // teal
    [234, 88, 12],     // orange
    [168, 85, 247],    // purple
    [234, 179, 8],     // yellow
    [14, 165, 233],    // sky
    [239, 68, 68],     // red
    [34, 197, 94],     // green
  ];
  const c = colors[i % colors.length];
  return `rgba(${c[0]}, ${c[1]}, ${c[2]}, ${alpha})`;
}

function isDarkMode() {
  return document.documentElement.getAttribute("data-theme") === "dark";
}

function gridColor() {
  return isDarkMode() ? "rgba(255,255,255,0.06)" : "rgba(0,0,0,0.06)";
}

// -------- Drill-down (dettaglio gruppo) --------
async function openDrill(meta) {
  const panel = $("#drill-panel");
  const tbody = $("#drill-table tbody");
  const title = $("#drill-title");
  const summary = $("#drill-summary");

  title.textContent = meta.name;
  summary.textContent = `${meta.count} movimenti · totale ${fmtEur(meta.total)} · caricamento…`;
  tbody.innerHTML = "";
  panel.classList.remove("hidden");
  panel.scrollIntoView({ behavior: "smooth", block: "start" });

  const params = new URLSearchParams();
  params.set("group_id", String(meta.id));
  if (meta.uncategorized_kind) params.set("uncategorized_kind", meta.uncategorized_kind);
  params.set("limit", "2000");
  if (state.selectedIds.size < state.accounts.length) {
    params.set("accounts", [...state.selectedIds].join(","));
  }
  if (state.includeAuthorized) params.set("include_authorized", "true");
  // Non applico exclude_trading ai gruppi di trading: saremmo in contraddizione
  // Se il gruppo contiene il tag 'trading', il drill vuole vedere proprio quelle tx
  const isTradingGroup = (meta.tags || []).includes("trading");
  if (state.excludeTrading && !isTradingGroup) params.set("exclude_trading", "true");
  if (state.dateFrom) params.set("date_from", state.dateFrom);
  if (state.dateTo) params.set("date_to", state.dateTo);

  try {
    const rows = await apiGet(`/api/transactions?${params.toString()}`);
    renderDrillRows(rows, meta);
  } catch (e) {
    summary.textContent = "Errore: " + e.message;
  }
}

function renderDrillRows(rows, meta) {
  const tbody = $("#drill-table tbody");
  const summary = $("#drill-summary");
  tbody.innerHTML = "";
  let sum = 0;
  for (const r of rows) {
    sum += Number(r.amount);
    const tr = document.createElement("tr");
    const amountCls = r.amount >= 0 ? "value-positive" : "value-negative";
    const desc = r.full_description || r.description || "";
    tr.innerHTML = `
      <td class="date-col">${fmtItDate(r.value_date)}</td>
      <td class="date-col">${escHtml(r.holder_name)} <span style="color:var(--text-secondary)">(${escHtml(r.account_number)})</span></td>
      <td class="desc-col">${escHtml(desc)}</td>
      <td class="amount-col ${amountCls}">${fmtEur(r.amount)}</td>
      <td class="date-col">${escHtml(r.status || "")}</td>
    `;
    tbody.appendChild(tr);
  }
  const showing = rows.length;
  const total = meta.count;
  const truncated = showing < total ? ` (mostrati i primi ${showing})` : "";
  summary.textContent = `${total} movimenti · totale ${fmtEur(meta.total)}${truncated}`;
}

function closeDrill() {
  $("#drill-panel").classList.add("hidden");
}

// -------- Config (tag-rules + groups) --------
// Stato "working" locale: copia editabile di regole e gruppi.
// state.rules / state.groups sono la versione canonica (server).
// state.rulesWorking / state.groupsWorking sono la versione modificabile.
// I bottoni Salva si attivano quando i due differiscono.
state.rulesDirty = false;
state.groupsDirty = false;

function escHtml(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;"}[c])); }

function cloneRules(rules) {
  return rules.map(r => ({ id: r.id, name: r.name, pattern: r.pattern, tag: r.tag, priority: r.priority }));
}
function cloneGroups(groups) {
  return groups.map(g => ({ id: g.id, name: g.name, kind: g.kind, priority: g.priority, tags: [...(g.tags || [])] }));
}

async function reloadServerConfig() {
  if (!state.serverUrl) return;
  const [rules, groups] = await Promise.all([
    apiGet("/api/tag-rules"),
    apiGet("/api/groups"),
  ]);
  state.rules = rules;
  state.groups = groups;
  state.rulesWorking = cloneRules(rules);
  state.groupsWorking = cloneGroups(groups);
  state.rulesDirty = false;
  state.groupsDirty = false;
  renderRulesTable();
  renderGroupsTable();
  updateSaveButtons();
}

function updateSaveButtons() {
  $("#save-rules-btn").disabled = !state.rulesDirty;
  $("#save-groups-btn").disabled = !state.groupsDirty;
  $("#rules-count").textContent = state.rulesWorking ? state.rulesWorking.length : 0;
  $("#groups-count").textContent = state.groupsWorking ? state.groupsWorking.length : 0;
}

function markRulesDirty() { state.rulesDirty = true; updateSaveButtons(); }
function markGroupsDirty() { state.groupsDirty = true; updateSaveButtons(); }

// --- Render tag-rules table ---
function renderRulesTable() {
  const tbody = $("#rules-tbody");
  tbody.innerHTML = "";
  state.rulesWorking.forEach((r, idx) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td class="col-priority"><input type="number" data-f="priority" value="${r.priority ?? 0}"></td>
      <td><input type="text" data-f="name" value="${escHtml(r.name)}"></td>
      <td class="col-pattern"><input type="text" data-f="pattern" value="${escHtml(r.pattern)}" spellcheck="false"></td>
      <td><input type="text" data-f="tag" value="${escHtml(r.tag)}" spellcheck="false"></td>
      <td><button class="icon-btn danger" title="Elimina regola" aria-label="Elimina">${TRASH_ICON}</button></td>
    `;
    tr.querySelectorAll("input").forEach(inp => {
      inp.oninput = () => {
        const val = inp.type === "number" ? Number(inp.value) : inp.value;
        r[inp.dataset.f] = val;
        markRulesDirty();
      };
    });
    tr.querySelector("button").onclick = () => {
      state.rulesWorking.splice(idx, 1);
      markRulesDirty();
      renderRulesTable();
    };
    tbody.appendChild(tr);
  });
}

function addRuleRow() {
  state.rulesWorking.push({ name: "Nuova regola", pattern: "", tag: "", priority: 999 });
  markRulesDirty();
  renderRulesTable();
  // focus sull'input name dell'ultima riga
  const tbody = $("#rules-tbody");
  const last = tbody.lastElementChild;
  if (last) last.querySelector('input[data-f="name"]').focus();
}

async function saveRules() {
  // Validazione client: regex compilabili
  for (const r of state.rulesWorking) {
    if (!r.name || !r.pattern || !r.tag) {
      setStatus("Tutte le regole devono avere nome, regex e tag", "err");
      return;
    }
    try { new RegExp(r.pattern); } catch (e) {
      setStatus(`Regex non valida in "${r.name}": ${e.message}`, "err");
      return;
    }
  }
  try {
    await apiPost("/api/tag-rules/bulk", state.rulesWorking.map(r => ({
      name: r.name, pattern: r.pattern, tag: r.tag, priority: r.priority || 0,
    })));
    setStatus(`Salvate ${state.rulesWorking.length} regole`, "ok");
    await reloadServerConfig();
    refreshChart();
  } catch (e) {
    setStatus("Errore salvataggio regole: " + e.message, "err");
  }
}

// --- Render groups table ---
function renderGroupsTable() {
  const tbody = $("#groups-tbody");
  tbody.innerHTML = "";
  state.groupsWorking.forEach((g, idx) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td class="col-priority"><input type="number" data-f="priority" value="${g.priority ?? 0}"></td>
      <td><input type="text" data-f="name" value="${escHtml(g.name)}"></td>
      <td><select data-f="kind">
        <option value="any"     ${g.kind==='any'    ?'selected':''}>Entrambi</option>
        <option value="income"  ${g.kind==='income' ?'selected':''}>Entrata</option>
        <option value="expense" ${g.kind==='expense'?'selected':''}>Uscita</option>
      </select></td>
      <td class="col-tags"></td>
      <td><button class="icon-btn danger" title="Elimina gruppo" aria-label="Elimina">${TRASH_ICON}</button></td>
    `;
    tr.querySelectorAll("input, select").forEach(el => {
      if (el.dataset.f) {
        el.onchange = el.oninput = () => {
          const val = el.type === "number" ? Number(el.value) : el.value;
          g[el.dataset.f] = val;
          markGroupsDirty();
        };
      }
    });
    tr.querySelector(".col-tags").appendChild(makeTagChipInput(g));
    tr.querySelector("button").onclick = () => {
      state.groupsWorking.splice(idx, 1);
      markGroupsDirty();
      renderGroupsTable();
    };
    tbody.appendChild(tr);
  });
}

function makeTagChipInput(group) {
  const host = document.createElement("div");
  host.className = "tag-chip-input";
  function render() {
    host.innerHTML = "";
    group.tags.forEach((t, i) => {
      const chip = document.createElement("span");
      chip.className = "tag-chip";
      chip.textContent = t;
      const rm = document.createElement("span");
      rm.className = "remove";
      rm.textContent = "×";
      rm.onclick = () => {
        group.tags.splice(i, 1);
        markGroupsDirty();
        render();
      };
      chip.appendChild(rm);
      host.appendChild(chip);
    });
    const input = document.createElement("input");
    input.type = "text";
    input.placeholder = group.tags.length === 0 ? "aggiungi tag…" : "";
    input.setAttribute("list", "tag-suggestions");
    input.onkeydown = (e) => {
      if (e.key === "Enter" || e.key === ",") {
        e.preventDefault();
        commit(input.value);
      } else if (e.key === "Backspace" && !input.value && group.tags.length > 0) {
        group.tags.pop();
        markGroupsDirty();
        render();
      }
    };
    input.onblur = () => { if (input.value.trim()) commit(input.value); };
    function commit(raw) {
      const t = raw.trim().replace(/,$/, "").trim();
      if (!t) return;
      if (!group.tags.includes(t)) {
        group.tags.push(t);
        markGroupsDirty();
      }
      input.value = "";
      render();
    }
    host.appendChild(input);
  }
  render();
  return host;
}

function addGroupRow() {
  state.groupsWorking.push({ name: "Nuovo gruppo", kind: "expense", priority: 999, tags: [] });
  markGroupsDirty();
  renderGroupsTable();
  const tbody = $("#groups-tbody");
  const last = tbody.lastElementChild;
  if (last) last.querySelector('input[data-f="name"]').focus();
}

async function saveGroups() {
  for (const g of state.groupsWorking) {
    if (!g.name) { setStatus("Tutti i gruppi devono avere un nome", "err"); return; }
    if (!["income", "expense", "any"].includes(g.kind)) { setStatus(`Kind non valido in "${g.name}"`, "err"); return; }
  }
  try {
    await apiPost("/api/groups/bulk", state.groupsWorking.map(g => ({
      name: g.name, kind: g.kind, priority: g.priority || 0, tags: g.tags || [],
    })));
    setStatus(`Salvati ${state.groupsWorking.length} gruppi`, "ok");
    await reloadServerConfig();
    refreshChart();
  } catch (e) {
    setStatus("Errore salvataggio gruppi: " + e.message, "err");
  }
}

async function resetSeed() {
  if (!confirm("Reimpostare tag-rules e gruppi alla configurazione iniziale?\n\nTutte le tue modifiche verranno perse.")) return;
  try {
    await apiPost("/api/seed", {});
    setStatus("Configurazione reimpostata", "ok");
    await reloadServerConfig();
    refreshChart();
  } catch (e) {
    setStatus("Errore reset: " + e.message, "err");
  }
}

// --- Untagged view ---
async function loadUntagged() {
  if (!state.serverUrl) return;
  const params = new URLSearchParams({ untagged: "true", limit: "2000" });
  if (state.selectedIds.size < state.accounts.length) {
    params.set("accounts", [...state.selectedIds].join(","));
  }
  if (state.includeAuthorized) params.set("include_authorized", "true");
  if (state.dateFrom) params.set("date_from", state.dateFrom);
  if (state.dateTo) params.set("date_to", state.dateTo);
  try {
    const rows = await apiGet(`/api/transactions?${params.toString()}`);
    $("#untagged-count").textContent = rows.length;
    const tbody = $("#untagged-table tbody");
    tbody.innerHTML = "";
    for (const r of rows) {
      const tr = document.createElement("tr");
      const cls = r.amount >= 0 ? "value-positive" : "value-negative";
      const desc = r.full_description || r.description || "";
      tr.innerHTML = `
        <td class="date-col">${fmtItDate(r.value_date)}</td>
        <td class="date-col">${escHtml(r.holder_name)} <span style="color:var(--text-secondary)">(${escHtml(r.account_number)})</span></td>
        <td class="desc-col">${escHtml(desc)}</td>
        <td class="amount-col ${cls}">${fmtEur(r.amount)}</td>
      `;
      tbody.appendChild(tr);
    }
  } catch (e) {
    setStatus("Errore caricamento non taggati: " + e.message, "err");
  }
}

// -------- View switcher --------
function setView(v) {
  state.view = v;
  $$(".view-tab").forEach(b => b.classList.toggle("active", b.dataset.view === v));
  closeDrill();
  refreshChart();
}

async function refreshAll() {
  if (!state.serverUrl) {
    setStatus("Configura l'indirizzo del server nelle impostazioni", "warn");
    $("#toolbar").classList.add("hidden");
    showChart(false);
    $("#groups-panel").classList.add("hidden");
    setTabsVisible(false);
    return;
  }
  try {
    await reloadAccounts();
    await reloadServerConfig();
    const hasData = state.accounts.length > 0;
    setTabsVisible(hasData);
    $("#toolbar").classList.toggle("hidden", !hasData);
    if (hasData) {
      await refreshChart();
    } else {
      showChart(false);
      $("#groups-panel").classList.add("hidden");
      setStatus("Nessun conto presente. Carica un file per iniziare.", "warn");
    }
  } catch (e) {
    setStatus("Errore server: " + e.message, "err");
    $("#toolbar").classList.add("hidden");
    showChart(false);
    setTabsVisible(false);
  }
}

function cycleTheme() {
  const cur = state.theme || "system";
  const idx = THEME_CYCLE.indexOf(cur);
  const next = THEME_CYCLE[(idx + 1) % THEME_CYCLE.length];
  applyTheme(next);
  saveConfig();
  if (chart) refreshChart();
}

// -------- Init --------
async function init() {
  await loadConfig();

  $("#upload-btn").onclick = doUpload;
  $("#file-input").onchange = onFileSelected;
  $("#settings-btn").onclick = toggleSettings;
  $("#close-settings-btn").onclick = closeSettings;
  $("#save-settings-btn").onclick = saveSettings;
  $("#test-connection-btn").onclick = testConnection;
  $("#theme-toggle").onclick = cycleTheme;
  $("#refresh-btn").onclick = refreshAll;
  $("#include-authorized").onchange = (e) => { state.includeAuthorized = e.target.checked; txCache.clear(); refreshChart(); };
  $("#exclude-trading").onchange = (e) => { state.excludeTrading = e.target.checked; txCache.clear(); refreshChart(); };
  $("#exclude-trading").checked = state.excludeTrading;
  $("#date-from").onchange = (e) => { state.dateFrom = e.target.value; refreshChart(); };
  $("#date-to").onchange = (e) => { state.dateTo = e.target.value; refreshChart(); };
  $("#drill-close").onclick = closeDrill;
  $("#add-rule-btn").onclick = addRuleRow;
  $("#save-rules-btn").onclick = saveRules;
  $("#add-group-btn").onclick = addGroupRow;
  $("#save-groups-btn").onclick = saveGroups;
  $("#reset-seed-btn").onclick = resetSeed;
  $("#reload-config-btn").onclick = async () => {
    await reloadServerConfig();
    await loadUntagged();
    setStatus("Configurazione ricaricata dal server", "ok");
  };
  $("#section-untagged").addEventListener("toggle", (e) => {
    if (e.target.open) loadUntagged();
  });

  $$(".view-tab").forEach(b => b.onclick = () => setView(b.dataset.view));

  if (window.matchMedia) {
    window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
      if (state.theme === "system") {
        applyTheme("system");
        if (chart) refreshChart();
      }
    });
  }

  setTabsVisible(false);
  if (!state.serverUrl) {
    openSettings();
    setStatus("Imposta l'indirizzo del server per iniziare", "warn");
    return;
  }
  await refreshAll();
}

document.addEventListener("DOMContentLoaded", init);
