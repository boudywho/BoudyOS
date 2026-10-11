# BoudyOS branch consolidation — 2026-10-11

## Provenance and decisions

TeamUltroid/Ultroid main was fetched directly at
`edd18d31eae982dff468bd8ce785fbb319e370c3`. It was already an ancestor
of BoudyOS main: no missing upstream-main commits. Branch histories are
reconciled into main, not indiscriminately used to replace newer code.

Every previous origin branch tip is retained under the annotated tag namespace
`archive/consolidation-20261011/<previous-branch-name>` before branch removal.
Only main remains an active origin development branch. Upstream remote refs
are provenance, not BoudyOS development branches.

| History | Resolution |
| --- | --- |
| feature/fixes | Useful fixes were already semantically integrated, including PMPermit, broadcasts, delay-spam, PDF import order, optional timezone and twikit event-loop fixes. Retain modern pypdf, argv subprocesses, pinned audited dependencies, trusted addons and log-group preservation. |
| feature/updates | Tool import/parsing fixes already present; retain newer branding and CI. Do not resurrect deleted inline media/workflows. |
| preview/installation-flow → p1-qol → p2-qol | Merge cumulative chain once. Integrate offline setup/doctor, fail-fast safe config validation, structured loader reports, typed DB settings, official plugin boot controls, supervised isolated multi-client launcher, short FloodWait handling, help suggestions and YAML translation checks. Adapt tests to actual behavior. |
| dev, extension, @stale | Older alternative upstream development histories are superseded by current main. Record historical ancestry with main's content retained. |
| rewrite, v2 | Alternate incompatible database/plugin/web architectures remove large parts of the supported plugin ecosystem. Retain current architecture; merge history as explicitly superseded, not a claim that their alternate features were installed. Archived tags preserve all implementations. |
| 9dejMC0n5KIlnkIw, fix/live-backups | Already contained in main. |

## Security constraints preserved

- No startup git clone/pull/pip installation or arbitrary addon hot-reload.
- Immutable source-root paths, trusted addon registry/hash checks, owner-only
  sensitive controls, constrained readiness heartbeat and external deployment.
- Existing Python 3.10/3.13 profiles and pinned dependency constraints; do not
  replace them with preview mutable Telethon-Patch URLs or duplicate profiles.
- No startup autojoin, unsupported shared-state multiclient configuration,
  secret argv/diagnostic echoes, permissive addon policies or root Docker mounts.
- Daily encrypted backups never restart the service; SQLite online snapshots
  and newest-three retention remain active. Log-channel zero placeholders do
  not overwrite the saved group.

Deployment uses a new tag pinned to the exact tested consolidated main commit.
An upgrade causes one controlled service restart, not a recurring restart.
