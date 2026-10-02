#!/usr/bin/env bash
set -euo pipefail
git clone https://github.com/jaredpalmer/kev.git "$RUNNER_TEMP/kev-src"
git -C "$RUNNER_TEMP/kev-src" checkout eb45fd2381396eb7edc3964b753ebc1b0ab1da2b
python -m venv "$RUNNER_TEMP/kev-env"
"$RUNNER_TEMP/kev-env/bin/pip" install --no-cache-dir torch==2.8.0 --index-url https://download.pytorch.org/whl/cpu
"$RUNNER_TEMP/kev-env/bin/pip" install --no-cache-dir -c ci/kev-constraints.txt "$RUNNER_TEMP/kev-src[serve]"
