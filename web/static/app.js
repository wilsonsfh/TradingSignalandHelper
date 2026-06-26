"use strict";

const REAL_MONEY = document.documentElement.dataset.realMoney === "true";

const $ = (sel) => document.querySelector(sel);
const el = (tag, cls, html) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (html != null) n.innerHTML = html;
  return n;
};

const fmt = (n) => (n == null ? "—" : Number(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
const money = (n) => (n == null ? "—" : (n < 0 ? "−$" : "$") + fmt(Math.abs(n)));
const signPct = (n) => (n == null ? "—" : (n >= 0 ? "+" : "−") + Math.abs(n).toFixed(2) + "%");

let latestSignals = {};

async function api(method, url, body) {
  const opts = { method, headers: { "Content-Type": "application/json" } };
  if (body) opts.body = JSON.stringify(body);
  const res = await fetch(url, opts);
  const data = await res.json().catch(() => ({}));
  return { ok: res.ok, status: res.status, data };
}

/* ───────── error banner ───────── */
function showError(msg) {
  const b = $("#errorBanner");
  if (!msg) { b.hidden = true; return; }
  b.textContent = msg;
  b.hidden = false;
}

/* ───────── toasts ───────── */
function toast(msg, kind = "ok") {
  const t = el("div", `toast ${kind}`, msg);
  $("#toastWrap").appendChild(t);
  setTimeout(() => { t.style.opacity = "0"; setTimeout(() => t.remove(), 250); }, 3200);
}

/* ───────── confirm modal ───────── */
let pendingConfirm = null;
function openConfirm({ title, sub, rows, confirmLabel, confirmClass, onConfirm }) {
  $("#modalTitle").textContent = title;
  $("#modalSub").textContent = sub;
  const dl = $("#ticket");
  dl.innerHTML = "";
  rows.forEach(([k, v, cls]) => {
    dl.appendChild(el("dt", null, k));
    dl.appendChild(el("dd", cls || null, v));
  });
  const btn = $("#confirmBtn");
  btn.textContent = confirmLabel || "Confirm";
  btn.className = "btn " + (confirmClass || "");
  pendingConfirm = onConfirm;
  $("#modalOverlay").hidden = false;
  btn.focus();
}
function closeConfirm() { $("#modalOverlay").hidden = true; pendingConfirm = null; }

$("#cancelBtn").addEventListener("click", closeConfirm);
$("#modalOverlay").addEventListener("click", (e) => { if (e.target.id === "modalOverlay") closeConfirm(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("#modalOverlay").hidden) closeConfirm(); });
$("#confirmBtn").addEventListener("click", async () => {
  const fn = pendingConfirm;
  closeConfirm();
  if (fn) await fn();
});

/* ───────── signals ───────── */
function actionChip(action) {
  const map = { BUY: "chip-buy", SELL: "chip-sell", HOLD: "chip-hold" };
  return `<span class="chip ${map[action] || "chip-hold"}">${action}</span>`;
}

function renderSignals(signals) {
  const list = $("#signalList");
  list.innerHTML = "";
  latestSignals = {};
  let actionable = 0;

  if (!signals.length) {
    list.appendChild(el("li", "empty", "No symbols in your watchlist."));
    $("#statSignals").textContent = "0";
    return;
  }

  signals.forEach((s) => {
    latestSignals[s.symbol] = s;
    const tradable = s.action === "BUY" || s.action === "SELL";
    if (tradable) actionable++;

    const row = el("li", "signal-row");
    const left = el("div", "sym", `${s.symbol}${actionChip(s.action)}`);

    const meta = s.take_profit
      ? `entry ${fmt(s.price)} · TP ${fmt(s.take_profit)} · SL ${fmt(s.stop_loss)}`
      : `last ${fmt(s.price)}`;
    const mid = el("div", "sig-mid",
      `<span class="sig-meta">${meta}</span><span class="sig-reason">${s.reason}</span>`);

    const btn = el("button", "btn btn-sm " + (s.action === "SELL" ? "btn-sell" : "btn-buy"),
      s.action === "SELL" ? "Sell" : "Buy");
    if (!tradable) { btn.disabled = true; btn.textContent = "No action"; btn.className = "btn btn-sm btn-ghost"; }
    btn.addEventListener("click", () => confirmTrade(s));

    row.append(left, mid, btn);
    list.appendChild(row);
  });

  $("#statSignals").textContent = String(actionable);
}

function confirmTrade(s) {
  const isSell = s.action === "SELL";
  const rows = [
    ["Symbol", s.symbol],
    ["Side", isSell ? "SELL (close long)" : "BUY (open long)", isSell ? "text-down" : "text-up"],
    ["Order", "Market"],
    ["Entry (ref)", fmt(s.price)],
  ];
  if (!isSell && s.take_profit) {
    rows.push(["Take-profit", fmt(s.take_profit), "text-up"]);
    rows.push(["Stop-loss", fmt(s.stop_loss), "text-down"]);
  }
  openConfirm({
    title: `${isSell ? "Sell" : "Buy"} ${s.symbol}`,
    sub: REAL_MONEY ? "⚠ REAL MONEY — this places a live order." : "Paper trade — fake money.",
    rows,
    confirmLabel: isSell ? "Confirm sell" : "Confirm buy",
    confirmClass: isSell ? "btn-sell" : "btn-buy",
    onConfirm: async () => {
      const { ok, data } = await api("POST", "/api/trade", { symbol: s.symbol, confirm: true });
      if (!ok) { toast(data.message || "Trade failed", "err"); return; }
      const kind = data.status === "OPENED" ? "ok" : data.status === "CLOSED" ? "ok" : "warn";
      toast(data.message, kind);
      refreshAll();
    },
  });
}

/* ───────── positions ───────── */
function rangeMark(p) {
  if (p.stop_loss == null || p.take_profit == null || p.current_price == null) return "";
  const span = p.take_profit - p.stop_loss;
  let pos = span ? ((p.current_price - p.stop_loss) / span) * 100 : 50;
  pos = Math.max(0, Math.min(100, pos));
  return `<div class="range"><span class="mark" style="left:${pos}%"></span></div>`;
}

function renderPositions(positions) {
  const list = $("#positionList");
  list.innerHTML = "";
  let totalPnl = 0;

  if (!positions.length) {
    list.appendChild(el("li", "empty", "No open positions. Place a trade to get started."));
    $("#statPositions").textContent = "0";
    $("#statPnl").textContent = money(0);
    $("#statPnl").className = "stat-value";
    return;
  }

  positions.forEach((p) => {
    totalPnl += p.pnl || 0;
    const dir = (p.pnl || 0) >= 0 ? "text-up" : "text-down";
    const row = el("li", "position-row");
    row.appendChild(el("div", "pos-top",
      `<span class="sym">${p.symbol}<span class="sym-sub">${p.quantity} @ ${fmt(p.avg_price)}</span></span>
       <span class="pos-pnl ${dir}">${money(p.pnl)} <span style="font-size:.8em">(${signPct(p.pnl_pct)})</span></span>`));
    row.appendChild(el("div", "pos-grid",
      `<div class="kv"><span class="k">Current</span><span class="v">${fmt(p.current_price)}</span></div>
       <div class="kv"><span class="k">TP</span><span class="v text-up">${fmt(p.take_profit)}</span></div>
       <div class="kv"><span class="k">SL</span><span class="v text-down">${fmt(p.stop_loss)}</span></div>`));
    const bar = rangeMark(p);
    if (bar) row.appendChild(el("div", null, bar));
    const actions = el("div", "pos-actions");
    const closeBtn = el("button", "btn btn-sm btn-ghost", "Close");
    closeBtn.addEventListener("click", () => confirmClose(p));
    actions.appendChild(closeBtn);
    row.appendChild(actions);
    list.appendChild(row);
  });

  $("#statPositions").textContent = String(positions.length);
  const pnlEl = $("#statPnl");
  pnlEl.textContent = money(totalPnl);
  pnlEl.className = "stat-value " + (totalPnl >= 0 ? "text-up" : "text-down");
}

function confirmClose(p) {
  openConfirm({
    title: `Close ${p.symbol}`,
    sub: "Sell the full position at the current price.",
    rows: [
      ["Symbol", p.symbol],
      ["Quantity", String(p.quantity)],
      ["Avg price", fmt(p.avg_price)],
      ["Current", fmt(p.current_price)],
      ["P&L", money(p.pnl), (p.pnl || 0) >= 0 ? "text-up" : "text-down"],
    ],
    confirmLabel: "Confirm close",
    confirmClass: "btn-sell",
    onConfirm: async () => {
      const { ok, data } = await api("POST", "/api/close", { symbol: p.symbol, confirm: true });
      toast(data.message || (ok ? "Closed" : "Close failed"), ok ? "ok" : "err");
      refreshAll();
    },
  });
}

/* ───────── activity ───────── */
function renderActivity(items) {
  const list = $("#activityList");
  if (!items || !items.length) {
    list.innerHTML = `<li class="activity-empty">No activity yet — place your first trade.</li>`;
    return;
  }
  list.innerHTML = "";
  items.forEach((a) => {
    list.appendChild(el("li", "activity-item",
      `<span class="t">${a.time}</span><span class="badge ${a.type}">${a.type.toUpperCase()}</span><span>${a.symbol} — ${a.message}</span>`));
  });
}

/* ───────── polling ───────── */
async function loadSignals() {
  const { ok, data } = await api("GET", "/api/signals");
  if (!ok) { showError("Could not load signals."); return; }
  showError(null);
  renderSignals(data.signals || []);
}
async function loadState() {
  const { ok, data } = await api("GET", "/api/state");
  if (!ok) { showError("Could not load account state."); return; }
  showError(null);
  renderPositions(data.positions || []);
  renderActivity(data.activity || []);
}
function refreshAll() { loadSignals(); loadState(); }

refreshAll();
setInterval(loadState, 4000);
setInterval(loadSignals, 20000);
