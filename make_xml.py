#!/usr/bin/env python3
"""Beginner entry point: turn Excel/CSV + Media/ into portable FCPXML."""

from __future__ import annotations

import argparse
import sys
import tempfile
from contextlib import ExitStack
from pathlib import Path

import csv_to_fcpxml as builder
import make_xml_input
import preview_report
import simple_timeline


def require_project_path(path: Path, project_root: Path, *, label: str) -> Path:
    """Return a resolved path only when it stays inside the project folder.

    ``make_xml.py`` is the beginner/Colab entry point, so it deliberately has a
    smaller trust boundary than the advanced engine.  In particular, a CSV
    uploaded for this workflow must not make the converter read a sibling or
    system folder through an absolute path.
    """

    resolved = path.resolve()
    root = project_root.resolve()
    if resolved != root and root not in resolved.parents:
        raise builder.BuildError(f"{label} 경로가 프로젝트 폴더 밖을 가리킵니다: {path}")
    return resolved


def update_build_report_inputs(
    report_path: Path,
    *,
    project_root: Path,
    timeline_input: make_xml_input.PreparedPlanInput,
    effective_timeline: Path,
    subtitle_input: make_xml_input.PreparedPlanInput | None,
    effective_subtitles: Path | None,
    summary: simple_timeline.SimpleTimelineSummary | None,
) -> None:
    """Replace disposable CSV paths with the user's original Excel/CSV names.

    The core engine reports the exact normalized CSV it read.  Excel decoding
    and the beginner adapter both create temporary CSVs that disappear after
    this command, so the durable report must identify the original workbook
    and selected sheet instead.  Beginner conversion statistics and warnings
    are appended when ``summary`` is present.
    """

    if not report_path.is_file():
        return

    def portable(path: Path) -> str:
        return path.resolve().relative_to(project_root.resolve()).as_posix()

    text = report_path.read_text(encoding="utf-8")
    text = text.replace(
        f"Timeline CSV: {portable(effective_timeline)}",
        "Timeline input: "
        f"{portable(timeline_input.source_path)} "
        f"({timeline_input.source_description})",
    )
    if effective_subtitles is not None:
        subtitle_description: str | None = None
        if (
            summary is not None
            and summary.subtitles_csv is not None
            and effective_subtitles.resolve() == summary.subtitles_csv.resolve()
        ):
            subtitle_description = (
                f"{portable(timeline_input.source_path)}의 '화면 자막' 열 "
                f"({timeline_input.source_description})"
            )
        elif subtitle_input is not None:
            subtitle_description = (
                f"{portable(subtitle_input.source_path)} "
                f"({subtitle_input.source_description})"
            )
        if subtitle_description is not None:
            text = text.replace(
                f"Subtitle CSV: {portable(effective_subtitles)}",
                f"Subtitle input: {subtitle_description}",
            )

    if summary is None:
        builder.atomic_write_text(report_path, text)
        return

    input_lines = [
        "Input preparation:",
        f"- Beginner rows: {summary.clip_count}",
        f"- Videos: {summary.video_count}",
        f"- Photos: {summary.image_count}",
        f"- Inline titles: {summary.subtitle_count}",
        f"- Accumulated duration: {builder.display_time(summary.total_duration)}",
    ]
    input_lines.extend(f"- Input warning: {warning}" for warning in summary.warnings)
    section = "\n".join(input_lines) + "\n\n"
    text = text.replace("\nClip map:\n", f"\n{section}Clip map:\n", 1)
    builder.atomic_write_text(report_path, text)


def choose_timeline(project_root: Path, requested: str | None) -> Path:
    """Compatibility wrapper for callers that imported the old CSV helper."""

    return make_xml_input.choose_timeline(project_root, requested)


def choose_subtitles(project_root: Path, requested: str | None, *, disabled: bool) -> Path | None:
    """Compatibility wrapper for callers that imported the old CSV helper."""

    return make_xml_input.choose_subtitles(
        project_root,
        requested,
        disabled=disabled,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "timeline.xlsx 또는 timeline.csv, Media/, 선택 subtitles.xlsx/.csv로 "
            "Final Cut Pro용 FCPXML을 만듭니다."
        ),
        epilog=(
            "예: python3 make_xml.py projects/my-video  |  "
            "세로+가로: python3 make_xml.py projects/my-video --layout both"
        ),
    )
    parser.add_argument(
        "project",
        help="timeline.xlsx 또는 timeline.csv와 Media/가 들어 있는 프로젝트 폴더",
    )
    parser.add_argument(
        "--timeline",
        default=None,
        help=(
            "타임라인 .xlsx/.csv 파일명. 두 형식이 모두 있으면 반드시 지정"
        ),
    )
    parser.add_argument(
        "--subtitles",
        default=None,
        help=(
            "선택 자막 .xlsx/.csv. 기본 subtitles 파일, Docs/subtitles 파일 "
            "또는 유일한 *대사표* 파일"
        ),
    )
    parser.add_argument(
        "--subtitle-mode",
        choices=("title", "caption", "both", "off"),
        default="title",
        help="title=화면 자막(추천), caption=접근성 캡션, both=두 XML 생성, off=XML 자막 끔",
    )
    parser.add_argument("--no-srt", action="store_true", help="업로드용 SRT를 생성하지 않음")
    parser.add_argument(
        "--no-subtitles",
        action="store_true",
        help="자동 자막 .xlsx/.csv 감지를 끔",
    )
    parser.add_argument("--media-dir", default="Media", help="미디어 폴더명. 기본 Media")
    parser.add_argument("--output-dir", default="Generated", help="결과 폴더명. 기본 Generated")
    parser.add_argument("--project-name", default=None, help="Final Cut에 표시할 프로젝트 이름")
    parser.add_argument("--fps", default="30", help="프로젝트 fps. 기본 30")
    parser.add_argument(
        "--photo-duration",
        default="3",
        help="간편 CSV에서 사진 시간이 비었을 때 쓸 초. 기본 3",
    )
    layout = parser.add_mutually_exclusive_group()
    layout.add_argument(
        "--layout",
        choices=("portrait", "landscape", "both"),
        default=None,
        help="portrait=세로 9:16, landscape=가로 16:9, both=둘 다",
    )
    layout.add_argument("--portrait", action="store_true", help="세로 1080x1920 (기본)")
    layout.add_argument("--landscape", action="store_true", help="가로 1920x1080")
    parser.add_argument("--validate-only", action="store_true", help="입력만 검사하고 XML은 만들지 않음")
    parser.add_argument(
        "--preview-only",
        action="store_true",
        help="입력을 검사한 뒤 세로·가로 썸네일 HTML만 만들고 XML은 만들지 않음",
    )
    parser.add_argument(
        "--open",
        action="store_true",
        help="생성 후 macOS의 Final Cut Pro로 XML을 전달함",
    )
    args = parser.parse_args(argv)

    selected_layout = args.layout
    if selected_layout is None:
        selected_layout = "landscape" if args.landscape else "portrait"

    if args.validate_only and args.preview_only:
        parser.error("--validate-only와 --preview-only는 함께 사용할 수 없습니다.")
    if args.open and (args.validate_only or args.preview_only):
        parser.error("--open은 --validate-only 또는 --preview-only와 함께 사용할 수 없습니다.")
    if args.no_subtitles and args.subtitles:
        parser.error("--no-subtitles와 --subtitles는 함께 사용할 수 없습니다.")

    try:
        project_root = Path(args.project).expanduser().resolve()
        if not project_root.is_dir():
            raise builder.BuildError(f"프로젝트 폴더가 없습니다: {project_root}")

        # Excel normalization and beginner conversion files are implementation
        # details. Keep both context managers alive through report rewriting,
        # then remove every temporary CSV on success, validation failure, or
        # Ctrl-C. Only Generated/ is a user-facing output.
        with ExitStack() as temporary_inputs:
            plan_inputs = temporary_inputs.enter_context(
                make_xml_input.prepare_mac_inputs(
                    project_root,
                    timeline=args.timeline,
                    subtitles=args.subtitles,
                    no_subtitles=args.no_subtitles,
                )
            )
            timeline = plan_inputs.timeline.csv_path
            external_subtitles = (
                plan_inputs.subtitles.csv_path
                if plan_inputs.subtitles is not None
                else None
            )

            media_text = Path(args.media_dir).expanduser()
            media_root = (
                media_text.resolve()
                if media_text.is_absolute()
                else (project_root / media_text).resolve()
            )
            media_root = require_project_path(
                media_root,
                project_root,
                label="Media 폴더",
            )
            if not media_root.is_dir():
                raise builder.BuildError(f"Media 폴더가 없습니다: {media_root}")

            # The supplied table can be either the sequential beginner sheet
            # or the precision timeline. The normalized CSV header decides;
            # users do not need a technical mode flag.
            input_mode = simple_timeline.detect_csv_mode(timeline)

            layouts = (
                ("portrait", "landscape") if selected_layout == "both" else (selected_layout,)
            )
            prepared: list[
                tuple[
                    str,
                    Path,
                    Path | None,
                    simple_timeline.SimpleTimelineSummary | None,
                ]
            ] = []

            if input_mode == "beginner":
                temporary_root = Path(
                    temporary_inputs.enter_context(
                        tempfile.TemporaryDirectory(prefix=".fcpxml_input_", dir=project_root)
                    )
                )
                for layout_name in layouts:
                    layout_root = temporary_root / layout_name
                    summary = simple_timeline.build_simple_timeline(
                        timeline,
                        media_root,
                        layout_root / "timeline.precision.csv",
                        layout_root / "inline_subtitles.csv",
                        default_photo_duration=args.photo_duration,
                        fps=args.fps,
                        layout=layout_name,
                    )
                    inline_subtitles = summary.subtitles_csv
                    if inline_subtitles is not None and external_subtitles is not None:
                        raise builder.BuildError(
                            "자막 입력이 두 곳에 있습니다. 간편 CSV의 '화면 자막' 열과 "
                            "별도 subtitles.xlsx/.csv 중 하나만 사용해주세요."
                        )
                    subtitles = (
                        None
                        if args.no_subtitles
                        else (inline_subtitles or external_subtitles)
                    )
                    prepared.append(
                        (layout_name, summary.timeline_csv, subtitles, summary)
                    )
                    label = "세로 9:16" if layout_name == "portrait" else "가로 16:9"
                    confirmation_prefix = (
                        f"간편 CSV 확인 [{label}]:"
                        if len(layouts) > 1
                        else "간편 CSV 확인:"
                    )
                    print(
                        f"{confirmation_prefix} "
                        f"장면 {summary.clip_count}개 "
                        f"(영상 {summary.video_count}, 사진 {summary.image_count}), "
                        f"전체 {builder.display_time(summary.total_duration)}, "
                        f"화면 자막 {summary.subtitle_count}개"
                    )
                    for warning in summary.warnings:
                        print(f"경고 [{label}]: {warning}")
            else:
                print("정밀 CSV 형식을 감지했습니다. 기존 타임라인 시간을 그대로 사용합니다.")
                subtitles = None if args.no_subtitles else external_subtitles
                prepared.extend((layout_name, timeline, subtitles, None) for layout_name in layouts)

            commands: list[
                tuple[
                    str,
                    list[str],
                    Path | None,
                    simple_timeline.SimpleTimelineSummary | None,
                ]
            ] = []
            output_root = Path(args.output_dir).expanduser()
            if not output_root.is_absolute():
                output_root = project_root / output_root
            profiled_output = args.layout is not None

            for layout_name, effective_timeline, subtitles, beginner_summary in prepared:
                command = [
                    "--quick-project",
                    str(project_root),
                    "--timeline",
                    str(effective_timeline),
                    "--media-dir",
                    str(media_root),
                    "--output-dir",
                    args.output_dir,
                    "--fps",
                    args.fps,
                    "--path-mode",
                    "relative",
                ]
                if profiled_output:
                    command.extend(["--layout", layout_name])
                elif layout_name == "landscape":
                    command.append("--landscape")
                else:
                    command.append("--portrait")
                if args.project_name:
                    command.extend(["--project-name", args.project_name])
                if subtitles is not None:
                    command.extend(
                        ["--subtitles", str(subtitles), "--subtitle-mode", args.subtitle_mode]
                    )
                    if args.no_srt:
                        command.append("--no-srt")
                elif args.no_subtitles:
                    command.append("--no-subtitles")
                commands.append((layout_name, command, subtitles, beginner_summary))

            # With two targets, validate both complete input interpretations
            # before rendering either one. This avoids producing a portrait
            # result and only then discovering an invalid landscape override.
            if args.preview_only or (len(commands) > 1 and not args.validate_only):
                for _, command, _, _ in commands:
                    result = builder.main([*command, "--validate-only"])
                    if result != 0:
                        return result

            if args.preview_only:
                timeline_csv_by_layout = {
                    layout_name: Path(command[command.index("--timeline") + 1])
                    for layout_name, command, _, _ in commands
                }
                subtitles_for_preview = next(
                    (
                        effective_subtitles
                        for _, _, effective_subtitles, _ in commands
                        if effective_subtitles is not None
                    ),
                    None,
                )
                try:
                    preview = preview_report.generate_preview_report(
                        timeline_csv_by_layout=timeline_csv_by_layout,
                        subtitles_csv=subtitles_for_preview,
                        project_root=project_root,
                        media_root=media_root,
                        output_root=output_root,
                        target_layouts=layouts,
                    )
                except preview_report.PreviewReportError as exc:
                    raise builder.BuildError(f"미리보기를 만들지 못했습니다: {exc}") from exc
                print(f"미리보기 생성 완료: {preview.index_path}")
                for warning in preview.warnings:
                    print(f"미리보기 경고: {warning}")
                print("HTML을 브라우저에서 확인한 뒤 --preview-only를 빼고 다시 실행하세요.")
                return 0

            for layout_name, command, effective_subtitles, beginner_summary in commands:
                effective_command = [*command]
                if args.validate_only:
                    effective_command.append("--validate-only")
                result = builder.main(effective_command)
                if result != 0:
                    return result
                if not args.validate_only:
                    profile = builder.LAYOUT_PROFILES[layout_name]
                    report_root = (
                        output_root / str(profile["folder"])
                        if profiled_output
                        else output_root
                    )
                    effective_timeline = Path(
                        command[command.index("--timeline") + 1]
                    )
                    update_build_report_inputs(
                        report_root / "build_report.txt",
                        project_root=project_root,
                        timeline_input=plan_inputs.timeline,
                        effective_timeline=effective_timeline,
                        subtitle_input=plan_inputs.subtitles,
                        effective_subtitles=effective_subtitles,
                        summary=beginner_summary,
                    )

            if args.validate_only or not args.open:
                return 0

            from open_in_final_cut import open_fcpxml

            for layout_name, _, subtitles, _ in commands:
                profile = builder.LAYOUT_PROFILES[layout_name]
                variant_root = (
                    output_root / str(profile["folder"])
                    if profiled_output
                    else output_root
                )
                base_name = builder.safe_output_basename(
                    args.project_name or project_root.name
                )
                output_name = (
                    builder.suffixed_output_basename(
                        base_name,
                        str(profile["basename_suffix"]),
                    )
                    if profiled_output
                    else base_name
                )
                candidates: list[Path] = []
                if subtitles is not None and args.subtitle_mode in {"title", "both"}:
                    candidates.append(variant_root / f"{output_name}_with_titles.fcpxml")
                if subtitles is not None and args.subtitle_mode in {"caption", "both"}:
                    candidates.append(variant_root / f"{output_name}_with_captions.fcpxml")
                candidates.append(variant_root / f"{output_name}_clean.fcpxml")
                xml_path = next((path for path in candidates if path.is_file()), None)
                if xml_path is None:
                    raise builder.BuildError(
                        "생성 완료로 보고되었지만 열 수 있는 FCPXML을 찾지 못했습니다: "
                        + ", ".join(str(path) for path in candidates)
                    )
                open_result = open_fcpxml(xml_path)
                if open_result != 0:
                    print(
                        f"XML 생성은 완료되었습니다: {xml_path}\n"
                        "Final Cut Pro에서 File > Import > XML로 직접 선택할 수 있습니다.",
                        file=sys.stderr,
                    )
                    return open_result
            return 0
    except builder.BuildError as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
