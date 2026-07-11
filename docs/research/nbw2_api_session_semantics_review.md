# NBW2 API Session Semantics Review

This is a **vendor-document review, not a validation exercise**. It
records what the N-BW2 API specification bundled with the pinned
`pyrinnaitouch` reference checkout says about transport, session,
framing, status, and command semantics, and compares that against
SmartLinq's own field evidence and the upstream implementations reviewed
in `upstream_command_behaviour_review.md`. No live traffic was sent, no
implementation was performed, no command was validated, and no entry in
`../protocol_assumptions.md` changes as a result of this document.
**There is no automatic A11 change: ledger item A11 remains Unknown
unless a later, separately approved review changes it.** Gate E is
**not advanced**, and no universal N-BW2 compatibility claim is made.

Reviewed: 11 July 2026.

## 1. Purpose and Scope

Commit 19 identified the bundled N-BW2 API PDF as the authoritative
documentation named by the Transport Keepalive Policy's gate
condition (1) and as the most likely resolver of several recorded
ambiguities. This review reads that document — all 48 pages — and maps
its content onto the questions SmartLinq actually has:

- what the module requires of a connected TCP client;
- whether a dedicated keepalive/idle message exists;
- what the sequence-number and acknowledgement rules are;
- which status fields and write fields are documented, with what
  read/write access;
- where the document confirms, contradicts, or is silent about
  SmartLinq field evidence and the upstream implementations.

This review **is**: a reading of one vendor document, sanitised per
repository rules, with every claim labelled as documented behaviour,
observed evidence, or inference.

This review **is not**:

- live traffic of any kind (none was sent, received, or captured);
- implementation (no integration code, tests, or configuration changed);
- command validation (no command was sent; none is established as safe);
- an A11 change (A11 remains Unknown; see section 8);
- Gate E advancement (see section 8);
- a compatibility claim (the document has one issue date and no
  firmware-variance caveats; all SmartLinq field evidence remains one
  installation);
- approval to implement controls, keepalives, discovery, or entities.

## 2. Source Document Identity

| Property | Value |
|---|---|
| Title | N-BW2 Networker Bridge (WIFI) Application Programmers Interface |
| Issue | 1.3 |
| Document reference | API-N-BW2 |
| Length | 48 pages |
| Authorship | prepared, checked, and approved by a named Rinnai engineer |
| First release | Issue 1.0, dated 04/04/18 |
| This issue | Issue 1.3, dated 13/11/19 |
| Location reviewed | `NBW2API_Iss1.3.pdf` in the pinned read-only `pyrinnaitouch` reference checkout (tag 0.13.4b1, commit `96092bd`) |

The change history records: Issue 1.1 added the zone measured
temperature (`MT`) to single-set-point zone status; Issue 1.2 changed
the configuration-command delimiter to a carriage return, added version
fields to `SYST.CFG`, a temperature-display option to `ECOM.CFG`, and
extra information to the UDP broadcast packet; Issue 1.3 added `MT` to
the evaporative `GSS` group.

Scope: the document describes exactly the interface SmartLinq consumes —
the N-BW2 bridge's local TCP-over-Wi-Fi API plus its UDP broadcast — for
Networker-based systems (N-C3/N-C6 and Brivis Touch N-C7; a documented
`SYST.CFG` flag, `NC`, identifies N-C7-based systems). The
`pyrinnaitouch` README states the interface specification is contained
in this PDF.

Authority framing used throughout this review:

- The document is treated as **authoritative for documented behaviour**:
  where it marks a field read-only or defines a mechanism, that is the
  vendor's stated contract.
- It is **not exhaustive**: its own test-application screenshots show
  status fields that do not appear in its tables (section 6), it
  contains no multi-client statement, and it has no firmware-variance
  caveats. Silence in the document is therefore never treated as
  evidence of absence on the wire.
- It was read as rendered pages (all 48). One legibility caveat is
  recorded honestly: the read/write access marker on the setpoint (`SP`)
  rows of the heat/cool tables could not be resolved with certainty at
  render resolution. The document's own worked examples write `SP`, so
  writability is not in doubt; only the table cell is flagged (sections
  7 and 10).

## 3. SmartLinq Baseline Before Review

Unchanged by this document (see `../protocol_assumptions.md`,
`../adr/0002-nbw2-passive-stale-session-recycle.md`, and
`upstream_command_behaviour_review.md`):

- v0.1.0 is passive and read-only: no outbound bytes of any kind — no
  keepalive, no polling, no acknowledgements, no commands.
- Freshness derives from valid-frame timestamps, never socket state.
- The passive idle-timeout recycle (ADR 0002) is the validated recovery
  behaviour on one local installation (Gate D: approximately five days,
  approximately 932 automated recycles, approximately 99.7%
  first-attempt recovery, zero refused sessions).
- Relevant ledger states before and after this review: A2 (stream stops
  after roughly five minutes; connection retained from the client side)
  — Revised by evidence; A11 (any idle keepalive form is
  side-effect-free and sufficient) — **Unknown**; A14 (greeting) —
  Partially validated; A15/A16 (recycle restores streaming; module
  tolerates recycle cadence) — Partially validated.

Any ledger change motivated by this review requires its own separately
approved commit; none is made here.

## 4. Transport and Session Semantics

Everything in this section is **documented behaviour** unless labelled
otherwise.

**UDP broadcast.** Once associated (access-point or station mode), the
module broadcasts a 256-byte UDP packet **every second** on the
documented discovery port. The packet layout is fully documented: an
identification tag; the TCP port as a big-endian 16-bit value at a fixed
byte offset (consistent with the offset already recorded in the
ledger); a default-AP-state flag; the module firmware version; the
Wi-Fi module firmware version; the WLAN access mode; and, in default AP
state only, scanned SSID details. The documented client connection flow
is: listen for the broadcast, take the module address from the datagram
source and the TCP port from the packet, then connect.

**Connection greeting.** Once a valid TCP connection is opened, the
module responds with `*HELLO*` — the greeting is vendor-documented, not
merely implementation lore (corroborates ledger A14 at specification
level).

**The client-traffic requirement (the headline).** Quoting the two
load-bearing fragments, which are short enough to quote exactly:

> "Provided the client issues commands to the N-BW2 the TCP connection
> will remain open. If no response from the client that initiates the
> connection is received within the TCP timeout time (T_TCPOUT), the
> N-BW2 will terminate the connection and perform a reboot."

The accompanying connection flow chart is explicit about the
consequence: no TCP packet received from the client within the timeout
leads to DISCONNECT and then **REBOOT N-BW2** — the module reboots
itself.

**T_TCPOUT is configurable.** T_TCPOUT is the `TNRX` setting in the
module's credentialed Wi-Fi configuration channel: "The TCP timeout
time … Range = 1 to 60 minutes", **default 5 minutes**. The vendor test
application labels it "No TCP message timeout time (mins)". Changing it
requires the module's default password over the configuration channel —
noted for completeness only; SmartLinq neither uses nor proposes using
that channel.

**Status streaming.** Documented directly:

> "The N-BW2 continually transmits the state of the Networker system at
> one second intervals."

There is **no status-request command anywhere in the document**;
streaming is unsolicited. This gives ledger item A1's observed
once-per-second cadence a documented basis (a later approved ledger
update may record that; none is made here).

**Client buffer guidance.** The document instructs clients to allow for
TCP packets of 2080 bytes minimum.

**What the document does not say.** No statement about single- versus
multi-client behaviour. No mention of a daily self-reboot (the upstream
Homebridge troubleshooting claim has no support in this document). The
documented reboot causes are: T_TCPOUT expiry, saving configuration
settings, and the credentialed boot command (referenced here only; it
remains quoted, and forbidden, in `AGENT_SCOPE.md`).

**A wording gap, recorded without resolution.** The prose says the
connection stays open "provided the client issues commands"; the flow
chart's timeout test is "no TCP packet received from client". Whether
an arbitrary client TCP packet resets the timer, or only a well-formed
command does, is not defined. This matters for any future
session-maintenance design and is carried as an open ambiguity
(section 10).

**Mapping to SmartLinq field evidence — a strong inference, not a
proven field conclusion.** SmartLinq's client transmits nothing, so
under the documented mechanism T_TCPOUT (default 5 minutes) would
expire on every session, after which the module terminates the
connection and reboots. That would coherently explain, on the one
studied installation:

- the stream stopping after roughly five minutes on every passive
  session (A2's observed cutoff ≈ the documented default timeout);
- the client-side view of a retained connection during the silence (a
  peer that is rebooting cannot complete an orderly close; a half-open
  socket is exactly what the ledger already refuses to exclude);
- recovery succeeding on the first reconnect roughly ten seconds after
  the recycle (consistent with a module reboot completing);
- the historical refused-connection and delayed-listener episodes (a
  rebooting module's listener is briefly absent).

The correspondence is close, but the document says "terminate the
connection" while the field observation is silence with a retained
client-side socket; the identification of the observed cutoff with the
documented mechanism is therefore recorded as a **strong inference**,
suitable for a later approved ledger update as basis text, not as a
validated protocol fact and not as a change to any ledger status in
this commit.

**Session-maintenance verdict.** The document makes the *requirement*
explicit — a client that wants a persistent session must send traffic
within T_TCPOUT — but defines **no dedicated keepalive or idle
message** anywhere in its 48 pages. Neither upstream idle form (the
bare sequence header once per minute; the header plus a short non-JSON
two-character ASCII token on a roughly ten-second send-idle cadence) is
documented, endorsed, or mentioned. Both upstreams transmitting inside
the documented window is evidence that their forms have worked on the
installations they were used against — **it validates nothing for
SmartLinq**, and no idle form is validated by this review.

## 5. Message Framing and Sequence Semantics

**Command framing (documented).** A Networker System Access command is
the prefix `N`, a sequence number, and a **single JSON object**: one
group-1 tag (`SYST`, `HGOM`, `CGOM`, or `ECOM`), one group-2 tag, and
one **or more** field/value pairs. Multi-field commands are documented
(the upstream implementations only ever send one field per command).

**Status framing (implied only).** The document states which groups are
"sent by the N-BW2 as part of the status information reported" but
never gives an explicit grammar for a status frame. The
array-of-single-key-objects wire shape, inter-frame behaviour, empty
frames, and malformed-input handling that SmartLinq's parser deals with
are **not documented**; SmartLinq's framing assumptions remain grounded
in its own field evidence and upstream observation, unchanged by this
review.

**Sequence numbering (documented).** Before issuing a command the
client should read the current sequence number from the status stream,
increment it — **"if 255, wrap around to 0"** — and use that value in
the command. The module then uses that sequence number in the next
status packet it issues; that echo **is** the documented
acknowledgement that the command was received. The documented client
guidance treats five seconds without the echo as "not updated after
command issued". No retry count is documented.

Consequences worth recording:

- **Sequence zero is a valid outgoing value in the documented scheme.**
  Homebridge deliberately skips zero; pyrinnaitouch's modulo-255
  arithmetic also deviates from the documented wrap-at-255 rule. The
  ledger row stating that zero is skipped for outgoing frames describes
  upstream implementation behaviour, not this document (a later
  approved ledger update may annotate that; none is made here).
- **A passive client sees a constant sequence number.** The status
  sequence changes when a command updates it; with no client commands
  it has no documented reason to change. This matches SmartLinq's
  passive observation that inbound sequence values are stable per
  session and must never be used for freshness or ordering.
- The acknowledgement models compared: pyrinnaitouch's numeric
  received-sequence acknowledgement is essentially the documented
  mechanism (including its 5-second window); Homebridge's
  content-verification (wait for the status to reflect the requested
  values) is stricter than documented. SmartLinq's Phase 2 principle of
  confirming by observed status is a design choice layered above the
  documented mechanism; nothing here forces a winner.

**A formatting ambiguity.** The command format table renders the
sequence as `###`, and the vendor test application displays three-digit
sequence values, while every field observation and all three reviewed
implementations use six-digit zero-padded sequence headers on the wire.
The document is read as illustrative rather than byte-exact here; the
discrepancy is carried in section 10 rather than resolved.

## 6. Status / Read Model Semantics

**Corroboration.** The document's field tables corroborate the
committed ledger map in every overlapping particular: the group
hierarchy; the `MD` value map including `R` (reverse cycle) and `N`
(none); the `ST` operating-state values with the previously unconfirmed
detail that PIN entry is the explicit value `Y`; the fault fields
(`AV`, `GP`, `UT`, `TP`, `CD`) — all read-only, with `UT` documented as
a unit identification in the range 01–15; measured temperature `MT` as
"(x10)" with "999 indicates undefined"; heat/cool setpoints 00–30 with
**"< 8 = OFF" documented verbatim**; and the evaporative comfort
set-point documented as 19–34 under automatic operation (ledger A8's
comfort-level reading is now documented, though its behavioural
semantics on real hardware remain unvalidated).

**Group presence.** `SYST` "is always sent"; each mode group "is sent …
when [that mode] is the current operating mode". This documents the
mode-group-presence behaviour pyrinnaitouch derives its mode from, and
equally documents `OSS.MD` as the declared mode field SmartLinq and
Homebridge read — the two derivations should agree on documented
behaviour, and neither is declared wrong by this review.

**Read/write access flags.** The tables mark every field R or W. The
notable facts:

- **`OSS.MD` is the only writable field in the entire `SYST` group.**
- **`OSS.ST` is marked read-only** — directly relevant to the
  time-setting conflict in section 7.
- `ZUO.UE` (common zone user-enable, heat/cool) is **read-only**, while
  `ZAO`–`ZDO` `UE` are writable.
- The evaporative `GSS` `Z?AE` fields (all five zones) are marked
  **writable** — resolving a Commit 19 ambiguity in favour of the
  pyrinnaitouch write path being documented behaviour.

**Newly documented fields not yet in the ledger's map** (all read-only
unless noted): `SYST.CFG` — `DF` (dual fuel control allowed), `CF`
(clock display format), `VR`/`CV` (module and Wi-Fi firmware versions),
`CC` (certificate checksum), `NC` (N-C7-based system); `SYST.AVM` —
`RA`/`RH`/`RC` (reverse-cycle air-conditioning/heating/cooling
availability); `SYST.OSS` — `RG` (registered with the master
networker); heat/cool mode `CFG` — `CF` (circulation fan available),
`PS` (pre-sleep period enabled), `DG` (schedule day grouping);
multi-set-point `ZXS` — `ID` (information defined ready for use);
evaporative `CFG` — `TP` (display temperature); evaporative `GSS` —
`SN` (service notification) and `MT` (added in Issue 1.3). Between
them, these account for **every previously unexplained key** in the
stale upstream test fixture recorded by Commit 19.

**The document is not exhaustive.** Its own screenshots show `SYST.OSS`
keys (`IP`, `BP`, `DE`, `DU`) that appear in no table in the document.
SmartLinq's practice of retaining unknown fields raw and treating them
as diagnostic-only is exactly right for this interface and is
unchanged.

**A documented-versus-observed nuance for A13.** The single-set-point
tables document `ZUO`/`ZUS` (common zone) groups; the multi-set-point
tables document only `ZXO`/`ZXS` for zones A–D. SmartLinq's real
multi-set-point installation has been observed emitting a `ZUO` group —
field behaviour beyond the tables, consistent with the non-exhaustive
framing above. Ledger A13 is unchanged; the nuance is recorded for a
later approved update.

**Mnemonic scoping caution, reinforced.** `TP` now demonstrably means
three different things by path (fault severity in `FLT`; time period in
the schedule-programming groups; display-temperature flag in the
evaporative `CFG`), and `CF` two (clock format in `SYST.CFG`;
circulation fan in mode-group `CFG`/`OOP`). Any future SmartLinq
mapping must remain keyed on the full group/subgroup path, as the
current model already is.

**Risk framing (unchanged from Commit 19).** Read-only model expansion
stays the categorically lower-risk lane: the fields above arrive in the
stream the integration already receives. They feed the passive semantic
mapping plan (`passive_semantic_mapping_plan.md`); entities and ledger
updates still require separately approved evidence.

## 7. Command / Write Model Semantics

Boundary first: this section maps **documented write surface**, as
evidence for future planning only. It is not approval to implement
controls, not command validation, and no command is inferred to be safe
for SmartLinq.

| Category | Documented status | Notes |
|---|---|---|
| Session maintenance | **Absent as a message; required as behaviour** | Traffic within T_TCPOUT or disconnect + module reboot; no idle form defined (section 4) |
| Status request / refresh | **Absent** | Continuous one-second streaming documented instead |
| Operating mode change | **Documented clearly** — `SYST.OSS.MD` (W) | Values H/E/C/R/N; `R` and `N` are documented write values no upstream exercises; the document notes mode switches are deferred while schedule setup is open |
| Power on / off | **Documented clearly** — mode `OOP.ST` (W: F/N/Z); evap `GSO.SW` (W: F/N) | Matches both upstreams |
| Fan-only / circulation fan | **Documented clearly** — `OOP.ST` = Z; plus `OOP.CF` (W) "circulation fan on" | `OOP.CF` (keep circulation fan on between heating cycles) is a documented write **no reviewed upstream uses** |
| Fan speed | **Documented clearly** — `OOP.FL` / evap `GSO.FL` (W: 01–16) | Matches both upstreams |
| Setpoint / comfort | **Documented** — `GSO.SP` / `ZXO.SP` 00–30, "< 8 = OFF"; evap `GSO.SP` 19–34 | Honest caveat: the R/W marker on the `SP` table rows was not visually resolvable at render resolution; the document's own worked examples write `SP`, so writability is certain even though the table cell is not |
| Zone enable / disable | **Documented** — `ZAO`–`ZDO` `UE` (W); **`ZUO.UE` is R**; evap `GSO` zone-user-enable fields (W, all five zones) | The common zone is not user-writable in heat/cool — a documented restriction neither upstream surfaces |
| Zone off idiom (multi-set-point) | **Documented** — setpoint below 8 is OFF | The idiom both upstreams use is vendor-documented |
| Control mode (schedule/manual) | **Documented clearly** — `GSO.OP` / `ZXO.OP` (W: A/M) | `A` is documented as "Schedule" — the upstream Auto-equals-schedule reading is confirmed |
| Schedule override / advance | **Documented clearly** — `GSO.AO` / `ZXO.AO` (W: N/A/O) | The previously mysterious `O` value is documented ("Operation"); the pyrinnaitouch zone advance-cancel template defect noted in Commit 19 stands as an implementation issue, not a documentation one |
| Schedule programming | **Documented clearly and extensively** — `APS` (system schedule setup) and `APZ` (zone schedule setup) groups, write-flagged, with day/weekday grouping, period, time, setpoint, and per-zone fields; evaporative `PSU` (programmed switch on/off) with switch-on/switch-off times, enables, and per-zone enables | **No reviewed upstream implements any of this**; large documented write surface, far beyond current SmartLinq scope |
| Clock / time setting | **Absent / conflicting** | The `STM` subgroup used by both upstreams appears **nowhere** in the document, and `OSS.ST` — which pyrinnaitouch writes to enter clock-setting mode — is marked **read-only**. The upstream time-setting path is undocumented behaviour that conflicts with the documented access flags |
| Module reboot / reset | **Documented** — in the credentialed Wi-Fi configuration channel (referenced only; the command remains quoted, and forbidden, in `AGENT_SCOPE.md`), plus automatic reboot on T_TCPOUT expiry and after configuration save | SmartLinq's prohibition is unchanged |
| Wi-Fi configuration channel | **Documented** — credentialed get/set of SSID, pass-phrase, join mode, and `TNRX`, with save/boot | Entirely out of SmartLinq scope; recorded because `TNRX` defines T_TCPOUT |

## 8. A11 and Gate E Relevance

The specific questions, answered conservatively:

1. **Does the document describe a dedicated idle/session-maintenance
   message?** No. No such message is defined anywhere in it.
2. **Does it describe that message's purpose?** Not applicable — the
   *requirement's* purpose is explicit (keep the connection open;
   absence of client traffic leads to disconnect and module reboot),
   but there is no defined message to attach a purpose to.
3. **Does it define a required cadence?** At mechanism level, yes:
   client traffic must arrive within T_TCPOUT — default 5 minutes,
   configurable 1–60 minutes. No message-level cadence exists because
   no message is defined.
4. **Does it define whether such traffic is safe / expected /
   optional?** Client traffic is *expected* for a persistent session.
   Nothing states that any particular frame — payload-less header,
   header plus token, or anything else — is side-effect-free.
5. **Does it resolve the Homebridge vs pyrinnaitouch difference?**
   Partially. It does not arbitrate their idle forms (neither is
   documented). It does side with the sequence-echo acknowledgement
   model and the wrap-to-zero sequence rule, where each upstream
   deviates differently. No winner is forced on the undocumented parts.
6. **Does it explain the observed five-minute stream silence?** At
   mechanism level, plausibly yes: T_TCPOUT's default equals the
   observed cutoff, and the documented consequence (terminate plus
   module reboot) is consistent with every observed post-cutoff
   behaviour. This mapping is recorded as a **strong inference**, not a
   proven field conclusion (section 4).
7. **Does it justify changing A11 from Unknown?** **No.** A11 asserts
   that a specific idle keepalive form is side-effect-free and
   sufficient. The document names no form, so no form gains validation.
   **A11 remains Unknown.** What the document does provide — the
   authoritative T_TCPOUT mechanism — belongs in a later, separately
   approved ledger update as basis/context text, not as a status change
   made by this review.
8. **Does it satisfy a Gate E prerequisite?** This review **completes
   the document-reading input** of keepalive gate condition (1) —
   "review of readable authoritative N-BW2 API documentation" — in the
   sense that the reading now exists. **Whether condition (1) is
   thereby satisfied is a maintainer decision, not a consequence of
   this document; and conditions (2) (a separately approved controlled
   experiment) and (3) (explicit user approval of the resulting design)
   are untouched. Gate E is not advanced by this review.**

## 9. Comparison Against Upstream Implementations

| Aspect | PDF (documented) | SmartLinq field evidence | Homebridge v3.4.18 | pyrinnaitouch 0.13.4b1 | Conclusion / uncertainty |
|---|---|---|---|---|---|
| Idle requirement | client traffic within T_TCPOUT, else disconnect + module reboot | never transmits; stream stops ~5 min; recycle recovers | sends bare header 1/min | sends header+token past ~10 s send-idle | requirement documented; **no form documented or validated**; A11 Unknown |
| T_TCPOUT | `TNRX`, default 5 min, range 1–60 min, configurable | observed cutoff ≈ 5 min | assumes 5-min behaviour (docs) | assumes 5-min behaviour (code comments) | default matches observation; configurability untested locally |
| Module reboot on timeout | documented (terminate + reboot) | silence with client-side socket retained; refused/delayed-listener episodes | claims module "disconnects" | reconnects on 30 s no-data | documented mechanism ↔ observations = **strong inference**, unproven |
| Status streaming | one-second continual transmission | ~1 frame/s observed (A1) | relies on push | relies on push | agreement; documented basis for A1 (ledger update later, if approved) |
| Greeting | `*HELLO*` documented after connect | observed (A14) | ignores it | consumes it; duplicate = suspected reset | agreement; duplicate-greeting semantics still unvalidated |
| Status request | none exists | n/a (passive) | none | none | agreement everywhere |
| Sequence wrap | increment; **255 wraps to 0** | inbound stable per session; wrap unobserved | skips 0 (1–254) | mod 255 (0–254), reset 1 per connect | **both implementations deviate from the documented rule**; module tolerance of each variant unknown |
| Sequence digits | format table shows `###`; app displays 3 digits | six-digit zero-padded observed | six-digit | six-digit | document read as illustrative; wire reality six-digit; unresolved formally |
| Acknowledgement | module echoes command sequence in next status; 5 s client guidance | n/a (no commands sent) | status-content check, 10 s, 3 retries | numeric echo ≥ sent, 5 s | pyrinnaitouch ≈ documented; Homebridge stricter; no winner forced |
| Passive sequence behaviour | changes only via commands (implied) | stable per session, non-monotonic | n/a | n/a | documented mechanism explains the observation |
| UDP role | documented onboarding path (address + port from broadcast, every second) | not used (parked) | discovery when unconfigured | listen-only readiness gate | discovery **stays parked**; both upstream roles are consistent with the documented broadcast |
| `OSS.ST` writability | **read-only** | not written (passive) | write exists in API, uncalled | **writes** ST to enter clock mode | documented conflict with pyrinnaitouch's path |
| `STM` group | **absent from the document** | observed in repo docs as upstream-derived | writes DY/TM/SV (uncalled) | writes DY/TM/SV (time service) | upstream time-setting is undocumented behaviour |
| Common zone (`ZUO`) | documented for single-set-point; absent from multi-set-point tables; `UE` read-only | `ZUO` observed on a real multi-set-point system (A13) | reads `ZUS`/`ZUIS`; no `ZUO` writes | reads; no `ZUO` writes | tables not exhaustive; A13 unchanged |
| Evap `GSS.Z?AE` | **writable** | not written | read-only use | writes it | Commit 19 ambiguity resolved toward pyrinnaitouch **as documentation**; still not validated on hardware |
| Zone-off idiom | "< 8 = OFF" documented | not exercised | uses it | uses it | vendor-documented idiom |
| Comfort setpoint | 19–34, auto operation | diagnostic-only (A8) | 19–34 with invert option | 19–34 with invert option | ranges agree; semantics still unvalidated locally |
| Schedule programming (`APS`/`APZ`/`PSU`) | documented, write-flagged | never observed exercised | not implemented | not implemented | documented surface with zero implementation evidence |
| Multi-client behaviour | **silent** | single-client warnings observed anecdotally | documented claim (single client) | in-process guard + comment | remains unvalidated; the document neither confirms nor denies |
| Daily self-reboot | **not mentioned** | one delayed-readiness episode | troubleshooting claim + boot workaround | no such code | upstream claim unsupported by the document; unresolved |

## 10. Open Ambiguities

Recorded without resolution:

1. **What resets T_TCPOUT** — "issues commands" (prose) versus "no TCP
   packet received from client" (flow chart). Whether a payload-less
   frame, a non-command byte, or only a well-formed command qualifies
   is undefined. This is the crux any future Gate E planning must
   design an experiment around.
2. **No documented idle form** — both upstream forms remain
   undocumented inventions; nothing here validates either.
3. **Sequence digit count** — documented `###` versus observed
   six-digit headers.
4. **Sequence zero in practice** — documented as valid on wrap; both
   implementations avoid or deviate; module behaviour on receiving each
   variant is unobserved.
5. **Status-frame grammar** — the array shape, empty frames,
   concatenation, and malformed-input behaviour are undocumented;
   SmartLinq's parser remains grounded in field evidence.
6. **Fields outside the tables** — screenshot-only `OSS` keys (`IP`,
   `BP`, `DE`, `DU`) and the common-zone group on multi-set-point
   systems; the document is authoritative but not exhaustive.
7. **The terminate-versus-observed-silence mapping** — strong
   inference, deliberately not promoted to fact (section 4).
8. **`SP` access marker legibility** — the one table cell that could
   not be read with certainty; writability established from examples.
9. **Multi-client behaviour** — no statement in the document; ledger
   caution stands.
10. **Daily self-reboot** — claimed upstream, absent from the document.
11. **Reverse cycle** — `MD` documents `R` as a value, but no
    reverse-cycle mode group is documented anywhere; reverse-cycle
    systems remain unmodelled in every source.

## 11. Recommended Next Milestones

Documentation and planning only; each requires its own approval, and
none is started by this document:

1. **A separately approved ledger-update commit**, if and when you
   choose: record the documented T_TCPOUT mechanism (and the
   one-second streaming statement) as basis/context for A1/A2, annotate
   the sequence-zero row as implementation-specific, and reconsider
   A11's basis text — **with A11 remaining Unknown** unless that later
   review explicitly and separately concludes otherwise.
2. **Passive semantic mapping** (`passive_semantic_mapping_plan.md`)
   proceeds unchanged as the low-risk evidence path; this review adds
   candidate fields to watch, nothing more.
3. **Read-only entity expansion** stays gated on mapping evidence, per
   Commit 19's register.
4. **A Gate E planning document** (paper only) is now a reasonable next
   research milestone if you judge gate condition (1)'s reading input
   satisfied: it would design — not run — the controlled experiment
   condition (2) requires, centred on ambiguity 1 above, with abort
   criteria and rollback. Producing it grants no traffic.
5. **Discovery remains parked.** The documented every-second broadcast
   strengthens the case for the listen-only readiness-gate variant
   *whenever discovery is deliberately unparked*, and not before.

Not recommended, explicitly: implementing any keepalive now;
implementing any command now; adding climate or control entities now;
running any live experiment now; changing any release or tag.

## 12. Explicit Non-Goals

This document, and the commit that introduces it:

- is a **PDF/document review only** — no other evidence class was
  touched, and the PDF was read from the pinned local reference
  checkout;
- **sent no live traffic** — no TCP, no UDP, no discovery, no packet
  capture, no connection to any module;
- **implemented nothing** — no integration code, tests, entities,
  configuration, or tooling changed;
- **validated no command** — no outbound byte of any kind is
  established as safe, required, or approved by this review;
- **makes no automatic A11 change** — **A11 remains Unknown** unless a
  later, separately approved review changes it, and no other ledger
  entry changes here either;
- **does not advance Gate E** — it completes the reading input of gate
  condition (1) at most; satisfaction of that condition is a
  maintainer decision, and conditions (2) and (3) are untouched;
- **makes no universal N-BW2 compatibility claim** — the document is
  one issue of one vendor specification, and all local field evidence
  remains a single installation;
- reproduces **no credentials, no default-password material, no
  addresses, no serial numbers, and no large quotations** from the
  document, and references — never re-quotes — the credentialed reboot
  command.
