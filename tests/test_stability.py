"""Regression tests using small synthetic, non-personal media."""
from __future__ import annotations
import csv
import io
import json
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
import zlib
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run as app
import colab_support as colab


def png_bytes(rgb=(60, 90, 120)):
    def chunk(name, data):
        return struct.pack('!I', len(data)) + name + data + struct.pack('!I', zlib.crc32(name + data))
    data = (b'\x00' + bytes(rgb) * 32) * 24
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('!2I5B', 32, 24, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(data)) + chunk(b'IEND', b'')


def csv_bytes(rows, headers=app.HEADERS):
    stream = io.StringIO(newline='')
    writer = csv.writer(stream)
    writer.writerow(headers)
    writer.writerows(rows)
    return stream.getvalue().encode('utf-8-sig')


class ProjectTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / 'my-video'
        (self.project / 'Media').mkdir(parents=True)
        self.csv = self.project / 'timeline.csv'

    def plan(self, rows, headers=app.HEADERS):
        self.csv.write_bytes(csv_bytes(rows, headers))
        return self.csv

    def photo(self, name='photo.png', duration='0.1', title='테스트'):
        (self.project / 'Media' / name).write_bytes(png_bytes())
        return self.plan([[name, '', '', duration, title, '']])


class CSVTests(ProjectTest):
    def test_blank_filename_is_error(self):
        self.plan([['', '', '', '3', '자막만 있는 장면', '']])
        with self.assertRaisesRegex(app.UserError, '2행.*파일명'):
            app.read_timeline(self.csv)

    def test_blank_rows_ignored_actual_line_preserved(self):
        self.plan([[''] * 6, ['photo.png', '', '', '3', '', '']])
        self.assertEqual(app.read_timeline(self.csv)[0]['__line__'], '3')

    def test_physical_empty_line_number(self):
        self.csv.write_text('파일\n\nphoto.png\n', encoding='utf-8')
        self.assertEqual(app.read_timeline(self.csv)[0]['__line__'], '3')

    def test_duplicate_headers(self):
        self.plan([['photo.png', 'x']], ['파일', '파일'])
        with self.assertRaisesRegex(app.UserError, '중복'):
            app.read_timeline(self.csv)

    def test_unknown_headers(self):
        self.plan([['photo.png', 'x']], ['파일', '오타'])
        with self.assertRaisesRegex(app.UserError, '열 이름'):
            app.read_timeline(self.csv)

    def test_extra_fields(self):
        self.plan([['a.png'] + [''] * 6])
        with self.assertRaisesRegex(app.UserError, '열 수'):
            app.read_timeline(self.csv)

    def test_missing_fields(self):
        self.plan([['a.png']])
        with self.assertRaisesRegex(app.UserError, '열이 누락'):
            app.read_timeline(self.csv)

    def test_quoted_comma_newline(self):
        self.plan([['a.png', '', '', '3', '안녕, 세계\n둘째 줄', '']])
        self.assertEqual(app.read_timeline(self.csv)[0]['화면 자막'], '안녕, 세계\n둘째 줄')

    def test_non_utf8(self):
        self.csv.write_bytes('파일\na.png'.encode('cp949'))
        with self.assertRaisesRegex(app.UserError, 'UTF-8'):
            app.read_timeline(self.csv)

    def test_empty_plan(self):
        self.plan([[''] * 6])
        with self.assertRaisesRegex(app.UserError, '장면'):
            app.read_timeline(self.csv)

    def test_path_traversal(self):
        for name in ('../a.png', '/tmp/a.png', 'Media/a.png', 'Media\\a.png', 'C:a.png'):
            with self.subTest(name=name), self.assertRaises(app.UserError):
                app.filename(name)

    def test_valid_time_formats(self):
        for text, expected in [('12.5', Fraction(25, 2)), ('01:02.5', Fraction(125, 2)), ('01:02:03.250', Fraction(14893, 4))]:
            with self.subTest(text=text):
                self.assertEqual(app.parse_seconds(text, 'time'), expected)

    def test_invalid_times(self):
        for value in ('NaN', 'Infinity', '-1', '00:60', '00:99:01', '1.5:20', '1:2:3:4', '1초'):
            with self.subTest(value=value), self.assertRaises(app.UserError):
                app.parse_seconds(value, 'time')

    def test_missing_media(self):
        self.plan([['missing.png', '', '', '3', '', '']])
        with self.assertRaisesRegex(app.UserError, '파일이 없습니다'):
            app.load_clips(self.project, self.csv)

    def test_photo_rejects_video_time(self):
        self.photo()
        self.plan([['photo.png', '0', '1', '', '', '']])
        with self.assertRaisesRegex(app.UserError, '사진에는'):
            app.load_clips(self.project, self.csv)

    def test_sound_typo_not_silently_unmuted(self):
        self.photo()
        self.plan([['photo.png', '', '', '3', '', '오타']])
        with self.assertRaisesRegex(app.UserError, '소리는'):
            app.load_clips(self.project, self.csv)

    def test_unicode_normalization(self):
        name = unicodedata.normalize('NFD', '사진.png')
        self.photo(name)
        self.plan([['사진.png', '', '', '3', '', '']])
        self.assertEqual(app.load_clips(self.project, self.csv)[0].path.name, name)

    def test_csv_xlsx_conflict(self):
        self.photo()
        (self.project / 'timeline.xlsx').write_bytes(b'placeholder')
        with self.assertRaisesRegex(app.UserError, '하나만'):
            app.prepare_timeline(self.project)

    def test_shipped_xlsx_matches_csv(self):
        output = self.project / 'converted.csv'
        app.convert_xlsx(ROOT / 'templates/timeline.xlsx', output)
        def values(path):
            return [{k: v for k, v in row.items() if k != '__line__'} for row in app.read_timeline(path)]
        self.assertEqual(values(output), values(ROOT / 'templates/timeline.csv'))


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
class BuildTests(ProjectTest):
    def setUp(self):
        super().setUp()
        sizes = patch.dict(app.LAYOUTS, {'portrait': (96, 160), 'landscape': (160, 96)})
        sizes.start()
        self.addCleanup(sizes.stop)
        self.photo()

    def test_same_photo_different_duration(self):
        self.plan([['photo.png', '', '', '0.5', '', ''], ['photo.png', '', '', '0.1', '', '']])
        app.build_project(self.project)
        files = list((self.project / 'output/media').glob('*.mp4'))
        self.assertEqual(len(files), 2)
        self.assertEqual(sorted(app.probe(p)[0] for p in files), [Fraction(1, 10), Fraction(1, 2)])

    def test_different_extensions_do_not_collide(self):
        (self.project / 'Media/photo.jpg').write_bytes(png_bytes((120, 20, 20)))
        self.plan([['photo.png', '', '', '0.1', '', ''], ['photo.jpg', '', '', '0.1', '', '']])
        app.build_project(self.project)
        self.assertEqual(len(list((self.project / 'output/media').glob('*.mp4'))), 2)

    def test_identical_photo_spec_reused(self):
        self.plan([['photo.png', '', '', '0.1', '', '']] * 2)
        app.build_project(self.project)
        self.assertEqual(len(list((self.project / 'output/media').glob('*.mp4'))), 1)

    def test_cache_key_covers_content_and_fit(self):
        clip = app.load_clips(self.project, self.csv)[0]
        first = app.image_cache_key(clip, 96, 160, 'fit')
        self.assertNotEqual(first, app.image_cache_key(clip, 96, 160, 'fill'))
        clip.path.write_bytes(png_bytes((1, 2, 3)))
        self.assertNotEqual(first, app.image_cache_key(clip, 96, 160, 'fit'))

    def test_both_xml_titles_timing_and_paths(self):
        outputs = app.build_project(self.project, 'both')
        self.assertEqual({p.name for p in outputs}, {'portrait.fcpxml', 'landscape.fcpxml'})
        for xml in outputs:
            root = ET.parse(xml).getroot()
            self.assertEqual([c.tag for c in root.find('.//title')], ['adjust-transform', 'text', 'text-style-def'])
            self.assertEqual(root.find('.//sequence').get('duration'), '1/10s')
        self.assertEqual(app.verified_result(self.project)['layout'], 'both')

    def test_no_title_when_blank(self):
        self.photo(title='')
        xml = app.build_project(self.project)[0]
        self.assertIsNone(ET.parse(xml).getroot().find('.//title'))

    def test_failure_keeps_old_xml_but_blocks_download(self):
        xml = app.build_project(self.project)[0]
        original = xml.read_bytes()
        self.plan([['missing.png', '', '', '3', '', '']])
        with self.assertRaises(app.UserError):
            app.build_project(self.project)
        self.assertEqual(xml.read_bytes(), original)
        with self.assertRaises(app.UserError):
            colab.make_result_archive(self.project, self.project.parent / 'result.zip')

    def test_failed_second_orientation_is_transactional(self):
        old = app.build_project(self.project)[0]
        original = old.read_bytes()
        build = app.build
        def fail_second(project, layout, fit, timeline, output=None):
            if layout == 'landscape':
                raise app.UserError('injected failure')
            return build(project, layout, fit, timeline, output)
        with patch.object(app, 'build', side_effect=fail_second):
            with self.assertRaisesRegex(app.UserError, 'injected'):
                app.build_project(self.project, 'both')
        self.assertEqual(old.read_bytes(), original)
        self.assertFalse((self.project / 'output/landscape.fcpxml').exists())
        self.assertFalse(list(self.project.glob('.fcpxml-build-*')))

    def test_layout_change_does_not_package_old_orientation(self):
        app.build_project(self.project, 'both')
        app.build_project(self.project, 'portrait')
        self.assertFalse((self.project / 'output/landscape.fcpxml').exists())
        self.assertTrue(list(self.project.glob('.previous-output-*')))

    def test_modified_input_blocks_archive(self):
        app.build_project(self.project)
        self.csv.write_text('파일\nother.png\n', encoding='utf-8')
        with self.assertRaisesRegex(app.UserError, '변경'):
            colab.make_result_archive(self.project, self.project.parent / 'result.zip')

    def test_modified_xml_blocks_archive(self):
        xml = app.build_project(self.project)[0]
        xml.write_text('modified', encoding='utf-8')
        with self.assertRaises(app.UserError):
            app.verified_result(self.project)

    def test_archive_allowlist_and_relocation(self):
        (self.project / 'Media/unused.mp4').write_bytes(b'unused')
        app.build_project(self.project)
        archive = colab.make_result_archive(self.project, self.project.parent / 'result.zip')
        with zipfile.ZipFile(archive) as z:
            self.assertIn('Media/photo.png', z.namelist())
            self.assertIn('output/portrait.fcpxml', z.namelist())
            self.assertNotIn('Media/unused.mp4', z.namelist())
            self.assertFalse(any(n.startswith('.') for n in z.namelist()))
            destination = self.project.parent / 'moved result'
            z.extractall(destination)
        app.validate_xml(destination / 'output/portrait.fcpxml', 96, 160)

    def test_missing_cache_blocks_archive(self):
        app.build_project(self.project)
        next((self.project / 'output/media').glob('*.mp4')).unlink()
        with self.assertRaises(app.UserError):
            app.verified_result(self.project)

    def test_build_lock(self):
        (self.project / '.fcpxml.lock').write_text('busy')
        with self.assertRaisesRegex(app.UserError, '다른 변환'):
            app.build_project(self.project)

    def test_actual_ffmpeg_error_not_success(self):
        (self.project / 'Media/photo.png').write_bytes(b'invalid')
        with self.assertRaises(app.UserError):
            app.build_project(self.project)
        self.assertFalse((self.project / 'output').exists())
        with self.assertRaises(app.UserError):
            app.verified_result(self.project)

    def test_video_bounds_mute_and_escaping(self):
        video = self.project / 'Media/한글 & scene.mp4'
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=size=64x48:rate=30:duration=1', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=1', '-c:v', 'libx264', '-threads', '1', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', str(video)], check=True)
        self.plan([[video.name, '0.2', '0.8', '', 'A & B < C', '끄기']])
        xml = app.build_project(self.project)[0]
        root = ET.parse(xml).getroot()
        self.assertEqual(root.find('.//asset-clip').get('srcEnable'), 'video')
        self.assertEqual(root.find('.//title/text/text-style').text, 'A & B < C')
        self.plan([[video.name, '0', '2', '', '', '']])
        with self.assertRaisesRegex(app.UserError, '원본 길이'):
            app.build_project(self.project)

    def test_cli_invalid_input_friendly_exit(self):
        self.plan([['', '', '', '1', 'text', '']])
        result = subprocess.run([sys.executable, str(ROOT / 'run.py'), str(self.project)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn('파일명', result.stderr)
        self.assertNotIn('Traceback', result.stderr)


class UploadTests(ProjectTest):
    def setUp(self):
        super().setUp()
        self.project = colab.new_session(Path(self.temp.name) / 'sessions')
        self.plan_data = csv_bytes([['photo.png', '', '', '0.1', 'text', '']])

    def upload_all(self):
        colab.save_plan(self.project, {'my plan.csv': self.plan_data})
        colab.save_media(self.project, {'photo.png': png_bytes()})

    def test_new_sessions_are_distinct(self):
        second = colab.new_session(Path(self.temp.name) / 'sessions')
        self.assertNotEqual(self.project, second)
        self.assertFalse((second / 'timeline.csv').exists())

    def test_no_fallback_to_example_plan(self):
        (self.project / 'timeline.csv').write_bytes(self.plan_data)
        with self.assertRaises(app.UserError):
            colab.require_uploads(self.project)

    def test_upload_completion_receipts(self):
        colab.save_plan(self.project, {'timeline.csv': self.plan_data})
        with self.assertRaisesRegex(app.UserError, '3번'):
            colab.require_uploads(self.project)
        colab.save_media(self.project, {'photo.png': png_bytes()})
        colab.require_uploads(self.project)

    def test_cancel_plan_invalidates_previous_uploads(self):
        self.upload_all()
        colab.begin_upload(self.project, 'plan')
        with self.assertRaises(app.UserError):
            colab.save_plan(self.project, {})
        with self.assertRaises(app.UserError):
            colab.require_uploads(self.project)

    def test_cancel_media_invalidates_previous_uploads(self):
        self.upload_all()
        with self.assertRaises(app.UserError):
            colab.save_media(self.project, {})
        with self.assertRaises(app.UserError):
            colab.require_uploads(self.project)

    def test_missing_media_lists_filename(self):
        colab.save_plan(self.project, {'timeline.csv': self.plan_data})
        with self.assertRaisesRegex(app.UserError, 'photo.png'):
            colab.save_media(self.project, {'other.png': png_bytes()})

    def test_plan_change_requires_media_again(self):
        self.upload_all()
        colab.save_plan(self.project, {'again.csv': self.plan_data})
        with self.assertRaises(app.UserError):
            colab.require_uploads(self.project)

    def test_upload_type_and_count_validation(self):
        for upload in ({'a.csv': self.plan_data, 'b.csv': self.plan_data}, {'a.numbers': b'x'}, {'a.csv': b''}):
            with self.subTest(upload=list(upload)), self.assertRaises(app.UserError):
                colab.save_plan(self.project, upload)

    def test_unreferenced_media_not_saved(self):
        colab.save_plan(self.project, {'a.csv': self.plan_data})
        extra = colab.save_media(self.project, {'photo.png': png_bytes(), 'other.png': png_bytes()})
        self.assertEqual(extra, ['other.png'])
        self.assertFalse((self.project / 'Media/other.png').exists())

    def test_changed_upload_bytes_detected(self):
        self.upload_all()
        (self.project / 'Media/photo.png').write_bytes(png_bytes((1, 2, 3)))
        with self.assertRaisesRegex(app.UserError, '변경'):
            colab.require_uploads(self.project)

    def test_duplicate_normalized_names(self):
        nfd = unicodedata.normalize('NFD', '사진.png')
        with self.assertRaisesRegex(app.UserError, '중복'):
            colab.normalized_upload({'사진.png': b'a', nfd: b'b'})


if __name__ == '__main__':
    unittest.main()
