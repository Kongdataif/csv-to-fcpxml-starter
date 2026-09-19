#!/usr/bin/env python3
"""CSV/XLSX + Media/ -> editable FCPXML. No complete video is exported.

Usage: python run.py my-video --layout both --fit fit
Output: my-video/output/{portrait,landscape}.fcpxml
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unicodedata
import urllib.parse
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from pathlib import Path

VERSION = "0.6.2-rc1"
VIDEO_EXTENSIONS = {".mov", ".mp4", ".m4v", ".mkv", ".avi"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic", ".tif", ".tiff"}
HEADERS = ("파일", "영상 원본 시작", "영상 원본 끝", "사진 표시 시간(초)", "화면 자막", "소리")
TITLE_UID = ".../Titles.localized/Bumper:Opener.localized/Basic Title.localized/Basic Title.moti"
FPS = Fraction(30)
LAYOUTS = {"portrait": (1080, 1920), "landscape": (1920, 1080)}


class UserError(Exception):
    """An actionable input/build error, not an internal traceback."""


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


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_json(path: Path, payload: dict) -> None:
    """Replace metadata only after the full new JSON has been written."""
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def filename(value: str) -> str:
    if (not value or value in {".", ".."} or "/" in value or "\\" in value
            or any(ord(c) < 32 for c in value) or ":" in value):
        raise UserError("'파일'에는 경로가 아닌 확장자를 포함한 파일명만 적으세요.")
    return unicodedata.normalize("NFC", value)


def media_index(directory: Path) -> dict[str, Path]:
    if not directory.is_dir() or directory.is_symlink():
        raise UserError(f"일반 폴더가 필요합니다: {directory}")
    result: dict[str, Path] = {}
    for path in directory.iterdir():
        if path.is_symlink():
            raise UserError(f"미디어 심볼릭 링크는 지원하지 않습니다: {path.name}")
        if not path.is_file():
            continue
        key = filename(path.name)
        if key in result:
            raise UserError(f"한글 정규화 후 파일명이 중복됩니다: {path.name}")
        result[key] = path
    return result


def parse_seconds(value: str, label: str) -> Fraction:
    text = value.strip()
    if not text:
        return Fraction(0)
    parts = text.split(":")
    if len(parts) > 3:
        raise UserError(f"{label}: 초, MM:SS 또는 HH:MM:SS.mmm 형식으로 적으세요.")
    try:
        numbers = [Decimal(part) for part in parts]
    except InvalidOperation as exc:
        raise UserError(f"{label}: 시간을 읽을 수 없습니다: {value!r}") from exc
    if any(not n.is_finite() or n < 0 for n in numbers):
        raise UserError(f"{label}: 유한한 0 이상의 시간을 적으세요.")
    if any(n != n.to_integral_value() for n in numbers[:-1]):
        raise UserError(f"{label}: 소수는 마지막 초 부분에만 적으세요.")
    if any(n >= 60 for n in numbers[1:]):
        raise UserError(f"{label}: 콜론 뒤 분·초는 60 미만이어야 합니다.")
    seconds = Fraction(0)
    for n in numbers:
        seconds = seconds * 60 + Fraction(n)
    return seconds


def frame_duration(seconds: Fraction, label: str) -> Fraction:
    frames = (seconds * FPS + Fraction(1, 2)).numerator // (seconds * FPS + Fraction(1, 2)).denominator
    if frames < 1:
        raise UserError(f"{label}: 길이는 최소 1프레임이어야 합니다.")
    return Fraction(frames, 30)


def xml_time(value: Fraction) -> str:
    return f"{value.numerator}s" if value.denominator == 1 else f"{value.numerator}/{value.denominator}s"


def run_command(command: list[str], error: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(command, check=True, capture_output=True, text=True, timeout=600 if command[0] == "ffmpeg" else 30)
    except subprocess.TimeoutExpired as exc:
        raise UserError(error + " (처리 시간이 초과되었습니다. 원본과 표시 시간을 확인하세요.)") from exc
    except FileNotFoundError as exc:
        raise UserError("FFmpeg와 ffprobe가 필요합니다. Mac: brew install ffmpeg") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip().splitlines()
        raise UserError(error + ("\n" + "\n".join(detail[-4:]) if detail else "")) from exc


def probe(path: Path) -> tuple[Fraction, int, int, Fraction, bool, int, int]:
    result = run_command([
        "ffprobe", "-v", "error", "-show_entries",
        "format=duration:stream=codec_type,width,height,duration,avg_frame_rate,channels,sample_rate",
        "-of", "json", str(path),
    ], f"미디어를 읽지 못했습니다: {path.name}")
    try:
        payload = json.loads(result.stdout)
        streams = payload.get("streams", [])
        video = next(s for s in streams if s.get("codec_type") == "video")
        duration_text = video.get("duration")
        if duration_text in {None, "N/A"}:
            duration_text = payload.get("format", {}).get("duration")
        duration = Fraction(Decimal(duration_text)) if duration_text not in {None, "N/A"} else Fraction(0)
        fps_text = video.get("avg_frame_rate", "30/1")
        source_fps = Fraction(fps_text) if fps_text not in {"0/0", "N/A"} else FPS
        width, height = int(video["width"]), int(video["height"])
        if width <= 0 or height <= 0 or source_fps <= 0:
            raise ValueError("invalid video format")
        audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
        return (duration, width, height, source_fps, audio is not None,
                int(audio.get("channels", 2)) if audio else 0,
                int(audio.get("sample_rate", 48000)) if audio else 0)
    except (KeyError, StopIteration, TypeError, ValueError, InvalidOperation, ZeroDivisionError) as exc:
        raise UserError(f"영상 정보를 확인하지 못했습니다: {path.name}") from exc


def xlsx_cell_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime) or isinstance(value, date):
        raise UserError("날짜 셀은 지원하지 않습니다. 원본 시간은 텍스트 또는 초 숫자로 입력하세요.")
    if isinstance(value, time):
        total = Fraction(value.hour * 3600 + value.minute * 60 + value.second) + Fraction(value.microsecond, 1000000)
        return str(float(total))
    if isinstance(value, timedelta):
        return str(value.total_seconds())
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else str(value)
    return str(value).strip()


def convert_xlsx(source: Path, target: Path) -> Path:
    """Read the timeline sheet, falling back to the active sheet. Reject formulas."""
    try:
        from openpyxl import load_workbook
    except ImportError as exc:
        raise UserError("Excel 입력 패키지가 필요합니다: python -m pip install -r requirements.txt") from exc
    try:
        workbook = load_workbook(source, read_only=True, data_only=False)
    except Exception as exc:
        raise UserError(f"Excel 파일을 읽지 못했습니다: {source.name}") from exc
    try:
        sheet = workbook["timeline"] if "timeline" in workbook.sheetnames else workbook.active
        rows = []
        for row in sheet.iter_rows():
            if any(cell.data_type in {"f", "e"} for cell in row):
                raise UserError(f"Excel {row[0].row}행: 수식·오류 셀 대신 계산된 값을 입력하세요.")
            rows.append([xlsx_cell_text(cell.value) for cell in row])
    finally:
        workbook.close()
    while rows and not any(rows[-1]):
        rows.pop()
    if not rows:
        raise UserError(f"Excel 시트가 비어 있습니다: {source.name}")
    width = max((i + 1 for row in rows for i, value in enumerate(row) if value), default=0)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8-sig", newline="") as handle:
        csv.writer(handle).writerows(row[:width] for row in rows)
    return target


def prepare_timeline(project: Path, output: Path | None = None) -> Path:
    candidates = [p for p in (project / "timeline.csv", project / "timeline.xlsx") if p.is_file()]
    if len(candidates) != 1:
        raise UserError("프로젝트 폴더에 timeline.csv 또는 timeline.xlsx 중 하나만 준비하세요. .numbers는 Excel로 내보내세요.")
    source = candidates[0]
    if source.is_symlink():
        raise UserError("기획표 심볼릭 링크는 지원하지 않습니다.")
    return source if source.suffix == ".csv" else convert_xlsx(source, (output or project / "output") / "timeline_converted.csv")


def read_timeline(csv_path: Path) -> list[dict[str, str]]:
    rows = []
    try:
        with csv_path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle, strict=True)
            headers = reader.fieldnames
            if not headers or "파일" not in headers:
                raise UserError("기획표 첫 행에 '파일' 열이 필요합니다.")
            if len(headers) != len(set(headers)):
                raise UserError("기획표에 중복된 열 이름이 있습니다.")
            unknown = [h for h in headers if h not in HEADERS]
            if unknown:
                raise UserError(f"지원하지 않는 열 이름: {', '.join(unknown)}. 양식 첫 행을 유지하세요.")
            while True:
                row = next(reader, None)
                if row is None:
                    break
                line = reader.line_num
                if None in row:
                    raise UserError(f"CSV {line}행: 열 수가 맞지 않습니다. 쉼표가 있는 문장은 따옴표로 감싸세요.")
                values = {k: (v or "").strip() for k, v in row.items()}
                if not any(values.values()):
                    continue
                if not values.get("파일"):
                    raise UserError(f"CSV {line}행: 내용이 있지만 파일명이 비어 있습니다.")
                if any(v is None for v in row.values()):
                    raise UserError(f"CSV {line}행: 일부 열이 누락되었습니다. 빈칸도 CSV 구분자를 유지하세요.")
                try:
                    filename(values["파일"])
                except UserError as exc:
                    raise UserError(f"CSV {line}행: {exc}") from exc
                values["__line__"] = str(line)
                rows.append(values)
    except (UnicodeDecodeError, csv.Error) as exc:
        raise UserError("기획표를 올바른 UTF-8 CSV 형식으로 저장하세요.") from exc
    if not rows:
        raise UserError("기획표에 장면을 한 개 이상 입력하세요.")
    return rows


def load_clips(project: Path, timeline_path: Path) -> list[Clip]:
    index = media_index(project / "Media")
    clips = []
    for row in read_timeline(timeline_path):
        label = f"CSV {row['__line__']}행"
        path = index.get(filename(row["파일"]))
        if path is None:
            raise UserError(f"{label}: Media/{row['파일']} 파일이 없습니다.")
        is_image = path.suffix.lower() in IMAGE_EXTENSIONS
        if path.suffix.lower() not in VIDEO_EXTENSIONS | IMAGE_EXTENSIONS:
            raise UserError(f"{label}: 지원하지 않는 미디어 형식입니다: {path.name}")
        start, end, photo = (row.get(k, "") for k in HEADERS[1:4])
        sound = row.get("소리", "").lower()
        if sound not in {"", "사용", "끄기", "예", "아니오", "true", "false", "1", "0"}:
            raise UserError(f"{label}: 소리는 '사용' 또는 '끄기'로 적으세요.")
        if is_image:
            if start or end:
                raise UserError(f"{label}: 사진에는 영상 원본 시작·끝을 입력하지 마세요.")
            duration = frame_duration(parse_seconds(photo or "3", label), label)
            source_in = Fraction(0)
            media_duration, width, height, source_fps, has_audio, channels, rate = (duration, 0, 0, FPS, False, 0, 0)
        else:
            if photo or bool(start) != bool(end):
                raise UserError(f"{label}: 영상의 사진 시간은 비우고, 시작·끝은 둘 다 입력하거나 둘 다 비우세요.")
            media_duration, width, height, source_fps, has_audio, channels, rate = probe(path)
            source_in = parse_seconds(start, label) if start else Fraction(0)
            source_out = parse_seconds(end, label) if end else media_duration
            if source_out <= source_in or source_out > media_duration:
                raise UserError(f"{label}: 원본 길이 안에서 시작 < 끝이 되도록 적으세요.")
            duration = frame_duration(source_out - source_in, label)
            if source_in + duration > media_duration:
                duration = Fraction(int((media_duration - source_in) * FPS), 30)
                if duration <= 0:
                    raise UserError(f"{label}: 원본 안에 1프레임 분량이 남아 있지 않습니다.")
        clips.append(Clip(path, source_in, duration, media_duration, width, height, source_fps,
                          has_audio, channels, rate, not is_image and has_audio and sound not in {"끄기", "아니오", "false", "0"},
                          row.get("화면 자막", "").replace("\\n", "\n"), is_image))
    return clips


def image_cache_key(clip: Clip, width: int, height: int, fit: str) -> str:
    spec = ["photo-v2", filename(clip.path.name), digest(clip.path), str(clip.duration), width, height, fit, str(FPS)]
    return hashlib.sha256(json.dumps(spec, ensure_ascii=False).encode()).hexdigest()


def render_image(clip: Clip, output: Path, width: int, height: int, fit: str) -> Path:
    cache = output / "media"
    cache.mkdir(parents=True, exist_ok=True)
    rendered = cache / f"photo_{image_cache_key(clip, width, height, fit)}.mp4"
    if not rendered.exists():
        probe(clip.path)  # Reject corrupt input before an infinite image-loop decoder.
        if fit == "fit":
            vf = f"scale={width}:{height}:force_original_aspect_ratio=decrease:force_divisible_by=2,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1"
        else:
            vf = f"scale={width}:{height}:force_original_aspect_ratio=increase:force_divisible_by=2,crop={width}:{height},setsar=1"
        run_command([
            "ffmpeg", "-v", "error", "-xerror", "-y", "-loop", "1", "-framerate", "30", "-i", str(clip.path),
            "-vf", vf, "-frames:v", str(int(clip.duration * FPS)), "-r", "30", "-an",
            "-c:v", "libx264", "-threads", "2", "-pix_fmt", "yuv420p", str(rendered),
        ], f"사진 변환 실패: {clip.path.name}. HEIC 등은 PNG/JPG로 내보낸 뒤 다시 시도하세요.")
    actual, _, _, _, _, _, _ = probe(rendered)
    if abs(actual - clip.duration) > Fraction(1, 1000):
        raise UserError(f"사진 캐시 길이 검증 실패: {clip.path.name}")
    clip.width, clip.height, clip.source_fps, clip.media_duration = width, height, FPS, clip.duration
    return rendered


def media_uri(path: Path, xml_path: Path) -> str:
    relative = Path(os.path.relpath(path, xml_path.parent)).as_posix()
    return urllib.parse.quote(relative if relative.startswith(".") else "./" + relative, safe="/.")


def add_title(parent: ET.Element, clip: Clip, index: int, portrait: bool) -> None:
    title = ET.SubElement(parent, "title", {"ref": "rBasicTitle", "name": f"Title {index:02d}", "lane": "1",
        "offset": xml_time(clip.source_in), "start": "3600s", "duration": xml_time(clip.duration), "role": "titles"})
    # FCPXML 1.14: text and text-style-def precede intrinsic video adjustments.
    text = ET.SubElement(title, "text")
    ET.SubElement(text, "text-style", {"ref": f"ts{index:03d}"}).text = clip.title
    style_def = ET.SubElement(title, "text-style-def", {"id": f"ts{index:03d}"})
    ET.SubElement(style_def, "text-style", {"font": "Apple SD Gothic Neo", "fontSize": "54" if portrait else "44",
        "fontFace": "Regular", "fontColor": "1 1 1 1", "alignment": "center", "strokeColor": "0 0 0 1", "strokeWidth": "-3"})
    ET.SubElement(title, "adjust-transform", {"position": "0 -37.5"})


def build(project: Path, layout: str, fit: str, timeline_path: Path, output: Path | None = None) -> Path:
    width, height = LAYOUTS[layout]
    output = output or project / "output"
    output.mkdir(parents=True, exist_ok=True)
    xml_path = output / f"{layout}.fcpxml"
    clips = load_clips(project, timeline_path)
    root = ET.Element("fcpxml", {"version": "1.14"})
    resources = ET.SubElement(root, "resources")
    ET.SubElement(resources, "format", {"id": "rProjectFormat", "name": f"{width}x{height} 30p", "frameDuration": "1/30s",
        "width": str(width), "height": str(height), "colorSpace": "1-1-1 (Rec. 709)"})
    if any(c.title for c in clips):
        ET.SubElement(resources, "effect", {"id": "rBasicTitle", "name": "Basic Title", "uid": TITLE_UID})
    sources = []
    for i, clip in enumerate(clips, 1):
        source = render_image(clip, output, width, height, fit) if clip.is_image else clip.path
        sources.append(source)
        ET.SubElement(resources, "format", {"id": f"rFormat{i:03d}", "name": f"Source {source.name}",
            "frameDuration": xml_time(1 / clip.source_fps), "width": str(clip.width), "height": str(clip.height)})
        attrs = {"id": f"rAsset{i:03d}", "name": source.name, "start": "0s", "duration": xml_time(clip.media_duration),
                 "hasVideo": "1", "videoSources": "1", "format": f"rFormat{i:03d}"}
        if clip.has_audio:
            attrs.update(hasAudio="1", audioSources="1", audioChannels=str(clip.audio_channels), audioRate=str(clip.audio_rate))
        asset = ET.SubElement(resources, "asset", attrs)
        ET.SubElement(asset, "media-rep", {"kind": "original-media", "src": media_uri(source, xml_path)})
    event = ET.SubElement(root, "event", {"name": "CSV to FCPXML"})
    project_xml = ET.SubElement(event, "project", {"name": f"{project.name} {layout}"})
    sequence = ET.SubElement(project_xml, "sequence", {"format": "rProjectFormat", "duration": xml_time(sum((c.duration for c in clips), Fraction(0))),
        "tcStart": "0s", "tcFormat": "NDF", "audioLayout": "stereo", "audioRate": "48k"})
    spine = ET.SubElement(sequence, "spine")
    cursor = Fraction(0)
    for i, clip in enumerate(clips, 1):
        attrs = {"ref": f"rAsset{i:03d}", "name": sources[i - 1].name, "offset": xml_time(cursor), "start": xml_time(clip.source_in),
                 "duration": xml_time(clip.duration), "srcEnable": "all" if clip.include_audio else "video"}
        if clip.include_audio:
            attrs["audioRole"] = "dialogue"
        node = ET.SubElement(spine, "asset-clip", attrs)
        ET.SubElement(node, "adjust-conform", {"type": fit})
        if clip.title:
            add_title(node, clip, i, layout == "portrait")
        if clip.has_audio and not clip.include_audio:
            # Explicitly deactivate every source channel, in addition to selecting
            # video only. FCPXML places audio components after anchored titles.
            ET.SubElement(node, "audio-channel-source", {
                "srcCh": ", ".join(str(channel) for channel in range(1, clip.audio_channels + 1)),
                "role": "dialogue", "active": "0",
            })
        cursor += clip.duration
    ET.indent(root, space="  ")
    xml_path.write_text('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE fcpxml>\n' + ET.tostring(root, encoding="unicode") + "\n", encoding="utf-8")
    validate_xml(xml_path, width, height)
    return xml_path


def validate_xml(path: Path, width: int, height: int) -> None:
    """Structural/reference/timing checks for our subset. NOT full Apple DTD validation."""
    root = ET.parse(path).getroot()
    if root.tag != "fcpxml" or root.get("version") != "1.14":
        raise UserError("FCPXML 버전 검증 실패")
    ids = [n.get("id") for n in root.iter() if n.get("id")]
    if len(ids) != len(set(ids)) or any(n.get("ref") not in ids for n in root.iter() if n.get("ref")):
        raise UserError("FCPXML 리소스 참조 검증 실패")
    fmt = root.find("resources/format")
    if fmt is None or (fmt.get("width"), fmt.get("height"), fmt.get("frameDuration")) != (str(width), str(height), "1/30s"):
        raise UserError("해상도·FPS 검증 실패")
    for media in root.findall("resources/asset/media-rep"):
        uri = media.get("src", "")
        if urllib.parse.urlsplit(uri).scheme or not (path.parent / urllib.parse.unquote(uri)).is_file():
            raise UserError(f"미디어 상대 경로 검증 실패: {uri}")
    # This generator emits exactly one text block, one style definition and
    # one transform. Check this narrow contract, not a hand-written full DTD.
    # A well-formed XML document alone cannot catch invalid child ordering.
    for title in root.iter("title"):
        if [child.tag for child in title] != ["text", "text-style-def", "adjust-transform"]:
            raise UserError(
                f"FCPXML 타이틀 구성 오류 ({title.get('name', 'title')}): "
                "text → text-style-def → adjust-transform 순서가 필요합니다."
            )
    cursor = Fraction(0)
    sequence = root.find("event/project/sequence")
    if sequence is None:
        raise UserError("타임라인이 없습니다.")
    for clip in sequence.findall("spine/asset-clip"):
        duration = Fraction(clip.get("duration", "0s")[:-1])
        if Fraction(clip.get("offset", "0s")[:-1]) != cursor or duration <= 0 or (duration * FPS).denominator != 1:
            raise UserError("타임라인 시간 검증 실패")
        cursor += duration
    if cursor <= 0 or Fraction(sequence.get("duration", "0s")[:-1]) != cursor:
        raise UserError("전체 길이 검증 실패")


def invalidate_result(project: Path, reason: str) -> None:
    write_json(project / ".last_build.json", {"status": "invalid", "reason": reason})


def build_project(project: Path, layout: str = "portrait", fit: str = "fit") -> list[Path]:
    project = project.resolve()
    if not project.is_dir():
        raise UserError(f"프로젝트 폴더가 없습니다: {project}")
    lock = project / ".fcpxml.lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise UserError("이 폴더에서 다른 변환이 실행 중입니다. 강제 종료 후라면 실행 중인 변환이 없는지 확인하고 .fcpxml.lock만 삭제하세요.") from exc
    os.close(fd)
    stage = None
    build_id = uuid.uuid4().hex
    try:
        invalidate_result(project, "이번 변환이 아직 성공하지 않았습니다.")
        if layout not in {*LAYOUTS, "both"} or fit not in {"fit", "fill"}:
            raise UserError("layout/fit 설정이 올바르지 않습니다.")
        stage = Path(tempfile.mkdtemp(prefix=".fcpxml-build-", dir=project))
        timeline = prepare_timeline(project, stage)
        clips = load_clips(project, timeline)
        plan = next(p for p in (project / "timeline.csv", project / "timeline.xlsx") if p.is_file())
        inputs = {p.relative_to(project).as_posix(): digest(p) for p in {plan, *(c.path for c in clips)}}
        layouts = tuple(LAYOUTS) if layout == "both" else (layout,)
        outputs = [build(project, direction, fit, timeline, stage) for direction in layouts]
        if any(digest(project / name) != sha for name, sha in inputs.items()):
            raise UserError("변환 중 입력 파일이 바뀌었습니다. 다시 실행하세요.")
        generated = {"output/" + p.relative_to(stage).as_posix(): digest(p) for p in stage.rglob("*") if p.is_file()}
        report = {"version": VERSION, "build_id": build_id, "layout": layout, "fit": fit,
                  "validation": "structural checks only; Final Cut Pro import not verified",
                  "files": {**inputs, **generated}}
        write_json(stage / "build_report.json", report)
        target = project / "output"
        if target.is_symlink() or (target.exists() and not target.is_dir()):
            raise UserError("output은 일반 폴더여야 합니다.")
        previous = project / (".previous-output-" + build_id)
        if target.exists():
            os.replace(target, previous)
        try:
            os.replace(stage, target)
            stage = None
        except OSError:
            if previous.exists():
                os.replace(previous, target)
            raise
        write_json(project / ".last_build.json", {"status": "success", "build_id": build_id,
                   "report_sha256": digest(target / "build_report.json")})
        return [target / p.name for p in outputs]
    except BaseException as exc:
        invalidate_result(project, str(exc) or type(exc).__name__)
        raise
    finally:
        if stage is not None:
            shutil.rmtree(stage, ignore_errors=True)
        lock.unlink(missing_ok=True)


def verified_result(project: Path) -> dict:
    """Only the latest successful build, with unchanged inputs AND outputs, is usable."""
    try:
        state = json.loads((project / ".last_build.json").read_text(encoding="utf-8"))
        report_path = project / "output" / "build_report.json"
        if state.get("status") != "success" or digest(report_path) != state.get("report_sha256"):
            raise UserError("이번 실행의 성공한 결과가 없습니다. 4번 변환을 다시 실행하세요.")
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if report["build_id"] != state["build_id"] or not report["files"]:
            raise UserError("결과 식별자가 일치하지 않습니다.")
        for name, sha in report["files"].items():
            relative = Path(name)
            path = project / relative
            if relative.is_absolute() or ".." in relative.parts or any((project / Path(*relative.parts[:i])).is_symlink() for i in range(1, len(relative.parts) + 1)):
                raise UserError("결과 안의 안전하지 않은 경로를 발견했습니다.")
            if digest(path) != sha:
                raise UserError(f"변환 후 파일이 변경되었습니다: {name}. 다시 변환하세요.")
        return report
    except (OSError, KeyError, ValueError, TypeError) as exc:
        raise UserError("검증된 결과가 없거나 파일이 누락되었습니다. 4번 변환부터 다시 실행하세요.") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description="CSV/XLSX + Media를 FCPXML로 변환합니다.")
    parser.add_argument("project", nargs="?", default="my-video")
    parser.add_argument("--layout", choices=(*LAYOUTS, "both"), default="portrait")
    parser.add_argument("--fit", choices=("fit", "fill"), default="fit")
    parser.add_argument("--version", action="version", version=VERSION)
    args = parser.parse_args()
    try:
        for output in build_project(Path(args.project).expanduser(), args.layout, args.fit):
            print(f"완료: {output}")
    except (UserError, OSError) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
