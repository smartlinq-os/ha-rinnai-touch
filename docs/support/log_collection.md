# Log Collection Guide

This guide explains how to collect and sanitise logs from the Rinnai Touch
integration before opening a bug report or a field validation report. It is
written for anyone reporting an issue or contributing controlled field
evidence — not for developers debugging the integration's own code.

The integration is **passive and read-only**. It never sends a command,
acknowledgement, polling request, or keepalive/session-maintenance byte to
the module. Everything below is about *watching* the integration, never
about sending anything to it yourself.

## What logs are useful

Lines from the integration's own loggers:

- `custom_components.rinnai_touch.client` — TCP connection lifecycle,
  session summaries, the passive stale-session recycle, and reconnect
  timing.
- `custom_components.rinnai_touch.coordinator` — data freshness and
  connection-state changes as seen by Home Assistant.

A short excerpt covering one or two full lifecycle cycles (a stream, a
recycle, and a recovery) is far more useful than a large unfiltered log
file.

## What logs are not useful

- Unrelated Home Assistant component or integration log lines.
- A full, unfiltered `home-assistant.log` dump.
- Screenshots of the log viewer that also show unrelated private
  information (see "What to redact" below).
- Raw packet captures or protocol traces of any kind — this project does
  not use them for support, and capturing them yourself requires the same
  care as the project's own passive probe tooling.

## Normal troubleshooting logging

Enable debug logging for the transport client and info logging for the
coordinator:

```yaml
logger:
  default: warning
  logs:
    custom_components.rinnai_touch.client: debug
    custom_components.rinnai_touch.coordinator: info
```

This shows session lifecycle, recycle, and reconnect activity without
flooding the log.

## Deep field debugging (only when specifically requested)

```yaml
logger:
  default: warning
  logs:
    custom_components.rinnai_touch: debug
```

This is noisier: Home Assistant logs a coordinator update for every
accepted status snapshot, which can arrive roughly once per second while
the module is streaming. Only enable this when a maintainer specifically
asks for it, and turn it back down to the normal troubleshooting
configuration afterwards.

## Normal expected passive recycle lifecycle

A healthy session normally looks like this:

1. TCP established
2. HELLO observed
3. First valid frame
4. Normal stream (roughly once-per-second status frames)
5. Idle-timeout recycle (no accepted snapshot for a bounded period)
6. 10-second reconnect delay
7. TCP established
8. First valid frame resumes

Seeing this pattern repeat is expected, not a fault. A brief connectivity
drop around each recycle is normal.

## Useful lifecycle log snippets to collect

Look for lines containing:

- `first valid frame received`
- `no accepted snapshot within the read-idle threshold`
- `session end (phase=` (the per-session summary line)
- `retrying in` (particularly the 10-second delay after a recycle)
- `TCP established`
- a `first valid frame received` line shortly after a reconnect
- any line containing `refused`, `reset`, `remote-eof`, `timeout`,
  `host-unreachable`, or the coordinator's `Status is stale` line

A handful of lines around each of these events, in order, is normally
enough to tell a full story.

## What to redact

Before pasting anything, remove:

- IP addresses
- Ports
- Credentials or Wi-Fi keys
- Tokens
- Device serial numbers
- Household details (room names, occupancy patterns, anything personally
  identifying)
- Raw protocol frames or payloads
- Screenshots that show any of the above, even incidentally

## When to disable the integration

Disable the config entry rather than leaving it running if you see:

- Repeated connection-refused sessions
- Repeated sessions with no valid frame at all
- Persistently stale data that does not clear
- Any HVAC, controller, or fault anomaly that could plausibly relate to the
  integration
- A reconnect loop that keeps needing manual intervention to clear

Collect logs first if you can do so safely, then disable the entry and
report the issue.

## What not to do

- Do not repeatedly reload or re-enable the integration while it is in a
  refused-connection state — this can make the state worse or harder to
  clear.
- Do not run a competing local TCP client (Homebridge, another integration,
  a probe tool) at the same time as validation testing.
- Do not perform packet captures or protocol probing of your own unless it
  has been separately approved for this project.
- Do not send any manual traffic to the module. This integration and this
  guide are both strictly passive.

## Related documentation

- [`README.md`](../../README.md) — general setup and the passive session
  recycle behaviour.
- [`docs/protocol_assumptions.md`](../protocol_assumptions.md) — the full,
  labelled evidence ledger this guide's claims are drawn from.
- Bug report and field validation issue templates, under
  `.github/ISSUE_TEMPLATE/`.
