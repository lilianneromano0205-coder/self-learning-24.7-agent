"""Release runner must be inert unless deliberately enabled."""
import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ReleaseSafety(unittest.TestCase):
    def test_default_is_keyless_and_inert(self):
        result = subprocess.run([sys.executable,str(ROOT/'tests/release_checks.py')],
            capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        receipt = json.loads(result.stdout)
        self.assertEqual(receipt['status'],'NOT_RUN')
        self.assertEqual(receipt['provider_calls'],0)

    def test_invalid_spend_ceiling_is_rejected_before_call(self):
        result = subprocess.run([sys.executable,str(ROOT/'tests/release_checks.py'),
            '--opt-in','--check','provider','--max-usd','100'],
            capture_output=True,text=True,timeout=10)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('0.01', result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
