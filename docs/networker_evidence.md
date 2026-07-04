# Rinnai / Brivis Networker Evidence Register

This register is the single in-repo record of what SmartLinq knows about
the Rinnai / Brivis Networker ecosystem and its TW1/TW2 two-wire interface.
It exists so that future work never turns a plausible idea into an assumed
fact.

## Purpose and rules

- Nothing in this register may become code, electrical design,
  requirements, or marketing claims without the separately approved
  hardware research programme producing new labelled evidence.
- Entries record no raw URLs, private file paths, addresses, ports,
  credentials, raw frames, or device-specific secrets.
- Evidence claims are kept separate from SmartLinq design implications: an
  implication is a design consequence SmartLinq chooses, not part of the
  evidence itself. Implications are marked explicitly.
- The NBW2 LAN protocol ledger is a separate document:
  `docs/protocol_assumptions.md`.

## Evidence labels

Exactly four labels are used:

- **Proven** — documented by the manufacturer/installer documentation
  family named in the entry, or directly observed.
- **Inference** — a reasonable conclusion from proven facts; not itself
  proven.
- **Hypothesis** — a product-level conjecture requiring validation.
- **Unknown** — not established; must not be treated as fact.

## Product boundary (binding)

A SmartLinq Networker module, if ever built, is an **add-on communications
accessory only** — comparable in role to the official N-BW2 accessory. It
is never a replacement for, and never bypasses or alters, HVAC equipment,
appliance control boards, appliance safety functions (gas, combustion,
flame-proving, thermal, pressure, compressor or fan-motor protection), wall
controllers, zone-control modules or damper hardware, or installer safety
procedures.

Correct product language: "SmartLinq Networker Bus Interface Module" or
"SmartLinq Rinnai Connectivity Module" — not a replacement HVAC controller.

Safer factual phrasing to reuse: *the Networker bus may influence normal
operating control; existing appliance safety systems must remain
independent, installed, and untouched.*

## Proven

| ID | Claim | Evidence reference |
|---|---|---|
| P1 | Compatible systems use labelled TW1/TW2 two-wire Networker connections. | Manufacturer installation manual family (Touch Wi-Fi kit / Networker controller documentation) |
| P2 | TW1 must be connected to TW1 and TW2 to TW2; polarity must be respected, and reversed wiring is a known fault risk. | Manufacturer installation manual family |
| P3 | The official N-BW2 attaches to the Networker ecosystem as an add-on Wi-Fi bridge accessory. | N-BW2 installation/configuration documentation |
| P4 | The N-BW2 commonly uses independent 12 V DC power on NC-3/NC-6 installations; some NC-7 arrangements may supply it through the interface. | N-BW2 installation/configuration documentation |
| P5 | Networker systems span multiple controller/system families and may include heating, refrigerated cooling, evaporative cooling, sensors, and zoning modules. | Manufacturer / installer-service documentation family |
| P6 | Controller and sensor addressing exists for some Networker device classes. This does not establish an address model for the N-BW2 or any future SmartLinq accessory (see U5). | Manufacturer / installer-service documentation family |
| P7 | The N-BW2 exposes a TCP/JSON LAN interface that can monitor and control compatible systems. The JSON is a LAN-side presentation, not the raw bus protocol. | Observed LAN API / external implementation evidence |

Design implications (SmartLinq choices, not evidence):

- **Implication for SmartLinq (P1, P3):** any future add-on connects only
  through the documented Networker interface, in the accessory role the
  N-BW2 already occupies.
- **Implication for SmartLinq (P2):** hardware and installation design must
  enforce polarity.
- **Implication for SmartLinq (P4):** default hardware should carry its own
  regulated power supply; interface-supplied power must never be assumed
  universal.
- **Implication for SmartLinq (P5):** compatibility is phased and
  evidence-led, never marketed as universal.
- **Implication for SmartLinq (P7):** never infer the bus protocol from the
  LAN JSON.

## Inference / Hypothesis

| ID | Statement | Label |
|---|---|---|
| I1 | The N-BW2 is probably an active Networker-bus peer or protocol bridge rather than a purely passive listener, because it can effect control. Its actual bus role is not formally proven. | Inference |
| I2 | A future SmartLinq communications module is architecturally plausible because an official add-on bridge accessory already occupies that role. Feasibility is not established. | Inference |
| I3 | A separate SmartLinq module could eliminate NBW2 LAN-side fragility by owning local networking, multi-client API behaviour, updates, logging, and recovery — contingent on safe bus interoperability. | Hypothesis |

## Unknown — must remain unknown

None of the following may be turned into requirements, code, electrical
design decisions, or marketing claims:

| ID | Unknown |
|---|---|
| U1 | Exact TW1/TW2 electrical signalling scheme, modulation, voltage tolerances, impedance, framing, timing, and termination requirements. |
| U2 | Whether Networker signalling is PLC, UART-like, RS-485-like, proprietary analog/modulation, or another mechanism. A teardown from a different Rinnai product line is a lead, not proof for Networker. |
| U3 | Bus arbitration, polling/broadcast behaviour, discovery/enrolment, and device-class rules. |
| U4 | Whether a passive third-party observer can attach safely and obtain meaningful data without active participation. |
| U5 | Whether the N-BW2 has a controller-style Networker address, or whether a SmartLinq module would need one. Documented controller/sensor addressing (P6) does not prove this. |
| U6 | Whether the N-BW2 polls for normal state, receives broadcasts, mirrors controller traffic, or uses a hybrid mechanism. |
| U7 | Exact cross-model compatibility, especially NC-3 vs NC-6 vs NC-7, add-on cooling, evaporative systems, ZonePlus, and multi-zone installations. |
| U8 | Warranty, certification, installer, electrical-isolation, and commercial-liability requirements for a third-party bus accessory. |

## Rejected assumptions

The following are recorded as rejected; none may be assumed:

- two wires means UART or RS-485;
- Networker is definitely power-line communication;
- a passive attachment is electrically harmless;
- NBW2 JSON groups map directly to bus messages;
- every bus device uses the same controller-style address model;
- official controller coexistence guarantees third-party coexistence;
- the bus directly carries appliance safety interlock logic;
- a future module can be installed without a compatibility and safety
  programme.

## Change discipline

Update this register only with new labelled evidence, naming the source
class and document family. Promotion out of Unknown requires the separately
approved, passive-first hardware research programme (bench-owned equipment,
electrically safe isolated observation, no transmission) — never inference
from the LAN API or from third-party behaviour.
