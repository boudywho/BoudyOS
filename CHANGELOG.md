# Changelog

## Unreleased — uninterrupted backups

- Backups no longer stop or restart the Telegram workspace. SQLite sessions
  use online snapshots with integrity checks; Redis keeps its native snapshot.
- Keep only the newest three encrypted backup/signature pairs.
- Ignore zero/empty log-channel placeholders instead of overwriting saved groups.
- Verified a production encrypted backup and restore inventory with the same
  running BoudyOS PID. Existing backup history was cleared at the owner's request.
- Legacy divergent GitHub branches remain separate: their incompatible loader,
  dependency, and architecture changes need selective review rather than blanket
  merging. This fix is integrated into main independently.

## Unreleased — canonical service name

- Added a root-only, dry-runnable, idempotent migration from
  `ultroid.service` to the canonical `boudyos.service`, with exact unit/drop-in
  preservation, atomic selector rewrites, fresh PID-correlated readiness and
  health verification, enabled-state preservation, and verified rollback to
  the restarted legacy service.
- Kept the `ultroid` Unix account and state, `/opt/ultroid`, existing runtime
  and environment values, Telegram identifiers, and `ultroid-redis.service`
  unchanged as compatibility surfaces.

## BoudyOS 2.2.6 — self-userbot text wizard

- Added a user-account-only numbered `.yt` wizard with no assistant-bot
  dependency.

## BoudyOS 2.2.5 — Python launcher module-mode fix

- Signaled module-mode startup before loading `pyUltroid`, preserving the
  launcher's writable-work exclusion while restoring managed activation.

## BoudyOS 2.2.4 — deployment preflight classifier fix

- Limited preflight shell syntax checks to executable files with shell shebangs,
  excluding the Python launcher from `bash -n` validation.

## BoudyOS 2.2.3 — UI and media workflow polish

- Polished BoudyOS UI and branding, removed inline YouTube search, and added a
  Telethon-native self-userbot `yt` media workflow with quality and timestamp
  selection, cleanup, and cancellation.

## BoudyOS 2.2.2 — Python 3.10 safe-path compatibility

- Replaced the Python 3.11-only `-P` service flag with an immutable launcher
  compatible with Python 3.10. The launcher removes the writable work directory
  from `sys.path`, pins imports to the root-owned release, and disables bytecode
  writes without weakening the managed runtime boundary.

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
