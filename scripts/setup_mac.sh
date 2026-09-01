#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo_root"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3.10 이상이 필요합니다: https://www.python.org/downloads/macos/" >&2
  exit 2
fi

python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 2)' || {
  echo "현재 Python이 너무 오래되었습니다. Python 3.10 이상을 설치하세요." >&2
  exit 2
}

if ! command -v ffprobe >/dev/null 2>&1 || ! command -v ffmpeg >/dev/null 2>&1; then
  echo "ffmpeg/ffprobe가 필요합니다. Homebrew가 있다면: brew install ffmpeg" >&2
  exit 2
fi

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi

# Install the local command-line tools inside this project's virtual
# environment.  The converter has no third-party Python runtime packages, so
# user media and project data never need to leave this Mac.
.venv/bin/python -m pip install --editable .

echo "준비 완료"
echo "가상환경 켜기: source .venv/bin/activate"
echo "세로+가로 데모: bash scripts/run_beginner_demo.sh"
echo "내 프로젝트: timeline.xlsx 또는 timeline.csv, Media/, 선택 subtitles.xlsx/.csv를 넣은 뒤"
echo "입력 검사: python make_xml.py projects/my-video --layout both --validate-only"
echo "화면 미리보기: python make_xml.py projects/my-video --layout both --preview-only"
echo "세로+가로 XML 만들기: python make_xml.py projects/my-video --layout both"
echo "Final Cut 열기: python make_xml.py projects/my-video --layout both --open"
