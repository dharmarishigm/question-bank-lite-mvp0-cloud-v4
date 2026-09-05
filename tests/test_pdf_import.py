import tempfile
import unittest
from pathlib import Path
import pymupdf
from pdf_import import parse_pdf, _reading_order, _split_options, _clean


class PdfImportTests(unittest.TestCase):
    def test_exam_shift_is_not_an_option(self):
        statement, options = _split_options('JEE Main (22 January Shift 1)\nFind n.\n(1) -40 (2) -41 (3) -80 (4) -81')
        self.assertIn('Find n.', statement)
        self.assertEqual(options, ['-40', '-41', '-80', '-81'])

    def test_statement_labels_are_not_answer_options(self):
        statement, options = _split_options('Consider (I) increasing (II) decreasing. Then (1) neither (2) I (3) both (4) II')
        self.assertIn('(II) decreasing', statement)
        self.assertEqual(options, ['neither', 'I', 'both', 'II'])

    def test_minus_sign_survives_line_wrap(self):
        self.assertEqual(_clean('x -\n2'), 'x - 2')

    def test_solutions_are_not_imported_as_questions(self):
        doc = pymupdf.open()
        doc.new_page().insert_text((40, 100), 'Q1. Find the maximum value of the given function.\n(1) 1 (2) 2 (3) 3 (4) 4')
        doc.new_page().insert_text((40, 100), 'ANSWERS AND SOLUTIONS\n1. (4) The answer is four.')
        with tempfile.TemporaryDirectory() as directory:
            result = parse_pdf(doc.tobytes(), directory, 'text')
        self.assertEqual([q['number'] for q in result['questions']], [1])

    def test_ocr_columns_keep_question_order_on_short_pages(self):
        page = pymupdf.open().new_page()
        lines = [
            ('Q1. Find x.', (10, 100, 200, 120)),
            ('(1) 2', (10, 120, 100, 140)),
            ('(2) 3', (10, 140, 100, 160)),
            ('Q2. Find y.', (610, 100, 800, 120)),
            ('(1) 4', (610, 120, 700, 140)),
            ('(2) 5', (610, 140, 700, 160)),
        ]
        ordered = _reading_order(lines, page)
        self.assertLess(ordered.index(('Q1. Find x.', (10, 100, 200, 120))), ordered.index(('Q2. Find y.', (610, 100, 800, 120))))

    def test_ocr_rows_keep_interleaved_questions_in_sequence(self):
        page = pymupdf.open().new_page()
        lines = [
            ('Q1. Find x.', (10, 100, 200, 120)),
            ('Q2. Find y.', (610, 130, 800, 150)),
            ('Q3. Find z.', (10, 160, 200, 180)),
        ]
        ordered = _reading_order(lines, page)
        self.assertLess(ordered.index(('Q1. Find x.', (10, 100, 200, 120))), ordered.index(('Q2. Find y.', (610, 130, 800, 150))))
        self.assertLess(ordered.index(('Q2. Find y.', (610, 130, 800, 150))), ordered.index(('Q3. Find z.', (10, 160, 200, 180))))

    def test_cross_page_question_keeps_all_source_segments(self):
        doc = pymupdf.open()
        p1 = doc.new_page()
        p1.insert_text((40, 100), 'Q1. Consider the following long physical situation where a particle moves under a force and continues on the next page.')
        p2 = doc.new_page()
        p2.insert_text((40, 100), 'The remaining condition is acceleration equals two metre per second squared. (1) 1 (2) 2 (3) 3 (4) 4')
        with tempfile.TemporaryDirectory() as directory:
            result = parse_pdf(doc.tobytes(), directory, 'text')
        self.assertEqual(len(result['questions']), 1)
        q = result['questions'][0]
        self.assertEqual([s['page'] for s in q['source_segments']], [1, 2])
        self.assertTrue(all(s['bbox'] for s in q['source_segments']))


if __name__ == '__main__':
    unittest.main()
