# Reference System Profile — Primary Test System

Generic, non-identifying facts about the primary development/test installation. This file must never contain IP addresses, MAC addresses, home-specific room names, credentials, occupancy-related timestamps, or raw payloads. Zone identities are recorded by protocol letter only. See `reference_data/README.md` for the full hygiene rules.

**Status: not yet captured.** All fields below are pending the first passive probe run (which requires explicit user approval, Homebridge stopped, and no competing local Rinnai client — see the Probe Tool Specification in `AGENT_SCOPE.md`).

## System Facts

| Field | Value | Source |
|---|---|---|
| Brand (Rinnai / Brivis) | Pending | — |
| WiFi module model | Pending (expected N-BW2 family) | — |
| Heater present (`SYST.AVM.HG`) | Pending | — |
| Add-on cooling present (`SYST.AVM.CG`) | Pending | — |
| Evaporative cooling present (`SYST.AVM.EC`) | Pending | — |
| Multi-setpoint (`SYST.CFG.MTSP`) | Pending | — |
| Temperature unit (`SYST.CFG.TU`) | Pending | — |
| Zones installed (letters only, per observed mode) | Pending | — |
| Controller reports measured temperature (`MT`) | Pending | — |
| Controller family / firmware notes (generic) | Pending | — |

## Observed Behaviour Notes

To be populated from sanitised probe observations only:

- Status frame cadence: pending (validates A1 in `docs/protocol_assumptions.md`)
- Idle disconnect behaviour: pending (validates A2)
- Frame delimiters / byte-level framing: pending (validates A3)
- Received sequence behaviour: pending (validates A4)

## Rules for Updating This File

1. Record protocol-level facts only, in generic terms.
2. Use zone letters (`U`, `A`–`D`), never household zone names.
3. Cross-reference the assumptions ledger in `docs/protocol_assumptions.md` when an observation validates or refutes an entry.
4. Sanitised payload excerpts belong in `reference_data/anonymised/` or `tests/fixtures/`, not here.
