"""Regression coverage for backups that leave the Telegram client running."""
import ast
import importlib.util
import os
import sqlite3
import tempfile
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('live_ops', ROOT / 'ops/boudyos_ops.py')
ops = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ops)


class LiveBackupTests(unittest.TestCase):
    def test_wal_session_snapshot_includes_committed_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'sessions'
            source.mkdir()
            with sqlite3.connect(source / 'asst.session') as db:
                db.execute('PRAGMA journal_mode=WAL')
                db.execute('CREATE TABLE state (value TEXT)')
                db.execute("INSERT INTO state VALUES ('saved-session')")
                db.commit()
                target = ops.copy_regular_source(source, root / 'backup')
                with sqlite3.connect(target / 'asst.session') as saved:
                    self.assertEqual(saved.execute('SELECT value FROM state').fetchall(), [('saved-session',)])
                    self.assertEqual(saved.execute('PRAGMA integrity_check').fetchone(), ('ok',))
                self.assertFalse((target / 'asst.session-wal').exists())
                self.assertFalse((target / 'asst.session-shm').exists())

    def test_snapshot_rejects_symlink_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outside = root / 'outside.session'
            with sqlite3.connect(outside) as db:
                db.execute('CREATE TABLE secret (value TEXT)')
            source = root / 'asst.session'
            source.symlink_to(outside)
            with self.assertRaises((ValueError, OSError)):
                ops.copy_live_file(source, root / 'snapshot')
            self.assertFalse((root / 'snapshot').exists())

    def test_sqlite_source_swap_before_native_open_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'asst.session'
            outside = root / 'outside.session'
            for path in (source, outside):
                with sqlite3.connect(path) as db:
                    db.execute('CREATE TABLE state (value TEXT)')
            run = ops.subprocess.run
            def swap_then_open(*args, **kwargs):
                source.unlink()
                source.symlink_to(outside)
                return run(*args, **kwargs)
            with patch.object(ops.subprocess, 'run', swap_then_open):
                with self.assertRaises(ops.subprocess.CalledProcessError):
                    ops.copy_live_file(source, root / 'snapshot')
            self.assertFalse((root / 'snapshot').exists())

    def test_wal_cleanup_during_walk_does_not_abort_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'sessions'
            source.mkdir()
            db = sqlite3.connect(source / 'asst.session')
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('CREATE TABLE state (value TEXT)')
            db.commit()
            walk = os.walk
            def close_after_listing(*args, **kwargs):
                for entry in walk(*args, **kwargs):
                    db.close()
                    yield entry
            with patch.object(ops.os, 'walk', close_after_listing):
                target = ops.copy_regular_source(source, root / 'backup')
            with sqlite3.connect(target / 'asst.session') as saved:
                self.assertEqual(saved.execute('PRAGMA integrity_check').fetchone(), ('ok',))

    def test_rotation_keeps_only_three_newest_archives(self):
        paths = [Path(f'boudyos-2026100{day}T000000Z.tar.age') for day in range(1, 9)]
        self.assertEqual(ops.rotation_keep(paths, now=datetime(2026, 10, 9, tzinfo=timezone.utc)), paths[-1:-4:-1])

    def test_zero_log_channel_does_not_replace_saved_group(self):
        # Execute the actual startup function without importing Telegram clients.
        tree = ast.parse((ROOT / 'pyUltroid/startup/funcs.py').read_text())
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'update_envs')
        class Database:
            def __init__(self):
                self.data = {'LOG_CHANNEL': -1001234567890}
            def keys(self):
                return list(self.data)
            def set_key(self, key, value):
                self.data[key] = value
        db = Database()
        parent = types.ModuleType('startup_fixture')
        parent.udB = db
        namespace = {'__package__': 'startup_fixture.startup', 'os': os,
                     'config': types.SimpleNamespace(_find_file=lambda _: None)}
        with patch.dict('sys.modules', {'startup_fixture': parent}), patch.dict(os.environ, {'LOG_CHANNEL': '0'}, clear=True):
            exec(compile(ast.Module(body=[function], type_ignores=[]), '<startup>', 'exec'), namespace)
            namespace['update_envs']()
        self.assertEqual(db.data['LOG_CHANNEL'], -1001234567890)


if __name__ == '__main__':
    unittest.main()
