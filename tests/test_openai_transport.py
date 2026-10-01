import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'ci'))
import semantic
import security

class OpenAITransportTests(unittest.TestCase):
    def test_missing_key_blocks_without_request(self):
        result=semantic.decide(Path('.'),'b','h',[],'',lambda req:self.fail('request without key'))
        self.assertTrue(result['unavailable'])
        self.assertFalse(result['approved'])

    def test_uses_openai_endpoint_and_model(self):
        def request(req):
            self.assertEqual(req.full_url,'https://api.openai.com/v1/chat/completions')
            self.assertEqual(req.get_header('Authorization'),'Bearer model-key')
            self.assertEqual(json.loads(req.data)['model'],'gpt-4o-mini')
            return {'choices':[{'finish_reason':'stop','message':{'content':json.dumps({**dict.fromkeys(semantic.KEYS,True),'reason':'Substantive generic behavior and tested edge cases.'})}}]}
        with patch.object(semantic,'tree',return_value={}):
            self.assertTrue(semantic.decide(Path('.'),'b','h',[],'model-key',request)['approved'])

    def test_security_missing_key_preserves_secret_detection(self):
        with patch.object(security,'scan_secrets',return_value=[{'category':'credentials','path':'sops/x/run.py'}]):
            self.assertEqual(security.assess(Path('.'),'b','h','')['verdict'],'prohibited')
        with patch.object(security,'scan_secrets',return_value=[]), patch.object(security,'submission',return_value={'sops/x/run.py':'print(1)'}), patch.object(security,'historical_findings',return_value=[]):
            r=security.assess(Path('.'),'b','h','',request=lambda req:self.fail('request without key'))
            self.assertEqual(r['verdict'],'unavailable')
            self.assertIn('OPENAI_API_KEY',r['error'])
