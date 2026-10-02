import argparse
import getpass
import os
import secrets
import psycopg
from psycopg.rows import dict_row
from werkzeug.security import generate_password_hash
from dotenv import load_dotenv
from pathlib import Path


def reconciliation(conn):
    historical = conn.execute("SELECT p.id,p.code,p.current_stock,b.quantity+coalesce(sum(CASE WHEN m.type='ENTRADA' THEN m.quantity ELSE -m.quantity END),0) AS expected FROM products p JOIN product_baselines b ON b.product_id=p.id LEFT JOIN movements m ON m.product_id=p.id AND NOT m.legacy GROUP BY p.id,b.quantity HAVING p.current_stock<>b.quantity+coalesce(sum(CASE WHEN m.type='ENTRADA' THEN m.quantity ELSE -m.quantity END),0)").fetchall()
    local = conn.execute("SELECT s.product_id,s.branch_id,s.quantity,s.opening_quantity+coalesce(sum(CASE WHEN m.type='ENTRADA' THEN m.quantity ELSE -m.quantity END),0) AS expected FROM product_stocks s LEFT JOIN movements m ON m.product_id=s.product_id AND m.branch_id=s.branch_id AND m.stock_model=2 AND NOT m.legacy GROUP BY s.product_id,s.branch_id HAVING s.quantity<>s.opening_quantity+coalesce(sum(CASE WHEN m.type='ENTRADA' THEN m.quantity ELSE -m.quantity END),0)").fetchall()
    totals = conn.execute('SELECT p.id,p.code,p.current_stock,p.unallocated_stock+coalesce(sum(s.quantity) FILTER(WHERE s.enabled),0) AS expected FROM products p LEFT JOIN product_stocks s ON s.product_id=p.id GROUP BY p.id HAVING p.current_stock<>p.unallocated_stock+coalesce(sum(s.quantity) FILTER(WHERE s.enabled),0)').fetchall()
    pending = conn.execute('SELECT count(*) AS n FROM products WHERE stock_allocation_pending').fetchone()['n']
    return {'histórico geral': historical, 'saldos por unidade': local, 'soma das unidades': totals}, pending


def main():
    load_dotenv(Path(__file__).with_name('.env'))
    parser = argparse.ArgumentParser(description='Operação explícita; nunca executado no boot.')
    parser.add_argument('command', choices=['create-admin','reconcile','purge-login-limits'])
    parser.add_argument('--username')
    parser.add_argument('--name')
    args = parser.parse_args()
    with psycopg.connect(os.environ['DATABASE_URL'], row_factory=dict_row) as conn:
        if args.command == 'create-admin':
            if not args.username or not args.name:
                parser.error('--username e --name são obrigatórios')
            password = getpass.getpass('Senha inicial (mínimo 12 caracteres): ')
            if not 12 <= len(password) <= 128 or password != getpass.getpass('Repita a senha: '):
                raise SystemExit('Senha inválida ou confirmação diferente.')
            conn.execute('INSERT INTO users(username,name,password_hash,role) VALUES(%s,%s,%s,%s)',
                         (args.username.lower().strip(),args.name,generate_password_hash(password),'ADMIN'))
            print('Administrador criado; contas existentes não foram alteradas.')
        elif args.command == 'reconcile':
            checks, pending = reconciliation(conn)
            for name, rows in checks.items():
                print(name+':', len(rows), 'divergência(s)')
                for row in rows:
                    print(row)
            print('Peças aguardando distribuição inicial:', pending)
            if any(checks.values()):
                raise SystemExit(1)
        else:
            conn.execute("DELETE FROM login_limits WHERE window_start<now()-interval '1 day'")
            print('Limites antigos removidos.')


if __name__ == '__main__':
    main()
