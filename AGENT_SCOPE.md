# Home Assistant Rinnai Touch Integration

## Objective

Build a high-quality, local-only Home Assistant custom integration for Rinnai Touch and Brivis Touch WiFi HVAC modules.

The integration must communicate directly with the local WiFi module using its TCP protocol. It must not require a Rinnai cloud account, Homebridge, MQTT, Node-RED, or any external service.

The intended outcome is an open-source custom integration suitable for eventual HACS publication.

## Workspace Layout

The Home Assistant project is located in:

```text
../ha-rinnai-touch
```

The upstream Homebridge project is available as a separate, read-only reference repository:

```text
../Rinnai-touch-reference/upstream-homebridge-rinnai-touch-platform
```

Do not copy the upstream repository into this project.

## Upstream Reference

Use the upstream Homebridge project to understand:

- Local TCP transport behaviour
- UDP discovery behaviour
- Message framing
- Status payload structure
- Capability detection
- Command construction
- Supported Rinnai and Brivis variants

Do not mechanically translate JavaScript into Python. Reimplement the protocol cleanly using Python async patterns and Home Assistant conventions.

Maintain Apache-2.0 attribution in `NOTICE` and project documentation.

## Safety Rules

1. Do not connect to, scan, reboot, send commands to, or otherwise interact with a live Rinnai Touch module unless explicitly approved by the user.
2. Treat all HVAC commands as safety-sensitive.
3. Capability discovery must be read-only.
4. Never switch HVAC modes, change power state, alter zones, modify schedules, change fan state, or operate a pump just to determine hardware capabilities.
5. Do not enable control entities until read-only communication has been tested and approved.
6. Do not hard-code IP addresses, room names, zones, firmware values, or assumptions from one example installation.
7. Prefer clear diagnostics and graceful failure over aggressive retry behaviour.
8. Close the TCP socket gracefully on Home Assistant stop, integration unload, config-entry reload, and config-flow validation completion. The module is reported to mishandle abrupt closes and rapid reconnects.
9. The module reboot command `CS<DVPW>{wpa-key}<BOOT>\r` is known from the upstream reference but forbidden. Do not implement, expose, or recommend it. Any future consideration requires separate credential handling, an explicit safety review, and a dedicated design decision.
10. The only write that could ever be permitted in Phase 1 is the transport keepalive defined in the Transport Keepalive Policy. No keepalive form is currently approved; the policy's gate conditions apply in full.

## Core Principles

- Local-only operation
- No cloud dependency
- Manual IP configuration first
- Optional discovery later
- Capability-based entity creation
- Robust TCP stream handling
- One shared client connection per physical module
- Clear availability behaviour
- Safe command serialisation
- HACS-ready project structure
- Testable protocol layer independent from Home Assistant entities

## Architecture References

- `docs/adr/0001-transport-source-boundary.md` — the transport/source
  boundary and the transport-neutral SmartLinq semantic contract. The N-BW2
  TCP client is a supported legacy transport adapter beneath that boundary,
  not the SmartLinq HVAC product core.
- `docs/adr/0002-nbw2-passive-stale-session-recycle.md` — the passive
  stale-session recycle design for the N-BW2 transport adapter:
  adapter-specific recovery that transmits nothing, with parameter values
  deferred to a separately approved implementation review.
- `docs/networker_evidence.md` — the Rinnai / Brivis Networker bus evidence
  register (five evidence labels plus source classes). Networker bus facts
  must not enter integration code, entities, or configuration without
  separately approved scope.
- `docs/research/community_brivis_networker_reverse_engineering_review.md` —
  read-only review of community Brivis Networker reverse-engineering
  evidence, scoped to studied legacy controller-family installations.
  Touch-generation and N-BW2 bus behaviour remain Unknown; the review
  grants no new operational permissions of any kind.

## Home Assistant and HomeKit Boundary

The integration is Home Assistant-native only. It must not include:

- HomeKit pairing logic
- HAP transport
- HomeKit accessory definitions
- HomeKit-specific dependencies
- Any direct Apple Home integration code

Apple Home exposure happens later through the standard Home Assistant HomeKit Bridge, configured by the user.

The integration's responsibilities toward HomeKit are limited to:

- Clean HA-native entity semantics
- Stable unique IDs
- Predictable entity names
- Documentation about recommended HomeKit Bridge exposure

See `docs/entity_model.md` for the full entity model and HomeKit Bridge guidance.

## Known Protocol Details

### UDP Discovery

Observed discovery behaviour:

```text
UDP listener port: 50000
Module prefix: Rinnai_NBW2_Module
TCP port stored in UDP response at byte offset 32
```

Manual host and TCP port setup must work even when UDP discovery is unavailable.

### TCP Transport

Observed default TCP port:

```text
27847
```

The module uses a persistent TCP connection.

Additional transport behaviour reported by the upstream reference:

- The module begins sending status frames unsolicited after TCP connect. No request is required to receive status.
- The module may permit only one active local TCP client at a time. Concurrent use by Homebridge, a probe tool, another integration, or the TouchApp's local connection may cause connection conflicts. Behaviour may vary by module firmware and remains subject to local validation. Setup and troubleshooting documentation must warn users about this prominently.
- The module is reported to drop connections after roughly five minutes without receiving any bytes. Passive captures and field sessions on one installation instead observed the stream stopping after roughly five minutes with the TCP connection retained from the client side (a client-side view; a half-open connection is not excluded) — see `docs/protocol_assumptions.md`, ledger items A2 and A15.
- The module is reported to enter a refused-connection state if a socket is closed abruptly or reopened too quickly. Graceful socket closure on Home Assistant stop, integration unload, config-entry reload, and config-flow validation completion is mandatory.

Incoming messages have the observed shape:

```text
N000123[{"SYST": {...}}, {"HGOM": {...}}]
```

Where:

- `N` is the message prefix.
- The next six digits are a sequence number.
- The payload is a JSON array.
- Multiple JSON objects may be included in one status payload.
- Each object represents a top-level status group.

Do not assume a single TCP read equals one complete message.

The parser must correctly handle:

- Partial frames
- Multiple complete frames in one read
- A complete frame plus a partial next frame
- Invalid JSON
- Repeated payloads
- Unexpected bytes
- Disconnects and reconnects

### Sequence Numbers

- Outgoing sequence numbers are derived from the latest valid received sequence.
- Outgoing sequence increments modulo 255.
- Sequence zero is skipped for outgoing frames.
- Received sequence zero is valid and must be accepted.
- Sequence values are zero-padded to six digits.

### Status Merge and Retention Semantics

- A status payload is a JSON array of single-key objects. Each received top-level group replaces the previously stored copy of that group. Nested fields are not deep-merged.
- Mode-group data is retained as last-known state. Absence of a mode group in a new frame does not mean the feature is unavailable or inactive.
- Entities and availability must use timestamps, the active operating mode, and observed capabilities, not group absence alone.
- Observed zones and mode capabilities are accumulated conservatively across valid status frames. A zone is not removed merely because its mode group is absent from a later frame. Zone removal requires explicit validated evidence or user-driven reconfiguration.

### Transport Keepalive Policy

The upstream reference reports the module disconnects idle TCP clients after about five minutes; this project's passive captures observed a silence condition with the TCP connection retained (see `docs/protocol_assumptions.md`, ledger item A2). External implementations address idle sessions with differing idle-traffic forms and cadences (one sends a bare sequence-number header roughly every 60 seconds; another sends a short non-JSON idle token appended to a sequence header at a much shorter cadence). These are behavioural evidence only.

**No keepalive form is approved.** Ledger item A11 remains Unknown. Enabling any transport keepalive requires all of:

1. review of readable authoritative N-BW2 API documentation;
2. a separately approved controlled experiment;
3. explicit user approval of the resulting design.

If a keepalive is ever approved, it remains bound by all of the following constraints:

- The candidate frame previously scoped for this project is exactly `N` followed by a six-digit sequence number, with no JSON payload.
- The sequence is derived from the latest valid received frame.
- Keepalives are sent no more frequently than every 60 seconds.
- No keepalive is sent until at least one valid status frame has been received on the current connection.
- The keepalive must never include a JSON payload, and must never be a reboot, date/time, mode, power, fan, zone, pump, schedule, or any other state-changing command.
- Keepalives are logged at debug level only.
- This is a transport keepalive, not a generic read-only operation. Describe it as such in code and documentation.

The probe defaults to passive mode and must not send any bytes unless explicitly invoked with a keepalive option. The first real-world probe run must be passive for at least six minutes, with Homebridge stopped and no competing local Rinnai client connected.

### Transport Session Recycle Policy

Passive stale-session recycle is the approved recovery design for the N-BW2 transport adapter (`docs/adr/0002-nbw2-passive-stale-session-recycle.md`): when the adapter's socket is connected but no valid frame has arrived within a bounded read-idle interval, the adapter closes the connection gracefully, reuses its existing reconnect lifecycle, and waits for a new valid frame. It transmits nothing at any point.

Parameter policy: the NBW2 adapter may use a bounded configurable read-idle recycle policy. The selected threshold must exceed normal expected frame spacing and must remain below the freshness threshold during controlled validation. Exact values are field-validation parameters, not protocol facts, and are not recorded in this document, in the ADR, or in the protocol assumptions ledger; any value change requires a separate approved implementation review.

Containment: the recycle is NBW2-adapter-specific and lives in the NBW2 client only. The coordinator and entities remain unaware of it. A future SmartLinq hardware source uses explicit documented heartbeat and data-freshness metadata instead of inheriting NBW2 session quirks. Passive recycle remains the fallback recovery path even if a separately approved outbound session-maintenance experiment later succeeds.

This policy is distinct from the Transport Keepalive Policy: it grants no outbound bytes, no keepalive, and no other transmission, and ledger item A11 remains Unknown. Recycling is not validated, not established as safe indefinitely, and not established as suitable for all modules (ledger item A16); a connected TCP socket never proves a healthy N-BW2 session. The design is documentation-only at this commit: no implementation exists, and implementation requires separate explicit approval.

### Commands

Observed command shape:

```text
N000123{"HGOM":{"ZAO":{"SP":"23"}}}
```

The command sequence should be based on the latest valid received sequence number.

Command success must be determined by observing a later valid status update that confirms the requested values.

The upstream module reboot command is known but forbidden:

```text
CS<DVPW>{wpa-key}<BOOT>\r
```

Do not implement, expose, or recommend it. Any future consideration would require separate credential handling, an explicit safety review, and a dedicated design decision.

## Important Status Groups

### System Configuration

```text
SYST.CFG.MTSP   Multi-setpoint capability
SYST.CFG.TU     Temperature unit
SYST.CFG.ZA-ZD  Zone names
```

### Hardware Availability

```text
SYST.AVM.HG     Heater available
SYST.AVM.CG     Refrigerated/add-on cooling available
SYST.AVM.EC     Evaporative cooling available
```

### Overall Operating State

```text
SYST.OSS.MD     Operating mode
SYST.OSS.ST     Controller operating state
```

### Fault State

```text
SYST.FLT.AV     Fault-active flag
```

Other fault keys may vary by firmware and controller family. Preserve raw fault data in diagnostics. Do not assume every system exposes the same fault structure.

### Mode Groups

```text
HGOM    Heating
CGOM    Refrigerated/add-on cooling
ECOM    Evaporative cooling
```

### Zone Groups

```text
ZAO, ZBO, ZCO, ZDO    Zone output/settings groups
ZAS, ZBS, ZCS, ZDS    Zone status/sensed-value groups
```

Zone `U` (Common) is a first-class protocol zone alongside `A`–`D`. The upstream reference reads sensed values for it (for example `ZUS.MT`) and a zone-installed flag (`ZUIS`) under the active mode's `CFG` subgroup. Zone option groups (`Z?O`) were only observed upstream for zones `A`–`D`; whether a `ZUO` group exists is unvalidated.

Observed or inferred fields include:

```text
OP     Control mode, typically automatic/manual
SP     Setpoint
UE     Zone user enabled
AE     Automatic/active enabled state
MT     Measured temperature, generally tenths of a degree
AO     Schedule override
```

Fields not yet validated across multiple systems must be treated as diagnostic-only until confirmed.

### Capability Discovery Boundary

Zone-installed flags (`Z?IS`) live under the `CFG` subgroup of the currently observed active mode group. Phase 1 capability discovery must be passive and cumulative across received frames. It must never imitate the upstream Homebridge plugin's active discovery approach of changing power state or cycling HVAC modes to enumerate capabilities. That approach is forbidden in all phases without explicit approval.

### Temperature and Value Caveats

- `MT` is reported in tenths of a degree. `MT=999` means no valid temperature reading.
- Some controllers never report temperatures at all. Temperature entities must be conditional and must never substitute zero for missing values.
- Evaporative setpoint values are diagnostic-only until validated with real device data, because they may represent a comfort level (observed upstream range 19–34) rather than a literal temperature.

## Required Architecture

```text
ha-rinnai-touch/
├── custom_components/
│   └── rinnai_touch/
│       ├── __init__.py
│       ├── api.py
│       ├── client.py
│       ├── coordinator.py
│       ├── config_flow.py
│       ├── const.py
│       ├── models.py
│       ├── protocol.py
│       ├── diagnostics.py
│       ├── sensor.py
│       ├── binary_sensor.py
│       ├── climate.py     (Phase 2 only — must not exist in Phase 1)
│       ├── switch.py      (Phase 2 only — must not exist in Phase 1)
│       ├── manifest.json
│       ├── strings.json
│       └── translations/
│           └── en.json
├── tests/
│   ├── fixtures/
│   ├── test_frame_parser.py
│   ├── test_status_model.py
│   ├── test_command_builder.py
│   ├── test_client_reconnect.py
│   └── test_config_flow.py
├── scripts/
│   └── rinnai_probe.py
├── docs/
│   ├── entity_model.md
│   └── protocol_assumptions.md
├── reference_data/
├── README.md
├── LICENSE
├── NOTICE
├── hacs.json
└── pyproject.toml
```

## Connection Requirements

Use separate timing values for:

- TCP connect timeout
- Command acknowledgement timeout
- Stale-status threshold
- Reconnect backoff

Suggested initial defaults:

```text
Connect timeout: 10 seconds
Command acknowledgement timeout: 15 seconds
Stale status threshold: 180 seconds
Reconnect backoff: 2s, 5s, 10s, 30s, then 60s maximum
Keepalive spacing: 60 seconds minimum (see Transport Keepalive Policy)
```

Availability must be based on recent valid status data, not merely the existence of a socket object.

### Config Flow Connection Policy

Any live connection attempt during configuration must be initiated by an explicit user action in the config flow. Saving a configuration entry must not silently test, scan, or reconnect to the module beyond the connection policy approved for the active integration entry.

Home Assistant startup, integration reload, passive discovery, and persistence of configuration must not silently trigger an extra validation connection. A user submitting a setup form is an explicit action; importing configuration or starting Home Assistant is not, and the integration must not unexpectedly connect merely because configuration was imported or Home Assistant started.

## Phase 1: Read-Only Integration

Build this first.

Phase 1 has two operating modes:

- Passive observation mode: no bytes are transmitted.
- Persistent monitored mode: a possible future mode in which a narrowly scoped transport keepalive maintains a stable local session — only if the Transport Keepalive Policy's gate conditions are ever met. No keepalive form is currently approved.

No HVAC state-changing command is permitted in either mode. The keepalive is a tightly scoped transport write, not a generic read-only operation.

Required features:

- Config flow accepting host/IP and optional TCP port
- Persistent TCP client
- Robust rolling frame parser
- Capability detection from status payloads
- Shared Home Assistant coordinator
- Device registry support
- Connection-status diagnostic entity
- Last-valid-status timestamp
- Fault-active binary sensor
- Raw fault diagnostic data
- Current-temperature sensors for available zones
- Zone availability/install indicators
- Diagnostics download with sensitive data redacted
- Unit tests using anonymised protocol fixtures
- Transport keepalive per the Transport Keepalive Policy, only if its gate conditions are ever met (currently parked; no form approved)
- Conservative, cumulative capability and zone discovery
- Config-flow and documentation warnings about the upstream-reported single-local-client limitation

Do not expose command-capable climate or switch entities during this phase.

`climate.py` and `switch.py` do not exist in Phase 1 and must remain absent until explicit Phase 2 approval.

## Phase 2: Controlled Commands

Only begin after Phase 1 has been tested and explicitly approved.

Potential controls:

- Overall HVAC mode
- Main target temperature
- Per-zone target temperatures where confirmed
- Zone enable/disable
- Fan state and fan speed where supported
- Evaporative pump state where supported

Every command must:

1. Use a single serial command queue.
2. Validate current capability and active mode.
3. Avoid commands when current state already matches the request.
4. Send one protocol command.
5. Wait for a confirming status update.
6. Retry only where safe.
7. Return useful Home Assistant errors on unsupported functionality or timeout.
8. Never silently assume a command worked.

## Entity Design

Avoid mirroring Homebridge's accessory model. The full entity inventory, behaviour specification, HomeKit Bridge guidance, and naming strategy live in `docs/entity_model.md`. The binding principles are summarised here.

### Device Model

- One Home Assistant device per physical Rinnai/Brivis WiFi module.
- Child zone devices may be created only where installed zones are confirmed.
- Zone devices use stable protocol letters internally: `u`, `a`, `b`, `c`, `d`.
- Controller-provided zone names are display names only. User renames must not alter entity unique IDs.
- Do not automatically assign Areas. Do not create dashboards automatically.

### Main Climate Entity (Phase 2)

- One main climate entity per module, representing the global physical HVAC mode.
- Global modes may include Off, Heat, Cool, and Fan Only where supported and validated. Evaporative-only systems may map cooling to the global evaporative mode after validation.
- Do not expose HVAC Auto or Heat-Cool range mode unless real hardware provides a validated native automatic changeover capability. Do not reproduce the upstream plugin's simulated Auto behaviour.
- On multi-setpoint systems, the main climate entity may have no global target temperature because targets belong to zones. On single-setpoint systems, a global target temperature may be exposed after validation.
- Current temperature must be conditional and never fabricated.

### Global Mode Semantics for Multi-Zone Systems

The hardware has one physical global HVAC mode. The entity model represents that constraint accurately, using "last explicit mode request wins":

- Setting an installed zone climate to Heat, Cool, or Fan Only switches the whole system to that mode, enables that zone, and then applies that zone's target temperature where applicable.
- Setting a zone to Off disables that zone only. It must not turn off the entire system or other enabled zones.
- Setting the main climate entity to Off turns off the entire HVAC system.
- A zone target-temperature change alone must not infer or alter the global Heat/Cool mode.
- Once a global mode change is confirmed, every enabled zone entity must report the resulting global HVAC mode. A zone must never silently claim it can heat while the plant is globally cooling, or vice versa.

### Zone Entities

- Zone climate entities are created only for installed zones on confirmed multi-setpoint systems. Zone target temperature and current temperature are local; zone mode reflects the global physical mode.
- Single-setpoint systems must not create fake zone climate entities.
- Multi-setpoint systems normally use the zone climate Off state to disable a zone. Do not add duplicate zone-enable switches where they would conflict with a zone climate entity.
- Single-setpoint or evaporative systems may receive dedicated zone-enable switches only where validated hardware fields support them.

### Fan and Evaporative Pump

- The circulation fan should become a separate Home Assistant fan entity where validated, not merely a climate fan mode.
- Evaporative pump control may become a switch only after real-device validation. Pump controls are operationally sensitive and must not be part of the recommended Apple Home exposure set.

### Phase 1 Entity Set

Phase 1 is read-only and contains only validated observational entities: connectivity, fault active, zone temperature sensors where available, operating mode, controller state, last-valid-status timestamp, limited fault detail, zone-installed diagnostics, and client diagnostics such as reconnect count and last disconnect reason.

Raw payloads must be available only in redacted diagnostics downloads, not as normal entity state or attributes.

Enabled by default where supported: connectivity, fault active, zone temperature sensors, operating mode, controller state, last-valid-status timestamp.

Disabled by default: fault-code detail, zone-installed indicators, reconnect counters, frame counters, last disconnect reason, unvalidated field sensors, future schedule/manual/auto diagnostic entities, evaporative comfort-level diagnostics.

### Naming and Unique IDs

- Root identity is the config entry ID.
- Entity unique IDs use `{entry_id}_{stable_protocol_key}` with fixed keys such as `climate_main`, `zone_a_climate`, `zone_a_temperature`, `zone_a_enabled`, `fault_active`, `fan`.
- Never use IP address, hostname, controller zone name, room name, capability state, or current mode in a unique ID.
- Capability changes may add or disable entities but must not re-key existing entities.
- Zone letters are stable internal identities. Zone names are display names only.
- Avoid unique-ID migrations unless a versioned migration is explicitly designed and tested.

### HomeKit Bridge Exposure Summary

- Phase 1: do not recommend exposing this integration to HomeKit Bridge at all.
- Phase 2: recommended exposure and the never-expose list are specified in `docs/entity_model.md`. Diagnostics, protocol counters, fault data, pump controls, and anything based on unvalidated fields are never recommended for Apple Home.

## Probe Tool Specification

`scripts/rinnai_probe.py` is a standalone diagnostic capture tool. It:

- is user-run only; the integration and agents never invoke it
- defaults to passive mode and must not send any bytes unless explicitly invoked with a keepalive option
- writes raw captures only to `reference_data/raw/`, which is ignored by Git
- warns about the upstream-reported single-local-client limitation before connecting
- warns users to stop Homebridge and competing local clients first
- prints a sanitisation/redaction checklist after capture
- never publishes raw captures into Git

The first real-world probe run must be passive for at least six minutes, with Homebridge stopped and no competing local Rinnai client connected, to confirm the module's idle-disconnect behaviour.

## Testing Requirements

Create anonymised fixtures for:

- Heating-only system
- Refrigerated cooling system
- Evaporative cooling system
- Single-setpoint system
- Multi-setpoint system
- Partial TCP frames
- Multiple concatenated frames
- Malformed payloads
- Repeated status payloads
- Stale status
- Connection loss and recovery
- Command acknowledgement
- Unsupported command attempts

## Required Deliverables Before Controls

Before adding live commands, provide:

1. Architecture summary
2. Protocol parsing design
3. List of protocol assumptions
4. List of unknowns requiring additional field samples
5. Test plan
6. Read-only integration implementation
7. Test results
8. Explicit list of commands not yet enabled