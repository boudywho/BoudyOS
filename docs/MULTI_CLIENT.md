# Independent BoudyOS clients

Prefer one managed systemd deployment per Telegram account in production.
The compatibility launcher `python multi_client.py` supports the primary
`API_ID`, `API_HASH`, `SESSION` and suffixed `API_ID1`/`API_HASH1`/`SESSION1`
through suffix `5`. Secrets are passed through child environments, never argv.

Each extra client requires an existing, separate `BOUDYOS_CLIENT_WORK<n>`
directory and its own suffixed `REDIS_URI<n>`, `MONGO_URI<n>`, or
`DATABASE_URL<n>`. Set its corresponding password/token/log-group variables
with the same suffix. Do not point two clients at the same database:
OWNER_ID, BOT_TOKEN, group IDs and configuration are account-specific.

The launcher validates all clients before starting any, waits for children,
and terminates/reaps them when interrupted. It does not provision directories
or databases. Use different Telegram sessions and keep each workspace private.
