# Release Checklist

A short, maintainer-facing checklist for cutting a routine release of this
passive/read-only integration. This is a hygiene checklist, not a
substitute for the approval gates that already govern any change to
runtime behaviour — nothing here authorises a runtime, protocol, or
parameter change on its own.

## 1. Pre-release repository checks

- [ ] `main` and `origin/main` point at the same commit
- [ ] the tracked working tree is clean (`git status --short` shows no
      tracked changes)
- [ ] if the known pre-existing unrelated untracked file
      (`reference_data/deep-research-report.md`) is present, it is left
      untouched — it is not part of any release
- [ ] the target commit hash for the release is confirmed and recorded
- [ ] the diff for a docs-only release commit is checked directly, to
      confirm no runtime or code change was accidentally included
- [ ] `pytest`, `ruff check .`, and `mypy custom_components tests` are
      green if the release includes any code change; for a docs-only
      release, confirm no code changed instead of re-running the suite
      unnecessarily

## 2. Version consistency

- [ ] `custom_components/rinnai_touch/manifest.json`'s `"version"` matches
      the intended release version
- [ ] `pyproject.toml`'s `version` matches the same value
- [ ] both fields move together for a release commit — never one without
      the other
- [ ] version numbers are not bumped in unrelated documentation-only
      commits unless that commit is explicitly part of the release itself

## 3. Documentation and evidence consistency

- [ ] README operator guidance describes what has actually been validated
      and does not overclaim compatibility beyond it
- [ ] `docs/protocol_assumptions.md` remains the single evidence source of
      truth — release notes summarise it, they do not introduce new claims
      that aren't there
- [ ] Gate D soak evidence is described as one-installation validation on
      one N-BW2 module, not general compatibility proof
- [ ] ledger item A11 is stated as Unknown unless a separately approved,
      separately documented outbound experiment has changed it
- [ ] no release describes outbound keepalive, polling, acknowledgement,
      command, or session-maintenance traffic as validated — passive
      releases validate passive recycle only

## 4. Tag and release flow

- [ ] the release commit is pushed to `main` and matches `origin/main`
      before any tag is created
- [ ] the annotated tag is created only after that push, never before
- [ ] the tag name matches the manifest/pyproject version, e.g. `v0.1.0`
- [ ] the tag points at the exact release commit — not a later or earlier
      one
- [ ] the GitHub release title follows the format
      `vX.Y.Z - Short Release Name`
- [ ] the release notes include: highlights; a field-validation summary;
      important limits; an explicit passive/read-only statement; an
      explicit no-outbound-traffic statement; an explicit statement that
      this is not a climate-control integration

This checklist describes the flow; it does not perform it. Creating or
pushing a tag or a GitHub release is a separate, explicit maintainer
action, taken outside of and after this checklist.

## 5. HACS post-release smoke check

- [ ] confirm HACS sees the new release
- [ ] update/download the release through HACS
- [ ] restart Home Assistant
- [ ] observe one or two idle-timeout recycle cycles only — this is a
      smoke check, not a new soak
- [ ] confirm the stream resumes and the first valid frame arrives after
      each recycle
- [ ] confirm data freshness stays fresh across the cycle
- [ ] confirm no refused sessions or frameless sessions occur during the
      check
- [ ] turn debug logging back down once the check is done

## 6. Kill-switch / rollback guidance

- [ ] disable the config entry if repeated refused-connection sessions
      occur
- [ ] disable if repeated frameless sessions occur
- [ ] disable if stale data persists
- [ ] disable if any HVAC, controller, or fault anomaly plausibly
      correlates with the integration
- [ ] do not repeatedly reload or re-enable the integration during a
      refused-connection or listener-failure condition
- [ ] to roll back, reinstall a prior HACS release/tag rather than leaving
      a broken release running

## 7. What must not be bundled into routine releases

A routine release never includes:

- [ ] a climate platform
- [ ] control entities of any kind
- [ ] Home Assistant services
- [ ] outbound traffic of any kind
- [ ] timing or parameter tuning (recycle threshold, reconnect delay,
      freshness threshold, backoff schedule)
- [ ] discovery or multi-client behaviour changes
- [ ] protocol expansion beyond what is already validated
- [ ] Networker bus hardware claims
- [ ] Gate E work

## 8. Gate E boundary

- [ ] Gate E is not part of normal release hygiene and is not implied by
      cutting a release
- [ ] Gate E is outbound session-maintenance planning only, unless
      separately approved
- [ ] any Gate E work starts from ledger item A11 Unknown, not from an
      assumption that any form is safe
- [ ] any Gate E implementation must be separately planned, reviewed,
      instrumented, and approved before live use
- [ ] passive recycle remains the validated fallback unless future
      evidence says otherwise
