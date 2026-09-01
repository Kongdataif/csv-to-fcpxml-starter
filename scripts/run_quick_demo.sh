#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo_root"

if [[ -x .venv/bin/python ]]; then
  python_cmd=".venv/bin/python"
else
  python_cmd="python3"
fi

"$python_cmd" scripts/make_demo_media.py --project examples/simple_project --no-bgm
"$python_cmd" make_xml.py examples/simple_project --validate-only
"$python_cmd" make_xml.py examples/simple_project
"$python_cmd" scripts/validate_fcpxml.py \
  --check-media \
  --require-relative \
  --project-root examples/simple_project \
  examples/simple_project/Generated/simple_project_clean.fcpxml

echo "간편 모드 성공: timeline.csv + Media/ → Generated/simple_project_clean.fcpxml"
