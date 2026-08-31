"""Explicit, bounded release checks. Default execution is inert and keyless.

Run only reviewed code, never pull-request code with release credentials.
Provider smoke is availability evidence, NOT quality/routing/learning evidence.
"""
import argparse
import contextlib
import io
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
# Fixed first-party endpoints prevent an input URL from redirecting credentials.
PROVIDER_ENDPOINTS = {'openai':'https://api.openai.com/v1',
                      'openrouter':'https://openrouter.ai/api/v1'}


def provider_check(args):
    """One metered 16-output-token call through the existing no-retry probe."""
    if not args.model or not os.getenv('LIVE_RELEASE_API_KEY'):
        return {'status':'NOT_RUN','reason':'explicit model and LIVE_RELEASE_API_KEY required',
                'provider_calls':0}
    rates = (args.input_per_mtok, args.output_per_mtok)
    if any(not math.isfinite(v) or v <= 0 for v in rates):
        raise ValueError('positive verified provider input/output rates are required')
    # Conservative reservation for the fixed tiny prompt plus output ceiling.
    # This bounds requests/tokens, not a provider's independent billing policy.
    reserved = (256*rates[0]+16*rates[1])/1_000_000
    if reserved > args.max_usd:
        raise ValueError('single-call reservation exceeds the configured spend ceiling')
    import loop
    import modelgateway
    with tempfile.TemporaryDirectory(prefix='release-provider-') as root:
        cfg = ('[agent]\nsandbox="docker"\nreflect_after=[]\n'
               f'daily_budget_usd={args.max_usd}\n'
               '[providers.release]\ntype="openai"\n'
               f'base_url={json.dumps(PROVIDER_ENDPOINTS[args.provider])}\n'
               'api_key_env="LIVE_RELEASE_API_KEY"\n'
               f'input_per_mtok={rates[0]}\noutput_per_mtok={rates[1]}\n'
               '[roles.default]\nprovider="release"\n'
               f'model={json.dumps(args.model)}\n')
        Path(root,'settings.toml').write_text(cfg,encoding='utf-8')
        agent = loop.Agent(root)
        verdict = agent._probe('release', args.model)
        rows = modelgateway.calls(root)
        cost = sum(r.get('cost_usd',0) for r in rows)
        ok = verdict == 'OK' and len(rows) == 1 and cost <= args.max_usd
        # Never emit server error bodies, credentials, or generated text.
        return {'status':'PASS' if ok else 'FAIL', 'provider_calls':len(rows),
                'cost_usd':cost, 'reserved_usd':reserved, 'max_output_tokens':16,
                'evidence':'real provider availability only',
                'usage': [{k:r.get(k,0) for k in ('tokens_in','tokens_out')} for r in rows]}


def docker_check(args):
    import sandbox
    image = args.docker_image
    if not image or '@sha256:' not in image:
        raise ValueError('a preinstalled Docker image pinned by sha256 digest is required')
    import mcp
    env = mcp.server_environment({})
    have = subprocess.run(['docker','image','inspect',image],env=env,
                          capture_output=True,timeout=10)
    if have.returncode:
        return {'status':'NOT_RUN','reason':'pinned Docker image unavailable; no pull attempted'}
    with tempfile.TemporaryDirectory(prefix='release-docker-') as root:
        marker = Path(root,'release-check.txt')
        code, out, err = sandbox.run(
            "python -c \"from pathlib import Path; Path('release-check.txt').write_text('contained')\"",
            root, {}, timeout=20,
            cfg={'agent':{'sandbox':'docker','sandbox_network':False,'sandbox_image':image}})
        return {'status':'PASS' if code == 0 and marker.exists()
                and marker.read_text() == 'contained' else 'FAIL',
                'evidence':'real Docker workspace round-trip', 'provider_calls':0}


def mcp_check(args):
    import mcp
    if not all((args.mcp_root,args.mcp_server,args.mcp_tool)):
        return {'status':'NOT_RUN','reason':'explicit installed MCP fixture not configured'}
    servers = mcp.load_servers(args.mcp_root)
    spec = servers.get(args.mcp_server, {})
    if (not spec.get('trust_identity') or spec.get('env_allow') or spec.get('env')
            or (spec.get('risk') or {}).get(args.mcp_tool) != 'read'):
        raise ValueError('MCP smoke requires reviewed identity, no credential grants, '
                         'and owner-declared read-only tool')
    mcp.validate_identity(spec)
    arguments = json.loads(args.mcp_args)
    with tempfile.TemporaryDirectory(prefix='release-mcp-ledger-') as ledger:
        server = mcp.connect(args.mcp_root,args.mcp_server,timeout=10)
        try:
            result, how = mcp.guarded_call(server,args.mcp_tool,arguments,root=ledger)
            return {'status':'PASS' if how == 'live' and not result.get('isError') else 'FAIL',
                    'evidence':'real configured legacy MCP read operation',
                    'trust_identity':spec['trust_identity'],'provider_calls':0}
        finally:
            server.close()


def federation_check(args):
    # Existing disposable pairwise authenticated HTTP fixture, no model providers.
    import mcp
    result = subprocess.run([sys.executable,str(ROOT/'tests/test_federation.py')],
                            cwd=ROOT,env=mcp.server_environment({}),
                            capture_output=True,timeout=45)
    return {'status':'PASS' if result.returncode == 0 else 'FAIL',
            'evidence':'real loopback custom federation HTTP; scripted model only',
            'remote_interoperability':'NOT_RUN','provider_calls':0}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--opt-in',action='store_true')
    parser.add_argument('--check', choices=('provider','docker','mcp','federation'),default='docker')
    parser.add_argument('--max-usd',type=float,default=0.01)
    parser.add_argument('--provider',choices=tuple(PROVIDER_ENDPOINTS),default='openai')
    parser.add_argument('--model',default='')
    parser.add_argument('--input-per-mtok',type=float,default=0)
    parser.add_argument('--output-per-mtok',type=float,default=0)
    parser.add_argument('--docker-image',default='')
    parser.add_argument('--mcp-root'); parser.add_argument('--mcp-server')
    parser.add_argument('--mcp-tool'); parser.add_argument('--mcp-args',default='{}')
    args = parser.parse_args(argv)
    if not args.opt_in:
        print(json.dumps({'status':'NOT_RUN','reason':'explicit --opt-in required','provider_calls':0}))
        return 0
    if not math.isfinite(args.max_usd) or not 0 < args.max_usd <= 0.01:
        parser.error('--max-usd must be positive and at most 0.01')
    started = time.monotonic()
    try:
        # Avoid loading environment keys in any non-provider subprocess.
        if args.check != 'provider':
            os.environ.pop('LIVE_RELEASE_API_KEY',None)
        with contextlib.redirect_stdout(io.StringIO()):
            result = globals()[args.check+'_check'](args)
    except Exception as exc:
        result = {'status':'FAIL','error_type':type(exc).__name__,
                  'reason':str(exc) if isinstance(exc,ValueError) else 'check failed; inspect locally',
                  'provider_calls':0}
    result.update(check=args.check,elapsed_seconds=round(time.monotonic()-started,3))
    print(json.dumps(result))
    return 0 if result['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
