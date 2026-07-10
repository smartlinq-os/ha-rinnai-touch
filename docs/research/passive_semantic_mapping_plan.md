# Passive Semantic Mapping Plan

This is a **plan, not evidence**. It defines how a future passive
observation exercise should be run and recorded; it does not itself
contain any capture, claim, or ledger update. No entry in
`docs/protocol_assumptions.md` changes as a result of this document.

The exercise it describes is strictly **read-only**: all actions are
performed using the real wall controller or the vendor app, never through
this integration or any test tool. The integration and any tooling used
alongside it send no traffic to the module at any point. This is **not
Gate E** — it has nothing to do with outbound session-maintenance
traffic — and it is **not command/control validation**: nothing here
tests, implies, or prepares sending a write to the module.

## 1. Purpose and Scope

The goal is to map what inbound status fields mean, by passively watching
how they change while a person operates the real wall controller or
vendor app. In scope:

- operating mode meanings (`SYST.OSS.MD` and the active mode group)
- controller state meanings (`SYST.OSS.ST`)
- fault/status meanings (`SYST.FLT` and related fields)
- current temperature fields, where visible (`MT`-style fields)
- target/setpoint fields, where visible (`SP`-style fields)
- fan state, where visible
- zone state, where visible (`Z?O` / `Z?S` groups)
- any unknown group or field observed to change in response to a user
  action

Boundaries that apply to the whole exercise, not just this section:

- Read-only throughout. No bytes are ever sent by this integration or any
  accompanying tool.
- Every state change originates from the real wall controller or the
  vendor app — never from anything running this plan.
- This plan is not Gate E and creates no path toward it on its own.
- This plan is not command/control validation. It does not test whether a
  write succeeds, because nothing here ever writes.

## 2. Preconditions

- [ ] v0.1.0 or later of the passive integration is installed
- [ ] Homebridge and any other competing local TCP client are disabled
- [ ] broad debug logging (`custom_components.rinnai_touch: debug`) is
      enabled only for the capture window, if needed, and turned back
      down afterwards — see `docs/support/log_collection.md`
- [ ] the HVAC system is in a safe, normal operating condition before
      starting
- [ ] a person is present throughout and able to stop at any point
- [ ] no packet capture of any kind is run
- [ ] no raw protocol payloads are committed to repository documentation
- [ ] no private IP addresses, ports, credentials, tokens, serial numbers,
      or household details are recorded in notes — see
      `reference_data/README.md` for the full hygiene rules this exercise
      must follow

## 3. Capture Method

A safe, user-run procedure, one action at a time:

1. Start from a stable baseline: the system in a known, normal state,
   with inbound status flowing normally.
2. Record the current visible wall-controller or vendor-app state in
   plain human terms (for example, "heating, 21°C target, zone A on") —
   not as a protocol field dump.
3. Perform exactly one user action at a time on the real wall controller
   or vendor app.
4. Wait for inbound status to settle before recording anything.
5. Collect only sanitised lifecycle/status observations — see the
   template in section 5. Never a raw payload.
6. Where practical, restore the previous state before starting the next
   action, so each observation starts from a known baseline again.
7. Stop immediately if any fault, controller-state anomaly, or unexpected
   HVAC behaviour appears, and do not continue testing until it is
   understood.

## 4. Suggested Passive Action Matrix

All actions below are ordinary user actions on the real wall controller
or vendor app — the kind an owner would perform anyway. None of them
induce a fault, defeat a safety, disconnect hardware, or create an
abnormal HVAC condition.

| Action | Performed using | Expected visible user-facing change | Fields/groups to watch | Risk level | Notes / stop condition |
|---|---|---|---|---|---|
| Baseline idle state | Wall controller or vendor app (observe only) | None — establishes the starting point | `SYST.OSS.MD`, `SYST.OSS.ST`, active mode group | Low | Record before touching anything else |
| System off/on transition | Wall controller or vendor app | System changes between off and its previous mode | `SYST.OSS.MD`, `SYST.OSS.ST` | Low | Allow the system to settle before the next action; do not cycle rapidly |
| Operating mode change | Wall controller or vendor app | Displayed mode changes (e.g. heat to cool, where supported) | `SYST.OSS.MD`, mode group presence (`HGOM`/`CGOM`/`ECOM`) | Low | Use only modes the system actually supports |
| Target temperature up/down by one step | Wall controller or vendor app | Displayed target changes by one step | Active mode group's setpoint field | Low | One step only; avoid extreme setpoints |
| Fan setting change, if supported | Wall controller or vendor app | Displayed fan state/speed changes | Active mode group's fan-related field | Low | Skip if the system has no independent fan control |
| Zone toggle, if supported | Wall controller or vendor app | A zone's displayed enabled/disabled state changes | Zone option group (`Z?O`) and zone status group (`Z?S`) | Low | Toggle back before the next action |
| Schedule/timer state, if visible | Wall controller or vendor app | Displayed schedule/timer state changes | Schedule-related fields, if any are visible | Low | Observe only; do not create new schedule entries for this exercise |
| Fault/no-fault baseline only | Observe only | None expected — confirms `SYST.FLT.AV` reads not-active in normal operation | `SYST.FLT` | Low | Never induce a fault. If one appears unexpectedly, stop and record it, then follow section 3 step 7 |
| Vendor app view/refresh without changing state, if safe | Vendor app | None — confirms passive observation matches app display | Any field the app also displays | Low | Skip if the app cannot be opened without side effects |

## 5. Evidence Recording Template

Use this template for every observation. No raw payloads, ever.

```text
Observation ID:
Date/window (coarse only, e.g. "week of 2026-07"):
Integration version:
Module type / firmware (if known):
Action performed:
Before state (human terms):
After state (human terms):
Inbound fields/groups that changed:
Unchanged fields/groups worth noting:
Reverted cleanly (yes/no/partially):
Anomalies:
Confidence level:
Follow-up needed:
```

Keep entries in human and general-field terms. Do not paste raw frame
content, IP addresses, ports, credentials, tokens, serial numbers, or
household detail into any observation record.

## 6. Classification Scheme

Apply one label per observation:

- **Observed once** — seen a single time, on one module, one session.
- **Repeated on same module** — seen more than once on the same
  installation.
- **Repeated across sessions** — seen consistently across separate
  sessions on the same module.
- **Repeated across module/firmware** — seen consistently on more than
  one module or firmware version.
- **Contradicted** — a later observation disagreed with an earlier one.
- **Unsafe / do not test** — the action itself should not be repeated;
  record why and stop.

A single "observed once" entry is not enough for a stable semantic claim.
Claims that later reach `docs/protocol_assumptions.md` need at least
"repeated on same module" evidence, and ideally more, following the same
evidence discipline already used for ledger items such as A14, A15, and
A16.

## 7. How Evidence May Later Enter the Repository

This plan authorises none of the following by itself. Only after
collected evidence has been reviewed might a later, separately proposed
and approved commit add:

- sanitised synthetic fixtures, following the existing sanitisation
  procedure in `reference_data/README.md` and the pattern already used by
  `scripts/sanitise_rinnai_capture.py`
- tests for parser/model mapping, in the existing offline test style
- updates to the `docs/protocol_assumptions.md` ledger, with an evidence
  label and status exactly like the existing entries
- richer read-only Home Assistant entities, if a mapping is confirmed
  with sufficient confidence

Sanitised observation records, once real evidence exists, most likely
belong under `reference_data/notes/` or `reference_data/anonymised/`,
matching the existing precedent of files like
`reference_data/notes/jaron_system_profile.md` — but that is a decision
for whenever the first real evidence is ready to commit, not something
this plan fixes in advance.

## 8. Boundaries Toward Future Control

- Passive semantic mapping is a prerequisite for control, not control
  itself.
- Observing a field change does not prove it is safe to write that field.
  Read and write behaviour are not the same evidence.
- Outbound commands of any kind remain out of scope for this plan.
- Gate E remains separately gated and is not advanced by this plan.
- Ledger item A11 remains Unknown; nothing in this plan changes that.
- No climate or other control entity should be added on the strength of
  this plan alone — that requires its own separately approved milestone,
  well beyond passive observation.
