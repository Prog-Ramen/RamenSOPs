"""Bounded readiness probe; verify the model identity before considering any PR."""
import json
import os
from pathlib import Path
import time
import urllib.request
from kev_server import RUN

for attempt in range(120):
    try:
        pid_file = Path(os.environ['RUNNER_TEMP']) / 'kev.pid'
        if pid_file.exists():
            try:
                os.kill(int(pid_file.read_text()), 0)
            except ProcessLookupError:
                log = Path(os.environ['RUNNER_TEMP']) / 'kev-server.log'
                if log.exists():
                    print('\n'.join(log.read_text(errors='replace').splitlines()[-30:]))
                raise SystemExit('Kev process exited before readiness; merging is blocked')
        with urllib.request.urlopen('http://127.0.0.1:8008/v1/models', timeout=2) as response:
            models = json.load(response)['models']
        model = next(m for m in models if m['name'] == 'kev-latest')
        if model['run'] != RUN or model['base'] != 'Qwen/Qwen3.5-4B-Base' or model['device'] != 'cpu' or model['dtype'] != 'bfloat16':
            raise SystemExit('Kev model identity/precision does not match trusted policy')
        print('Pinned Kev-4B CPU service ready')
        break
    except (OSError, ValueError, KeyError, StopIteration):
        time.sleep(5)
else:
    raise SystemExit('Kev did not become ready within ten minutes; merging is blocked')
