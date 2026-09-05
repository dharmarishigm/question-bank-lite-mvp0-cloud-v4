import os
import unittest
from io import BytesIO
from unittest import mock

from fastapi import UploadFile

from app import parse_pdf_paper
from gcp_documentai import status as documentai_status
from llm_extract import (
    Extraction,
    ExtractedQuestion,
    _generate_structured,
    _merge_local_question_fields,
    gcp_project_id,
    gcp_region,
    llm_status,
    validate_extraction,
)


class LlmExtractionTests(unittest.TestCase):
    def question(self, **changes):
        return ExtractedQuestion(**{'number': 1, 'page': 1, 'statement': 'Find $x^2$.',
            'options': ['1', '2', '3', '4'], 'answer': 'A', 'solution': '', 'uncertainties': [], **changes})

    def test_rejects_missing_questions(self):
        with self.assertRaises(ValueError):
            validate_extraction(Extraction(questions=[]), {'questions': []}, 1)

    def test_local_option_disagreement_is_not_authoritative(self):
        local = {'questions': [{'number': 1, 'page': 1, 'options': ['1', '2', '3', '4']}]}
        validate_extraction(Extraction(questions=[self.question(options=[])]), local, 1)

    def test_rejects_duplicate_questions(self):
        with self.assertRaises(ValueError):
            validate_extraction(Extraction(questions=[self.question(), self.question()]), {'questions': []}, 1)

    def test_accepts_latex_and_printed_answer(self):
        validate_extraction(Extraction(questions=[self.question()]), {'questions': []}, 1)

    def test_merges_missing_options_from_local_extraction(self):
        local = {'questions': [{'number': 1, 'page': 1, 'statement': 'Find x.', 'options': ['1', '2', '3', '4'], 'answer': 'C', 'solution': 'The correct option is C.'}]}
        candidate = ExtractedQuestion(number=1, page=1, statement='Find x.', options=[], answer='', solution='')
        merged = _merge_local_question_fields(local, candidate)
        self.assertEqual(merged.options, ['1', '2', '3', '4'])
        self.assertEqual(merged.answer, 'C')
        self.assertEqual(merged.solution, 'The correct option is C.')

    def test_reads_standard_google_cloud_environment_variables(self):
        with mock.patch.dict('os.environ', {'GOOGLE_CLOUD_PROJECT': 'demo-project', 'GOOGLE_CLOUD_LOCATION': 'us-central1', 'QB_PDF_LLM': 'vertex'}, clear=True):
            self.assertEqual(gcp_project_id(), 'demo-project')
            self.assertEqual(gcp_region(), 'us-central1')
            self.assertTrue(llm_status()['available'])

    def test_ignores_placeholder_gcp_values_from_env(self):
        with mock.patch.dict('os.environ', {
            'GCP_PROJECT_ID': 'your-project-id',
            'GOOGLE_CLOUD_PROJECT': '',
            'GCP_REGION': 'asia-south1',
            'DOCUMENTAI_PROCESSOR_ID': 'your-processor-id',
            'QB_PDF_LLM': 'vertex',
            'QB_VERIFY': 'on',
        }, clear=True):
            self.assertEqual(gcp_project_id(), '')
            self.assertFalse(llm_status()['available'])
            self.assertFalse(documentai_status()['available'])

    def test_accepts_structured_json_even_when_finish_reason_is_not_stop(self):
        response = mock.Mock()
        response.candidates = [mock.Mock(finish_reason='MAX_TOKENS')]
        response.text = '{"questions": [{"number": 1, "page": 1, "statement": "Find x.", "options": ["1", "2"], "answer": "A", "solution": ""}]}'
        response.usage_metadata = None
        client = mock.Mock()
        client.models.generate_content.return_value = response

        out = _generate_structured(client, model='gemini-test', parts=['x'], schema=Extraction, system_instruction='prompt', max_tokens=128)

        self.assertIs(out, response)


class PdfUploadFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_auto_mode_falls_back_to_local_extraction_on_vertex_error(self):
        local = {'questions': [{'number': 1, 'page': 1, 'statement': 'Find x.', 'options': ['1', '2'], 'image': '/uploads/a.png'}], 'warnings': []}
        file = UploadFile(filename='sample.pdf', file=BytesIO(b'%PDF-1.4\n%%EOF'))

        async def fake_run_in_threadpool(func, *args, **kwargs):
            if func.__name__ == 'parse_pdf':
                return local
            if func.__name__ == 'extract_pdf':
                raise RuntimeError('ClientError')
            raise AssertionError(f'unexpected function: {func!r}')

        with mock.patch('app.llm_status', return_value={'available': True}), \
             mock.patch('app.run_in_threadpool', side_effect=fake_run_in_threadpool):
            result = await parse_pdf_paper(file, mode='auto')

        self.assertEqual(result['questions'][0]['statement'], 'Find x.')
        self.assertIn('GCP extraction failed', result['warnings'][0])

class ChunkingTests(unittest.TestCase):
    def test_pdf_is_split_with_one_page_overlap(self):
        import pymupdf
        from llm_extract import _gemini_source_chunks
        doc = pymupdf.open()
        for i in range(17):
            page = doc.new_page()
            page.insert_text((72, 72), f'Q page {i+1}')
        data = doc.tobytes()
        doc.close()
        old = os.environ.get('QB_GEMINI_CHUNK_PAGES')
        old_overlap = os.environ.get('QB_GEMINI_CHUNK_OVERLAP')
        os.environ['QB_GEMINI_CHUNK_PAGES'] = '8'
        os.environ['QB_GEMINI_CHUNK_OVERLAP'] = '1'
        try:
            chunks = list(_gemini_source_chunks(data, 'application/pdf', 17))
        finally:
            if old is None: os.environ.pop('QB_GEMINI_CHUNK_PAGES', None)
            else: os.environ['QB_GEMINI_CHUNK_PAGES'] = old
            if old_overlap is None: os.environ.pop('QB_GEMINI_CHUNK_OVERLAP', None)
            else: os.environ['QB_GEMINI_CHUNK_OVERLAP'] = old_overlap
        self.assertEqual([(c[2], c[3]) for c in chunks], [(0, 8), (7, 8), (14, 3)])

    def test_overlap_duplicate_prefers_more_complete_question(self):
        from llm_extract import ExtractedQuestion, SourceRegion, _dedupe_extractions
        a = ExtractedQuestion(number=10, page=8, statement='short', source_regions=[SourceRegion(page=8,bbox=[0,0,1,1])])
        b = ExtractedQuestion(number=10, page=8, statement='longer complete question', options=['1','2','3','4'], source_regions=[SourceRegion(page=8,bbox=[0,0,1,1]), SourceRegion(page=9,bbox=[0,0,1,1])])
        out = _dedupe_extractions([a,b])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].statement, 'longer complete question')
