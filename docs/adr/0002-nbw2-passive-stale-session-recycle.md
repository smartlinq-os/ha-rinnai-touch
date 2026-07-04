# ADR 0002: NBW2 Passive Stale-Session Recycle

## Status

Accepted (design decision) — 5 July 2026.

Documentation only. No implementation exists at this commit. Any
implementation, including its parameter values, requires a separately
approved implementation review.

## Context

The N-BW2 TCP client is a passive receive-only transport adapter beneath
the transport/source boundary fixed by ADR 0001. Field sessions on one
real installation (5 July 2026), recorded under the sanitisation rules in
`docs/protocol_assumptions.md` ("Field Session Evidence (Private)"),
established the following:

- Fresh passive sessions repeatedly showed: TCP established → short
  ASCII greeting → first valid status frame → valid status frames
  approximately once per second for about five minutes → valid frames
  stop. Observed twice in independent fresh sessions, consistent with
  the earlier passive probe captures (local field observation, single
  installation).
- During the silence the TCP connection remained established *from the
  client side*. This is a client-side observation only: a passive client
  cannot distinguish a quiet peer from a half-open connection, and a
  connected TCP socket is never proof of a healthy N-BW2 session (local
  field observation with a stated epistemic limitation).
- Disabling and re-enabling the integration — closing and reopening the
  TCP connection — restored a further roughly five-minute stream window.
  Observed twice, with human-paced turnarounds (local field observation;
  ledger item A15, Partially validated).
- In one observed field episode, the local listener became available
  only after the N-BW2 module was restarted, following a delayed
  readiness period (local field observation, single episode).

External behavioural evidence (read-only source review of the local
upstream Homebridge reference and the funtastix `pyrinnaitouch`
implementation at its reviewed version — see `docs/protocol_assumptions.md`,
Provenance): both implementations pair periodic outbound idle traffic at
cadences well below five minutes with a bounded no-data watchdog that
closes and reconnects the socket; neither passively holds a silent
socket. Their idle-traffic forms and cadences differ structurally, so no
single maintenance form is validated for this module; ledger item A11
remains Unknown. Community reports — unverified — associate rapid
reconnect loops with refused or unavailable listeners, which cautions
against aggressive automated reconnect pacing (basis of ledger item
A16).

The reading that the roughly five-minute cutoff is a module-side timer
keyed to inbound traffic is an inference / hypothesis. Alternative
explanations (cloud-session interaction, network-path loss producing a
half-open connection, firmware variance, post-restart settling) are not
excluded by current evidence.

Without a recovery behaviour, a purely passive client receives roughly
five minutes of telemetry per manual reload and then remains stale
indefinitely.

## Decision

### The recycle behaviour

When the NBW2 adapter's socket is connected but no valid frame has
arrived within a bounded read-idle interval, the adapter closes the
connection gracefully, reuses its existing reconnect lifecycle, and
waits for a new valid frame. It transmits nothing at any point.

### Parameter policy

The NBW2 adapter may use a bounded configurable read-idle recycle
policy. Binding constraints:

- the selected threshold must exceed normal expected frame spacing;
- it must remain below the freshness threshold during controlled
  validation;
- the exact values are field-validation parameters, not protocol facts,
  and are deliberately not recorded in this ADR, in `AGENT_SCOPE.md`, or
  in the protocol assumptions ledger;
- any value change requires a separate approved implementation review.

### What this decision is not

- Not a keepalive: it grants no outbound bytes of any kind, does not
  weaken ledger item A11, and leaves the Transport Keepalive Policy
  unchanged.
- Not a validation claim: recycling is not validated, not established as
  safe indefinitely, and not established as suitable for all modules.
  Module tolerance of a sustained automated reconnect cadence is Unknown
  (ledger item A16).
- Not a health claim: a connected TCP socket never proves a healthy
  N-BW2 session.

## Rules for future work

1. Recycle logic is NBW2-adapter-specific and lives in the NBW2 client
   only, beneath the ADR 0001 seam.
2. The coordinator and entities remain unaware of recycling: freshness
   stays report-only, availability semantics are unchanged, and no new
   coordinator API is created.
3. A future SmartLinq hardware source uses explicit documented heartbeat
   and data-freshness metadata instead of inheriting NBW2 session
   quirks; recycle behaviour never migrates above the seam or into
   another source.
4. Passive recycle remains the fallback recovery path even if a
   separately approved outbound session-maintenance experiment later
   succeeds.
5. Implementation, parameter values, and any later parameter change each
   require separate explicit approval.
6. A bounded user-run field soak must precede any claim that the
   behaviour is validated (ledger items A15 and A16 record the
   validation state).

## Consequences

- Once implemented, the adapter will reconnect periodically in normal
  operation. Module tolerance of that cadence is Unknown (A16) until
  field-validated; the user-level kill switch is disabling the config
  entry.
- Observability stays within the existing sanitised transport-forensics
  rules: fixed labels, counters, timings, and booleans only — never
  addresses, ports, payloads, or raw protocol material.
- The cost is discipline: the recovery behaviour must land beneath the
  seam even where a shortcut through coordinator or entity semantics
  would be quicker.

## References

- `AGENT_SCOPE.md` — binding scope and safety rules, including the
  Transport Session Recycle Policy and the Transport Keepalive Policy.
- `docs/protocol_assumptions.md` — NBW2 LAN protocol facts and
  assumptions ledger (items A2, A11, A15, A16; "Field Session Evidence
  (Private)").
- `docs/adr/0001-transport-source-boundary.md` — the transport/source
  boundary this decision operates beneath.
