# ADR 0001: Transport/Source Boundary and the SmartLinq Semantic Contract

## Status

Accepted — 4 July 2026.

## Context

SmartLinq is building a reliable local Home Assistant integration for
compatible Rinnai / Brivis Networker HVAC systems. The immediate path
communicates with the existing Rinnai / Brivis N-BW2 Wi-Fi module over its
local TCP interface. A longer-term strategic option is a SmartLinq-owned
add-on communications module attaching to the documented TW1/TW2 Networker
interface and exposing a more robust local API. That option is governed by
the SmartLinq Networker programme context (v1.0, 4 July 2026, private
engineering baseline) and by the in-repo evidence register,
`docs/networker_evidence.md`.

This ADR fixes the boundary that keeps today's NBW2 work and any future
transport interchangeable beneath a stable Home Assistant-facing model.

## Decision

### The SmartLinq semantic contract (transport-neutral)

The Home Assistant-facing state is transport-neutral and consists of:

- the typed status snapshot (`models.StatusSnapshot`);
- data freshness (`no_data` / `fresh` / `stale`; monotonic, report-only);
- connection/link health, kept distinct from freshness and from HVAC state;
- the conservative capability model (evidence-led, never assumed from
  product family names);
- later, command-to-acknowledgement semantics (Phase 2, separately
  approved).

Entities and any future HomeKit or SmartLinq tooling consume coordinator
state only. They must never read the snapshot's raw NBW2 groups
(`StatusSnapshot.raw_groups`), which exist for the NBW2 layer and future
redacted diagnostics only. This is enforced by review convention today; a
structural lock is a recommended addition at the next approved
test-touching milestone.

### The transport/source seam as implemented today

`coordinator.RinnaiTouchCoordinator` depends on an injectable
client/source-like dependency: the `client_factory` constructor parameter
builds an object owning a `start()` / `stop()` lifecycle and publishing
typed snapshot and connection-event callbacks. Offline tests already
exercise this seam with socket-free fakes.

This is an evolution-friendly seam. It is **not** a completed generic
multi-transport framework, and there is **no** public `RinnaiTouchSource`
API — no such name exists in code. Formalising a named source interface is
future work, undertaken only when a second source implementation is
actually approved.

### NBW2: a supported legacy transport adapter

The N-BW2 TCP client (`client.py`, with `protocol.py` framing and the raw
layer of `models.py`) is a **supported legacy transport adapter**, not the
SmartLinq HVAC product core. All NBW2 wire specifics stay confined beneath
the seam. The adapter remains passive receive-only under the current phase
rules in `AGENT_SCOPE.md`.

### Future SmartLinq Networker module: a separate programme

If proven viable, a future SmartLinq Networker communications module
presents a versioned local API source beneath the same semantic model. It
is an add-on communications accessory only — never a replacement for HVAC
equipment, appliance control boards, safety systems, wall controllers, or
zoning hardware.

No present code assumes anything about TW1/TW2 electrical behaviour,
addressing, signalling, polling, passive observation, or active
participation. Hardware work is a separately approved, passive-first
research programme with its own gates; its evidence register is
`docs/networker_evidence.md`.

Community reverse-engineering evidence reviewed on 4 July 2026 (see
`docs/research/community_brivis_networker_reverse_engineering_review.md`)
means that research no longer starts from a blank physical-layer hypothesis
for certain studied legacy Brivis controller-family systems. Both sides of
that finding are binding: the same review establishes that Touch-generation
systems, N-BW2-specific bus behaviour, safe parallel third-party
attachment, active participation, and commercial suitability remain
Unknown. The decision, gates, and rules in this ADR are unchanged.

## Rules for future work

1. Entities depend on typed coordinator state, freshness, and capability
   data — never NBW2 raw groups.
2. `client.py` remains the NBW2-specific transport implementation; NBW2
   concepts must not leak above the seam.
3. Any future SmartLinq hardware module exposes a versioned local API that
   can implement the same source/coordinator contract.
4. Capability support is derived from actual system evidence, not product
   family names.
5. Communications-module health remains distinct from HVAC state/health.
6. Without separate explicit approval, do not add: UDP or any discovery,
   retry-timing changes, keepalives, commands or outbound traffic of any
   kind, raw-group entity coupling, live-network behaviour in development
   or tests, or bus-level concepts (TW1/TW2, device addressing, signalling,
   topology) in entities, coordinator semantics, config flow, or
   diagnostics.
7. External implementations (`funtastix/rinnaitouch`,
   `funtastix/pyrinnaitouch`, and the read-only Homebridge reference) are
   behavioural evidence only. Do not copy outbound keepalives, command
   payloads, sequence arithmetic, acknowledgement algorithms, authenticated
   reboot commands, UDP listener implementations, global IP-keyed
   singletons, blocking setup patterns, host/IP-derived identity, or
   parser/thread implementations.
8. Stop and ask for scope approval before anything in rule 6 or 7.

## Consequences

- Today's NBW2 reliability work proceeds without blocking on hardware
  research, and hardware speculation cannot leak into Home Assistant
  semantics.
- A future SmartLinq module can be adopted by adding a source
  implementation beneath the seam; entities, unique IDs, and automations
  are unaffected.
- The cost is discipline: NBW2-specific fixes must land beneath the seam
  even when a shortcut through the entity layer would be quicker.

## References

- `AGENT_SCOPE.md` — binding scope and safety rules.
- `docs/networker_evidence.md` — Networker bus evidence register.
- `docs/protocol_assumptions.md` — NBW2 LAN protocol facts and assumptions
  ledger.
- `docs/entity_model.md` — entity inventory and identity strategy.
