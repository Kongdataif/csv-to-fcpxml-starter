#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo_root"

if [[ -x .venv/bin/python ]]; then
  python_cmd=".venv/bin/python"
else
  python_cmd="python3"
fi

"$python_cmd" scripts/make_demo_media.py --project examples/title_project --no-bgm
"$python_cmd" make_xml.py examples/title_project --validate-only
"$python_cmd" make_xml.py examples/title_project
"$python_cmd" scripts/validate_fcpxml.py \
  --check-media \
  --require-relative \
  --project-root examples/title_project \
  examples/title_project/Generated/title_project_clean.fcpxml \
  examples/title_project/Generated/title_project_with_titles.fcpxml

test -f examples/title_project/Generated/title_project.srt
echo "화면 자막 데모 성공: subtitles.csv → with_titles.fcpxml + SRT"
