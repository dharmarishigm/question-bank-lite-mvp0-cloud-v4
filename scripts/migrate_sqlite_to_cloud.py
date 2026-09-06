"""One-time, restartable migration from local SQLite and files to Cloud SQL/GCS."""
from __future__ import annotations
import argparse,mimetypes,os,sqlite3
from pathlib import Path
import psycopg
from psycopg import sql
from google.cloud import storage

TABLE_ORDER=['questions','source_documents','extraction_runs','question_versions','question_explanations','exam_registrations','ai_generation_runs','users','app_sessions','oauth_states','exams','exam_questions','pending_exam_registrations','exam_registration_links','exam_enrollments','exam_versions','exam_proctor_codes','exam_sessions','exam_answers','exam_audit_log','proctor_code_failures']

def migrate_rows(source,destination):
    source.row_factory=sqlite3.Row
    for table in TABLE_ORDER:
        if not source.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone():continue
        rows=source.execute(f'SELECT * FROM {table}').fetchall()
        for row in rows:
            columns=list(row.keys());values=[row[name] for name in columns]
            statement=sql.SQL('INSERT INTO {} ({}) VALUES ({}) ON CONFLICT DO NOTHING').format(sql.Identifier(table),sql.SQL(',').join(map(sql.Identifier,columns)),sql.SQL(',').join(sql.Placeholder()*len(columns)))
            destination.execute(statement,values)
        print(f'{table}: {len(rows)} rows')

def migrate_files(root,bucket_name):
    client=storage.Client();bucket=client.bucket(bucket_name);count=0
    for path in root.rglob('*'):
        if not path.is_file() or path.suffix.lower() in {'.db', '.sqlite', '.sqlite3'}:continue
        name=path.relative_to(root).as_posix();blob=bucket.blob(name)
        if not blob.exists(client):blob.upload_from_filename(path,content_type=mimetypes.guess_type(path.name)[0]);count+=1
    print(f'objects uploaded: {count}')

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--sqlite',required=True);parser.add_argument('--data-dir',required=True);parser.add_argument('--database-url',default=os.getenv('DATABASE_URL'));parser.add_argument('--bucket',default=os.getenv('GCS_DATA_BUCKET'));args=parser.parse_args()
    if not args.database_url or not args.bucket:parser.error('DATABASE_URL and GCS_DATA_BUCKET are required')
    url=args.database_url.replace('postgresql+psycopg://','postgresql://')
    with sqlite3.connect(args.sqlite) as source,psycopg.connect(url) as destination:
        migrate_rows(source,destination);destination.commit()
        serial_tables = destination.execute("""SELECT table_name FROM information_schema.columns
            WHERE table_schema='public' AND column_name='id' AND column_default LIKE 'nextval(%'""").fetchall()
        for (table,) in serial_tables:
            destination.execute(
                sql.SQL("SELECT setval(pg_get_serial_sequence(%s,'id'),COALESCE(MAX(id),1),MAX(id) IS NOT NULL) FROM {}").format(sql.Identifier(table)),
                (table,),
            )
        destination.commit()
    migrate_files(Path(args.data_dir),args.bucket)
if __name__=='__main__':main()
