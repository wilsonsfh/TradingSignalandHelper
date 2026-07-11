# First Paper Trade Guide Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add optional, replayable in-product guidance that gets a first-time operator to one monitored mock position in under a minute.

**Architecture:** Add a paper-only semantic guide to the existing template. Vanilla JavaScript owns localStorage dismissal/replay; existing CSS tokens provide a responsive inline strip without changing APIs or adding a modal.

**Tech Stack:** Flask/Jinja, semantic HTML, vanilla JavaScript, CSS, pytest, x-browser.

## Global Constraints

- Paper mode only; never show first-trade prompting in REAL mode.
- Optional and dismissible; never block the workspace.
- Replayable through `How to use`.
- Three steps only: choose BUY, confirm ticket, watch protection.
- No new dependency, modal, coachmark, or decorative animation.
- Preserve all backend/UI contracts and finish at the 151-test gate.
- Do not commit or push.

---

### Task 1: Guide Contract and Markup

**Files:**
- Modify: `tests/test_web_app.py`
- Modify: `web/templates/index.html`

- [ ] Add a failing test asserting `quickStart`, `guideToggle`, `guideDismiss`, and
the three action phrases exist in paper HTML but not REAL HTML.
- [ ] Run the focused test and confirm RED.
- [ ] Add a paper-only `<section id="quickStart">` after the summary rail plus a
`How to use` button in the workspace intro.
- [ ] Run the focused test and confirm GREEN.

### Task 2: Dismissal, Replay, and Styling

**Files:**
- Modify: `web/static/app.js`
- Modify: `web/static/styles.css`
- Modify: `tests/test_web_app.py`

- [ ] Add a failing asset assertion for `signal-desk-guide-dismissed`,
`localStorage.setItem`, and guide replay behavior.
- [ ] Implement first-load visibility, permanent dismissal, and replay through
`guideToggle`; update `aria-expanded` and focus the guide heading when reopened.
- [ ] Style a border-based three-step strip using current tokens; stack steps at
620px; retain 44px mobile controls; add no motion.
- [ ] Run all web tests and the full suite.

### Task 3: Browser Acceptance

- [ ] Verify first visit shows the guide in paper mode.
- [ ] Verify dismiss hides it and persists after reload.
- [ ] Verify `How to use` restores it and moves focus to the guide heading.
- [ ] Verify REAL mode contains no guide markup.
- [ ] Verify 1440/820/390 widths have no overflow and console is clean.
- [ ] Run JS syntax, Impeccable detector, Python compile, and `git diff --check`.
