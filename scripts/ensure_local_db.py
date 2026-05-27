"""Create local Postgres database if it does not exist. Uses DATABASE_URL from .env."""
import os
import sys
from pathlib import Path
from urllib.parse import urlparse, urlunparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

db_url = os.getenv("DATABASE_URL", "").strip()
if not db_url:
    print("DATABASE_URL is not set in .env")
    sys.exit(1)

parsed = urlparse(db_url)
db_name = parsed.path.lstrip("/") or "real_estate_web3"
admin_url = urlunparse(parsed._replace(path="/postgres"))

conn = psycopg2.connect(admin_url)
conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
cur = conn.cursor()
cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db_name,))
if cur.fetchone():
    print(f"Database {db_name} already exists")
else:
    cur.execute(f'CREATE DATABASE "{db_name}"')
    print(f"Created database {db_name}")
cur.close()
conn.close()
