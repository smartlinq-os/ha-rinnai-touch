# Gate E Session-Maintenance Experiment Plan

This is a **paper-only experiment plan**. It designs a **future
controlled experiment**; it does not approve, run, automate, or
implement it. **No traffic was sent** in preparing this plan, nothing
was implemented, no command was validated, and no entry in
`../protocol_assumptions.md` changes as a result of this document —
**A11 remains Unknown** and **Gate E remains unadvanced**. No universal
N-BW2 compatibility claim is made, and nothing here approves a Home
Assistant runtime keepalive. Every phase described below, including the
experiment itself, requires its own separate, explicit approval; the
experiment is **not approved to run**.

Prepared: 11 July 2026.

## 1. Purpose and Scope

The Transport Keepalive Policy (`../../AGENT_SCOPE.md`, mirrored in the
ledger) gates any outbound session maintenance behind three conditions:
(1) review of readable authoritative N-BW2 API documentation; (2) a
separately approved controlled experiment; (3) explicit user approval
of the resulting design. Commits 19–21 produced the reading input for
condition (1); whether that condition is satisfied **remains a future
maintainer decision**. This document addresses the *design* portion of
condition (2) only: it is the plan a future controlled experiment would
follow if — and only if — it is later separately approved.

This plan **is**: Phase E0 (the paper plan itself) plus the Phase E1
design outline for a future harness, with candidate analysis,
preconditions, phases, proposed timings, success criteria, failure
criteria, abort criteria, evidence-handling rules, and possible ledger
outcomes defined in advance.

This plan **is not**:

- approval to run anything (the experiment is not approved to run);
- live traffic of any kind (no traffic sent; nothing connected);
- implementation (no harness, script, fixture, test, or code exists or
  is created by this commit);
- command validation (no frame of any kind is established as safe);
- an A11 change (A11 remains Unknown);
- Gate E advancement (designing the experiment does not run it, and no
  gate condition is declared satisfied here);
- a compatibility claim (everything below concerns a single local
  installation only);
- Home Assistant runtime keepalive approval (see section 12).

## 2. Evidence Baseline

What is already established, with sources:

- **SmartLinq v0.1.0 baseline.** Passive and read-only: no keepalive,
  no polling, no acknowledgements, no commands. Recovery is the passive
  idle-timeout recycle (ADR 0002), Gate-D-validated on one local
  installation (~932 automated recycles over ~5 days, ~99.7%
  first-attempt recovery, zero refused sessions). ADR 0002 rule 4:
  passive recycle remains the fallback recovery path even if a
  separately approved outbound session-maintenance experiment later
  succeeds.
- **Commit 19** (`upstream_command_behaviour_review.md`): both working
  external implementations maintain sessions with outbound idle
  traffic; their forms differ (bare sequence header roughly once per
  minute vs sequence header plus a short non-JSON two-character ASCII
  token after send-idle); both pair idle traffic with no-data
  watchdog/reconnect. Source review only; nothing validated for
  SmartLinq.
- **Commit 20** (`nbw2_api_session_semantics_review.md`): the vendor
  API PDF documents a client-traffic requirement within T_TCPOUT (the
  `TNRX` setting: default five minutes, range 1–60 minutes); absent
  client traffic within it, the module terminates the connection and
  performs a reboot. The PDF documents continuous one-second status
  streaming and sequence-echo acknowledgement, and defines **no
  dedicated keepalive or idle message** — neither upstream idle form is
  documented or validated.
- **Commit 21** (`../protocol_assumptions.md`): the ledger records the
  PDF evidence. A11 remains Unknown. The central Known Unknown is:
  **what resets T_TCPOUT — any client TCP packet, or only a well-formed
  command?** The PDF's prose says "issues commands"; its flow chart
  tests for any client TCP packet.
- **Binding policy constraints** that any future run inherits unchanged
  (Transport Keepalive Policy): the candidate frame previously scoped
  for this project is exactly `N` followed by a six-digit sequence
  number with no JSON payload; the sequence derives from the latest
  valid received frame; spacing is never more frequent than every 60
  seconds; nothing is sent until at least one valid status frame has
  arrived on the current connection; the frame must never be a reboot,
  date/time, mode, power, fan, zone, pump, schedule, or any other
  state-changing command; keepalives are logged at debug level only.

Context (inference only): if the Commit 20 T_TCPOUT mapping is correct,
the current passive recycle pattern may already coincide with repeated
module timeout/reboot cycles; a successful session-maintenance
candidate could reduce that during the test window. This is context
only, not a safety claim.

## 3. Experiment Question

The narrow question a future controlled experiment would answer:

> Can a minimal, non-HVAC-state-changing client-traffic candidate reset
> T_TCPOUT and keep the N-BW2 TCP status stream alive beyond the
> default timeout window, without observable side effects, on a single
> local installation only?

Secondary, receive-only observations designed in from the start (no
extra traffic; they are read from the stream that arrives anyway):

- **Sequence echo**: whether the status stream's sequence number
  changes to echo the candidate's sequence. The PDF documents the echo
  for *commands*; observing it (or its absence) for the candidate frame
  directly probes the central Known Unknown — command-only versus
  any-packet timer reset.
- **Window extension**: whether streaming continues past the point
  where every passive session to date has gone silent, and whether
  continuation tracks the candidate timing.
- **Reboot indicators**: whether the mid-session greeting reappearance,
  listener loss, or refused periods seen around passive cutoffs are
  absent.

Decision tree, on paper only: if Candidate 1 fails to hold the session
while everything else behaves normally, the narrower reading
(well-formed commands only) gains weight and Candidate 2 becomes the
next *paper* candidate for a separately approved follow-up plan.
Failure of Candidate 1 does not authorise trying Candidate 2 in the
same run or under the same approval.

## 4. Candidate Session-Maintenance Forms

All candidate frames are described **structurally only**; no raw
traffic appears in this document.

| # | Candidate (structural) | Evidence | Pros | Cons | Classification |
|---|---|---|---|---|---|
| 1 | Bare sequence header: `N` + six-digit sequence, no payload | Mature Homebridge implementation sends it roughly once per minute; that stack has run successfully against this installation; identical to the policy-scoped candidate frame | Minimal content; lowest semantic load; no JSON field/value command; stays inside every existing policy constraint | Not documented by the API PDF; may be tolerated only incidentally; no formal acknowledgement defined for it | **Proposed first experiment candidate — proposed only, not approved behaviour, not approved to run** |
| 2 | Sequence header plus a short non-JSON two-character ASCII token | pyrinnaitouch sends it after send-idle; that stack has also run against this installation | Intentionally used by the Python stack; participates in its sequence-wait model | Not documented by the API PDF; adds an undocumented token; higher semantic uncertainty than the bare header; not the policy-scoped frame | Second-ranked paper candidate; only reachable via a separately approved follow-up plan |
| 3 | A documented writable command used as traffic | The API PDF documents many writable fields | Unambiguously a "command" under the PDF's prose reading | Every documented write changes HVAC, controller, schedule, clock, zone, or configuration state; Commit 20 found no documented status-request or no-op | **Not suitable for the first Gate E experiment** |

**Sequence arithmetic (decided for this plan).** Because Candidate 1 is
Homebridge-style, the proposed future experiment uses the Homebridge
evidence-source arithmetic: last-received + 1, modulo 255, skipping
zero (transmitted range 1–254). A 12–15 minute run sends so few frames
that the wrap boundary is never approached. The API PDF instead
documents increment-with-wrap 255→0 (zero valid); **this mismatch is a
known difference**, recorded here deliberately: the experiment tests
the field-proven combination exactly as its evidence source uses it,
not a novel variant.

## 5. Preconditions and Safety Boundaries

Every item must hold before a future, separately approved run begins:

- [ ] The user has explicitly approved running the experiment (a later
      decision; this plan is not that approval).
- [ ] The SmartLinq Home Assistant integration is disabled/unloaded.
- [ ] Homebridge is disabled/stopped.
- [ ] funtastix/rinnaitouch is disabled/stopped.
- [ ] The Rinnai vendor app is not actively controlling the system
      during the test.
- [ ] Exactly one local TCP client (the approved harness) will exist,
      and a pre-check has found no competing client.
- [ ] The user is physically present or actively monitoring the wall
      controller/app for the whole run.
- [ ] The HVAC system is in a benign state chosen by the user, recorded
      beforehand in human terms (matching the passive semantic mapping
      plan's template style).
- [ ] No fault or abnormal controller state is present at the start.
- [ ] The rollback plan is understood: abort means graceful close,
      stop, observe; recovery uses only the already-validated passive
      paths (passive recycle / re-enabling the integration).
- [ ] Logs are enabled only for the test window.
- [ ] No cloud, account, or configuration-channel usage of any kind.
- [ ] No UDP discovery or probing.
- [ ] No packet capture unless separately approved.
- [ ] No credentialed reboot or configuration commands under any
      circumstances (existing prohibition; unchanged).
- [ ] The network is stable (no known Wi-Fi/AP disruption planned
      during the window).

## 6. Future Harness Boundary

For future planning only — **no harness is implemented, scaffolded, or
named by this commit**. Whether the future harness is a new standalone
tool or a separately approved extension of the existing user-run probe
is a Phase E1 design decision. Whatever form it takes, it must satisfy
all of the following:

- standalone research harness, outside the Home Assistant runtime;
- never loaded, imported, or invoked by Home Assistant;
- exactly one TCP connection, opened once;
- passive receive first: it waits for the greeting and a valid status
  stream before anything else;
- no send occurs until at least one valid status frame has been
  received on the current connection (existing policy rule);
- sequence derivation exactly per the chosen candidate's evidence
  source (section 4);
- sends only the single approved candidate frame, at the approved
  cadence, and nothing else — ever;
- logs sanitised lifecycle events only (fixed labels, counters, coarse
  timings, booleans), in the style of the existing transport
  forensics;
- no raw payloads in the repository; no credentials; no configuration
  writes; no HVAC state-changing commands;
- a hard timeout that ends the run unconditionally;
- a hard stop on any anomaly (section 9's abort criteria), with no
  automatic retry.

## 7. Proposed Test Phases

| Phase | Content | Gate |
|---|---|---|
| **E0 — paper review complete** | This document, reviewed and approved *as a plan* | Approval of this commit approves the plan's existence, nothing more |
| **E1 — offline harness design review** | Paper-only review of the future harness design against section 6; no code is written | Separate explicit approval |
| **E2 — dry-run review** | Walkthrough of the exact procedure: candidate frame represented structurally (never a raw payload), operator checklist, abort drill, log plan — still no traffic | Separate explicit approval |
| **E3 — one controlled live experiment** | A single run per section 8, on the single local installation, user present — **only if separately and explicitly approved at the time** | Separate explicit approval, given at run time |
| **E4 — evidence review and ledger decision** | Sanitised results reviewed; any ledger change is its own separately approved commit | Separate explicit approval |

This commit delivers **E0 plus the E1 design outline only**. No phase
auto-triggers the next; each requires its own approval; approval of any
phase does not imply approval of a later one.

## 8. Candidate Cadence and Timing

All values below are **proposed**, not approved; they are experiment
parameters for a future run, not protocol facts, and any change at
approval time supersedes them.

- Observe the passive status stream first: connect, wait for the
  greeting and the first valid status frames, and confirm normal
  streaming before any send is considered.
- First candidate frame: proposed at approximately 60 seconds after the
  first valid status frame — well before the default T_TCPOUT window,
  and consistent with the existing policy floor of no-more-frequent-
  than-60-seconds.
- Repeat cadence: proposed every 60 seconds (the Homebridge evidence
  cadence, and the policy minimum spacing).
- Run length: proposed 12–15 minutes of streaming — long enough to
  cross **at least two default T_TCPOUT windows** if the candidate
  works, short enough to bound exposure.
- Hard timeout: proposed 20 minutes, unconditional.
- Post-run observation: proposed 10–15 minutes of passive-only
  observation (no sends) to confirm behaviour returns to the known
  passive baseline and no delayed anomaly appears.
- One run per approval. Stop immediately on any anomaly; a stopped or
  aborted run is not retried without a new approval.

## 9. Success, Failure, and Abort Criteria

**Success criteria** (all must hold):

- the status stream remains continuous beyond at least two default
  T_TCPOUT windows (more than ten minutes);
- no module-reboot indicators: no mid-session greeting reappearance,
  no listener loss, no refused-listener period during or after the run;
- no unexpected state change of any kind;
- no controller or app anomaly;
- no fault state;
- no loss of freshness (valid frames keep arriving at the expected
  cadence);
- user-visible HVAC state remains unchanged throughout;
- post-run passive behaviour returns to the known baseline, indicating
  no persistent change to the module.

**Failure criteria** (any one suffices):

- the stream stops near T_TCPOUT despite the candidate being sent;
- the socket closes, resets, or is refused unexpectedly;
- the module appears to reboot;
- the controller changes state;
- HVAC mode, power, setpoint, fan, zone, or schedule changes without
  user initiation;
- a fault appears;
- the wall controller or app becomes abnormal;
- repeated malformed-frame symptoms appear in the received stream;
- a send-path error occurs (treated as failure evidence, never
  retried);
- any user concern, of any kind.

**Abort criteria** (hard abort — immediate graceful close, stop,
observe; no retry without a new approval):

- any HVAC state change not initiated by the user;
- fault or abnormal controller state;
- loss of user confidence;
- an unexpected reboot or refused-listener sequence;
- no valid status frame within a defined interval (to be fixed at E2;
  proposed on the order of the existing freshness threshold);
- any raw/protocol uncertainty during the run — anything the operator
  cannot immediately explain;
- any competing client discovered.

Failure and abort both leave recovery to the already-validated passive
paths only. A failed or aborted run changes nothing about v0.1.0's
behaviour: passive recycle remains the standing fallback (ADR 0002).

## 10. Evidence Handling and Sanitisation

- No raw frames are ever committed to the repository.
- No credentials, no IP addresses, no ports, no serial numbers in any
  repository document or log excerpt.
- Only sanitised lifecycle summaries and coarse timing are recorded:
  fixed labels, counters, booleans, and approximate durations — the
  existing transport-forensics discipline.
- The candidate frame is written **structurally only** in research
  documents; it is not copied as raw traffic unless that is separately
  approved.
- Raw logs are retained locally by the user unless sanitised; anything
  entering the repository follows the existing sanitisation procedure
  (`../../reference_data/README.md` rules and the established
  fixture-sanitisation pattern).
- Observation records use the human-terms template style of the passive
  semantic mapping plan.

## 11. Ledger Outcomes

Possible outcomes are defined here in advance but **not applied** by
this document; any ledger change is a Phase E4 decision in its own
separately approved commit.

- If no experiment is run: **A11 remains Unknown**. This is the current
  state and the default state.
- After a successful experiment: A11 may **at most** become partially
  validated / locally validated **for the exact candidate form and
  cadence tested, on a single local installation only**, subject to
  separate approval of the ledger wording. Cross-module,
  cross-firmware, long-term, and any-other-form behaviour would remain
  unvalidated.
- After a failed experiment: A11 remains Unknown, or the tested
  candidate is annotated as rejected for the tested conditions,
  depending on the evidence.
- **No outcome grants Home Assistant runtime implementation
  automatically** (section 12).
- Even a fully successful experiment **does not imply command/control
  safety**: holding a session open with a candidate frame validates
  nothing about mode, power, setpoint, fan, zone, schedule, or any
  other write.

## 12. Post-Experiment Implementation Boundary

A Home Assistant runtime keepalive remains a **later design decision**,
not part of the Gate E experiment and not approved by this plan or by
any experiment outcome. If — and only if — a controlled experiment
succeeds and its evidence is accepted at E4, possible later steps, each
with its own approval, would be:

- update the ledger (E4);
- design an HA integration keepalive feature behind an explicit feature
  gate, satisfying Transport Keepalive Policy condition (3) — explicit
  user approval of the resulting design;
- add offline tests in the existing style before any runtime change;
- keep passive recycle as the fallback recovery path regardless
  (ADR 0002 rule 4);
- consider default-off until broader evidence exists, given that all
  evidence would still be from a single local installation only.

None of this is started, scaffolded, or implied by this commit.

## 13. Explicit Non-Goals

This document, and the commit that introduces it:

- is **planning only** — a paper-only experiment plan for a future
  controlled experiment that is **not approved to run**;
- **sent no live traffic** — no TCP, no UDP, no discovery, no packet
  capture, no connection to any module, and nothing was executed from
  any reference repository;
- **implemented nothing** — no harness, script, fixture, test, code,
  or configuration exists or changes as a result of this commit;
- **validated no command and no candidate** — Candidate 1 is a proposed
  experiment candidate only, not approved behaviour;
- **changes no ledger entry** — in particular **A11 remains Unknown**;
- **does not advance Gate E** — condition (1)'s satisfaction remains a
  future maintainer decision, condition (2) gains only a design on
  paper, and condition (3) is untouched;
- **makes no universal N-BW2 compatibility claim** — every element of
  this plan concerns a single local installation only;
- **approves no Home Assistant runtime keepalive** — the runtime
  boundary in section 12 stands, and v0.1.0's passive posture,
  including passive recycle as the standing fallback, is unchanged.
