# Ultroid - UserBot
# Copyright (C) 2021-2026 TeamUltroid
"""Supervise independent clients; credentials never appear in process arguments."""
import os
from pathlib import Path
import signal
import subprocess
import sys

_AUTH = ('API_ID', 'API_HASH', 'SESSION')
_SOURCE = Path(__file__).resolve().parent


def _client_env(suffix):
    values = [os.environ.get(key + suffix) for key in _AUTH]
    return values if all(values) else None


def main():
    clients = []
    workspaces = set()
    databases = set()
    for suffix in ('', '1', '2', '3', '4', '5'):
        auth = _client_env(suffix)
        if not auth:
            continue
        work = os.environ.get('BOUDYOS_CLIENT_WORK' + suffix)
        work = Path(work).resolve() if work else (Path.cwd() if not suffix else None)
        if work is None or not work.is_dir() or work in workspaces:
            print('Each extra client requires its own existing BOUDYOS_CLIENT_WORK<n> directory.')
            return 1
        env = {key: value for key, value in os.environ.items()
               if not any(key == base + number for base in (*_AUTH, 'BOT_TOKEN', 'LOG_CHANNEL', 'REDIS_URI', 'REDIS_PASSWORD', 'REDIS_URL', 'REDISHOST', 'REDISPORT', 'REDISPASSWORD', 'REDISUSER', 'MONGO_URI', 'DATABASE_URL')
                          for number in ('', '1', '2', '3', '4', '5'))}
        env.update(dict(zip(_AUTH, auth)))
        for key in ('BOT_TOKEN', 'LOG_CHANNEL', 'REDIS_URI', 'REDIS_PASSWORD', 'MONGO_URI', 'DATABASE_URL'):
            value = os.environ.get(key + suffix)
            if value:
                env[key] = value
        redis_uri = os.environ.get('REDIS_URI' + suffix) or os.environ.get('REDIS_URL' + suffix)
        redis_host = os.environ.get('REDISHOST' + suffix)
        if not redis_uri and redis_host:
            redis_uri = redis_host + ':' + os.environ.get('REDISPORT' + suffix, '6379')
        if redis_uri:
            env['REDIS_URI'] = redis_uri
        password = os.environ.get('REDIS_PASSWORD' + suffix) or os.environ.get('REDISPASSWORD' + suffix)
        if password:
            env['REDIS_PASSWORD'] = password
        # Do not silently share account settings/OWNER_ID/BOT_TOKEN across clients.
        remote = next(((key, env[key]) for key in ('REDIS_URI', 'MONGO_URI', 'DATABASE_URL') if env.get(key)), None)
        if suffix and remote is None:
            print('Extra clients require a distinct suffixed database configuration.')
            return 1
        if remote is not None and remote in databases:
            print('Clients must not share a remote database.')
            return 1
        databases.add(remote)
        workspaces.add(work)
        env['PYTHONPATH'] = str(_SOURCE)
        clients.append((env, str(work)))
    if not clients:
        print('No complete client credentials found; set API_ID, API_HASH, SESSION.')
        return 1
    children = []
    old_handler = signal.getsignal(signal.SIGTERM)
    def terminate(signum, frame):
        raise KeyboardInterrupt
    try:
        signal.signal(signal.SIGTERM, terminate)
        for env, work in clients:
            children.append(subprocess.Popen([sys.executable, '-m', 'pyUltroid'], env=env, cwd=work))
        return max((child.wait() for child in children), default=0)
    except KeyboardInterrupt:
        return 130
    finally:
        signal.signal(signal.SIGTERM, old_handler)
        for child in children:
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()


if __name__ == '__main__':
    raise SystemExit(main())
