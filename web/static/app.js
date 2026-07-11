"use strict";

const REAL_MONEY = document.documentElement.dataset.realMoney === "true";
const ORDER_QUANTITY = Number(document.documentElement.dataset.quantity || 1);
let latestPositionsBySymbol = new Map();
let signalRequestVersion = 0;
let stateRequestVersion = 0;
const QUICK_START_STORAGE_KEY = "signal-desk-guide-dismissed";

const $ = (selector) => document.querySelector(selector);
const node = (tag, className, text) => {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text != null) element.textContent = text;
  return element;
};

const fmt = (value) => value == null
  ? "—"
  : Number(value).toLocaleString("en-US", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
const money = (value) => value == null
  ? "—"
  : `${value < 0 ? "−" : "+"}$${fmt(Math.abs(value))}`;
const signPct = (value) => value == null
  ? "—"
  : `${value >= 0 ? "+" : "−"}${Math.abs(value).toFixed(2)}%`;

const POSITION_PRESENTATIONS = {
  OPEN: {
    label: "Monitored",
    tone: "safe",
    detail: "TP/SL watch active",
    action: "close",
    actionLabel: "Close position",
  },
  OPEN_UNPROTECTED: {
    label: "Soft monitor only",
    tone: "attention",
    detail: "Broker protection unavailable",
    action: "close",
    actionLabel: "Exit now",
  },
  ENTRY_PENDING: {
    label: "Entry pending",
    tone: "pending",
    detail: "Awaiting broker fill",
    action: "cancel-entry",
    actionLabel: "Cancel entry",
  },
  ENTRY_CANCEL_PENDING: {
    label: "Cancellation pending",
    tone: "pending",
    detail: "Do not submit another cancellation",
    action: null,
  },
  EXIT_PENDING: {
    label: "Exit pending",
    tone: "pending",
    detail: "Monitoring until fill confirmation",
    action: null,
  },
  TP_CANCEL_PENDING: {
    label: "Protection cancellation pending",
    tone: "pending",
    detail: "Exit waits for final protected quantity",
    action: null,
  },
  ENTRY_UNKNOWN: {
    label: "Manual reconciliation",
    tone: "danger",
    detail: "Entry accepted without a trackable order ID",
    action: null,
  },
  OPEN_PROTECTION_UNKNOWN: {
    label: "Manual reconciliation",
    tone: "danger",
    detail: "Protection order identity is unknown",
    action: null,
  },
  EXIT_UNKNOWN: {
    label: "Manual reconciliation",
    tone: "danger",
    detail: "Exit accepted without a trackable order ID",
    action: null,
  },
};

function positionPresentation(status) {
  return POSITION_PRESENTATIONS[status] || {
    label: "Manual attention",
    tone: "danger",
    detail: `Unrecognized broker state: ${status || "unknown"}`,
    action: null,
  };
}

async function api(method, url, body) {
  const options = { method, headers: { "Content-Type": "application/json" } };
  if (body !== undefined) options.body = JSON.stringify(body);
  try {
    const response = await fetch(url, options);
    const data = await response.json().catch(() => ({}));
    return { ok: response.ok, status: response.status, data };
  } catch (error) {
    return {
      ok: false,
      status: 0,
      data: { message: `Network error: ${error.message || "request failed"}` },
    };
  }
}

const errors = { signals: null, state: null };
function renderErrors() {
  const banner = $("#errorBanner");
  const messages = Object.values(errors).filter(Boolean);
  banner.hidden = messages.length === 0;
  banner.textContent = messages.join(" · ");
}

function setError(source, message) {
  errors[source] = message || null;
  renderErrors();
}

function setRefreshStatus(refreshing, incomplete = false) {
  const status = $("#lastUpdated");
  status.classList.toggle("is-refreshing", refreshing);
  status.textContent = refreshing
    ? "Refreshing…"
    : incomplete
      ? "Refresh incomplete"
      : `Updated ${new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}`;
}

function toast(message, kind = "ok") {
  const item = node("div", `toast ${kind}`, message);
  $("#toastWrap").appendChild(item);
  window.setTimeout(() => {
    item.classList.add("is-leaving");
    window.setTimeout(() => item.remove(), 150);
  }, 3200);
}

const orderDialog = $("#orderDialog");
let pendingConfirm = null;
let lastFocusedElement = null;
let lastFocusedLabel = null;

function openConfirm({ title, sub, rows, confirmLabel, confirmClass, onConfirm, trigger }) {
  lastFocusedElement = trigger || document.activeElement;
  lastFocusedLabel = lastFocusedElement?.getAttribute?.("aria-label") || null;
  $("#modalTitle").textContent = title;
  $("#modalSub").textContent = sub;
  const ticket = $("#ticket");
  ticket.replaceChildren();
  rows.forEach(([label, value, className]) => {
    ticket.appendChild(node("dt", null, label));
    ticket.appendChild(node("dd", className || null, value));
  });
  const confirmButton = $("#confirmBtn");
  confirmButton.textContent = confirmLabel || "Confirm";
  confirmButton.className = `btn ${confirmClass || ""}`.trim();
  pendingConfirm = onConfirm;
  orderDialog.showModal();
  confirmButton.focus();
}

function closeConfirm() {
  if (orderDialog.open) orderDialog.close();
}

function restoreDialogFocus(element, label) {
  window.setTimeout(() => {
    const fallback = label
      ? Array.from(document.querySelectorAll("[aria-label]")).find(
          (candidate) => candidate.getAttribute("aria-label") === label,
        )
      : null;
    const target = element?.isConnected ? element : fallback;
    target?.focus();
  }, 50);
}

$("#cancelBtn").addEventListener("click", closeConfirm);
$("#dialogCloseBtn").addEventListener("click", closeConfirm);
orderDialog.addEventListener("cancel", (event) => {
  event.preventDefault();
  closeConfirm();
});
orderDialog.addEventListener("close", () => {
  pendingConfirm = null;
  restoreDialogFocus(lastFocusedElement, lastFocusedLabel);
  lastFocusedElement = null;
  lastFocusedLabel = null;
});
$("#confirmBtn").addEventListener("click", async () => {
  const action = pendingConfirm;
  closeConfirm();
  if (action) await action();
});

function actionChip(action) {
  const classes = { BUY: "chip-buy", SELL: "chip-sell", HOLD: "chip-hold" };
  return node("span", `chip ${classes[action] || "chip-hold"}`, action);
}

function emptyState(title, detail) {
  const item = node("li", "empty-state");
  item.append(node("strong", null, title), node("span", null, detail));
  return item;
}

function renderSignals(signals) {
  const list = $("#signalList");
  const focusedControlLabel = document.activeElement?.getAttribute?.("aria-label") || null;
  list.replaceChildren();
  list.setAttribute("aria-busy", "false");
  let actionable = 0;

  if (!signals.length) {
    list.appendChild(emptyState("No watchlist symbols", "Add symbols through WATCHLIST configuration, then refresh."));
    $("#statSignals").textContent = "0";
    return;
  }

  signals.forEach((signal) => {
    const tradable = signal.action === "BUY" || signal.action === "SELL";
    if (tradable) actionable += 1;
    const row = node("li", "signal-row");
    const identity = node("div", "signal-identity");
    identity.append(node("strong", "ticker", signal.symbol), actionChip(signal.action));
    const details = node("div", "signal-details");
    details.append(
      node("span", "signal-levels", signal.take_profit
        ? `Entry ${fmt(signal.price)} · TP ${fmt(signal.take_profit)} · SL ${fmt(signal.stop_loss)}`
        : `Last ${fmt(signal.price)}`),
      node("span", "signal-reason", signal.reason || "No strategy explanation available"),
    );
    row.append(identity, details);

    if (tradable) {
      const button = node("button", `btn btn-sm ${signal.action === "SELL" ? "btn-sell" : "btn-buy"}`, "Review");
      button.type = "button";
      button.setAttribute("aria-label", `Review ${signal.action.toLowerCase()} for ${signal.symbol}`);
      button.addEventListener("click", () => confirmTrade(signal, button));
      row.appendChild(button);
    } else {
      row.appendChild(node("span", "no-action", "No action"));
    }
    list.appendChild(row);
  });

  $("#statSignals").textContent = String(actionable);
  if (focusedControlLabel) {
    const replacement = Array.from(list.querySelectorAll("[aria-label]")).find(
      (element) => element.getAttribute("aria-label") === focusedControlLabel,
    );
    replacement?.focus({ preventScroll: true });
  }
}

function confirmTrade(signal, trigger) {
  const isSell = signal.action === "SELL";
  const trackedPosition = latestPositionsBySymbol.get(signal.symbol);
  if (isSell && !trackedPosition) {
    toast("Cannot review sell: tracked position quantity is unavailable.", "warn");
    return;
  }
  const ticketQuantity = isSell
    ? trackedPosition?.quantity ?? "No tracked position"
    : ORDER_QUANTITY;
  const rows = [
    ["Symbol", signal.symbol],
    ["Action", isSell ? "Sell to close" : "Buy to open", isSell ? "text-down" : "text-up"],
    ["Quantity", String(ticketQuantity)],
    ["Order", "Market"],
    ["Reference", fmt(signal.price)],
  ];
  if (!isSell && signal.take_profit != null) {
    rows.push(["Take-profit", fmt(signal.take_profit), "text-up"]);
    rows.push(["Stop-loss", fmt(signal.stop_loss), "text-down"]);
  }
  openConfirm({
    title: `${isSell ? "Review sell" : "Review buy"} · ${signal.symbol}`,
    sub: REAL_MONEY
      ? "LIVE MONEY. Confirming places a real broker order."
      : "Paper order. No real money will move.",
    rows,
    confirmLabel: isSell ? "Confirm sell" : "Confirm buy",
    confirmClass: isSell ? "btn-sell" : "btn-buy",
    trigger,
    onConfirm: async () => {
      const { ok, data } = await api("POST", "/api/trade", {
        symbol: signal.symbol,
        confirm: true,
      });
      if (!ok) {
        toast(data.message || "Trade failed", "err");
        return;
      }
      const kind = ["OPENED", "CLOSED"].includes(data.status) ? "ok" : "warn";
      toast(data.message || data.status, kind);
      await refreshAll();
    },
  });
}

function rangeMark(position) {
  if (position.stop_loss == null || position.take_profit == null || position.current_price == null) return null;
  const span = position.take_profit - position.stop_loss;
  const ratio = span ? ((position.current_price - position.stop_loss) / span) * 100 : 50;
  const range = node("div", "risk-range");
  range.setAttribute("aria-label", `Current price within stop-loss to take-profit range: ${Math.round(Math.max(0, Math.min(100, ratio)))} percent`);
  const marker = node("span", "risk-marker");
  marker.style.left = `${Math.max(0, Math.min(100, ratio))}%`;
  range.appendChild(marker);
  return range;
}

function stateChip(presentation) {
  return node("span", `state-chip state-${presentation.tone}`, presentation.label);
}

function renderPositions(positions) {
  const list = $("#positionList");
  latestPositionsBySymbol = new Map(
    positions.map((position) => [position.symbol, position]),
  );
  list.replaceChildren();
  list.setAttribute("aria-busy", "false");
  let totalPnl = 0;
  let attentionCount = 0;

  if (!positions.length) {
    list.appendChild(emptyState("No active capital", "Review an actionable signal before opening a paper position."));
    $("#statPositions").textContent = "0";
    $("#statAttention").textContent = "0";
    $("#statPnl").textContent = "+$0.00";
    $("#statPnl").className = "summary-value";
    return;
  }

  positions.forEach((position) => {
    const presentation = positionPresentation(position.status);
    if (presentation.tone !== "safe") attentionCount += 1;
    const hasBasis = Number(position.avg_price) > 0;
    if (hasBasis) totalPnl += position.pnl || 0;

    const row = node("li", `position-row position-${presentation.tone}`);
    const top = node("div", "position-top");
    const identity = node("div", "position-identity");
    identity.append(
      node("strong", "ticker", position.symbol),
      node("span", "position-basis", hasBasis
        ? `${position.quantity} @ ${fmt(position.avg_price)}`
        : `${position.quantity} · basis pending`),
    );
    top.appendChild(identity);

    const state = node("div", "position-state");
    const stateCopy = node("div", "state-copy");
    stateCopy.append(
      stateChip(presentation),
      node("span", "state-detail", presentation.detail),
      node("span", "sr-only", `Exact broker state: ${position.status}`),
    );
    state.appendChild(stateCopy);

    const financial = node("div", "position-financial");
    const pnl = node("div", `position-pnl ${(position.pnl || 0) >= 0 ? "text-up" : "text-down"}`);
    pnl.append(
      node("strong", null, hasBasis ? money(position.pnl) : "Pending"),
      node("span", null, hasBasis ? signPct(position.pnl_pct) : position.status),
    );
    financial.appendChild(pnl);

    const metrics = node("dl", "position-metrics");
    [
      ["Current", fmt(position.current_price)],
      ["Take-profit", fmt(position.take_profit), "text-up"],
      ["Stop-loss", fmt(position.stop_loss), "text-down"],
    ].forEach(([label, value, className]) => {
      const group = node("div", "metric-pair");
      group.append(node("dt", null, label), node("dd", className || null, value));
      metrics.appendChild(group);
    });

    row.append(top, state, financial, metrics);
    const range = rangeMark(position);
    if (range) row.appendChild(range);

    const actionArea = node("div", "position-actions");
    if (presentation.action) {
      const className = presentation.tone === "danger"
        ? "btn btn-sm btn-danger"
        : presentation.action === "cancel-entry"
          ? "btn btn-sm btn-warning"
          : "btn btn-sm btn-ghost";
      const button = node("button", className, presentation.actionLabel);
      button.type = "button";
      button.setAttribute("aria-label", `${presentation.actionLabel} for ${position.symbol}`);
      button.addEventListener("click", () => confirmPositionAction(position, presentation, button));
      actionArea.appendChild(button);
    } else {
      actionArea.appendChild(node("span", "action-locked", presentation.tone === "danger"
        ? "Automation paused"
        : "Broker confirmation pending"));
    }
    row.appendChild(actionArea);
    list.appendChild(row);
  });

  $("#statPositions").textContent = String(positions.length);
  $("#statAttention").textContent = String(attentionCount);
  const pnl = $("#statPnl");
  pnl.textContent = money(totalPnl);
  pnl.className = `summary-value ${totalPnl >= 0 ? "text-up" : "text-down"}`;
}

function confirmPositionAction(position, presentation, trigger) {
  const cancellingEntry = presentation.action === "cancel-entry";
  openConfirm({
    title: `${cancellingEntry ? "Cancel entry" : presentation.actionLabel} · ${position.symbol}`,
    sub: REAL_MONEY
      ? "LIVE MONEY. Review the broker action before confirming."
      : cancellingEntry
        ? "Cancel the unfilled remainder. Any partial fill remains tracked."
        : "Submit an exit for the full tracked quantity. Monitoring continues until fill confirmation.",
    rows: [
      ["Symbol", position.symbol],
      ["Protection state", presentation.label],
      ["Quantity", String(position.quantity)],
      ["Order", "Market"],
      ["Average", Number(position.avg_price) > 0 ? fmt(position.avg_price) : "Pending"],
      ["Current", fmt(position.current_price)],
      ["Unrealized P&L", Number(position.avg_price) > 0 ? money(position.pnl) : "Pending"],
    ],
    confirmLabel: cancellingEntry ? "Confirm cancellation" : "Confirm exit",
    confirmClass: cancellingEntry ? "btn-warning" : "btn-danger",
    trigger,
    onConfirm: async () => {
      const { ok, data } = await api("POST", "/api/close", {
        symbol: position.symbol,
        confirm: true,
      });
      toast(data.message || (ok ? "Action submitted" : "Action failed"), ok ? "ok" : "err");
      await refreshAll();
    },
  });
}

function renderActivity(items) {
  const list = $("#activityList");
  list.replaceChildren();
  if (!items?.length) {
    list.appendChild(emptyState("No activity yet", "Orders, monitor updates, and errors appear here."));
    return;
  }
  items.forEach((activity) => {
    const item = node("li", "activity-item");
    item.append(
      node("time", "activity-time", activity.time),
      node("span", `activity-badge activity-${activity.type}`, String(activity.type).toUpperCase()),
      node("span", "activity-message", `${activity.symbol} · ${activity.message}`),
    );
    list.appendChild(item);
  });
}

async function loadSignals() {
  const requestVersion = ++signalRequestVersion;
  $("#signalList").setAttribute("aria-busy", "true");
  const { ok, data } = await api("GET", "/api/signals");
  if (requestVersion !== signalRequestVersion) return;
  if (!ok) {
    setError("signals", data.message || "Could not load signals");
    $("#signalList").setAttribute("aria-busy", "false");
    return;
  }
  setError("signals", null);
  renderSignals(data.signals || []);
}

async function loadState() {
  const requestVersion = ++stateRequestVersion;
  $("#positionList").setAttribute("aria-busy", "true");
  const { ok, data } = await api("GET", "/api/state");
  if (requestVersion !== stateRequestVersion) return;
  if (!ok) {
    setError("state", data.message || "Could not load account state");
    $("#positionList").setAttribute("aria-busy", "false");
    return;
  }
  setError("state", null);
  renderPositions(data.positions || []);
  renderActivity(data.activity || []);
}

async function refreshAll() {
  setRefreshStatus(true);
  await Promise.all([loadSignals(), loadState()]);
  setRefreshStatus(false, Object.values(errors).some(Boolean));
}

function showQuickStart(show, focus = false) {
  const guide = $("#quickStart");
  const toggle = $("#guideToggle");
  if (!guide || !toggle) return;
  guide.hidden = !show;
  toggle.setAttribute("aria-expanded", String(show));
  if (show && focus) $("#quickStartTitle")?.focus();
}

function initializeQuickStart() {
  const guide = $("#quickStart");
  const toggle = $("#guideToggle");
  const dismiss = $("#guideDismiss");
  if (!guide || !toggle || !dismiss) return;
  let dismissed = false;
  try {
    dismissed = window.localStorage.getItem(QUICK_START_STORAGE_KEY) === "true";
  } catch (_error) {
    dismissed = false;
  }
  showQuickStart(!dismissed);
  dismiss.addEventListener("click", () => {
    try {
      window.localStorage.setItem(QUICK_START_STORAGE_KEY, "true");
    } catch (_error) {
      // The guide still dismisses for this page when storage is unavailable.
    }
    showQuickStart(false);
    toggle.focus();
  });
  toggle.addEventListener("click", () => showQuickStart(true, true));
}

initializeQuickStart();
refreshAll();
window.setInterval(() => {
  if (document.visibilityState === "visible") {
    setRefreshStatus(true);
    loadState().then(() => setRefreshStatus(false, Object.values(errors).some(Boolean)));
  }
}, 4000);
window.setInterval(() => {
  if (document.visibilityState === "visible") {
    setRefreshStatus(true);
    loadSignals().then(() => setRefreshStatus(false, Object.values(errors).some(Boolean)));
  }
}, 20000);
