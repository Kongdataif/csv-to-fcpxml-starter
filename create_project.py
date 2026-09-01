#!/usr/bin/env python3
"""Create a safe, editable CSV-to-FCPXML project skeleton."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path


DEFAULT_CONFIG = {
    "event_name": "CSV Automation",
    "project_name": "My CSV Rough Cut",
    "output_basename": "my_roughcut",
    "fcpxml_version": "1.14",
    "width": 1920,
    "height": 1080,
    "fps": "30",
    "color_space": "1-1-1 (Rec. 709)",
    "audio_rate": "48k",
    "timeline_csv": "timeline.csv",
    "output_dir": "Generated",
    "path_mode": "relative",
    "image_mode": "video-cache",
    "image_background": "#000000",
    "bgm": None,
    "subtitles": {},
    "captions": {},
}
DEFAULT_TIMELINE = (
    "id,kind,file,timeline_in,timeline_out,source_in,source_out,conform,include_audio,volume_db,notes,enabled\n"
    "V01,video,Media/replace_with_your_video.mp4,00:00:00.000,00:00:04.000,00:00:00.000,"
    "00:00:04.000,fit,false,0,첫 장면,true\n"
    "I01,image,Media/replace_with_your_photo.png,00:00:04.000,00:00:07.000,,,fill,false,0,사진 3초,true\n"
)
DEFAULT_CAPTIONS = (
    "id,start,end,text,notes\n"
    "C01,00:00:00.200,00:00:03.800,첫 번째 자막,첫 장면\n"
    "C02,00:00:04.200,00:00:06.800,두 번째 자막,사진 장면\n"
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="새 CSV → FCPXML 프로젝트 폴더를 만듭니다.")
    parser.add_argument("target", help="새 프로젝트 폴더 경로")
    parser.add_argument("--portrait", action="store_true", help="1080×1920 세로 프로젝트로 생성")
    parser.add_argument("--fps", default="30", help="프로젝트 fps (예: 30, 30000/1001)")
    subtitle_group = parser.add_mutually_exclusive_group()
    subtitle_group.add_argument(
        "--with-subtitles",
        action="store_true",
        help="일반 화면 자막 Title + SRT 설정을 켭니다 (추천)",
    )
    subtitle_group.add_argument(
        "--with-captions",
        action="store_true",
        help="기존 iTT 접근성 캡션 + SRT 설정을 켭니다",
    )
    parser.add_argument(
        "--subtitle-mode",
        choices=("title", "caption", "both", "off"),
        default="title",
        help="--with-subtitles 결과 방식. 기본 title",
    )
    args = parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parent
    template_root = repo_root / "templates"
    target = Path(args.target).expanduser().resolve()

    if target.exists():
        if not target.is_dir():
            print(f"오류: 대상 경로가 폴더가 아닙니다: {target}", file=sys.stderr)
            return 2
        if any(target.iterdir()):
            print(f"오류: 비어 있지 않은 폴더에는 만들지 않습니다: {target}", file=sys.stderr)
            return 2

    target.mkdir(parents=True, exist_ok=True)
    for directory in ("Media", "Audio", "Docs", "Generated"):
        (target / directory).mkdir(exist_ok=True)

    timeline_template = template_root / "timeline_template.csv"
    captions_template = template_root / "captions_template.csv"
    subtitles_template = template_root / "subtitles_template.csv"
    project_template = template_root / "project_template.json"
    if timeline_template.exists():
        shutil.copy2(timeline_template, target / "timeline.csv")
    else:
        (target / "timeline.csv").write_text(DEFAULT_TIMELINE, encoding="utf-8-sig")
    if args.with_subtitles:
        source = subtitles_template if subtitles_template.exists() else captions_template
        if source.exists():
            shutil.copy2(source, target / "Docs" / "subtitles.csv")
        else:
            (target / "Docs" / "subtitles.csv").write_text(DEFAULT_CAPTIONS, encoding="utf-8-sig")
    if args.with_captions:
        if captions_template.exists():
            shutil.copy2(captions_template, target / "Docs" / "captions.csv")
        else:
            (target / "Docs" / "captions.csv").write_text(DEFAULT_CAPTIONS, encoding="utf-8-sig")

    if project_template.exists():
        config = json.loads(project_template.read_text(encoding="utf-8"))
    else:
        config = dict(DEFAULT_CONFIG)
    config["project_name"] = target.name
    config["event_name"] = f"{target.name} · CSV Automation"
    config["output_basename"] = (
        re.sub(r"[^0-9A-Za-z가-힣._-]+", "_", target.name).strip("_") or "my_roughcut"
    )
    config["fps"] = args.fps
    if args.portrait:
        config["width"], config["height"] = 1080, 1920
    if args.with_subtitles:
        config["subtitles"] = {
            "file": "Docs/subtitles.csv",
            "mode": args.subtitle_mode,
            "srt": True,
            "role": "Subtitles",
            "font": "Apple SD Gothic Neo",
            "font_size": 44,
            "alignment": "center",
            "outline_color": "0 0 0 1",
            "outline_width": -3,
            "shadow": True,
            "shadow_color": "0 0 0 0.75",
            "shadow_offset": "2 -2",
            "shadow_blur_radius": 3,
            "prefix": "",
            "wrap_width": 20,
            "prefix_color": "0.447059 0.945098 1 1",
            "body_color": "1 1 1 1",
            "format": "ITT",
            "language": "ko-KR",
            "placement": "bottom"
        }
        config["captions"] = {}
    if args.with_captions:
        config["captions"] = {
            "file": "Docs/captions.csv",
            "embed": True,
            "format": "ITT",
            "role": "Captions",
            "language": "ko-KR",
            "placement": "bottom",
            "prefix": "",
            "wrap_width": 20,
            "prefix_color": "1 1 1 1",
            "body_color": "1 1 1 1",
            "background_color": "0 0 0 0.9",
            "bold": True,
        }
        config["subtitles"] = {}

    (target / "project.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(f"프로젝트 뼈대를 만들었습니다: {target}")
    print("1) Media/에 영상·사진을 넣습니다.")
    print("2) timeline.csv의 파일명과 시간을 수정합니다.")
    print("3) 화면 자막은 subtitles.mode=title, 접근성 캡션은 caption을 사용합니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
