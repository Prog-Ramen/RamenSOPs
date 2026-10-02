import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'ci'))
from kev_download import verify

class CacheIntegrityTests(unittest.TestCase):
    def test_corrupted_model_cannot_be_used(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            original=b'known pinned model bytes'
            p=root/'weights.safetensors';p.write_bytes(original)
            info=SimpleNamespace(rfilename=p.name,lfs=SimpleNamespace(sha256=hashlib.sha256(original).hexdigest()))
            verify(root,[info])
            p.write_bytes(b'altered cached model')
            with self.assertRaisesRegex(ValueError,'integrity failure'):
                verify(root,[info])

    def test_configuration_git_blob_hash_checked(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            data=b'{"base":"pinned"}'
            p=root/'config.json';p.write_bytes(data)
            info=SimpleNamespace(rfilename=p.name,lfs=None,blob_id=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest())
            verify(root,[info])
            p.write_bytes(b'{}')
            with self.assertRaises(ValueError):
                verify(root,[info])
