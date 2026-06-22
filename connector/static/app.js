/* IC AI Connector Dashboard */

const TOKEN_KEY = "ic_connector_token";
const POLL_MS = 4000;

let pollTimer = null;
let countdownTimer = null;
let feedMeta = null;
let lastFeedHeadId = null;

const $ = (sel) => document.querySelector(sel);

function getToken() {
  return sessionStorage.getItem(TOKEN_KEY) || "";
}

function setToken(t) {
  sessionStorage.setItem(TOKEN_KEY, t);
}

function clearToken() {
  sessionStorage.removeItem(TOKEN_KEY);
}

function authHeaders() {
  return {
    Authorization: `Bearer ${getToken()}`,
    "Content-Type": "application/json",
  };
}

async function api(path, opts = {}) {
  const res = await fetch(path, {
    ...opts,
    headers: { ...authHeaders(), ...(opts.headers || {}) },
  });
  if (res.status === 401) {
    clearToken();
    showLock();
    throw new Error("Session expired");
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = new Error(data.detail || res.statusText || "Request failed");
    err.status = res.status;
    throw err;
  }
  return data;
}

function toast(msg, ms = 2800) {
  const el = $("#toast");
  el.textContent = msg;
  el.classList.remove("hidden");
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.add("hidden"), ms);
}

function fmt(n, dec = 2) {
  if (n == null || Number.isNaN(Number(n))) return "—";
  return Number(n).toLocaleString(undefined, {
    minimumFractionDigits: dec,
    maximumFractionDigits: dec,
  });
}

function fmtPnl(n) {
  const v = Number(n);
  const s = (v >= 0 ? "+" : "") + fmt(v, 4);
  return s;
}

function pnlClass(n) {
  const v = Number(n);
  if (v > 0) return "positive";
  if (v < 0) return "negative";
  return "";
}

function showLock() {
  $("#lock-screen").classList.remove("hidden");
  $("#app").classList.add("hidden");
  stopPoll();
}

function showApp() {
  $("#lock-screen").classList.add("hidden");
  $("#app").classList.remove("hidden");
  startPoll();
  loadSettings();
}

async function tryUnlock() {
  const token = $("#token-input").value.trim();
  const errEl = $("#lock-error");
  errEl.classList.add("hidden");
  if (!token) {
    errEl.textContent = "Enter your access code.";
    errEl.classList.remove("hidden");
    return;
  }
  setToken(token);
  try {
    await api("/api/ui/dashboard");
    showApp();
    toast("Connected");
  } catch (e) {
    if (e.status === 401 || e.message === "Session expired") {
      clearToken();
      errEl.textContent = "Invalid access code. Check CONNECTOR_TOKEN in .env";
      errEl.classList.remove("hidden");
      return;
    }
    showApp();
    toast(e.message || "Connected (exchange sync delayed)");
  }
}

function stopPoll() {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = null;
  if (countdownTimer) clearInterval(countdownTimer);
  countdownTimer = null;
}

function startPoll() {
  stopPoll();
  refreshDashboard();
  pollTimer = setInterval(refreshDashboard, POLL_MS);
  startCountdown();
}

function feedHeadId(head) {
  if (!head || !head.count) return "empty";
  return head.latest_id || "empty";
}

async function refreshDashboard() {
  const dot = $("#sync-indicator");
  try {
    const d = await api("/api/ui/dashboard");
    dot.classList.remove("error");

    const bal = d.balance || {};
    $("#stat-balance").textContent = `$${fmt(bal.total)}`;
    const upnlEl = $("#stat-upnl");
    upnlEl.textContent = fmtPnl(d.total_unrealized_pnl);
    upnlEl.className = `stat-value ${pnlClass(d.total_unrealized_pnl)}`;
    $("#stat-positions").textContent = (d.positions || []).length;

    $("#account-badge").textContent = (d.account || "live").toUpperCase();
    $("#trade-mode-pill").textContent = `${d.trade_mode || "auto"} mode`;
    $("#last-sync").textContent = new Date().toLocaleTimeString();

    renderPositionsAndOrders(d.positions || [], d.algo_orders || []);
    renderRisk(d.risk || {}, d.trade_mode);

    if (d.feed_meta) feedMeta = d.feed_meta;
    await maybeLoadAiFeed(d.feed_head);
  } catch (e) {
    dot.classList.add("error");
    if (e.message !== "Session expired") {
      console.error(e);
      if (e.status === 503) toast("Binance sync delayed — retrying…", 4000);
    }
  }
}

async function maybeLoadAiFeed(head) {
  const id = feedHeadId(head);
  if (id === lastFeedHeadId) return;
  lastFeedHeadId = id;
  await loadAiFeedFull();
}

async function loadAiFeedFull() {
  const feed = await api("/api/ui/ai-feed");
  if (feed.meta) feedMeta = feed.meta;
  renderAiFeed(feed.messages || []);
}

function formatCountdown(totalSeconds) {
  const s = Math.max(0, Math.floor(totalSeconds));
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`;
}

function nextDecisionClient(intervalSec = 900) {
  const now = Math.floor(Date.now() / 1000);
  const next = (Math.floor(now / intervalSec) + 1) * intervalSec;
  return next * 1000;
}

function updateCountdown() {
  const el = $("#decision-countdown");
  if (!el) return;

  let nextMs;
  if (feedMeta?.next_decision_at) {
    nextMs = new Date(feedMeta.next_decision_at).getTime();
  } else {
    nextMs = nextDecisionClient(feedMeta?.interval_seconds || 900);
  }

  const remaining = (nextMs - Date.now()) / 1000;
  el.classList.remove("urgent", "analyzing");
  if (remaining <= 0) {
    el.textContent = "Analyzing…";
    el.classList.add("analyzing");
  } else if (remaining <= 60) {
    el.textContent = formatCountdown(remaining);
    el.classList.add("urgent");
  } else {
    el.textContent = formatCountdown(remaining);
  }
}

function startCountdown() {
  if (countdownTimer) clearInterval(countdownTimer);
  updateCountdown();
  countdownTimer = setInterval(updateCountdown, 1000);
}

function formatFeedTime(iso) {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleTimeString(undefined, {
      hour: "numeric",
      minute: "2-digit",
    });
  } catch {
    return "";
  }
}

function messageToHtml(text) {
  return escapeHtml(text).replace(/\n/g, "<br>");
}

function tierClassFromLine(line) {
  const m = line.match(/\((P1|P2|P3|Watch|—)\)/);
  if (!m) return "";
  const t = m[1];
  if (t === "P1") return "feed-tier-p1";
  if (t === "P2") return "feed-tier-p2";
  if (t === "P3") return "feed-tier-p3";
  if (t === "Watch") return "feed-tier-watch";
  return "feed-tier-none";
}

function formatFeedBody(m) {
  const coins = Array.isArray(m.coin_briefs) ? m.coin_briefs : [];
  if (coins.length) {
    const coinHtml = coins
      .map((line) => {
        const text = String(line || "").trim();
        if (!text) return "";
        const symMatch = text.match(/^([A-Z0-9]+USDT)\b/);
        if (symMatch) {
          const sym = symMatch[1];
          const rest = text.slice(sym.length).trim();
          const tierCls = tierClassFromLine(text);
          return `<div class="feed-coin ${tierCls}"><span class="feed-sym">${escapeHtml(sym)}</span> ${escapeHtml(rest)}</div>`;
        }
        return `<div class="feed-coin">${escapeHtml(text)}</div>`;
      })
      .join("");
    return coinHtml;
  }
  return messageToHtml(m.brief || "");
}

function scrollChatToBottom() {
  const el = $("#ai-feed");
  if (!el) return;
  requestAnimationFrame(() => {
    el.scrollTop = el.scrollHeight;
  });
}

function renderAiFeed(messages) {
  const el = $("#ai-feed");
  if (!messages.length) {
    el.innerHTML =
      '<div class="chat-empty">Analysis messages appear here every 15 minutes.</div>';
    lastFeedHeadId = "empty";
    return;
  }

  el.innerHTML = messages
    .map((m) => {
      const time = formatFeedTime(m.created_at);
      const stamp = time
        ? `<div class="speaker-tag">${escapeHtml(time)}</div>`
        : "";
      return `<div class="bubble ai">${stamp}${formatFeedBody(m)}</div>`;
    })
    .join("");
  scrollChatToBottom();
}

async function clearAiFeed() {
  if (!confirm("Clear AI Desk chat? New analysis messages will appear on the next cycle.")) {
    return;
  }
  try {
    await api("/api/ui/ai-feed", { method: "DELETE" });
    lastFeedHeadId = "empty";
    renderAiFeed([]);
    toast("Chat cleared");
  } catch (e) {
    toast(e.message);
  }
}

function shortSymbol(sym) {
  if (!sym) return "";
  const s = String(sym).toUpperCase();
  if (s.includes("/")) return s.split("/")[0] + s.split("/")[1].split(":")[0];
  return s.replace(":", "");
}

function normalizeSymbolKey(sym) {
  return shortSymbol(sym);
}

function indexAlgosBySymbol(algos) {
  const map = {};
  for (const a of algos) {
    const key = normalizeSymbolKey(a.symbol);
    if (!map[key]) map[key] = { sl: null, tp: null };
    const type = (a.orderType || "").toUpperCase();
    const price = a.triggerPrice;
    if (type === "STOP_MARKET" || type.includes("STOP")) {
      map[key].sl = price;
    } else if (type.includes("TAKE_PROFIT") || type === "TAKE_PROFIT_MARKET") {
      map[key].tp = price;
    }
  }
  return map;
}

function renderTpslCell(sl, tp) {
  if (!sl && !tp) return '<span class="tpsl-empty">-- / --</span>';
  const tpStr = tp ? `<span class="tpsl-tp">${fmt(tp, 4)}</span>` : '<span class="tpsl-empty">--</span>';
  const slStr = sl ? `<span class="tpsl-sl">${fmt(sl, 4)}</span>` : '<span class="tpsl-empty">--</span>';
  return `<div class="tpsl-cell">${tpStr}<span class="tpsl-sep">/</span>${slStr}</div>`;
}

function renderPositionsAndOrders(positions, algos) {
  const algoMap = indexAlgosBySymbol(algos);
  $("#pos-tab-count").textContent = positions.length;
  $("#orders-tab-count").textContent = algos.length;

  renderPositionsTable(positions, algoMap);
  renderOrdersTable(algos);
}

function renderPositionsTable(positions, algoMap) {
  const tbody = $("#positions-body");
  if (!positions.length) {
    tbody.innerHTML = '<tr><td colspan="9" class="empty">No open positions</td></tr>';
    return;
  }

  tbody.innerHTML = positions
    .map((p) => {
      const sym = p.symbol || "";
      const key = normalizeSymbolKey(sym);
      const display = shortSymbol(sym);
      const side = (p.side || "").toLowerCase();
      const isLong = side === "long";
      const lev = p.leverage ? `${p.leverage}x` : "";
      const pnl = p.unrealizedPnl;
      const roi = p.percentage != null ? `${Number(p.percentage).toFixed(2)}%` : "";
      const { sl, tp } = algoMap[key] || { sl: null, tp: null };
      const sizeCls = isLong ? "size-long" : "size-short";
      const sizeSign = isLong ? "" : "-";

      return `
      <tr data-symbol="${escapeHtml(sym)}">
        <td>
          <div class="symbol-cell">
            <span class="symbol-name">${escapeHtml(display)}</span>
            <div class="symbol-meta">
              <span class="symbol-perp">Perp ${escapeHtml(lev)}</span>
              <span class="side-badge ${isLong ? "long" : "short"}">${escapeHtml(side)}</span>
            </div>
          </div>
        </td>
        <td class="${sizeCls}">${sizeSign}${fmt(p.contracts, 4)}</td>
        <td>${fmt(p.entryPrice, 4)}</td>
        <td>${fmt(p.markPrice, 4)}</td>
        <td>${fmt(p.liquidationPrice, 4)}</td>
        <td>${p.initialMargin != null ? fmt(p.initialMargin, 2) : "—"}</td>
        <td>
          <div class="pnl-cell ${pnlClass(pnl)}">
            <span>${fmtPnl(pnl)}</span>
            ${roi ? `<span class="pnl-roi">(${roi})</span>` : ""}
          </div>
        </td>
        <td>${renderTpslCell(sl, tp)}</td>
        <td>
          <div class="action-cell">
            <button class="btn btn-ghost btn-sm" data-partial="${escapeHtml(sym)}" data-pct="100">Market</button>
            <button class="btn btn-ghost btn-sm" data-partial="${escapeHtml(sym)}" data-pct="50">50%</button>
            <input type="number" step="any" class="inline-input" placeholder="SL" data-sl-symbol="${escapeHtml(sym)}" />
            <button class="btn btn-gold btn-sm" data-move-sl="${escapeHtml(sym)}" title="Move SL">SL</button>
          </div>
        </td>
      </tr>`;
    })
    .join("");

  bindPositionActions(tbody);
}

function renderOrdersTable(algos) {
  const tbody = $("#orders-body");
  if (!algos.length) {
    tbody.innerHTML = '<tr><td colspan="5" class="empty">No open orders</td></tr>';
    return;
  }
  tbody.innerHTML = algos
    .map((a) => {
      const type = (a.orderType || "").replace(/_/g, " ");
      return `
    <tr>
      <td>${escapeHtml(shortSymbol(a.symbol || ""))}</td>
      <td>${escapeHtml(type)}</td>
      <td>${escapeHtml(a.side || "")}</td>
      <td>${fmt(a.triggerPrice, 4)}</td>
      <td>${escapeHtml(a.algoStatus || "NEW")}</td>
    </tr>`;
    })
    .join("");
}

function bindPositionActions(tbody) {
  tbody.querySelectorAll("[data-partial]").forEach((btn) => {
    btn.addEventListener("click", () =>
      partialClose(btn.dataset.partial, Number(btn.dataset.pct))
    );
  });
  tbody.querySelectorAll("[data-move-sl]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const sym = btn.dataset.moveSl;
      const row = btn.closest("tr");
      const input = row?.querySelector(`[data-sl-symbol]`);
      const price = Number(input?.value);
      if (!price || price <= 0) {
        toast("Enter a stop loss price");
        return;
      }
      moveSl(sym, price);
    });
  });
}

function initTabs() {
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      const name = tab.dataset.tab;
      document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
      $("#tab-positions").classList.toggle("hidden", name !== "positions");
      $("#tab-orders").classList.toggle("hidden", name !== "orders");
    });
  });
}

function renderRisk(risk, tradeMode) {
  const el = $("#risk-grid");
  const state = risk.state || {};
  const ks = state.kill_switch ? "kill-active" : "";
  const pnl = state.realized_pnl_today ?? 0;
  el.innerHTML = `
    <div class="risk-item"><div class="label">Kill Switch</div><div class="value ${ks}">${state.kill_switch ? "ACTIVE" : "Off"}</div></div>
    <div class="risk-item"><div class="label">Daily PnL</div><div class="value ${pnlClass(pnl)}">${fmtPnl(pnl)}</div></div>
    <div class="risk-item"><div class="label">Max Order</div><div class="value">$${fmt(risk.limits?.max_notional_per_order, 0)}</div></div>
    <div class="risk-item"><div class="label">Max Leverage</div><div class="value">${risk.limits?.max_leverage || "—"}x</div></div>
  `;
}

async function partialClose(symbol, pct) {
  try {
    const res = await api("/api/ui/partial-close", {
      method: "POST",
      body: JSON.stringify({ symbol, percentage: pct }),
    });
    toast(res.status === "executed" ? `Closed ${pct}%` : `Close ${pct}%: ${res.status || "ok"}`);
    refreshDashboard();
  } catch (e) {
    toast(e.message);
  }
}

async function moveSl(symbol, trigger_price) {
  try {
    const res = await api("/api/ui/move-sl", {
      method: "POST",
      body: JSON.stringify({ symbol, trigger_price }),
    });
    toast(res.status === "executed" ? "Stop loss updated" : `SL update: ${res.status || "ok"}`);
    refreshDashboard();
  } catch (e) {
    toast(e.message);
  }
}

const DEFAULT_MODEL_BY_PROVIDER = {
  google: "gemini-2.5-flash",
  anthropic: "claude-sonnet-4-6",
  openai: "gpt-4o",
};

function resolveModelForProvider(provider, model) {
  const p = provider || "google";
  const m = (model || "").trim();
  const fallback = DEFAULT_MODEL_BY_PROVIDER[p] || "gemini-2.5-flash";
  if (!m) return fallback;
  if (p === "google" && m.startsWith("gemini")) return m;
  if (p === "anthropic" && m.startsWith("claude")) return m;
  if (p === "openai" && /^(gpt|o[134])/.test(m)) return m;
  return fallback;
}

function applyProviderModelUi(provider, model) {
  const resolved = resolveModelForProvider(provider, model);
  $("#ai-model").value = resolved;
  $("#ai-model").placeholder =
    DEFAULT_MODEL_BY_PROVIDER[provider] || "gemini-2.5-flash";
}

async function loadSettings() {
  try {
    const s = await api("/api/ui/settings");
    $("#binance-status").innerHTML = s.binance_configured
      ? `Connected · key <code>${escapeHtml(s.binance_key_mask)}</code>`
      : '<span class="negative">Not configured — add keys to .env</span>';

    const orch = s.orchestrator || {};
    const lastRun = orch.last_run_at
      ? new Date(orch.last_run_at).toLocaleString()
      : "Never";
    const aiOk = orch.ai_configured
      ? `<span class="positive">Key configured</span>`
      : `<span class="negative">No AI key — add below</span>`;
    $("#orchestrator-status").innerHTML = `
      ${aiOk} · ${escapeHtml(orch.ai_provider || "google")} / ${escapeHtml(orch.ai_model || "—")}<br>
      Trade mode: <strong>${escapeHtml(orch.trade_mode || s.trade_mode)}</strong> · Cycle: ${orch.decision_interval_seconds || 900}s<br>
      Last run: ${escapeHtml(lastRun)} · Status: ${escapeHtml(orch.last_status || "—")}${orch.last_error ? `<br><span class="negative">${escapeHtml(orch.last_error)}</span>` : ""}
    `;

    const provider = s.ai_provider || "google";
    $("#ai-provider").value = provider;
    applyProviderModelUi(provider, s.ai_model);
    if (s.ai_api_key_mask) {
      $("#ai-api-key").placeholder = `Current: ${s.ai_api_key_mask}`;
    }

    const lim = s.limits || {};
    $("#limits-grid").innerHTML = `
      <div class="limit-item"><div class="label">Max Notional</div><div class="value">$${fmt(lim.max_notional_per_order, 0)}</div></div>
      <div class="limit-item"><div class="label">Max Positions</div><div class="value">${lim.max_open_positions}</div></div>
      <div class="limit-item"><div class="label">Max Daily Loss</div><div class="value">$${fmt(lim.max_daily_loss, 0)}</div></div>
      <div class="limit-item"><div class="label">Max Leverage</div><div class="value">${lim.max_leverage}x</div></div>
      <div class="limit-item"><div class="label">Trade Mode</div><div class="value">${escapeHtml(s.trade_mode)}</div></div>
    `;
  } catch (e) {
    console.error("settings", e);
  }
}

async function saveSettings() {
  const provider = $("#ai-provider").value;
  const body = {
    ai_provider: provider,
    ai_model: resolveModelForProvider(provider, $("#ai-model").value),
  };
  const key = $("#ai-api-key").value.trim();
  if (key) body.ai_api_key = key;
  try {
    await api("/api/ui/settings", { method: "POST", body: JSON.stringify(body) });
    $("#ai-api-key").value = "";
    toast("Settings saved");
    loadSettings();
  } catch (e) {
    toast(e.message);
  }
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function openSettings() {
  $("#settings-drawer").classList.remove("hidden");
  loadSettings();
}

function closeSettings() {
  $("#settings-drawer").classList.add("hidden");
}

/* Init */
document.addEventListener("DOMContentLoaded", () => {
  $("#unlock-btn").addEventListener("click", tryUnlock);
  $("#token-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter") tryUnlock();
  });
  $("#logout-btn").addEventListener("click", () => {
    clearToken();
    showLock();
  });
  $("#settings-toggle").addEventListener("click", openSettings);
  $("#settings-close").addEventListener("click", closeSettings);
  $("#settings-backdrop").addEventListener("click", closeSettings);
  $("#save-settings").addEventListener("click", saveSettings);
  $("#ai-provider").addEventListener("change", () => {
    applyProviderModelUi($("#ai-provider").value, $("#ai-model").value);
  });

  initTabs();

  $("#clear-feed-btn")?.addEventListener("click", clearAiFeed);

  if (getToken()) {
    showApp();
  } else {
    showLock();
  }
});
