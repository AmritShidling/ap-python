import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Lock

import psycopg2.extras
from dotenv import load_dotenv
from psycopg2.pool import ThreadedConnectionPool

load_dotenv()

PG_URI = "postgresql://postgres.updgrusggnfpfxgfaczn:28Qwhsdxewii@aws-0-eu-west-1.pooler.supabase.com:5432/postgres"
LOG_SQL = os.environ.get("LOG_SQL") == "1"

try:
    pool = ThreadedConnectionPool(1, 8, dsn=PG_URI, sslmode="require")
    _probe = pool.getconn()
    with _probe.cursor() as _cur:
        _cur.execute("SELECT 1")
        _cur.fetchone()
    pool.putconn(_probe)
    print("[db] connected to Postgres", flush=True)
except Exception as _e:
    print(f"[db] CONNECTION FAILED: {type(_e).__name__}: {_e}", file=sys.stderr, flush=True)
    sys.exit(1)
executor = ThreadPoolExecutor(max_workers=8)

_sql_counter = 0
_sql_lock = Lock()


def run(sql, params=None):
    global _sql_counter
    conn = pool.getconn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            t0 = time.time()
            try:
                if params:
                    cur.execute(sql, params)
                else:
                    cur.execute(sql)
                rows = [dict(r) for r in cur.fetchall()] if cur.description else []
                if LOG_SQL:
                    with _sql_lock:
                        _sql_counter += 1
                        sid = _sql_counter
                    snippet = " ".join(sql.split())[:110]
                    print(f"  [SQL #{sid}] {int((time.time() - t0) * 1000)}ms  rows={len(rows)}  {snippet}")
                return rows
            except Exception as e:
                if LOG_SQL:
                    snippet = " ".join(sql.split())[:110]
                    print(f"  [SQL FAIL] {type(e).__name__}  {snippet}")
                raise
    finally:
        pool.putconn(conn)
