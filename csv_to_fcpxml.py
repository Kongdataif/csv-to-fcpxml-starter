#!/usr/bin/env python3
"""Build a Final Cut Pro rough-cut FCPXML project from CSV files.

The script intentionally focuses on deterministic, repeatable work:
- lay video or still-image rows onto the primary storyline
- trim video with source-in/source-out values
- optionally retain source audio
- attach one BGM file
- generate ordinary editable Basic Title subtitles from a dialogue CSV
- optionally generate iTT captions and an SRT sidecar

It does not try to make editorial decisions, transitions, color grades, or
complex retiming. Those remain Final Cut Pro work.

Python dependencies: standard library only.
External tools: ffprobe (validation); ffmpeg only when image_mode=video-cache.
"""

from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from pathlib import Path
from typing import Any, Iterable

__version__ = "0.6.0"

VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm"}
FCP_FRIENDLY_VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".heic", ".webp", ".bmp"}
AUDIO_EXTENSIONS = {".m4a", ".wav", ".aif", ".aiff", ".mp3", ".aac", ".flac"}
COMMON_FPS = {
    "23.976": Fraction(24000, 1001),
    "29.97": Fraction(30000, 1001),
    "59.94": Fraction(60000, 1001),
}
BASIC_TITLE_UID = ".../Titles.localized/Bumper:Opener.localized/Basic Title.localized/Basic Title.moti"
SUBTITLE_MODES = {"title", "caption", "both", "off"}

# The public CLI uses editing-oriented names (portrait/landscape), while the
# output folders describe the actual frame. Keeping the profile in one place
# prevents the Final Cut project format, output filename, cache location and
# title defaults from drifting apart.
LAYOUT_PROFILES: dict[str, dict[str, Any]] = {
    "portrait": {
        "width": 1080,
        "height": 1920,
        "folder": "vertical_9x16",
        "project_suffix": "[세로 9:16]",
        "basename_suffix": "vertical_9x16",
        # Reels/Shorts controls occupy much of the lower edge. This places the
        # title centre 37.5% above the bottom instead of reusing a portrait-only
        # pixel offset in every project size.
        "title_y_percent": "-12.5",
        "wrap_width": 18,
    },
    "landscape": {
        "width": 1920,
        "height": 1080,
        "folder": "horizontal_16x9",
        "project_suffix": "[가로 16:9]",
        "basename_suffix": "horizontal_16x9",
        "title_y_percent": "-37.5",
        "wrap_width": 30,
    },
}

# Uploaded media is untrusted input.  A damaged container must not leave a
# Colab cell or CI job hanging forever.  Probing should normally take under a
# second; image rendering gets a much larger ceiling because it intentionally
# encodes one short cache video per still image.
FFPROBE_TIMEOUT_SECONDS = 60
FFMPEG_TIMEOUT_SECONDS = 15 * 60
EXTERNAL_DIAGNOSTIC_MAX_CHARS = 2_000

# FFmpeg can echo untrusted container metadata to stderr.  Remove terminal
# control sequences before that text reaches a notebook, CI log or shell.  OSC
# covers hyperlinks/window-title changes, CSI covers colours/cursor commands,
# and the remaining branches cover the other ECMA-48 escape-string families.
_ANSI_ESCAPE_RE = re.compile(
    r"""
    \x1b(?:
        \][^\x07\x1b]*(?:\x07|\x1b\\|$)
      | P[^\x1b]*(?:\x1b\\|$)
      | [X^_][^\x1b]*(?:\x1b\\|$)
      | \[[0-?]*[ -/]*[@-~]
      | [@-_]
    )
    """,
    re.VERBOSE,
)
_TERMINAL_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")


class BuildError(RuntimeError):
    """A user-correctable project configuration or media error."""


def sanitize_external_diagnostic(
    value: object,
    *,
    max_chars: int = EXTERNAL_DIAGNOSTIC_MAX_CHARS,
) -> str:
    """Return bounded, single-line text safe to print in a terminal.

    Media metadata is attacker-controlled, and ffprobe/ffmpeg may copy it into
    stderr.  In particular, ANSI OSC hyperlinks and CSI cursor commands must
    never be passed through to the user's terminal.  C0/C1 controls are
    replaced with spaces, whitespace is collapsed, and very large diagnostics
    are truncated without hiding that truncation occurred.
    """

    if max_chars < 1:
        raise ValueError("max_chars must be at least 1")
    text = str(value or "")
    text = _ANSI_ESCAPE_RE.sub("", text)
    text = _TERMINAL_CONTROL_RE.sub(" ", text)
    text = " ".join(text.split())
    if not text:
        return "(진단 내용 없음)"[:max_chars]
    if len(text) <= max_chars:
        return text

    marker = " …(이하 생략)"
    if max_chars <= len(marker):
        return marker[-max_chars:]
    return text[: max_chars - len(marker)].rstrip() + marker


def utf8_prefix(value: str, max_bytes: int) -> str:
    """Return the longest whole-character prefix within ``max_bytes``.

    Filename component limits are byte based on the Colab/Linux and common
    Mac filesystems.  Slicing Python characters alone can therefore accept a
    Korean name that later fails with ``ENAMETOOLONG``.  Building the prefix a
    character at a time also guarantees that UTF-8 is never cut mid-sequence.
    """

    if max_bytes < 0:
        raise ValueError("max_bytes must be zero or greater")
    pieces: list[str] = []
    used_bytes = 0
    for character in str(value):
        character_bytes = len(character.encode("utf-8"))
        if used_bytes + character_bytes > max_bytes:
            break
        pieces.append(character)
        used_bytes += character_bytes
    return "".join(pieces)


@dataclass(frozen=True)
class MediaInfo:
    duration: Fraction | None
    width: int | None
    height: int | None
    fps: Fraction | None
    has_video: bool
    has_audio: bool
    audio_rate: int | None
    audio_channels: int | None
    video_duration: Fraction | None = None


@dataclass
class ClipRow:
    row_number: int
    clip_id: str
    kind: str
    file_text: str
    file_path: Path
    timeline_in: Fraction
    timeline_out: Fraction
    source_in: Fraction
    source_out: Fraction
    conform: str
    include_audio: bool
    volume_db: Decimal
    notes: str
    media_info: MediaInfo | None = None
    asset_id: str = ""
    format_id: str = ""

    @property
    def timeline_duration(self) -> Fraction:
        return self.timeline_out - self.timeline_in

    @property
    def source_duration(self) -> Fraction:
        return self.source_out - self.source_in


@dataclass(frozen=True)
class CaptionRow:
    caption_id: str
    start: Fraction
    end: Fraction
    text: str
    notes: str

    @property
    def duration(self) -> Fraction:
        return self.end - self.start


@dataclass(frozen=True)
class AudioBed:
    path: Path
    media_info: MediaInfo
    timeline_start: Fraction
    source_in: Fraction
    duration: Fraction
    volume_db: Decimal
    role: str

    @property
    def timeline_end(self) -> Fraction:
        return self.timeline_start + self.duration


@dataclass(frozen=True)
class SubtitleOptions:
    """Normalized subtitle settings for both the new and legacy config shapes."""

    file_text: str | None
    mode: str
    generate_srt: bool
    config: dict[str, Any]
    legacy: bool = False


@dataclass(frozen=True)
class MediaInputPolicy:
    """Pinned FFmpeg demuxer and options for one accepted file extension."""

    kind: str
    demuxer: str
    demuxer_options: tuple[str, ...] = ()


_MOV_SAFE_OPTIONS = (
    # QuickTime data references and aliases can point at another local file.
    # They are unnecessary for ordinary self-contained MOV/MP4/M4A/HEIC input
    # and must stay disabled even if a future FFmpeg build changes defaults.
    "-enable_drefs",
    "0",
    "-use_absolute_path",
    "0",
)
MEDIA_INPUT_POLICIES: dict[str, MediaInputPolicy] = {
    ".mp4": MediaInputPolicy("video", "mov", _MOV_SAFE_OPTIONS),
    ".mov": MediaInputPolicy("video", "mov", _MOV_SAFE_OPTIONS),
    ".m4v": MediaInputPolicy("video", "mov", _MOV_SAFE_OPTIONS),
    ".avi": MediaInputPolicy("video", "avi"),
    ".mkv": MediaInputPolicy("video", "matroska,webm"),
    ".webm": MediaInputPolicy("video", "matroska,webm"),
    ".jpg": MediaInputPolicy("image", "image2", ("-pattern_type", "none")),
    ".jpeg": MediaInputPolicy("image", "image2", ("-pattern_type", "none")),
    ".png": MediaInputPolicy("image", "image2", ("-pattern_type", "none")),
    ".tif": MediaInputPolicy("image", "image2", ("-pattern_type", "none")),
    ".tiff": MediaInputPolicy("image", "image2", ("-pattern_type", "none")),
    ".webp": MediaInputPolicy("image", "image2", ("-pattern_type", "none")),
    ".bmp": MediaInputPolicy("image", "image2", ("-pattern_type", "none")),
    ".heic": MediaInputPolicy("image", "mov", _MOV_SAFE_OPTIONS),
    ".m4a": MediaInputPolicy("audio", "mov", _MOV_SAFE_OPTIONS),
    ".wav": MediaInputPolicy("audio", "wav"),
    ".aif": MediaInputPolicy("audio", "aiff"),
    ".aiff": MediaInputPolicy("audio", "aiff"),
    ".mp3": MediaInputPolicy("audio", "mp3"),
    ".aac": MediaInputPolicy("audio", "aac"),
    ".flac": MediaInputPolicy("audio", "flac"),
}


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def decimal_to_fraction(value: str | int | float | Decimal) -> Fraction:
    try:
        decimal_value = Decimal(str(value))
        if not decimal_value.is_finite():
            raise ValueError("non-finite decimal")
        return Fraction(decimal_value)
    except (InvalidOperation, ValueError, ZeroDivisionError, OverflowError) as exc:
        raise BuildError(f"숫자를 해석할 수 없습니다: {value!r}") from exc


def parse_time(value: str | None, *, field: str = "time") -> Fraction:
    """Parse HH:MM:SS.mmm, HH:MM:SS,mmm, MM:SS.mmm, or decimal seconds."""
    if value is None:
        raise BuildError(f"{field} 값이 비어 있습니다.")
    raw = value.strip()
    if not raw:
        raise BuildError(f"{field} 값이 비어 있습니다.")

    normalized = raw.replace(",", ".")
    if ":" not in normalized:
        result = decimal_to_fraction(normalized)
        if result < 0:
            raise BuildError(f"{field} 값은 음수일 수 없습니다: {raw!r}")
        return result

    parts = normalized.split(":")
    if len(parts) == 3:
        h_text, m_text, s_text = parts
    elif len(parts) == 2:
        h_text, m_text, s_text = "0", parts[0], parts[1]
    else:
        raise BuildError(f"{field} 시간 형식이 올바르지 않습니다: {raw!r}")

    try:
        hours = int(h_text)
        minutes = int(m_text)
        seconds = Decimal(s_text)
    except (ValueError, InvalidOperation) as exc:
        raise BuildError(f"{field} 시간 형식이 올바르지 않습니다: {raw!r}") from exc

    if hours < 0 or minutes < 0 or minutes >= 60 or seconds < 0 or seconds >= 60:
        raise BuildError(f"{field} 시간 범위를 확인하세요: {raw!r}")
    total = Decimal(hours * 3600 + minutes * 60) + seconds
    return Fraction(total)


def parse_optional_time(value: str | None) -> Fraction | None:
    if value is None or not value.strip():
        return None
    return parse_time(value)


def parse_bool(value: Any, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if not text:
        return default
    # Beginner CSV files use ordinary Korean words instead of programming
    # literals.  Keeping these aliases here also makes the advanced CSV parser
    # consistent with the Colab adapter.
    if text in {"1", "true", "yes", "y", "on", "예", "사용", "켜기", "켬"}:
        return True
    if text in {"0", "false", "no", "n", "off", "아니오", "미사용", "끄기", "끔"}:
        return False
    raise BuildError(f"참/거짓 값을 해석할 수 없습니다: {value!r}")


def finite_decimal(
    value: Any,
    *,
    field: str,
    minimum: Decimal | None = None,
    maximum: Decimal | None = None,
) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise BuildError(f"{field}는 숫자여야 합니다.") from exc
    if not parsed.is_finite():
        raise BuildError(f"{field}는 유한한 숫자여야 합니다.")
    if minimum is not None and parsed < minimum:
        raise BuildError(f"{field}는 {minimum} 이상이어야 합니다.")
    if maximum is not None and parsed > maximum:
        raise BuildError(f"{field}는 {maximum} 이하여야 합니다.")
    return parsed


def validate_rgba(value: Any, *, field: str) -> str:
    parts = str(value).split()
    try:
        values = [Decimal(part) for part in parts]
    except InvalidOperation as exc:
        raise BuildError(f"{field}는 RGBA 숫자 4개여야 합니다.") from exc
    if len(values) != 4 or any(not item.is_finite() or item < 0 or item > 1 for item in values):
        raise BuildError(f"{field}는 0~1 범위의 RGBA 숫자 4개여야 합니다.")
    return " ".join(parts)


def normalize_subtitle_options(config: dict[str, Any]) -> SubtitleOptions:
    """Map the new subtitles object and the legacy captions object to one model.

    New projects default to ordinary Basic Title subtitles. Legacy `captions`
    projects deliberately keep their old iTT + SRT behavior.
    """

    new_raw = config.get("subtitles")
    legacy_raw = config.get("captions")
    new_active = new_raw not in (None, {})
    legacy_active = legacy_raw not in (None, {})
    if new_active and legacy_active:
        raise BuildError(
            "project.json에 subtitles와 captions를 동시에 설정할 수 없습니다. "
            "일반 영상 자막은 subtitles를, 기존 iTT 호환 설정은 captions를 사용하세요."
        )

    if new_active:
        if not isinstance(new_raw, dict):
            raise BuildError("project.json의 subtitles는 객체 또는 null이어야 합니다.")
        raw = dict(new_raw)
        mode = str(raw.get("mode", "title")).strip().lower()
        if mode not in SUBTITLE_MODES:
            raise BuildError("subtitles.mode는 title, caption, both, off 중 하나여야 합니다.")
        generate_srt = parse_bool(
            raw.get("srt", raw.get("write_srt", True)),
            default=True,
        )
        return SubtitleOptions(
            file_text=str(raw.get("file", "")).strip() or None,
            mode=mode,
            generate_srt=generate_srt,
            config=raw,
            legacy=False,
        )

    if legacy_active:
        if not isinstance(legacy_raw, dict):
            raise BuildError("project.json의 captions는 객체 또는 null이어야 합니다.")
        raw = dict(legacy_raw)
        embedded = parse_bool(raw.get("embed", True), default=True)
        return SubtitleOptions(
            file_text=str(raw.get("file", "")).strip() or None,
            mode="caption" if embedded else "off",
            generate_srt=True,
            config=raw,
            legacy=True,
        )

    if new_raw not in (None, {}) and not isinstance(new_raw, dict):
        raise BuildError("project.json의 subtitles는 객체 또는 null이어야 합니다.")
    if legacy_raw not in (None, {}) and not isinstance(legacy_raw, dict):
        raise BuildError("project.json의 captions는 객체 또는 null이어야 합니다.")
    return SubtitleOptions(file_text=None, mode="off", generate_srt=False, config={})


def parse_fps(value: str | int | float) -> Fraction:
    text = str(value).strip()
    if text in COMMON_FPS:
        return COMMON_FPS[text]
    try:
        fps = Fraction(text)
    except (ValueError, ZeroDivisionError) as exc:
        raise BuildError(f"fps를 해석할 수 없습니다: {value!r}") from exc
    if fps <= 0:
        raise BuildError("fps는 0보다 커야 합니다.")
    return fps


def validate_config(config: dict[str, Any]) -> None:
    dimensions: dict[str, int] = {}
    for key, default in (("width", 1080), ("height", 1920)):
        try:
            value = int(config.get(key, default))
        except (TypeError, ValueError) as exc:
            raise BuildError(f"project.json의 {key}는 정수여야 합니다.") from exc
        if value <= 0:
            raise BuildError(f"project.json의 {key}는 0보다 커야 합니다.")
        dimensions[key] = value

    parse_fps(config.get("fps", "30"))
    version = str(config.get("fcpxml_version", "1.14")).strip()
    if not re.fullmatch(r"\d+\.\d+", version):
        raise BuildError("project.json의 fcpxml_version은 1.14 같은 형식이어야 합니다.")
    if version != "1.14":
        raise BuildError(
            "이 emitter는 FCPXML 1.14만 생성합니다. 버전 숫자만 바꾸는 다운그레이드는 지원하지 않습니다."
        )

    path_mode = str(config.get("path_mode", "absolute")).strip().lower()
    if path_mode not in {"absolute", "relative"}:
        raise BuildError("project.json의 path_mode는 absolute 또는 relative여야 합니다.")

    image_mode = str(config.get("image_mode", "video-cache")).strip().lower()
    if image_mode not in {"video-cache", "direct"}:
        raise BuildError("project.json의 image_mode는 video-cache 또는 direct여야 합니다.")
    if image_mode == "video-cache" and any(value % 2 for value in dimensions.values()):
        raise BuildError("video-cache 모드의 width와 height는 H.264 호환을 위해 짝수여야 합니다.")
    background = str(config.get("image_background", "#000000"))
    if not re.fullmatch(r"#[0-9A-Fa-f]{6}", background):
        raise BuildError("image_background는 #000000 같은 6자리 16진수 색상이어야 합니다.")

    subtitle_options = normalize_subtitle_options(config)
    subtitle_config = subtitle_options.config
    section = "captions" if subtitle_options.legacy else "subtitles"
    try:
        wrap_width = int(subtitle_config.get("wrap_width", 20))
    except (TypeError, ValueError) as exc:
        raise BuildError(f"{section}.wrap_width는 정수여야 합니다.") from exc
    if wrap_width < 8:
        raise BuildError(f"{section}.wrap_width는 8 이상이어야 합니다.")
    caption_format = str(subtitle_config.get("format", "ITT")).upper()
    if caption_format != "ITT":
        raise BuildError("현재 Caption XML은 ITT 형식만 지원합니다. SRT는 별도 선택 결과입니다.")
    placement = str(subtitle_config.get("placement", "bottom")).lower()
    if placement not in {"top", "bottom"}:
        raise BuildError(f"{section}.placement는 top 또는 bottom이어야 합니다.")
    if subtitle_options.legacy:
        parse_bool(subtitle_config.get("embed", True), default=True)
    parse_bool(subtitle_config.get("bold", False), default=False)
    parse_bool(subtitle_config.get("shadow", True), default=True)
    for color_key, default in (
        ("prefix_color", "0.447059 0.945098 1 1"),
        ("body_color", "1 1 1 1"),
        ("background_color", "0 0 0 0.9"),
        ("outline_color", "0 0 0 1"),
        ("shadow_color", "0 0 0 0.75"),
    ):
        validate_rgba(subtitle_config.get(color_key, default), field=f"{section}.{color_key}")

    if subtitle_options.mode in {"title", "both"}:
        font = str(subtitle_config.get("font", "Apple SD Gothic Neo")).strip()
        if not font:
            raise BuildError("subtitles.font는 비어 있을 수 없습니다.")
        finite_decimal(
            subtitle_config.get("font_size", 44),
            field="subtitles.font_size",
            minimum=Decimal("1"),
        )
        finite_decimal(subtitle_config.get("position_x", 0), field="subtitles.position_x")
        finite_decimal(subtitle_config.get("position_y", -720), field="subtitles.position_y")
        if "position_x_percent" in subtitle_config:
            finite_decimal(
                subtitle_config["position_x_percent"],
                field="subtitles.position_x_percent",
                minimum=Decimal("-1000"),
                maximum=Decimal("1000"),
            )
        if "position_y_percent" in subtitle_config:
            finite_decimal(
                subtitle_config["position_y_percent"],
                field="subtitles.position_y_percent",
                minimum=Decimal("-1000"),
                maximum=Decimal("1000"),
            )
        finite_decimal(
            subtitle_config.get("outline_width", -3),
            field="subtitles.outline_width",
            minimum=Decimal("-100"),
            maximum=Decimal("100"),
        )
        finite_decimal(
            subtitle_config.get("shadow_blur_radius", 3),
            field="subtitles.shadow_blur_radius",
            minimum=Decimal("0"),
        )
        shadow_offset = str(subtitle_config.get("shadow_offset", "2 -2")).split()
        if len(shadow_offset) != 2:
            raise BuildError("subtitles.shadow_offset은 '2 -2' 같은 숫자 두 개여야 합니다.")
        for item in shadow_offset:
            finite_decimal(item, field="subtitles.shadow_offset")
        alignment = str(subtitle_config.get("alignment", "center")).lower()
        if alignment not in {"left", "center", "right", "justified"}:
            raise BuildError("subtitles.alignment는 left, center, right, justified 중 하나여야 합니다.")
        if not str(subtitle_config.get("title_effect_uid", BASIC_TITLE_UID)).strip():
            raise BuildError("subtitles.title_effect_uid는 비어 있을 수 없습니다.")

    audio_rate = str(config.get("audio_rate", "48k"))
    if audio_rate not in {"32k", "44.1k", "48k", "88.2k", "96k", "176.4k", "192k"}:
        raise BuildError("project.json의 audio_rate 값이 지원 범위에 없습니다.")

    bgm = config.get("bgm")
    if bgm is not None and not isinstance(bgm, dict):
        raise BuildError("project.json의 bgm은 객체 또는 null이어야 합니다.")


def snap_to_frame(value: Fraction, fps: Fraction) -> tuple[Fraction, int, Fraction]:
    """Return snapped seconds, frame number, and absolute snapping error."""
    exact_frames = value * fps
    # Fraction-aware half-up rounding for non-negative timeline values.
    if exact_frames < 0:
        frame_number = -int((-exact_frames) + Fraction(1, 2))
    else:
        frame_number = int(exact_frames + Fraction(1, 2))
    snapped = Fraction(frame_number, 1) / fps
    return snapped, frame_number, abs(snapped - value)


def fcpxml_time(value: Fraction) -> str:
    if value.denominator == 1:
        return f"{value.numerator}s"
    return f"{value.numerator}/{value.denominator}s"


def srt_time(value: Fraction) -> str:
    milliseconds = int(value * 1000 + Fraction(1, 2))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def display_time(value: Fraction) -> str:
    milliseconds = int(value * 1000 + Fraction(1, 2))
    minutes, remainder = divmod(milliseconds, 60_000)
    seconds, millis = divmod(remainder, 1000)
    return f"{minutes:02d}:{seconds:02d}.{millis:03d}"


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_text = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(temporary_text)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            descriptor = -1
            handle.write(text)
        temporary.chmod(0o644)
        os.replace(temporary, path)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary.exists():
            temporary.unlink()


def resolve_project_path(
    raw_path: str | Path,
    *,
    project_root: Path,
    field: str,
    restrict_to_project_root: bool,
) -> Path:
    path = Path(raw_path).expanduser()
    resolved = path.resolve() if path.is_absolute() else (project_root / path).resolve()
    root = project_root.resolve()
    if restrict_to_project_root and resolved != root and root not in resolved.parents:
        raise BuildError(f"{field} 경로가 프로젝트 폴더 밖을 가리킵니다: {raw_path}")
    return resolved


def first_value(row: dict[str, str], *keys: str) -> str:
    normalized: dict[str, str] = {}
    for key, value in row.items():
        if key is None:
            continue
        if isinstance(value, list):
            rendered = ",".join(str(item) for item in value)
        else:
            rendered = str(value or "")
        normalized[str(key).strip().lower()] = rendered
    for key in keys:
        value = normalized.get(key.strip().lower(), "")
        if value.strip():
            return value.strip()
    return ""


def infer_kind(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in VIDEO_EXTENSIONS:
        return "video"
    if suffix in IMAGE_EXTENSIONS:
        return "image"
    if suffix in AUDIO_EXTENSIONS:
        return "audio"
    raise BuildError(
        f"파일 종류를 확장자로 판단할 수 없습니다: {path.name}. "
        "timeline.csv의 kind 열에 video 또는 image를 적어주세요."
    )


# ---------------------------------------------------------------------------
# Media probing and image normalization
# ---------------------------------------------------------------------------


def require_command(command: str, purpose: str) -> str:
    path = shutil.which(command)
    if not path:
        raise BuildError(
            f"{purpose}에 필요한 `{command}` 명령을 찾지 못했습니다. "
            "Mac에서는 `brew install ffmpeg`로 설치할 수 있습니다."
        )
    return path


def media_input_policy(path: Path, *, expected_kind: str | None = None) -> MediaInputPolicy:
    """Select a fixed demuxer instead of allowing content-based playlist probing.

    FFmpeg's automatic probing can interpret an HLS or concat playlist even
    when it has been renamed to ``.mp4`` or ``.png``. Such a playlist may then
    read another local file. Pinning the demuxer to the accepted extension
    prevents that format switch. Image2 pattern expansion and QuickTime
    external data references are disabled by the policy options as well.
    """

    suffix = path.suffix.lower()
    policy = MEDIA_INPUT_POLICIES.get(suffix)
    if policy is None:
        supported = ", ".join(sorted(MEDIA_INPUT_POLICIES))
        raise BuildError(
            f"보안상 자동 형식 감지를 하지 않습니다: {path.name}. "
            f"지원 확장자를 사용해주세요: {supported}"
        )
    if expected_kind is not None and policy.kind != expected_kind:
        raise BuildError(
            f"파일 확장자와 kind가 다릅니다: {path.name}은 {policy.kind}, "
            f"기획표에는 {expected_kind}로 지정되었습니다."
        )
    return policy


def ffmpeg_input_options(policy: MediaInputPolicy) -> list[str]:
    return ["-f", policy.demuxer, *policy.demuxer_options]


def probe_media(path: Path, *, expected_kind: str | None = None) -> MediaInfo:
    policy = media_input_policy(path, expected_kind=expected_kind)
    ffprobe = require_command("ffprobe", "미디어 검사")
    command = [
        ffprobe,
        "-v",
        "error",
        "-protocol_whitelist",
        "file",
        *ffmpeg_input_options(policy),
        "-show_entries",
        "format=duration:stream=codec_type,width,height,avg_frame_rate,r_frame_rate,sample_rate,channels,duration",
        "-of",
        "json",
        str(path),
    ]
    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=FFPROBE_TIMEOUT_SECONDS,
        )
        payload = json.loads(result.stdout)
    except subprocess.CalledProcessError as exc:
        detail = sanitize_external_diagnostic(exc.stderr or exc.stdout or exc)
        raise BuildError(f"ffprobe가 파일을 읽지 못했습니다: {path}\n{detail}") from exc
    except subprocess.TimeoutExpired as exc:
        raise BuildError(
            f"미디어 검사가 {FFPROBE_TIMEOUT_SECONDS}초 안에 끝나지 않았습니다: {path.name}. "
            "파일이 손상되지 않았는지 확인하거나 MOV/MP4로 다시 변환해주세요."
        ) from exc
    except json.JSONDecodeError as exc:
        raise BuildError(f"ffprobe 결과를 해석하지 못했습니다: {path}") from exc

    streams = payload.get("streams", [])
    video = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
    audio = next((stream for stream in streams if stream.get("codec_type") == "audio"), None)

    duration_text = payload.get("format", {}).get("duration")
    duration = decimal_to_fraction(duration_text) if duration_text not in {None, "N/A"} else None

    fps: Fraction | None = None
    if video:
        for fps_text in (video.get("avg_frame_rate"), video.get("r_frame_rate")):
            if not fps_text or fps_text in {"0/0", "N/A"}:
                continue
            try:
                fps = Fraction(fps_text)
                if fps > 0:
                    break
            except (ValueError, ZeroDivisionError):
                fps = None

    video_duration_text = video.get("duration") if video else None
    video_duration = (
        decimal_to_fraction(video_duration_text)
        if video_duration_text not in {None, "", "N/A"}
        else None
    )

    return MediaInfo(
        duration=duration,
        width=int(video["width"]) if video and video.get("width") else None,
        height=int(video["height"]) if video and video.get("height") else None,
        fps=fps,
        has_video=video is not None,
        has_audio=audio is not None,
        audio_rate=int(audio["sample_rate"]) if audio and audio.get("sample_rate") else None,
        audio_channels=int(audio["channels"]) if audio and audio.get("channels") else None,
        video_duration=video_duration,
    )


def render_image_as_video(
    *,
    image_path: Path,
    output_path: Path,
    duration: Fraction,
    width: int,
    height: int,
    fps: Fraction,
    conform: str,
    background: str,
) -> bool:
    policy = media_input_policy(image_path, expected_kind="image")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_temporary = output_path.with_name(output_path.stem + ".tmp" + output_path.suffix)
    legacy_temporary.unlink(missing_ok=True)

    if output_path.exists() and output_path.stat().st_mtime >= image_path.stat().st_mtime:
        return False

    ffmpeg = require_command("ffmpeg", "이미지 영상 변환")

    exact_frames = duration * fps
    if exact_frames.denominator != 1 or exact_frames <= 0:
        raise BuildError("사진 노출 시간이 프로젝트 프레임 경계에 맞지 않습니다.")

    if conform == "fill":
        video_filter = (
            f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},setsar=1"
        )
    else:
        # fit and none are normalized as a safe fit for the generated rough-cut clip.
        safe_background = background.replace("#", "0x")
        video_filter = (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color={safe_background},setsar=1"
        )

    descriptor, temporary_text = tempfile.mkstemp(
        prefix=f".{output_path.stem}.",
        suffix=f".tmp{output_path.suffix}",
        dir=output_path.parent,
    )
    os.close(descriptor)
    temporary = Path(temporary_text)
    command = [
        ffmpeg,
        "-y",
        "-protocol_whitelist",
        "file",
        *ffmpeg_input_options(policy),
    ]
    if policy.demuxer == "image2":
        command.extend(["-loop", "1", "-framerate", str(fps)])
    else:
        # HEIC is an ISO-BMFF input rather than image2. Generic stream looping
        # repeats its single decoded frame without enabling path patterns.
        command.extend(["-stream_loop", "-1"])
    command.extend(
        [
            "-i",
            str(image_path),
            "-vf",
            video_filter,
            "-r",
            str(fps),
            "-frames:v",
            str(exact_frames.numerator),
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(temporary),
        ]
    )
    try:
        subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=FFMPEG_TIMEOUT_SECONDS,
        )
        rendered_info = probe_media(temporary)
        if not rendered_info.has_video:
            raise BuildError(f"생성된 사진 캐시에 영상 스트림이 없습니다: {temporary}")
        rendered_duration = rendered_info.video_duration or rendered_info.duration
        if rendered_duration is not None and rendered_duration + Fraction(1, 2) / fps < duration:
            raise BuildError(
                f"생성된 사진 캐시 길이가 부족합니다: {float(rendered_duration):.3f}s < {float(duration):.3f}s"
            )
        os.replace(temporary, output_path)
    except subprocess.CalledProcessError as exc:
        detail = sanitize_external_diagnostic(exc.stderr or exc.stdout or exc)
        raise BuildError(f"이미지를 영상으로 변환하지 못했습니다: {image_path}\n{detail}") from exc
    except subprocess.TimeoutExpired as exc:
        raise BuildError(
            f"사진 변환이 {FFMPEG_TIMEOUT_SECONDS // 60}분 안에 끝나지 않았습니다: "
            f"{image_path.name}. 사진 표시 시간을 줄이거나 파일을 다시 저장해주세요."
        ) from exc
    finally:
        temporary.unlink(missing_ok=True)
    return True


def image_cache_path(
    *,
    image_path: Path,
    output_root: Path,
    clip_id: str,
    duration: Fraction,
    width: int,
    height: int,
    fps: Fraction,
    conform: str,
    background: str,
) -> Path:
    stat = image_path.stat()
    fingerprint = {
        "path": str(image_path.resolve()),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "duration": fcpxml_time(duration),
        "width": width,
        "height": height,
        "fps": str(fps),
        "conform": conform,
        "background": background,
    }
    digest = hashlib.sha256(
        json.dumps(fingerprint, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:12]
    safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", clip_id).strip("_") or "image"
    safe_stem = re.sub(r"[^\w.-]+", "_", image_path.stem, flags=re.UNICODE).strip("._-")
    # Keep the complete cache component below the usual 255-byte NAME_MAX.
    # The digest is retained in full because it carries the render settings;
    # only the human-readable id/stem label may be shortened.
    suffix = f"_{digest}.mp4"
    readable = utf8_prefix(f"{safe_id}_{safe_stem or 'image'}", 240 - len(suffix.encode("utf-8")))
    readable = readable.rstrip("._-") or "image"
    return output_root / ".build_media" / f"{readable}{suffix}"


# ---------------------------------------------------------------------------
# Input loading and validation
# ---------------------------------------------------------------------------


def load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise BuildError(f"설정 파일이 없습니다: {path}") from exc
    except json.JSONDecodeError as exc:
        raise BuildError(f"설정 JSON 문법을 확인하세요: {path}\n{exc}") from exc
    if not isinstance(payload, dict):
        raise BuildError(f"설정 JSON의 최상위 값은 객체여야 합니다: {path}")
    return payload


def load_timeline(
    path: Path,
    *,
    project_root: Path,
    media_root: Path | None = None,
    fps: Fraction,
    frame_tolerance: Fraction,
    restrict_to_project_root: bool = False,
    require_media_root: bool = False,
    default_include_audio: bool = False,
) -> tuple[list[ClipRow], list[str]]:
    warnings: list[str] = []
    try:
        handle = path.open("r", encoding="utf-8-sig", newline="")
    except FileNotFoundError as exc:
        raise BuildError(f"타임라인 CSV가 없습니다: {path}") from exc

    clips: list[ClipRow] = []
    with handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise BuildError(f"타임라인 CSV 헤더가 없습니다: {path}")

        for row_number, row in enumerate(reader, start=2):
            if None in row:
                raise BuildError(
                    f"timeline.csv {row_number}행: 헤더보다 값이 많습니다. 쉼표와 따옴표를 확인하세요."
                )
            if not any(str(value or "").strip() for value in row.values()):
                continue
            enabled_text = first_value(row, "enabled", "사용")
            if enabled_text and not parse_bool(enabled_text, default=True):
                continue

            clip_id = first_value(row, "id", "clip_id", "번호", "index") or f"clip_{row_number - 1:03d}"
            file_text = first_value(row, "file", "filename", "파일", "media", "source")
            if not file_text:
                raise BuildError(f"timeline.csv {row_number}행: file 값이 없습니다.")

            file_path = resolve_project_path(
                file_text,
                project_root=project_root,
                field=f"timeline.csv {row_number}행 file",
                restrict_to_project_root=restrict_to_project_root,
            )
            if not file_path.exists() and media_root is not None and not Path(file_text).is_absolute():
                fallback_path = resolve_project_path(
                    media_root / file_text,
                    project_root=project_root,
                    field=f"timeline.csv {row_number}행 file",
                    restrict_to_project_root=restrict_to_project_root,
                )
                if fallback_path.exists():
                    file_path = fallback_path
            if not file_path.exists():
                raise BuildError(f"timeline.csv {row_number}행: 미디어 파일이 없습니다: {file_path}")
            if require_media_root:
                if media_root is None:
                    raise BuildError("간편 모드 Media 폴더 설정이 없습니다.")
                resolved_media_root = media_root.resolve()
                resolved_file = file_path.resolve()
                if resolved_file == resolved_media_root or resolved_media_root not in resolved_file.parents:
                    raise BuildError(
                        f"timeline.csv {row_number}행: 간편 모드 미디어는 Media 폴더 안에 있어야 합니다: "
                        f"{file_text}"
                    )
            if not file_path.is_file():
                raise BuildError(f"timeline.csv {row_number}행: 미디어가 일반 파일이 아닙니다: {file_path}")

            kind = first_value(row, "kind", "type", "종류").lower() or infer_kind(file_path)
            if kind not in {"video", "image"}:
                raise BuildError(
                    f"timeline.csv {row_number}행: kind는 video 또는 image여야 합니다. 현재 값: {kind!r}"
                )

            timeline_in = parse_time(
                first_value(row, "timeline_in", "output in", "output_in", "시작", "in"),
                field=f"timeline.csv {row_number}행 timeline_in",
            )
            timeline_out = parse_time(
                first_value(row, "timeline_out", "output out", "output_out", "끝", "out"),
                field=f"timeline.csv {row_number}행 timeline_out",
            )
            if timeline_in < 0 or timeline_out <= timeline_in:
                raise BuildError(
                    f"timeline.csv {row_number}행: timeline_out은 timeline_in보다 커야 합니다."
                )

            snapped_in, _, in_error = snap_to_frame(timeline_in, fps)
            snapped_out, _, out_error = snap_to_frame(timeline_out, fps)
            if in_error or out_error:
                warnings.append(
                    f"{clip_id}: 타임라인 시간이 {fps}fps 프레임 경계로 보정되었습니다 "
                    f"({display_time(timeline_in)}–{display_time(timeline_out)} → "
                    f"{display_time(snapped_in)}–{display_time(snapped_out)})."
                )
            timeline_in, timeline_out = snapped_in, snapped_out
            if timeline_out <= timeline_in:
                raise BuildError(
                    f"timeline.csv {row_number}행: 프레임 보정 후 길이가 0이 되었습니다. "
                    "최소 1프레임 이상으로 늘려주세요."
                )

            source_in = parse_optional_time(first_value(row, "source_in", "source in", "원본 시작"))
            source_out = parse_optional_time(first_value(row, "source_out", "source out", "원본 끝"))
            duration = timeline_out - timeline_in

            if kind == "image":
                source_in = Fraction(0)
                source_out = duration
            else:
                source_in = source_in if source_in is not None else Fraction(0)
                source_out = source_out if source_out is not None else source_in + duration

            if source_out <= source_in:
                raise BuildError(f"timeline.csv {row_number}행: source_out은 source_in보다 커야 합니다.")

            conform = first_value(row, "conform", "맞춤").lower() or "fit"
            if conform not in {"fit", "fill", "none"}:
                raise BuildError(
                    f"timeline.csv {row_number}행: conform은 fit, fill, none 중 하나여야 합니다."
                )

            include_audio = parse_bool(
                first_value(row, "include_audio", "source_audio", "원본 오디오"),
                default=default_include_audio if kind == "video" else False,
            )
            volume_text = first_value(row, "volume_db", "volume", "음량 db") or "0"
            try:
                volume_db = Decimal(volume_text)
            except InvalidOperation as exc:
                raise BuildError(f"timeline.csv {row_number}행: volume_db 값이 잘못됐습니다: {volume_text!r}") from exc
            if not volume_db.is_finite():
                raise BuildError(f"timeline.csv {row_number}행: volume_db는 유한한 숫자여야 합니다.")

            clips.append(
                ClipRow(
                    row_number=row_number,
                    clip_id=clip_id,
                    kind=kind,
                    file_text=file_text,
                    file_path=file_path,
                    timeline_in=timeline_in,
                    timeline_out=timeline_out,
                    source_in=source_in,
                    source_out=source_out,
                    conform=conform,
                    include_audio=include_audio,
                    volume_db=volume_db,
                    notes=first_value(row, "notes", "note", "메모", "장면 의도"),
                )
            )

    if not clips:
        raise BuildError("타임라인 CSV에 활성화된 클립이 없습니다.")

    clips.sort(key=lambda clip: (clip.timeline_in, clip.row_number))
    seen_ids: set[str] = set()
    cursor = Fraction(0)
    for clip in clips:
        if clip.clip_id in seen_ids:
            raise BuildError(f"중복 clip id가 있습니다: {clip.clip_id}")
        seen_ids.add(clip.clip_id)
        if clip.timeline_in < cursor:
            raise BuildError(
                f"주 스토리라인 클립이 겹칩니다: {clip.clip_id}가 {display_time(clip.timeline_in)}에 시작하지만 "
                f"앞 클립은 {display_time(cursor)}까지 이어집니다."
            )
        cursor = clip.timeline_out

    return clips, warnings


def load_captions(path: Path | None) -> list[CaptionRow]:
    if path is None:
        return []
    try:
        handle = path.open("r", encoding="utf-8-sig", newline="")
    except FileNotFoundError as exc:
        raise BuildError(f"자막 CSV가 없습니다: {path}") from exc

    captions: list[CaptionRow] = []
    with handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise BuildError(f"자막 CSV 헤더가 없습니다: {path}")
        for row_number, row in enumerate(reader, start=2):
            if None in row:
                raise BuildError(
                    f"자막 CSV {row_number}행: 헤더보다 값이 많습니다. 쉼표 시간은 따옴표로 감싸세요."
                )
            if not any(str(value or "").strip() for value in row.values()):
                continue
            caption_id = first_value(row, "id", "caption_id", "번호", "index") or str(row_number - 1)
            start = parse_time(first_value(row, "start", "시작", "in"), field=f"자막 CSV {row_number}행 시작")
            end = parse_time(first_value(row, "end", "끝", "out"), field=f"자막 CSV {row_number}행 끝")
            text = first_value(row, "text", "caption", "최종 대사", "대사")
            if not text:
                raise BuildError(f"자막 CSV {row_number}행: 자막 문구가 없습니다.")
            if end <= start:
                raise BuildError(f"자막 CSV {row_number}행: 끝 시간은 시작 시간보다 커야 합니다.")
            captions.append(
                CaptionRow(
                    caption_id=caption_id,
                    start=start,
                    end=end,
                    text=text.replace("\\n", "\n"),
                    notes=first_value(row, "notes", "note", "장면 의도", "메모"),
                )
            )
    captions.sort(key=lambda caption: (caption.start, caption.end))
    return captions


def snap_captions_to_frames(captions: list[CaptionRow], *, fps: Fraction) -> tuple[list[CaptionRow], list[str]]:
    normalized: list[CaptionRow] = []
    warnings: list[str] = []
    for caption in captions:
        start, _, start_error = snap_to_frame(caption.start, fps)
        end, _, end_error = snap_to_frame(caption.end, fps)
        if end <= start:
            raise BuildError(
                f"자막 {caption.caption_id}: 프레임 보정 후 길이가 0이 되었습니다. 최소 1프레임 이상으로 늘려주세요."
            )
        if start_error or end_error:
            warnings.append(
                f"자막 {caption.caption_id}: 시간이 {fps}fps 프레임 경계로 보정되었습니다 "
                f"({display_time(caption.start)}–{display_time(caption.end)} → "
                f"{display_time(start)}–{display_time(end)})."
            )
        normalized.append(
            CaptionRow(
                caption_id=caption.caption_id,
                start=start,
                end=end,
                text=caption.text,
                notes=caption.notes,
            )
        )
    normalized.sort(key=lambda caption: (caption.start, caption.end))
    for previous, current in zip(normalized, normalized[1:]):
        if current.start < previous.end:
            raise BuildError(
                f"자막 시간이 겹칩니다: {previous.caption_id}({display_time(previous.start)}–"
                f"{display_time(previous.end)})와 {current.caption_id}({display_time(current.start)}–"
                f"{display_time(current.end)})."
            )
    return normalized, warnings


def prepare_clips(
    clips: list[ClipRow],
    *,
    config: dict[str, Any],
    output_root: Path,
    fps: Fraction,
    project_width: int,
    project_height: int,
    frame_tolerance: Fraction,
    render_images: bool,
    warnings: list[str],
) -> None:
    image_mode = str(config.get("image_mode", "video-cache")).strip().lower()
    if image_mode not in {"video-cache", "direct"}:
        raise BuildError("project.json의 image_mode는 video-cache 또는 direct여야 합니다.")
    background = str(config.get("image_background", "#000000"))

    for clip in clips:
        if clip.kind == "image" and image_mode == "video-cache":
            require_command("ffmpeg", "이미지 영상 변환")
            if render_images:
                output_path = image_cache_path(
                    image_path=clip.file_path,
                    output_root=output_root,
                    clip_id=clip.clip_id,
                    duration=clip.timeline_duration,
                    width=project_width,
                    height=project_height,
                    fps=fps,
                    conform=clip.conform,
                    background=background,
                )
                render_image_as_video(
                    image_path=clip.file_path,
                    output_path=output_path,
                    duration=clip.timeline_duration,
                    width=project_width,
                    height=project_height,
                    fps=fps,
                    conform=clip.conform,
                    background=background,
                )
                clip.file_path = output_path.resolve()
                clip.kind = "video"
                clip.source_in = Fraction(0)
                clip.source_out = clip.timeline_duration
                clip.conform = "fit"

        info = probe_media(clip.file_path, expected_kind=clip.kind)
        clip.media_info = info
        if not info.has_video:
            raise BuildError(f"영상 스트림이 없는 파일입니다: {clip.file_path}")

        if clip.kind == "video":
            if info.fps:
                snapped_source_in, _, source_in_error = snap_to_frame(clip.source_in, info.fps)
                snapped_source_out, _, source_out_error = snap_to_frame(clip.source_out, info.fps)
                if source_in_error or source_out_error:
                    warnings.append(
                        f"{clip.clip_id}: source 시간이 원본 {info.fps}fps 프레임 경계로 보정되었습니다 "
                        f"({display_time(clip.source_in)}–{display_time(clip.source_out)} → "
                        f"{display_time(snapped_source_in)}–{display_time(snapped_source_out)})."
                    )
                clip.source_in, clip.source_out = snapped_source_in, snapped_source_out
                if clip.source_out <= clip.source_in:
                    raise BuildError(
                        f"{clip.clip_id}: 원본 프레임 보정 후 source 구간 길이가 0이 되었습니다."
                    )
            duration_delta = abs(clip.source_duration - clip.timeline_duration)
            if duration_delta > frame_tolerance:
                raise BuildError(
                    f"{clip.clip_id}: source 구간({float(clip.source_duration):.3f}s)과 timeline 구간"
                    f"({float(clip.timeline_duration):.3f}s)의 길이가 다릅니다. "
                    "자동 리타이밍을 하지 않으므로 두 길이를 같게 맞춰주세요."
                )
            if duration_delta:
                warnings.append(
                    f"{clip.clip_id}: source와 timeline 길이 차이가 1/2 프로젝트 프레임 이내라 "
                    f"허용했습니다 ({float(duration_delta):.6f}s)."
                )

        video_duration = info.video_duration or info.duration
        if clip.kind == "video" and video_duration is not None and clip.source_out > video_duration + frame_tolerance:
            raise BuildError(
                f"{clip.clip_id}: source_out {display_time(clip.source_out)}이 파일 길이 "
                f"{display_time(video_duration)}를 넘습니다: {clip.file_path.name}"
            )

        if clip.include_audio and not info.has_audio:
            warnings.append(f"{clip.clip_id}: include_audio가 켜졌지만 파일에 오디오 스트림이 없습니다.")
            clip.include_audio = False

        if clip.file_path.suffix.lower() not in FCP_FRIENDLY_VIDEO_EXTENSIONS and clip.kind == "video":
            warnings.append(
                f"{clip.clip_id}: {clip.file_path.suffix or '(확장자 없음)'} 파일은 ffprobe가 읽어도 "
                "Final Cut Pro에서 직접 지원되지 않을 수 있습니다. MOV 또는 MP4 변환을 권장합니다."
            )


def prepare_bgm(
    config: dict[str, Any],
    *,
    project_root: Path,
    fps: Fraction,
    warnings: list[str],
    restrict_to_project_root: bool = False,
) -> AudioBed | None:
    raw = config.get("bgm")
    if not raw:
        return None
    if not isinstance(raw, dict):
        raise BuildError("project.json의 bgm은 객체 또는 null이어야 합니다.")
    if not raw.get("file"):
        return None

    path = resolve_project_path(
        str(raw["file"]),
        project_root=project_root,
        field="BGM file",
        restrict_to_project_root=restrict_to_project_root,
    )
    if not path.exists():
        raise BuildError(f"BGM 파일이 없습니다: {path}")

    info = probe_media(path)
    if not info.has_audio:
        raise BuildError(f"BGM 파일에 오디오 스트림이 없습니다: {path}")

    timeline_start_raw = parse_time(
        str(raw.get("timeline_start", raw.get("start", "0"))), field="BGM timeline_start"
    )
    source_in_raw = parse_time(str(raw.get("source_in", "0")), field="BGM source_in")

    if raw.get("duration") not in {None, ""}:
        duration_raw = parse_time(str(raw["duration"]), field="BGM duration")
    elif raw.get("timeline_end", raw.get("end")) not in {None, ""}:
        timeline_end_raw = parse_time(
            str(raw.get("timeline_end", raw.get("end"))), field="BGM timeline_end"
        )
        duration_raw = timeline_end_raw - timeline_start_raw
    elif info.duration is not None:
        duration_raw = info.duration - source_in_raw
    else:
        raise BuildError("BGM의 duration 또는 timeline_end가 필요합니다.")

    if duration_raw <= 0:
        raise BuildError("BGM duration은 0보다 커야 합니다.")

    timeline_end_raw = timeline_start_raw + duration_raw
    timeline_start, _, start_error = snap_to_frame(timeline_start_raw, fps)
    timeline_end, _, end_error = snap_to_frame(timeline_end_raw, fps)
    if timeline_end <= timeline_start:
        raise BuildError("BGM은 프로젝트 타임라인에서 최소 1프레임 이상이어야 합니다.")
    if start_error or end_error:
        warnings.append(
            f"BGM 타임라인 시간이 {fps}fps 프레임 경계로 보정되었습니다 "
            f"({display_time(timeline_start_raw)}–{display_time(timeline_end_raw)} → "
            f"{display_time(timeline_start)}–{display_time(timeline_end)})."
        )
    duration = timeline_end - timeline_start

    if info.audio_rate:
        source_in, _, source_error = snap_to_frame(source_in_raw, Fraction(info.audio_rate))
        if source_error:
            warnings.append(
                f"BGM source_in이 {info.audio_rate}Hz 오디오 샘플 경계로 보정되었습니다 "
                f"({display_time(source_in_raw)} → {display_time(source_in)})."
            )
    else:
        source_in = source_in_raw

    if info.duration is not None and source_in + duration > info.duration + Fraction(1, 2) / fps:
        raise BuildError("BGM source_in과 duration의 합이 실제 오디오 파일 길이를 넘습니다.")

    try:
        volume_db = Decimal(str(raw.get("volume_db", 0)))
    except InvalidOperation as exc:
        raise BuildError("BGM volume_db는 숫자여야 합니다.") from exc
    if not volume_db.is_finite():
        raise BuildError("BGM volume_db는 유한한 숫자여야 합니다.")

    return AudioBed(
        path=path,
        media_info=info,
        timeline_start=timeline_start,
        source_in=source_in,
        duration=duration,
        volume_db=volume_db,
        role=str(raw.get("role", "music")) or "music",
    )


# ---------------------------------------------------------------------------
# Caption formatting
# ---------------------------------------------------------------------------


def split_prefix(text: str, prefix: str) -> tuple[str, str]:
    stripped = text.strip()
    if prefix and stripped.lower().startswith(prefix.lower()):
        return stripped[: len(prefix)], stripped[len(prefix) :].lstrip()
    return "", stripped


def wrap_caption_text(text: str, *, prefix: str, width: int) -> tuple[str, str]:
    prefix_text, body = split_prefix(text, prefix)
    if "\n" in body:
        body_text = body.strip()
    else:
        # Keep Korean/English punctuation as useful break opportunities.
        chunks = re.split(r"(?<=[.!?…])\s+", body)
        lines: list[str] = []
        for chunk in chunks:
            if not chunk:
                continue
            wrapped = textwrap.wrap(
                chunk,
                width=max(8, width),
                break_long_words=True,
                break_on_hyphens=False,
                replace_whitespace=False,
                drop_whitespace=True,
            )
            lines.extend(wrapped or [chunk])
        body_text = "\n".join(lines).strip()
    return prefix_text, body_text


def write_srt(captions: list[CaptionRow], output_path: Path, *, prefix: str, width: int) -> None:
    lines: list[str] = []
    for index, caption in enumerate(captions, start=1):
        prefix_text, body = wrap_caption_text(caption.text, prefix=prefix, width=width)
        rendered = f"{prefix_text}\n{body}" if prefix_text else body
        lines.extend(
            [
                str(index),
                f"{srt_time(caption.start)} --> {srt_time(caption.end)}",
                rendered,
                "",
            ]
        )
    atomic_write_text(output_path, "\n".join(lines))


# ---------------------------------------------------------------------------
# FCPXML generation
# ---------------------------------------------------------------------------


def media_src(path: Path, *, output_path: Path, path_mode: str) -> str:
    if path_mode == "absolute":
        return path.resolve().as_uri()
    try:
        relative = path.resolve().relative_to(output_path.parent.resolve())
        uri_path = "./" + relative.as_posix()
    except ValueError:
        relative = Path(os.path.relpath(path.resolve(), output_path.parent.resolve()))
        uri_path = relative.as_posix()
        if not uri_path.startswith("."):
            uri_path = "./" + uri_path
    return urllib.parse.quote(uri_path, safe="/.:_-~")


def add_media_resource(
    resources: ET.Element,
    clip: ClipRow,
    *,
    asset_id: str,
    format_id: str,
    output_path: Path,
    path_mode: str,
) -> None:
    assert clip.media_info is not None
    info = clip.media_info

    format_attrs: dict[str, str] = {"id": format_id, "name": f"Source {clip.file_path.name}"}
    if info.fps:
        frame_duration = Fraction(1, 1) / info.fps
        format_attrs["frameDuration"] = fcpxml_time(frame_duration)
    if info.width:
        format_attrs["width"] = str(info.width)
    if info.height:
        format_attrs["height"] = str(info.height)
    ET.SubElement(resources, "format", format_attrs)

    asset_duration = info.video_duration or info.duration or clip.source_out
    attrs = {
        "id": asset_id,
        "name": clip.file_path.name,
        "start": "0s",
        "duration": fcpxml_time(asset_duration),
        "hasVideo": "1",
        "videoSources": "1",
        "format": format_id,
    }
    if info.has_audio:
        attrs.update(
            {
                "hasAudio": "1",
                "audioSources": "1",
                "audioChannels": str(info.audio_channels or 2),
                "audioRate": str(info.audio_rate or 48000),
            }
        )
    asset = ET.SubElement(resources, "asset", attrs)
    ET.SubElement(
        asset,
        "media-rep",
        {"kind": "original-media", "src": media_src(clip.file_path, output_path=output_path, path_mode=path_mode)},
    )


def add_audio_resource(
    resources: ET.Element,
    *,
    asset_id: str,
    path: Path,
    info: MediaInfo,
    duration_fallback: Fraction,
    output_path: Path,
    path_mode: str,
) -> None:
    attrs = {
        "id": asset_id,
        "name": path.name,
        "start": "0s",
        "duration": fcpxml_time(info.duration or duration_fallback),
        "hasAudio": "1",
        "audioSources": "1",
        "audioChannels": str(info.audio_channels or 2),
        "audioRate": str(info.audio_rate or 48000),
    }
    asset = ET.SubElement(resources, "asset", attrs)
    ET.SubElement(
        asset,
        "media-rep",
        {"kind": "original-media", "src": media_src(path, output_path=output_path, path_mode=path_mode)},
    )


def find_parent_clip(clips: list[ClipRow], start: Fraction, end: Fraction) -> ClipRow | None:
    for clip in clips:
        if clip.timeline_in <= start and end <= clip.timeline_out:
            return clip
    return None


def compact_decimal(value: Decimal) -> str:
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered or "0"


def normalize_title_role(value: Any) -> str:
    role = str(value or "titles").strip()
    if not role:
        return "titles"
    if role == "titles" or role.startswith("titles."):
        return role
    return f"titles.{role}"


def title_position_percent(
    subtitle_config: dict[str, Any],
    *,
    project_height: int,
) -> tuple[Decimal, Decimal]:
    """Return FCP adjust-transform position in frame-height percentages."""

    if "position_x_percent" in subtitle_config:
        x_percent = finite_decimal(
            subtitle_config["position_x_percent"],
            field="subtitles.position_x_percent",
        )
    else:
        x_pixels = finite_decimal(subtitle_config.get("position_x", 0), field="subtitles.position_x")
        x_percent = x_pixels * Decimal(100) / Decimal(project_height)
    if "position_y_percent" in subtitle_config:
        y_percent = finite_decimal(
            subtitle_config["position_y_percent"],
            field="subtitles.position_y_percent",
        )
    else:
        default_y = Decimal(project_height) * Decimal("-0.375")
        y_pixels = finite_decimal(
            subtitle_config.get("position_y", default_y),
            field="subtitles.position_y",
        )
        y_percent = y_pixels * Decimal(100) / Decimal(project_height)
    return x_percent, y_percent


def title_style_attributes(
    subtitle_config: dict[str, Any],
    *,
    color: str,
) -> dict[str, str]:
    attributes = {
        "font": str(subtitle_config.get("font", "Apple SD Gothic Neo")),
        "fontSize": compact_decimal(
            finite_decimal(
                subtitle_config.get("font_size", 44),
                field="subtitles.font_size",
                minimum=Decimal("1"),
            )
        ),
        "fontFace": str(subtitle_config.get("font_face", "Regular")),
        "fontColor": color,
        "bold": "1" if parse_bool(subtitle_config.get("bold", False), default=False) else "0",
        "strokeColor": str(subtitle_config.get("outline_color", "0 0 0 1")),
        "strokeWidth": compact_decimal(
            finite_decimal(subtitle_config.get("outline_width", -3), field="subtitles.outline_width")
        ),
        "alignment": str(subtitle_config.get("alignment", "center")).lower(),
    }
    if parse_bool(subtitle_config.get("shadow", True), default=True):
        attributes.update(
            {
                "shadowColor": str(subtitle_config.get("shadow_color", "0 0 0 0.75")),
                "shadowOffset": str(subtitle_config.get("shadow_offset", "2 -2")),
                "shadowBlurRadius": compact_decimal(
                    finite_decimal(
                        subtitle_config.get("shadow_blur_radius", 3),
                        field="subtitles.shadow_blur_radius",
                        minimum=Decimal("0"),
                    )
                ),
            }
        )
    return attributes


def build_fcpxml(
    *,
    output_path: Path,
    config: dict[str, Any],
    clips: list[ClipRow],
    captions: list[CaptionRow],
    embed_captions: bool,
    bgm: AudioBed | None,
    embed_titles: bool = False,
) -> list[str]:
    warnings: list[str] = []
    fps = parse_fps(config.get("fps", "30"))
    version = str(config.get("fcpxml_version", "1.14"))
    project_name = str(config.get("project_name", "CSV Rough Cut"))
    event_name = str(config.get("event_name", "CSV Automation"))
    width = int(config.get("width", 1080))
    height = int(config.get("height", 1920))
    color_space = str(config.get("color_space", "1-1-1 (Rec. 709)"))
    path_mode = str(config.get("path_mode", "absolute")).strip().lower()

    total_duration = max(clip.timeline_out for clip in clips)
    if captions:
        total_duration = max(total_duration, max(caption.end for caption in captions))
    if bgm:
        total_duration = max(total_duration, bgm.timeline_end)

    root = ET.Element("fcpxml", {"version": version})
    resources = ET.SubElement(root, "resources")
    project_format_id = "rProjectFormat"
    ET.SubElement(
        resources,
        "format",
        {
            "id": project_format_id,
            "name": f"Project {width}x{height} {fps}p",
            "frameDuration": fcpxml_time(Fraction(1, 1) / fps),
            "width": str(width),
            "height": str(height),
            "colorSpace": color_space,
        },
    )

    basic_title_resource_id = ""
    if embed_titles and captions:
        subtitle_config = normalize_subtitle_options(config).config
        basic_title_resource_id = "rBasicTitle"
        ET.SubElement(
            resources,
            "effect",
            {
                "id": basic_title_resource_id,
                "name": "Basic Title",
                "uid": str(subtitle_config.get("title_effect_uid", BASIC_TITLE_UID)),
            },
        )

    # One asset resource per CSV row. This permits the same source file to be
    # used with independent source ranges without complex resource merging.
    for index, clip in enumerate(clips, start=1):
        clip.asset_id = f"rAsset{index:03d}"
        clip.format_id = f"rFormat{index:03d}"
        add_media_resource(
            resources,
            clip,
            asset_id=clip.asset_id,
            format_id=clip.format_id,
            output_path=output_path,
            path_mode=path_mode,
        )

    bgm_resource_id = ""
    if bgm:
        bgm_resource_id = "rBGM"
        add_audio_resource(
            resources,
            asset_id=bgm_resource_id,
            path=bgm.path,
            info=bgm.media_info,
            duration_fallback=bgm.source_in + bgm.duration,
            output_path=output_path,
            path_mode=path_mode,
        )

    event = ET.SubElement(root, "event", {"name": event_name})
    project = ET.SubElement(event, "project", {"name": project_name})
    sequence = ET.SubElement(
        project,
        "sequence",
        {
            "format": project_format_id,
            "duration": fcpxml_time(total_duration),
            "tcStart": "0s",
            "tcFormat": "NDF",
            "audioLayout": "stereo",
            "audioRate": str(config.get("audio_rate", "48k")),
        },
    )
    spine = ET.SubElement(sequence, "spine")

    element_by_clip_id: dict[str, ET.Element] = {}
    # start, end, XML element, element-local start value
    timeline_anchors: list[tuple[Fraction, Fraction, ET.Element, Fraction]] = []
    cursor = Fraction(0)
    for clip in clips:
        if clip.timeline_in > cursor:
            gap = ET.SubElement(
                spine,
                "gap",
                {
                    "name": "Gap",
                    "offset": fcpxml_time(cursor),
                    "start": "0s",
                    "duration": fcpxml_time(clip.timeline_in - cursor),
                },
            )
            timeline_anchors.append((cursor, clip.timeline_in, gap, Fraction(0)))
        attrs = {
            "ref": clip.asset_id,
            "name": clip.file_path.name,
            "offset": fcpxml_time(clip.timeline_in),
            "start": fcpxml_time(clip.source_in),
            "duration": fcpxml_time(clip.timeline_duration),
            "srcEnable": "all" if clip.include_audio else "video",
        }
        if clip.include_audio:
            attrs["audioRole"] = "dialogue"
        element = ET.SubElement(spine, "asset-clip", attrs)
        ET.SubElement(element, "adjust-conform", {"type": clip.conform})
        if clip.include_audio and clip.volume_db != 0:
            ET.SubElement(element, "adjust-volume", {"amount": f"{clip.volume_db}dB"})
        element_by_clip_id[clip.clip_id] = element
        timeline_anchors.append((clip.timeline_in, clip.timeline_out, element, clip.source_in))
        cursor = clip.timeline_out

    if cursor < total_duration:
        trailing_gap = ET.SubElement(
            spine,
            "gap",
            {
                "name": "Gap",
                "offset": fcpxml_time(cursor),
                "start": "0s",
                "duration": fcpxml_time(total_duration - cursor),
            },
        )
        timeline_anchors.append((cursor, total_duration, trailing_gap, Fraction(0)))

    # Connect BGM to the clip (or gap) that contains its start. The common
    # case is 0s, attached beneath the first primary-storyline clip.
    if bgm_resource_id:
        anchor_start, _, parent_element, local_start = next(
            anchor
            for anchor in timeline_anchors
            if anchor[0] <= bgm.timeline_start < anchor[1]
        )
        # With 1x playback and no timeMap, nested offset is expressed in the
        # anchor's local timeline: A = local_start + (sequence_time - anchor_offset).
        child_offset = local_start + (bgm.timeline_start - anchor_start)
        audio_element = ET.SubElement(
            parent_element,
            "asset-clip",
            {
                "ref": bgm_resource_id,
                "name": bgm.path.name,
                "lane": "-1",
                "offset": fcpxml_time(child_offset),
                "start": fcpxml_time(bgm.source_in),
                "duration": fcpxml_time(bgm.duration),
                "srcEnable": "audio",
                "audioRole": bgm.role,
            },
        )
        ET.SubElement(audio_element, "adjust-volume", {"amount": f"{bgm.volume_db}dB"})

    if basic_title_resource_id and captions:
        subtitle_config = normalize_subtitle_options(config).config
        prefix = str(subtitle_config.get("prefix", subtitle_config.get("speaker_label", "")))
        wrap_width = int(subtitle_config.get("wrap_width", 20))
        prefix_color = str(subtitle_config.get("prefix_color", "0.447059 0.945098 1 1"))
        body_color = str(subtitle_config.get("body_color", "1 1 1 1"))
        title_role = normalize_title_role(subtitle_config.get("role", "titles"))
        x_percent, y_percent = title_position_percent(subtitle_config, project_height=height)

        for index, caption in enumerate(captions, start=1):
            try:
                anchor_start, _, parent_element, local_start = next(
                    anchor
                    for anchor in timeline_anchors
                    if anchor[0] <= caption.start < anchor[1]
                )
            except StopIteration:
                warnings.append(
                    f"화면 자막 {caption.caption_id}의 시작 시각({display_time(caption.start)})을 "
                    "연결할 타임라인 구간이 없어 Title XML에서 제외했습니다."
                )
                continue
            child_offset = local_start + (caption.start - anchor_start)
            title_element = ET.SubElement(
                parent_element,
                "title",
                {
                    "ref": basic_title_resource_id,
                    "name": f"subtitle {index:02d} · Basic Title",
                    "lane": "1",
                    "offset": fcpxml_time(child_offset),
                    "start": "3600s",
                    "duration": fcpxml_time(caption.duration),
                    "role": title_role,
                },
            )
            text_element = ET.SubElement(title_element, "text")
            prefix_text, body_text = wrap_caption_text(caption.text, prefix=prefix, width=wrap_width)
            if prefix_text:
                prefix_style_id = f"tsT{index:03d}p"
                prefix_style = ET.SubElement(text_element, "text-style", {"ref": prefix_style_id})
                prefix_style.text = prefix_text
                prefix_definition = ET.SubElement(title_element, "text-style-def", {"id": prefix_style_id})
                ET.SubElement(
                    prefix_definition,
                    "text-style",
                    title_style_attributes(subtitle_config, color=prefix_color),
                )
                body_prefix = "\n"
            else:
                body_prefix = ""

            body_style_id = f"tsT{index:03d}b"
            body_style = ET.SubElement(text_element, "text-style", {"ref": body_style_id})
            body_style.text = body_prefix + body_text
            body_definition = ET.SubElement(title_element, "text-style-def", {"id": body_style_id})
            ET.SubElement(
                body_definition,
                "text-style",
                title_style_attributes(subtitle_config, color=body_color),
            )
            ET.SubElement(
                title_element,
                "adjust-transform",
                {"position": f"{compact_decimal(x_percent)} {compact_decimal(y_percent)}"},
            )

    if embed_captions and captions:
        normalized_subtitles = normalize_subtitle_options(config)
        caption_config = normalized_subtitles.config
        role_name = str(
            caption_config.get("role", "System Neo" if normalized_subtitles.legacy else "Captions")
        )
        language = str(caption_config.get("language", "ko-KR"))
        caption_format = str(caption_config.get("format", "ITT")).upper()
        placement = str(caption_config.get("placement", "bottom"))
        prefix = str(caption_config.get("prefix", "system neo:" if normalized_subtitles.legacy else ""))
        wrap_width = int(caption_config.get("wrap_width", 20))
        prefix_color = str(caption_config.get("prefix_color", "0.447059 0.945098 1 1"))
        body_color = str(caption_config.get("body_color", "1 1 1 1"))
        background_color = str(caption_config.get("background_color", "0 0 0 0.9"))
        bold_default = normalized_subtitles.legacy
        bold = "1" if parse_bool(caption_config.get("bold", bold_default), default=bold_default) else "0"
        role = f"{role_name}?captionFormat={caption_format}.{language}"

        for index, caption in enumerate(captions, start=1):
            parent_clip = find_parent_clip(clips, caption.start, caption.end)
            if parent_clip is None:
                warnings.append(
                    f"자막 {caption.caption_id}({display_time(caption.start)}–{display_time(caption.end)})은 "
                    "한 영상 클립 안에 완전히 들어가지 않아 Caption XML에서 제외했습니다."
                )
                continue
            parent_element = element_by_clip_id[parent_clip.clip_id]
            relative_offset = caption.start - parent_clip.timeline_in
            # This builder intentionally emits no retiming/timeMap. For a
            # trimmed parent, connected-item offset therefore starts at the
            # parent's source/local start rather than at zero.
            child_offset = parent_clip.source_in + relative_offset
            caption_element = ET.SubElement(
                parent_element,
                "caption",
                {
                    "name": f"caption {index:02d} · AUTO",
                    "lane": "1",
                    "offset": fcpxml_time(child_offset),
                    # Mirroring a known-good Final Cut iTT caption export.
                    "start": "3600s",
                    "duration": fcpxml_time(caption.duration),
                    "role": role,
                },
            )
            text_element = ET.SubElement(caption_element, "text", {"placement": placement})
            prefix_text, body_text = wrap_caption_text(caption.text, prefix=prefix, width=wrap_width)
            if prefix_text:
                prefix_style_id = f"tsC{index:03d}p"
                prefix_style = ET.SubElement(text_element, "text-style", {"ref": prefix_style_id})
                prefix_style.text = prefix_text
                prefix_def = ET.SubElement(caption_element, "text-style-def", {"id": prefix_style_id})
                ET.SubElement(
                    prefix_def,
                    "text-style",
                    {
                        "fontFace": "Regular",
                        "fontColor": prefix_color,
                        "backgroundColor": background_color,
                        "bold": bold,
                        "alignment": "center",
                    },
                )
                body_prefix = "\n"
            else:
                body_prefix = ""

            body_style_id = f"tsC{index:03d}b"
            body_style = ET.SubElement(text_element, "text-style", {"ref": body_style_id})
            body_style.text = body_prefix + body_text
            body_def = ET.SubElement(caption_element, "text-style-def", {"id": body_style_id})
            ET.SubElement(
                body_def,
                "text-style",
                {
                    "fontFace": "Regular",
                    "fontColor": body_color,
                    "backgroundColor": background_color,
                    "bold": bold,
                    "alignment": "center",
                },
            )

    ET.indent(root, space="  ")
    # FCPXML <text> uses mixed content. Pretty-print whitespace inside it can
    # become visible caption whitespace, so keep those child tags adjacent.
    for mixed_text in root.findall(".//text"):
        mixed_text.text = None
        for child in mixed_text:
            child.tail = None
    xml_body = ET.tostring(root, encoding="unicode", short_empty_elements=True)
    atomic_write_text(
        output_path,
        '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE fcpxml>\n' + xml_body + "\n",
    )
    return warnings


def verify_fcpxml_target(
    path: Path,
    *,
    expected_width: int,
    expected_height: int,
    expected_fps: Fraction,
) -> None:
    """Fail closed when a generated XML does not match its layout profile."""

    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise BuildError(f"생성된 FCPXML을 다시 읽을 수 없습니다: {path}\n{exc}") from exc
    resources = {
        element.get("id"): element
        for element in root.findall("./resources/format")
        if element.get("id")
    }
    sequences = root.findall(".//project/sequence")
    if not sequences:
        raise BuildError(f"생성된 FCPXML에 프로젝트 sequence가 없습니다: {path}")
    expected_frame_duration = fcpxml_time(Fraction(1, 1) / expected_fps)
    for sequence in sequences:
        format_ref = sequence.get("format", "")
        project_format = resources.get(format_ref)
        if project_format is None:
            raise BuildError(
                f"생성된 FCPXML의 프로젝트 format 참조가 없습니다: {format_ref or '(none)'}"
            )
        actual = (
            project_format.get("width"),
            project_format.get("height"),
            project_format.get("frameDuration"),
        )
        expected = (str(expected_width), str(expected_height), expected_frame_duration)
        if actual != expected:
            raise BuildError(
                "생성된 FCPXML 규격 검증에 실패했습니다: "
                f"실제 {actual[0]}x{actual[1]} / {actual[2]}, "
                f"기대 {expected[0]}x{expected[1]} / {expected[2]}"
            )


def write_report(
    path: Path,
    *,
    project_root: Path,
    config_path: Path,
    timeline_path: Path,
    captions_path: Path | None,
    subtitle_options: SubtitleOptions,
    clips: list[ClipRow],
    captions: list[CaptionRow],
    outputs: Iterable[Path],
    warnings: list[str],
    config: dict[str, Any],
    config_label: str | None = None,
) -> None:
    root = project_root.resolve()

    def portable_path(value: Path | None) -> str:
        if value is None:
            return "(none)"
        resolved = value.resolve()
        try:
            relative = resolved.relative_to(root)
        except ValueError:
            return str(resolved)
        return relative.as_posix() or "."

    total_duration = max(clip.timeline_out for clip in clips)
    recommended = "*_clean.fcpxml"
    if subtitle_options.mode in {"title", "both"} and captions:
        recommended = "*_with_titles.fcpxml (일반 영상 자막 추천)"
    elif subtitle_options.mode == "caption" and captions:
        recommended = "*_with_captions.fcpxml (접근성·언어 캡션)"
    lines = [
        "FCPXML CSV BUILDER REPORT",
        "=" * 72,
        f"Recommended import: {recommended}",
        f"Project root: {project_root.name}/",
        f"Config: {config_label or portable_path(config_path)}",
        f"Timeline CSV: {portable_path(timeline_path)}",
        f"Subtitle CSV: {portable_path(captions_path)}",
        f"Subtitle mode: {subtitle_options.mode}",
        f"SRT sidecar: {'yes' if subtitle_options.generate_srt else 'no'}",
        f"Frame size: {int(config.get('width', 1080))}x{int(config.get('height', 1920))}",
        f"Frame rate: {parse_fps(config.get('fps', '30'))} fps",
        f"Visual clips: {len(clips)}",
        f"Subtitle rows: {len(captions)}",
        f"Primary storyline end: {display_time(total_duration)}",
        "",
        "Outputs:",
    ]
    lines.extend(f"- {portable_path(output)}" for output in outputs)
    lines.extend(["", "Warnings:"])
    lines.extend(f"- {warning}" for warning in warnings)
    if not warnings:
        lines.append("- none")
    lines.extend(["", "Clip map:"])
    for clip in clips:
        note = f" · {clip.notes}" if clip.notes else ""
        lines.append(
            f"- {clip.clip_id}: {display_time(clip.timeline_in)}–{display_time(clip.timeline_out)} "
            f"<= {clip.file_path.name} [{display_time(clip.source_in)}–{display_time(clip.source_out)}]"
            f"{note}"
        )
    atomic_write_text(path, "\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def safe_output_basename(value: str) -> str:
    sanitized = re.sub(r"[^0-9A-Za-z가-힣._-]+", "_", value).strip("_") or "auto_roughcut"
    # 대부분의 파일시스템은 한 파일명 구성요소를 255 *바이트*로 제한한다.
    # 한글 100자는 UTF-8에서 약 300바이트이므로 글자 수만 제한하면 결과를
    # 쓰는 마지막 단계에서 난해한 ``File name too long`` 오류가 날 수 있다.
    # 가장 긴 출력 접미사와 확장자를 붙일 여유를 남겨 basename을 180바이트로
    # 자른다. 문자 단위로 더하므로 다중 바이트 문자를 중간에서 끊지 않는다.
    return utf8_prefix(sanitized, 180).rstrip("._-") or "auto_roughcut"


def suffixed_output_basename(value: str, suffix: str) -> str:
    """Append a required variant suffix without exceeding the byte budget."""

    safe_base = safe_output_basename(value)
    safe_suffix = re.sub(r"[^0-9A-Za-z._-]+", "_", suffix).strip("._-")
    suffix_text = f"_{safe_suffix}" if safe_suffix else ""
    prefix_budget = 180 - len(suffix_text.encode("utf-8"))
    if prefix_budget <= 0:
        raise BuildError("출력 파일 접미사가 너무 깁니다.")
    prefix = utf8_prefix(safe_base, prefix_budget).rstrip("._-") or "auto_roughcut"
    return prefix + suffix_text


def quick_config(
    project_root: Path,
    *,
    project_name: str | None,
    landscape: bool,
    fps: str,
    media_dir: str,
    layout: str | None = None,
) -> dict[str, Any]:
    name = (project_name or project_root.name).strip() or "CSV Rough Cut"
    selected_layout = layout or ("landscape" if landscape else "portrait")
    if selected_layout not in LAYOUT_PROFILES:
        raise BuildError("간편 모드 layout은 portrait 또는 landscape여야 합니다.")
    profile = LAYOUT_PROFILES[selected_layout]
    width, height = int(profile["width"]), int(profile["height"])
    return {
        "event_name": "CSV Automation",
        "project_name": name,
        "output_basename": safe_output_basename(name),
        "fcpxml_version": "1.14",
        "width": width,
        "height": height,
        "fps": fps,
        "color_space": "1-1-1 (Rec. 709)",
        "audio_rate": "48k",
        "timeline_csv": "timeline.csv",
        "output_dir": "Generated",
        "path_mode": "relative",
        "image_mode": "video-cache",
        "image_background": "#000000",
        "media_dir": media_dir,
        "bgm": None,
        "subtitles": {},
        "captions": {},
    }


def layout_variant_config(
    config: dict[str, Any],
    *,
    layout: str,
    distinct_output: bool,
) -> dict[str, Any]:
    """Return an isolated config for one 9:16 or 16:9 result.

    User-specified title positions remain authoritative. Only the implicit
    fallback becomes a layout-aware percentage, which fixes the old behaviour
    where ``-720`` pixels was sensible for a 1920-high portrait project but far
    too low for a 1080-high landscape project.
    """

    if layout not in LAYOUT_PROFILES:
        raise BuildError(f"지원하지 않는 layout입니다: {layout}")
    profile = LAYOUT_PROFILES[layout]
    variant = copy.deepcopy(config)
    variant["width"] = int(profile["width"])
    variant["height"] = int(profile["height"])

    # Do not activate a modern subtitles block beside an existing legacy
    # captions block. When modern title settings are already in use (or no
    # legacy block exists), add only missing profile defaults.
    legacy_active = variant.get("captions") not in (None, {})
    subtitle_raw = variant.get("subtitles")
    if isinstance(subtitle_raw, dict) and subtitle_raw and not legacy_active:
        if "position_y_percent" not in subtitle_raw and "position_y" not in subtitle_raw:
            subtitle_raw["position_y_percent"] = profile["title_y_percent"]
        subtitle_raw.setdefault("wrap_width", int(profile["wrap_width"]))

    if distinct_output:
        base_project_name = str(variant.get("project_name", "CSV Rough Cut")).strip() or "CSV Rough Cut"
        variant["project_name"] = f"{base_project_name} {profile['project_suffix']}"
        base_output = safe_output_basename(
            str(variant.get("output_basename", base_project_name))
        )
        variant["output_basename"] = suffixed_output_basename(
            base_output,
            str(profile["basename_suffix"]),
        )
    return variant


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="CSV와 미디어 파일로 Final Cut Pro용 FCPXML 러프컷을 생성합니다."
    )
    source_group = parser.add_mutually_exclusive_group()
    source_group.add_argument("--config", default=None, help="고급 모드 project.json 경로")
    source_group.add_argument(
        "--quick-project",
        default=None,
        help="간편 모드 프로젝트 폴더. timeline.csv와 Media/만 필요합니다",
    )
    parser.add_argument("--timeline", default=None, help="타임라인 CSV 경로. 생략하면 config의 timeline_csv 사용")
    parser.add_argument("--output-dir", default=None, help="출력 폴더. 생략하면 config의 output_dir 사용")
    parser.add_argument("--media-dir", default="Media", help="간편 모드 미디어 폴더명. 기본 Media")
    parser.add_argument("--subtitles", default=None, help="선택 자막 CSV 경로")
    parser.add_argument(
        "--subtitle-mode",
        choices=("title", "caption", "both", "off"),
        default=None,
        help="자막 결과: title(일반 영상용, 추천), caption(접근성용), both, off",
    )
    parser.add_argument("--no-srt", action="store_true", help="별도 SRT 파일을 생성하지 않습니다")
    parser.add_argument("--no-subtitles", action="store_true", help="자막 CSV 설정을 모두 무시합니다")
    parser.add_argument("--project-name", default=None, help="간편 모드 Final Cut 프로젝트 이름")
    parser.add_argument(
        "--output-basename",
        default=None,
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--fps", default="30", help="간편 모드 프로젝트 fps. 기본 30")
    layout_group = parser.add_mutually_exclusive_group()
    layout_group.add_argument(
        "--layout",
        choices=("portrait", "landscape", "both"),
        default=None,
        help="출력 화면: portrait(9:16), landscape(16:9), both(둘 다)",
    )
    layout_group.add_argument("--portrait", action="store_true", help="간편 모드 세로 1080x1920 (기본)")
    layout_group.add_argument("--landscape", action="store_true", help="간편 모드 가로 1920x1080")
    parser.add_argument(
        "--path-mode",
        choices=("absolute", "relative"),
        default=None,
        help="미디어 URI 방식. Colab/이동용 결과는 relative 권장",
    )
    parser.add_argument(
        "--no-embedded-captions",
        action="store_true",
        help="기존 호환용: iTT Caption XML만 끕니다 (Title·SRT는 유지)",
    )
    parser.add_argument("--validate-only", action="store_true", help="입력만 검사하고 결과 파일은 만들지 않습니다")
    parser.add_argument(
        "--restrict-to-project-root",
        action="store_true",
        help="timeline·미디어·BGM·자막·출력 경로를 프로젝트 폴더 안으로 제한합니다",
    )
    parser.add_argument(
        "--allow-external-output",
        action="store_true",
        help="고급용: Generated 결과를 프로젝트 폴더 밖에 쓰는 것을 명시적으로 허용합니다",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = parser.parse_args(argv)

    selected_layout = args.layout
    if selected_layout is None:
        selected_layout = "landscape" if args.landscape else "portrait"

    try:
        quick_mode = bool(args.quick_project)
        config_label: str | None = None
        if quick_mode:
            project_root = Path(args.quick_project).expanduser().resolve()
            if not project_root.is_dir():
                raise BuildError(f"간편 모드 프로젝트 폴더가 없습니다: {project_root}")
            config = quick_config(
                project_root,
                project_name=args.project_name,
                landscape=selected_layout == "landscape",
                fps=args.fps,
                media_dir=args.media_dir,
                layout="portrait" if selected_layout == "both" else selected_layout,
            )
            config_path = project_root / ".quick-mode"
            config_label = "자동 간편 모드 (timeline.csv + Media/)"
            args.restrict_to_project_root = True
        else:
            config_path = Path(args.config or "project.json").expanduser().resolve()
            config = load_json(config_path)
            project_root = config_path.parent
        if args.output_basename:
            config["output_basename"] = safe_output_basename(args.output_basename)
        if args.no_subtitles and args.subtitles:
            raise BuildError("--no-subtitles와 --subtitles는 함께 사용할 수 없습니다.")
        if args.no_subtitles:
            config["subtitles"] = {}
            config["captions"] = {}
        elif args.subtitles or args.subtitle_mode:
            current = normalize_subtitle_options(config)
            migrated = dict(current.config)
            if current.legacy:
                # CLI overrides may migrate a legacy captions block to the
                # new subtitles shape. Materialize the old implicit defaults
                # so changing only the file or mode does not restyle captions.
                migrated.setdefault("role", "System Neo")
                migrated.setdefault("prefix", "system neo:")
                migrated.setdefault("bold", True)
                migrated.pop("embed", None)
            if args.subtitles:
                migrated["file"] = args.subtitles
            if args.subtitle_mode:
                migrated["mode"] = args.subtitle_mode
            elif current.legacy:
                migrated["mode"] = current.mode
            if args.no_srt:
                migrated["srt"] = False
            elif args.subtitles and not current.file_text:
                migrated["srt"] = True
            else:
                migrated["srt"] = current.generate_srt
            config["subtitles"] = migrated
            config["captions"] = {}
        if args.path_mode:
            config["path_mode"] = args.path_mode
        validate_config(config)
        subtitle_options = normalize_subtitle_options(config)
        fps = parse_fps(config.get("fps", "30"))
        frame_tolerance = Fraction(1, 2) / fps

        media_root: Path | None = None
        media_dir_text = config.get("media_dir")
        if media_dir_text:
            media_root = resolve_project_path(
                str(media_dir_text),
                project_root=project_root,
                field="media_dir",
                restrict_to_project_root=args.restrict_to_project_root,
            )
            if quick_mode and not media_root.is_dir():
                raise BuildError(f"Media 폴더가 없습니다: {media_root}")

        timeline_text = args.timeline or config.get("timeline_csv", "timeline.csv")
        timeline_path = resolve_project_path(
            str(timeline_text),
            project_root=project_root,
            field="timeline_csv",
            restrict_to_project_root=args.restrict_to_project_root,
        )

        output_dir_text = args.output_dir or config.get("output_dir", "Output")
        output_dir = resolve_project_path(
            str(output_dir_text),
            project_root=project_root,
            field="output_dir",
            restrict_to_project_root=(
                args.restrict_to_project_root or not args.allow_external_output
            ),
        )

        dual_output = selected_layout == "both"
        profiled_output = args.layout is not None
        if dual_output:
            requested_layouts: tuple[str | None, ...] = ("portrait", "landscape")
        elif quick_mode or args.layout is not None:
            requested_layouts = (selected_layout,)
        else:
            # Advanced project.json builds without the new --layout option keep
            # their custom dimensions exactly as before. The legacy quick-only
            # --portrait/--landscape flags therefore do not unexpectedly alter
            # an advanced config.
            requested_layouts = (None,)

        variants: list[tuple[str | None, dict[str, Any], Path]] = []
        for layout_name in requested_layouts:
            if layout_name is None:
                variant_config = copy.deepcopy(config)
                variant_output_dir = output_dir
            else:
                variant_config = layout_variant_config(
                    config,
                    layout=layout_name,
                    distinct_output=profiled_output,
                )
                profile = LAYOUT_PROFILES[layout_name]
                variant_output_dir = (
                    output_dir / str(profile["folder"]) if profiled_output else output_dir
                )
            validate_config(variant_config)
            if parse_fps(variant_config.get("fps", "30")) != fps:
                raise BuildError("세로·가로 결과는 동일한 fps를 사용해야 합니다.")
            variants.append((layout_name, variant_config, variant_output_dir))

        clips, warnings = load_timeline(
            timeline_path,
            project_root=project_root,
            media_root=media_root,
            fps=fps,
            frame_tolerance=frame_tolerance,
            restrict_to_project_root=args.restrict_to_project_root,
            require_media_root=quick_mode,
            default_include_audio=quick_mode,
        )
        caption_file_text = subtitle_options.file_text
        captions_path: Path | None = None
        if caption_file_text:
            captions_path = resolve_project_path(
                str(caption_file_text),
                project_root=project_root,
                field="captions.file" if subtitle_options.legacy else "subtitles.file",
                restrict_to_project_root=args.restrict_to_project_root,
            )
        captions = load_captions(captions_path)
        captions, caption_warnings = snap_captions_to_frames(captions, fps=fps)
        warnings.extend(caption_warnings)
        bgm = prepare_bgm(
            config,
            project_root=project_root,
            fps=fps,
            warnings=warnings,
            restrict_to_project_root=args.restrict_to_project_root,
        )
        bgm_text = "있음" if bgm else "없음"

        if args.validate_only:
            for layout_name, variant_config, variant_output_dir in variants:
                variant_clips = copy.deepcopy(clips)
                variant_warnings = list(warnings)
                prepare_clips(
                    variant_clips,
                    config=variant_config,
                    output_root=variant_output_dir,
                    fps=fps,
                    project_width=int(variant_config.get("width", 1080)),
                    project_height=int(variant_config.get("height", 1920)),
                    frame_tolerance=frame_tolerance,
                    render_images=False,
                    warnings=variant_warnings,
                )
                label = layout_name or "custom"
                variant_subtitles = normalize_subtitle_options(variant_config)
                print(
                    f"검사 완료 [{label}]: {variant_config['width']}x{variant_config['height']} "
                    f"{fps}fps, 클립 {len(variant_clips)}개, 자막 {len(captions)}개, "
                    f"자막 방식 {variant_subtitles.mode}, BGM {bgm_text}"
                )
                for warning in variant_warnings:
                    print(f"경고 [{label}]: {warning}")
            return 0

        completed_outputs: list[Path] = []
        warning_count = 0
        for layout_name, variant_config, variant_output_dir in variants:
            variant_clips = copy.deepcopy(clips)
            variant_warnings = list(warnings)
            variant_subtitles = normalize_subtitle_options(variant_config)
            variant_caption_config = variant_subtitles.config
            variant_output_dir.mkdir(parents=True, exist_ok=True)
            prepare_clips(
                variant_clips,
                config=variant_config,
                output_root=variant_output_dir,
                fps=fps,
                project_width=int(variant_config.get("width", 1080)),
                project_height=int(variant_config.get("height", 1920)),
                frame_tolerance=frame_tolerance,
                render_images=True,
                warnings=variant_warnings,
            )

            safe_project_name = safe_output_basename(
                str(variant_config.get("output_basename", "auto_roughcut"))
            )
            clean_xml = variant_output_dir / f"{safe_project_name}_clean.fcpxml"
            title_xml = variant_output_dir / f"{safe_project_name}_with_titles.fcpxml"
            embedded_xml = variant_output_dir / f"{safe_project_name}_with_captions.fcpxml"
            srt_output = variant_output_dir / f"{safe_project_name}.srt"
            report_output = variant_output_dir / "build_report.txt"

            variant_warnings.extend(
                build_fcpxml(
                    output_path=clean_xml,
                    config=variant_config,
                    clips=variant_clips,
                    captions=[],
                    embed_captions=False,
                    bgm=bgm,
                )
            )
            verify_fcpxml_target(
                clean_xml,
                expected_width=int(variant_config.get("width", 1080)),
                expected_height=int(variant_config.get("height", 1920)),
                expected_fps=fps,
            )
            outputs: list[Path] = [clean_xml]
            output_mode = variant_subtitles.mode
            if args.no_embedded_captions:
                if output_mode == "caption":
                    output_mode = "off"
                elif output_mode == "both":
                    output_mode = "title"
            make_titles = bool(captions) and output_mode in {"title", "both"}
            embed_captions = bool(captions) and output_mode in {"caption", "both"}
            make_srt = bool(captions) and variant_subtitles.generate_srt and not args.no_srt

            if captions:
                default_prefix = "system neo:" if variant_subtitles.legacy else ""
                prefix = str(
                    variant_caption_config.get(
                        "prefix",
                        variant_caption_config.get("speaker_label", default_prefix),
                    )
                )
                wrap_width = int(variant_caption_config.get("wrap_width", 20))
                if make_srt:
                    write_srt(captions, srt_output, prefix=prefix, width=wrap_width)
                    outputs.append(srt_output)

                if make_titles:
                    variant_warnings.extend(
                        build_fcpxml(
                            output_path=title_xml,
                            config=variant_config,
                            clips=variant_clips,
                            captions=captions,
                            embed_captions=False,
                            embed_titles=True,
                            bgm=bgm,
                        )
                    )
                    verify_fcpxml_target(
                        title_xml,
                        expected_width=int(variant_config.get("width", 1080)),
                        expected_height=int(variant_config.get("height", 1920)),
                        expected_fps=fps,
                    )
                    outputs.append(title_xml)
                if embed_captions:
                    variant_warnings.extend(
                        build_fcpxml(
                            output_path=embedded_xml,
                            config=variant_config,
                            clips=variant_clips,
                            captions=captions,
                            embed_captions=True,
                            bgm=bgm,
                        )
                    )
                    verify_fcpxml_target(
                        embedded_xml,
                        expected_width=int(variant_config.get("width", 1080)),
                        expected_height=int(variant_config.get("height", 1920)),
                        expected_fps=fps,
                    )
                    outputs.append(embedded_xml)

            stale_outputs: list[Path] = []
            if not make_srt:
                stale_outputs.append(srt_output)
            if not make_titles:
                stale_outputs.append(title_xml)
            if not embed_captions:
                stale_outputs.append(embedded_xml)
            for stale_output in stale_outputs:
                stale_output.unlink(missing_ok=True)

            write_report(
                report_output,
                project_root=project_root,
                config_path=config_path,
                timeline_path=timeline_path,
                captions_path=captions_path,
                subtitle_options=SubtitleOptions(
                    file_text=variant_subtitles.file_text,
                    mode=output_mode,
                    generate_srt=make_srt,
                    config=variant_subtitles.config,
                    legacy=variant_subtitles.legacy,
                ),
                clips=variant_clips,
                captions=captions,
                outputs=outputs,
                warnings=variant_warnings,
                config=variant_config,
                config_label=config_label,
            )
            outputs.append(report_output)
            completed_outputs.extend(outputs)
            warning_count += len(variant_warnings)

        print("완료했습니다.")
        for output in completed_outputs:
            print(f"- {output}")
        if warning_count:
            print(f"경고 {warning_count}개가 있습니다. 각 build_report.txt를 확인하세요.")
        return 0

    except BuildError as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 2
    except (OSError, ValueError, TypeError) as exc:
        print(f"파일 또는 설정 처리 오류: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("사용자가 작업을 중단했습니다.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
