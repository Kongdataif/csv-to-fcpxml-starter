#!/usr/bin/env python3
"""Mac beginner entry-point input discovery and temporary Excel conversion.

The build engine intentionally consumes CSV files.  This module keeps that
contract while allowing a beginner project folder to contain ``timeline.xlsx``
and, optionally, ``subtitles.xlsx``.  CSV inputs are returned unchanged.  XLSX
inputs are decoded by :mod:`spreadsheet_input` into a private temporary folder
inside the project root and are removed when the context manager exits.

Keeping discovery here also prevents a silent ``timeline.xlsx`` versus
``timeline.csv`` preference.  If both exist, the user must choose one with the
corresponding command-line option.
"""

from __future__ import annotations

import tempfile
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Literal

import csv_to_fcpxml as builder
from spreadsheet_input import (
    NUMBERS_EXPORT_GUIDANCE,
    PlanInputError,
    decode_uploaded_plan,
)


PlanKind = Literal["timeline", "subtitles"]

MAX_TIMELINE_ROWS = 5_000
MAX_SUBTITLE_ROWS = 10_000
MAX_XLSX_BYTES = 10 * 1024 * 1024

_MAX_ROWS: dict[PlanKind, int] = {
    "timeline": MAX_TIMELINE_ROWS,
    "subtitles": MAX_SUBTITLE_ROWS,
}
_SUPPORTED_SUFFIXES = {".csv", ".xlsx"}
_RESERVED_SUBTITLE_STEMS = {"subtitle", "subtitles"}


@dataclass(frozen=True)
class PreparedPlanInput:
    """One selected user file and the CSV path consumed by the build engine."""

    source_path: Path
    csv_path: Path
    source_description: str

    @property
    def converted(self) -> bool:
        return self.csv_path != self.source_path


@dataclass(frozen=True)
class PreparedMacInputs:
    """Prepared timeline plus an optional separately timed subtitle sheet."""

    timeline: PreparedPlanInput
    subtitles: PreparedPlanInput | None


def _project_root(path: str | Path) -> Path:
    root = Path(path).expanduser().resolve()
    if not root.is_dir():
        raise builder.BuildError(f"프로젝트 폴더가 없습니다: {root}")
    return root


def _display_path(path: Path, project_root: Path) -> str:
    try:
        return path.relative_to(project_root).as_posix()
    except ValueError:
        return str(path)


def _require_project_file(path: Path, project_root: Path, *, label: str) -> Path:
    """Resolve a regular file without allowing the beginner CLI to leave root."""

    resolved = path.resolve()
    if resolved != project_root and project_root not in resolved.parents:
        raise builder.BuildError(
            f"{label} 경로가 프로젝트 폴더 밖을 가리킵니다: {path}"
        )
    if not resolved.is_file():
        raise builder.BuildError(f"{label} 파일이 없습니다: {resolved}")
    return resolved


def _validate_suffix(path: Path, *, label: str, option: str) -> None:
    suffix = path.suffix.lower()
    if suffix == ".numbers":
        raise builder.BuildError(NUMBERS_EXPORT_GUIDANCE)
    if suffix not in _SUPPORTED_SUFFIXES:
        shown = suffix or "(확장자 없음)"
        raise builder.BuildError(
            f"{label} 형식은 .xlsx 또는 UTF-8 .csv만 지원합니다: {shown}. "
            f"파일을 다시 저장하거나 {option}으로 올바른 파일을 지정해주세요."
        )


def _requested_file(
    project_root: Path,
    requested: str | Path,
    *,
    label: str,
    option: str,
) -> Path:
    path = Path(requested).expanduser()
    _validate_suffix(path, label=label, option=option)
    candidate = path if path.is_absolute() else project_root / path
    return _require_project_file(candidate, project_root, label=label)


def _directory_entries(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    try:
        return sorted(
            directory.iterdir(),
            key=lambda path: (path.name.casefold(), path.name),
        )
    except OSError as exc:
        raise builder.BuildError(
            f"폴더의 입력 파일을 확인하지 못했습니다: {directory}: {exc}"
        ) from exc


def _regular_files(entries: list[Path]) -> list[Path]:
    return [path for path in entries if path.is_file()]


def _raise_ambiguous(
    candidates: list[Path],
    project_root: Path,
    *,
    label: str,
    option: str,
) -> None:
    names = ", ".join(_display_path(path, project_root) for path in candidates)
    raise builder.BuildError(
        f"{label} 파일이 여러 개라 자동으로 고를 수 없습니다: {names}\n"
        f"{option} 파일명으로 사용할 파일을 명시해주세요."
    )


def _read_xlsx_payload(path: Path, *, label: str) -> bytes:
    """Read at most the same 10 MiB accepted by ``decode_uploaded_plan``."""

    try:
        with path.open("rb") as handle:
            payload = handle.read(MAX_XLSX_BYTES + 1)
    except OSError as exc:
        raise builder.BuildError(
            f"{label} Excel 파일을 읽지 못했습니다: {path}: {exc}"
        ) from exc
    if len(payload) > MAX_XLSX_BYTES:
        raise builder.BuildError(
            f"{label} Excel 파일이 너무 큽니다. "
            "압축된 .xlsx 크기는 10 MiB 이하여야 합니다."
        )
    return payload


def choose_timeline(
    project_root: str | Path,
    requested: str | Path | None,
) -> Path:
    """Choose one timeline XLSX/CSV without silently preferring an extension."""

    root = _project_root(project_root)
    if requested is not None:
        return _requested_file(
            root,
            requested,
            label="타임라인",
            option="--timeline",
        )

    root_entries = _directory_entries(root)
    root_files = _regular_files(root_entries)
    conventional = [
        path
        for path in root_files
        if path.name.casefold() in {"timeline.xlsx", "timeline.csv"}
    ]
    if len(conventional) > 1:
        _raise_ambiguous(
            conventional,
            root,
            label="타임라인",
            option="--timeline",
        )
    if conventional:
        return _require_project_file(conventional[0], root, label="타임라인")

    candidates = [
        path
        for path in root_files
        if path.suffix.lower() in _SUPPORTED_SUFFIXES
        and path.stem.casefold() not in _RESERVED_SUBTITLE_STEMS
    ]
    if len(candidates) == 1:
        return _require_project_file(candidates[0], root, label="타임라인")
    if len(candidates) > 1:
        _raise_ambiguous(
            candidates,
            root,
            label="타임라인",
            option="--timeline",
        )

    if any(path.name.casefold() == "timeline.numbers" for path in root_entries):
        raise builder.BuildError(NUMBERS_EXPORT_GUIDANCE)
    raise builder.BuildError(
        f"타임라인 파일이 없습니다: {root}\n"
        "프로젝트 폴더에 timeline.xlsx 또는 UTF-8 timeline.csv를 넣어주세요."
    )


def choose_subtitles(
    project_root: str | Path,
    requested: str | Path | None,
    *,
    disabled: bool,
) -> Path | None:
    """Choose an optional subtitles XLSX/CSV, including ``Docs/*대사표*``."""

    root = _project_root(project_root)
    if disabled:
        return None
    if requested is not None:
        return _requested_file(
            root,
            requested,
            label="자막",
            option="--subtitles",
        )

    docs = root / "Docs"
    root_entries = _directory_entries(root)
    docs_entries = _directory_entries(docs)
    root_files = _regular_files(root_entries)
    docs_files = _regular_files(docs_entries)
    conventional = [
        path
        for path in (*root_files, *docs_files)
        if path.name.casefold() in {"subtitles.xlsx", "subtitles.csv"}
    ]
    if len(conventional) > 1:
        _raise_ambiguous(
            conventional,
            root,
            label="자막",
            option="--subtitles",
        )
    if conventional:
        return _require_project_file(conventional[0], root, label="자막")

    dialogue_sheets = [
        path
        for path in docs_files
        if "대사표" in path.name and path.suffix.lower() in _SUPPORTED_SUFFIXES
    ]
    if len(dialogue_sheets) == 1:
        return _require_project_file(dialogue_sheets[0], root, label="자막")
    if len(dialogue_sheets) > 1:
        _raise_ambiguous(
            dialogue_sheets,
            root,
            label="대사표",
            option="--subtitles",
        )

    numbers_candidates = [
        path
        for path in (*root_entries, *docs_entries)
        if path.name.casefold() == "subtitles.numbers"
        or ("대사표" in path.name and path.suffix.lower() == ".numbers")
    ]
    if numbers_candidates:
        raise builder.BuildError(NUMBERS_EXPORT_GUIDANCE)
    return None


@contextmanager
def prepare_plan_csv(
    source: str | Path,
    *,
    project_root: str | Path,
    kind: PlanKind,
) -> Iterator[PreparedPlanInput]:
    """Yield a build-ready CSV and always remove XLSX conversion artifacts.

    A source CSV is deliberately neither decoded nor copied.  XLSX goes through
    ``decode_uploaded_plan`` so its ZIP/XML security checks and the per-kind row
    limit are identical to the Colab upload path.
    """

    root = _project_root(project_root)
    if kind not in _MAX_ROWS:
        raise builder.BuildError("kind는 'timeline' 또는 'subtitles'여야 합니다.")

    label = "타임라인" if kind == "timeline" else "자막"
    option = "--timeline" if kind == "timeline" else "--subtitles"
    source_path = Path(source).expanduser()
    _validate_suffix(source_path, label=label, option=option)
    if not source_path.is_absolute():
        source_path = root / source_path
    source_path = _require_project_file(source_path, root, label=label)

    if source_path.suffix.lower() == ".csv":
        yield PreparedPlanInput(
            source_path=source_path,
            csv_path=source_path,
            source_description="CSV 파일",
        )
        return

    # The unique directory is inside the project boundary required by the
    # beginner engine, but separate from user files and Generated/.  It is
    # deleted on success, validation error, decoder error, and KeyboardInterrupt.
    with tempfile.TemporaryDirectory(prefix=".fcpxml_input_", dir=root) as temp_text:
        payload = _read_xlsx_payload(source_path, label=label)

        try:
            _, canonical_bytes, description = decode_uploaded_plan(
                source_path.name,
                payload,
                kind=kind,
                max_rows=_MAX_ROWS[kind],
            )
        except PlanInputError as exc:
            raise builder.BuildError(f"{label} Excel 파일을 읽을 수 없습니다: {exc}") from exc

        csv_path = Path(temp_text) / f"{kind}.normalized.csv"
        try:
            csv_path.write_bytes(canonical_bytes)
        except OSError as exc:
            raise builder.BuildError(
                f"{label} 임시 CSV를 준비하지 못했습니다: {exc}"
            ) from exc

        yield PreparedPlanInput(
            source_path=source_path,
            csv_path=csv_path,
            source_description=description,
        )


@contextmanager
def prepare_mac_inputs(
    project_root: str | Path,
    *,
    timeline: str | Path | None = None,
    subtitles: str | Path | None = None,
    no_subtitles: bool = False,
) -> Iterator[PreparedMacInputs]:
    """Discover and prepare all Mac beginner inputs for one complete build."""

    root = _project_root(project_root)
    if no_subtitles and subtitles is not None:
        raise builder.BuildError(
            "--no-subtitles와 --subtitles는 함께 사용할 수 없습니다."
        )

    timeline_source = choose_timeline(root, timeline)
    subtitle_source = choose_subtitles(root, subtitles, disabled=no_subtitles)

    with ExitStack() as stack:
        prepared_timeline = stack.enter_context(
            prepare_plan_csv(timeline_source, project_root=root, kind="timeline")
        )
        prepared_subtitles = (
            stack.enter_context(
                prepare_plan_csv(subtitle_source, project_root=root, kind="subtitles")
            )
            if subtitle_source is not None
            else None
        )
        yield PreparedMacInputs(
            timeline=prepared_timeline,
            subtitles=prepared_subtitles,
        )
