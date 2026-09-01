#!/usr/bin/env python3
"""Create a safe, static visual preview for a precise timeline CSV.

The module has no Python package dependencies.  It asks ``ffprobe`` for the
source dimensions and uses ``ffmpeg`` to create one JPEG per scene: the middle
of the selected source range for video, or a downsized copy for a still image.
The resulting report compares the requested 9:16 and 16:9 layouts, overlays a
conservative title-safe area and every subtitle that intersects the scene, and
explains likely letterboxing/pillarboxing or cropping.

Public API and an integration example::

    from pathlib import Path
    from preview_report import generate_preview_report

    project_root = Path("/path/to/MyProject")
    report = generate_preview_report(
        timeline_csv_by_layout={
            "portrait": project_root / "Generated" / "portrait" / "timeline.precise.csv",
            "landscape": project_root / "Generated" / "landscape" / "timeline.precise.csv",
        },
        subtitles_csv=project_root / "subtitles.csv",  # or None
        project_root=project_root,
        media_root=project_root / "Media",
        output_root=project_root / "Generated",
        target_layouts=("portrait", "landscape"),
    )
    print(report.index_path)  # .../Generated/preview/index.html

Call it after a beginner spreadsheet has been converted to the precise CSV and
before FCPXML emission to provide a preflight preview.  The same call can be
made after emission to refresh the report; it never reads or mutates FCPXML.

Security boundaries are deliberate: timeline/subtitle CSV files and output
must stay inside ``project_root``; each media reference must stay inside the
explicitly supplied ``media_root`` (including after symlink resolution).
External URLs, traversal components, and Windows paths on non-Windows hosts
are rejected.  All user-controlled strings are HTML escaped and the report has
no JavaScript.
"""

from __future__ import annotations

import csv
import hashlib
import html
import json
import os
import re
import subprocess
import tempfile
import time
from functools import wraps
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from pathlib import Path, PureWindowsPath
from typing import Mapping, Sequence


VIDEO_EXTENSIONS = {".avi", ".m4v", ".mkv", ".mov", ".mp4", ".webm"}
IMAGE_EXTENSIONS = {
    ".bmp",
    ".heic",
    ".jpeg",
    ".jpg",
    ".png",
    ".tif",
    ".tiff",
    ".webp",
}

# Do not let FFmpeg auto-detect playlist/manifest formats from a file whose
# name merely looks like ordinary media.  Auto-detected HLS/concat inputs can
# follow nested ``../../outside`` references even when the top-level CSV path
# itself passed the media_root containment check.
_VIDEO_INPUT_FORMATS = {
    ".avi": "avi",
    ".m4v": "mov",
    ".mkv": "matroska,webm",
    ".mov": "mov",
    ".mp4": "mov",
    ".webm": "matroska,webm",
}
MAX_PREVIEW_CSV_BYTES = 10 * 1024 * 1024
MAX_PREVIEW_SCENES = 300
MAX_PREVIEW_SUBTITLES = 5_000
MAX_SUBTITLES_PER_SCENE = 100
MAX_THUMBNAIL_BYTES = 8 * 1024 * 1024


class PreviewReportError(RuntimeError):
    """A safe, user-correctable preview input or output error."""

    def __str__(self) -> str:
        # Errors are printed by make_xml.py.  Strip ANSI/OSC control bytes and
        # collapse forged line breaks from uploaded CSV values before they
        # reach Terminal.app or a CI log.
        return _clean_diagnostic(super().__str__(), limit=2_000)


@dataclass(frozen=True)
class LayoutSpec:
    """One supported delivery layout."""

    name: str
    label: str
    width: int
    height: int

    @property
    def aspect(self) -> Fraction:
        return Fraction(self.width, self.height)


@dataclass(frozen=True)
class SubtitleCue:
    """A subtitle on the completed timeline."""

    cue_id: str
    start: Fraction
    end: Fraction
    text: str
    notes: str = ""


@dataclass(frozen=True)
class TimelineScene:
    """A normalized row from the precise timeline CSV."""

    row_number: int
    clip_id: str
    kind: str
    file_text: str
    file_path: Path
    timeline_in: Fraction
    timeline_out: Fraction
    source_in: Fraction
    source_out: Fraction
    conforms: tuple[tuple[str, str], ...]
    notes: str = ""

    @property
    def timeline_midpoint(self) -> Fraction:
        return (self.timeline_in + self.timeline_out) / 2

    @property
    def source_midpoint(self) -> Fraction:
        return (self.source_in + self.source_out) / 2

    def conform_for(self, layout: str) -> str:
        for layout_name, conform in self.conforms:
            if layout_name == layout:
                return conform
        raise KeyError(layout)


@dataclass(frozen=True)
class LayoutAssessment:
    """Predicted result of applying a conform mode to one layout."""

    layout: str
    conform: str
    object_fit: str
    effect: str
    axis: str | None
    total_percent: float | None
    warning: str | None


@dataclass(frozen=True)
class PreviewScene:
    """Rendered preview information for one scene."""

    scene: TimelineScene
    thumbnail_path: Path | None
    thumbnail_error: str | None
    source_width: int | None
    source_height: int | None
    subtitles: tuple[SubtitleCue, ...]
    assessments: tuple[LayoutAssessment, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class PreviewReport:
    """Paths and diagnostics produced by :func:`generate_preview_report`."""

    index_path: Path
    preview_dir: Path
    assets_dir: Path
    scenes: tuple[PreviewScene, ...]
    warnings: tuple[str, ...]


_LAYOUTS = {
    "portrait": LayoutSpec("portrait", "세로 9:16", 1080, 1920),
    "landscape": LayoutSpec("landscape", "가로 16:9", 1920, 1080),
}
_LAYOUT_ALIASES = {
    "portrait": "portrait",
    "vertical": "portrait",
    "세로": "portrait",
    "landscape": "landscape",
    "horizontal": "landscape",
    "가로": "landscape",
}
_CONFORM_ALIASES = {
    "fit": "fit",
    "contain": "fit",
    "전체 보이기": "fit",
    "전체 보기": "fit",
    "fill": "fill",
    "cover": "fill",
    "화면 채우기": "fill",
    "채우기": "fill",
    "none": "none",
    "자동 맞춤 안 함": "none",
    "맞춤 안 함": "none",
    "원본": "none",
}
def _is_within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _clean_diagnostic(value: object, *, limit: int = 300) -> str:
    text = str(value or "")
    text = "".join(character if character in "\n\t" or ord(character) >= 32 else "�" for character in text)
    compact = " ".join(text.split())
    if len(compact) > limit:
        return compact[: limit - 1] + "…"
    return compact


def _clean_user_text(value: object, *, limit: int = 100_000) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    text = "".join(
        character if character in "\n\t" or ord(character) >= 32 else "�"
        for character in text
    )
    if len(text) > limit:
        return text[: limit - 1] + "…"
    return text


def _translate_filesystem_errors(function):
    """Keep direct API callers on the module's documented error type."""

    @wraps(function)
    def wrapped(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except PreviewReportError:
            raise
        except OSError as exc:
            detail = _clean_diagnostic(exc)
            raise PreviewReportError(f"미리보기 파일 처리에 실패했습니다: {detail}") from exc

    return wrapped


def _resolve_project_file(raw_path: str | Path, *, project_root: Path, field: str) -> Path:
    path = Path(raw_path)
    resolved = path.resolve() if path.is_absolute() else (project_root / path).resolve()
    if not _is_within(resolved, project_root):
        raise PreviewReportError(f"{field} 경로가 프로젝트 폴더 밖을 가리킵니다: {raw_path}")
    if not resolved.is_file():
        raise PreviewReportError(f"{field} 파일이 없습니다: {raw_path}")
    if resolved.stat().st_size > MAX_PREVIEW_CSV_BYTES:
        raise PreviewReportError(
            f"{field} 파일이 미리보기 제한 {MAX_PREVIEW_CSV_BYTES // (1024 * 1024)}MB를 넘습니다."
        )
    return resolved


def _resolve_output_root(raw_path: str | Path | None, *, project_root: Path) -> Path:
    if raw_path is None:
        resolved = (project_root / "output").resolve()
    else:
        path = Path(raw_path)
        resolved = path.resolve() if path.is_absolute() else (project_root / path).resolve()
    if not _is_within(resolved, project_root):
        raise PreviewReportError(f"output_root가 프로젝트 폴더 밖을 가리킵니다: {raw_path}")
    if resolved.exists() and not resolved.is_dir():
        raise PreviewReportError(f"output_root가 폴더가 아닙니다: {resolved}")
    return resolved


def _resolve_media_reference(
    file_text: str,
    *,
    project_root: Path,
    media_root: Path,
    row_number: int,
) -> Path:
    """Resolve a CSV media field without granting access outside media_root."""

    raw = file_text.strip()
    field = f"timeline.csv {row_number}행 file"
    if not raw:
        raise PreviewReportError(f"{field} 값이 없습니다.")
    if "\x00" in raw:
        raise PreviewReportError(f"{field}에 NUL 문자를 사용할 수 없습니다.")
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:(?://)?", raw):
        raise PreviewReportError(f"{field}에 URL 또는 URI를 사용할 수 없습니다: {raw}")
    if "\\" in raw or (os.name != "nt" and PureWindowsPath(raw).drive):
        raise PreviewReportError(f"{field}에 Windows/역슬래시 경로를 사용할 수 없습니다: {raw}")

    raw_path = Path(raw)
    if any(part == ".." for part in raw_path.parts):
        raise PreviewReportError(f"{field}에 상위 폴더 이동(..)을 사용할 수 없습니다: {raw}")

    candidates: list[Path] = []
    if raw_path.is_absolute():
        candidates.append(raw_path.resolve())
    else:
        candidates.extend(((project_root / raw_path).resolve(), (media_root / raw_path).resolve()))

    approved: list[Path] = []
    for candidate in candidates:
        if _is_within(candidate, media_root) and candidate not in approved:
            approved.append(candidate)
    if not approved:
        raise PreviewReportError(f"{field}이 Media 폴더 밖을 가리킵니다: {raw}")

    for candidate in approved:
        if candidate.is_file():
            return candidate
    # A missing in-bound media file becomes a visible placeholder instead of
    # preventing the rest of the report from being useful.
    return approved[0]


def _parse_time(value: str | None, *, field: str) -> Fraction:
    raw = str(value or "").strip().replace(",", ".")
    if not raw:
        raise PreviewReportError(f"{field} 값이 비어 있습니다.")
    parts = raw.split(":")
    if len(parts) == 1:
        try:
            total_seconds = Decimal(parts[0])
        except InvalidOperation as exc:
            raise PreviewReportError(
                f"{field} 시간 형식이 올바르지 않습니다: {value!r}"
            ) from exc
        if not total_seconds.is_finite() or total_seconds < 0:
            raise PreviewReportError(f"{field} 시간 범위를 확인하세요: {value!r}")
        return Fraction(total_seconds)
    elif len(parts) == 2:
        hours_text, minutes_text, seconds_text = "0", parts[0], parts[1]
    elif len(parts) == 3:
        hours_text, minutes_text, seconds_text = parts
    else:
        raise PreviewReportError(f"{field} 시간 형식이 올바르지 않습니다: {value!r}")
    try:
        hours = int(hours_text)
        minutes = int(minutes_text)
        seconds = Decimal(seconds_text)
    except (InvalidOperation, ValueError) as exc:
        raise PreviewReportError(f"{field} 시간 형식이 올바르지 않습니다: {value!r}") from exc
    if (
        hours < 0
        or minutes < 0
        or minutes >= 60
        or not seconds.is_finite()
        or seconds < 0
        or seconds >= 60
    ):
        raise PreviewReportError(f"{field} 시간 범위를 확인하세요: {value!r}")
    return Fraction(Decimal(hours * 3600 + minutes * 60) + seconds)


def _parse_optional_time(value: str | None, *, field: str) -> Fraction | None:
    if value is None or not str(value).strip():
        return None
    return _parse_time(value, field=field)


def _first_value(row: dict[str | None, object], *keys: str) -> str:
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
        candidate = normalized.get(key.strip().lower(), "")
        if candidate.strip():
            return candidate.strip()
    return ""


def _parse_enabled(value: str, *, row_number: int) -> bool:
    text = value.strip().lower()
    if not text:
        return True
    if text in {"1", "true", "yes", "y", "on", "예", "사용", "켜기", "켬"}:
        return True
    if text in {"0", "false", "no", "n", "off", "아니오", "미사용", "끄기", "끔"}:
        return False
    raise PreviewReportError(f"timeline.csv {row_number}행 enabled 값을 해석할 수 없습니다: {value!r}")


def _normalize_conform(value: str, *, field: str) -> str:
    normalized = _CONFORM_ALIASES.get(value.strip().lower())
    if normalized is None:
        raise PreviewReportError(
            f"{field}은 fit/fill/none 또는 전체 보이기/화면 채우기/맞춤 안 함이어야 합니다: {value!r}"
        )
    return normalized


def _infer_kind(path: Path, *, row_number: int) -> str:
    extension = path.suffix.lower()
    if extension in VIDEO_EXTENSIONS:
        return "video"
    if extension in IMAGE_EXTENSIONS:
        return "image"
    raise PreviewReportError(
        f"timeline.csv {row_number}행: 파일 종류를 판단할 수 없습니다. kind에 video 또는 image를 적으세요."
    )


def _validate_media_extension(path: Path, *, kind: str, row_number: int) -> None:
    """Keep an explicit ``kind`` cell from bypassing the media allowlist."""

    extension = path.suffix.lower()
    allowed = VIDEO_EXTENSIONS if kind == "video" else IMAGE_EXTENSIONS
    if extension not in allowed:
        rendered = extension or "(확장자 없음)"
        raise PreviewReportError(
            f"timeline.csv {row_number}행: {kind}에 지원하지 않는 확장자입니다: {rendered}"
        )


def _input_format_arguments(path: Path, *, kind: str) -> list[str]:
    """Return a forced local demuxer for an already validated media path."""

    extension = path.suffix.lower()
    if kind == "video":
        input_format = _VIDEO_INPUT_FORMATS[extension]
        arguments = ["-f", input_format]
        if input_format == "mov":
            # QuickTime data references are unnecessary for uploaded source
            # clips and can otherwise point at another local file.
            arguments.extend(("-enable_drefs", "0", "-use_absolute_path", "0"))
        return arguments
    if extension == ".heic":
        return ["-f", "mov", "-enable_drefs", "0", "-use_absolute_path", "0"]
    # ``pattern_type none`` prevents %, glob, or sequence expansion in an
    # otherwise authorized still-image filename.
    return ["-f", "image2", "-pattern_type", "none"]


def _load_timeline(
    path: Path,
    *,
    project_root: Path,
    media_root: Path,
    layouts: tuple[LayoutSpec, ...],
) -> list[TimelineScene]:
    scenes: list[TimelineScene] = []
    try:
        handle = path.open("r", encoding="utf-8-sig", newline="")
    except (OSError, UnicodeError) as exc:
        raise PreviewReportError(f"타임라인 CSV를 읽을 수 없습니다: {path.name}: {exc}") from exc

    try:
        with handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames:
                raise PreviewReportError("타임라인 CSV 헤더가 없습니다.")
            normalized_headers = [str(item or "").strip().lower() for item in reader.fieldnames]
            if len(normalized_headers) != len(set(normalized_headers)):
                raise PreviewReportError("타임라인 CSV에 중복 헤더가 있습니다.")
            for row_number, row in enumerate(reader, start=2):
                if None in row:
                    raise PreviewReportError(
                        f"timeline.csv {row_number}행: 헤더보다 값이 많습니다. 쉼표와 따옴표를 확인하세요."
                    )
                if not any(str(value or "").strip() for value in row.values()):
                    continue
                if not _parse_enabled(_first_value(row, "enabled", "사용"), row_number=row_number):
                    continue

                clip_id = _first_value(row, "id", "clip_id", "번호", "index") or f"clip_{row_number - 1:03d}"
                file_text = _first_value(row, "file", "filename", "파일", "media", "source")
                file_path = _resolve_media_reference(
                    file_text,
                    project_root=project_root,
                    media_root=media_root,
                    row_number=row_number,
                )
                kind = _first_value(row, "kind", "type", "종류").lower() or _infer_kind(
                    file_path, row_number=row_number
                )
                if kind not in {"video", "image"}:
                    raise PreviewReportError(
                        f"timeline.csv {row_number}행: kind는 video 또는 image여야 합니다: {kind!r}"
                    )
                _validate_media_extension(file_path, kind=kind, row_number=row_number)

                timeline_in = _parse_time(
                    _first_value(row, "timeline_in", "output in", "output_in", "시작", "in"),
                    field=f"timeline.csv {row_number}행 timeline_in",
                )
                timeline_out = _parse_time(
                    _first_value(row, "timeline_out", "output out", "output_out", "끝", "out"),
                    field=f"timeline.csv {row_number}행 timeline_out",
                )
                if timeline_out <= timeline_in:
                    raise PreviewReportError(
                        f"timeline.csv {row_number}행: timeline_out은 timeline_in보다 커야 합니다."
                    )
                duration = timeline_out - timeline_in
                source_in = _parse_optional_time(
                    _first_value(row, "source_in", "source in", "원본 시작"),
                    field=f"timeline.csv {row_number}행 source_in",
                )
                source_out = _parse_optional_time(
                    _first_value(row, "source_out", "source out", "원본 끝"),
                    field=f"timeline.csv {row_number}행 source_out",
                )
                if kind == "image":
                    source_in, source_out = Fraction(0), duration
                else:
                    source_in = source_in if source_in is not None else Fraction(0)
                    source_out = source_out if source_out is not None else source_in + duration
                if source_out <= source_in:
                    raise PreviewReportError(
                        f"timeline.csv {row_number}행: source_out은 source_in보다 커야 합니다."
                    )

                common_text = _first_value(row, "conform", "맞춤", "화면 맞춤") or "fit"
                common = _normalize_conform(
                    common_text, field=f"timeline.csv {row_number}행 conform"
                )
                conforms: list[tuple[str, str]] = []
                for layout in layouts:
                    # Each mapping entry is already the effective precision
                    # CSV that the XML builder consumes for that layout.  Read
                    # its normalized common conform only; honoring extra
                    # direction columns here would preview a value the precise
                    # XML engine itself ignores.
                    conforms.append((layout.name, common))
                scenes.append(
                    TimelineScene(
                        row_number=row_number,
                        clip_id=clip_id,
                        kind=kind,
                        file_text=file_text,
                        file_path=file_path,
                        timeline_in=timeline_in,
                        timeline_out=timeline_out,
                        source_in=source_in,
                        source_out=source_out,
                        conforms=tuple(conforms),
                        notes=_first_value(row, "notes", "note", "메모", "장면 의도"),
                    )
                )
                if len(scenes) > MAX_PREVIEW_SCENES:
                    raise PreviewReportError(
                        f"미리보기 장면은 최대 {MAX_PREVIEW_SCENES}개까지 지원합니다."
                    )
    except (csv.Error, UnicodeError) as exc:
        raise PreviewReportError(f"타임라인 CSV 형식을 읽을 수 없습니다: {exc}") from exc

    if not scenes:
        raise PreviewReportError("타임라인 CSV에 활성화된 장면이 없습니다.")
    scenes.sort(key=lambda item: (item.timeline_in, item.row_number))
    seen_ids: set[str] = set()
    cursor = Fraction(0)
    for scene in scenes:
        if scene.clip_id in seen_ids:
            raise PreviewReportError(f"중복 clip id가 있습니다: {scene.clip_id}")
        seen_ids.add(scene.clip_id)
        if scene.timeline_in < cursor:
            raise PreviewReportError(f"주 스토리라인 장면이 겹칩니다: {scene.clip_id}")
        cursor = scene.timeline_out
    return scenes


def _merge_layout_timelines(
    timelines: Mapping[str, list[TimelineScene]],
    *,
    layouts: tuple[LayoutSpec, ...],
) -> list[TimelineScene]:
    """Pair orientation-specific rows by clip id and retain each conform."""

    canonical_layout = layouts[0]
    canonical_scenes = timelines[canonical_layout.name]
    canonical_ids = [scene.clip_id for scene in canonical_scenes]
    canonical_set = set(canonical_ids)
    indexes: dict[str, dict[str, TimelineScene]] = {}
    for layout in layouts:
        index = {scene.clip_id: scene for scene in timelines[layout.name]}
        indexes[layout.name] = index
        missing = canonical_set - set(index)
        extra = set(index) - canonical_set
        if missing or extra:
            details: list[str] = []
            if missing:
                details.append("누락: " + ", ".join(sorted(missing)))
            if extra:
                details.append("추가: " + ", ".join(sorted(extra)))
            raise PreviewReportError(
                f"{layout.label} 정밀 CSV의 clip id 구성이 {canonical_layout.label}과 다릅니다 "
                f"({'; '.join(details)})."
            )

    merged: list[TimelineScene] = []
    structural_fields = (
        "kind",
        "file_path",
        "timeline_in",
        "timeline_out",
        "source_in",
        "source_out",
    )
    for canonical in canonical_scenes:
        conform_values: list[tuple[str, str]] = []
        for layout in layouts:
            candidate = indexes[layout.name][canonical.clip_id]
            mismatches = [
                field
                for field in structural_fields
                if getattr(candidate, field) != getattr(canonical, field)
            ]
            if mismatches:
                raise PreviewReportError(
                    f"clip id {canonical.clip_id}: {layout.label} 정밀 CSV의 "
                    f"{', '.join(mismatches)} 값이 {canonical_layout.label}과 다릅니다. "
                    "같은 장면끼리 나란히 비교할 수 있도록 맞춰주세요."
                )
            conform_values.append((layout.name, candidate.conform_for(layout.name)))
        merged.append(
            TimelineScene(
                row_number=canonical.row_number,
                clip_id=canonical.clip_id,
                kind=canonical.kind,
                file_text=canonical.file_text,
                file_path=canonical.file_path,
                timeline_in=canonical.timeline_in,
                timeline_out=canonical.timeline_out,
                source_in=canonical.source_in,
                source_out=canonical.source_out,
                conforms=tuple(conform_values),
                notes=canonical.notes,
            )
        )
    return merged


def _load_subtitles(path: Path | None) -> list[SubtitleCue]:
    if path is None:
        return []
    cues: list[SubtitleCue] = []
    try:
        handle = path.open("r", encoding="utf-8-sig", newline="")
    except (OSError, UnicodeError) as exc:
        raise PreviewReportError(f"자막 CSV를 읽을 수 없습니다: {path.name}: {exc}") from exc
    try:
        with handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames:
                raise PreviewReportError("자막 CSV 헤더가 없습니다.")
            normalized_headers = [str(item or "").strip().lower() for item in reader.fieldnames]
            if len(normalized_headers) != len(set(normalized_headers)):
                raise PreviewReportError("자막 CSV에 중복 헤더가 있습니다.")
            for row_number, row in enumerate(reader, start=2):
                if None in row:
                    raise PreviewReportError(
                        f"자막 CSV {row_number}행: 헤더보다 값이 많습니다. 쉼표와 따옴표를 확인하세요."
                    )
                if not any(str(value or "").strip() for value in row.values()):
                    continue
                cue_id = _first_value(row, "id", "caption_id", "번호", "index") or str(
                    row_number - 1
                )
                start = _parse_time(
                    _first_value(row, "start", "시작", "in"),
                    field=f"자막 CSV {row_number}행 시작",
                )
                end = _parse_time(
                    _first_value(row, "end", "끝", "out"),
                    field=f"자막 CSV {row_number}행 끝",
                )
                text = _first_value(row, "text", "caption", "최종 대사", "대사")
                if not text:
                    raise PreviewReportError(f"자막 CSV {row_number}행: 자막 문구가 없습니다.")
                if end <= start:
                    raise PreviewReportError(
                        f"자막 CSV {row_number}행: 끝 시간은 시작 시간보다 커야 합니다."
                    )
                cues.append(
                    SubtitleCue(
                        cue_id=cue_id,
                        start=start,
                        end=end,
                        text=text.replace("\\n", "\n"),
                        notes=_first_value(row, "notes", "note", "장면 의도", "메모"),
                    )
                )
                if len(cues) > MAX_PREVIEW_SUBTITLES:
                    raise PreviewReportError(
                        f"미리보기 자막은 최대 {MAX_PREVIEW_SUBTITLES}개까지 지원합니다."
                    )
    except (csv.Error, UnicodeError) as exc:
        raise PreviewReportError(f"자막 CSV 형식을 읽을 수 없습니다: {exc}") from exc
    cues.sort(key=lambda cue: (cue.start, cue.end, cue.cue_id))
    return cues


def _normalize_layouts(target_layouts: Sequence[str] | str) -> tuple[LayoutSpec, ...]:
    raw_layouts: Sequence[str] = (target_layouts,) if isinstance(target_layouts, str) else target_layouts
    result: list[LayoutSpec] = []
    seen: set[str] = set()
    for value in raw_layouts:
        normalized = _LAYOUT_ALIASES.get(str(value).strip().lower())
        if normalized is None:
            raise PreviewReportError(
                f"지원하지 않는 target layout입니다: {value!r}. portrait/landscape를 사용하세요."
            )
        if normalized not in seen:
            result.append(_LAYOUTS[normalized])
            seen.add(normalized)
    if not result:
        raise PreviewReportError("target_layouts에는 portrait 또는 landscape가 하나 이상 필요합니다.")
    return tuple(result)


def calculate_layout_assessment(
    source_width: int,
    source_height: int,
    *,
    layout: str,
    conform: str,
) -> LayoutAssessment:
    """Estimate the visible empty/cropped fraction for a source and layout.

    Percentages are totals across the named axis.  For example, 68% horizontal
    crop means roughly 34% from each side when the source remains centered.
    This is intentionally an approximate preflight warning; Final Cut spatial
    transforms applied later can change the result.
    """

    normalized_layout = _LAYOUT_ALIASES.get(str(layout).strip().lower())
    if normalized_layout is None:
        raise PreviewReportError(f"지원하지 않는 layout입니다: {layout!r}")
    normalized_conform = _normalize_conform(str(conform), field="conform")
    try:
        width, height = int(source_width), int(source_height)
    except (TypeError, ValueError) as exc:
        raise PreviewReportError("source_width/source_height는 양의 정수여야 합니다.") from exc
    if width <= 0 or height <= 0:
        raise PreviewReportError("source_width/source_height는 양의 정수여야 합니다.")

    spec = _LAYOUTS[normalized_layout]
    object_fit = "cover" if normalized_conform == "fill" else "contain"
    if normalized_conform == "none":
        return LayoutAssessment(
            layout=spec.name,
            conform=normalized_conform,
            object_fit=object_fit,
            effect="unknown",
            axis=None,
            total_percent=None,
            warning=(
                f"{spec.label}: 맞춤 안 함(none)은 원본 픽셀 크기와 후속 Transform에 따라 결과가 달라집니다. "
                "이 보고서는 잘림을 숨기지 않도록 contain으로 표시합니다."
            ),
        )

    source_aspect = Fraction(width, height)
    target_aspect = spec.aspect
    relative_difference = abs(float(source_aspect / target_aspect) - 1.0)
    if relative_difference < 0.005:
        return LayoutAssessment(
            layout=spec.name,
            conform=normalized_conform,
            object_fit=object_fit,
            effect="none",
            axis=None,
            total_percent=0.0,
            warning=None,
        )

    source_wider = source_aspect > target_aspect
    if source_wider:
        fraction = 1.0 - float(target_aspect / source_aspect)
    else:
        fraction = 1.0 - float(source_aspect / target_aspect)
    percent = max(0.0, min(100.0, fraction * 100.0))
    each = percent / 2.0
    source_label = f"{width}×{height}"

    if normalized_conform == "fit":
        if source_wider:
            effect, axis, side = "letterbox", "vertical", "상·하"
        else:
            effect, axis, side = "pillarbox", "horizontal", "좌·우"
        warning = (
            f"{spec.label}: {source_label} 원본을 fit(전체 보이기)하면 {side} 여백이 "
            f"합계 약 {percent:.1f}% 생깁니다(각 약 {each:.1f}%)."
        )
    else:
        if source_wider:
            effect, axis, side = "crop-x", "horizontal", "좌·우"
        else:
            effect, axis, side = "crop-y", "vertical", "상·하"
        warning = (
            f"{spec.label}: {source_label} 원본을 fill(화면 채우기)하면 {side}가 "
            f"합계 약 {percent:.1f}% 잘립니다(각 약 {each:.1f}%, 원본 축 기준)."
        )
    return LayoutAssessment(
        layout=spec.name,
        conform=normalized_conform,
        object_fit=object_fit,
        effect=effect,
        axis=axis,
        total_percent=percent,
        warning=warning,
    )


def _unknown_assessment(layout: LayoutSpec, conform: str, reason: str) -> LayoutAssessment:
    return LayoutAssessment(
        layout=layout.name,
        conform=conform,
        object_fit="cover" if conform == "fill" else "contain",
        effect="unknown",
        axis=None,
        total_percent=None,
        warning=f"{layout.label}: 원본 비율을 확인하지 못해 여백/잘림을 계산할 수 없습니다 ({reason}).",
    )


def _run_process(command: list[str], *, timeout_seconds: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=False,
        stdout=subprocess.PIPE,
        # FFmpeg runs with loglevel=error, but a damaged upload can still emit
        # unbounded diagnostics.  The exit code is enough for a clear
        # placeholder; discarding stderr avoids buffering attacker-controlled
        # output in RAM.
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_seconds,
    )


def _probe_dimensions(
    path: Path,
    *,
    kind: str,
    ffprobe_path: str,
    timeout_seconds: float,
) -> tuple[int | None, int | None, str | None]:
    if not path.is_file():
        return None, None, "미디어 파일이 없습니다"
    command = [
        ffprobe_path,
        "-v",
        "error",
        "-protocol_whitelist",
        "file",
        *_input_format_arguments(path, kind=kind),
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height:stream_tags=rotate:stream_side_data=rotation",
        "-of",
        "json",
        str(path),
    ]
    try:
        completed = _run_process(command, timeout_seconds=timeout_seconds)
    except FileNotFoundError:
        return None, None, f"ffprobe 실행 파일을 찾을 수 없습니다: {ffprobe_path}"
    except subprocess.TimeoutExpired:
        return None, None, f"ffprobe가 {timeout_seconds:g}초 안에 끝나지 않았습니다"
    except OSError as exc:
        return None, None, f"ffprobe 실행 실패: {_clean_diagnostic(exc)}"
    if completed.returncode != 0:
        detail = _clean_diagnostic(completed.stderr) or f"종료 코드 {completed.returncode}"
        return None, None, f"ffprobe 실패: {detail}"
    try:
        payload = json.loads(completed.stdout)
        stream = payload["streams"][0]
        width, height = int(stream["width"]), int(stream["height"])
        if width <= 0 or height <= 0:
            raise ValueError("non-positive dimensions")
        rotation_value: object = stream.get("tags", {}).get("rotate", 0)
        for side_data in stream.get("side_data_list", []):
            if "rotation" in side_data:
                rotation_value = side_data["rotation"]
                break
        rotation = int(float(rotation_value)) % 360
        if rotation in {90, 270}:
            width, height = height, width
    except (IndexError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return None, None, f"ffprobe 해상도 응답을 해석할 수 없습니다: {_clean_diagnostic(exc)}"
    return width, height, None


def _fraction_seconds(value: Fraction) -> str:
    rendered = format(Decimal(value.numerator) / Decimal(value.denominator), ".9f")
    return rendered.rstrip("0").rstrip(".") or "0"


def _render_thumbnail(
    scene: TimelineScene,
    *,
    output_path: Path,
    ffmpeg_path: str,
    thumbnail_max_size: int,
    timeout_seconds: float,
) -> str | None:
    if not scene.file_path.is_file():
        return "미디어 파일이 없습니다"
    descriptor, temporary_text = tempfile.mkstemp(
        prefix=f".{output_path.stem}.", suffix=".jpg", dir=output_path.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_text)
    scale = (
        f"scale=w='min(iw,{thumbnail_max_size})':h='min(ih,{thumbnail_max_size})':"
        "force_original_aspect_ratio=decrease:force_divisible_by=2"
    )
    command = [
        ffmpeg_path,
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-protocol_whitelist",
        "file",
        *_input_format_arguments(scene.file_path, kind=scene.kind),
    ]
    if scene.kind == "video":
        command.extend(("-ss", _fraction_seconds(scene.source_midpoint)))
    command.extend(
        (
            "-i",
            str(scene.file_path),
            "-map",
            "0:v:0",
            "-frames:v",
            "1",
            "-an",
            "-sn",
            "-dn",
            "-vf",
            scale,
            "-q:v",
            "3",
            "-y",
            str(temporary),
        )
    )
    try:
        try:
            completed = _run_process(command, timeout_seconds=timeout_seconds)
        except FileNotFoundError:
            return f"ffmpeg 실행 파일을 찾을 수 없습니다: {ffmpeg_path}"
        except subprocess.TimeoutExpired:
            return f"ffmpeg가 {timeout_seconds:g}초 안에 끝나지 않았습니다"
        except OSError as exc:
            return f"ffmpeg 실행 실패: {_clean_diagnostic(exc)}"
        if completed.returncode != 0:
            detail = _clean_diagnostic(completed.stderr) or f"종료 코드 {completed.returncode}"
            return f"ffmpeg 썸네일 생성 실패: {detail}"
        if not temporary.is_file() or temporary.stat().st_size == 0:
            return "ffmpeg가 정상 JPEG 썸네일을 만들지 못했습니다"
        if temporary.stat().st_size > MAX_THUMBNAIL_BYTES:
            return (
                "ffmpeg JPEG가 안전한 크기 제한 "
                f"{MAX_THUMBNAIL_BYTES // (1024 * 1024)}MB를 넘었습니다"
            )
        os.replace(temporary, output_path)
        return None
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _asset_name(index: int, scene: TimelineScene) -> str:
    try:
        stat = scene.file_path.stat()
        fingerprint = f"{scene.file_path}|{stat.st_size}|{stat.st_mtime_ns}|{scene.source_midpoint}"
    except OSError:
        fingerprint = f"{scene.file_path}|missing|{scene.source_midpoint}"
    digest = hashlib.sha256(fingerprint.encode("utf-8", errors="replace")).hexdigest()[:10]
    return f"scene-{index:04d}-{digest}.jpg"


def _display_time(value: Fraction) -> str:
    milliseconds = int(value * 1000 + Fraction(1, 2))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1000)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}"
    return f"{minutes:02d}:{seconds:02d}.{millis:03d}"


def _e(value: object) -> str:
    return html.escape(_clean_user_text(value), quote=True)


def _multiline_html(value: object) -> str:
    return _e(value).replace("\n", "<br>\n")


def _render_html(
    *,
    rendered_scenes: list[PreviewScene],
    layouts: tuple[LayoutSpec, ...],
    warnings: list[str],
) -> str:
    warning_items = "".join(f"<li>{_e(warning)}</li>" for warning in warnings)
    if warning_items:
        warning_section = (
            '<section class="summary warning-summary" aria-labelledby="warning-heading">'
            '<h2 id="warning-heading">확인할 항목</h2><ul>'
            f"{warning_items}</ul></section>"
        )
    else:
        warning_section = (
            '<section class="summary ok-summary"><h2>확인 결과</h2>'
            "<p>자동 미리보기에서 여백·잘림 또는 썸네일 경고를 찾지 못했습니다.</p></section>"
        )

    cards: list[str] = []
    for index, rendered in enumerate(rendered_scenes, start=1):
        scene = rendered.scene
        source_label = (
            f"{rendered.source_width}×{rendered.source_height}"
            if rendered.source_width and rendered.source_height
            else "확인 불가"
        )
        caption_markup = "".join(
            '<p class="caption-line">'
            f'<span class="caption-time">{_e(_display_time(cue.start))}–{_e(_display_time(cue.end))}</span>'
            f'<span class="caption-text">{_multiline_html(cue.text)}</span>'
            "</p>"
            for cue in rendered.subtitles
        )
        if not caption_markup:
            caption_markup = '<p class="no-caption">이 장면과 겹치는 자막 없음</p>'

        figures: list[str] = []
        assessments = {assessment.layout: assessment for assessment in rendered.assessments}
        for layout in layouts:
            assessment = assessments[layout.name]
            safe_label = (
                "숏폼 공통 안전영역"
                if layout.name == "portrait"
                else "가로 보수적 안전영역"
            )
            if rendered.thumbnail_path is not None:
                media_markup = (
                    f'<img class="media fit-{assessment.object_fit}" '
                    f'src="assets/{_e(rendered.thumbnail_path.name)}" '
                    f'alt="{_e(scene.clip_id)} 장면 썸네일">'
                )
            else:
                media_markup = (
                    '<div class="placeholder" role="img" aria-label="썸네일 생성 실패">'
                    "<strong>썸네일 생성 실패</strong>"
                    f"<span>{_e(rendered.thumbnail_error or '원인을 확인할 수 없습니다')}</span>"
                    "</div>"
                )
            layout_warning = (
                f'<p class="layout-warning">⚠ {_e(assessment.warning)}</p>'
                if assessment.warning
                else '<p class="layout-ok">비율 차이로 인한 큰 여백·잘림이 예상되지 않습니다.</p>'
            )
            figures.append(
                f'<figure class="layout-preview {layout.name}">'
                f"<figcaption><strong>{_e(layout.label)}</strong> · {assessment.conform} / "
                f"object-fit: {assessment.object_fit}</figcaption>"
                f'<div class="viewport {layout.name}">{media_markup}'
                f'<div class="safe-area" aria-label="{_e(safe_label)}">'
                f'<span class="safe-label">{_e(safe_label)}</span>'
                f'<div class="caption-stack">{caption_markup}</div>'
                "</div></div>"
                f"{layout_warning}</figure>"
            )

        scene_warnings = "".join(f"<li>{_e(warning)}</li>" for warning in rendered.warnings)
        warning_markup = (
            f'<details class="scene-warnings" open><summary>장면 경고</summary><ul>{scene_warnings}</ul></details>'
            if scene_warnings
            else ""
        )
        notes_markup = (
            f'<p class="notes"><strong>메모:</strong> {_multiline_html(scene.notes)}</p>'
            if scene.notes
            else ""
        )
        cards.append(
            '<article class="scene-card">'
            '<header class="scene-header">'
            f"<div><span class=\"scene-number\">장면 {index}</span><h2>{_e(scene.clip_id)}</h2></div>"
            f'<p class="timeline-range">{_e(_display_time(scene.timeline_in))}–'
            f"{_e(_display_time(scene.timeline_out))}</p>"
            "</header>"
            '<dl class="metadata">'
            f"<div><dt>파일</dt><dd>{_e(scene.file_text)}</dd></div>"
            f"<div><dt>종류</dt><dd>{_e(scene.kind)}</dd></div>"
            f"<div><dt>원본 비율</dt><dd>{_e(source_label)}</dd></div>"
            f"<div><dt>대표 프레임</dt><dd>{_e(_display_time(scene.source_midpoint))}</dd></div>"
            "</dl>"
            f"{notes_markup}<div class=\"layout-grid\">{''.join(figures)}</div>{warning_markup}"
            "</article>"
        )

    layout_names = " · ".join(layout.label for layout in layouts)
    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
  <title>FCPXML 생성 전 시각 미리보기</title>
  <style>
    :root {{ color-scheme: dark; font-family: -apple-system, BlinkMacSystemFont, "Apple SD Gothic Neo", sans-serif; }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; background: #0b0d12; color: #f4f6fb; line-height: 1.5; }}
    main {{ width: min(1500px, calc(100% - 32px)); margin: 0 auto; padding: 40px 0 72px; }}
    .page-header {{ margin-bottom: 28px; }}
    .eyebrow, .scene-number {{ color: #8fb4ff; font-size: .78rem; font-weight: 700; letter-spacing: .09em; text-transform: uppercase; }}
    h1 {{ margin: 4px 0 8px; font-size: clamp(1.8rem, 4vw, 3rem); }}
    h2 {{ margin: 3px 0; }}
    .lede, .timeline-range, .notes {{ color: #b9c0cf; }}
    .summary, .scene-card {{ border: 1px solid #2b3140; border-radius: 16px; background: #151923; box-shadow: 0 12px 32px #0005; }}
    .summary {{ margin: 22px 0; padding: 18px 22px; }}
    .warning-summary {{ border-color: #725526; background: #211b12; }}
    .ok-summary {{ border-color: #285f49; background: #102019; }}
    .summary h2 {{ font-size: 1.1rem; }}
    .summary ul, .scene-warnings ul {{ margin: 8px 0 0; padding-left: 22px; }}
    .scene-card {{ margin-top: 28px; padding: 22px; overflow: hidden; }}
    .scene-header {{ display: flex; justify-content: space-between; align-items: end; gap: 18px; border-bottom: 1px solid #2b3140; padding-bottom: 14px; }}
    .timeline-range {{ margin: 0; font-variant-numeric: tabular-nums; white-space: nowrap; }}
    .metadata {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin: 18px 0; }}
    .metadata div {{ min-width: 0; border-radius: 10px; background: #0f1219; padding: 10px 12px; }}
    dt {{ color: #929bad; font-size: .76rem; }}
    dd {{ margin: 2px 0 0; overflow-wrap: anywhere; }}
    .layout-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(330px, 1fr)); gap: 22px; align-items: start; }}
    figure {{ min-width: 0; margin: 0; border-radius: 12px; background: #0d1017; padding: 14px; }}
    figcaption {{ min-height: 28px; margin-bottom: 10px; color: #cad0dc; }}
    .viewport {{ position: relative; width: 100%; overflow: hidden; background: #030405; border: 1px solid #343b4c; border-radius: 8px; isolation: isolate; }}
    .viewport.portrait {{ width: min(100%, 315px); max-height: 560px; margin-inline: auto; aspect-ratio: 9 / 16; }}
    .viewport.landscape {{ aspect-ratio: 16 / 9; }}
    .media {{ position: absolute; inset: 0; width: 100%; height: 100%; }}
    .fit-contain {{ object-fit: contain; }}
    .fit-cover {{ object-fit: cover; }}
    .safe-area {{ position: absolute; border: 1px dashed #72f0b0cc; z-index: 2; pointer-events: none; }}
    .viewport.portrait .safe-area {{ top: 15%; right: 18%; bottom: 35%; left: 6%; }}
    .viewport.landscape .safe-area {{ inset: 7.5%; }}
    .safe-label {{ position: absolute; top: 0; left: 0; padding: 2px 5px; color: #07120c; background: #72f0b0dd; font-size: clamp(.48rem, .8vw, .7rem); font-weight: 700; }}
    .caption-stack {{ position: absolute; left: 4%; right: 4%; bottom: 4%; max-height: 45%; overflow: auto; text-align: center; }}
    .caption-line {{ margin: 5px 0; padding: 6px 9px; border-radius: 6px; background: #000c; color: white; font-size: clamp(.62rem, 1.5vw, 1rem); text-shadow: 0 1px 2px black; }}
    .caption-time {{ display: block; color: #a7b0c1; font-size: .66em; font-variant-numeric: tabular-nums; }}
    .caption-text {{ display: block; overflow-wrap: anywhere; }}
    .no-caption {{ display: inline-block; margin: 0; padding: 4px 7px; background: #0009; color: #c9cfda; font-size: .7rem; }}
    .placeholder {{ position: absolute; inset: 0; display: grid; place-content: center; gap: 7px; padding: 18%; text-align: center; color: #ffc2b8; background: repeating-linear-gradient(135deg, #271516, #271516 12px, #1b1012 12px, #1b1012 24px); }}
    .placeholder span {{ color: #dca49d; font-size: .78rem; overflow-wrap: anywhere; }}
    .layout-warning, .layout-ok {{ min-height: 48px; margin: 10px 2px 0; font-size: .87rem; }}
    .layout-warning {{ color: #ffd08b; }}
    .layout-ok {{ color: #82d9af; }}
    .scene-warnings {{ margin-top: 14px; color: #ffd08b; }}
    .scene-warnings summary {{ cursor: pointer; font-weight: 700; }}
    @media (max-width: 780px) {{
      main {{ width: min(100% - 20px, 1500px); padding-top: 24px; }}
      .scene-card {{ padding: 14px; }}
      .metadata {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .layout-grid {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
<main>
  <header class="page-header">
    <span class="eyebrow">CSV → FCPXML preflight</span>
    <h1>생성 전 시각 미리보기</h1>
    <p class="lede">{len(rendered_scenes)}개 장면 · {_e(layout_names)} · 세로 점선은 Reels·Shorts UI를 함께 고려한 보수적 공통 영역이고, 가로 점선은 각 변 7.5% 영역입니다. 비율 경고는 중앙 정렬 기준의 근사값입니다.</p>
  </header>
  {warning_section}
  {''.join(cards)}
</main>
</body>
</html>
"""


def _atomic_write_text(path: Path, content: str) -> None:
    descriptor, temporary_text = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_text)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            descriptor = -1
            handle.write(content)
        os.replace(temporary, path)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


@_translate_filesystem_errors
def generate_preview_report(
    *,
    project_root: str | Path,
    media_root: str | Path,
    timeline_csv: str | Path | None = None,
    timeline_csv_by_layout: Mapping[str, str | Path] | None = None,
    subtitles_csv: str | Path | None = None,
    output_root: str | Path | None = None,
    target_layouts: Sequence[str] | str = ("portrait", "landscape"),
    ffmpeg_path: str = "ffmpeg",
    ffprobe_path: str = "ffprobe",
    thumbnail_max_size: int = 960,
    timeout_seconds: float = 60.0,
    total_timeout_seconds: float = 15 * 60.0,
) -> PreviewReport:
    """Generate ``<output_root>/preview/index.html`` and JPEG assets.

    Inputs must use the precise schema (``timeline_in/out`` and optional
    ``source_in/out``).  Pass one ``timeline_csv`` when both previews share a
    precise CSV.  For the ``both`` workflow, pass
    ``timeline_csv_by_layout={"portrait": ..., "landscape": ...}``; rows are
    paired by clip id and each file's conform is retained.  Structural media
    and timing values must agree across the paired rows.  Korean aliases
    supported by the main builder are accepted as well.  ``subtitles_csv`` may
    be omitted.  Beginner direction-specific columns are normalized into the
    respective precision CSV before this API is called, so the preview and XML
    consume exactly the same effective ``conform`` value.

    Individual ffprobe/ffmpeg or missing-media failures do not abort the whole
    report: they produce a clearly labelled placeholder and warning.  Invalid
    CSV, unauthorized paths, and unsafe output locations raise
    :class:`PreviewReportError`.  At most 300 scenes and 5,000 subtitles are
    accepted, and external media work stops after the total timeout budget;
    remaining scenes then receive explicit placeholders.
    """

    root = Path(project_root).resolve()
    if not root.is_dir():
        raise PreviewReportError(f"project_root 폴더가 없습니다: {project_root}")
    media_path = Path(media_root)
    media = media_path.resolve() if media_path.is_absolute() else (root / media_path).resolve()
    if not media.is_dir():
        raise PreviewReportError(f"media_root 폴더가 없습니다: {media_root}")
    layouts = _normalize_layouts(target_layouts)
    try:
        max_size = int(thumbnail_max_size)
        timeout = float(timeout_seconds)
        total_timeout = float(total_timeout_seconds)
    except (TypeError, ValueError) as exc:
        raise PreviewReportError(
            "thumbnail_max_size와 timeout_seconds 값은 숫자여야 합니다."
        ) from exc
    if not 64 <= max_size <= 4096:
        raise PreviewReportError("thumbnail_max_size는 64~4096 범위여야 합니다.")
    if not 0 < timeout <= 3600:
        raise PreviewReportError("timeout_seconds는 0보다 크고 3600 이하여야 합니다.")
    if not 1 <= total_timeout <= 7200:
        raise PreviewReportError(
            "total_timeout_seconds는 1 이상 7200 이하여야 합니다."
        )

    if timeline_csv is not None and timeline_csv_by_layout is not None:
        raise PreviewReportError(
            "timeline_csv와 timeline_csv_by_layout을 동시에 지정할 수 없습니다."
        )
    if timeline_csv is None and timeline_csv_by_layout is None:
        raise PreviewReportError(
            "timeline_csv 또는 timeline_csv_by_layout 중 하나를 지정해야 합니다."
        )

    timeline_path: Path | None = None
    timeline_paths_by_layout: dict[str, Path] | None = None
    if timeline_csv_by_layout is not None:
        if not isinstance(timeline_csv_by_layout, Mapping):
            raise PreviewReportError("timeline_csv_by_layout은 layout과 CSV 경로의 매핑이어야 합니다.")
        timeline_paths_by_layout = {}
        for raw_layout, raw_path in timeline_csv_by_layout.items():
            normalized_layout = _LAYOUT_ALIASES.get(str(raw_layout).strip().lower())
            if normalized_layout is None:
                raise PreviewReportError(
                    f"timeline_csv_by_layout의 layout이 올바르지 않습니다: {raw_layout!r}"
                )
            if normalized_layout in timeline_paths_by_layout:
                raise PreviewReportError(
                    f"timeline_csv_by_layout에 중복 layout이 있습니다: {normalized_layout}"
                )
            timeline_paths_by_layout[normalized_layout] = _resolve_project_file(
                raw_path,
                project_root=root,
                field=f"timeline_csv_by_layout[{normalized_layout}]",
            )
        required_layouts = {layout.name for layout in layouts}
        missing_layouts = required_layouts - set(timeline_paths_by_layout)
        if missing_layouts:
            raise PreviewReportError(
                "timeline_csv_by_layout에 대상 layout CSV가 없습니다: "
                + ", ".join(sorted(missing_layouts))
            )
    else:
        timeline_path = _resolve_project_file(
            timeline_csv, project_root=root, field="timeline_csv"
        )
    subtitle_path: Path | None = None
    if subtitles_csv is not None and str(subtitles_csv).strip():
        subtitle_path = _resolve_project_file(
            subtitles_csv, project_root=root, field="subtitles_csv"
        )
    output = _resolve_output_root(output_root, project_root=root)
    preview_dir = (output / "preview").resolve()
    assets_dir = (preview_dir / "assets").resolve()
    for candidate, label in ((preview_dir, "preview"), (assets_dir, "preview/assets")):
        if not _is_within(candidate, root):
            raise PreviewReportError(f"{label} 출력 경로가 프로젝트 폴더 밖을 가리킵니다.")
        if candidate.exists() and not candidate.is_dir():
            raise PreviewReportError(f"{label} 출력 경로가 폴더가 아닙니다: {candidate}")
    output.mkdir(parents=True, exist_ok=True)
    preview_dir.mkdir(parents=True, exist_ok=True)
    assets_dir.mkdir(parents=True, exist_ok=True)
    # Re-check after mkdir so an existing symlinked component cannot redirect
    # generated thumbnails outside the authorized project tree.
    if not _is_within(preview_dir.resolve(), root) or not _is_within(assets_dir.resolve(), root):
        raise PreviewReportError("preview 출력 폴더의 심볼릭 링크가 프로젝트 밖을 가리킵니다.")

    if timeline_paths_by_layout is not None:
        timelines: dict[str, list[TimelineScene]] = {}
        for layout in layouts:
            timelines[layout.name] = _load_timeline(
                timeline_paths_by_layout[layout.name],
                project_root=root,
                media_root=media,
                layouts=(layout,),
            )
        scenes = _merge_layout_timelines(timelines, layouts=layouts)
    else:
        assert timeline_path is not None
        scenes = _load_timeline(
            timeline_path, project_root=root, media_root=media, layouts=layouts
        )
    subtitles = _load_subtitles(subtitle_path)
    rendered_scenes: list[PreviewScene] = []
    all_warnings: list[str] = []
    used_cues: set[int] = set()
    probe_cache: dict[Path, tuple[int | None, int | None, str | None]] = {}
    deadline = time.monotonic() + total_timeout

    for index, scene in enumerate(scenes, start=1):
        scene_warnings: list[str] = []
        scene_label = _clean_diagnostic(scene.clip_id, limit=120)
        if scene.file_path not in probe_cache:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                probe_cache[scene.file_path] = (
                    None,
                    None,
                    f"전체 미리보기 시간 제한 {total_timeout:g}초를 넘었습니다",
                )
            else:
                probe_cache[scene.file_path] = _probe_dimensions(
                    scene.file_path,
                    kind=scene.kind,
                    ffprobe_path=ffprobe_path,
                    timeout_seconds=min(timeout, remaining),
                )
        width, height, probe_error = probe_cache[scene.file_path]
        if probe_error:
            warning = f"장면 {scene_label}: 원본 비율 확인 실패 — {probe_error}"
            scene_warnings.append(warning)
            all_warnings.append(warning)

        asset_path = assets_dir / _asset_name(index, scene)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            thumbnail_error = (
                f"전체 미리보기 시간 제한 {total_timeout:g}초를 넘어 생성을 건너뛰었습니다"
            )
        else:
            thumbnail_error = _render_thumbnail(
                scene,
                output_path=asset_path,
                ffmpeg_path=ffmpeg_path,
                thumbnail_max_size=max_size,
                timeout_seconds=min(timeout, remaining),
            )
        if thumbnail_error:
            warning = f"장면 {scene_label}: 썸네일 생성 실패 — {thumbnail_error}"
            scene_warnings.append(warning)
            all_warnings.append(warning)
            thumbnail_path: Path | None = None
        else:
            thumbnail_path = asset_path

        overlapping: list[SubtitleCue] = []
        for cue_index, cue in enumerate(subtitles):
            if cue.start < scene.timeline_out and cue.end > scene.timeline_in:
                overlapping.append(cue)
                used_cues.add(cue_index)
                if len(overlapping) > MAX_SUBTITLES_PER_SCENE:
                    raise PreviewReportError(
                        f"장면 {scene_label}: 겹치는 자막이 {MAX_SUBTITLES_PER_SCENE}개를 넘습니다."
                    )

        assessments: list[LayoutAssessment] = []
        for layout in layouts:
            conform = scene.conform_for(layout.name)
            if width is not None and height is not None:
                assessment = calculate_layout_assessment(
                    width, height, layout=layout.name, conform=conform
                )
            else:
                assessment = _unknown_assessment(
                    layout, conform, probe_error or "알 수 없는 원인"
                )
            assessments.append(assessment)
            if assessment.warning:
                scene_warnings.append(assessment.warning)
                all_warnings.append(f"장면 {scene_label}: {assessment.warning}")

        rendered_scenes.append(
            PreviewScene(
                scene=scene,
                thumbnail_path=thumbnail_path,
                thumbnail_error=thumbnail_error,
                source_width=width,
                source_height=height,
                subtitles=tuple(overlapping),
                assessments=tuple(assessments),
                warnings=tuple(scene_warnings),
            )
        )

    for cue_index, cue in enumerate(subtitles):
        if cue_index not in used_cues:
            cue_label = _clean_diagnostic(cue.cue_id, limit=120)
            all_warnings.append(
                f"자막 {cue_label}: 어떤 활성 장면과도 겹치지 않아 미리보기에 표시되지 않습니다."
            )

    index_path = preview_dir / "index.html"
    page = _render_html(
        rendered_scenes=rendered_scenes,
        layouts=layouts,
        warnings=all_warnings,
    )
    _atomic_write_text(index_path, page)
    return PreviewReport(
        index_path=index_path,
        preview_dir=preview_dir,
        assets_dir=assets_dir,
        scenes=tuple(rendered_scenes),
        warnings=tuple(all_warnings),
    )


__all__ = [
    "LayoutAssessment",
    "PreviewReport",
    "PreviewReportError",
    "PreviewScene",
    "SubtitleCue",
    "TimelineScene",
    "calculate_layout_assessment",
    "generate_preview_report",
]
