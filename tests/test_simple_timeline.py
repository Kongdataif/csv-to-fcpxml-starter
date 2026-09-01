from __future__ import annotations

import csv
import os
import tempfile
import unittest
import unicodedata
from fractions import Fraction
from pathlib import Path
from unittest import mock

import csv_to_fcpxml as engine
import simple_timeline as simple


def video_info(
    duration: Fraction,
    *,
    has_audio: bool = True,
    fps: Fraction = Fraction(30),
) -> engine.MediaInfo:
    """테스트에서 실제 ffprobe를 실행하지 않기 위한 영상 정보."""

    return engine.MediaInfo(
        duration=duration,
        width=1920,
        height=1080,
        fps=fps,
        has_video=True,
        has_audio=has_audio,
        audio_rate=48_000 if has_audio else None,
        audio_channels=2 if has_audio else None,
        video_duration=duration,
    )


class SimpleTimelineTests(unittest.TestCase):
    def make_root(self) -> tuple[tempfile.TemporaryDirectory[str], Path, Path]:
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        media = root / "Media"
        media.mkdir()
        return temporary, root, media

    @staticmethod
    def read_rows(path: Path) -> list[dict[str, str]]:
        with path.open("r", encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))

    def test_detects_beginner_and_precision_headers(self) -> None:
        self.assertEqual(simple.detect_header_mode(["파일", "화면 자막"]), "beginner")
        self.assertEqual(
            simple.detect_header_mode(["file", "timeline_in", "timeline_out"]),
            "precision",
        )
        self.assertEqual(simple.detect_header_mode(["파일", "시작", "끝"]), "precision")

    def test_mixed_video_and_photo_accumulates_timeline_and_uses_defaults(self) -> None:
        temporary, root, media = self.make_root()
        with temporary:
            (media / "카페 영상.mov").touch()
            (media / "아이패드 그림.png").touch()
            source = root / "간편.csv"
            source.write_text(
                "파일,영상 원본 시작,영상 원본 끝,사진 표시 시간(초),화면 자막,소리,화면 맞춤,메모\n"
                "카페 영상.mov,00:00:02.000,00:00:06.000,,카페에서 첫 부팅,사용,화면 채우기,오프닝\n"
                "아이패드 그림.png,,,,그림 완성,사용,전체 보기,사진 장면\n",
                encoding="utf-8",
            )
            timeline = root / "generated_timeline.csv"
            subtitles = root / "generated_subtitles.csv"

            with mock.patch.object(engine, "probe_media", return_value=video_info(Fraction(10))):
                result = simple.build_simple_timeline(
                    source, media, timeline, subtitles, default_photo_duration=Fraction(3)
                )

            rows = self.read_rows(timeline)
            self.assertEqual([row["kind"] for row in rows], ["video", "image"])
            self.assertEqual((rows[0]["timeline_in"], rows[0]["timeline_out"]), ("0", "4"))
            self.assertEqual((rows[1]["timeline_in"], rows[1]["timeline_out"]), ("4", "7"))
            self.assertEqual(rows[0]["conform"], "fill")
            self.assertEqual(rows[1]["conform"], "fit")
            self.assertEqual(rows[0]["include_audio"], "true")
            self.assertEqual(rows[1]["include_audio"], "false")
            self.assertEqual(rows[0]["volume_db"], "0")
            self.assertEqual(result.total_duration, Fraction(7))
            self.assertEqual((result.video_count, result.image_count), (1, 1))
            self.assertEqual(result.subtitle_count, 2)
            self.assertEqual(len(result.warnings), 1)  # 사진 행의 소리 값은 무시됨

            title_rows = self.read_rows(subtitles)
            self.assertEqual((title_rows[1]["시작"], title_rows[1]["끝"]), ("4", "7"))

    def test_whole_video_is_probed_and_blank_audio_defaults_on(self) -> None:
        temporary, root, media = self.make_root()
        with temporary:
            video = media / "whole.mp4"
            video.touch()
            source = root / "simple.csv"
            source.write_text("파일,소리\nwhole.mp4,\n", encoding="utf-8")

            with mock.patch.object(engine, "probe_media", return_value=video_info(Fraction(13, 2))) as probe:
                result = simple.build_simple_timeline(source, media, root / "timeline.csv")

            row = self.read_rows(root / "timeline.csv")[0]
            self.assertEqual((row["source_in"], row["source_out"]), ("0", "6.5"))
            self.assertEqual(row["timeline_out"], "6.5")
            self.assertEqual(row["include_audio"], "true")
            self.assertEqual(result.total_duration, Fraction(13, 2))
            probe.assert_called_once_with(video.resolve())

    def test_fractional_default_photo_duration_is_kept_exactly(self) -> None:
        temporary, root, media = self.make_root()
        with temporary:
            (media / "still.png").touch()
            source = root / "simple.csv"
            source.write_text("파일\nstill.png\n", encoding="utf-8")
            result = simple.build_simple_timeline(
                source,
                media,
                root / "timeline.csv",
                default_photo_duration=Fraction(5, 2),
            )
            self.assertEqual(result.total_duration, Fraction(5, 2))
            self.assertEqual(self.read_rows(root / "timeline.csv")[0]["timeline_out"], "2.5")

    def test_fractional_clip_lengths_accumulate_as_integer_project_frames(self) -> None:
        temporary, root, media = self.make_root()
        with temporary:
            (media / "a.png").touch()
            (media / "b.png").touch()
            source = root / "simple.csv"
            source.write_text(
                "파일,사진 표시 시간(초)\na.png,0.02\nb.png,0.02\n", encoding="utf-8"
            )
            result = simple.build_simple_timeline(
                source, media, root / "timeline.csv", fps=Fraction(30)
            )
            rows = self.read_rows(root / "timeline.csv")
            self.assertEqual(result.total_duration, Fraction(1, 15))
            self.assertEqual(len(result.warnings), 2)
            # 두 번째 시작점은 첫 번째의 반올림되지 않은 0.02초가 아니라
            # 정확히 1프레임 뒤여야 한다.
            self.assertAlmostEqual(float(rows[1]["timeline_in"]), 1 / 30, places=8)
            self.assertAlmostEqual(float(rows[1]["timeline_out"]), 2 / 30, places=8)
            self.assertEqual(rows[0]["source_out"], rows[0]["timeline_out"])

    def test_trimmed_video_uses_requested_source_range_and_audio_label(self) -> None:
        temporary, root, media = self.make_root()
        with temporary:
            (media / "trim.mov").touch()
            source = root / "simple.csv"
            source.write_text(
                "파일,영상 원본 시작,영상 원본 끝,소리,화면 맞춤\n"
                "trim.mov,1.2,4.7,끄기,자동 맞춤 안 함\n",
                encoding="utf-8",
            )
            with mock.patch.object(engine, "probe_media", return_value=video_info(Fraction(8))):
                simple.build_simple_timeline(source, media, root / "timeline.csv")

            row = self.read_rows(root / "timeline.csv")[0]
            self.assertEqual((row["source_in"], row["source_out"]), ("1.2", "4.7"))
            self.assertEqual(row["timeline_out"], "3.5")
            self.assertEqual(row["include_audio"], "false")
            self.assertEqual(row["conform"], "none")

    def test_direction_specific_conform_overrides_common_value(self) -> None:
        temporary, root, media = self.make_root()
        with temporary:
            (media / "still.png").touch()
            source = root / "simple.csv"
            source.write_text(
                "파일,화면 맞춤,세로 화면 맞춤,가로 화면 맞춤\n"
                "still.png,전체 보이기,화면 채우기,전체 보이기\n",
                encoding="utf-8",
            )

            simple.build_simple_timeline(
                source,
                media,
                root / "portrait.csv",
                layout="portrait",
            )
            simple.build_simple_timeline(
                source,
                media,
                root / "landscape.csv",
                layout="landscape",
            )

            self.assertEqual(self.read_rows(root / "portrait.csv")[0]["conform"], "fill")
            self.assertEqual(self.read_rows(root / "landscape.csv")[0]["conform"], "fit")

    def test_blank_direction_specific_conform_falls_back_to_common_value(self) -> None:
        temporary, root, media = self.make_root()
        with temporary:
            (media / "still.png").touch()
            source = root / "simple.csv"
            source.write_text(
                "파일,화면 맞춤,세로 화면 맞춤,가로 화면 맞춤\n"
                "still.png,화면 채우기,,\n",
                encoding="utf-8",
            )

            for layout in ("portrait", "landscape"):
                output = root / f"{layout}.csv"
                simple.build_simple_timeline(source, media, output, layout=layout)
                self.assertEqual(self.read_rows(output)[0]["conform"], "fill")

    def test_selected_direction_conform_has_column_specific_error(self) -> None:
        temporary, root, media = self.make_root()
        with temporary:
            (media / "still.png").touch()
            source = root / "simple.csv"
            source.write_text(
                "파일,화면 맞춤,세로 화면 맞춤,가로 화면 맞춤\n"
                "still.png,전체 보이기,왼쪽 맞춤,무시되는 값\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(engine.BuildError, "세로 화면 맞춤.*왼쪽 맞춤"):
                simple.build_simple_timeline(
                    source,
                    media,
                    root / "portrait.csv",
                    layout="portrait",
                )

            # 가로 생성에서는 가로 열만 검사하므로 세로 열의 오타가 오류의
            # 원인으로 잘못 표시되지 않는다.
            with self.assertRaisesRegex(engine.BuildError, "가로 화면 맞춤.*무시되는 값"):
                simple.build_simple_timeline(
                    source,
                    media,
                    root / "landscape.csv",
                    layout="landscape",
                )

    def test_layout_must_be_portrait_or_landscape(self) -> None:
        temporary, root, media = self.make_root()
        with temporary:
            (media / "still.png").touch()
            source = root / "simple.csv"
            source.write_text("파일\nstill.png\n", encoding="utf-8")
            with self.assertRaisesRegex(engine.BuildError, "portrait.*landscape"):
                simple.build_simple_timeline(
                    source,
                    media,
                    root / "timeline.csv",
                    layout="both",
                )

    def test_source_endpoints_are_snapped_before_project_duration(self) -> None:
        temporary, root, media = self.make_root()
        with temporary:
            (media / "source24.mov").touch()
            source = root / "simple.csv"
            source.write_text(
                "파일,영상 원본 시작,영상 원본 끝\nsource24.mov,0.02,0.07\n",
                encoding="utf-8",
            )
            info = video_info(Fraction(10), fps=Fraction(24))
            with mock.patch.object(engine, "probe_media", return_value=info):
                result = simple.build_simple_timeline(
                    source, media, root / "timeline.csv", fps=Fraction(30)
                )
                # 생성된 정밀 CSV가 실제 기존 엔진의 source/project frame
                # 검증까지 통과하는지 확인한다(24fps 원본 → 30fps 프로젝트).
                clips, load_warnings = engine.load_timeline(
                    root / "timeline.csv",
                    project_root=root,
                    media_root=media,
                    fps=Fraction(30),
                    frame_tolerance=Fraction(1, 60),
                )
                engine.prepare_clips(
                    clips,
                    config={"image_mode": "direct"},
                    output_root=root / "Generated",
                    fps=Fraction(30),
                    project_width=1920,
                    project_height=1080,
                    frame_tolerance=Fraction(1, 60),
                    render_images=False,
                    warnings=load_warnings,
                )
            row = self.read_rows(root / "timeline.csv")[0]
            self.assertAlmostEqual(float(row["source_in"]), 0.0, places=8)
            self.assertAlmostEqual(float(row["source_out"]), 2 / 24, places=8)
            self.assertEqual(result.total_duration, Fraction(1, 10))  # 3 project frames
            self.assertGreaterEqual(len(result.warnings), 2)  # source snap + project snap

    def test_order_column_sorts_positive_unique_values(self) -> None:
        temporary, root, media = self.make_root()
        with temporary:
            (media / "first.png").touch()
            (media / "second.png").touch()
            source = root / "simple.csv"
            source.write_text(
                "순서,파일,사진 표시 시간(초)\n"
                "2,second.png,2\n"
                "1,first.png,1\n",
                encoding="utf-8",
            )
            simple.build_simple_timeline(source, media, root / "timeline.csv")
            rows = self.read_rows(root / "timeline.csv")
            self.assertEqual([row["file"] for row in rows], ["first.png", "second.png"])
            self.assertEqual([row["timeline_in"] for row in rows], ["0", "1"])

    def test_inline_title_requires_and_generates_subtitle_output(self) -> None:
        temporary, root, media = self.make_root()
        with temporary:
            (media / "still.png").touch()
            source = root / "simple.csv"
            source.write_text("파일,화면 자막\nstill.png,안녕하세요\n", encoding="utf-8")
            with self.assertRaisesRegex(engine.BuildError, "자막 출력 경로"):
                simple.build_simple_timeline(source, media, root / "timeline.csv")

            result = simple.build_simple_timeline(
                source, media, root / "timeline.csv", root / "subtitles.csv"
            )
            subtitle = self.read_rows(root / "subtitles.csv")[0]
            self.assertEqual(subtitle["최종 대사"], "안녕하세요")
            self.assertEqual((subtitle["시작"], subtitle["끝"]), ("0", "3"))
            self.assertEqual(result.subtitles_csv, root / "subtitles.csv")

    def test_one_sided_video_trim_has_friendly_row_error(self) -> None:
        temporary, root, media = self.make_root()
        with temporary:
            (media / "clip.mp4").touch()
            source = root / "simple.csv"
            source.write_text(
                "파일,영상 원본 시작,영상 원본 끝\nclip.mp4,1,\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(engine.BuildError, "2행.*둘 다"):
                simple.build_simple_timeline(source, media, root / "timeline.csv")

    def test_photo_rejects_video_trim_fields(self) -> None:
        temporary, root, media = self.make_root()
        with temporary:
            (media / "still.jpg").touch()
            source = root / "simple.csv"
            source.write_text(
                "파일,영상 원본 시작,영상 원본 끝\nstill.jpg,0,1\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(engine.BuildError, "2행.*사진에는"):
                simple.build_simple_timeline(source, media, root / "timeline.csv")

    def test_photo_none_conform_is_reported_and_normalized_to_safe_fit(self) -> None:
        temporary, root, media = self.make_root()
        with temporary:
            (media / "still.jpg").touch()
            source = root / "simple.csv"
            source.write_text(
                "파일,화면 맞춤\nstill.jpg,자동 맞춤 안 함\n", encoding="utf-8"
            )
            summary = simple.build_simple_timeline(source, media, root / "timeline.csv")
            self.assertEqual(self.read_rows(root / "timeline.csv")[0]["conform"], "fit")
            self.assertRegex(summary.warnings[0], "사진.*전체 보이기")

    def test_video_rejects_photo_duration(self) -> None:
        temporary, root, media = self.make_root()
        with temporary:
            (media / "clip.mp4").touch()
            source = root / "simple.csv"
            source.write_text("파일,사진 표시 시간(초)\nclip.mp4,3\n", encoding="utf-8")
            with self.assertRaisesRegex(engine.BuildError, "2행.*영상에는"):
                simple.build_simple_timeline(source, media, root / "timeline.csv")

    def test_duplicate_order_reports_both_rows(self) -> None:
        temporary, root, media = self.make_root()
        with temporary:
            (media / "a.png").touch()
            (media / "b.png").touch()
            source = root / "simple.csv"
            source.write_text("순서,파일\n1,a.png\n1,b.png\n", encoding="utf-8")
            with self.assertRaisesRegex(engine.BuildError, "3행.*중복.*2행"):
                simple.build_simple_timeline(source, media, root / "timeline.csv")

    def test_filename_must_match_exactly_and_must_not_be_a_path(self) -> None:
        temporary, root, media = self.make_root()
        with temporary:
            (media / "Intro.MOV").touch()
            source = root / "simple.csv"
            source.write_text("파일\nintro.mov\n", encoding="utf-8")
            with self.assertRaisesRegex(engine.BuildError, "2행.*대소문자"):
                simple.build_simple_timeline(source, media, root / "timeline.csv")

            source.write_text("파일\nMedia/Intro.MOV\n", encoding="utf-8")
            with self.assertRaisesRegex(engine.BuildError, "2행.*파일명만"):
                simple.build_simple_timeline(source, media, root / "timeline.csv")

    def test_filename_with_comma_is_safely_quoted_in_generated_csv(self) -> None:
        temporary, root, media = self.make_root()
        with temporary:
            (media / "scene,one.png").touch()
            source = root / "simple.csv"
            source.write_text('파일,메모\n"scene,one.png","쉼표, 메모"\n', encoding="utf-8")
            simple.build_simple_timeline(source, media, root / "timeline.csv")
            row = self.read_rows(root / "timeline.csv")[0]
            self.assertEqual(row["file"], "scene,one.png")
            self.assertEqual(row["notes"], "쉼표, 메모")

    def test_nfc_csv_name_matches_unique_nfd_macos_filename(self) -> None:
        temporary, root, media = self.make_root()
        with temporary:
            nfc_name = "한글.png"
            nfd_name = unicodedata.normalize("NFD", nfc_name)
            self.assertNotEqual(nfc_name, nfd_name)
            (media / nfd_name).touch()
            source = root / "simple.csv"
            source.write_text(f"파일\n{nfc_name}\n", encoding="utf-8")
            result = simple.build_simple_timeline(source, media, root / "timeline.csv")
            row = self.read_rows(root / "timeline.csv")[0]
            self.assertEqual(row["file"], nfd_name)
            self.assertRegex(result.warnings[0], "Unicode 표기.*자동 연결")

    @unittest.skipUnless(hasattr(os, "symlink"), "symbolic links are unavailable")
    def test_symlink_media_is_rejected_before_probe(self) -> None:
        temporary, root, media = self.make_root()
        with temporary:
            outside = root / "outside.mov"
            outside.touch()
            (media / "linked.mov").symlink_to(outside)
            source = root / "simple.csv"
            source.write_text("파일\nlinked.mov\n", encoding="utf-8")
            with mock.patch.object(engine, "probe_media") as probe:
                with self.assertRaisesRegex(engine.BuildError, "2행.*심볼릭 링크"):
                    simple.build_simple_timeline(source, media, root / "timeline.csv")
            probe.assert_not_called()

    def test_directory_named_like_video_is_rejected_before_probe(self) -> None:
        temporary, root, media = self.make_root()
        with temporary:
            (media / "fake.mov").mkdir()
            source = root / "simple.csv"
            source.write_text("파일\nfake.mov\n", encoding="utf-8")
            with mock.patch.object(engine, "probe_media") as probe:
                with self.assertRaisesRegex(engine.BuildError, "2행.*일반 미디어 파일"):
                    simple.build_simple_timeline(source, media, root / "timeline.csv")
            probe.assert_not_called()


if __name__ == "__main__":
    unittest.main()
