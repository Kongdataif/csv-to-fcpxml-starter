#!/usr/bin/env python3
"""timeline.csv와 Media 폴더를 Final Cut Pro용 FCPXML로 변환합니다.

기본 폴더 구조::

    my-video/
    ├── timeline.csv   # 장면 순서와 편집 정보
    └── Media/         # CSV의 '파일' 열에 적은 사진·영상

기본 실행::

    python3 run.py my-video --layout portrait --fit fit
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from fractions import Fraction
from pathlib import Path


VIDEO_EXTENSIONS = {".mov", ".mp4", ".m4v", ".mkv", ".avi"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic", ".tif", ".tiff"}
HEADERS = ("파일", "영상 원본 시작", "영상 원본 끝", "사진 표시 시간(초)", "화면 자막", "소리")
TITLE_UID = ".../Titles.localized/Bumper:Opener.localized/Basic Title.localized/Basic Title.moti"
FPS = Fraction(30)


class UserError(Exception):
    pass


@dataclass
class Clip:
    path: Path
    source_in: Fraction
    duration: Fraction
    media_duration: Fraction
    width: int
    height: int
    source_fps: Fraction
    has_audio: bool
    audio_channels: int
    audio_rate: int
    include_audio: bool
    title: str
    is_image: bool


def parse_seconds(value: str, label: str) -> Fraction:
    text = value.strip()
    if not text:
        return Fraction(0)
    parts = text.split(":")
    if len(parts) > 3:
        raise UserError(f"{label}: 시간은 초, MM:SS 또는 HH:MM:SS 형식이어야 합니다.")
    try:
        numbers = [Decimal(part) for part in parts]
    except InvalidOperation as exc:
        raise UserError(f"{label}: 시간을 읽을 수 없습니다: {value!r}") from exc
    if any(number < 0 for number in numbers):
        raise UserError(f"{label}: 음수 시간은 사용할 수 없습니다.")
    seconds = Decimal(0)
    for number in numbers:
        seconds = seconds * 60 + number
    return Fraction(seconds)


def frame_duration(seconds: Fraction, label: str) -> Fraction:
    frames = int((Decimal(seconds.numerator) * 30 / Decimal(seconds.denominator)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    if frames < 1:
        raise UserError(f"{label}: 길이는 최소 1프레임이어야 합니다.")
    return Fraction(frames, 30)


def xml_time(value: Fraction) -> str:
    if value.denominator == 1:
        return f"{value.numerator}s"
    return f"{value.numerator}/{value.denominator}s"


def run_command(command: list[str], error: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(command, check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise UserError("FFmpeg가 필요합니다. Mac에서는 `brew install ffmpeg`를 실행하세요.") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip().splitlines()
        raise UserError(f"{error}" + (f"\n{detail[-1]}" if detail else "")) from exc


def probe(path: Path) -> tuple[Fraction, int, int, Fraction, bool, int, int]:
    result = run_command(
        [
            "ffprobe", "-v", "error", "-show_entries",
            "format=duration:stream=codec_type,width,height,avg_frame_rate,channels,sample_rate",
            "-of", "json", str(path),
        ],
        f"미디어를 읽지 못했습니다: {path.name}",
    )
    try:
        payload = json.loads(result.stdout)
        streams = payload.get("streams", [])
        video = next(stream for stream in streams if stream.get("codec_type") == "video")
        duration_text = payload.get("format", {}).get("duration")
        duration = Fraction(Decimal(duration_text)) if duration_text not in {None, "N/A"} else Fraction(0)
        fps_text = video.get("avg_frame_rate", "30/1")
        source_fps = Fraction(fps_text) if fps_text not in {"0/0", "N/A"} else FPS
        audio = next((stream for stream in streams if stream.get("codec_type") == "audio"), None)
        return (
            duration, int(video["width"]), int(video["height"]), source_fps, audio is not None,
            int(audio.get("channels", 2)) if audio else 0,
            int(audio.get("sample_rate", 48000)) if audio else 0,
        )
    except (KeyError, StopIteration, ValueError, InvalidOperation, ZeroDivisionError) as exc:
        raise UserError(f"영상 정보를 확인하지 못했습니다: {path.name}") from exc


def read_timeline(project: Path) -> list[dict[str, str]]:
    csv_path = project / "timeline.csv"
    if not csv_path.is_file():
        raise UserError(f"파일이 없습니다: {csv_path}")
    try:
        with csv_path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None or "파일" not in reader.fieldnames:
                raise UserError("timeline.csv에 '파일' 열이 필요합니다.")
            unknown = [name for name in reader.fieldnames if name not in HEADERS]
            if unknown:
                raise UserError(f"지원하지 않는 CSV 열입니다: {', '.join(unknown)}")
            rows = [{key: (value or "").strip() for key, value in row.items()} for row in reader]
    except UnicodeDecodeError as exc:
        raise UserError("timeline.csv를 UTF-8 형식으로 저장하세요.") from exc
    rows = [row for row in rows if row.get("파일")]
    if not rows:
        raise UserError("timeline.csv에 장면을 한 개 이상 입력하세요.")
    return rows


def load_clips(project: Path) -> list[Clip]:
    media_dir = project / "Media"
    if not media_dir.is_dir():
        raise UserError(f"폴더가 없습니다: {media_dir}")
    clips: list[Clip] = []
    for row_number, row in enumerate(read_timeline(project), start=2):
        name = row["파일"]
        if Path(name).name != name or name in {".", ".."}:
            raise UserError(f"CSV {row_number}행: '파일'에는 Media 폴더 안의 파일명만 적으세요.")
        path = media_dir / name
        if not path.is_file():
            raise UserError(f"CSV {row_number}행: Media/{name} 파일이 없습니다.")
        suffix = path.suffix.lower()
        is_image = suffix in IMAGE_EXTENSIONS
        if suffix not in VIDEO_EXTENSIONS | IMAGE_EXTENSIONS:
            raise UserError(f"CSV {row_number}행: 지원하지 않는 파일 형식입니다: {name}")

        start_text = row.get("영상 원본 시작", "")
        end_text = row.get("영상 원본 끝", "")
        photo_text = row.get("사진 표시 시간(초)", "")
        if is_image:
            if start_text or end_text:
                raise UserError(f"CSV {row_number}행: 사진에는 영상 시작·끝을 입력하지 마세요.")
            duration = frame_duration(parse_seconds(photo_text or "3", f"CSV {row_number}행 사진 시간"), f"CSV {row_number}행")
            media_duration, width, height, source_fps, has_audio, audio_channels, audio_rate = (
                Fraction(0), 0, 0, FPS, False, 0, 0
            )
        else:
            if photo_text:
                raise UserError(f"CSV {row_number}행: 영상에는 사진 시간을 입력하지 마세요.")
            if bool(start_text) != bool(end_text):
                raise UserError(f"CSV {row_number}행: 영상 시작과 끝은 둘 다 입력하거나 둘 다 비우세요.")
            media_duration, width, height, source_fps, has_audio, audio_channels, audio_rate = probe(path)
            if media_duration <= 0:
                raise UserError(f"CSV {row_number}행: 영상 길이를 확인하지 못했습니다: {name}")
            source_in = parse_seconds(start_text, f"CSV {row_number}행 시작") if start_text else Fraction(0)
            source_out = parse_seconds(end_text, f"CSV {row_number}행 끝") if end_text else media_duration
            if source_out <= source_in or source_out > media_duration + Fraction(1, 1000):
                raise UserError(f"CSV {row_number}행: 영상 시작·끝 범위를 확인하세요.")
            duration = frame_duration(source_out - source_in, f"CSV {row_number}행")

        clips.append(
            Clip(
                path=path,
                source_in=Fraction(0) if is_image else source_in,
                duration=duration,
                media_duration=duration if is_image else media_duration,
                width=width,
                height=height,
                source_fps=source_fps,
                has_audio=has_audio,
                audio_channels=audio_channels,
                audio_rate=audio_rate,
                include_audio=(not is_image and has_audio and row.get("소리", "사용") not in {"끄기", "아니오", "false", "0"}),
                title=row.get("화면 자막", "").replace("\\n", "\n"),
                is_image=is_image,
            )
        )
    return clips


def render_image(clip: Clip, output: Path, width: int, height: int, fit: str) -> Path:
    cache = output / "media"
    cache.mkdir(parents=True, exist_ok=True)
    rendered = cache / f"{clip.path.stem}_{width}x{height}.mp4"
    if fit == "fit":
        video_filter = f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1"
    else:
        video_filter = f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},setsar=1"
    run_command(
        [
            "ffmpeg", "-y", "-loop", "1", "-i", str(clip.path), "-t", str(float(clip.duration)),
            "-vf", video_filter, "-r", "30", "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(rendered),
        ],
        f"사진을 영상으로 변환하지 못했습니다: {clip.path.name}",
    )
    clip.width, clip.height, clip.source_fps = width, height, FPS
    clip.media_duration = clip.duration
    return rendered


def media_uri(path: Path, xml_path: Path) -> str:
    relative = Path(os.path.relpath(path, xml_path.parent)).as_posix()
    return urllib.parse.quote(relative if relative.startswith(".") else f"./{relative}", safe="/.")


def add_title(parent: ET.Element, text_value: str, duration: Fraction, source_in: Fraction, index: int, portrait: bool) -> None:
    title = ET.SubElement(parent, "title", {
        "ref": "rBasicTitle", "name": f"Title {index:02d}", "lane": "1",
        "offset": xml_time(source_in), "start": "3600s", "duration": xml_time(duration), "role": "titles",
    })
    text = ET.SubElement(title, "text")
    ET.SubElement(text, "text-style", {"ref": f"ts{index:03d}"}).text = text_value
    style_def = ET.SubElement(title, "text-style-def", {"id": f"ts{index:03d}"})
    ET.SubElement(style_def, "text-style", {
        "font": "Apple SD Gothic Neo", "fontSize": "54" if portrait else "44",
        "fontFace": "Regular", "fontColor": "1 1 1 1", "alignment": "center",
        "strokeColor": "0 0 0 1", "strokeWidth": "-3",
    })
    ET.SubElement(title, "adjust-transform", {"position": "0 -37.5"})


def build(project: Path, layout: str, fit: str) -> Path:
    portrait = layout == "portrait"
    width, height = (1080, 1920) if portrait else (1920, 1080)
    output_dir = project / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    xml_path = output_dir / f"{layout}.fcpxml"
    clips = load_clips(project)

    root = ET.Element("fcpxml", {"version": "1.14"})
    resources = ET.SubElement(root, "resources")
    ET.SubElement(resources, "format", {
        "id": "rProjectFormat", "name": f"{width}x{height} 30p", "frameDuration": "1/30s",
        "width": str(width), "height": str(height), "colorSpace": "1-1-1 (Rec. 709)",
    })
    if any(clip.title for clip in clips):
        ET.SubElement(resources, "effect", {"id": "rBasicTitle", "name": "Basic Title", "uid": TITLE_UID})

    source_paths: list[Path] = []
    for index, clip in enumerate(clips, start=1):
        source = render_image(clip, output_dir, width, height, fit) if clip.is_image else clip.path
        source_paths.append(source)
        format_id, asset_id = f"rFormat{index:03d}", f"rAsset{index:03d}"
        ET.SubElement(resources, "format", {
            "id": format_id, "name": f"Source {source.name}",
            "frameDuration": xml_time(Fraction(1, 1) / clip.source_fps),
            "width": str(clip.width), "height": str(clip.height),
        })
        attrs = {
            "id": asset_id, "name": source.name, "start": "0s", "duration": xml_time(clip.media_duration),
            "hasVideo": "1", "videoSources": "1", "format": format_id,
        }
        if clip.has_audio:
            attrs.update({
                "hasAudio": "1", "audioSources": "1",
                "audioChannels": str(clip.audio_channels), "audioRate": str(clip.audio_rate),
            })
        asset = ET.SubElement(resources, "asset", attrs)
        ET.SubElement(asset, "media-rep", {"kind": "original-media", "src": media_uri(source, xml_path)})

    event = ET.SubElement(root, "event", {"name": "CSV to FCPXML"})
    project_xml = ET.SubElement(event, "project", {"name": f"{project.name} {layout}"})
    total = sum((clip.duration for clip in clips), Fraction(0))
    sequence = ET.SubElement(project_xml, "sequence", {
        "format": "rProjectFormat", "duration": xml_time(total), "tcStart": "0s", "tcFormat": "NDF",
        "audioLayout": "stereo", "audioRate": "48k",
    })
    spine = ET.SubElement(sequence, "spine")
    cursor = Fraction(0)
    for index, clip in enumerate(clips, start=1):
        attrs = {
            "ref": f"rAsset{index:03d}", "name": source_paths[index - 1].name,
            "offset": xml_time(cursor), "start": xml_time(clip.source_in),
            "duration": xml_time(clip.duration), "srcEnable": "all" if clip.include_audio else "video",
        }
        if clip.include_audio:
            attrs["audioRole"] = "dialogue"
        asset_clip = ET.SubElement(spine, "asset-clip", attrs)
        ET.SubElement(asset_clip, "adjust-conform", {"type": fit})
        if clip.title:
            add_title(asset_clip, clip.title, clip.duration, clip.source_in, index, portrait)
        cursor += clip.duration

    ET.indent(root, space="  ")
    body = ET.tostring(root, encoding="unicode", short_empty_elements=True)
    xml_path.write_text('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE fcpxml>\n' + body + "\n", encoding="utf-8")
    return xml_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="프로젝트 폴더의 timeline.csv와 Media/를 Final Cut Pro용 FCPXML로 변환합니다.",
        epilog=(
            "예: python3 run.py my-video --layout both --fit fit\n"
            "결과: my-video/output/portrait.fcpxml 및 landscape.fcpxml"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    # 위치 인자: CSV 파일 자체가 아니라 CSV와 Media가 함께 있는 폴더를 받습니다.
    parser.add_argument(
        "project",
        nargs="?",
        default="my-video",
        help="timeline.csv와 Media/가 들어 있는 프로젝트 폴더 (기본값: my-video)",
    )
    # 출력 해상도 선택. both는 두 FCPXML을 같은 output 폴더에 만듭니다.
    parser.add_argument(
        "--layout",
        choices=("portrait", "landscape", "both"),
        default="portrait",
        help=(
            "출력 화면: portrait=세로 1080x1920(기본값), "
            "landscape=가로 1920x1080, both=세로와 가로 모두 생성"
        ),
    )
    # 원본과 출력 화면의 비율이 다를 때 적용할 공통 배치 방식입니다.
    parser.add_argument(
        "--fit",
        choices=("fit", "fill"),
        default="fit",
        help=(
            "화면 맞춤: fit=원본 전체 표시·여백 가능(기본값), "
            "fill=화면을 채움·가장자리 잘림 가능"
        ),
    )
    args = parser.parse_args()
    project = Path(args.project).expanduser().resolve()
    if not project.is_dir():
        print(f"오류: 프로젝트 폴더가 없습니다: {project}", file=sys.stderr)
        return 1
    try:
        layouts = ("portrait", "landscape") if args.layout == "both" else (args.layout,)
        outputs = [build(project, layout, args.fit) for layout in layouts]
    except UserError as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1
    for output in outputs:
        print(f"완료: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
