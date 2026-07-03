"""Rinnai Touch: local-only Home Assistant integration (offline scaffold).

This package is intentionally inert at this milestone. Importing it must have
no side effects: no connections, no I/O, and no Home Assistant imports.

Home Assistant setup hooks (``async_setup_entry`` / ``async_unload_entry``)
are added in a later approved milestone together with the client and
coordinator, per AGENT_SCOPE.md. Adding a partial setup hook now would invent
incomplete runtime behaviour, so this module stays a documented placeholder
that only establishes the package boundary for tests and tooling.
"""
