# Calm Risk Console Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the generic card dashboard with a responsive, safety-first trading workspace that makes broker protection state and pending actions legible before P&L.

**Architecture:** Keep the existing Flask template and API endpoints. Restructure the semantic HTML, centralize position-state presentation and state-dependent actions in vanilla JavaScript, and replace CSS with the selected tokenized Calm Risk Console system.

**Tech Stack:** Flask/Jinja, semantic HTML, vanilla JavaScript, CSS custom properties, pytest, browser acceptance through x-browser.

## Global Constraints

- Preserve all backend/API behavior and the full 143-test backend gate.
- Keep `Signal`, `Position`, and `Activity` as the only first-class UI objects.
- Show position state before P&L/action; unknown-order states must say manual reconciliation.
- One primary action per row or dialog; no duplicate exit action while broker confirmation is pending.
- Dark restrained palette, border-based depth, system sans plus monospace figures.
- Native modal dialog, focus restoration, Escape behavior, visible focus rings.
- Desktop 1440x900, tablet 820x1000, mobile 390x844; no horizontal overflow.
- No repeated row entrance animation on polling; reduced motion removes transforms.
- Do not commit or push.

---

### Task 1: Semantic Workspace and UI Contract

**Files:**
- Modify: `tests/test_web_app.py`
- Modify: `web/templates/index.html`

**Interfaces:**
- Preserves: `statPnl`, `statPositions`, `statSignals`, `errorBanner`, `signalList`, `positionList`, `activityList`, `ticket`, `cancelBtn`, `confirmBtn`, `toastWrap`.
- Adds: `statAttention`, `lastUpdated`, `orderDialog`, `dialogCloseBtn`, `signalCount`, and section descriptions.

- [ ] **Step 1: Write a failing static UI contract test**

```python
def test_index_exposes_risk_console_landmarks():
    app, _ = _app()
    html = app.test_client().get("/").get_data(as_text=True)
    assert 'id="statAttention"' in html
    assert 'id="lastUpdated"' in html
    assert '<dialog' in html and 'id="orderDialog"' in html
    assert 'id="signalCount"' in html
    assert "Protection state" in html
```

- [ ] **Step 2: Verify RED**

Run: `.venv/bin/pytest tests/test_web_app.py::test_index_exposes_risk_console_landmarks -q`

Expected: FAIL because the current template has no attention metric, native dialog,
or protection-state language.

- [ ] **Step 3: Implement the semantic shell**

Use a sticky `<header>`, one `<section class="summary-rail">`, a two-pane
`<div class="workspace-grid">`, and a full-width activity section. Replace the
overlay `<div role="dialog">` with:

```html
<dialog class="order-dialog" id="orderDialog" aria-labelledby="modalTitle">
  <button id="dialogCloseBtn" class="icon-button" aria-label="Close order ticket">...</button>
  <h2 id="modalTitle">Confirm order</h2>
  <p id="modalSub">Review before placing.</p>
  <dl id="ticket"></dl>
  <div class="dialog-actions">...</div>
</dialog>
```

Use specific copy: `Signal Desk`, `Paper workspace`, `Protection state`, and
`Recent activity`.

- [ ] **Step 4: Verify GREEN**

Run: `.venv/bin/pytest tests/test_web_app.py::test_index_exposes_risk_console_landmarks -q`

Expected: PASS.

### Task 2: State-Aware Rendering and Dialog Behavior

**Files:**
- Modify: `web/static/app.js`
- Modify: `tests/test_web_app.py`

**Interfaces:**
- Produces: `positionPresentation(status) -> {label, tone, detail, action}`.
- Position actions: `OPEN -> Close`, `OPEN_UNPROTECTED -> Exit now`,
  `ENTRY_PENDING -> Cancel entry`, pending confirmations and unknown-order states ->
  no automated button.

- [ ] **Step 1: Add failing asset-contract assertions**

```python
def test_frontend_asset_covers_position_safety_states():
    script = Path("web/static/app.js").read_text()
    for state in (
        "OPEN_UNPROTECTED", "ENTRY_PENDING", "ENTRY_CANCEL_PENDING",
        "EXIT_PENDING", "TP_CANCEL_PENDING", "ENTRY_UNKNOWN",
        "OPEN_PROTECTION_UNKNOWN", "EXIT_UNKNOWN",
    ):
        assert state in script
    assert "showModal" in script
    assert "lastFocusedElement" in script
```

- [ ] **Step 2: Verify RED**

Run: `.venv/bin/pytest tests/test_web_app.py::test_frontend_asset_covers_position_safety_states -q`

Expected: FAIL because the current script does not render status families or use a
native dialog.

- [ ] **Step 3: Implement state-aware rendering**

Create one state map with precise labels/details and action descriptors. Render:

- status chip and detail before financial values;
- `Pending` instead of P&L when `avg_price` is zero;
- attention count for every state except `OPEN`;
- accessible button labels containing symbol and operation;
- no action button for confirmation-pending or unknown-order states.

Use text nodes/textContent for API values. Keep `innerHTML` only for static skeleton or
empty-state markup.

- [ ] **Step 4: Implement native dialog and refresh feedback**

Store `lastFocusedElement`, call `orderDialog.showModal()`, close through native
`close()`, and restore focus on the `close` event. Change refresh feedback from an
infinite pulse to `Refreshing...` then `Updated HH:MM:SS`. Show API `message` text in
the persistent error banner.

- [ ] **Step 5: Verify GREEN**

Run: `.venv/bin/pytest tests/test_web_app.py -q`

Expected: all web tests PASS.

### Task 3: Visual System, Responsive Layout, and Browser Gate

**Files:**
- Rewrite: `web/static/styles.css`

**Interfaces:**
- Consumes semantic classes and state tones from Tasks 1-2.
- Produces responsive layouts at 1440px, 820px, and 390px plus reduced-motion behavior.

- [ ] **Step 1: Implement tokens and selected hierarchy**

Define tokens for 4/8px spacing, fixed product type scale, near-black surfaces, teal
accent, green/red direction, amber attention, 6/10px radii, semantic z-index, and
`--ease-out: cubic-bezier(.23,1,.32,1)`. Use borders without wide decorative shadows
for panes and rows.

- [ ] **Step 2: Implement interaction and responsive states**

- Controls: >=44px touch height on mobile, 120ms press scale, visible focus ring.
- Dialog: 180ms centered opacity/scale; native `::backdrop`.
- Toast: 180ms enter, fast exit.
- Rows: no load/poll entrance animation.
- <=900px: workspace panes stack.
- <=620px: header wraps, summary remains three compact columns, signal rows and
  position headers become two-column layouts, buttons span available width where
  needed.
- Reduced motion: no transforms or movement.

- [ ] **Step 3: Run automated verification**

```bash
.venv/bin/pytest -q
.venv/bin/python -m compileall -q broker data signals state strategy trader web
git diff --check
```

Expected: PASS/no output from compile and diff checks.

- [ ] **Step 4: Run live browser acceptance**

Start the app in isolated mock state, then verify with x-browser at 1440x900,
820x1000, and 390x844:

- no horizontal overflow;
- mode, summary, status, signals, positions, and activity hierarchy;
- dialog opens, receives focus, closes on Escape, and restores focus;
- pending/unknown status fixtures render without an automated action;
- error and empty states remain legible;
- console has no application errors.

- [ ] **Step 5: Record the final design ledger**

Update the completion report with direction, rejected alternatives, status vocabulary,
responsive decisions, motion purpose/frequency, and objective browser/test evidence.
