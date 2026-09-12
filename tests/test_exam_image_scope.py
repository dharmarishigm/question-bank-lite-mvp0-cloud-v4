import json
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from security_boundary import authorize_asset


class SnapshotDB:
    def __init__(self, snapshot):
        self.snapshot = snapshot

    def execute(self, sql, params):
        assert params[0] == 11
        return self

    def fetchall(self):
        return [{'question_set_json': json.dumps(self.snapshot)}]

    def close(self):
        pass


@pytest.mark.parametrize('path', ['/uploads/figure.png', '/uploads/generated-visual-0123456789abcdef-question.svg', '/uploads/generated-visual-0123456789abcdef-a.svg'])
@pytest.mark.parametrize('field', ['statement', 'options'])
def test_exam_markdown_images_allowed(path, field):
    value = f'![Figure]({path})'
    snapshot = [{field: [value] if field == 'options' else value}]
    with patch('platform_api.db', return_value=SnapshotDB(snapshot)):
        authorize_asset(path, {'id': 11, 'role': 'STUDENT'})


@pytest.mark.parametrize('snapshot', [[], [{'solution': '![Answer](/uploads/figure.png)'}], [{'statement': '![Other](/uploads/figure.png-extra)'}], [{'statement': '/uploads/figure.png is mentioned but not an image'}]])
def test_unscoped_images_remain_private(snapshot):
    with patch('platform_api.db', return_value=SnapshotDB(snapshot)):
        with pytest.raises(HTTPException) as error:
            authorize_asset('/uploads/figure.png', {'id': 11, 'role': 'STUDENT'})
        assert error.value.status_code == 403
