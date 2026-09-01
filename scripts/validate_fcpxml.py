#!/usr/bin/env python3
"""Perform portable structural checks on generated FCPXML files."""

from __future__ import annotations

import argparse
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from fractions import Fraction
from pathlib import Path


LAYOUT_DIMENSIONS = {
    "portrait": (1080, 1920),
    "landscape": (1920, 1080),
}
COMMON_FPS = {
    "23.976": Fraction(24000, 1001),
    "29.97": Fraction(30000, 1001),
    "59.94": Fraction(60000, 1001),
}


def parse_expected_fps(value: str | int | float | Fraction) -> Fraction:
    text = str(value).strip()
    if text in COMMON_FPS:
        return COMMON_FPS[text]
    try:
        parsed = Fraction(text)
    except (ValueError, ZeroDivisionError) as exc:
        raise ValueError(f"fps를 해석할 수 없습니다: {value!r}") from exc
    if parsed <= 0:
        raise ValueError("fps는 0보다 커야 합니다.")
    return parsed


def parse_fcpxml_seconds(value: str) -> Fraction:
    if not value.endswith("s"):
        raise ValueError(f"초 단위가 아닌 FCPXML 시간입니다: {value!r}")
    try:
        parsed = Fraction(value[:-1])
    except (ValueError, ZeroDivisionError) as exc:
        raise ValueError(f"FCPXML 시간을 해석할 수 없습니다: {value!r}") from exc
    if parsed <= 0:
        raise ValueError(f"FCPXML 시간은 0보다 커야 합니다: {value!r}")
    return parsed


def resolve_media_uri(xml_path: Path, src: str) -> Path | None:
    parsed = urllib.parse.urlparse(src)
    if parsed.scheme == "file":
        return Path(urllib.request.url2pathname(urllib.parse.unquote(parsed.path)))
    if not parsed.scheme:
        return (xml_path.parent / urllib.parse.unquote(src)).resolve()
    return None


def validate(
    path: Path,
    *,
    check_media: bool,
    require_relative: bool = False,
    project_root: Path | None = None,
    expected_width: int | None = None,
    expected_height: int | None = None,
    expected_fps: str | int | float | Fraction | None = None,
) -> list[str]:
    errors: list[str] = []
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        return [f"XML을 읽을 수 없습니다: {exc}"]

    if root.tag != "fcpxml":
        errors.append(f"루트 요소가 fcpxml이 아닙니다: {root.tag}")
    if not root.get("version"):
        errors.append("fcpxml version이 없습니다.")

    resources_by_id = {
        element.get("id"): element
        for element in root.findall("./resources/*")
        if element.get("id")
    }
    resource_ids = set(resources_by_id)

    expected_frame_duration: Fraction | None = None
    if expected_fps is not None:
        try:
            expected_frame_duration = Fraction(1, 1) / parse_expected_fps(expected_fps)
        except ValueError as exc:
            errors.append(str(exc))

    if expected_width is not None and expected_width <= 0:
        errors.append("기대 width는 0보다 커야 합니다.")
    if expected_height is not None and expected_height <= 0:
        errors.append("기대 height는 0보다 커야 합니다.")

    for sequence in root.findall(".//project/sequence"):
        format_ref = sequence.get("format")
        project_format = resources_by_id.get(format_ref or "")
        if project_format is None or project_format.tag != "format":
            if expected_width is not None or expected_height is not None or expected_fps is not None:
                errors.append(
                    f"프로젝트 sequence의 format 리소스를 찾을 수 없습니다: {format_ref or '(none)'}"
                )
            continue
        if expected_width is not None and project_format.get("width") != str(expected_width):
            errors.append(
                f"프로젝트 width가 예상과 다릅니다: "
                f"{project_format.get('width', '(none)')} != {expected_width}"
            )
        if expected_height is not None and project_format.get("height") != str(expected_height):
            errors.append(
                f"프로젝트 height가 예상과 다릅니다: "
                f"{project_format.get('height', '(none)')} != {expected_height}"
            )
        if expected_frame_duration is not None:
            actual_text = project_format.get("frameDuration", "")
            try:
                actual_frame_duration = parse_fcpxml_seconds(actual_text)
            except ValueError as exc:
                errors.append(str(exc))
            else:
                if actual_frame_duration != expected_frame_duration:
                    actual_fps = Fraction(1, 1) / actual_frame_duration
                    expected_rate = Fraction(1, 1) / expected_frame_duration
                    errors.append(
                        f"프로젝트 fps가 예상과 다릅니다: {actual_fps} != {expected_rate}"
                    )
    text_style_ids = {
        element.get("id") for element in root.findall(".//text-style-def") if element.get("id")
    }
    for element in root.iter():
        ref = element.get("ref")
        if not ref:
            continue
        expected_ids = text_style_ids if element.tag == "text-style" else resource_ids
        if ref not in expected_ids:
            ref_kind = "text-style" if element.tag == "text-style" else "resource"
            errors.append(f"정의되지 않은 {ref_kind} ref: {ref}")

    title_child_order = {
        "param": 0,
        "text": 1,
        "text-style-def": 2,
        "note": 3,
        "adjust-color": 4,
        "adjust-crop": 4,
        "adjust-corners": 4,
        "adjust-conform": 4,
        "adjust-transform": 4,
        "adjust-blend": 4,
        "adjust-stabilization": 4,
        "adjust-rollingShutter": 4,
        "audio": 5,
        "video": 5,
        "clip": 5,
        "title": 5,
        "asset-clip": 5,
        "spine": 5,
        "marker": 6,
        "chapter-marker": 6,
        "rating": 6,
        "keyword": 6,
        "analysis-marker": 6,
        "filter-video": 7,
        "metadata": 8,
    }
    for title in root.findall(".//title"):
        effect = resources_by_id.get(title.get("ref", ""))
        if effect is None or effect.tag != "effect":
            errors.append(f"title ref가 effect 리소스를 가리키지 않습니다: {title.get('ref', '(none)')}")
        elif not effect.get("uid"):
            errors.append(f"title effect에 uid가 없습니다: {effect.get('id')}")
        if title.find("text") is None:
            errors.append(f"text가 없는 title이 있습니다: {title.get('name', '(unnamed)')}")
        ranks = [title_child_order.get(child.tag, 99) for child in title]
        if ranks != sorted(ranks):
            errors.append(f"title 자식 요소 순서가 FCPXML DTD와 다릅니다: {title.get('name', '(unnamed)')}")

    for media_rep in root.findall(".//media-rep"):
        src = media_rep.get("src")
        if not src:
            errors.append("src가 없는 media-rep가 있습니다.")
            continue
        parsed = urllib.parse.urlparse(src)
        if require_relative and (parsed.scheme or src.startswith("/")):
            errors.append(f"상대 URI가 아닌 media-rep src: {src}")
            continue
        if check_media:
            resolved = resolve_media_uri(path, src)
            if resolved is not None and not resolved.exists():
                errors.append(f"참조 미디어가 없습니다: {src} → {resolved}")
            if resolved is not None and project_root is not None:
                root_path = project_root.resolve()
                if resolved != root_path and root_path not in resolved.parents:
                    errors.append(f"참조 미디어가 프로젝트 폴더 밖을 가리킵니다: {src} → {resolved}")

    if root.find("./event/project/sequence/spine") is None and root.find("./library/event/project/sequence/spine") is None:
        errors.append("event/project/sequence/spine 구조를 찾지 못했습니다.")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="생성된 FCPXML의 XML·참조 구조를 검사합니다.")
    parser.add_argument("files", nargs="+", help="검사할 .fcpxml 파일")
    parser.add_argument("--check-media", action="store_true", help="src가 가리키는 로컬 미디어 존재 여부도 검사")
    parser.add_argument("--require-relative", action="store_true", help="모든 media-rep src가 상대 URI인지 검사")
    parser.add_argument("--project-root", default=None, help="모든 로컬 미디어가 이 폴더 안에 있는지 검사")
    parser.add_argument(
        "--expect-layout",
        choices=("portrait", "landscape"),
        default=None,
        help="프로젝트 해상도를 portrait=1080x1920 또는 landscape=1920x1080으로 검사",
    )
    parser.add_argument("--expect-width", type=int, default=None, help="기대 프로젝트 width")
    parser.add_argument("--expect-height", type=int, default=None, help="기대 프로젝트 height")
    parser.add_argument("--expect-fps", default=None, help="기대 프로젝트 fps (예: 30, 29.97)")
    args = parser.parse_args(argv)

    failed = False
    project_root = Path(args.project_root).expanduser().resolve() if args.project_root else None
    expected_width = args.expect_width
    expected_height = args.expect_height
    if args.expect_layout:
        layout_width, layout_height = LAYOUT_DIMENSIONS[args.expect_layout]
        if expected_width is not None and expected_width != layout_width:
            parser.error("--expect-layout과 --expect-width가 서로 다릅니다.")
        if expected_height is not None and expected_height != layout_height:
            parser.error("--expect-layout과 --expect-height가 서로 다릅니다.")
        expected_width, expected_height = layout_width, layout_height
    for file_text in args.files:
        path = Path(file_text).expanduser().resolve()
        errors = validate(
            path,
            check_media=args.check_media,
            require_relative=args.require_relative,
            project_root=project_root,
            expected_width=expected_width,
            expected_height=expected_height,
            expected_fps=args.expect_fps,
        )
        if errors:
            failed = True
            print(f"실패: {path}", file=sys.stderr)
            for error in errors:
                print(f"- {error}", file=sys.stderr)
        else:
            print(f"통과: {path}")
    return 2 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
