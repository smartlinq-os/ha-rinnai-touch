# Gate E Dry-Run Review Checklist

This is a **dry-run review only** instrument: the Phase E2
**paper/operator rehearsal** checklist for the Gate E
session-maintenance experiment planned in
`gate_e_session_maintenance_experiment_plan.md` and designed in
`gate_e_standalone_harness_design.md`. Working through this checklist
involves **no live traffic** — no TCP, no UDP, no discovery, no packet
capture, no connection to anything — and produces **no executable
artefact**: no harness, script, code, test, fixture, or pseudocode
exists or is created by this document or by the commit that introduces
it. The experiment it rehearses is **not approved to run**;
**Candidate 1 remains proposed only**; **A11 remains Unknown**
(`../protocol_assumptions.md`); **Gate E remains operationally
unadvanced**; and **E3 remains future** and not approved. Everything
below concerns a **single local installation only** and an
**operator-controlled** future process.

Commit 24 delivers the E2 dry-run review checklist only. Creating the
checklist is not the same as performing the dry-run: this document is
a **blank reusable instrument**, committed with every box unchecked. A
future completed dry-run may support an E3 *proposal* only after
separate review; it approves nothing by itself.

Prepared: 11 July 2026.

## 1. Purpose and Scope

The purpose of Phase E2 is to rehearse and review the future E3 run
**without connecting to anything**: the participants walk through the
procedure, the refusal conditions, the abort drill, and the evidence
rules entirely on paper, and the reviewer decides whether an E3
proposal may be drafted.

Performing this dry-run:

- does **not** run the experiment;
- does **not** send traffic — no live traffic; nothing connects;
- does **not** approve E3 (a Go outcome permits only an E3 proposal —
  section 10);
- does **not** implement the harness — the future harness remains
  unimplemented, and no executable artefact is produced;
- does **not** change A11 — A11 remains Unknown;
- does **not** advance Gate E operationally — no Transport Keepalive
  Policy gate condition is satisfied by rehearsing.

Instrument handling (binding):

- the committed document is a blank reusable instrument;
- completed dry-run checklists stay **local to the operator** by
  default, like raw logs;
- only a **sanitised completion summary** may enter the repository
  later, via a separately approved future commit;
- the repository must never receive a raw completed checklist that
  contains sensitive details.

## 2. Roles and Recommended Separation

Three roles, defined at a high level:

- **Operator** — the person who would run the future harness if E3 is
  later separately approved, and who performs this rehearsal.
- **Observer** — the person who would watch the wall controller,
  vendor app, and HVAC behaviour during a future E3 run. The observer
  *function* is mandatory for E3: someone must be watching
  user-visible behaviour for the whole run.
- **Reviewer/approver** — the person who reviews the completed
  dry-run package and decides whether an E3 proposal may be made.

Separation rules:

- a separate Observer person is **recommended, not required**;
- one person may hold the Operator and Observer roles only if that is
  **explicitly recorded** in the package and **accepted by the
  Reviewer/approver**;
- the checklist prefers separation where practical, and never makes
  extra people a hard blocker where separation is impractical;
- role assignments are recorded in the E3 approval package
  (section 11).

## 3. Environment Selection

Choose and record the future E3 environment, per the E1 design's
"Installation environment for a future E3 run"
(`gate_e_standalone_harness_design.md`, section 11):

- [ ] the environment is chosen: **primary local installation** or
      **redundant/non-primary local installation**;
- [ ] the installation role is recorded in the evidence template
      fields;
- [ ] the known module/controller family is recorded, if known;
- [ ] differences from the target production system are recorded, if
      known;
- [ ] all participants confirm every safety gate applies **unchanged**
      in either environment;
- [ ] all participants confirm a redundant/non-primary choice lowers
      **operational impact only** — it is **not safer at the protocol
      level**, because the module-side unknowns are identical;
- [ ] all participants confirm the environment choice **validates
      nothing automatically** and permits **no gate skipping**;
- [ ] evidence from either environment is understood to remain
      **single local installation only** evidence for that run.

## 4. Pre-Dry-Run Inputs

The reviewer confirms the future E3 plan names a value for each item
below. Values are reviewed **as proposals** — they restate or refine
the E0 plan's proposed timings and remain subject to separate E3
approval — and none of them may be an address, port, serial,
credential, raw frame, or payload: no such value appears in this
document, in any completed checklist that will be shared, or in the
approval package.

- [ ] installation role (section 3);
- [ ] operator and observer (section 2);
- [ ] candidate identity: **Candidate 1** — Homebridge-style bare
      sequence header, structural description only, no payload;
- [ ] proposed cadence;
- [ ] proposed first-send offset;
- [ ] proposed live run duration;
- [ ] proposed hard timeout;
- [ ] proposed post-run passive observation duration;
- [ ] abort thresholds: the qualitative triggers from the E0 plan and
      E1 design, plus any proposed numeric values for review here —
      the E1 design (section 9) defers exact numbers to this E2
      review;
- [ ] where the evidence summary will be kept and how it will be
      handled — local by default, sanitised before any sharing;
- [ ] local log-retention plan;
- [ ] rollback/recovery plan: the validated passive paths only —
      passive recycle and re-enabling the integration
      (`../adr/0002-nbw2-passive-stale-session-recycle.md`, rule 4).

## 5. Candidate 1 Confirmation

Confirm each item, citing the source it restates:

- [ ] **Candidate 1 remains proposed only** — not approved behaviour,
      not established as safe, and **not approved to run** (E0 plan,
      section 4; E1 design, section 4);
- [ ] no raw frame appears in this document, in the completed
      checklist, or in the approval package — structural description
      only: the ASCII prefix `N` followed by a six-digit zero-padded
      sequence number, with no payload;
- [ ] no JSON payload; no token; no command field; no configuration
      write (E1 design, section 4);
- [ ] no second candidate in the same run — Candidate 1 failure never
      authorises Candidate 2 under the same approval (E0 plan,
      section 3);
- [ ] no retry burst — at most one send per cadence interval (E1
      design, section 4);
- [ ] no cadence faster than the approved cadence — the policy floor
      is unchanged;
- [ ] no send before the first valid status frame on the current
      connection;
- [ ] the sequence rule is understood exactly as decided in
      Commit 23: latest valid received sequence + 1, modulo 255, zero
      replaced by 1, six-digit formatting, **re-derived per send** —
      never a private outgoing counter; repeated identical candidate
      sequence values are an expected observable if the module does
      not echo (E1 design, section 5);
- [ ] the API PDF's 255→0 wrap rule is understood as a recorded
      **known difference** from the evidence-source rule; changing
      sequence arithmetic is a separate design decision and not part
      of this candidate (E1 design, section 5).

## 6. Startup Walkthrough

A human paper-review rehearsal of the E1 design's startup and refusal
flow (section 3). No step below connects to anything, and none is an
executable instruction: the participants read, discuss, and confirm.

- [ ] the pre-run safety checklist from the E1 design (section 8) has
      been read aloud or reviewed line by line;
- [ ] all participants confirm **no live connection occurs during E2
      itself** — the rehearsal is entirely on paper;
- [ ] the future target environment is identified between the
      participants **without recording addresses, ports, or other
      sensitive details** anywhere;
- [ ] the participants confirm that, before any future E3 run, the
      SmartLinq Home Assistant integration would be disabled/unloaded,
      Homebridge stopped, funtastix/rinnaitouch stopped, and the
      vendor app not actively controlling the system;
- [ ] the operator confirmation prompt (E1 design, sections 2–3) is
      read aloud or reviewed: it must name the exact candidate
      structure and the exact cadence, and any mismatch is a refusal;
- [ ] the participants confirm the future harness would connect
      **once only** per run;
- [ ] the participants confirm it would wait for the documented
      greeting if present, and for **at least one valid status
      frame**, before anything else;
- [ ] the participants confirm **no send occurs if no valid frame has
      arrived**;
- [ ] the participants confirm the send path arms only after a valid
      frame **and** operator confirmation, with the first send no
      earlier than the approved offset.

## 7. Refusal Conditions Walkthrough

Rehearse each refusal condition: for each, the operator states what
it means and confirms the response is **refuse to send, permanently
for the run**.

- [ ] no valid status frame on the connection;
- [ ] malformed or unknown stream — anything the operator cannot
      immediately explain;
- [ ] operator mismatch or uncertainty about the prompt, the
      candidate, or the cadence;
- [ ] a competing local client is discovered;
- [ ] wrong candidate, cadence, duration, or hard timeout relative to
      the approved values;
- [ ] any unsatisfied checklist item;
- [ ] unclear logging or sanitisation arrangements;
- [ ] the observer function is unavailable where the package requires
      it;
- [ ] operator concern of any kind.

Outcome rule: a refusal during a future E3 run — or an unresolved
refusal condition during this rehearsal — means **no E3 proposal
until corrected and re-reviewed**.

## 8. Abort Drill

A paper rehearsal: for each trigger, the operator and observer state,
in their own words, what they would do. Every answer must match the
single response pattern below.

Triggers rehearsed:

- [ ] HVAC state changes unexpectedly;
- [ ] a fault appears;
- [ ] the wall controller or vendor app becomes abnormal;
- [ ] the stream stops or no valid frame appears;
- [ ] a send error occurs;
- [ ] the greeting reappears unexpectedly mid-session;
- [ ] the connection closes, resets, or is refused;
- [ ] the operator or observer loses confidence;
- [ ] a competing client appears;
- [ ] any raw/protocol uncertainty appears.

Response pattern — identical for every trigger:

1. stop sending immediately;
2. close gracefully where possible;
3. no retry;
4. no automatic reconnect;
5. observe the system: wall controller, vendor app, HVAC behaviour;
6. recover via the validated passive paths only — passive recycle and
   re-enabling the integration (ADR 0002, rule 4);
7. document the outcome in the evidence summary;
8. no second candidate.

- [ ] the abort drill has been rehearsed, and its acknowledgement is
      recorded for the approval package.

## 9. Evidence and Sanitisation Review

Confirm the evidence discipline (E0 plan, section 10; E1 design,
sections 7 and 10):

- [ ] no raw frames are ever committed;
- [ ] no credentials;
- [ ] no IP addresses;
- [ ] no ports;
- [ ] no serials;
- [ ] no full JSON;
- [ ] no screenshots unless separately approved and sanitised;
- [ ] logs and evidence contain only lifecycle counters, coarse
      timings, booleans, and fixed labels;
- [ ] the sanitised evidence summary template (E1 design, section 10)
      is ready, including the installation-role fields;
- [ ] raw logs stay local unless sanitised per the existing
      procedure;
- [ ] completed dry-run checklists stay local by default; only a
      sanitised completion summary may enter the repository via a
      separately approved future commit.

## 10. Go / No-Go Decision

The only Go this checklist can produce is **"Go to E3 proposal"** —
it is never "Go run". E3 itself remains future and not approved
regardless of the outcome here.

**Go to E3 proposal** requires all of:

- [ ] every checklist item in sections 3–9 is satisfied;
- [ ] the environment is selected and recorded;
- [ ] operator and observer roles are clear — separation, or an
      explicitly recorded and accepted exception;
- [ ] the candidate and cadence are understood by every participant;
- [ ] the abort drill has been rehearsed and acknowledged;
- [ ] evidence handling is agreed;
- [ ] the reviewer accepts the package;
- [ ] no unresolved wording, protocol, or safety uncertainty remains.

**No-Go** if any checklist item fails, any participant is uncertain,
or completing the package would require committing sensitive
information. A No-Go outcome means no E3 proposal until the failure
is corrected and the dry-run is re-reviewed.

A Go outcome permits exactly one thing: drafting a **separate E3
approval request** (section 11). It does not schedule, approve, or
run anything.

## 11. E3 Approval Package

Before E3 can be separately proposed, all of the following must
exist:

- the completed E2 dry-run checklist — held locally by the operator,
  per section 1's instrument-handling rules;
- the selected installation role;
- the candidate, cadence, duration, hard-timeout, and post-run
  observation values;
- the operator/observer role assignment, including any explicitly
  accepted same-person exception;
- the abort-drill acknowledgement;
- the sanitisation plan;
- the evidence summary template, ready to fill;
- an explicit statement that **E2 does not approve E3** — completing
  this checklist grants nothing;
- an explicit, separate E3 approval request, to be decided at that
  future time — approval is given at run time or not at all (E1
  design, section 11).

The package contains no addresses, ports, serials, credentials, raw
frames, payloads, or full JSON. If any part of it enters the
repository, it does so as a sanitised summary in a separately
approved future commit.

## 12. Relationship to Gate E Phases

- **E0 — paper experiment plan**: delivered by Commit 22
  (`gate_e_session_maintenance_experiment_plan.md`).
- **E1 — offline harness design**: delivered by Commit 23
  (`gate_e_standalone_harness_design.md`).
- **E2 — dry-run review**: **Commit 24 delivers the E2 dry-run review
  checklist only.** Creating the checklist is not the same as
  performing the dry-run: no dry-run has occurred, and none is
  scheduled by this document. A future completed dry-run may support
  an E3 **proposal** only after separate review.
- **E3 — one controlled live experiment**: **E3 remains future** and
  **not approved**; separate explicit approval is given at run time
  or not at all.
- **E4 — evidence review and ledger decision**: remains future; the
  only phase that may change any ledger entry. **A11 remains
  Unknown** until a separately approved ledger change, if any ever
  occurs.

No phase auto-triggers the next, and approval of any phase does not
imply approval of a later one. **Gate E remains operationally
unadvanced**: no Transport Keepalive Policy gate condition is
declared satisfied by this document, and no traffic is approved.

## 13. Explicit Non-Goals

This document, and the commit that introduces it:

- is a **dry-run review only** instrument — a **paper/operator
  rehearsal**; performing it connects to nothing;
- involves **no live traffic** and **no network operation** — no TCP,
  no UDP, no discovery, no packet capture, no runtime operation;
- creates **no executable artefact** — no harness, no code, no
  script, no test, no fixture, no pseudocode; the future harness
  remains unimplemented;
- changes **no runtime behaviour** — no Home Assistant integration
  change, no keepalive support, no command/control code, no climate
  entities, switches, buttons, numbers, selects, or services;
- **validates no command and no candidate** — **Candidate 1 remains
  proposed only**: not approved behaviour, not established as safe,
  and **not approved to run**;
- **changes no ledger entry** — **A11 remains Unknown**;
- **does not advance Gate E operationally** — it delivers the E2
  dry-run review checklist only; **E3 remains future** and not
  approved, and E4 remains future;
- **makes no universal N-BW2 compatibility claim** — every element
  concerns a **single local installation only**, whether primary or
  redundant/non-primary;
- **approves no Home Assistant runtime keepalive** — the E1 design's
  runtime boundary stands unchanged;
- describes an **operator-controlled** future process — never an
  autonomous one — and changes no release, tag, or version.
