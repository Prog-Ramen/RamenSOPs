"""Build Rameness format-4 sharded, columnar indexes without importing any SOP code.

Every category gets its own _index.json listing only its children. An SOP's entry holds only what a client
chooses by (id, description, keywords); its inputs, permissions and file hashes are in its own _meta.json, which
a client fetches only for the SOPs it picks, checked against the hash the listing gives for it. The root index
also carries the aliases of SOPs moved when a category was reorganized.
"""
import hashlib
import json
from pathlib import Path

GENERATED = {'index.json', '_index.json', '_meta.json'}


def build(root):
    root.mkdir(parents=True, exist_ok=True)
    for f in root.rglob('*.json'):
        if f.name in GENERATED:
            f.unlink()
    def entry(path):
        sid = '.'.join(path.relative_to(root).parts)
        meta = path / 'sop.json'
        if meta.exists():
            m = json.loads(meta.read_text())
            files = [{'path': str(f.relative_to(root)), 'sha256': hashlib.sha256(f.read_bytes()).hexdigest()}
                     for f in sorted(path.rglob('*')) if f.is_file() and '__pycache__' not in f.parts and f.name not in GENERATED]
            data = json.dumps({'kind': m['kind'], 'permissions': m.get('permissions', []), 'version': m.get('version', '1.0.0'),
                               'inputs': m['inputs'], 'status': m['status'], 'files': files}, indent=1, sort_keys=True).encode()
            (path / '_meta.json').write_bytes(data)
            return {'type': 'sop', 'id': sid, 'description': m['description'], 'keywords': m.get('keywords', []),
                    'path': str(path.relative_to(root)),
                    'meta': {'path': str((path / '_meta.json').relative_to(root)), 'sha256': hashlib.sha256(data).hexdigest()}}
        m = json.loads((path / '_node.json').read_text()) if (path / '_node.json').exists() else {}
        children = sorted(p.name for p in path.iterdir() if p.is_dir() and not p.name.startswith('.'))
        return {'type': 'node', 'id': sid, 'description': m.get('description', sid), 'keywords': m.get('keywords', []), 'requires': m.get('requires', []), 'children': children}
    def walk(path):
        children = sorted(p for p in path.iterdir() if p.is_dir() and not p.name.startswith('.'))
        entries = [entry(p) for p in children]
        for p in children:
            if not (p / 'sop.json').exists():
                walk(p)
        index = path / ('index.json' if path == root else '_index.json')
        data = {'format': 4, 'id': '.'.join(path.relative_to(root).parts), 'entries': entries}
        if path == root and (root / '_aliases.json').exists():
            data['aliases'] = json.loads((root / '_aliases.json').read_text())
        index.write_text(json.dumps(data, indent=1) + '\n')
    walk(root)

if __name__ == '__main__':
    build(Path('sops'))
