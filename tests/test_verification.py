import unittest

import app
from verification import confidence_score, deterministic_issues, formulas_for_question, status_from


class VerificationTests(unittest.TestCase):
    def test_bbox_overlap_selects_math_evidence(self):
        docai = {'formulas': [
            {'page': 1, 'latex': r'x^2=4', 'bbox': [0.1, 0.1, 0.4, 0.2]},
            {'page': 1, 'latex': r'y=7', 'bbox': [0.7, 0.7, 0.9, 0.8]},
        ]}
        got = formulas_for_question(docai, 1, [0.05, 0.05, 0.5, 0.3])
        self.assertEqual([x['latex'] for x in got], [r'x^2=4'])

    def test_critical_issue_forces_failed(self):
        issues = [{'severity': 'critical'}]
        score = confidence_score(.99, issues, [])
        self.assertEqual(status_from(score, issues), 'FAILED')

    def test_matching_formula_does_not_raise_issue(self):
        issues = deterministic_issues('Find $x^2=4$.', [{'latex': r'x^2=4'}])
        self.assertEqual(issues, [])


class SourceFormatTests(unittest.TestCase):
    def test_extracts_plain_text_from_txt(self):
        text = "Q1. What is 2+2?\nA. 3\nB. 4\nC. 5\n"
        self.assertIn("2+2", app._text_source_preview("sample.txt", text.encode()))

    def test_extracts_notebook_text_from_ipynb(self):
        payload = '{"cells": [{"source": ["Q1. What is 2+2?\\n", "A. 3\\n", "B. 4\\n"]}]}'
        self.assertIn("2+2", app._text_source_preview("sample.ipynb", payload.encode()))

    def test_parses_questions_and_options_from_text_sources(self):
        text = "Q1. What is 2+2?\nA. 3\nB. 4\nC. 5\nAnswer: B\n\nQ2. Which is prime?\nA. 9\nB. 11\nC. 15\nAns: B"
        parsed = app._text_local("sample.txt", text.encode())
        self.assertEqual(parsed["questions"][0]["statement"], "What is 2+2?")
        self.assertEqual(parsed["questions"][0]["options"], ["3", "4", "5"])
        self.assertEqual(parsed["questions"][0]["answer"], "B")
        self.assertEqual(parsed["questions"][1]["answer"], "B")


if __name__ == '__main__':
    unittest.main()
