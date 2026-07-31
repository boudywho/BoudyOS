# BoudyOS operations runbook

## Profiles and dependency constraints

`PLUGIN_PROFILES` accepts `core`, `media`, `admin`, `automation`, `developer`,
and `experimental`. Every loadable file under `plugins/` belongs to exactly one
profile; assistant modules are separate and assistant `games` follows
`experimental`.

New provisioning writes:

```text
PLUGIN_PROFILES=core,media
PLUGIN_PROFILE_POLICY=new-safe-v1
```

An upgraded database with no profile or policy marker is explicitly migrated
to `legacy-all-v1`; this is independent of `INIT_DEPLOY` and `LOG_OFF`.

`requirements/database.txt` contains the Redis/hiredis, MongoDB, and PostgreSQL
drivers required by the documented startup configurations and is included by
the default media profile. Optional Google, Instagram, X, and Heroku clients
remain outside that default. `constraints/py310.txt` and
`constraints/py313.txt` are tested direct pins for core/media/database, not
complete transitive hash locks. CPython 3.10–3.12 uses the
py310 set; 3.13+ uses py313. Every installer supplies its matching constraint
and runs `pip check`. Telethon-Patch is a VCS requirement fixed at commit
`369fa3266c8a9c9aefb4a6c5608e8d44c09c7087`. Some vulnerability tools cannot
map a VCS distribution reliably to advisory databases, so CI audits the
installed environment and this VCS result must be reviewed separately.

## Transactional releases

Install the helper root-owned and non-group/world-writable. Before enabling or
starting any BoudyOS unit, install and run the path provisioner:

```bash
install -d -o root -g root -m 0755 /usr/local/lib/boudyos
install -o root -g root -m 0644 ops/boudyos_ops.py \
  /usr/local/lib/boudyos/boudyos_ops.py
install -o root -g root -m 0644 ops/tmpfiles.d/boudyos.conf \
  /usr/lib/tmpfiles.d/boudyos.conf
install -o root -g root -m 0644 ops/systemd/boudyos-paths.service \
  /etc/systemd/system/boudyos-paths.service
systemd-tmpfiles --create /usr/lib/tmpfiles.d/boudyos.conf
systemctl daemon-reload
systemctl enable boudyos-paths.service
```

The prerequisite deterministically creates `/opt/boudyos`,
`/var/lib/boudyos`, `/var/lib/boudyos/status`, `/run/boudyos`,
`/run/lock/boudyos`, and `/var/backups/boudyos` before protected service
namespaces are built.
Application units then use `RuntimeDirectory=` and `StateDirectory=` to apply
the selected service account to `/run/boudyos` and
`/var/lib/boudyos/app-status`. Deploy applies the configured runtime group to
the root-owned workspace selectors, while status truth remains root-owned and
service non-writable.

Install the remaining path and service units, then validate the exact sudoers
file with `visudo -cf`.
Telegram is allowed only:

```text
/usr/local/sbin/boudyos-deploy request --non-interactive
```

The short action validates root configuration, atomically replaces
`/var/lib/boudyos/deploy.request`, and exits. The path unit starts the long
root `deploy` action. The root update check publishes the configured target
tag and commit in the sanitized shared status directory; the bot compares its
active immutable metadata with that target and never reads the root config.

Copy `ops/config/deploy.conf.example` to `/etc/boudyos/deploy.conf` as
root:root 0640. Replace the documented zero placeholder. Real
`check`, `preflight`, `request`, and `deploy` fail closed unless both values are
present and the commit is nonzero 40-hex:

```text
BOUDYOS_RELEASE_TAG=v2.2.0
BOUDYOS_RELEASE_COMMIT=<exact 40-hex peeled tag commit>
```

`check` and `deploy` fetch only
`+refs/tags/$BOUDYOS_RELEASE_TAG:refs/tags/$BOUDYOS_RELEASE_TAG`, compare the
peeled tag to the pin, verify the approved origin, refuse downgrade/unrelated
history, and use detached `HEAD`. Deployment builds a fresh venv, runs unit,
compile, import, JSON/YAML, shell, diff, and `pip check` preflight. An existing
target directory is quarantined and replaced; it is never silently reused.

Immutable source and `.venv` remain root-owned under `/opt/boudyos/releases`.
Each `/var/lib/boudyos/workspaces/<40-hex-commit>` is root-owned 0750 and
contains exactly a root-owned `source` symlink to
`/opt/boudyos/releases/<same-commit>` plus a service-owned 0700 `work/`.
Systemd uses `current/work` as `WorkingDirectory`, starts
`current/source/.venv/bin/python` with safe-path mode, and sets `PYTHONPATH` to
`current/source`. The single atomic `/var/lib/boudyos/current` replacement
therefore selects immutable code and writable state together. The process
therefore imports `pyUltroid`, official `plugins`, `assistant`, and `strings`
directly from the immutable release even if a namesake appears in writable
state.

`work/` contains writable add-ons, downloads, sessions, databases, logs,
temporary files, VCBot state, and `resources/{auth,auths,downloads}`. Bundled
images/fonts and the trusted add-on registry are addressed from source
constants derived from module location. The unit makes the workspace selector
and workspace root read-only and allowlists only `current/work`, `/run/boudyos`,
and app status as writable. Prior mutable state is validated as regular,
link-free content and copied into the new `work/`; official source is never
copied there. This preserves relative media and command output.

Before every start the helper removes the readiness marker. Start, stop, link,
or readiness failure enters rollback. Rollback is reported successful only
after the previous service is active with a fresh PID-correlated heartbeat
and its exact tag plus full commit have been derived from the retained
immutable release and atomically republished. The configured newer target
remains `available` after a rollback. Release and workspace ownership, modes,
shape, and absence of writable official selectors are validated before the
link switch and again before service start. An invalid retained target is
refused and never executed.

## Authenticated encrypted backup

Install `age`. Provision at least 32 random bytes as root:root 0600 at the
configured `HMAC_KEY_FILE`, separate from backups and the age identity, for
example:

```bash
install -d -m 0700 /etc/boudyos
python3 /usr/local/lib/boudyos/boudyos_ops.py ensure-hmac-key \
  /etc/boudyos/backup-auth.key
```

Configure the public `AGE_RECIPIENT`, root-readable allowlist, native Redis
connection, age identity path, HMAC key path, and quiesce service. The bot
service is stopped briefly while allowlisted local files/directories are
copied; symlink or special-file sources fail. Redis is exported with
`redis-cli --rdb`, not copied while live.

The supplied allowlist names `/var/lib/boudyos/current`. The root backup helper
accepts that one activation symlink only when it resolves directly to
`/var/lib/boudyos/workspaces/<40-hex-commit>`. It requires the workspace to
contain the exact root-owned `source` link and `work/`, copies only real mutable
state from `work/`, rejects every other link or special entry, and does not
traverse historic workspaces or immutable source. Backup status includes only
the sanitized `managed` or `legacy` mode, never a source path.
In legacy mode the allowlist names `/opt/ultroid`, but the helper copies only
its session/database/add-on/auth/download/log mutable set; executable code and
virtual-environment links are not archived as mutable state.

The manifest is an exact regular-file inventory excluding only manifest
metadata. Verification checks path, size, mode, SHA-256, missing and extra
files, and rejects links/devices/FIFOs. The encrypted ciphertext receives a
detached HMAC-SHA256 sidecar. Restore verification authenticates ciphertext
before age decrypts or tar parsing begins. The HMAC key is read from its file,
never placed in arguments or logs. There is no plaintext fallback.

Rotation keeps 7 daily, 4 weekly, and 3 monthly archive/signature pairs.
`boudyos-restore-verify` uses a private temporary directory and never writes
production.

## Health, readiness, and status

The application writes readiness after initialization even with `LOG_OFF` and
refreshes it every 15 seconds. Deploy and health default to a 45-second maximum
age and require the marker PID to equal systemd `MainPID`.

Set `BOUDYOS_STATUS_DIR=/var/lib/boudyos/status` as the root-owned truth
directory and `BOUDYOS_APP_STATUS_DIR=/var/lib/boudyos/app-status` as the
service-owned output directory. Root truth is root-owned, group-readable where
the dashboard needs it, and never group-writable: directories are 0750,
sanitized dashboard files are 0640, and private alert state is 0600. The bot
unit mounts root truth read-only and cannot replace it; app-side update reports
go only to `app-status`. Root health never reads app-owned status.

Health covers service/restarts, readiness, Redis, disk, memory, immutable
source ownership, exact workspace/work layout, backup freshness, and update
freshness. Alert cooldown advances
only after a successful Telegram response; failure is recorded only as the
fixed sanitized state `alert delivery failed`.

Review:

```bash
systemctl status boudyos.service boudyos-deploy.path \
  boudyos-health.timer boudyos-backup.timer
/usr/local/sbin/boudyos-deploy status
journalctl -u boudyos.service --since today
```

Never share raw configuration, exceptions, paths, URLs, chat IDs, or logs.

## Release verification

Before handoff run the commands listed in `MIGRATION.md`, including both Python
versions, JSON/YAML parsing, ShellCheck, Docker exact-source smoke tests when
the registry/network is available, `git diff --check`, and the AST/grep safety
checks in `scripts/quality_checks.py`.

## Upstream sync

Fetch TeamUltroid as a separate upstream, review its range, and preserve AGPL
headers and internal identifiers, callback data, session formats, database
keys, and environment contracts. Upstream is never an in-app deploy target.
