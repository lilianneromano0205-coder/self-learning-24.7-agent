"""Disposable regressions for authority lifetime, not persistence tooling."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import sandbox
import execution
import contract
import controlplane


class ContainmentTests(unittest.TestCase):
    def test_default_requires_isolation(self):
        self.assertEqual(sandbox.backend_name({}), 'docker')

    def test_host_detached_child_cannot_outlive_authority_by_default(self):
        mechanisms = ['detached', 'group'] if os.name == 'nt' else ['session', 'group']
        for mechanism in mechanisms:
            with self.subTest(mechanism=mechanism), tempfile.TemporaryDirectory() as d:
                root = Path(d)
                protected = root / 'settings.toml'
                protected.write_text('[agent]\n', encoding='utf-8')
                (root / 'child.py').write_text(
                    'import time\nfrom pathlib import Path\n'
                    'time.sleep(0.3)\nPath("settings.toml").write_text("CHANGED")\n',
                    encoding='utf-8')
                flags = (f'creationflags={subprocess.DETACHED_PROCESS}' if mechanism == 'detached'
                         else f'creationflags={subprocess.CREATE_NEW_PROCESS_GROUP}' if os.name == 'nt'
                         else 'start_new_session=True' if mechanism == 'session'
                         else 'process_group=0')
                (root / 'parent.py').write_text(
                    'import subprocess,sys\nsubprocess.Popen([sys.executable,"child.py"],'
                    'stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,'
                    + flags + ')\n', encoding='utf-8')
                rc, _, err = execution.run('gate', f'"{sys.executable}" parent.py', d,
                                            cfg={'agent': {'sandbox': 'host'}}, timeout=5)
                time.sleep(0.7)  # bounded delayed fixture is finished before temp cleanup
                self.assertEqual(protected.read_text(), '[agent]\n', (rc, err))
                self.assertNotEqual(rc, 0)

    def test_seal_errors_refuse_before_execution(self):
        with tempfile.TemporaryDirectory() as d, patch.object(controlplane, 'seal', side_effect=OSError('seal failed')), patch.object(sandbox, 'run') as run:
            with self.assertRaises(execution.Refused):
                execution.run('gate', 'echo ok', d, cfg={'agent': {'sandbox': 'docker'}})
            run.assert_not_called()

    def test_enforcement_errors_are_not_clean(self):
        with tempfile.TemporaryDirectory() as d, patch.object(controlplane, 'enforce', side_effect=OSError('verify failed')), patch.object(sandbox, 'run', return_value=(0, '', '')):
            rc, _, err = execution.run('gate', 'echo ok', d, cfg={'agent': {'sandbox': 'docker'}})
            self.assertNotEqual(rc, 0)
            self.assertIn('verify failed', err)

    def test_hosted_workspace_refuses_without_contact(self):
        for backend in sandbox.HOSTED:
            with self.subTest(backend=backend), tempfile.TemporaryDirectory() as d, patch.object(sandbox, '_hosted') as remote:
                rc, _, err = sandbox.run('echo change > file', d, cfg={'agent': {'sandbox': backend}})
                self.assertNotEqual(rc, 0)
                self.assertIn('round-trip', err)
                remote.assert_not_called()

    def test_conflicting_append_never_reseals_contract(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / 'experts' / 'one'
            root.mkdir(parents=True)
            contract.create(str(root), 'g1', 'goal', accept=[{'id': 'a', 'what': 'original', 'check': 'echo original'}])
            contract.freeze(str(root), 'g1')
            c = contract.load(str(root), 'g1')
            c['acceptance'][0]['check'] = 'echo changed'
            c['accept_hash'] = contract._accept_hash(c['acceptance'])
            Path(contract.path(str(root), 'g1')).write_text(json.dumps(c), encoding='utf-8')
            with open(contract.seal_path(str(root))[0], 'a', encoding='utf-8') as f:
                f.write(json.dumps({'gid': 'g1', 'accept_hash': c['accept_hash']}) + '\n')
            with patch.object(execution, 'run', return_value=(0, '', '')) as run:
                result = contract.verify(str(root), 'g1')
                self.assertTrue(result['tamper'], result)
                self.assertFalse(result['all'])
                run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
