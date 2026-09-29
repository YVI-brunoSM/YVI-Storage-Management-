"""Explicit, transactional, checksum-verified migrations. No app import or seeds."""
import argparse
import hashlib
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo
import psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent


def inspect(conn):
    exists = conn.execute("SELECT to_regclass('public.products') AS name").fetchone()['name']
    if not exists:
        return {'existing_database': False}
    report = {'existing_database': True}
    for table in ('products','users','movements','categories','branches'):
        report[table] = conn.execute(psycopg.sql.SQL('SELECT count(*) AS n FROM {}').format(psycopg.sql.Identifier(table))).fetchone()['n']
    report['invalid_products'] = conn.execute("SELECT count(*) AS n FROM products WHERE current_stock IS NULL OR current_stock<0 OR min_stock IS NULL OR min_stock<0 OR purchase_price IS NULL OR purchase_price<0 OR sale_price IS NULL OR sale_price<0 OR unit NOT IN ('un','m','par','cx','kg')").fetchone()['n']
    report['orphan_movement_products'] = conn.execute('SELECT count(*) AS n FROM movements m LEFT JOIN products p ON p.id=m.product_id WHERE m.product_id IS NOT NULL AND p.id IS NULL').fetchone()['n']
    report['duplicate_case_insensitive_usernames'] = conn.execute('SELECT count(*) AS n FROM (SELECT lower(username) FROM users GROUP BY lower(username) HAVING count(*)>1) duplicates').fetchone()['n']
    report['stock_differences_from_legacy_history'] = conn.execute("SELECT count(*) AS n FROM products p LEFT JOIN (SELECT product_id,sum(CASE WHEN type='ENTRADA' THEN quantity ELSE -quantity END) AS qty FROM movements GROUP BY product_id) m ON m.product_id=p.id WHERE p.current_stock<>coalesce(m.qty,0)").fetchone()['n']
    return report


def migrate(url, legacy_timezone=None, accept_legacy=False, report_only=False):
    with psycopg.connect(url, row_factory=dict_row) as conn:
        conn.execute("SET lock_timeout='5s'")
        conn.execute("SET statement_timeout='120s'")
        conn.execute('SELECT pg_advisory_xact_lock(791648230)')
        report = inspect(conn)
        if report_only:
            return report
        conn.execute('CREATE TABLE IF NOT EXISTS schema_migrations(version TEXT PRIMARY KEY, checksum TEXT NOT NULL, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())')
        existing = {r['version']: r['checksum'] for r in conn.execute('SELECT * FROM schema_migrations')}
        if report['existing_database'] and '002_hardening' not in existing:
            if not accept_legacy or not legacy_timezone:
                raise RuntimeError('Banco existente: faça backup, leia --report, defina LEGACY_TIMEZONE e LEGACY_MIGRATION_ACK=yes para confirmar a linha de base atual.')
            if report['invalid_products']:
                raise RuntimeError('Há produtos inválidos; corrija-os antes de migrar. Nenhum ajuste automático foi feito.')
            if report['duplicate_case_insensitive_usernames']:
                raise RuntimeError('Há logins duplicados quando se ignoram maiúsculas/minúsculas. Resolva antes de migrar.')
        ZoneInfo(legacy_timezone or 'UTC')
        conn.execute("SELECT set_config('app.legacy_timezone',%s,true)", (legacy_timezone or 'UTC',))
        for path in sorted((ROOT / 'migrations').glob('*.sql')):
            sql = path.read_text(encoding='utf-8')
            checksum = hashlib.sha256(sql.encode()).hexdigest()
            if path.stem in existing:
                if existing[path.stem] != checksum:
                    raise RuntimeError('Migração aplicada foi modificada: ' + path.name)
                continue
            conn.execute(sql)
            conn.execute('INSERT INTO schema_migrations(version,checksum) VALUES(%s,%s)', (path.stem, checksum))
        return report


if __name__ == '__main__':
    load_dotenv(ROOT / '.env')
    parser = argparse.ArgumentParser()
    parser.add_argument('--report', action='store_true')
    args = parser.parse_args()
    url = os.getenv('MIGRATION_DATABASE_URL') or os.environ['DATABASE_URL']
    try:
        result = migrate(url, os.getenv('LEGACY_TIMEZONE'), os.getenv('LEGACY_MIGRATION_ACK') == 'yes', args.report)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as exc:
        # Keep connection strings and row contents out of deployment logs.
        print('Migração não concluída:', type(exc).__name__)
        if isinstance(exc, RuntimeError):
            print(str(exc))
        raise SystemExit(1)
