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

Exactly five evidence labels are used, applied to every evidence-backed
entry in this register:

- **Proven for a studied community implementation** — directly observed or
  demonstrated in a named, studied implementation or installation. Never
  universal proof.
- **Strong external evidence** — consistently supported by external
  implementations or by external documentation that has not been
  independently verified as an official source. Not proof.
- **Inference / hypothesis** — a reasonable conclusion or product-level
  conjecture; not itself evidence.
- **Unknown** — not established; must not be treated as fact.
- **Rejected assumption** — recorded so it is never assumed.

Every evidence-backed entry also carries a source class, using only:

- community report;
- community implementation code;
- redistributed installer/service-manual copy, provenance pending
  independent verification;
- external documentation cited in prior research, pending independent
  verification;
- independently verified official source.

No entry currently qualifies for the "independently verified official
source" class. Entries resting on manufacturer or installer documentation
cited in prior research are labelled Strong external evidence and remain
pending until independently verified against official Brivis/Rinnai-hosted
sources.

## Community evidence sources

Reviewed read-only on 4 July 2026 — full review, scope limits, and
non-transferable assumptions in
`docs/research/community_brivis_networker_reverse_engineering_review.md`:

- a community reverse-engineering report of one legacy rotary-generation
  Brivis control panel and its two-wire connection (community report and
  community implementation code, 2016–2018);
- a community ESPHome controller-replacement project on an NC-2-era system
  (community report and community implementation code, 2022–2023), whose
  repository also redistributes a copy of a Brivis Networker
  installer/service manual (redistributed installer/service-manual copy,
  provenance pending independent verification).

Community evidence never weakens an N-BW2-specific Unknown, and the
redistributed manual copy is never the sole basis for weakening any
Unknown.

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

## Ecosystem claims (P1–P7)

| ID | Claim | Evidence label and source class |
|---|---|---|
| P1 | Compatible systems use labelled TW1/TW2 two-wire Networker connections. | Strong external evidence — external documentation cited in prior research, pending independent verification |
| P2 | TW1 must be connected to TW1 and TW2 to TW2; polarity must be respected, and reversed wiring is a known fault risk. | Strong external evidence — external documentation cited in prior research, pending independent verification |
| P3 | The official N-BW2 attaches to the Networker ecosystem as an add-on Wi-Fi bridge accessory. | Strong external evidence — external documentation cited in prior research, pending independent verification |
| P4 | The N-BW2 commonly uses an independent low-voltage DC plug-pack supply on NC-3/NC-6 installations; some NC-7 arrangements may supply it through the interface. | Strong external evidence — external documentation cited in prior research, pending independent verification |
| P5 | Networker systems span multiple controller/system families and may include heating, refrigerated cooling, evaporative cooling, sensors, and zoning modules. | Strong external evidence — external documentation cited in prior research, pending independent verification |
| P6 | Controller and sensor addressing exists for some Networker device classes. This does not establish an address model for the N-BW2 or any future SmartLinq accessory (see U5). | Strong external evidence — external documentation cited in prior research, pending independent verification |
| P7 | The N-BW2 exposes a TCP/JSON LAN interface that can monitor and control compatible systems. The JSON is a LAN-side presentation, not the raw bus protocol. | Strong external evidence — community implementation code |

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

Corroboration recorded by the community review (none of it upgrades a
baseline entry or weakens an Unknown on its own):

- **P4/P6 corroboration — Strong external evidence (redistributed
  installer/service-manual copy, provenance pending independent
  verification):** a redistributed Brivis
  Networker service-manual copy describes legacy Networker wall controls
  powered from the network wiring within a documented low-voltage DC
  operating range; installer-assigned per-appliance unit identification
  numbers (its own text uses the word "address"); and, for the legacy
  "Networker Version 3" generation, master/slave controller roles set by
  installer parameter, with dual controllers wired in parallel. Provenance
  pending independent verification. N-BW2 and Touch-generation
  applicability remains Unknown (U5).
- **NC-2 limitation — Proven for a studied community implementation
  (community report):** one project found its NC-2 controller's
  address/master role fixed, preventing coexistence with their custom
  replacement controller; the project replaced the NC-2 rather than
  coexisting with it. Replacement evidence is not coexistence evidence.
- **"NC-3 onwards may allow address changes" — Strong external evidence
  (community report; source-attributed understanding):** retained as
  attributed understanding only.

## Inference / Hypothesis

| ID | Statement | Label |
|---|---|---|
| I1 | The N-BW2 is probably an active Networker-bus peer or protocol bridge rather than a purely passive listener, because it can effect control. Its actual bus role is not formally proven. | Inference / hypothesis |
| I2 | A future SmartLinq communications module is architecturally plausible because an official add-on bridge accessory already occupies that role. Feasibility is not established. | Inference / hypothesis |
| I3 | A separate SmartLinq module could eliminate NBW2 LAN-side fragility by owning local networking, multi-client API behaviour, updates, logging, and recovery — contingent on safe bus interoperability. | Inference / hypothesis |

## Unknown — must remain unknown

None of the following may be turned into requirements, code, electrical
design decisions, or marketing claims:

| ID | Unknown |
|---|---|
| U1 | General TW1/TW2 electrical facts. For certain studied legacy rotary-generation installations, community evidence shows a DC-powered two-wire pair with current-keyed serial signalling (Proven for a studied community implementation; community report + community implementation code), and a redistributed manual copy states a low-voltage DC operating range for legacy wall controls (Strong external evidence; redistributed installer/service-manual copy, provenance pending independent verification). Everything else remains Unknown: voltage/impedance/termination/tolerance and loading envelopes in general, Touch-generation (NC-6/NC-7) systems, and every N-BW2-specific electrical fact. |
| U2 | The signalling mechanism beyond the studied scope. For the studied legacy installations, two independent community projects decode the same bus traffic as inverted-UART-style asynchronous serial at a standard low rate (Proven for a studied community implementation). Whether this holds for other generations — especially the Touch era the N-BW2 targets — or universally across Networker families remains Unknown. PLC/RS-485/other-mechanism claims stay unsupported beyond that scope, and the wire count itself still proves nothing (see rejected assumptions). |
| U3 | Bus arbitration, collision handling, polling/broadcast rules, discovery/enrolment, and device-class rules — Unknown for all generations. Community observations of the studied legacy installations show request/response, acknowledgement-like, and periodic traffic patterns, as authors' interpretations only (Inference / hypothesis; community report). |
| U4 | Whether a third-party observer can attach safely — electrically and operationally — and obtain meaningful data without active participation on any target system, especially Touch-generation systems with an N-BW2 present. Attached read-out was demonstrated on the studied legacy installations (Proven for a studied community implementation), but attachment measurably loads the bus, and bus-powering a Wi-Fi-class device disturbed communications in one project until external power was used. Passive is not the same as electrically non-invasive. |
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
  programme;
- controller-replacement evidence demonstrates parallel coexistence;
- community-prototype evidence demonstrates commercial design, compliance,
  safety, or universal compatibility;
- evidence from studied legacy controller-family installations applies to
  Touch-generation systems or to the N-BW2.

## Change discipline

Update this register only with new labelled evidence. Every new entry
carries one of the five evidence labels and one of the five source classes.
Promotion out of Unknown requires the separately approved, passive-first
hardware research programme (bench-owned equipment, electrically safe
isolated observation, no transmission) — never inference from the LAN API,
from third-party behaviour, or from a redistributed document copy alone. No
raw protocol material (byte values, frames, opcode tables, address values,
CRC parameters, exact timing or rate values, or copyable circuit detail)
may be recorded in this repository.
