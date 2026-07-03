# Protocol Facts and Assumptions Ledger

This document separates what is supported by the upstream reference source from what still requires validation against real hardware. It must be updated whenever a passive probe capture confirms or refutes an entry.

## Provenance

Protocol facts below are derived from reading the upstream Homebridge project:

- `homebridge-rinnai-touch-platform` v3.4.18 (commit `c4ea9e6`), Apache-2.0, by mantorok1 and contributors
- Located locally as a read-only reference at `../Rinnai-touch-reference/upstream-homebridge-rinnai-touch-platform`
- No code is copied from it; this project reimplements the protocol independently in Python (see `NOTICE`)

No live-device captures exist yet. Every fact below, however well supported by upstream source, remains subject to confirmation by passive probe observation.

## Confirmed Upstream Protocol Facts

### UDP discovery

- Bind UDP port 50000 and listen; the module broadcasts datagrams.
- Datagrams from the module begin with the 18 ASCII bytes `Rinnai_NBW2_Module`.
- The TCP port is a big-endian unsigned 16-bit integer at byte offset 32 of the datagram.
- The module's IP address is the datagram's source address.
- Source: `src/rinnai/UdpService.ts`.

### TCP transport

- Default TCP port `27847` when an address is configured manually.
- The module begins sending status frames unsolicited after TCP connect; no request is needed.
- The module appears to permit only one local TCP client at a time. A held connection locks out Homebridge, probe scripts, other integrations, and the TouchApp's local connection (the TouchApp falls back to the Rinnai cloud).
- Upstream reports the module drops connections after roughly five minutes without receiving any bytes.
- Upstream reports the module can enter a refused-connection state if a socket is closed abruptly or reopened too quickly. Graceful closure is mandatory on Home Assistant stop, integration unload, config-entry reload, and config-flow validation completion.
- Upstream reports the module normally reboots itself daily, that a permanently held TCP connection prevents this, and that the module may become unstable after being connected for long periods.
- Sources: `src/rinnai/TcpService.ts`, `src/rinnai/RinnaiSession.ts`, `docs/troubleshooting.md`.

### Framing

- Message shape: `N` + six-digit zero-padded sequence + JSON array of single-key objects, for example `N000123[{"SYST":{...}},{"HGOM":{...}}]`.
- Frames may arrive concatenated in a single TCP read (fixed upstream in v2.5.0). The upstream parser handles this by discarding all but the last frame; this project must instead use a rolling buffer that yields every frame.
- The status array may contain a single element (fixed upstream in v3.0.4), for example only `SYST` when the controller is in a settings mode.
- The module re-sends identical payloads; upstream deduplicates by exact string comparison.
- Sources: `src/models/Message.ts`, `src/rinnai/RinnaiSession.ts`, upstream `CHANGELOG.md`.

### Sequence numbers

- Outgoing sequence numbers are derived from the latest valid received sequence.
- Outgoing sequence increments modulo 255.
- Sequence zero is skipped for outgoing frames (transmitted range 000001–000254).
- Received sequence zero is valid and must be accepted (fixed upstream in v3.0.6).
- Sequence values are zero-padded to six digits.
- Source: `src/rinnai/RinnaiSession.ts` (`getNextSequence`).

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
| `CFG` | `MTSP` (Y/N), `TU` (C/F), `ZA`–`ZD` | Multi-setpoint flag, temperature unit, zone name strings |
| `AVM` | `HG`, `CG`, `EC` (Y/N) | Heater / add-on cooler / evaporative availability |
| `OSS` | `DY`, `TM`, `MD`, `ST` | Day, time, operating mode, controller state |
| `FLT` | `AV` (Y/N), `GP`, `UT`, `TP`, `CD` | Fault active, appliance type, unit, severity, code |
| `STM` | `DY`, `TM`, `SV` | Day/time setting (write side — Phase 2+, not used) |

Observed value maps:

- `OSS.MD`: `H` heating, `C` cooling, `E` evaporative, `R` reverse cycle, `N` none. `R` and `N` map to no mode group upstream.
- `OSS.ST`: `N` normal, `C` clock setting, `P` parameter setting, `U` user setting, otherwise PIN entry.
- `FLT.GP`: `H` heater, `C` add-on cooler, `E` evaporative, `R` reverse cycle, `N` controlling device.
- `FLT.TP`: `M` minor, `B` busy, `L` lockout.
- Fault keys may vary by firmware and controller family; preserve raw fault data in diagnostics.

Mode groups (`HGOM` heating, `CGOM` add-on cooling, `ECOM` evaporative):

| Subgroup | Fields | Meaning |
|---|---|---|
| `CFG` | `Z{U,A–D}IS` (Y/N) | Zone installed, per current mode |
| `OOP` (heat/cool) | `ST` (`N` on / `F` off / `Z` fan-only), `FL` | Power/fan state, fan speed 1–16 |
| `GSO` (evap) | `SW`, `FS`, `PS`, `Z{x}UE`, `Z{x}AE` | Switch, fan, pump, per-zone enables |
| `GSO` (single-setpoint heat/cool) | `OP` (`M`/`A`), `SP`, `AO` (`N`/`A`/`O`) | Control mode, setpoint, schedule override |
| `GSS` | `HC`, `CC` (heat/cool), `BY` (evap), `AT` (single-SP) | Calling for heat/cool, busy, schedule period |
| `Z{A–D}O` | `UE`, `OP`, `SP` (multi-SP), `AO` | Per-zone options |
| `Z{U,A–D}S` | `AE`, `MT`, `AT` | Per-zone sensed values |

Zone and value caveats:

- Zone `U` (Common) is a first-class protocol zone alongside `A`–`D`. Upstream reads `ZUS.MT` and `ZUIS`. A `ZUO` group was not observed upstream and is unvalidated.
- `MT` is tenths of a degree. `MT=999` means no valid temperature reading.
- Some controllers never report temperatures. Temperature entities must be conditional and never substitute zero.
- Heat/cool setpoints are integer °C, observed range 8–30; on multi-setpoint systems a value below 8 acts as zone-off upstream.
- Evaporative `SP` may be a comfort level (observed upstream range 19–34, with a configurable inverted mapping), not a literal temperature. Diagnostic-only until validated.
- Sources: `src/models/Status.ts`, `src/rinnai/RinnaiService.ts`, `src/models/Fault.ts`, `src/accessories/Fan.ts`, upstream `docs/`.

### Command grammar (reference only — no command code before Phase 2 approval)

- Shape: `N` + next sequence + `{"GROUP":{"SUBGROUP":{"FIELD":"VALUE"}}}`.
- Success is confirmed only by a later status frame reflecting the requested values (upstream: 10-second window, up to 3 attempts).
- The upstream module reboot command `CS<DVPW>{wpa-key}<BOOT>\r` is known but **forbidden**: do not implement, expose, or recommend it. Any future consideration requires separate credential handling, an explicit safety review, and a dedicated design decision.
- Upstream's capability discovery actively powers the system on and cycles operating modes (`src/platform.ts`, `findDevices`). That approach is forbidden here in all phases: Phase 1 capability discovery is passive and cumulative only.

## Transport Keepalive Policy

The upstream reference reports the module disconnects idle TCP clients after about five minutes. A narrowly constrained transport keepalive is authorised for the native integration, subject to all of the following:

- The keepalive frame is exactly `N` followed by a six-digit sequence number, with no JSON payload.
- The sequence is derived from the latest valid received frame.
- Keepalives are sent no more frequently than every 60 seconds.
- No keepalive is sent until at least one valid status frame has been received on the current connection.
- The keepalive must never include a JSON payload, and must never be a reboot, date/time, mode, power, fan, zone, pump, schedule, or any other state-changing command.
- Keepalives are logged at debug level only.
- It is described as a transport keepalive, not as a generic read-only operation.

The keepalive becomes Phase 1 integration behaviour only after passive probe validation confirms the module's idle disconnect behaviour. The probe defaults to passive mode and sends no bytes unless explicitly invoked with a keepalive option. The first real-world probe run must be passive for at least six minutes, with Homebridge stopped and no competing local Rinnai client connected.

## Assumptions Requiring Real-World Validation

| ID | Assumption | Basis | Validation method | Status |
|---|---|---|---|---|
| A1 | Status frames arrive on change and/or on a timer; cadence unknown | upstream listens passively | passive probe timing log | Unvalidated |
| A2 | Module drops idle connections at ~5 minutes | upstream troubleshooting doc | first passive probe run ≥ 6 minutes | Unvalidated |
| A3 | Every frame starts with `N`; delimiter bytes between frames (if any) unknown | upstream parser assumptions | hex-level capture | Unvalidated |
| A4 | Received sequence increments per status change; wrap behaviour at 254/255 | upstream send-side arithmetic only | capture analysis across many frames | Unvalidated |
| A5 | Group presence when system off or `MD` in `{N, R}` | upstream mode map | capture with system off/in settings mode | Unvalidated |
| A6 | Zone data shape on the reference system (`Z?IS`, `MT` presence, `999` sentinel, name padding) | upstream field map | first sanitised capture | Unvalidated |
| A7 | `FLT` structure stability across firmware | AGENT_SCOPE warning | fault-state captures; community samples | Unvalidated |
| A8 | Evaporative semantics incl. comfort-level mapping | upstream flags evap untested | community samples | Unvalidated |
| A9 | Multi-controller payload shape | upstream flags untested | community samples | Unvalidated |
| A10 | UDP datagram full layout and broadcast cadence | offset-32 port only documented | passive UDP capture (discovery phase) | Unvalidated |
| A11 | The blank keepalive is side-effect-free and sufficient to hold the connection | upstream sends it every 60 s | probe keepalive mode, only after A2 passive baseline | Unvalidated |
| A12 | `TU` values are only `C`/`F` | upstream default handling | captures; community samples | Unvalidated |
| A13 | Existence/shape of a `ZUO` group | not observed upstream | captures | Unvalidated |

## Known Unknowns

- Reverse-cycle (`MD=R`) systems: no mode group mapping exists upstream; entirely unmodelled.
- Fault code vocabulary and per-firmware variance.
- Behaviour when the controller leaves Normal state mid-session (clock/parameter/PIN modes) — upstream blocks at startup only; this integration must instead surface the state passively.
- Whether the module's daily self-reboot proceeds while a client is connected, and what the disconnect looks like from the client side.
- Interaction between the module's cloud connection (TouchApp remote path) and the local TCP session.

## Update Discipline

When a probe capture validates or refutes an entry: update the Status column, record the capture fixture name (sanitised, under `tests/fixtures/` or `reference_data/anonymised/`), and reflect any behavioural consequence in `AGENT_SCOPE.md` in the same commit.
