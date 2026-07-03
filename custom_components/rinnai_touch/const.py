"""Constants for the Rinnai Touch integration.

Only offline-safe values live here: identifiers, configuration keys, the
timing values approved in AGENT_SCOPE.md, and stable protocol constants
supported by docs/protocol_assumptions.md. Anything that frames messages,
manages connections, or implements the transport keepalive belongs to later
approved milestones (protocol.py, client.py).
"""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "rinnai_touch"

# Configuration entry keys. The config flow itself arrives in a later
# milestone; the key names are fixed early because entity unique IDs and
# stored entries must stay stable (docs/entity_model.md).
CONF_HOST: Final = "host"
CONF_PORT: Final = "port"
CONF_NAME: Final = "name"

# Default TCP port observed for Rinnai Touch WiFi modules (AGENT_SCOPE.md,
# "TCP Transport").
DEFAULT_TCP_PORT: Final = 27847

# Approved connection timing values (AGENT_SCOPE.md, "Connection
# Requirements"). COMMAND_ACK_TIMEOUT_SECONDS is reserved for Phase 2; no
# command implementation exists in Phase 1.
CONNECT_TIMEOUT_SECONDS: Final = 10
COMMAND_ACK_TIMEOUT_SECONDS: Final = 15
STALE_STATUS_THRESHOLD_SECONDS: Final = 180
RECONNECT_BACKOFF_SCHEDULE_SECONDS: Final = (2, 5, 10, 30, 60)

# Minimum spacing of the Phase 1 transport keepalive (AGENT_SCOPE.md,
# "Transport Keepalive Policy"). The keepalive itself is not implemented in
# this milestone.
KEEPALIVE_MIN_SPACING_SECONDS: Final = 60

# Stable protocol facts supported by docs/protocol_assumptions.md.
MESSAGE_PREFIX: Final = "N"
SEQUENCE_DIGITS: Final = 6
SEQUENCE_MODULO: Final = 255
ZONE_LETTERS: Final = ("U", "A", "B", "C", "D")

# Measured-temperature sentinel meaning "no valid reading" (MT=999). Kept as
# a string because the protocol carries it as text.
MT_NO_READING: Final = "999"
