"""PostgreSQL transactions; a DB lock serializes domain transitions across processes."""
from contextlib import contextmanager
from uuid import uuid4
from datetime import datetime, timezone
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from .catalog import digest

SCHEMA = '''
CREATE TABLE IF NOT EXISTS ep_users (
 id text PRIMARY KEY, username text UNIQUE NOT NULL, display_name text NOT NULL,
 password_hash text NOT NULL, admin boolean NOT NULL DEFAULT false, enabled boolean NOT NULL DEFAULT true);
CREATE TABLE IF NOT EXISTS ep_members (
 project_id text NOT NULL, user_id text NOT NULL REFERENCES ep_users(id), roles jsonb NOT NULL,
 PRIMARY KEY(project_id,user_id));
CREATE TABLE IF NOT EXISTS ep_sessions (
 token_hash text PRIMARY KEY, user_id text NOT NULL REFERENCES ep_users(id), csrf text NOT NULL,
 expires timestamptz NOT NULL);
CREATE TABLE IF NOT EXISTS ep_records (
 id text PRIMARY KEY, kind text NOT NULL, project_id text NOT NULL, body jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now());
CREATE INDEX IF NOT EXISTS ep_records_project ON ep_records(project_id,kind);
CREATE TABLE IF NOT EXISTS ep_events (
 seq bigserial PRIMARY KEY, project_id text NOT NULL, actor text NOT NULL, action text NOT NULL,
 data jsonb NOT NULL, prev_hash text NOT NULL, hash text NOT NULL, created_at timestamptz NOT NULL DEFAULT now());
CREATE OR REPLACE FUNCTION ep_no_event_edit() RETURNS trigger LANGUAGE plpgsql AS $$
 BEGIN RAISE EXCEPTION 'audit is append only'; END; $$;
DROP TRIGGER IF EXISTS ep_audit_immutable ON ep_events;
CREATE TRIGGER ep_audit_immutable BEFORE UPDATE OR DELETE ON ep_events FOR EACH ROW EXECUTE FUNCTION ep_no_event_edit();
'''

def uid(prefix='r'):
    return prefix + '_' + uuid4().hex

def now():
    return datetime.now(timezone.utc).isoformat()

class Database:
    def __init__(self, dsn):
        self.dsn = dsn
        with self.tx() as c:
            c.execute(SCHEMA)

    @contextmanager
    def tx(self, write=True):
        with psycopg.connect(self.dsn, row_factory=dict_row) as c:
            if write:
                c.execute('SELECT pg_advisory_xact_lock(734091553)')
            else:
                c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                c.ep_gate_cache={}
            yield c

    @staticmethod
    def get(c, ident, kind=None):
        r = c.execute('SELECT body,kind FROM ep_records WHERE id=%s', (ident,)).fetchone()
        if not r or (kind and r['kind'] != kind):
            raise KeyError('记录不存在')
        return r['body']

    @staticmethod
    def put(c, kind, body):
        c.execute('INSERT INTO ep_records(id,kind,project_id,body) VALUES(%s,%s,%s,%s) '
                  'ON CONFLICT(id) DO UPDATE SET body=EXCLUDED.body',
                  (body['id'], kind, body.get('project_id', ''), Jsonb(body)))
        return body

    @staticmethod
    def rows(c, kind, project=None):
        sql, args = 'SELECT body FROM ep_records WHERE kind=%s', [kind]
        if project is not None:
            sql += ' AND project_id=%s'; args.append(project)
        return [r['body'] for r in c.execute(sql + ' ORDER BY created_at,id', args).fetchall()]

    @staticmethod
    def event(c, project, actor, action, data):
        prev = c.execute('SELECT hash FROM ep_events ORDER BY seq DESC LIMIT 1').fetchone()
        prev = prev['hash'] if prev else '0' * 64
        value = {'project': project, 'actor': actor, 'action': action, 'data': data, 'prev': prev}
        c.execute('INSERT INTO ep_events(project_id,actor,action,data,prev_hash,hash) VALUES(%s,%s,%s,%s,%s,%s)',
                  (project, actor, action, Jsonb(data), prev, digest(value)))
