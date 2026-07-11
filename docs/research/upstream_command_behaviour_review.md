# Upstream Command Behaviour Review

This is a **source review, not a validation exercise**. It maps how two
working external integrations (and the protocol library one of them uses)
behave against Rinnai Touch / N-BW2 modules, based entirely on reading
their source code at pinned versions. No live traffic was sent, no
implementation was performed, no command was validated, and no entry in
`../protocol_assumptions.md` changes as a result of this document.
Ledger item A11 remains **Unknown**, Gate E is **not advanced**, and no
universal N-BW2 compatibility claim is made.

Reviewed: 11 July 2026.

## 1. Purpose and Scope

SmartLinq's integration is at v0.1.0: passive, read-only, validated on
one local installation (Gate D). Two external integrations have been
manually confirmed by the user to work against the same unit, including
sending commands. Their source is therefore valuable **evidence for
future planning**. This review maps, from source only:

- what inbound status fields/signals they use;
- what outbound traffic they send, grouped by purpose;
- how they maintain local TCP sessions;
- how they handle discovery and onboarding;
- how they represent modes, setpoints, fan, zones, faults, and
  controller state;
- where the two implementations agree, differ, or are ambiguous;
- what risks exist if SmartLinq ever chooses to validate outbound
  behaviour.

This review **is**: documentation of upstream-observed behaviour, at
pinned source versions, sanitised per repository rules.

This review **is not**:

- live traffic of any kind (none was sent, received, or captured);
- implementation (no integration code, tests, or configuration changed);
- command validation (no command was sent; none is established as safe);
- a change to ledger item A11, which remains Unknown;
- Gate E advancement (no outbound session-maintenance step is approved);
- a compatibility claim (all local evidence remains one installation);
- approval to implement controls, a climate entity, or discovery.

Both upstream implementations send outbound traffic as a matter of
routine. **That fact validates nothing for SmartLinq.** Upstream code
sending a byte is evidence that a byte *can* be sent by someone else's
implementation on the installations they tested, not that SmartLinq
sending it is safe, required, or approved. Every SmartLinq outbound
decision remains behind its existing gates.

## 2. Sources Reviewed

| # | Local read-only reference | Upstream project | Pinned version | Licence |
|---|---|---|---|---|
| 1 | `../../../Rinnai-touch-reference/upstream-ha-rinnaitouch` | `funtastix/rinnaitouch` (Home Assistant custom component) | tag 0.13.4b1, commit `9e7f933` | MIT |
| 2 | `../../../Rinnai-touch-reference/upstream-pyrinnaitouch` | `funtastix/pyrinnaitouch` (Python protocol/client library) | tag 0.13.4b1, commit `96092bd` | MIT |
| 3 | `../../../Rinnai-touch-reference/upstream-homebridge-rinnai-touch-platform` | `mantorok1/homebridge-rinnai-touch-platform` | v3.4.18, commit `c4ea9e6` | Apache-2.0 |

Sources 1 and 2 form one integration stack: the Home Assistant component
contains **no wire-protocol code** — every socket, session, parsing, and
command byte lives in `pyrinnaitouch`, which the component pins exactly
(`pyrinnaitouch==0.13.4b1` in its manifest). Statements below about
"the funtastix stack" name the layer they come from.

Source 3 matches the version already pinned in the Provenance section of
`../protocol_assumptions.md`.

Key files reviewed include `pyrinnaitouch/pollconnection.py`,
`system.py`, `commands.py`, `const.py`, `system_status.py`,
`unit_status.py`, `zone.py` (source 2, all modules read); every
integration module of source 1; and `src/rinnai/RinnaiSession.ts`,
`TcpService.ts`, `UdpService.ts`, `RinnaiService.ts`,
`src/models/Command.ts`, `Message.ts`, `Status.ts`, `Fault.ts`,
`src/platform.ts`, and the docs of source 3.

The `pyrinnaitouch` repository **bundles the N-BW2 API specification PDF
(`NBW2API_Iss1.3.pdf`)** and its README states the interface
specification is contained in that document. Its presence on local disk
is recorded here; its **content was deliberately not reviewed** in this
commit — see sections 10 and 11. Reviewing it is the natural candidate
for keepalive gate condition (1) in `AGENT_SCOPE.md`.

Evidence discipline: everything below is an **upstream source fact**
(what the code does), unless explicitly marked as an upstream
documentation claim or cross-referenced to this project's own ledger
evidence. Upstream source facts describe those implementations, not the
module: what the module requires or tolerates remains governed by the
ledger's validation states.

## 3. SmartLinq Current Baseline

For contrast, the validated v0.1.0 baseline (see `../../README.md`,
`../protocol_assumptions.md`, ADR 0002):

- local TCP status monitoring with a robust rolling frame parser;
- Home Assistant config flow (manual host entry, explicit user-action
  validation connection) and six read-only entities;
- freshness model driven by valid-frame timestamps, never socket state;
- passive idle-timeout session recycle (ADR 0002): a bounded read-idle
  interval triggers a graceful close and reconnect, transmitting
  nothing; parameter values are deliberately not recorded in
  documentation;
- **no outbound bytes of any kind**: no keepalive, no polling, no
  acknowledgements, no commands, no control entities, no climate
  platform;
- Gate D passed on one local N-BW2 installation: approximately five
  days, approximately 932 automated passive recycles, first-attempt
  recovery approximately 99.7%, zero refused sessions, zero frameless
  idle-timeout sessions (single-installation evidence only; ledger items
  A15/A16 are Partially validated, A11 Unknown).

## 4. Connection and Session Lifecycle Comparison

All timing values in this section are **upstream implementation
parameters read from source**, recorded for comparison only. They are
not module requirements, not validated against this project's module,
and not SmartLinq parameters.

| Aspect | Homebridge v3.4.18 | pyrinnaitouch 0.13.4b1 | SmartLinq v0.1.0 |
|---|---|---|---|
| Connect flow | 3 attempts 500 ms apart; on total failure wait 60 s and repeat forever | single attempt per loop with fixed sleeps between failures (5 s after refused/timeout, 10 s otherwise), forever | supervised sequential connect with backoff schedule (2/5/10/30/60 s), reset only after a valid session |
| Connect timeout | 5 s socket timeout | 5 s, then socket switched to non-blocking | bounded connect timeout (see `client.py`) |
| "Connected" means | first **valid status frame** received (connect promise resolves in the data handler) | TCP connect succeeded (frames come later) | TCP established; availability/freshness always derive from valid frames, never the socket |
| Greeting | not consumed explicitly; frame parser simply never matches it | consumed explicitly; the first `*HELLO*` is logged, a duplicate is logged as a suspected unit reset | treated as discardable pre-frame bytes; presence recorded as a log-only boolean (ledger A14) |
| Idle / no-data watchdog | 5 s socket inactivity timeout → destroy socket → reconnect | 30 s without received data → forced reconnect | bounded read-idle recycle, no transmission (ADR 0002) |
| Session maintenance | cron job **once per minute**: bare sequence header, no payload, no acknowledgement awaited | idle frame whenever **more than 10 s** have passed since the last outbound send: sequence header plus a short non-JSON two-character ASCII token; participates in the sequence-acknowledgement wait | **none — transmits nothing** |
| Reconnect pacing | 2 s delay after error, then the connect flow above | fixed 5 s / 10 s sleeps; plus a UDP readiness gate on some paths (section 5) | backoff schedule plus a post-recycle delay floor |
| Close semantics | abrupt socket destroy | shutdown-both-directions then close | graceful close and `wait_closed` on every path |
| Startup gating | blocks until first status frame, then until controller state is Normal (retries every 60 s) | returns immediately; status arrives asynchronously | config-flow validation requires at least one valid snapshot; runtime startup never blocks |
| Duplicate frames | deduplicated by exact status-text comparison; repeats never reach subscribers | no deduplication; every frame processed | every valid frame refreshes freshness and reaches listeners by design |
| Multi-client guard | documentation warning only | in-process duplicate-connection guard raises an error, citing hardware intolerance | documentation warnings; single shared client per entry by construction |

Observations:

- Both upstream implementations pair **periodic outbound idle traffic at
  cadences well below five minutes** with a **bounded no-data watchdog
  that closes and reconnects**. Neither passively holds a silent socket.
  This corroborates, from primary source, what the ledger already
  records as external behavioural evidence.
- The two idle-traffic forms **differ structurally** (bare header once
  per minute vs header-plus-token roughly every ten seconds of send
  inactivity). No single session-maintenance form is therefore validated
  by upstream agreement, and **A11 remains Unknown**.
- The upstream troubleshooting documentation (source 3) claims the
  module disconnects clients that send nothing for about five minutes
  and that its once-per-minute blank command prevents this. This
  project's own field evidence instead observed streaming stop after
  roughly five minutes with the TCP connection retained from the client
  side (ledger A2). These readings are **presented side by side without
  a forced conclusion**; the bundled API PDF may resolve the mechanism
  and should be reviewed as its own milestone.
- SmartLinq's passive recycle is the transmission-free analogue of the
  upstream watchdog-reconnect pattern, and remains the approved fallback
  recovery path regardless of any future outbound decision (ADR 0002).

## 5. Discovery and Onboarding Behaviour

Three distinct patterns were observed:

**Homebridge — discovery proper.** When no address is configured, it
binds the documented UDP discovery port, waits for a module broadcast
carrying the documented module prefix, takes the module's IP from the
datagram source and the TCP port from a fixed byte offset in the
datagram (both facts already recorded in `../protocol_assumptions.md`),
and connects. With a static address configured, UDP is never used. In
discovery mode the address is deliberately forgotten on every disconnect
and re-discovered on reconnect.

**pyrinnaitouch — readiness gate, not discovery.** The module address is
always user-configured. Before connecting, the library binds the same
UDP port **receive-only** (verified: the UDP socket never transmits) and
waits for a broadcast **whose source address matches the configured
module** before attempting TCP; after six 5-second timeouts
(about 30 s) it attempts TCP anyway. The gate runs only when the
connection state is idle on entering the connect routine (initial start,
remote EOF, socket I/O errors); reconnects triggered by the 30 s
watchdog, refused/timed-out connects, or parse errors bypass it. Upstream
history indicates this replaced a fixed delay to make restarts reliable —
i.e. it treats the broadcast as a **module-readiness signal**.

**funtastix HA wrapper — manual entry, user-declared topology.** The
config flow takes a host plus **user checkboxes for zones A–D and
Common**, and optional per-zone external temperature sensor entities (a
workaround for controllers that report no temperature). No UDP appears
in the flow. Its setup "validation" only starts the connection thread
and returns; connection failures surface asynchronously, and the try
block mainly catches the duplicate-connection guard.

**Separately: active capability discovery (Homebridge).** On first run
(or when forced), `platform.ts` `findDevices()` enumerates capabilities
by **powering the system on and cycling through every installed
operating mode**, then restoring the prior state, caching the result to
a file. This approach is already **forbidden** for SmartLinq in all
phases (`AGENT_SCOPE.md`, Capability Discovery Boundary); SmartLinq's
passive cumulative observation is the approved alternative.

Conclusions for SmartLinq:

- Discovery is demonstrably a **convenience, not a prerequisite** for
  status or command behaviour: one working stack ships without any
  discovery in its onboarding, and the other makes it optional.
- Discovery therefore stays **parked on the roadmap — parked, not
  deleted** (section 10, row 10). The readiness-gate variant (UDP as a
  listen-only "module is up" signal, distinct from address discovery) is
  recorded as a design idea worth evaluating whenever discovery is
  unparked; it would be a new receive-only network surface and would
  need its own approval.

## 6. Status / Read Model Comparison

**Corroboration.** The three sources agree on the status vocabulary
already recorded in the ledger's status group map: `SYST` with `CFG` /
`AVM` / `OSS` / `FLT` / `STM`; mode groups `HGOM` / `CGOM` / `ECOM` with
`CFG`, `OOP` or `GSO`, `GSS`, `Z?O`, `Z?S`; the documented value maps
for `MD`, `ST`, fault fields, `MT` tenths with the no-reading sentinel,
setpoint ranges, and the below-8 zone-off idiom on multi-setpoint
systems. Nothing found in this review contradicts the committed map.

**Three model philosophies.** The implementations differ sharply in how
they *hold* state:

- Homebridge: one flat store; each received top-level group replaces the
  stored copy of that group; other groups are retained; mode is derived
  from `OSS.MD`.
- pyrinnaitouch: a **fresh status object per frame**, replacing the
  previous one wholesale; parsing is positional (it expects `SYST`
  first and the mode group second); mode is derived from **which mode
  group is present in the frame** (heating over cooling over
  evaporative), not from `OSS.MD`; a frame with no mode group is
  dropped and the previous status object is kept; a single-group frame
  is handled only as a time-setting special case.
- SmartLinq: per-group replace plus **cumulative capability/zone
  latches** and a monotonic freshness model; mode from `OSS.MD`;
  single-element and empty frames are ordinary inputs.

Neither upstream has a data-freshness model; availability heuristics are
coarse (e.g. the funtastix main entity is available whenever a mode
group has been seen). SmartLinq's freshness-first model is retained
deliberately.

**Fields upstream reads that SmartLinq's typed model does not yet
surface.** All are read from the same status stream this integration
already receives, so they are candidates for **read-only** work:

| Area | Fields (subgroup-scoped mnemonics) | Upstream use |
|---|---|---|
| Activity flags (heat) | `GSS`: `HC`, `PH`, `GV`, `FS` (per-zone in `Z?S` on multi-setpoint) | calling-for-heat, preheating, gas valve, fan active |
| Activity flags (cool) | `GSS`: `CC`, `CP`, `FS` (per-zone variants) | calling-for-cool, compressor, fan active |
| Activity flags (evap) | `GSS`: `BY`, `PW`, `PO`, `FO` | busy, prewetting, pump operating, fan operating |
| Schedule | `GSS`/`Z?S`: `AT`, `AZ`; `GSO`/`Z?O`: `AO` | schedule period, advanced period, override state |
| Fan | `OOP`/`GSO`: `FL` | fan speed level |
| Evap operation | `GSO`: `SW`, `FS`, `PS` | switch, fan state, pump state |
| Module info | `CFG`: `VR`, `CV` | firmware and Wi-Fi module version strings |

Caution recorded for future mapping work: **two-letter mnemonics are
subgroup-scoped, not global** (upstream uses `FS` as evaporative fan
state in `GSO` but fan-active in `GSS`; other keys likewise change
meaning by context). Any SmartLinq mapping must key on the full
group/subgroup path, as the current model already does.

A stale test fixture in the library also shows further undocumented
two-letter keys under `OSS`, `CFG`, `AVM`, and `FLT`, and at least one
additional subgroup — corroborating this project's own private-capture
observation of undocumented fields. These remain diagnostic-only.

**Risk framing.** Expanding the **read-only** model is categorically
lower risk than any command/control work: it consumes the stream the
integration already receives, transmits nothing, and is testable
offline against synthetic fixtures. The field candidates above are
inputs to the passive semantic mapping plan
(`passive_semantic_mapping_plan.md`) — evidence for planning, with
ledger updates and entities only after separately approved evidence.

## 7. Outbound Behaviour and Command Taxonomy

**Boundary first:** everything in this section is **evidence for future
planning only**. It is not approval to implement controls, not command
validation, and not a safety claim. No cloud or account path exists in
any reviewed source — every outbound behaviour is local TCP.

**Shared command grammar (both stacks agree).** A command is the next
outgoing sequence header followed by one single-path nested JSON object:
group → subgroup → field → short string value, exactly the shape already
recorded in `AGENT_SCOPE.md` and the ledger. Outgoing sequence numbers
derive from the last received sequence, modulo 255, zero-padded to six
digits.

**Confirmation models differ.** Homebridge validates a command against
current status (skips it when the state already matches), then waits up
to 10 s for a status frame reflecting the requested values, retrying the
write up to 3 times. pyrinnaitouch performs mode-appropriateness
validation only, then treats a received sequence number ≥ the sent one
as the acknowledgement (5 s gate before the next queued command), with
no content check, no retry, and no skip-if-already-set. SmartLinq's
existing Phase 2 principles (serial queue, capability validation,
confirm by status, no silent success) are closest to the Homebridge
model; this review does not choose a winner.

**Taxonomy.** Classification values: *passive-safe already implemented*
/ *Gate E planning only* / *future command-harness planning* / *too
risky, out of scope* / *unclear, needs more source review*.

| Purpose | Field path (structural) | Homebridge | funtastix stack | HVAC state change? | Reversible? (inferred) | SmartLinq classification |
|---|---|---|---|---|---|---|
| Session maintenance | header only / header + short non-JSON two-character ASCII token | bare header, 1/min | header+token after >10 s send-idle | not intended to (unvalidated; A11 Unknown) | n/a | **Gate E planning only** |
| Status request / refresh | — | none exists | none exists | n/a | n/a | n/a — streaming is unsolicited; the passive receive side is already implemented |
| Operating mode change | `SYST.OSS.MD` ← `H`/`C`/`E` | yes | yes | **yes** | yes, by converse command | future command-harness planning |
| Power on / off | mode `OOP.ST` ← `N`/`F`; evap `GSO.SW` ← `N`/`F` | yes | yes | **yes** | yes | future command-harness planning |
| Fan-only | mode `OOP.ST` ← `Z` | yes | yes | **yes** | yes | future command-harness planning |
| Fan speed | `OOP.FL` / evap `GSO.FL` (two-digit value) | yes | yes | **yes** | yes | future command-harness planning |
| Setpoint / comfort | `GSO.SP` or `Z?O.SP` (two-digit); evap `GSO.SP` comfort | yes | yes | **yes** | yes | future command-harness planning |
| Zone enable / disable | `Z?O.UE` ← `Y`/`N`; evap `GSO.Z?UE` | yes | yes | **yes** | yes | future command-harness planning |
| Zone off (multi-setpoint idiom) | `Z?O.SP` below 8 (zero sent) | yes (via setpoint floor) | yes (explicit zero) | **yes** | yes (restore setpoint) | future command-harness planning; both stacks agree on the idiom |
| Control mode (manual/auto) | `GSO.OP` / `Z?O.OP` ← `M`/`A` | yes | yes | **yes** (schedule behaviour) | yes | future command-harness planning |
| Schedule advance / cancel | `GSO.AO` / `Z?O.AO` | yes (`N`/`A`/`O` values) | yes; **zone cancel template is textually identical to zone advance** (apparent upstream defect) | **yes** | intended, but see defect | unclear, needs more source review |
| Evap zone auto/manual | Homebridge: none per-zone; pyrinnaitouch writes `GSS.Z?AE` | read-only use of `Z?AE` | **writes a `GSS` field** other sources treat as status | **yes** | unclear | unclear, needs more source review |
| Day/time set | three-step: `SYST.OSS.ST` ← clock-set state, then `STM.DY`+`TM`, then `STM.SV` ← `Y` | API exists, **no caller** | yes (service) | controller state change (clock mode), not plant state | partially | unclear, needs more source review; not an early candidate — it drives the controller through a settings state |
| Operating state write (standalone) | `SYST.OSS.ST` | API exists, no caller | only as step 1 of day/time | controller state | unclear | unclear, needs more source review |
| Pump control | evap `GSO.PS` ← `N`/`F` | yes | yes | **yes** | yes | future command-harness planning; operationally sensitive, late candidate |
| Module reboot | credentialed non-JSON form (already quoted, and forbidden, in `AGENT_SCOPE.md`) | yes — optional scheduled daily job using the module's Wi-Fi credential | **absent** (no such code in 0.13.4b1) | **yes** — restarts the module | n/a | **too risky, out of scope** (existing prohibition stands) |
| Active capability discovery | composite: power-on + mode cycling | yes (`findDevices`) | not needed (user declares zones) | **yes** | restores prior state | **too risky, out of scope** (already forbidden) |
| Cloud / account actions | — | none | none | n/a | n/a | n/a |

Notes:

- The **first non-HVAC-state-changing outbound candidate** for SmartLinq
  is the session-maintenance frame itself — which is exactly Gate E, and
  it stays gated (register row 6). Every other observed write changes
  HVAC, zone, schedule, or controller state.
- "Reversible" above is an inference from upstream code paths (a
  converse command exists), not a validated property.
- Command *success semantics* matter as much as command forms: upstream
  demonstrates two different acknowledgement models, and any future
  SmartLinq harness must pick and validate one deliberately.

## 8. Implementation Differences and Ambiguities

Differences (no winner forced; where behaviour disagrees, the module's
actual requirement is unknown until authoritative documentation or
separately approved evidence resolves it):

1. **Idle-traffic form and cadence**: bare sequence header once per
   minute (Homebridge) vs header plus short non-JSON token roughly every
   ten seconds of send inactivity (pyrinnaitouch).
2. **Sequence zero**: Homebridge skips zero when wrapping (transmitted
   range 1–254); pyrinnaitouch's arithmetic can emit zero. The ledger's
   "sequence zero is skipped" row is therefore **Homebridge-specific
   behaviour, not a demonstrated protocol requirement** (no ledger
   change is made by this review; the nuance is recorded here).
3. **Sequence base**: last-received+1 (Homebridge) vs
   max(own+1, last-received+1) with reset to 1 on every connect
   (pyrinnaitouch).
4. **Acknowledgement**: status-content confirmation with retries vs
   numeric sequence acknowledgement without retries.
5. **Watchdog horizon**: 5 s socket inactivity vs 30 s without data.
6. **Reconnect pacing**: short-burst attempts with a long fallback wait
   vs fixed short sleeps, plus pyrinnaitouch's conditional UDP readiness
   gate.
7. **UDP role**: address/port discovery vs listen-only readiness gate.
8. **Frame extraction**: Homebridge keeps only the last frame in a read
   (documented in the ledger); pyrinnaitouch regex-matches the first
   complete frame, assumes positional group order, and tears the session
   down on unparseable input (its resynchronisation branch is
   unreachable as written). SmartLinq's structural rolling parser is
   independent of both.
9. **Mode derivation**: `OSS.MD` vs presence-of-mode-group.
10. **State retention**: per-group replace vs whole-object replace per
    frame.
11. **Duplicate handling**: dedupe vs process-every-frame.
12. **Close semantics**: abrupt destroy vs shutdown-then-close.
13. **Reboot capability**: present but optional (Homebridge) vs absent
    (pyrinnaitouch 0.13.4b1). Irrelevant to SmartLinq: forbidden either
    way.
14. **Startup gating**: block-until-Normal-state vs return-immediately.

Ambiguities recorded without conclusion:

- What the module actually requires to keep a session streaming (form,
  cadence, or whether inbound traffic is the trigger at all) — the A2
  tension between upstream documentation claims and this project's own
  silence-with-connection field evidence stands unresolved. The bundled
  API PDF is the most likely resolver (separate milestone).
- Whether writing the `GSS.Z?AE` field is a legitimate evaporative
  zone-control path or an upstream quirk.
- Whether the pyrinnaitouch zone advance-cancel template (identical to
  its zone advance template) is a defect; the Homebridge cancel path
  differs.
- Whether sequence-zero emission is tolerated by the module.
- Reverse-cycle systems remain unmodelled in every reviewed source.

## 9. Licensing and Code-Reuse Boundary

| Source | Licence | Attribution state |
|---|---|---|
| `funtastix/rinnaitouch` | MIT | not currently in `NOTICE` (no code used) |
| `funtastix/pyrinnaitouch` | MIT | not currently in `NOTICE` (no code used) |
| `mantorok1/homebridge-rinnai-touch-platform` | Apache-2.0 | attributed in `NOTICE` as the protocol reference |

Both licences are permissive and would allow code reuse with
attribution. **This project's policy is stricter and stands: no
implementation code is copied from any upstream source.** The SmartLinq
integration is independently implemented in Python. Acceptable use of
these sources is exactly:

- behavioural understanding (this document);
- independently implemented mappings derived from that understanding;
- offline tests built on sanitised or synthetic evidence;
- documentation of observed upstream behaviour with provenance.

Mechanical translation of upstream code remains out of scope. `NOTICE`
is deliberately **not** modified in this commit; whether to add
courtesy attribution for the funtastix projects (whose behavioural
evidence now informs project documentation) is left as an explicit
maintainer decision for a future commit.

## 10. SmartLinq Risk-Ranked Adoption Register

Ordered lowest risk first. "Not before" conditions are binding.

| # | Item | Value | Evidence source | Risk | Preconditions | Recommended next action | Not before |
|---|---|---|---|---|---|---|---|
| 1 | Maintain passive recycle as the standing fallback | keeps validated v0.1.0 behaviour; recovery path independent of any outbound future | Gate D soak (ledger A15/A16); upstream watchdog parallels | low — already validated on one installation | none | keep unchanged; continue field observation via issue templates | n/a — current state |
| 2 | Passive semantic mapping with real wall controller/app | turns observed fields (section 6) into validated meanings | Commit 18 plan; upstream read models | low — read-only, user-operated | v0.1.0 installed; competing clients disabled | execute `passive_semantic_mapping_plan.md` and record evidence | user schedules the exercise |
| 3 | Read-only entity expansion | activity flags, schedule state, fan speed, module versions as diagnostics | section 6 field table; upstream entity precedents | low–moderate — no transmission; risk is semantic error | row 2 evidence for each field; ledger updates approved | scope a small entity/fixture commit per validated field cluster | not before row 2 evidence exists for the fields concerned |
| 4 | NBW2 API PDF review | authoritative answers on session maintenance, sequences, command semantics | bundled document in source 2 | low — reading a local document | separate scoping (it is a substantial document) | propose a dedicated documentation-review milestone | its own approved milestone — **not this commit** |
| 5 | Gate E session-maintenance planning (planning only) | a written experiment design for holding a session open, if ever approved | section 4 comparison; keepalive policy | moderate — planning is paper-only, but drift risk into implementation must be resisted | row 4 complete; A11 review; explicit user approval of the plan's scope | draft the controlled-experiment design document only | not before the PDF review; grants no traffic |
| 6 | First non-HVAC-state-changing outbound candidate | = the session-maintenance frame itself | section 7 taxonomy (only candidate in class) | high — first byte ever transmitted; module tolerance unknown (A11) | rows 4–5; separately approved controlled experiment; explicit user approval | none now | not before Gate E's three gate conditions are all met |
| 7 | Standalone command harness planning (paper only) | design for a user-run, non-integration command test tool with confirmation semantics | section 7 taxonomy; both upstream ack models | moderate as paper; high the moment it becomes code | rows 4–6 learnings; explicit scoping | none now | not before row 6 has validated evidence |
| 8 | First HVAC-state-changing command candidate (likely a single setpoint step) | smallest reversible plant-affecting write | section 7; both stacks agree on `SP` semantics | very high — changes a real heating/cooling plant | rows 4–7; harness exists; user present; documented rollback | none now | not before the command harness is approved and validated |
| 9 | Climate entity and zone controls | full Phase 2 user surface | `AGENT_SCOPE.md` Phase 2; upstream entity models | very high — everyday control surface multiplies exposure | Phase 2 approval; rows 4–8; entity-model decisions | none now | not before Phase 2 is explicitly opened |
| 10 | Discovery / onboarding (parked) | setup convenience; possible readiness-gate variant | section 5 | moderate — new receive surface; multi-module questions | separate approval; A10 validation | none now — **parked, not deleted** | not before a dedicated scoping decision |

## 11. Recommended Next Milestones

In order, each requiring its own approval and none started by this
document:

1. **Execute the passive semantic mapping plan** (Commit 18) on the real
   installation — read-only, user-operated; produces the evidence that
   everything else in section 6 depends on.
2. **Read-only entity expansion**, in small validated clusters, only for
   fields whose meaning row-2 evidence confirms.
3. **NBW2 API PDF review** as a dedicated documentation milestone —
   deliberately **not** part of this commit. This addresses keepalive
   gate condition (1) and is the cheapest way to resolve several
   section 8 ambiguities.
4. **Gate E planning document** (paper only, after the PDF review):
   experiment design for session maintenance, including abort criteria
   and rollback. Producing the plan grants no traffic; A11 changes only
   through the full gate sequence.
5. **Command harness planning** (paper only, later): confirmation
   semantics, serialisation, capability checks, and refusal behaviour,
   informed by both upstream acknowledgement models.
6. **Discovery remains parked** until deliberately unparked; the
   pyrinnaitouch readiness-gate variant is noted for that future
   discussion.

## 12. Explicit Non-Goals

This document, and the commit that introduces it:

- is **source review only** — reading pinned local checkouts;
- **sent no live traffic** — no TCP, no UDP, no discovery, no packet
  capture, no connection to any module, and nothing was executed from
  any upstream repository;
- **implemented nothing** — no integration code, tests, entities,
  configuration, or tooling changed;
- **validated no command** — no outbound byte of any kind is established
  as safe, required, or approved by this review;
- **changes no ledger entry** — in particular **A11 remains Unknown**;
- **does not advance Gate E** — outbound session maintenance stays fully
  gated behind authoritative-documentation review, a separately approved
  controlled experiment, and explicit user approval;
- **makes no universal N-BW2 compatibility claim** — all local evidence
  remains a single installation, and upstream behaviour describes
  upstream implementations, not every module or firmware;
- **copies no upstream code** and proposes no control entities, no
  climate platform, no discovery implementation, and no change to the
  passive posture of v0.1.0.
