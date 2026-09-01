#!/usr/bin/env python3
"""Open a generated FCPXML document in Final Cut Pro on macOS."""

from __future__ import annotations

import argparse
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def open_fcpxml(path: str | Path) -> int:
    xml_path = Path(path).expanduser().resolve()
    if sys.platform != "darwin":
        print(
            "오류: Final Cut Pro에서 열기는 macOS에서만 사용할 수 있습니다. "
            "Colab에서는 XML을 다운로드한 뒤 Mac으로 옮겨주세요.",
            file=sys.stderr,
        )
        return 2
    if not xml_path.is_file():
        print(f"오류: FCPXML 파일이 없습니다: {xml_path}", file=sys.stderr)
        return 2
    if xml_path.suffix.lower() != ".fcpxml":
        print(f"오류: .fcpxml 파일을 선택하세요: {xml_path}", file=sys.stderr)
        return 2
    try:
        root = ET.parse(xml_path).getroot()
    except (OSError, ET.ParseError) as exc:
        print(f"오류: XML을 읽을 수 없습니다: {exc}", file=sys.stderr)
        return 2
    if root.tag != "fcpxml":
        print(f"오류: FCPXML 문서가 아닙니다: {xml_path}", file=sys.stderr)
        return 2

    availability = subprocess.run(
        ["open", "-Ra", "Final Cut Pro"],
        capture_output=True,
        text=True,
        check=False,
    )
    if availability.returncode != 0:
        print("오류: 이 Mac에서 Final Cut Pro를 찾지 못했습니다.", file=sys.stderr)
        return 2

    opened = subprocess.run(
        ["open", "-a", "Final Cut Pro", str(xml_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if opened.returncode != 0:
        detail = opened.stderr.strip() or opened.stdout.strip()
        print(f"오류: Final Cut Pro로 XML을 전달하지 못했습니다. {detail}", file=sys.stderr)
        return 2

    print(f"Final Cut Pro로 XML을 전달했습니다: {xml_path}")
    print("Final Cut Pro 화면에서 대상 Library/Event와 경고를 확인해 가져오기를 완료하세요.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="생성된 FCPXML을 macOS의 Final Cut Pro에서 엽니다."
    )
    parser.add_argument("fcpxml", help="가져올 .fcpxml 파일")
    args = parser.parse_args(argv)
    return open_fcpxml(args.fcpxml)


if __name__ == "__main__":
    raise SystemExit(main())
