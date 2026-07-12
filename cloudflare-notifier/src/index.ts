/**
 * signal-notifier — TradingView webhook -> Telegram, on Cloudflare Workers.
 *
 * The always-on edge front for TradingSignalandHelper: TradingView fires a chart-event
 * alert at POST /webhook; this Worker authenticates it, records it (KV), and pushes a
 * Telegram message. It mirrors the Python bridge's alert schema (honors alert
 * tp/sl/quantity) but does NOT place orders — live moomoo/OpenD execution needs a
 * persistent host (local Mac / VM / Zo Computer), which Workers cannot be.
 *
 * Auth model (same account as danes-musings, deployed via Wrangler under wilsonsfh):
 *   - POST /webhook  : machine path. Shared secret in the body `key` (+ optional HMAC
 *                      X-Signature, + optional TradingView IP allow-list). Must stay
 *                      reachable by TradingView, so do NOT put interactive Access on it.
 *   - GET  / , /api/events : human path. Protect with one-click Cloudflare Access
 *                      (Workers & Pages -> Settings -> Domains & Routes -> Enable Access),
 *                      so only your browser SSO can read the dashboard.
 */

interface Env {
  EVENTS: KVNamespace;
  WEBHOOK_SECRET: string;
  TELEGRAM_BOT_TOKEN: string;
  TELEGRAM_CHAT_ID: string;
  TRADINGVIEW_IP_ALLOWLIST: string;
  MAX_ALERT_QUANTITY: string;
  WEBHOOK_MAX_AGE_SECONDS: string;
}

interface AlertEvent {
  time: string;
  source: string;
  symbol: string;
  action: string;
  quantity: number | null;
  tp: number | null;
  sl: number | null;
  status: string;
  message: string;
  event_id: string | null;
}

class AlertError extends Error {
  constructor(message: string, readonly status = 400, readonly label = "ERROR") {
    super(message);
  }
}

const OPEN = new Set(["open", "buy", "long"]);
const CLOSE = new Set(["close", "sell", "short", "exit"]);
const JSON_HEADERS = { "content-type": "application/json" };

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: JSON_HEADERS });
}

async function sha256(input: string): Promise<Uint8Array> {
  return new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(input)));
}

// Constant-time, length-agnostic comparison (compare digests, not raw strings).
async function safeEqual(a: string, b: string): Promise<boolean> {
  const [da, db] = await Promise.all([sha256(a), sha256(b)]);
  let diff = 0;
  for (let i = 0; i < da.length; i++) diff |= da[i] ^ db[i];
  return diff === 0;
}

async function hmacHex(secret: string, body: string): Promise<string> {
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const sig = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(body));
  return [...new Uint8Array(sig)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

function price(value: unknown, name: string): number | null {
  if (value === null || value === undefined) return null;
  if (typeof value === "boolean") throw new AlertError(`${name} must be a number`);
  const n = Number(value);
  if (!Number.isFinite(n) || n <= 0) throw new AlertError(`${name} must be a positive, finite price`);
  return Math.round(n * 10000) / 10000;
}

function parseAlert(body: Record<string, unknown>, env: Env): AlertEvent & { occurred_at: number } {
  const eventId = String(body.event_id ?? "").trim();
  const timestamp = String(body.timestamp ?? "").trim();
  if (!eventId || !timestamp) throw new AlertError("event_id and timestamp are required");
  const occurredAt = Date.parse(timestamp);
  if (Number.isNaN(occurredAt)) throw new AlertError("timestamp must be ISO-8601");
  const ageSec = Math.abs(Date.now() - occurredAt) / 1000;
  if (ageSec > Number(env.WEBHOOK_MAX_AGE_SECONDS || "300")) {
    throw new AlertError("alert is too old or too far in the future", 400, "EXPIRED");
  }

  const actionRaw = String(body.action ?? "").toLowerCase().trim();
  const sideRaw = String(body.side ?? "").toLowerCase().trim();
  const tokens = new Set([actionRaw, sideRaw]);
  let action: string;
  if (actionRaw !== "open" && [...CLOSE].some((t) => tokens.has(t))) action = "close";
  else if ([...OPEN].some((t) => tokens.has(t))) action = "open";
  else throw new AlertError("could not determine open/buy or close/sell");

  const symbol = String(body.symbol ?? "").toUpperCase().trim();
  if (!symbol) throw new AlertError("symbol is required");

  let quantity: number | null = null;
  if (body.quantity !== null && body.quantity !== undefined) {
    const q = Number(body.quantity);
    if (!Number.isInteger(q) || q <= 0) throw new AlertError("quantity must be a positive integer");
    if (q > Number(env.MAX_ALERT_QUANTITY || "100")) throw new AlertError("quantity exceeds MAX_ALERT_QUANTITY");
    quantity = q;
  }

  const tp = price(body.tp, "tp");
  const sl = price(body.sl, "sl");
  if (action === "open" && tp !== null && sl !== null && !(sl < tp)) {
    throw new AlertError("stop_loss must be below take_profit for a long entry");
  }

  return {
    time: new Date().toISOString().slice(11, 19),
    source: "tradingview",
    symbol, action, quantity, tp, sl,
    status: "RECEIVED", message: "", event_id: eventId,
    occurred_at: occurredAt,
  };
}

async function recordEvent(env: Env, ev: AlertEvent): Promise<void> {
  const raw = await env.EVENTS.get("recent");
  const list: AlertEvent[] = raw ? JSON.parse(raw) : [];
  list.unshift(ev);
  await env.EVENTS.put("recent", JSON.stringify(list.slice(0, 50)));
}

async function sendTelegram(env: Env, text: string): Promise<void> {
  if (!env.TELEGRAM_BOT_TOKEN || !env.TELEGRAM_CHAT_ID) return;
  await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/sendMessage`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({
      chat_id: env.TELEGRAM_CHAT_ID,
      text,
      parse_mode: "HTML",
      disable_web_page_preview: true,
    }),
  });
}

function telegramText(ev: AlertEvent): string {
  const icon = ev.status === "RECEIVED" ? (ev.action === "close" ? "📕" : "📈") : "⛔";
  const head = `${icon} <b>${ev.symbol}</b> ${ev.action.toUpperCase()}`;
  if (ev.status !== "RECEIVED") return `${head}\nrejected — ${ev.message} (${ev.status})`;
  const levels = ev.quantity != null || ev.tp != null || ev.sl != null
    ? `\nqty ${ev.quantity ?? "—"} · TP ${ev.tp ?? "—"} · SL ${ev.sl ?? "—"}`
    : "";
  return `${head}${levels}\n<i>tradingview · ${ev.time} UTC</i>`;
}

async function handleWebhook(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
  if ((env.WEBHOOK_SECRET ?? "").trim().length < 32) {
    return json({ status: "MISCONFIGURED", message: "set a >=32-char WEBHOOK_SECRET" }, 503);
  }
  const allow = (env.TRADINGVIEW_IP_ALLOWLIST || "").split(",").map((s) => s.trim()).filter(Boolean);
  const ip = request.headers.get("CF-Connecting-IP") || "";
  if (allow.length && !allow.includes(ip)) {
    return json({ status: "IP_FORBIDDEN", message: "source IP is not allow-listed" }, 403);
  }

  const raw = await request.text();
  const sig = request.headers.get("X-Signature");
  if (sig && !(await safeEqual(sig, await hmacHex(env.WEBHOOK_SECRET, raw)))) {
    return json({ status: "BAD_SIGNATURE", message: "invalid signature" }, 401);
  }

  let body: Record<string, unknown>;
  try {
    const parsed = JSON.parse(raw);
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) throw new Error();
    body = parsed as Record<string, unknown>;
  } catch {
    return json({ status: "ERROR", message: "JSON body must be an object" }, 400);
  }

  if (!(await safeEqual(String(body.key ?? ""), env.WEBHOOK_SECRET))) {
    return json({ status: "UNAUTHORIZED", message: "bad or missing key" }, 401);
  }

  let ev: AlertEvent & { occurred_at: number };
  try {
    ev = parseAlert(body, env);
  } catch (e) {
    const err = e as AlertError;
    const rej: AlertEvent = {
      time: new Date().toISOString().slice(11, 19), source: "tradingview",
      symbol: String(body.symbol ?? "?").toUpperCase().slice(0, 12) || "?",
      action: String(body.action ?? "?").slice(0, 12), quantity: null, tp: null, sl: null,
      status: err.label, message: err.message, event_id: String(body.event_id ?? "") || null,
    };
    ctx.waitUntil(Promise.all([recordEvent(env, rej), sendTelegram(env, telegramText(rej))]));
    return json({ status: err.label, message: err.message }, err.status);
  }

  const dedupeKey = `evt:${ev.event_id}`;
  if (await env.EVENTS.get(dedupeKey)) {
    return json({ status: "REPLAY", message: "event_id was already processed" }, 409);
  }
  await env.EVENTS.put(dedupeKey, "1", { expirationTtl: 86400 });

  ev.status = "OK";
  ev.message = ev.action === "open" ? "signal received (open)" : "signal received (close)";
  ctx.waitUntil(Promise.all([recordEvent(env, ev), sendTelegram(env, telegramText(ev))]));
  return json({ status: ev.status, symbol: ev.symbol, action: ev.action });
}

async function dashboard(env: Env): Promise<Response> {
  const raw = await env.EVENTS.get("recent");
  const list: AlertEvent[] = raw ? JSON.parse(raw) : [];
  const rows = list.map((e) => {
    const tone = e.status === "OK" ? "#5bd18c" : "#ff8994";
    const lv = e.quantity != null || e.tp != null || e.sl != null
      ? `qty ${e.quantity ?? "—"} · TP ${e.tp ?? "—"} · SL ${e.sl ?? "—"}` : (e.message || "");
    return `<tr><td class="t">${e.time}</td><td><b>${e.symbol}</b> ${e.action.toUpperCase()}</td>
      <td class="lv">${lv}</td><td style="color:${tone}">${e.status}</td></tr>`;
  }).join("");
  const html = `<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow"><title>Signal Notifier</title>
<style>body{margin:0;background:#090c10;color:#edf1f4;font:14px/1.5 Inter,system-ui,sans-serif;padding:24px}
h1{font-size:18px;margin:0 0 4px}p{color:#a3adb7;margin:0 0 16px;font-size:12px}
table{width:100%;border-collapse:collapse}td{border-bottom:1px solid #29323c;padding:8px 6px;font-size:13px;vertical-align:top}
.t{color:#a3adb7;font-family:monospace;font-size:11px;white-space:nowrap}.lv{color:#a3adb7;font-family:monospace;font-size:12px}
.empty{color:#a3adb7;padding:24px 0}</style>
<h1>Incoming alerts</h1><p>TradingView events received by the notifier (latest ${list.length}).</p>
${list.length ? `<table>${rows}</table>` : `<div class="empty">No alerts yet.</div>`}`;
  return new Response(html, { headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store" } });
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);
    if (request.method === "POST" && url.pathname === "/webhook") return handleWebhook(request, env, ctx);
    if (request.method === "GET" && url.pathname === "/api/events") {
      const raw = await env.EVENTS.get("recent");
      return json({ events: raw ? JSON.parse(raw) : [] });
    }
    if (request.method === "GET" && (url.pathname === "/" || url.pathname === "")) return dashboard(env);
    return json({ status: "NOT_FOUND" }, 404);
  },
} satisfies ExportedHandler<Env>;
