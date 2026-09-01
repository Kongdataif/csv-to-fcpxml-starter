#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo_root"

if [[ -x .venv/bin/python ]]; then
  python_cmd=".venv/bin/python"
else
  python_cmd="python3"
fi

"$python_cmd" scripts/make_demo_media.py
"$python_cmd" csv_to_fcpxml.py --config examples/demo_project/project.json --validate-only
"$python_cmd" csv_to_fcpxml.py --config examples/demo_project/project.json
"$python_cmd" scripts/validate_fcpxml.py --check-media \
  examples/demo_project/Generated/demo_roughcut_clean.fcpxml \
  examples/demo_project/Generated/demo_roughcut_with_captions.fcpxml

echo "데모 성공: examples/demo_project/Generated/"
