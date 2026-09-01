#!/usr/bin/env python3
"""Generate tiny, redistributable demo media with FFmpeg filters."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def run_ffmpeg(arguments: list[str], output: Path, *, force: bool) -> None:
    if output.exists() and not force:
        print(f"재사용: {output}")
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y", *arguments, str(output)]
    subprocess.run(command, check=True)
    print(f"생성: {output}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="6초 데모용 영상·사진·BGM을 생성합니다.")
    parser.add_argument(
        "--project",
        default=str(Path(__file__).resolve().parents[1] / "examples" / "demo_project"),
        help="demo_project 폴더",
    )
    parser.add_argument("--force", action="store_true", help="기존 데모 미디어를 다시 생성")
    parser.add_argument("--no-bgm", action="store_true", help="BGM 데모 파일은 만들지 않음")
    args = parser.parse_args(argv)

    if shutil.which("ffmpeg") is None:
        print("오류: ffmpeg가 없습니다. Mac에서는 `brew install ffmpeg` 후 다시 실행하세요.", file=sys.stderr)
        return 2

    project = Path(args.project).expanduser().resolve()
    media = project / "Media"
    audio = project / "Audio"

    try:
        run_ffmpeg(
            [
                "-f", "lavfi", "-i", "color=c=0x4f75d8:s=720x1280:r=30:d=2",
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=2",
                "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
            ],
            media / "scene_01.mp4",
            force=args.force,
        )
        run_ffmpeg(
            [
                "-f", "lavfi", "-i", "color=c=0xf39bb4:s=720x1280:r=1",
                "-frames:v", "1",
            ],
            media / "scene_02.png",
            force=args.force,
        )
        run_ffmpeg(
            [
                "-f", "lavfi", "-i", "color=c=0x6b3fa0:s=720x1280:r=30:d=2",
                "-f", "lavfi", "-i", "sine=frequency=660:sample_rate=48000:duration=2",
                "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
            ],
            media / "scene_03.mp4",
            force=args.force,
        )
        if not args.no_bgm:
            run_ffmpeg(
                [
                    "-f", "lavfi", "-i", "sine=frequency=220:sample_rate=48000:duration=6",
                    "-af", "volume=0.08", "-c:a", "aac", "-b:a", "128k",
                ],
                audio / "demo_bgm.m4a",
                force=args.force,
            )
    except subprocess.CalledProcessError as exc:
        print(f"오류: 데모 미디어 생성에 실패했습니다 (exit {exc.returncode}).", file=sys.stderr)
        return 2

    print("데모 미디어 준비 완료")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
