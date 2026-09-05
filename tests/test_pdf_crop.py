import io
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, AsyncMock

import pymupdf
from PIL import Image
from fastapi.testclient import TestClient
import app


class PdfCropTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        db = str(root / 'test.db')
        with sqlite3.connect(db) as conn:
            conn.executescript(app.SCHEMA)
        for name, value in [('DB_PATH', db), ('SOURCE_DIR', str(root)), ('UPLOAD_DIR', str(root))]:
            patcher = patch.object(app, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        with pymupdf.open() as doc:
            doc.new_page(width=400, height=600)
            doc.new_page(width=400, height=600).insert_text((100, 200), 'Selected question')
            self.source = app._prepare_pdf_preview(doc.tobytes(), 'crop-test.pdf')

    def test_crop_uses_original_page_and_expected_dimensions(self):
        _, content = app._render_pdf_crop(self.source['id'], app.PdfCropRequest(page=2, bbox=[.25, .25, .75, .75]))
        with Image.open(io.BytesIO(content)) as image:
            self.assertEqual(image.size, (840, 1260))

    def test_invalid_selections_are_rejected(self):
        for box in ([.5, .5, .4, .8], [-.1, 0, 1, 1], [0, 0, .001, .001], [0, 0, float('nan'), 1]):
            with self.assertRaises(app.HTTPException):
                app._render_pdf_crop(self.source['id'], app.PdfCropRequest(page=1, bbox=box))
        with self.assertRaises(app.HTTPException):
            app._render_pdf_crop(self.source['id'], app.PdfCropRequest(page=3, bbox=[0, 0, 1, 1]))

    def test_endpoint_preserves_pdf_provenance_on_local_fallback(self):
        with patch.object(app, 'llm_status', return_value={'available': False}), TestClient(app.app) as client:
            response = client.post(f"/api/sources/{self.source['id']}/digitise-crop", json={'page': 2, 'bbox': [.25, .25, .75, .75]})
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        question = data['questions'][0]
        self.assertEqual(question['source_document_id'], self.source['id'])
        self.assertEqual(question['source_page'], 2)
        self.assertEqual(question['source_bbox'], [.25, .25, .75, .75])
        self.assertEqual(question['source_segments'][0]['page'], 2)
        self.assertEqual(question['verification_status'], 'UNVERIFIED')
        with app.connect() as conn:
            row = conn.execute('SELECT source_document_id FROM extraction_runs WHERE id=?', (data['extraction_run_id'],)).fetchone()
            self.assertEqual(row['source_document_id'], self.source['id'])

    def test_aliased_visual_coordinates_are_transformed_once(self):
        assets = [{'page': 1, 'bbox': [0, 0, 1, 1], 'type': 'diagram'}]
        data = {'questions': [{'statement': 'Question', 'visuals': assets, 'visual_assets': assets}]}
        source = {'id': 'original', 'filename': 'test.pdf', 'sha256': 'hash', 'mime_type': 'application/pdf', 'page_count': 2}
        app._map_crop_evidence(data, source, app.PdfCropRequest(page=2, bbox=[.25, .25, .75, .75]))
        question = data['questions'][0]
        for key in ('visuals', 'visual_assets'):
            self.assertEqual(question[key][0]['bbox'], [.25, .25, .75, .75])
            self.assertEqual(question[key][0]['page'], 2)

    def test_endpoint_accepts_multiple_crops_in_one_request(self):
        question_a = {'statement': 'Question A', 'options': ['A', 'B'], 'answer': 'A'}
        question_b = {'statement': 'Question B', 'options': ['C', 'D'], 'answer': 'C'}
        with patch.object(app, '_parse_source', AsyncMock(side_effect=[
            {'questions': [question_a], 'warnings': [], 'llm': {'provider': 'local', 'model': 'local'}},
            {'questions': [question_b], 'warnings': [], 'llm': {'provider': 'local', 'model': 'local'}},
        ])), TestClient(app.app) as client:
            response = client.post(f"/api/sources/{self.source['id']}/digitise-crop",
                                   json={'selections': [
                                       {'page': 1, 'bbox': [.10, .10, .40, .40]},
                                       {'page': 2, 'bbox': [.25, .25, .75, .75]},
                                   ]})
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(len(data['questions']), 2)
        self.assertEqual(data['questions'][0]['source_page'], 1)
        self.assertEqual(data['questions'][1]['source_page'], 2)

    def test_entire_selection_survives_tighter_ai_region(self):
        extraction = {
            'extraction_run_id': 'test-run',
            'questions': [{'statement': 'Detected question', 'image': '/uploads/tight.png',
                           'source_bbox': [.2, .2, .6, .6],
                           'source_segments': [{'page': 1, 'bbox': [.2, .2, .6, .6], 'image': '/uploads/tight.png'}]}],
        }
        with patch.object(app, '_parse_source', AsyncMock(return_value=extraction)), TestClient(app.app) as client:
            response = client.post(f"/api/sources/{self.source['id']}/digitise-crop",
                                   json={'page': 2, 'bbox': [.25, .25, .75, .75]})
        self.assertEqual(response.status_code, 200, response.text)
        question = response.json()['questions'][0]
        self.assertEqual(question['source_bbox'], [.25, .25, .75, .75])
        self.assertEqual(question['source_segments'][0]['bbox'], question['source_bbox'])
        self.assertTrue(question['image'].startswith('/uploads/selected-'))
        self.assertEqual(question['source_image'], question['image'])
        with Image.open(Path(app.UPLOAD_DIR) / Path(question['image']).name) as image:
            self.assertEqual(image.size, (840, 1260))
