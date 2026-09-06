from database import _qmark, translate_ddl, translate_sql


def test_qmark_translation_preserves_literals_and_escaped_quotes():
    assert _qmark("SELECT '?', 'it''s ?' WHERE id=?") == "SELECT '?', 'it''s ?' WHERE id=%s"


def test_sqlite_insert_and_ddl_are_portable():
    assert translate_sql("INSERT OR IGNORE INTO items(id) VALUES(?)") == (
        "INSERT INTO items(id) VALUES(%s) ON CONFLICT DO NOTHING"
    )
    assert "BIGSERIAL PRIMARY KEY" in translate_ddl("id INTEGER PRIMARY KEY AUTOINCREMENT")
