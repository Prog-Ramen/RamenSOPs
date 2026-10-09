"""Categories with more than LIMIT SOPs directly in them, read from the folders alone (no model, no code run).
The rebalance job runs this first and does nothing else when the tree is fine."""
import json
import sys
from pathlib import Path

LIMIT = 8


def crowded(root, limit=LIMIT):
    out = {}
    for d in sorted(p for p in root.rglob('*') if p.is_dir()):
        if (d / 'sop.json').exists() or any(part.startswith(('.', '_')) for part in d.relative_to(root).parts):
            continue
        n = sum(1 for c in d.iterdir() if c.is_dir() and (c / 'sop.json').exists())
        if n > limit:
            out['.'.join(d.relative_to(root).parts)] = n
    return out


if __name__ == '__main__':
    over = crowded(Path(sys.argv[1] if len(sys.argv) > 1 else 'sops'))
    print(json.dumps(over))
