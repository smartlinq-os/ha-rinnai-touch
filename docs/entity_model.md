# Entity Model and HomeKit Bridge Design

This document is the authoritative entity design for the Rinnai Touch integration. It is a design artefact: none of the entities described here exist until their phase is implemented and approved. See `AGENT_SCOPE.md` for the binding summary and safety rules.

## Positioning

The integration is Home Assistant-native only. It contains no HomeKit pairing logic, no HAP transport, no HomeKit accessory definitions, no HomeKit-specific dependencies, and no direct Apple Home integration code.

Apple Home exposure happens later, entirely through the standard Home Assistant HomeKit Bridge, configured by the user. The integration's responsibilities toward that future are:

- Clean HA-native entity semantics
- Stable unique IDs
- Predictable entity names
- Documentation about recommended HomeKit Bridge exposure (this document)

## Device Model

- One Home Assistant device per physical Rinnai/Brivis WiFi module.
- Child zone devices may be created only where installed zones are confirmed from status data.
- Zone devices use stable protocol letters internally: `u`, `a`, `b`, `c`, `d`.
- Controller-provided zone names are display names only. They seed the initial friendly name; user renames persist in the entity/device registry and must never alter unique IDs.
- Do not automatically assign Areas.
- Do not create dashboards automatically.
- Not all installations are multi-zone. A system with no installed zones remains a single device with no child devices.

## Entity Inventory

| Entity | Platform | Phase | Created when | Category | Default |
|---|---|---|---|---|---|
| Main climate | climate | 2 | always (one per module) | — | enabled |
| Zone climate (per zone) | climate | 2 | MTSP=Y and zone installed | — | enabled |
| Zone enable switch (per zone) | switch | 2 | single-setpoint or evaporative systems, validated fields only | — | enabled |
| Circulation fan | fan | 2 | validated fan capability | — | enabled |
| Evaporative pump | switch | 2 | evaporative capability, after real-device validation | — | enabled |
| Connectivity | binary_sensor | 1 | always | diagnostic | enabled |
| Fault active | binary_sensor | 1 | always | diagnostic | enabled |
| Zone temperature (per zone) | sensor | 1 | zone reports valid `MT` | — | enabled |
| Operating mode | sensor (enum) | 1 | always | diagnostic | enabled |
| Controller state | sensor (enum) | 1 | always | diagnostic | enabled |
| Last valid status | sensor (timestamp) | 1 | always | diagnostic | enabled |
| Fault code detail | sensor | 1 | always | diagnostic | disabled |
| Zone installed (per zone) | binary_sensor | 1 | zone observed | diagnostic | disabled |
| Reconnect count | sensor | 1 | always | diagnostic | disabled |
| Frame counters | sensor | 1 | always | diagnostic | disabled |
| Last disconnect reason | sensor | 1 | always | diagnostic | disabled |
| Unvalidated field sensors | sensor | 1+ | as observed | diagnostic | disabled |
| Schedule/manual/auto diagnostics | sensor | 2+ | validated | diagnostic | disabled |
| Evaporative comfort-level | sensor | 1+ | evaporative systems | diagnostic | disabled |

Raw payloads are available only in redacted diagnostics downloads, never as normal entity state or attributes.

## Phase 1 vs Phase 2

**Phase 1 is read-only.** Only the observational entities above exist: connectivity, fault active, zone temperatures where available, operating mode, controller state, last-valid-status timestamp, limited fault detail, zone-installed diagnostics, and client diagnostics (reconnect count, last disconnect reason, frame counters).

`climate.py` and `switch.py` do not exist in Phase 1 and must remain absent until explicit Phase 2 approval. No entity in Phase 1 can write HVAC state.

**Phase 2 adds controls** only after Phase 1 has been tested and explicitly approved, per `AGENT_SCOPE.md`.

## Main Climate Entity (Phase 2)

- One main climate entity per module. It represents the global physical HVAC mode.
- Global modes may include Off, Heat, Cool, and Fan Only where supported and validated.
- Evaporative-only systems may map cooling to the global evaporative mode after validation.
- Do not expose HVAC Auto or Heat-Cool range mode unless real hardware provides a validated native automatic changeover capability. Do not reproduce the upstream Homebridge plugin's simulated Auto behaviour.
- On multi-setpoint systems, the main climate entity may have no global target temperature, because targets belong to zones.
- On single-setpoint systems, a global target temperature may be exposed after validation.
- Current temperature must be conditional and never fabricated. If the controller does not report a temperature, the attribute is unset — never zero.

## Global Mode Behaviour for Multi-Zone Systems

A multi-zone Rinnai or Brivis system has one physical global HVAC mode. The hardware cannot heat and cool simultaneously, and the entity model must represent that constraint accurately. The rule is **"last explicit mode request wins"**:

- Setting an installed zone climate to **Heat** switches the whole system to Heat, enables that zone, and then applies that zone's target temperature where applicable.
- Setting a zone to **Cool** switches the whole system to Cool, enables that zone, and then applies that zone's target temperature where applicable.
- Setting a zone to **Fan Only** switches the whole system to fan-only where supported and validated.
- Setting a zone to **Off** disables that zone only. It must not turn off the entire system or other enabled zones.
- Setting the **main climate entity to Off** turns off the entire HVAC system.
- A zone **target-temperature change alone** must not infer or alter the global Heat/Cool mode.
- Once a global mode change is confirmed by status data, **every enabled zone entity must update** to report the resulting global HVAC mode. Zones must never display stale or conflicting modes after a global change.

A user or automation selecting Cool on one zone while the house is heating is a legitimate request to move the whole plant into cooling mode.

## Zone Climate Entities (Phase 2, multi-setpoint only)

- Created only for installed zones on confirmed multi-setpoint (`MTSP=Y`) systems.
- Zone target temperature is local. Zone current temperature is local where available.
- Zone mode reflects the global physical mode. A zone must never silently claim it can heat while the plant is globally cooling, or vice versa.
- Setting zone Off disables only that zone.
- Single-setpoint systems must not create fake zone climate entities.

## Zone Enable Controls (Phase 2)

- Multi-setpoint systems normally use the zone climate Off state to disable a zone.
- Do not add duplicate zone-enable switches where they would conflict with a zone climate entity.
- Single-setpoint or evaporative systems may receive dedicated zone-enable switches only where validated hardware fields support them.

## Fan and Evaporative Pump (Phase 2)

- The circulation fan becomes a separate Home Assistant fan entity where validated, not merely a climate fan mode. The fan is genuinely independent hardware behaviour (usable with heating off), and the observed 1–16 speed range maps cleanly onto percentage steps.
- Evaporative pump control may become a switch only after real-device validation.
- Pump controls are operationally sensitive and must not be part of the recommended Apple Home exposure set.

## Default Entity Visibility

Enabled by default where supported:

- Connectivity
- Fault active
- Zone temperature sensors
- Operating mode
- Controller state
- Last-valid-status timestamp

Disabled by default:

- Fault-code detail
- Zone-installed indicators
- Reconnect counters
- Frame counters
- Last disconnect reason
- Unvalidated field sensors
- Future schedule/manual/auto diagnostic entities
- Evaporative comfort-level diagnostics

## HomeKit Bridge Recommendations

### Phase 1

Do not expose this integration to HomeKit Bridge. No control entities exist yet and the entity model is still settling. Documentation must not recommend bridging Phase 1 entities.

### Phase 2 recommended exposure

- **Single-setpoint systems:** main climate, fan, and optional zone switches where validated.
- **Multi-setpoint systems:** main climate plus zone climate entities, optional temperature sensors, and fan where validated.

HomeKit users must be warned that selecting Heat, Cool, or Fan Only on a zone may change the entire HVAC system globally — zone mode changes affect the shared plant.

### Never recommend exposing to Apple Home

- Connectivity
- Controller state
- Stale-status sensors
- Fault details and raw fault data
- Fault-active sensor
- Diagnostics of any kind
- Protocol counters and reconnect counters
- Raw payload data
- Evaporative pump controls
- Reboot controls
- Time/date controls
- Schedule-maintenance controls
- Advanced module-maintenance surfaces
- Anything based on unvalidated fields

Two enforcement layers apply: diagnostic entity categories keep these out of default bridge filters, and documentation recommends an explicit include-entity allowlist rather than domain-wide exposure.

## Stable Naming and Unique-ID Strategy

The goal: a HomeKit pairing established after Phase 2 survives every subsequent upgrade.

- **Root identity is the config entry ID.** It is stable for the life of the entry and independent of IP address, hostname, discovered capabilities, and display names.
- **Entity unique IDs** use `{entry_id}_{stable_protocol_key}`. Stable protocol keys are fixed identifiers such as:
  - `climate_main`
  - `zone_a_climate`
  - `zone_a_temperature`
  - `zone_a_enabled`
  - `fault_active`
  - `fan`
- **Never** use IP address, hostname, controller zone name, room name, capability state, or current mode in a unique ID.
- **Capability changes may add or disable entities but must not re-key existing entities.** A system that later reveals multi-setpoint support or add-on cooling grows new entities; existing unique IDs are immutable.
- **Zone letters are stable internal identities. Zone names are display names only.**
- **Avoid unique-ID migrations** unless a versioned migration is explicitly designed and tested.
- **Devices:** module `(DOMAIN, {entry_id})`; zone children `(DOMAIN, {entry_id}_zone_a)` linked via the module device.
- **User guidance:** settle Home Assistant entity naming *before* initially bridging to Apple Home. Apple Home preserves accessory identity and may recreate accessories — losing room assignments and automations — if identities change after pairing.
