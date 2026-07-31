# Architecture and security boundaries

BoudyOS retains the `pyUltroid` package, `UltroidClient`, Telegram decorators,
database abstraction, assistant callbacks, and upstream plugin layout. The
BoudyOS layer adds small stdlib-first policy modules under
`pyUltroid/security/`: parsing, arithmetic, subprocesses, paths/archives,
add-ons, updater policy, profiles, and sanitized status.

Trust boundaries:

- Telegram content, downloaded filenames, URLs, add-on bytes, database values,
  archives, and status files are untrusted.
- The bot process has account/session access and is not a deployment authority.
- The root helper accepts only the approved BoudyOS origin and a root-pinned
  release tag plus full commit, fetches the exact tag ref, checks its peeled
  commit and forward ancestry, stages a fresh venv, and activates transactionally.
- TeamUltroid/Ultroid is preserved as upstream provenance and a reviewed sync
  source, never as the in-app deployment target.
- Trusted add-ons remain privileged in-process Python. Verification is supply
  chain integrity, not sandboxing.

The subprocess boundary accepts argument vectors, caps runtime/output, and
returns structured results. The archive boundary rejects absolute paths,
parent traversal, links, devices, and destinations outside the runtime
workspace before extraction.

Verified Git source and its virtual environment stay root-owned under
`/opt/boudyos/releases`. Every commit-named workspace is root-owned and
contains an exact root-owned `source` link to its same-commit release plus a
service-owned `work/` directory. Systemd executes `current/source` with
safe-path Python and uses `current/work` as cwd, so the one root-controlled
`/var/lib/boudyos/current` replacement selects code and state atomically.
Official plugin/help/assistant discovery and
trusted registry lookup derive paths from module location, never cwd.
Writable add-ons and state stay in `work/`; bundled assets are addressed
directly from immutable source. Deployment and health verify source and
workspace ownership, modes, exact selector shape, and the absence of
service-replaceable official selectors.

Readiness is a JSON heartbeat containing the application PID and timestamp.
Deploy and health checks require the service `MainPID`, a post-start timestamp,
and a marker no older than 45 seconds. Root deploy/update/backup/health/release
truth lives in a root-owned, non-service-writable `BOUDYOS_STATUS_DIR`.
Service-produced reports use a separate `BOUDYOS_APP_STATUS_DIR`; root health
does not trust it. Both surfaces use bounded schemas, fixed messages, and no
credentials, private identifiers, tracebacks, or private filesystem paths.
