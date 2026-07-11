# Gate E Standalone Harness Design

This is an **offline harness design only**: the paper design of a
**future standalone harness** for the Gate E session-maintenance
experiment planned in `gate_e_session_maintenance_experiment_plan.md`.
The harness is **not implemented** — no code, script, test, fixture, or
configuration exists or is created by this document or by the commit
that introduces it. The experiment the future harness would serve is
**not approved to run**, and **no traffic was sent** in preparing this
design: nothing connected, nothing transmitted, nothing captured.
**Candidate 1 remains proposed only** — proposed as the first
experiment candidate, not approved behaviour, not established as safe.
**A11 remains Unknown** (`../protocol_assumptions.md`), and **Gate E
remains unadvanced** operationally: this document delivers the Phase E1
paper harness design and nothing more — it approves no E2 dry-run, no
E3 live experiment, no E4 ledger decision, no outbound traffic, and no
Home Assistant runtime keepalive. Every run this design describes
concerns a **single local installation only**, and the future harness
would be **operator-controlled** at every step: a human-run tool for
one short supervised test window, never an autonomous daemon.

Prepared: 11 July 2026.

## 1. Purpose and Scope

**Purpose.** If — and only if — a Phase E3 controlled experiment is
later separately and explicitly approved, the future harness would:

- perform exactly one controlled Gate E session-maintenance test per
  approved run;
- receive the status stream passively first, before any send is
  considered;
- send only Candidate 1, at the approved cadence, during the approved
  test window;
- log sanitised lifecycle evidence suitable for the Phase E4 review.

The single question the future harness exists to help answer is the
Commit 22 experiment question: whether Candidate 1 can reset T_TCPOUT
(the documented TCP timeout, default five minutes — see
`nbw2_api_session_semantics_review.md` and the ledger) and keep the
N-BW2 status stream alive beyond the default timeout window, without
observable side effects, on a single local installation only.

**Non-purpose.** The future harness would **not** be:

- a general protocol client;
- a Home Assistant integration — never loaded, imported, or invoked by
  the Home Assistant runtime;
- a command tool (no HVAC state-changing command of any kind);
- a discovery tool;
- a packet-capture tool;
- a configuration or reboot tool;
- a long-running daemon.

**Fixed boundaries**, inherited unchanged from the Commit 22 plan
(section 6) and the Transport Keepalive Policy:

- one purpose: the Candidate 1 T_TCPOUT question above;
- one candidate: Candidate 1 only (section 4);
- one local TCP client, one connection, opened once per run;
- no UDP;
- no discovery;
- no packet capture;
- no cloud, account, or configuration-channel usage of any kind;
- no credentialed commands;
- no HVAC state-changing commands;
- no Home Assistant runtime integration;
- no automatic retry or reconnect on anomaly (section 9);
- operator-controlled throughout: explicit confirmation before any
  connection and before any send, an abort always available, a hard
  timeout always armed.

This design is suitable only for a future human-run experiment.

## 2. Inputs and Operator Control

High-level operator inputs, defined here without values. **No real IP
address or port number appears anywhere in this document**; the target
is supplied by the operator at run time.

- target host and port, supplied by the operator at runtime;
- test duration (proposed default: the Commit 22 plan's 12–15 minutes
  of streaming);
- candidate cadence (proposed default 60 seconds — section 4);
- hard timeout, unconditional (proposed default: the Commit 22 plan's
  20 minutes);
- optional log output path, for the sanitised lifecycle log only
  (section 7);
- an explicit operator confirmation prompt that must be answered
  before any send is allowed (section 3).

All defaults are **proposed, not approved**: they restate the
Commit 22 plan's proposals, and the values fixed at E2/E3 approval time
supersede them. The confirmation prompt must name the exact candidate
structure and the exact cadence being approved for the run; any
mismatch between what the prompt describes and what the operator
expects is a refusal condition, not something to proceed past.

## 3. Startup and Refusal Flow

The future harness must run this sequence strictly in order:

1. print the pre-run safety checklist (section 8) and the run
   parameters (duration, cadence, hard timeout);
2. require explicit typed operator confirmation — of the checklist,
   the exact candidate structure, and the exact cadence — before
   opening any connection;
3. connect once to the operator-supplied target;
4. wait for the documented greeting if present (ledger item A14),
   recording its presence as a boolean only;
5. wait passively for at least one valid status frame;
6. derive the next candidate sequence from the latest valid received
   frame using the Candidate 1 evidence-source rule (section 5);
7. only then arm the send path, with the first send no earlier than
   the approved offset (proposed: approximately 60 seconds after the
   first valid status frame).

Refusal is the default state; sending is the exception that must be
affirmatively unlocked. The future harness must **refuse to send** —
permanently for the run, logging a fixed refusal label — when any of
the following holds:

- no valid status frame has arrived on the current connection;
- the frame stream is malformed or unknown: the received input
  contains anything the operator cannot immediately explain —
  undecodable or structurally invalid candidates, or non-frame bytes
  beyond the expected greeting (qualitative by design; exact numeric
  thresholds are Phase E2 dry-run parameters — section 9);
- the operator has not confirmed the exact candidate and cadence.

A refusal is never retried within the run. The hard timeout ends the
run unconditionally, in every state, whether or not any send occurred.

## 4. Candidate Send Rule

Candidate 1 only, described **structurally only** (no raw candidate
frame appears in this document): the ASCII prefix `N` followed by a
six-digit zero-padded sequence number, with **no payload** — no JSON
payload, no token, no command field, no configuration write.

Send rules the future harness must enforce:

- no send before the first valid status frame on the current
  connection (existing policy rule, unchanged);
- no cadence faster than the approved cadence; the default proposed
  cadence remains 60 seconds (Commit 22), which is also the Transport
  Keepalive Policy's minimum spacing;
- no retry burst: at most one send per cadence interval, never
  re-sent, never accelerated;
- sends stop immediately and permanently on any anomaly (section 9);
- no second candidate form in the same run, ever: failure of
  Candidate 1 does not authorise trying Candidate 2 under the same
  approval (Commit 22 plan, section 3).

**Candidate 1 remains proposed only.** Nothing in this section
approves the candidate as safe, approves sending it, or validates it;
A11 remains Unknown.

## 5. Sequence Handling

Candidate 1 uses the **Homebridge evidence-source rule** decided in
the Commit 22 plan (section 4), matching the pinned evidence source
exactly:

- at each send, the sequence is derived from the **latest valid
  received frame** at that moment: latest valid received sequence + 1,
  modulo 255;
- a result of zero is replaced by 1 (Homebridge skip-zero behaviour;
  transmitted range 1–254);
- formatted as six zero-padded decimal digits;
- **re-derived per send** from the latest valid received frame — never
  a private outgoing counter.

Recorded consequence — an observable, not a defect: the API PDF
documents the sequence echo for *commands*, and whether the module
echoes Candidate 1 is part of the central Known Unknown. If the module
does not echo, the received sequence stays stable and consecutive
candidate sends would carry **identical sequence values** — exactly
what the evidence source does in the same situation. The future
harness must record whether repeated identical candidate sequences
occurred, and must not "correct" them with a private counter, which
would create a novel untested variant.

No wrap boundary is expected in the proposed short run; if the latest
received sequence happened to sit at the boundary, the rule above is
total and already defines the outgoing value.

**Known difference, recorded deliberately:** the API PDF documents
increment-with-wrap 255→0, with zero a valid outgoing value
(`nbw2_api_session_semantics_review.md`, section 5). The
evidence-source rule above deviates from the documented rule in the
same way its source implementation does; the experiment would test the
field-proven combination exactly as its evidence source uses it.
Changing sequence arithmetic is a separate design decision and is not
part of this candidate.

## 6. Receive Loop and Observations

The future harness must:

- parse received bytes only far enough to identify valid frames and
  their sequence numbers (the framing facts already recorded in
  `../protocol_assumptions.md`); parsing exists to gate sending and to
  count lifecycle events, not to interpret HVAC state;
- never expose raw payloads in logs (section 7);
- record lifecycle counters only: frames, valid frames, candidate
  sends, connection events;
- record whether status frames continue past one and then two default
  T_TCPOUT windows (the window-extension observation);
- record whether the status stream's sequence number changes to echo a
  candidate's sequence after each send (the sequence-echo observation
  — the direct probe of the central Known Unknown: command-only versus
  any-packet timer reset);
- record any greeting reappearance mid-session as a possible
  module-reboot indicator;
- record connection close, reset, or refusal as failure evidence,
  using fixed classification labels in the existing
  transport-forensics style;
- **never infer HVAC safety from parser success**: a well-formed
  status stream proves framing, not that the system is unaffected;
  only the operator's observation of the wall controller/app addresses
  user-visible state.

## 7. Logging and Sanitisation

Logging follows the existing sanitised transport-forensics discipline
already used by the integration's client: fixed labels, counters,
coarse timings, and booleans.

**Allowed log content:**

- coarse timestamps or relative times;
- lifecycle events as fixed labels;
- counts;
- first valid frame timing;
- last valid frame timing;
- candidate send count;
- candidate cadence;
- whether sequence echo was observed;
- whether the stream crossed one / two default timeout windows;
- whether the greeting reappeared;
- whether the connection ended, with its fixed classification label;
- whether the operator aborted;
- whether a fault or abnormal state was observed by the operator.

**Forbidden log content:**

- raw frames;
- payloads;
- credentials;
- IP addresses;
- ports;
- serial numbers;
- full JSON;
- screenshot data;
- vendor credential or configuration values.

Raw logs, if the future harness produced any at all, would remain
local to the operator; anything entering the repository follows the
existing sanitisation procedure and reference-data rules. The
sanitised evidence summary (section 10) is the intended
repository-facing artefact.

## 8. Operator Checklists

**Pre-run checklist** — every item must hold before a future,
separately approved E3 run begins (restating and extending the
Commit 22 preconditions):

- [ ] the run itself has been separately and explicitly approved
      (this design is not that approval);
- [ ] the SmartLinq Home Assistant integration is disabled/unloaded;
- [ ] Homebridge is stopped;
- [ ] funtastix/rinnaitouch is stopped;
- [ ] the Rinnai vendor app is not actively controlling the system;
- [ ] exactly one local TCP client (the future harness) will exist,
      and a pre-check has found no competing client;
- [ ] the HVAC system is in a benign state chosen by the operator,
      recorded beforehand in human terms;
- [ ] no fault or abnormal controller state is present;
- [ ] the operator is monitoring the wall controller/app for the
      whole run;
- [ ] the abort procedure is understood (section 9);
- [ ] the test window is short and supervised, with the hard timeout
      armed.

**Post-run checklist:**

- [ ] the harness process is stopped;
- [ ] no unexpected state change occurred;
- [ ] no fault is present;
- [ ] the wall controller/app behave normally;
- [ ] passive behaviour has been observed to return to the known
      baseline (proposed: the Commit 22 plan's 10–15 minutes of
      passive-only observation);
- [ ] the Home Assistant integration is re-enabled only after that
      observation;
- [ ] logs are retained locally, or sanitised per section 7 before
      any sharing.

## 9. Failure and Abort Handling

Binding rules for the future harness:

- graceful close on abort whenever possible (the module is reported
  to mishandle abrupt closes — `../../AGENT_SCOPE.md`);
- no retry after anomaly: a stopped or aborted run is not retried
  without a new approval;
- no automatic reconnect after failure, ever;
- any send-path error is failure evidence, never retried;
- any malformed-frame uncertainty is an abort — anything in the
  received stream the operator cannot immediately explain;
- operator concern of any kind always aborts;
- no second candidate in the same run.

Thresholds in this document are **qualitative by design**: exact
numeric values (for example the no-valid-frame abort interval) are
Phase E2 dry-run parameters, fixed at E2 approval time per the
Commit 22 plan (section 9).

Failure and abort both leave recovery to the already-validated passive
paths only: the passive stale-session recycle and re-enabling the
integration. Passive recycle remains the standing fallback recovery
path regardless of any experiment outcome
(`../adr/0002-nbw2-passive-stale-session-recycle.md`, rule 4).

## 10. Sanitised Evidence Summary Template

A future run would produce one sanitised summary in the following
form. **This is a template only**: no fixture file, no pre-filled
example, and no raw material accompanies it.

- Test ID:
- Date/window:
- Installation role: primary / redundant-non-primary
- Known module/controller family:
- Differences from target production system, if known:
- Candidate:
- Cadence:
- Duration:
- Initial HVAC state:
- Preconditions confirmed:
- First valid frame:
- First candidate send:
- Candidate sends:
- Stream crossed one default timeout window:
- Stream crossed two default timeout windows:
- Sequence echo observed:
- Greeting reappeared:
- Connection ended:
- User-visible state changed:
- Fault observed:
- Abort/failure reason:
- Sanitisation confirmed:
- Conclusion:
- Ledger recommendation:

The "Ledger recommendation" field records a proposal for Phase E4
only; no ledger change follows automatically from a completed template
(the Commit 22 plan, section 11, defines the possible outcomes, and
every ledger change is its own separately approved commit).

## 11. Relationship to Gate E Phases

- **E0 — paper experiment plan**: delivered by Commit 22
  (`gate_e_session_maintenance_experiment_plan.md`), which also
  included the E1 design outline.
- **E1 — offline harness design**: **this document delivers the E1
  paper harness design.** Nothing is implemented; acceptance of the
  commit that introduces this document is approval of the design *as a
  document*, and nothing operational advances with it.
- **E2 — dry-run review**: remains future, behind its own separate
  explicit approval; E2 fixes the numeric thresholds this design
  deliberately leaves qualitative.
- **E3 — one controlled live experiment**: remains future and **not
  approved**; separate explicit approval is given at run time or not
  at all.
- **E4 — evidence review and ledger decision**: remains future, behind
  its own separate explicit approval; the only phase that may change
  any ledger entry.

No phase auto-triggers the next, and approval of any phase does not
imply approval of a later one. **Gate E remains unadvanced
operationally**: no Transport Keepalive Policy gate condition is
declared satisfied by this document, no traffic is approved, and A11
remains Unknown.

### Installation environment for a future E3 run

A future, separately approved E3 experiment may be run on either:

- the **primary local installation** (the installation behind all
  existing SmartLinq field evidence); or
- a **redundant/non-primary local installation**, if one is available
  to the operator,

provided **every safety boundary in this design applies unchanged** in
either case. This choice concerns the live experiment *environment*
only: the future harness — the operator-run tool and process this
document designs — is the same in both cases and is not replaced or
altered by the choice. No particular setup is required or implied; if
no redundant/non-primary installation exists, the primary installation
with the full checklist is the designed path.

Recorded limits of the redundant/non-primary option:

- it lowers **operational impact only**: a problem during the test
  window would disrupt a system whose availability matters less, and
  nothing else improves;
- it is **not safer at the protocol level**: the module-side unknowns
  (A11, the T_TCPOUT reset trigger, reboot behaviour) are identical on
  either installation;
- it does **not validate the candidate automatically**, on that
  installation or any other;
- it removes **none** of: one-client-only operation, operator
  monitoring, the abort criteria, sanitised evidence handling, or the
  separate explicit E3 approval;
- it does **not allow skipping any of the E1/E2/E3/E4 gates**;
- evidence from either environment remains **single local installation
  only** evidence for that run: the evidence summary must record the
  installation role (section 10) so a Phase E4 review can weigh
  transferability, and differences from the target production system,
  where known, are recorded rather than assumed away.

## 12. Relationship to Home Assistant Runtime

- Future harness success would **not** automatically allow a Home
  Assistant runtime keepalive. An HA runtime keepalive remains a
  separate design, implementation, testing, and release decision —
  each step with its own approval — and stays gated by Transport
  Keepalive Policy condition (3): explicit user approval of the
  resulting design.
- The passive stale-session recycle remains the fallback recovery path
  regardless of any experiment outcome (ADR 0002, rule 4).
- If an HA runtime keepalive is ever designed, a **default-off,
  explicit feature gate** may be appropriate, given that all evidence
  would still come from single local installations.
- **No runtime changes are part of this commit**: no keepalive
  support, no command/control code, no climate entities, no switches,
  buttons, numbers, selects, or services, and no change to the v0.1.0
  passive posture.

## 13. Explicit Non-Goals

This document, and the commit that introduces it:

- is an **offline harness design only** — the paper design of a
  **future standalone harness**; the harness is **not implemented**,
  and no script, code, test, fixture, or configuration is created;
- **sent no live traffic** — no TCP, no UDP, no discovery, no packet
  capture, no connection to any module, and nothing was executed from
  any reference repository;
- **approves nothing to run** — the experiment is **not approved to
  run**, no outbound session-maintenance traffic is approved, and
  **Candidate 1 remains proposed only**: not approved behaviour, not
  established as safe;
- **validates no command** — no frame of any kind is established as
  safe, and even a fully successful future experiment would validate
  nothing about any write;
- **changes no ledger entry** — in particular **A11 remains Unknown**;
- **does not advance Gate E operationally** — it delivers the E1 paper
  harness design only; E2, E3, and E4 remain future, each behind its
  own separate explicit approval, and no gate condition is declared
  satisfied;
- **makes no universal N-BW2 compatibility claim** — every run this
  design describes concerns a **single local installation only**,
  whether primary or redundant/non-primary;
- **approves no Home Assistant runtime keepalive** — section 12
  stands, and v0.1.0's passive posture, including passive recycle as
  the standing fallback, is unchanged;
- designs an **operator-controlled** tool for a future human-run
  experiment — never an autonomous daemon, never part of the Home
  Assistant runtime.
