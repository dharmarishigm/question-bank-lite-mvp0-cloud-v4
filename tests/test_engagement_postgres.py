from database import PostgresConnection

class Cursor:
    rowcount = 1
    def fetchone(self):
        return {'id': 42}

class Connection:
    def execute(self, statement, params):
        self.statement = statement
        return Cursor()

def test_keyed_engagement_tables_do_not_request_nonexistent_id():
    raw = Connection()
    db = PostgresConnection(raw)
    for table, column in [('engagement_limits', 'key'), ('flag_trials', 'user_id')]:
        db.execute(f'INSERT INTO {table}({column}) VALUES(?)', ('test',))
        assert 'RETURNING id' not in raw.statement
    assert db.execute('INSERT INTO enquiries(name) VALUES(?)', ('test',)).lastrowid == 42
    assert raw.statement.endswith('RETURNING id')
