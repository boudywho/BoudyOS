"""Behavior checks for reconciled preview functionality."""
import importlib.util
import logging
import os
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch, Mock

ROOT = Path(__file__).resolve().parents[1]


def load_file(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MultiClientTests(unittest.TestCase):
    def test_missing_credentials_launches_nothing(self):
        mod = load_file('multi_client_test', 'multi_client.py')
        with patch.dict(os.environ, {}, clear=True), patch.object(mod.subprocess, 'Popen') as launch:
            self.assertEqual(mod.main(), 1)
            launch.assert_not_called()

    def test_secondary_uses_isolated_env_without_secret_arguments(self):
        mod = load_file('multi_client_test', 'multi_client.py')
        with tempfile.TemporaryDirectory() as tmp:
            env = {'API_ID1': '22', 'API_HASH1': 'private-hash', 'SESSION1': 'private-session',
                   'BOUDYOS_CLIENT_WORK1': tmp, 'REDIS_URI1': 'localhost:6381', 'REDIS_PASSWORD1': 'private-password'}
            child = Mock()
            child.wait.return_value = 0
            with patch.dict(os.environ, env, clear=True), patch.object(mod.subprocess, 'Popen', return_value=child) as launch:
                self.assertEqual(mod.main(), 0)
            args, kwargs = launch.call_args
            self.assertEqual(args[0][-2:], ['-m', 'pyUltroid'])
            self.assertNotIn('private-session', args[0])
            self.assertEqual(kwargs['env']['SESSION'], 'private-session')
            self.assertEqual(kwargs['env']['REDIS_URI'], 'localhost:6381')
            self.assertEqual(kwargs['cwd'], tmp)

    def test_secondary_shared_redis_is_rejected(self):
        mod = load_file('multi_client_test', 'multi_client.py')
        env = {'API_ID1': '22', 'API_HASH1': 'hash', 'SESSION1': 'session', 'REDIS_URI': 'localhost:6380'}
        with patch.dict(os.environ, env, clear=True), patch.object(mod.subprocess, 'Popen') as launch:
            self.assertEqual(mod.main(), 1)
            launch.assert_not_called()


class LoaderReportTests(unittest.TestCase):
    def test_real_import_results_are_recorded(self):
        pkg = types.ModuleType('pyUltroid')
        pkg.__path__ = [str(ROOT / 'pyUltroid')]
        pkg.LOGS = logging.getLogger('loader-report-test')
        tools = types.ModuleType('pyUltroid.fns.tools')
        tools.get_all_files = lambda *args: []
        modules = {'pyUltroid': pkg, 'pyUltroid.fns.tools': tools}
        with patch.dict('sys.modules', modules), tempfile.TemporaryDirectory() as tmp:
            loader = load_file('pyUltroid.loader_fixture', 'pyUltroid/loader.py')
            for name in ('good', 'missing', 'broken'):
                (Path(tmp) / f'{name}.py').write_text('')
            def importer(path):
                name = Path(path).stem
                if name == 'missing':
                    raise ModuleNotFoundError('missing optional package', name='optional_pkg')
                if name == 'broken':
                    raise ValueError('invalid plugin')
                return types.ModuleType('good')
            result = loader.Loader(tmp, logger=Mock()).load(func=importer)
            self.assertEqual(result['loaded'], ['good'])
            self.assertEqual(result['missing_deps'], [('missing', 'optional_pkg')])
            self.assertEqual(result['failed'], [('broken', 'ValueError: invalid plugin')])
            self.assertIn('1 loaded, 1 missing-dep, 1 failed', loader.summarize_load_report(Mock()))
            loader.reset_load_report()
            self.assertEqual(loader.LOAD_REPORT['loaded'], [])

    def test_excluded_plugin_is_not_loaded_even_when_included(self):
        pkg = types.ModuleType('pyUltroid')
        pkg.__path__ = [str(ROOT / 'pyUltroid')]
        pkg.LOGS = logging.getLogger('loader-report-test')
        tools = types.ModuleType('pyUltroid.fns.tools')
        tools.get_all_files = lambda *args: []
        with patch.dict('sys.modules', {'pyUltroid': pkg, 'pyUltroid.fns.tools': tools}), tempfile.TemporaryDirectory() as tmp:
            loader = load_file('pyUltroid.loader_fixture', 'pyUltroid/loader.py')
            (Path(tmp) / 'disabled.py').write_text('')
            importer = Mock(return_value=types.ModuleType('disabled'))
            result = loader.Loader(tmp, logger=Mock()).load(func=importer, include=['disabled'], exclude=['disabled'])
            self.assertEqual(result['loaded'], [])
            importer.assert_not_called()
