import io
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pymupdf
from PIL import Image
import app


class PdfPreviewTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        db = str(root / 'test.db')
        with sqlite3.connect(db) as conn:
            conn.executescript(app.SCHEMA)
        for name, value in [('DB_PATH', db), ('SOURCE_DIR', str(root))]:
            patcher = patch.object(app, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        with pymupdf.open() as doc:
            for number in range(3):
                doc.new_page().insert_text((72, 72), f'Preview page {number + 1}')
            self.content = doc.tobytes()

    def test_all_pages_can_be_rendered_without_extraction(self):
        with patch.object(app, 'extract_pdf', side_effect=AssertionError('No AI expected')):
            result = app._prepare_pdf_preview(self.content, 'paper.pdf')
            self.assertEqual(result['page_count'], 3)
            self.assertEqual([p['number'] for p in result['pages']], [1, 2, 3])
            for number in (1, 3):
                response = app.preview_pdf_page(result['id'], number)
                self.assertEqual(response.media_type, 'image/png')
                with Image.open(io.BytesIO(response.body)) as image:
                    self.assertGreater(image.height, 100)
            self.assertEqual(app.list_questions()['total'], 0)

    def test_invalid_pdf_and_missing_page_are_rejected(self):
        with self.assertRaises(app.HTTPException):
            app._prepare_pdf_preview(b'not a PDF', 'bad.pdf')
        result = app._prepare_pdf_preview(self.content, 'paper.pdf')
        for number in (0, 4):
            with self.assertRaises(app.HTTPException) as error:
                app.preview_pdf_page(result['id'], number)
            self.assertEqual(error.exception.status_code, 404)
        with self.assertRaises(app.HTTPException):
            app.preview_pdf_page('missing', 1)

    def test_repeated_upload_reuses_source(self):
        first = app._prepare_pdf_preview(self.content, 'paper.pdf')
        second = app._prepare_pdf_preview(self.content, 'renamed.pdf')
        self.assertEqual(first['id'], second['id'])
        self.assertEqual(second['filename'], 'renamed.pdf')
