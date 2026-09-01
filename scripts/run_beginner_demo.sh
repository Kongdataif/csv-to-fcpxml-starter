#!/usr/bin/env bash
set -euo pipefail

# End-to-end check for the v0.4 beginner sheet.  The project is temporary so
# running CI (or this script locally) never changes the documented example.
repo_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo_root"

if [[ -x .venv/bin/python ]]; then
  python_cmd=".venv/bin/python"
else
  python_cmd="python3"
fi

demo_root="$(mktemp -d "${TMPDIR:-/tmp}/csv-fcpxml-beginner.XXXXXX")"
trap 'rm -rf -- "$demo_root"' EXIT
mkdir -p "$demo_root/Media"
cp templates/simple_timeline.csv "$demo_root/timeline.csv"

# The template trims cafe_boot.mov from 12s to 16s, so this tiny synthetic
# source must be longer than 16 seconds.  Low resolution keeps the test fast;
# the FCPXML project resolution is verified independently by the validator.
ffmpeg -hide_banner -loglevel error -nostdin -y \
  -f lavfi -i "color=c=0x345995:s=320x180:r=30:d=17" \
  -f lavfi -i "sine=frequency=440:sample_rate=48000:duration=17" \
  -shortest -c:v libx264 -pix_fmt yuv420p -c:a aac \
  "$demo_root/Media/cafe_boot.mov"
ffmpeg -hide_banner -loglevel error -nostdin -y \
  -f lavfi -i "color=c=0xe8c547:s=320x180:r=1" -frames:v 1 \
  "$demo_root/Media/ipad_drawing.png"
ffmpeg -hide_banner -loglevel error -nostdin -y \
  -f lavfi -i "color=c=0x8f3985:s=320x180:r=30:d=2" \
  -f lavfi -i "sine=frequency=660:sample_rate=48000:duration=2" \
  -shortest -c:v libx264 -pix_fmt yuv420p -c:a aac \
  "$demo_root/Media/office.mp4"

"$python_cmd" make_xml.py "$demo_root" --project-name beginner_demo --layout both --validate-only
"$python_cmd" make_xml.py "$demo_root" --project-name beginner_demo --layout both --preview-only
"$python_cmd" make_xml.py "$demo_root" --project-name beginner_demo --layout both

portrait_root="$demo_root/Generated/vertical_9x16"
landscape_root="$demo_root/Generated/horizontal_16x9"

"$python_cmd" scripts/validate_fcpxml.py \
  --check-media --require-relative --project-root "$demo_root" \
  --expect-layout portrait --expect-fps 30 \
  "$portrait_root/beginner_demo_vertical_9x16_clean.fcpxml" \
  "$portrait_root/beginner_demo_vertical_9x16_with_titles.fcpxml"
"$python_cmd" scripts/validate_fcpxml.py \
  --check-media --require-relative --project-root "$demo_root" \
  --expect-layout landscape --expect-fps 30 \
  "$landscape_root/beginner_demo_horizontal_16x9_clean.fcpxml" \
  "$landscape_root/beginner_demo_horizontal_16x9_with_titles.fcpxml"

for variant_root in "$portrait_root" "$landscape_root"; do
  test -s "$variant_root/build_report.txt"
  grep -q "Timeline input: timeline.csv (CSV 파일)" "$variant_root/build_report.txt"
  if grep -q '.fcpxml_input_' "$variant_root/build_report.txt"; then
    echo "오류: 빌드 보고서에 삭제된 내부 CSV 경로가 남았습니다." >&2
    exit 2
  fi
  find "$variant_root/.build_media" -type f -name '*.mp4' -print -quit | grep -q .
done
test -s "$portrait_root/beginner_demo_vertical_9x16.srt"
test -s "$landscape_root/beginner_demo_horizontal_16x9.srt"
test -s "$demo_root/Generated/preview/index.html"
grep -q "숏폼 공통 안전영역" "$demo_root/Generated/preview/index.html"
grep -q "가로 보수적 안전영역" "$demo_root/Generated/preview/index.html"
if find "$demo_root" -maxdepth 1 -type d -name '.fcpxml_input_*' -print -quit | grep -q .; then
  echo "오류: 간편 CSV 임시 폴더가 정리되지 않았습니다." >&2
  exit 2
fi

echo "간편 CSV 성공: 세로 9:16 + 가로 16:9 Title/clean FCPXML + SRT"
