"""Exercise real local HTTP authentication and CSRF with disposable state."""
import json
from pathlib import Path
import sys
import tempfile
import subprocess
import shutil
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ui


class UIAuth(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        class Handler(ui.Handler):
            home = cls.tmp.name
            token = 'planted-owner-token'
            def _events(self, query):
                self._json({'stream_authenticated': True})
        cls.srv = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.thread = threading.Thread(target=cls.srv.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = 'http://127.0.0.1:'+str(cls.srv.server_port)

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown(); cls.srv.server_close(); cls.thread.join()
        cls.tmp.cleanup()

    def request(self, path, method='GET', headers=None):
        req = urllib.request.Request(self.base+path, method=method, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=3) as response:
                return response.status, response.headers, response.read().decode()
        except urllib.error.HTTPError as e:
            with e:
                return e.code, e.headers, e.read().decode()

    def test_query_token_never_authenticates(self):
        for path in ('/api/experts','/api/events'):
            code, _, body = self.request(path+'?token=planted-owner-token')
            self.assertEqual(code, 401, body)
            self.assertNotIn('planted-owner-token', body)

    def test_bearer_header_authenticates_api_and_stream(self):
        for path in ('/api/experts','/api/events'):
            code, _, _ = self.request(path, headers={'Authorization':'Bearer planted-owner-token'})
            self.assertEqual(code, 200)

    def test_cross_origin_write_remains_refused_with_valid_bearer(self):
        code, _, _ = self.request('/api/experts', 'POST',
            {'Authorization':'Bearer planted-owner-token','Origin':'https://untrusted.invalid',
             'Sec-Fetch-Site':'cross-site'})
        self.assertEqual(code, 403)

    def test_bootstrap_is_public_and_not_cacheable_or_referring(self):
        code, headers, body = self.request('/')
        self.assertEqual(code, 200)
        self.assertNotIn('planted-owner-token', body)
        self.assertEqual(headers.get('Referrer-Policy'), 'no-referrer')
        self.assertIn('no-store', headers.get('Cache-Control',''))

    @unittest.skipUnless(shutil.which('node'), 'Node needed for JavaScript behavior check')
    def test_ui_stream_uses_header_and_parses_split_frames(self):
        html = Path(ui.__file__).with_name('ui.html').read_text(encoding='utf-8')
        start = html.index('function connectEvents(')
        if html[start-6:start] == 'async ':
            start -= 6
        js = html[start:html.index('function feedRowHtml', start)]
        harness = r'''
const assert = require('node:assert/strict');
const S = {}; const EV_KINDS = ['task_done'];
const token = ()=> 'planted-browser-token';
const paintLive = ()=>{}; const setTimeout = ()=>{};
const window = {fetch: true, ReadableStream: true, EventSource: class {}};
let seen = null;
const fetch = async (url, options)=> {
  seen = {url, options};
  const chunks = ['event: ready\ndata: {}\n\nevent: task_',
                  'done\ndata: {"text":"completed"}\n\n'];
  return {ok:true, headers:{get:()=> 'text/event-stream'},
          body:{getReader:()=>({read:async()=> chunks.length
            ? {value:new TextEncoder().encode(chunks.shift()),done:false}
            : {done:true}, releaseLock(){}})}};
};
'''
        harness += js + '''
(async()=> { await connectEvents();
 assert.ok(seen, 'stream must use fetch with a bearer header');
 assert.equal(seen.url, '/api/events');
 assert.equal(seen.options.headers.Authorization, 'Bearer planted-browser-token');
 assert.equal(S.live[0].text, 'completed');
 assert.equal(S.es, null);
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
        result = subprocess.run(['node','-e',harness], capture_output=True,
                                text=True, timeout=8)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
