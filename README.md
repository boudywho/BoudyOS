<p align="center">
  <img src="./resources/extras/boudyos_logo.png" width="280" alt="BoudyOS logo">
</p>

<h1 align="center">BoudyOS</h1>

<p align="center">
  A polished personal Telegram workspace built with Telethon.
</p>

## About

BoudyOS is a personalized public fork of
[TeamUltroid/Ultroid](https://github.com/TeamUltroid/Ultroid). It keeps Ultroid's
plugin ecosystem, deployment model, session format, database contracts, and
upstream-compatible internals while presenting a focused BoudyOS experience.

The `pyUltroid` package, `UltroidClient`, commands, callback data, environment
keys, and database identifiers intentionally retain their upstream names for
compatibility.

## Features

- Dashboard-based help for plugins, add-ons, voice chat, settings, and updates
- Telegram assistant and private log-group integration
- Optional official add-ons and voice-chat components
- Redis, MongoDB, PostgreSQL, and local database support inherited from Ultroid
- Docker, Heroku, Okteto, Termux, and local deployment paths

## Deploy

### Requirements

- Python 3.10 or newer
- Telegram `API_ID`, `API_HASH`, and a user `SESSION`
- One supported database configuration:
  - `REDIS_URI` and `REDIS_PASSWORD`
  - `MONGO_URI`
  - `DATABASE_URL`

Never publish your `.env`, session string, bot token, database credentials, or
generated session files.

### Local

```bash
git clone https://github.com/boudywho/BoudyOS.git
cd BoudyOS
python3 -m venv venv
. venv/bin/activate
pip install -U -r requirements.txt
cp .env.sample .env
```

Fill in `.env`, generate a session with `bash sessiongen` if needed, then run:

```bash
bash startup
```

On Windows, use:

```powershell
python -m pyUltroid
```

### Docker Compose

Create `.env`, then run:

```bash
docker compose up --build -d
```

### Heroku

Review [app.json](./app.json), configure the required variables in Heroku, and
deploy this repository. The application uses the container stack defined by
[heroku.yml](./heroku.yml).

### Okteto

The included [okteto-pipeline.yml](./okteto-pipeline.yml) and
[docker-compose.yml](./docker-compose.yml) use the same environment variables
as local deployment.

## Updates and upstream compatibility

BoudyOS preserves Ultroid's internal update assumptions where practical.
Installations that track an `upstream` Git remote can continue to compare and
pull upstream changes. Review upstream changes before applying them to a
branded deployment.

- BoudyOS source and support:
  [github.com/boudywho/BoudyOS](https://github.com/boudywho/BoudyOS)
- Upstream project:
  [TeamUltroid/Ultroid](https://github.com/TeamUltroid/Ultroid)
- Upstream add-ons:
  [TeamUltroid/UltroidAddons](https://github.com/TeamUltroid/UltroidAddons)

## License and credits

BoudyOS remains licensed under the
[GNU Affero General Public License v3 or later](./LICENSE). Existing copyright
and license headers are preserved.

The core architecture and substantial implementation come from
[TeamUltroid](https://github.com/TeamUltroid/Ultroid) and its contributors.
BoudyOS also inherits work built on
[Telethon](https://github.com/LonamiWebs/Telethon) and
[PyTgCalls](https://github.com/pytgcalls/pytgcalls). See the repository history
for the complete contributor record.
