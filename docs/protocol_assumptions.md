# Protocol Facts and Assumptions Ledger

This document separates what is supported by the upstream reference source from what still requires validation against real hardware. It must be updated whenever a passive probe capture confirms or refutes an entry.

## Provenance

Protocol facts below are derived from reading the upstream Homebridge project:

- `homebridge-rinnai-touch-platform` v3.4.18 (commit `c4ea9e6`), Apache-2.0, by mantorok1 and contributors
- Located locally as a read-only reference at `../Rinnai-touch-reference/upstream-homebridge-rinnai-touch-platform`
- No code is copied from it; this project reimplements the protocol independently in Python (see `NOTICE`)

Live passive observations now exist (see "Passive Capture Evidence" and "Field Session Evidence" below); all are from one local installation, and no outbound or live command testing has occurred. Every fact below, however well supported by upstream source or vendor documentation, remains subject to confirmation by local observation.

Where an entry cites "external implementations", the behavioural evidence comes from read-only review (4 July 2026) of the upstream Homebridge reference above plus `funtastix/rinnaitouch` and `funtastix/pyrinnaitouch` (v0.13.4b1). No code is copied from any of them; their behaviour is evidence only. The three-source implementation review is recorded in `docs/research/upstream_command_behaviour_review.md`.

Where an entry cites "the API PDF", the source is the vendor document `NBW2API_Iss1.3.pdf` (N-BW2 Networker Bridge (WIFI) Application Programmers Interface, Issue 1.3), bundled in the pinned `pyrinnaitouch` reference checkout and reviewed read-only on 11 July 2026 in `docs/research/nbw2_api_session_semantics_review.md`. The PDF is treated as authoritative for documented behaviour but not exhaustive (its own screenshots show fields absent from its tables), and it validates no local behaviour by itself.

## Upstream-Sourced Protocol Facts

### UDP discovery

- Bind UDP port 50000 and listen; the module broadcasts datagrams.
- Datagrams from the module begin with the 18 ASCII bytes `Rinnai_NBW2_Module`.
- The TCP port is a big-endian unsigned 16-bit integer at byte offset 32 of the datagram.
- The module's IP address is the datagram's source address.
- The API PDF documents the broadcast as a 256-byte packet sent every second, carrying an identification tag, the TCP port, a default-AP-state flag, module and Wi-Fi firmware versions, the WLAN access mode, and (in default AP state) scanned SSID details. Discovery remains parked; nothing here approves implementing it.
- Sources: `src/rinnai/UdpService.ts`; the API PDF (see `docs/research/nbw2_api_session_semantics_review.md`).

### TCP transport

- Default TCP port `27847` when an address is configured manually.
- The module begins sending status frames unsolicited after TCP connect; no request is needed. The API PDF documents this as continual status transmission at one-second intervals, and documents no status-request command.
- The module may permit only one active local TCP client at a time. Concurrent use by Homebridge, a probe tool, another integration, or the TouchApp's local connection may cause connection conflicts. Upstream documentation reports that the TouchApp may still operate via the Rinnai cloud while a local connection is held. Behaviour may vary by module firmware and remains subject to local validation.
- The API PDF documents a configurable TCP timeout, T_TCPOUT (the credentialed `TNRX` configuration setting: default five minutes, range 1–60 minutes — session context, not a status control): if no client traffic is received within it, the module terminates the connection and performs a reboot. Upstream reports of the module dropping connections after roughly five minutes without receiving any bytes are consistent with the documented default. The API PDF defines no dedicated idle/keepalive message (see the Transport Keepalive Policy and ledger item A11).
- Upstream reports the module can enter a refused-connection state if a socket is closed abruptly or reopened too quickly. Graceful closure is mandatory on Home Assistant stop, integration unload, config-entry reload, and config-flow validation completion.
- Upstream reports the module normally reboots itself daily, that a permanently held TCP connection prevents this, and that the module may become unstable after being connected for long periods (the API PDF does not mention a daily self-reboot; this remains an upstream-documentation claim).
- External implementations expect the module to send the short ASCII greeting `*HELLO*` immediately after TCP connect, before any status frame: one consumes it explicitly, the other discards it as pre-frame bytes. The greeting is documented by the API PDF and has been observed on one local installation (ledger item A14). This project's parser already treats any pre-frame bytes as ordinary discardable input, and the transport forensics record the greeting's presence as a boolean.
- Sources: `src/rinnai/TcpService.ts`, `src/rinnai/RinnaiSession.ts`, `docs/troubleshooting.md`; the API PDF (see `docs/research/nbw2_api_session_semantics_review.md`); `*HELLO*` behaviour: the API PDF plus external implementations (see Provenance).

### Framing

- Message shape: `N` + six-digit zero-padded sequence + JSON array of single-key objects, for example `N000123[{"SYST":{...}},{"HGOM":{...}}]`.
- Frames may arrive concatenated in a single TCP read (fixed upstream in v2.5.0). The upstream parser handles this by discarding all but the last frame; this project must instead use a rolling buffer that yields every frame.
- The status array may contain a single element (fixed upstream in v3.0.4), for example only `SYST` when the controller is in a settings mode.
- The module re-sends identical payloads; upstream deduplicates by exact string comparison.
- The API PDF documents the command-direction format only (a header plus a single JSON object carrying one group, one subgroup, and one or more fields); it gives no explicit status-frame grammar, so the array-of-single-key-objects shape, empty frames, and malformed-input behaviour remain grounded in field observation and upstream source.
- Sources: `src/models/Message.ts`, `src/rinnai/RinnaiSession.ts`, upstream `CHANGELOG.md`; the API PDF (see `docs/research/nbw2_api_session_semantics_review.md`).

### Sequence numbers

- Outgoing sequence numbers are derived from the latest valid received sequence.
- The API PDF documents the outgoing rule as increment-with-wrap: after 255, wrap to 0 — sequence zero is a valid outgoing value in the documented scheme.
- Implementations deviate from the documented rule in different ways: Homebridge increments modulo 255 and skips zero (transmitted range 000001–000254); pyrinnaitouch's arithmetic yields 0–254 and resets per connection. This project transmits nothing, so all outgoing-sequence facts are planning evidence only; no outbound behaviour is approved.
- Received sequence zero is valid and must be accepted (fixed upstream in v3.0.6).
- The API PDF documents that the module echoes a command's sequence number in the next status packet (the documented acknowledgement); with no client commands the status sequence has no documented reason to change.
- Sequence values are zero-padded to six digits on the wire as observed locally and as implemented upstream; the API PDF's format illustration is read as illustrative rather than byte-exact here.
- Sources: `src/rinnai/RinnaiSession.ts` (`getNextSequence`); `pyrinnaitouch/pollconnection.py`; the API PDF (see `docs/research/nbw2_api_session_semantics_review.md`).

### Merge and retention semantics

- Each received top-level group (`SYST`, `HGOM`, `CGOM`, `ECOM`) replaces the previously stored copy of that group. Nested fields are not deep-merged.
- Mode-group data is retained as last-known state. Absence of a mode group in a new frame does not mean the feature is unavailable or inactive.
- Entities and availability must use timestamps, the active operating mode, and observed capabilities — not group absence alone.
- Observed zones and mode capabilities are accumulated conservatively across valid status frames. A zone is not removed merely because its mode group is absent from a later frame. Zone removal requires explicit validated evidence or user-driven reconfiguration.
- Source: `src/models/Status.ts` (`update`), plus this project's design decisions.

### Status group map

System-level (`SYST`):

| Subgroup | Fields | Meaning |
|---|---|---|
| `CFG` | `MTSP` (Y/N), `TU` (C/F), `ZA`–`ZD`; the API PDF adds `DF`, `CF`, `VR`, `CV`, `CC`, `NC` | Multi-setpoint flag, temperature unit, zone name strings; dual-fuel flag, clock format, firmware/Wi-Fi versions, certificate checksum, N-C7 flag |
| `AVM` | `HG`, `CG`, `EC` (Y/N); the API PDF adds `RA`, `RH`, `RC` | Heater / add-on cooler / evaporative availability; reverse-cycle availability flags |
| `OSS` | `DY`, `TM`, `MD`, `ST`; the API PDF adds `RG` | Day, time, operating mode, controller state; registered-with-master flag |
| `FLT` | `AV` (Y/N), `GP`, `UT`, `TP`, `CD` | Fault active, appliance type, unit, severity, code |
| `STM` | `DY`, `TM`, `SV` | Day/time setting (write side — Phase 2+, not used; upstream-implementation path, absent from the API PDF, which marks `OSS.ST` read-only) |

Observed value maps:

- `OSS.MD`: `H` heating, `C` cooling, `E` evaporative, `R` reverse cycle, `N` none. `R` and `N` map to no mode group upstream.
- `OSS.ST`: `N` normal, `C` clock setting, `P` parameter setting, `U` user setting, `Y` PIN entry (`Y` documented by the API PDF; upstream treated any other value as PIN entry).
- `FLT.GP`: `H` heater, `C` add-on cooler, `E` evaporative, `R` reverse cycle, `N` controlling device.
- `FLT.TP`: `M` minor, `B` busy, `L` lockout.
- Fault keys may vary by firmware and controller family; preserve raw fault data in diagnostics.

Mode groups (`HGOM` heating, `CGOM` add-on cooling, `ECOM` evaporative):

| Subgroup | Fields | Meaning |
|---|---|---|
| `CFG` | `Z{U,A–D}IS` (Y/N); the API PDF adds `CF`, `PS`, `DG` (heat/cool) and `TP` (evap) | Zone installed, per current mode; circulation-fan availability, pre-sleep enabled, day grouping; evap display-temperature flag |
| `OOP` (heat/cool) | `ST` (`N` on / `F` off / `Z` fan-only), `FL`; the API PDF adds `CF` | Power/fan state, fan speed 1–16; keep-circulation-fan-on (a documented write no reviewed integration uses) |
| `GSO` (evap) | `SW`, `FS`, `PS`, `Z{x}UE` | Switch, fan, pump, per-zone user enables |
| `GSO` (single-setpoint heat/cool) | `OP` (`M`/`A`), `SP`, `AO` (`N`/`A`/`O`) | Control mode, setpoint, schedule override |
| `GSS` | `HC`, `CC` (heat/cool), `BY` (evap), `AT` (single-SP); the API PDF adds `PH`, `GV`, `FS` (heat), `CP` (cool), `AZ`, and for evap `PW`, `PO`, `FO`, `SN`, `MT`, `Z{x}AE` | Calling for heat/cool, busy, schedule period; activity flags, advanced-to period, evap status fields and per-zone auto-enables (`Z{x}AE` sits under `GSS`, corrected from this table's earlier evap-`GSO` placement) |
| `Z{A–D}O` | `UE`, `OP`, `SP` (multi-SP), `AO` | Per-zone options |
| `Z{U,A–D}S` | `AE`, `MT`, `AT`; the API PDF adds `ID` plus per-zone `FS`, `PH`, `GV`/`CP`, `AZ` on multi-setpoint | Per-zone sensed values; info-defined flag and per-zone activity/schedule fields |

The API PDF also documents `APS`/`APZ` (heat/cool schedule programming) and `PSU` (evaporative programmed switch on/off) as write-side groups: documented, not implemented by any reviewed integration, and not validated. The complete vendor-documented field mapping lives in `docs/research/nbw2_api_session_semantics_review.md`; this table stays a concise map, not a duplicate.

Zone and value caveats:

- Zone `U` (Common) is a first-class protocol zone alongside `A`–`D`. Upstream reads `ZUS.MT` and `ZUIS`. The API PDF documents `ZUO`/`ZUS` for single-setpoint systems (with the common-zone user-enable read-only) and omits common-zone groups from its multi-setpoint tables; a `ZUO` group has nonetheless been observed on this project's multi-setpoint reference system (A13).
- `MT` is tenths of a degree. `MT=999` means no valid temperature reading (both documented by the API PDF).
- Some controllers never report temperatures. Temperature entities must be conditional and never substitute zero.
- Heat/cool setpoints are integer °C; the API PDF documents the range as 00–30 with below-8 meaning off, and both upstream implementations use the below-8 zone-off idiom on multi-setpoint systems.
- Evaporative `SP` is documented by the API PDF as a comfort level (19–34, automatic operation), not a literal temperature; upstream implementations apply a configurable inverted mapping. Diagnostic-only until validated on real hardware.
- Sources: `src/models/Status.ts`, `src/rinnai/RinnaiService.ts`, `src/models/Fault.ts`, `src/accessories/Fan.ts`, upstream `docs/`; the API PDF (see `docs/research/nbw2_api_session_semantics_review.md`).

### Command grammar (reference only — no command code before Phase 2 approval)

- Shape: `N` + next sequence + `{"GROUP":{"SUBGROUP":{"FIELD":"VALUE"}}}`.
- Success is confirmed only by a later status frame reflecting the requested values (upstream: 10-second window, up to 3 attempts).
- The API PDF's documented acknowledgement is narrower: the module echoes the command's sequence number in its next status packet, with five seconds suggested before treating a command as not received. Homebridge's content verification is stricter than documented; pyrinnaitouch approximates the documented mechanism. All of this is planning evidence only.
- The API PDF marks `SYST.OSS.MD` as the only writable `SYST` field and `OSS.ST` as read-only, and contains no `STM` subgroup: the upstream day/time-setting path is undocumented behaviour (see `docs/research/nbw2_api_session_semantics_review.md`).
- The upstream module reboot command `CS<DVPW>{wpa-key}<BOOT>\r` is known but **forbidden**: do not implement, expose, or recommend it. Any future consideration requires separate credential handling, an explicit safety review, and a dedicated design decision.
- Upstream's capability discovery actively powers the system on and cycles operating modes (`src/platform.ts`, `findDevices`). That approach is forbidden here in all phases: Phase 1 capability discovery is passive and cumulative only.

## Phase 1 Operating Modes

Phase 1 has two operating modes:

- Passive observation mode: no bytes are transmitted. The passive stale-session recycle design (ADR 0002) stays within passive observation mode: it transmits nothing.
- Persistent monitored mode: a possible future mode in which a narrowly scoped transport keepalive maintains a stable local session — only if the Transport Keepalive Policy's gate conditions are ever met. No keepalive form is currently approved.

No HVAC state-changing command is permitted in either mode. The keepalive is a tightly scoped transport write, not a generic read-only operation.

## Transport Keepalive Policy

The upstream reference reports the module disconnects idle TCP clients after about five minutes; this project's passive captures observed a silence condition with the TCP connection retained (ledger item A2). External implementations address idle sessions with differing idle-traffic forms and cadences (one sends a bare sequence-number header roughly every 60 seconds; another sends a short non-JSON idle token appended to a sequence header at a much shorter cadence). These are behavioural evidence only. Both external implementations also close and reconnect their connection after a bounded no-data interval; this is behavioural evidence only and grants nothing.

**No keepalive form is approved.** Ledger item A11 remains Unknown. Enabling any transport keepalive requires all of: (1) review of readable authoritative N-BW2 API documentation; (2) a separately approved controlled experiment; (3) explicit user approval of the resulting design.

If a keepalive is ever approved, it remains bound by all of the following constraints:

- The candidate frame previously scoped for this project is exactly `N` followed by a six-digit sequence number, with no JSON payload.
- The sequence is derived from the latest valid received frame.
- Keepalives are sent no more frequently than every 60 seconds.
- No keepalive is sent until at least one valid status frame has been received on the current connection.
- The keepalive must never include a JSON payload, and must never be a reboot, date/time, mode, power, fan, zone, pump, schedule, or any other state-changing command.
- Keepalives are logged at debug level only.
- It is described as a transport keepalive, not as a generic read-only operation.

The probe defaults to passive mode and sends no bytes unless explicitly invoked with a keepalive option. The first real-world probe run must be passive for at least six minutes, with Homebridge stopped and no competing local Rinnai client connected.

## Config Flow Connection Policy

Any live connection attempt during configuration must be initiated by an explicit user action in the config flow. Saving a configuration entry must not silently test, scan, or reconnect to the module beyond the connection policy approved for the active integration entry.

Home Assistant startup, integration reload, passive discovery, and persistence of configuration must not silently trigger an extra validation connection. A user submitting a setup form is an explicit action; importing configuration or starting Home Assistant is not, and the integration must not unexpectedly connect merely because configuration was imported or Home Assistant started.

## Passive Capture Evidence (Private)

Two passive probe captures have been taken and are kept private and
untracked per the raw-capture rules. Findings are recorded here without
timestamps, addresses, frame sizes, or sequence values:

- Both captures observed approximately one complete status frame per
  second for about five minutes.
- The module then stopped sending status while retaining the TCP
  connection for at least the remainder of a fifteen-minute passive
  session: the observed cutoff is a silence condition, not a disconnect.
- Inbound sequence values were stable per session and are not a monotonic
  counter; sequence values must never be treated as a freshness or
  ordering source.
- The integration must therefore evaluate freshness from valid-frame
  timestamps, never from socket connectivity (reaffirming the existing
  availability rule).
- No delimiter bytes were observed between frames, and the two captures
  were structurally consistent with each other.
- This evidence motivates a future controlled keepalive experiment, but
  no keepalive payload has been validated, authorised, or enabled by this
  evidence.

Fully synthetic fixtures derived from the observed structure (with every
value replaced) live under `tests/fixtures/` and are generated by
`scripts/sanitise_rinnai_capture.py`, which emits counts and checks only
and refuses anything it cannot safely sanitise.

## Field Session Evidence (Private)

Field sessions of the integration against one real installation
(5 July 2026) are recorded here under the same sanitisation discipline:
no timestamps, addresses, ports, frame sizes, sequence values, or frame
counts.

- Fresh passive sessions repeatedly showed: TCP established → short
  ASCII greeting → first valid status frame → valid status frames
  approximately once per second for about five minutes → valid frames
  stop. Observed twice in independent fresh sessions, consistent with
  the passive probe captures above (local field observation, single
  installation).
- During the silence the TCP connection remained established from the
  client side. This is a client-side observation only: a passive client
  cannot distinguish a quiet peer from a half-open connection, and a
  connected TCP socket is never proof of a healthy N-BW2 session.
- After the 180-second freshness threshold elapsed without a valid
  frame, the integration reported data stale while connection state
  remained connected — the freshness model behaved as designed (local
  field observation).
- Disabling and re-enabling the integration closed and reopened the TCP
  connection and restored a further roughly five-minute stream window.
  Observed twice, with human-paced turnarounds; automated recycle
  cadence is unvalidated (local field observation; see A15 and A16).
- In one observed field episode, the local listener became available
  only after the N-BW2 module was restarted, following a delayed
  readiness period (local field observation, single episode).

This evidence motivates the passive stale-session recycle design
(`docs/adr/0002-nbw2-passive-stale-session-recycle.md`). It validates no
keepalive payload and grants no outbound traffic of any kind.

### Gate D Soak Evidence (10 July 2026)

A single-installation automated soak of the Commit 14B passive stale-session
recycle ran for approximately five days (5–10 July 2026) on the same local
N-BW2 installation described above, with Homebridge disabled throughout and
debug logging enabled. Findings, recorded under the same sanitisation
discipline:

- Of approximately 972 sessions reviewed, approximately 932 were normal
  idle-timeout recycles, each following the same repeating pattern already
  described above: roughly five minutes of active streaming, roughly 150
  seconds of read-idle silence, a graceful recycle, the 10-second
  post-recycle delay floor, and a new session with the greeting and valid
  frames resumed.
- The first-attempt recovery rate after an idle-timeout recycle was
  approximately 99.7% (928 of 931 evaluable recycles). Typical recovery
  from recycle trigger to the next valid frame was on the order of 11
  seconds; the longest observed was on the order of 31 seconds.
- Zero refused-listener sessions and zero frameless idle-timeout sessions
  occurred across the observation window.
- One freshness-stale event occurred, when a single recovery exceeded the
  remaining margin under the 180-second freshness threshold; the freshness
  model reported it correctly and recovery followed automatically.
- A minority of sessions ended for reasons other than idle-timeout:
  clustered reset events, a small number of connect timeouts, and a single
  host-unreachable event. Automatic recovery followed every one of them, no
  refused-listener state resulted, and no progressive degradation trend was
  identified across the window.
- Passive stale-session recycle passed Gate D on this one local installation
  over this observation window (see A15 and A16). This soak validates the
  passive socket-recycle mechanism only: it exercises no outbound
  keepalive, acknowledgement, polling request, command, or other
  session-maintenance traffic, and does not change ledger item A11.

## Assumptions Requiring Real-World Validation

| ID | Assumption | Basis | Validation method | Status |
|---|---|---|---|---|
| A1 | Status frames arrive on change and/or on a timer; cadence unknown | upstream listens passively; the API PDF documents continual status transmission at one-second intervals | passive probe timing log | Evidence recorded — roughly one frame per second while streaming, observed on one installation and documented by the API PDF (see Passive Capture Evidence) |
| A2 | Module stops streaming status after roughly five minutes without inbound bytes; the TCP connection can remain open | upstream troubleshooting doc; passive captures; the API PDF documents T_TCPOUT (default five minutes, configurable 1–60 minutes): absent client traffic within it, the module terminates the connection and performs a reboot | future controlled keepalive experiment (gated) | Revised by evidence — silence repeatedly observed in field sessions with the TCP connection retained from the client side (a client-side view; a half-open connection is not excluded); closing and reopening the connection restored streaming (see A15). Identifying the observed silence with the documented T_TCPOUT termination-and-reboot mechanism is a strong inference, not a proven field fact (see `docs/research/nbw2_api_session_semantics_review.md`) |
| A3 | Every frame starts with `N`; delimiter bytes between frames (if any) unknown | upstream parser assumptions | hex-level capture | Partially validated — frames parse cleanly; no delimiter bytes observed |
| A4 | Received sequence increments per status change; wrap behaviour at 254/255 | upstream send-side arithmetic; the API PDF documents the sequence-echo acknowledgement, which explains per-session stability for a silent client | capture analysis across many frames | Evidence recorded — stable per session, not monotonic; wrap unobserved |
| A5 | Group presence when system off or `MD` in `{N, R}` | upstream mode map; the API PDF states each mode group is sent when that mode is current, and leaves `MD` in `{N, R}` behaviour undocumented | capture with system off/in settings mode | Unvalidated |
| A6 | Zone data shape on the reference system (`Z?IS`, `MT` presence, `999` sentinel, name padding) | upstream field map | first sanitised capture | Partially validated — `Z?IS`, `MT` presence, and sentinel behaviour observed on the reference system; name padding, broader semantics, and cross-firmware behaviour remain unvalidated |
| A7 | `FLT` structure stability across firmware | AGENT_SCOPE warning | fault-state captures; community samples | Unvalidated |
| A8 | Evaporative semantics incl. comfort-level mapping | upstream flags evap untested; the API PDF documents the evaporative set point as a comfort level (19–34, automatic operation) | community samples | Unvalidated |
| A9 | Multi-controller payload shape | upstream flags untested | community samples | Unvalidated |
| A10 | UDP datagram full layout and broadcast cadence | the API PDF documents the full broadcast layout and a one-second cadence; nothing observed locally (discovery parked) | passive UDP capture (discovery phase) | Unvalidated |
| A11 | Any idle keepalive form is side-effect-free and sufficient to hold the connection | external implementations send differing idle traffic (form and cadence differ); the API PDF documents a client-traffic requirement within T_TCPOUT but defines no dedicated idle/keepalive message, so no specific side-effect-free, sufficient form is validated | readable authoritative N-BW2 API review, then a separately approved controlled experiment | Unknown — no form validated, authorised, or enabled |
| A12 | `TU` values are only `C`/`F` | upstream default handling; documented by the API PDF (`C`/`F`) | captures; community samples | Unvalidated |
| A13 | Existence/shape of a `ZUO` group | not observed in upstream implementations; the API PDF documents `ZUO`/`ZUS` for single-setpoint systems and omits common-zone groups from its multi-setpoint tables | captures | Partially validated — `ZUO` observed on the reference system; semantics, shape variation, and cross-firmware behaviour remain unvalidated |
| A14 | The module sends the `*HELLO*` greeting after TCP connect, before status frames | documented by the API PDF; external implementation behavioural evidence plus successful local field sessions | additional sessions and cross-module observation; duplicate-banner or reset semantics remain unvalidated | Partially validated — documented by the API PDF and observed on one local N-BW2 installation after TCP connection and before the first accepted status frame. Cross-module behaviour, firmware variation, and duplicate-banner semantics remain unvalidated |
| A15 | Closing and reopening the TCP connection after stream silence restores streaming | field sessions — one installation, manual human-paced recycles plus automated Gate D soak | additional field soaks on other modules and firmware; cross-network observation | Partially validated — two manual field recycles plus approximately 932 automated idle-timeout recycles over approximately five days on one local N-BW2 module. First-attempt recovery after idle recycle was approximately 99.7%, with zero refused sessions and zero frameless idle-timeout sessions. Cross-module, cross-firmware, cross-network, and long-term behaviour remain unvalidated. |
| A16 | The module tolerates a sustained periodic reconnect cadence without entering a refused state | field sessions — one installation, automated Gate D soak; community reports remain unverified | additional field soaks on other modules; long-term listener-wear observation | Partially validated — one local N-BW2 module tolerated approximately 932 automated idle-timeout recycles over approximately five days without entering a refused-listener state. Long-term listener wear, other firmware versions, other networks, seasonal/system-mode variation, and multi-client behaviour remain unvalidated. |

## Known Unknowns

- Reverse-cycle (`MD=R`) systems: no mode group mapping exists upstream; the API PDF documents `R` as an `MD` value and `RA`/`RH`/`RC` availability flags but no reverse-cycle mode group; entirely unmodelled.
- Fault code vocabulary and per-firmware variance.
- Behaviour when the controller leaves Normal state mid-session (clock/parameter/PIN modes) — upstream blocks at startup only; this integration must instead surface the state passively.
- Whether the module reboots itself daily as upstream documentation claims (the API PDF does not mention it), whether any such reboot proceeds while a client is connected, and what the disconnect looks like from the client side.
- Interaction between the module's cloud connection (TouchApp remote path) and the local TCP session.
- What resets T_TCPOUT: the API PDF's prose says the connection stays open provided the client "issues commands", while its flow chart tests for any client TCP packet; the distinction is undefined and is the central design question for any future, separately approved Gate E planning.

## Update Discipline

When a probe capture validates or refutes an entry: update the Status column, record the capture fixture name (sanitised, under `tests/fixtures/` or `reference_data/anonymised/`), and reflect any behavioural consequence in `AGENT_SCOPE.md` in the same commit.
