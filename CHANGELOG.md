# Changelog

## BoudyOS 2.2.1 — legacy migration readiness

- Corrected the migration `prepare` and legacy rollback gates for installations
  running BoudyOS 2.1/legacy Ultroid, which predate the 2.2 readiness heartbeat.
- Legacy resume now requires a replaced nonzero systemd MainPID to remain
  active and unchanged for a bounded grace interval; managed 2.2 activation
  and rollback still require the fresh PID-correlated heartbeat.
- Repeated `prepare` validates and reuses an exact protected preparation record
  instead of stopping the legacy service or creating an ambiguous snapshot.

## BoudyOS 2.2.0 — security and reliability

- Native activation now uses one atomic commit-workspace selector for immutable
  source plus writable work, verifies stopped/replaced processes around every
  transition, serializes deploy/rollback/migration, and restores legacy backup
  mode and configuration during migration rollback.

### Security

- Removed generic data/calculator/NIGHT_TIME `eval()` paths. Legacy Python
  literals remain data-only through `ast.literal_eval`.
- Added a bounded arithmetic evaluator and made owner Python execution an
  explicit `ALLOW_DANGEROUS_DEV_EXEC` opt-in, unavailable to sudo users.
- Added argv-only bounded subprocess, workspace-path, and safe archive APIs;
  migrated media, archive, upload, move, and delete operations away from shell
  interpolation.
- Disabled raw URL add-on execution by default. Trusted registry installs now
  enforce HTTPS source policy, full immutable revisions, SHA-256, size/time
  limits, valid Python syntax, atomic replacement, and rollback.
- Replaced in-bot pull/reset/pip behavior with approved BoudyOS-origin
  pinned tag+commit checks and a short root-owned deployment request.

### Reliability and operations

- Added exact-tag detached deployment, immutable source plus writable runtime
  copies, verified rollback, PID-correlated readiness heartbeats, HMAC-authenticated
  age backups, exact restore manifests, health probing, and narrow sudoers.
- Added backward-compatible plugin profiles. Existing installs retain the old
  all-plugin default; new installs start with `core,media`.
- Added dashboard version/uptime/plugin/update/Redis/assistant/backup/health
  summaries using bounded, allowlisted status data.
- Restored Telethon-Patch at immutable commit `369fa3266c8a9c9aefb4a6c5608e8d44c09c7087`.
- Split optional dependencies, added direct-pin Python 3.10/3.13 constraints, stopped the
  default container from installing every integration, and removed the legacy
  Pydantic 1.8.2 Instagram fork conflict.
- Replaced auto-committing workflows with read-only CI, pinned Actions,
  CodeQL least permissions, and grouped Dependabot updates.
- Added the tested `ultroid` / `ultroid.service` / `/opt/ultroid` /
  `/etc/ultroid/ultroid.env` migration and retained rollback snapshot path.

### Compatibility

Telegram command names and callback data, session formats, environment and
database keys, `pyUltroid`, `UltroidClient`, the AGPL/upstream provenance, and
BoudyOS assets remain compatible. The upstream py-Ultroid version remains
`2026.04.03`; the BoudyOS product version is `2.2.0`.

## BoudyOS 2.1.2

Production baseline: commit `5a7f41f`.
