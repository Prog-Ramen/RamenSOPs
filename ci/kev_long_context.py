"""Single cold-context quality request with a twenty-minute diagnostic deadline."""
import json
import time
import urllib.request
from pathlib import Path
from kev_review import decide
from semantic import strict_json

started = time.monotonic()
def request(req):
    print('Starting single JSONL quality request; deadline=1200 seconds', flush=True)
    with urllib.request.urlopen(req, timeout=1200) as response:
        raw = response.read(65537)
    if len(raw) > 65536:
        raise ValueError('oversized response')
    result = strict_json(raw)
    print('Server metrics:', json.dumps({k: v for k, v in result.items() if k != 'answers'}), flush=True)
    return result

result = decide(Path(__file__).with_name('kev-positive.json').read_text(), request=request)
print('Quality result:', json.dumps(result), flush=True)
print('Elapsed seconds:', round(time.monotonic() - started, 2), flush=True)
if result.get('unavailable') or not result.get('approved'):
    raise SystemExit('Single-context diagnostic did not complete an approved review')
