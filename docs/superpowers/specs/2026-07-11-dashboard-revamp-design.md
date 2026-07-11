# Trading Dashboard Revamp Design

**Date:** 2026-07-11
**Status:** Selected under autonomous-continuity instruction
**Direction:** Calm risk console
**Comparison:** `docs/superpowers/mockups/2026-07-11-dashboard-options.html`

## Goal

Revamp the local trading dashboard so a single operator can answer, in order:

1. Is the system in paper or live mode?
2. Does any position need attention?
3. What capital is active and how is it protected?
4. Which signal is worth reviewing next?
5. What just happened?

The UI must preserve every backend/API behavior and remain useful in mock mode with
no credentials.

## Selected Direction

**Calm risk console** uses a restrained dark workspace, a single summary rail,
side-by-side signal and position panes, and an audit activity strip. It won over:

- **Daylight decision ledger:** readable but needlessly replaces the established dark
  foundation and weakens live operational scanning.
- **Focus queue:** strongest single-next-action hierarchy but hides portfolio breadth
  and slows repeated desktop scanning.

## Conceptual Model

The product exposes three first-class objects only:

- **Signal:** symbol, action, reference price, TP/SL, and reason.
- **Position:** symbol, quantity, entry/current prices, P&L, TP/SL, and broker state.
- **Activity:** timestamp, event type, symbol, and message.

Broker states collapse into three user-facing families:

| Family | Broker states | User-facing language |
|---|---|---|
| Monitored | `OPEN` | Monitored; TP/SL watch active |
| In progress | `ENTRY_PENDING`, `ENTRY_CANCEL_PENDING`, `EXIT_PENDING`, `TP_CANCEL_PENDING` | Entry pending, cancellation pending, or exit pending |
| Manual attention | `OPEN_UNPROTECTED`, `ENTRY_UNKNOWN`, `OPEN_PROTECTION_UNKNOWN`, `EXIT_UNKNOWN` | Soft monitor only or manual reconciliation required |

The exact broker state remains available in accessible detail text, but raw enum
names are not the primary label.

## Interaction Contract

### Workspace

- Mode and refresh health remain visible in the sticky header.
- Summary rail shows unrealized P&L, active positions, and attention count.
- Signal pane shows actionable count in its own header.
- Position status appears before its action.
- Activity is an audit ledger, not decoration.

### Position actions

| State | Action |
|---|---|
| `OPEN` | Close position |
| `OPEN_UNPROTECTED` | Exit now |
| `ENTRY_PENDING` | Cancel entry |
| `ENTRY_CANCEL_PENDING`, `EXIT_PENDING`, `TP_CANCEL_PENDING` | No duplicate action; explain that broker confirmation is pending |
| Unknown-order states | No automated action; require manual reconciliation |

### Confirmation ticket

- Remains a centered modal because the action is occasional and consequential.
- Uses native dialog semantics, restores focus to the trigger, closes on Escape, and
  blocks background interaction.
- Shows symbol, side/action, quantity, order type, reference/current price, TP/SL, and
  explicit paper-vs-real warning.
- Confirmation remains the single primary action.

### Edges

- Loading: skeletons, not a central spinner.
- Empty signals: explain that the watchlist is empty.
- Empty positions: explain that no capital is active and point to signals.
- Dependency errors: show the API message in a persistent banner; do not erase the
  other pane's last valid content.
- Pending/unknown positions with zero average price never display fabricated P&L.

## Visual System

- Preserve a dark, low-glare workspace for a desk user checking positions throughout
  the day and evening.
- Restrained color strategy: near-black neutrals, teal for primary/focus, green/red
  for market direction, amber for pending/attention.
- Use borders for depth; remove decorative wide shadows from panels.
- One system sans family plus monospace for prices/timestamps.
- Tabular numerals for all financial values.
- Radius: 6px controls, 10px panes, pills only for compact statuses.
- Accent is earned by mode/focus/primary action, never wallpaper.

## Responsive Behavior

- Desktop: summary rail, signals/positions split, full-width activity.
- Tablet: panes stack; summary remains compact.
- Mobile: header wraps, summary becomes a compact three-column strip, rows become
  two-column compositions, actions use at least 44px touch height, and long reasons
  wrap without overflow.

## Motion

- Remove infinite refresh pulsing and repeated row entrance animations on polling.
- Button press: 120ms scale feedback.
- Modal: 180ms opacity/scale from `0.97`, centered origin.
- Toast: 180ms translate/opacity transition; fast exit.
- No animation for high-frequency data refreshes.
- `prefers-reduced-motion` removes transforms while retaining instant/opacity feedback.

## Accessibility

- Semantic sections/headings and live regions remain.
- Visible `:focus-visible` ring on every control.
- WCAG AA text contrast; muted copy remains readable.
- Status never relies on color alone.
- Dialog focus is restored and background is inert through native modal behavior.
- Buttons expose precise labels such as `Review buy for AAPL` and `Cancel AAPL entry`.

## Verification

- Existing Python/backend suite remains green.
- Add static UI contract assertions for new landmarks/status hooks.
- Browser-check desktop 1440x900, tablet 820x1000, and mobile 390x844.
- Verify no horizontal overflow, dialog keyboard behavior, empty/loading/error states,
  pending/unknown position rendering, and reduced motion.
- Inspect browser console for errors.

## First-Run Addendum (2026-07-12)

**Selected pattern:** inline quick start. Comparison:
`docs/superpowers/mockups/2026-07-12-onboarding-options.html`.

The paper-mode aha moment is opening one mock BUY and seeing a monitored position.
Add one optional, non-blocking guide between the summary rail and workspace panes:

1. Choose an actionable BUY signal.
2. Review quantity, market order, TP, and SL; confirm fake money.
3. Watch protection state and activity until the broker/monitor confirms closure.

The guide appears on first use, dismisses permanently through localStorage, and is
replayable through a compact `How to use` control. It never appears in REAL mode,
does not introduce another modal, and adds no decorative motion.
