# Community Brivis Networker Reverse-Engineering Review

Read-only review completed 4 July 2026. This document records what two
community projects demonstrate about the two-wire "Networker" bus on
**studied legacy Brivis controller-family installations**, with strict scope
limits, so future work neither re-derives these findings nor generalises
them beyond their evidence.

## Purpose and evidence discipline

Exactly five evidence labels are used:

- **Proven for a studied community implementation**
- **Strong external evidence**
- **Inference / hypothesis**
- **Unknown**
- **Rejected assumption**

Source classes: community report; community implementation code;
redistributed installer/service-manual copy, provenance pending independent
verification; external documentation cited in prior research, pending
independent verification; independently verified official source.

Binding hierarchy:

- Proven for one studied installation is not universal Networker proof.
- Proven for a custom replacement-controller board is not proof of safe
  parallel coexistence.
- Proven for a hobby prototype is not proof of commercial hardware design,
  compliance, safety, cross-model compatibility, or installer suitability.
- Proven controller-bus behaviour is not proof of N-BW2 bus behaviour.
- An observed protocol or circuit topology is not permission to add code,
  hardware, commands, keepalives, UDP, discovery, or active bus
  participation.

No raw protocol material is reproduced here: no byte values, frames, packet
examples, opcode tables, address values, CRC parameters, exact timing or
rate values, or copyable circuit detail. Only high-level structure is
described; the sources carry the specifics.

## Source identity

1. **Community report A** — `NZSmartie/bravis-reverse-engineering`
   (default branch at short revision 92e816b; final change April 2018; work
   dated 2016–2018). One studied installation: a Brivis ducted-heating
   system with a legacy rotary-dial wall control. Source classes: community
   report (write-up), community implementation code (parser/logger).
2. **Community project B** — `Makin-Things/ESPHome-Brivis-Networker`
   (default branch at short revision 99e3564; final change December 2023;
   key update September 2022). One studied installation: a Brivis ducted
   heater with an NC-2 controller, later operated by the author's custom
   replacement controller board. Source classes: community report,
   community implementation code.
3. **Redistributed manual** — a copy of "Brivis Service Manual 6 —
   Networker" (Issue 5, printed 2014) is redistributed inside project B's
   repository. Source class: redistributed installer/service-manual copy;
   **provenance pending independent verification** against an official
   Brivis/Rinnai-hosted source. Claims resting only on this copy are
   labelled Strong external evidence, never manufacturer-proven, and never
   the sole basis for weakening an Unknown.

## What each source demonstrates

**Report A (label: Proven for a studied community implementation, except
where noted):** the studied panel's two-wire connection enters a full
bridge rectifier, making that panel polarity-tolerant at its own input
(installation-level polarity rules in the evidence register remain
authoritative); the pair carries low-voltage DC that dips measurably while
data is transmitted, consistent with current-keyed signalling; a
threshold-detection receive circuit plus a logic analyser, later a
microcontroller serial logger, collected traffic non-destructively; the
captured signal decodes as inverted-UART-style asynchronous serial at a
standard low rate; messages are length-prefixed and contain address-like
source and destination fields, command-like content, optional data, and a
trailing CRC mechanism identified by the author. The author's functional
interpretations — ping-like, acknowledgement-like, status-request/report,
time-of-day, and temperature-control behaviours, including a scan of
successive addresses observed after the controller was removed — are
**Inference / hypothesis**: implementation observations, not an official
protocol specification.

**Project B (label: Proven for a studied community implementation, except
where noted):** the legacy Networker bus supplies both power and serial
communications over its two wires (author statement consistent with their
working hardware); their board attached to the bus and logged traffic
before any controller replacement; powering a Wi-Fi-class microcontroller
plus analogue circuitry from the bus caused serial errors during Wi-Fi
transmission, resolved by an external supply — direct evidence that
attachment loading matters; from September 2022 the author's board
**replaced** the NC-2 controller and ran the home's heating; the NC-2's
address/master role could not be changed, preventing coexistence with the
custom controller. The statement that NC-3-onward controllers may allow
address changes is the author's own understanding (**Strong external
evidence**, source-attributed). Project B's implementation code
independently corroborates report A's framing model, inverted-serial
signalling (with a marginal practical tuning difference in rate between the
two projects), trailing CRC mechanism, and consistent address-like field
usage.

**Redistributed manual (label: Strong external evidence; source class:
redistributed installer/service-manual copy, provenance pending independent
verification):** describes,
for legacy rotary-generation Networker systems, wall controls powered from
the network wiring within a documented low-voltage DC operating range;
installer-assigned per-appliance unit identification numbers (the manual's
own text uses the word "address"); and, for the "Networker Version 3"
generation, master/slave controller roles set by installer parameter with
dual controllers wired in parallel — controllers ship as master by default,
and two masters (or two slaves) do not function together.

## Physical-layer findings (studied legacy family)

Evidenced for the studied installations only: a two-wire, DC-powered,
polarity-tolerant-at-the-studied-panel bus carrying current-keyed,
inverted-UART-style asynchronous serial; attached devices load the bus
measurably; bus power is sufficient for a panel but was not sufficient for
a Wi-Fi-class prototype during transmission. Tolerances, impedance,
termination, loading budgets, and every Touch-generation or N-BW2-specific
electrical fact remain **Unknown**.

## Packet-model findings (structural description only)

Evidenced for the studied installations only: length-prefixed messages with
address-like source/destination fields, command-like content, optional
data, and a trailing CRC mechanism; request/response, acknowledgement-like,
and periodic traffic patterns per the authors' interpretations
(**Inference / hypothesis**). Arbitration, collision handling,
discovery/enrolment, device-class rules, and any N-BW2 dialect remain
**Unknown**.

## Coexistence and addressing findings

The studied NC-2 could not change its address/master role (Proven for that
installation); dual-controller master/slave operation is described for the
legacy Version 3 generation by the redistributed manual (Strong external
evidence); NC-3-onward address-change capability is source-attributed
understanding only. **No source provides any evidence
about N-BW2 bus addressing or N-BW2 coexistence** — absence of evidence,
recorded as Unknown (register U5/U6).

## Applicability to N-BW2 and SmartLinq — non-transferable assumptions

Not transferable from this review: legacy-family electrical or framing
findings to Touch-generation (NC-6/NC-7) systems; anything to N-BW2 bus
behaviour; controller-replacement success to parallel add-on coexistence;
prototype attachment to safe, warranted, installer-acceptable attachment;
observed structure to permission for any active participation. SmartLinq's
intended model is an add-on communications accessory alongside existing
controllers — a mode **neither project demonstrated** (project B removed
the original controller for its active role).

## Product implications (SmartLinq choices, not evidence)

- The passive-first hardware research programme (register change
  discipline; gates H1–H4) now starts from an evidenced legacy-family
  physical-layer model rather than a blank hypothesis.
- External power for any future SmartLinq device is reinforced as the
  default assumption; bus power is not to be relied upon.
- Bench validation must characterise attachment loading before any
  live-system consideration; "passive" is not the same as electrically
  non-invasive.

## Evidence gaps

Touch-generation captures; any system with an N-BW2 present; multi-zone,
add-on-cooling, and evaporative variants; tolerance/termination/loading
envelopes; official confirmation of the redistributed manual's provenance;
any official protocol documentation.

## Future validation gates

Unchanged from the register and ADR: bench-owned compatible equipment (H1);
a separately approved, electrically safe, isolated passive-observation plan
(H2); correlation of observed bus behaviour with known N-BW2 API state,
without transmission (H3); feasibility decision (H4). Nothing in this
review authorises code, hardware, commands, keepalives, UDP, discovery, or
live-network or live-bus activity.
