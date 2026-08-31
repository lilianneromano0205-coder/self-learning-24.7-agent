"""Filesystem receipts for acquisition; only disposable local fixtures."""
import json
import os
from pathlib import Path
import shlex
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import acquire
import sandbox
import workers


class ArenaTests(unittest.TestCase):
    def fixture(self, root):
        root.joinpath('settings.toml').write_text('[agent]\nsandbox="docker"\n')
        rec = acquire.request(str(root), 'arenaexample', 'pypi', 'zzz isolated qqq', version='1.0')
        workers.register(str(root), 'Disposable', 'local-docker', ['docker', 'install'])
        return rec

    def test_installer_only_receives_minimal_arena(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            rec = self.fixture(root)
            root.joinpath('private-sentinel').write_text('PRIVATE-WORKSPACE')
            seen = {}
            def installer(cmd, arena, env, timeout, cfg):
                seen['root'] = Path(arena)
                seen['sentinel_visible'] = (Path(arena) / 'private-sentinel').exists()
                target = shlex.split(cmd)[shlex.split(cmd).index('--target') + 1]
                package = Path(arena) / target / 'arenaexample'
                package.mkdir(parents=True)
                package.joinpath('__init__.py').write_text('VERSION="1.0"')
                return 0, 'fixture installed', ''
            with patch.object(sandbox, 'available', return_value=(True, 'fixture')), patch.object(sandbox, 'run', side_effect=installer):
                got = acquire.install(d, d, rec['id'])
            self.assertNotEqual(seen['root'], root)
            self.assertFalse(seen['sentinel_visible'])
            self.assertFalse((root / 'capabilities' / 'arenaexample').exists(), 'must await probe before promotion')
            self.assertTrue(got.get('content_hash'))

    def test_remove_deletes_bytes_before_ledger_success(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            target = root / 'capabilities' / 'arenaexample'
            target.mkdir(parents=True)
            target.joinpath('installed.py').write_text('installed')
            acquire._save(d, [{'id':'a', 'name':'arenaexample', 'stage':'trusted', 'install_path':'capabilities/arenaexample', 'history':[]}])
            got = acquire.remove(d, 'a')
            self.assertFalse(target.exists())
            self.assertEqual(got['stage'], 'removed')

    def test_remove_refuses_outside_path_and_leaves_ledger(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / 'expert'; root.mkdir()
            outside = Path(d) / 'private'; outside.mkdir()
            acquire._save(str(root), [{'id':'a', 'name':'arenaexample', 'stage':'trusted', 'install_path':'../private', 'history':[]}])
            with self.assertRaises(acquire.Refused):
                acquire.remove(str(root), 'a')
            self.assertTrue(outside.exists())
            self.assertEqual(acquire.load(str(root))[0]['stage'], 'trusted')

    def test_validate_rejects_link_before_promotion(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); output = root / 'output'; output.mkdir()
            outside = root / 'private'; outside.write_text('private')
            os.link(outside, output / 'alias')
            validate = getattr(acquire, 'validate_output', None)
            self.assertTrue(callable(validate), 'output validation is missing')
            with self.assertRaises(acquire.Refused):
                validate(str(output))

    def test_probe_cannot_import_on_host_or_skip_output_hash(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); rec = self.fixture(root)
            arena = root / 'tmp' / 'acquire-arena-test'; output = arena / 'output'
            pkg = output / 'arenaexample'; pkg.mkdir(parents=True)
            pkg.joinpath('__init__.py').write_text('VERSION=1')
            rows = acquire.load(d); rows[0].update(stage='installed', arena_path='tmp/acquire-arena-test',
                install_path='tmp/acquire-arena-test/output', content_hash=acquire.validate_output(str(output)))
            acquire._save(d, rows)
            seen = {}
            def probe(op, cmd, probe_root, **kwargs):
                seen.update(op=op, cmd=cmd, root=probe_root, cfg=kwargs.get('cfg'))
                return 0, 'imported arenaexample', ''
            import execution
            with patch.object(execution, 'run', side_effect=probe):
                got = acquire.capability_test(d, rec['id'])
            self.assertEqual(seen['cfg']['agent']['sandbox'], 'docker')
            self.assertFalse(seen['cfg']['agent']['sandbox_network'])
            self.assertNotEqual(Path(seen['root']), root)
            self.assertEqual(got['stage'], 'tested')
            self.assertTrue((root / 'capabilities' / 'arenaexample' / 'arenaexample' / '__init__.py').exists())
            self.assertFalse(arena.exists())


class ContainmentSpellingTests(unittest.TestCase):
    """A path that is merely spelled differently is not an escape.

    `_contained` demanded `realpath(base) == base`, which is false for any
    root holding a WINDOWS 8.3 SHORT NAME — realpath expands `RUNNER~1` to
    `runneradmin`. Every acquisition on a GitHub Windows runner was refused
    as "escaping its authority root", and so was every acquisition for a user
    whose profile name exceeds eight characters. The four real escapes below
    must keep failing, which is what makes the first assertion safe.
    """

    def _short_name_base(self, parent):
        """A directory addressed by its 8.3 alias, or None if unavailable."""
        if os.name != 'nt':
            return None
        import ctypes
        long_dir = os.path.join(parent, 'acquirecontainmentprobe')
        os.makedirs(long_dir, exist_ok=True)
        buf = ctypes.create_unicode_buffer(1024)
        if not ctypes.windll.kernel32.GetShortPathNameW(long_dir, buf, 1024):
            return None
        short = buf.value
        return short if os.path.abspath(short) != os.path.abspath(long_dir) else None

    def test_a_short_name_root_is_contained_not_refused(self):
        with tempfile.TemporaryDirectory() as d:
            base = self._short_name_base(d)
            if base is None:
                self.skipTest('no 8.3 short name available here (not Windows, '
                              'or 8dot3 name creation is disabled on this '
                              'volume) — run on Windows to exercise it')
            sub = os.path.join(base, 'arena')
            os.makedirs(sub, exist_ok=True)
            self.assertNotEqual(os.path.realpath(base), os.path.abspath(base),
                                'fixture is not exercising a spelling difference')
            self.assertEqual(acquire._contained(base, sub), sub)

    def test_every_real_escape_is_still_refused(self):
        with tempfile.TemporaryDirectory() as d:
            base = os.path.join(d, 'base')
            os.makedirs(os.path.join(base, 'arena'))
            for label, target in (
                    ('a sibling outside the root', os.path.join(d, 'elsewhere')),
                    ('the root itself', base),
                    ('a parent traversal', os.path.join(base, '..', 'x'))):
                with self.assertRaises(acquire.Refused, msg=label):
                    acquire._contained(base, target)

    def test_a_linked_root_or_component_is_still_refused(self):
        with tempfile.TemporaryDirectory() as d:
            real = os.path.join(d, 'real')
            os.makedirs(os.path.join(real, 'arena'))
            link = os.path.join(d, 'linked-root')
            try:
                if os.name == 'nt':
                    import subprocess
                    if subprocess.run(['cmd', '/c', 'mklink', '/J', link, real],
                                      capture_output=True).returncode != 0:
                        self.skipTest('cannot create a junction here')
                else:
                    os.symlink(real, link)
            except (OSError, NotImplementedError):
                self.skipTest('cannot create a link here')
            with self.assertRaises(acquire.Refused):
                acquire._contained(link, os.path.join(link, 'arena'))


if __name__ == '__main__':
    unittest.main()
