"""Populate and verify a pinned HF model cache; never execute downloaded model code."""
import hashlib
import os
from pathlib import Path
from huggingface_hub import HfApi, snapshot_download

MODELS = (
    ('jaredpalmer/kev-4b', '6cfce5c2fa4b4bd64026336ab649c5ca78857d52'),
    ('Qwen/Qwen3.5-4B-Base', '1001bb4d826a52d1f399e183466143f4da7b741b'),
)
PATTERNS = ['*.json', '*.safetensors', '*.pt', '*.txt', '*.jinja']


def verify(root, files):
    for item in files:
        p = root / item.rfilename
        if not p.exists():
            continue
        if item.lfs:
            expected = item.lfs.sha256
            h = hashlib.sha256()
            with p.open('rb') as f:
                for chunk in iter(lambda: f.read(4 * 1024 * 1024), b''):
                    h.update(chunk)
        else:
            data = p.read_bytes()
            h = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data)
            expected = item.blob_id
        if not expected or h.hexdigest() != expected:
            raise ValueError('Pinned model cache integrity failure: ' + item.rfilename)


if __name__ == '__main__':
    api = HfApi()
    for repo, revision in MODELS:
        root = Path(snapshot_download(repo, revision=revision, allow_patterns=PATTERNS))
        info = api.model_info(repo, revision=revision, files_metadata=True)
        if info.sha != revision:
            raise ValueError('Unexpected model revision')
        verify(root, info.siblings)
    cache = Path(os.environ['HF_HOME'])
    size = sum(p.stat().st_size for p in cache.rglob('*') if p.is_file() and not p.is_symlink())
    print('Verified model cache bytes:', size)
    # Keep this workflow below the free repository allowance without increasing billing limits.
    if size > 9 * 1024**3:
        raise ValueError('Model cache exceeds 9 GiB budget')
