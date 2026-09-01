"""Local regression fixtures; no packages are installed or provider keys used."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import mcp


class MCPHardening(unittest.TestCase):
    def test_child_does_not_inherit_ungranted_environment(self):
        # A real child reports only the names of planted values, never secrets.
        code = "import os,json; print(json.dumps({'id':1,'result':{k:os.getenv(k) for k in ['OPENAI_API_KEY','AWS_SECRET_ACCESS_KEY','GITHUB_TOKEN','INNOCENT_CONFIG','PATH']}}))"
        with patch.dict(os.environ, {'OPENAI_API_KEY':'planted-model',
                'AWS_SECRET_ACCESS_KEY':'planted-cloud', 'GITHUB_TOKEN':'planted-github',
                'INNOCENT_CONFIG':'ungranted'}):
            s = mcp.Server('fixture', {'cmd':sys.executable, 'args':['-c',code],
                                     'env_allow':['GITHUB_TOKEN']})
            try:
                env = s._read_response(1)['result']
                self.assertIsNone(env['OPENAI_API_KEY'])
                self.assertIsNone(env['AWS_SECRET_ACCESS_KEY'])
                self.assertIsNone(env['INNOCENT_CONFIG'])
                self.assertEqual(env['GITHUB_TOKEN'], 'planted-github')
                self.assertTrue(env['PATH'])
            finally:
                s.close()

    def test_invalid_environment_grants_fail_before_spawn(self):
        for allow in ('*', ['*'], ['A=B'], [3]):
            with self.subTest(allow=allow), self.assertRaises(ValueError):
                mcp.Server('bad', {'cmd':sys.executable, 'args':['-c','pass'],
                                   'env_allow':allow})

    def protocol_server(self, result=None, error=None):
        reply = {'jsonrpc':'2.0','id':1}
        reply.update({'error':error} if error else {'result':result})
        code = 'import sys; sys.stdin.readline(); print('+repr(json.dumps(reply))+',flush=True); sys.stdin.read()'
        return mcp.Server('protocol-fixture', {'cmd':sys.executable,'args':['-c',code]}, timeout=2)

    def test_modern_rejection_is_not_fake_negotiation(self):
        s = self.protocol_server(error={'code':-32022,'message':'Unsupported protocol'})
        try:
            with self.assertRaises(RuntimeError):
                s.handshake()
            self.assertIsNone(s._era)
        finally:
            s.close()

    def test_unimplemented_version_is_rejected(self):
        s = self.protocol_server(result={'protocolVersion':'2026-07-28'})
        try:
            with self.assertRaises(RuntimeError):
                s.handshake()
        finally:
            s.close()

    def test_enable_pins_executable_and_detects_configuration_drift(self):
        with tempfile.TemporaryDirectory() as root, patch('shutil.which', return_value=sys.executable):
            path, entry = mcp.enable(root, 'playwright')
            self.assertRegex(entry['args'][1], r'^@playwright/mcp@\d+\.\d+\.\d+$')
            self.assertTrue(entry.get('integrity'))
            self.assertTrue(entry.get('trust_identity'))
            # Changing code while retaining old trust evidence must not launch.
            entry['args'][-1] = '@playwright/mcp@0.0.1'
            Path(path).write_text(json.dumps({'servers':{'playwright':entry}}))
            with patch('subprocess.Popen') as spawn, self.assertRaises(ValueError):
                mcp.connect(root, 'playwright')
            spawn.assert_not_called()

    def test_catalog_has_no_floating_executable(self):
        with tempfile.TemporaryDirectory() as root, patch('shutil.which', return_value=sys.executable):
            for name in mcp.CATALOG:
                _, entry = mcp.enable(root, name)
                args = entry['args']
                package = args[1] if entry['cmd'] == 'npx' else args[0]
                self.assertRegex(package, r'(?:@|==)\d+\.\d+\.\d+$')
                self.assertTrue(entry.get('version'))
                self.assertTrue(entry.get('source'))

    def test_code_update_invalidates_grant_but_not_completed_effect(self):
        import approvals
        import effects
        fixture = str(Path(__file__).with_name('mock_mcp_server.py'))
        with tempfile.TemporaryDirectory() as root:
            spec = {'cmd':sys.executable, 'args':[fixture], 'version':'1.0.0'}
            spec['trust_identity'] = mcp.server_identity(spec)
            config = Path(root, 'mcp.json')
            config.write_text(json.dumps({'servers':{'fixture':spec}}))
            server = mcp.connect(root, 'fixture')
            args = {'id':'disposable-record'}
            try:
                _, status = mcp.guarded_call(server, 'delete_record', args, root=root)
                self.assertEqual(status, 'approval_required')
                old = approvals.pending(root)[0]
                approvals.decide(root, old['id'], True)
            finally:
                server.close()
            spec['version'] = '1.0.1'
            spec['trust_identity'] = mcp.server_identity(spec)
            config.write_text(json.dumps({'servers':{'fixture':spec}}))
            server = mcp.connect(root, 'fixture')
            try:
                _, status = mcp.guarded_call(server, 'delete_record', args, root=root)
                self.assertEqual(status, 'approval_required')
                self.assertNotEqual(approvals.pending(root)[0]['id'], old['id'])
                self.assertFalse(Path(root, 'deleted.log').exists())
                # Code updates never make a previously completed effect repeat.
                key = effects.key_of(os.getenv('AGENT_TASK_LINEAGE') or 'manual',
                                     'fixture', 'delete_record', args)
                effects.record(root,key,'t','fixture','delete_record',args,{'content':[]})
                _, status = mcp.guarded_call(server, 'delete_record', args, root=root)
                self.assertEqual(status, 'replayed')
                self.assertFalse(Path(root, 'deleted.log').exists())
            finally:
                server.close()


if __name__ == '__main__':
    unittest.main()
