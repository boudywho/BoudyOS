# BoudyOS security policy

## Reporting

Do not open a public issue containing session strings, bot tokens, database
credentials, private chat identifiers, logs, or exploit details. Use the
repository's private security-reporting channel when enabled by the maintainer.
If private reporting is unavailable, open a minimal issue asking Hermes for a
private contact route.

Supported security releases are the current BoudyOS 2.x release and the
immediately previous 2.x release during its migration window.

## Dangerous owner capabilities

The `.eval` and `.bash` commands execute with full account/process authority.
Both require the explicit `developer` profile,
`ALLOW_DANGEROUS_DEV_EXEC=true`, and owner identity; sudo users cannot invoke
them. Shell timeout kills and reaps the whole process group. Prefer
`core,media` and do not enable `developer` on unattended accounts.

## Add-on trust model

Python add-ons execute in-process. They can read messages, act as the Telegram
account, access the configured database, and inspect process memory. Hash and
source verification prove which bytes were installed; static syntax validation
does **not** make an add-on safe.

`.getaddons trusted <name>` installs only a bundled registry entry pinned to a
full commit and SHA-256. The bundled registry may be empty until Hermes reviews
and publishes entries. Legacy `.getaddons raw <https-url.py> CONFIRM` additionally
requires `ALLOW_UNTRUSTED_PLUGINS=true`; it is deliberately labeled untrusted.
Attachment `.install`, raw URL, plugin-channel, and unverified local `.load`
paths are owner-only and require `ALLOW_UNTRUSTED_PLUGINS=true`. Startup loads
registry-pinned local files only when their SHA-256 still matches; other local
add-ons require the same opt-in. Source URLs/query strings are not logged.

## Update boundary

Telegram compares active immutable metadata with the root-configured tag and
full commit. It may invoke only the short root `request` action; systemd runs
the long deploy. The helper fetches the exact tag ref, verifies the peeled
commit and forward ancestry, and rejects downgrade/unrelated history.
TeamUltroid remains provenance/sync only.

Backups use age encryption plus detached HMAC-SHA256 over ciphertext with a
separate root-only random key. Authentication occurs before decrypt/extract.
The exact manifest rejects missing/extra/non-regular content and mode, size, or
digest changes.

## Secrets

Never commit `.env`, sessions, age identities, private keys, database exports,
status files, or backups. Rotate a secret immediately if it appears in a log or
commit. Operational status is allowlisted and must not include URLs,
credentials, identifiers, paths, or raw exceptions.
