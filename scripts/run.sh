#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [ ! -x .venv/bin/dealintel ]; then ./scripts/setup.sh; fi
. .venv/bin/activate
exec dealintel run
