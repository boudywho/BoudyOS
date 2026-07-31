# BoudyOS 2.2 migration and rollback

## Existing installations

Before changing units, complete an authenticated encrypted backup and restore
verification. Pin both `v2.2.2` and its exact 40-hex peeled commit in the
root-owned deploy configuration. A placeholder is documentation only and is
rejected by operational actions.

Unset `PLUGIN_PROFILES` never removes commands from an upgraded installation.
The first 2.2 load writes `PLUGIN_PROFILE_POLICY=legacy-all-v1` independently
of `INIT_DEPLOY` and `LOG_OFF`. Only new provisioning writes
`new-safe-v1` with `core,media`.

Leave `ALLOW_DANGEROUS_DEV_EXEC` and `ALLOW_UNTRUSTED_PLUGINS` false. Developer
shell/eval require the `developer` profile, owner identity, and the dangerous
execution opt-in. Attachment, raw URL, plugin-channel, and unverified local
code load paths require owner-controlled untrusted-plugin opt-in.

## Exact legacy production layout

The supported legacy layout is:

```text
user:    ultroid
service: ultroid.service
source:  /opt/ultroid
env:     /etc/ultroid/ultroid.env
```

Use `ops/config/deploy-ultroid.conf.example`,
`ops/config/backup-ultroid.conf.example`,
`ops/config/backup-paths-ultroid.example`,
`ops/config/health-ultroid.conf.example`,
`ops/sudoers/ultroid-boudyos-deploy`, and
`ops/systemd/ultroid-boudyos.conf.example`. Replace the commit placeholder and
validate sudoers before installation. Install
`ops/tmpfiles.d/boudyos.conf` and `ops/systemd/boudyos-paths.service` as
documented in `docs/operations.md`, run `systemd-tmpfiles --create` before any
unit is started, and enable the provisioning service. The legacy drop-in also
uses `RuntimeDirectory=boudyos` and `StateDirectory=boudyos/app-status`, so
systemd deterministically applies `ultroid:ultroid` ownership to those two
writable directories before `ExecStart`.

Run:

```bash
sudo /usr/local/sbin/boudyos-migrate-ultroid plan
sudo /usr/local/sbin/boudyos-migrate-ultroid prepare
sudo /usr/local/sbin/boudyos-deploy check
sudo /usr/local/sbin/boudyos-deploy stage
# Replace the live backup allowlist/config and health config with the managed
# examples (preserving separately provisioned recipient/key values).
sudo /usr/local/sbin/boudyos-migrate-ultroid activate
```

Before `prepare`, install the legacy backup and health examples at their
documented live paths. `prepare` briefly stops `ultroid.service`, creates a
root-only rollback
snapshot under `/var/lib/boudyos/migration-snapshots`, copies the environment
to `/etc/boudyos/runtime.env` with group `ultroid`, creates an
root-owned runtime seed containing an `ultroid`-owned `work/`, and restarts the
legacy unit. The source snapshot, environment, session/local database files,
add-ons, auth, downloads, and external Redis configuration remain available.
Only mutable state is seeded into `work/`; legacy official source files are not
copied into an executable runtime position. It does not delete or rewrite
`/opt/ultroid` or `/etc/ultroid/ultroid.env`.

`stage` builds, preflights, quarantines/replaces any prior target directories,
and prepares a root-owned commit workspace containing an exact root-owned
`source` link and service-owned `work/` state. Official code is executed
through that link; no code selector is placed below writable state. It atomically records the
exact verified source and runtime paths, tag, and full commit in root-owned
mode-0640 staged state.
`activate` rejects linked, traversing, mismatched, or insecure staged state and
refuses to stop the legacy unit until the live backup, allowlist, and health
configuration all target the managed runtime. It
loads the drop-in template only from that exact staged source. It installs the
reviewed drop-in only after those exact tag+commit directories, ownership,
modes, and work layout verify. It repeats validation after the link switch,
before start. It removes stale readiness, switches the existing
`ultroid.service` to immutable BoudyOS code and venv with `work/` as its
writable cwd, and
requires fresh PID-correlated readiness. Failure removes the drop-in and
restarts the original unit.

## Rollback

For a deployed BoudyOS release:

```bash
sudo /usr/local/sbin/boudyos-deploy rollback
```

The helper does not report success until the retained prior release is active
and fresh-ready. It does not rewrite database keys.

For the legacy unit migration:

```bash
sudo /usr/local/sbin/boudyos-migrate-ultroid rollback
```

This verifies a stop before changing anything, removes the managed selectors,
restores the recorded legacy drop-in/backup/allowlist/health configuration,
reloads systemd, and establishes a new ready PID for the original
`ultroid.service`. Backup status is reset to sanitized `legacy` mode so a
managed-workspace backup cannot be reported for the running legacy process;
the root-only snapshot and staged release are retained for safe reactivation.
Verify Redis, session
login, assistant connection, media writes, and a restore drill before removing
any legacy files.

The upstream py-Ultroid version remains `2026.04.03`; BoudyOS is `2.2.2`.
