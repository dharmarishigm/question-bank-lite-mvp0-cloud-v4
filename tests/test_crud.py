"""Persistence regression for the editor's delete action."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app


class QuestionDeletionTests(unittest.TestCase):
    def test_edited_question_and_versions_can_be_deleted(self):
        with tempfile.TemporaryDirectory() as directory:
            db = str(Path(directory) / 'questions.db')
            with sqlite3.connect(db) as conn:
                conn.executescript(app.SCHEMA)
            with patch.object(app, 'DB_PATH', db):
                question = app.create_question(app.Question(statement='Original'))
                app.update_question(question['id'], app.Question(statement='Edited'))
                self.assertEqual(len(app.get_versions(question['id'])), 1)
                self.assertEqual(app.delete_question(question['id']), {'deleted': question['id']})
                self.assertEqual(app.get_versions(question['id']), [])
                with self.assertRaises(app.HTTPException) as error:
                    app.get_question(question['id'])
                self.assertEqual(error.exception.status_code, 404)
