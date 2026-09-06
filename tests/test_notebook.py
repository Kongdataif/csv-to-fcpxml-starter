"""Execute notebook cells with mocked browser upload/download, not real Colab UI."""
import ast
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from test_stability import ROOT, csv_bytes, png_bytes
import colab_support as support
import run as app


class NotebookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        notebook = json.loads((ROOT / 'colab.ipynb').read_text(encoding='utf-8'))
        cls.code = [''.join(c['source']) for c in notebook['cells'] if c['cell_type'] == 'code']

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = support.new_session(Path(self.temp.name))
        self.downloaded = []
        self.uploads = []
        files = types.SimpleNamespace(upload=lambda: self.uploads.pop(0), download=self.downloaded.append)
        google = types.ModuleType('google')
        colab = types.ModuleType('google.colab')
        colab.files = files
        google.colab = colab
        modules = patch.dict(sys.modules, {'google': google, 'google.colab': colab})
        modules.start()
        self.addCleanup(modules.stop)
        self.scope = dict(Path=Path, os=os, tempfile=tempfile, sys=sys, subprocess=subprocess, repo=ROOT, project=self.project, verified_result=app.verified_result)
        for name in ('begin_upload', 'save_plan', 'save_media', 'require_plan', 'require_uploads', 'make_result_archive'):
            self.scope[name] = getattr(support, name)

    def execute(self, index):
        with contextlib.redirect_stdout(io.StringIO()):
            exec(compile(self.code[index], f'colab-cell-{index + 1}', 'exec'), self.scope)

    def prepare_uploads(self, duration='0.1'):
        self.uploads = [{'timeline.csv': csv_bytes([['photo.png', '', '', duration, 'text', '']])}, {'photo.png': png_bytes()}]
        self.execute(1)
        self.execute(2)

    def test_all_five_code_cells_compile(self):
        self.assertEqual(len(self.code), 5)
        for source in self.code:
            ast.parse(source)

    def test_core_pin_is_immutable_commit(self):
        assigns = [n for n in ast.parse(self.code[0]).body if isinstance(n, ast.Assign)]
        pin = next(ast.literal_eval(n.value) for n in assigns if any(isinstance(t, ast.Name) and t.id == 'CORE_REV' for t in n.targets))
        self.assertRegex(pin, r'^[0-9a-f]{40}$')
        self.assertNotEqual(pin, '0' * 40)
        self.assertNotIn('pull', self.code[0])

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
    def test_cells_upload_convert_download(self):
        self.prepare_uploads()
        self.execute(3)
        self.execute(4)
        self.assertEqual(len(self.downloaded), 1)
        self.assertTrue(Path(self.downloaded[0]).is_file())

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
    def test_failed_conversion_never_calls_download(self):
        self.prepare_uploads()
        self.execute(3)
        self.prepare_uploads('-1')
        with self.assertRaises(subprocess.CalledProcessError):
            self.execute(3)
        with self.assertRaises(app.UserError):
            self.execute(4)
        self.assertEqual(self.downloaded, [])

    def test_cancelled_upload_never_calls_download(self):
        self.uploads = [{}]
        with self.assertRaises(app.UserError):
            self.execute(1)
        with self.assertRaises(app.UserError):
            self.execute(4)
        self.assertEqual(self.downloaded, [])


if __name__ == '__main__':
    unittest.main()
