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

### Commands

Observed command shape:

```text
N000123{"HGOM":{"ZAO":{"SP":"23"}}}
```

The command sequence should be based on the latest valid received sequence number.

Command success must be determined by observing a later valid status update that confirms the requested values.

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
│       ├── climate.py
│       ├── switch.py
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
```

Availability must be based on recent valid status data, not merely the existence of a socket object.

## Phase 1: Read-Only Integration

Build this first.

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

Do not expose command-capable climate or switch entities during this phase.

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

Avoid mirroring Homebridge’s accessory model.

Preferred entity design:

- One main climate entity for the overall HVAC system.
- Optional per-zone climate entities only after multi-setpoint behaviour is confirmed.
- Zone-enable switches where capability data supports them.
- Diagnostic sensors for connection state, stale data, mode, controller state and raw fault values.
- Fan and pump entities only where hardware capability is confirmed.
- Schedules, manual mode and advance-period functions should be future services or advanced entities, not first-release clutter.

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