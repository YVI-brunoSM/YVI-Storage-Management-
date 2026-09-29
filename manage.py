import argparse
import getpass
import os
import secrets
import psycopg
from psycopg.rows import dict_row
from werkzeug.security import generate_password_hash
from dotenv import load_dotenv
from pathlib import Path


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
            rows = conn.execute("SELECT p.id,p.code,p.current_stock,b.quantity+coalesce(sum(CASE WHEN m.type='ENTRADA' THEN m.quantity ELSE -m.quantity END),0) AS expected FROM products p JOIN product_baselines b ON b.product_id=p.id LEFT JOIN movements m ON m.product_id=p.id AND NOT m.legacy GROUP BY p.id,b.quantity HAVING p.current_stock<>b.quantity+coalesce(sum(CASE WHEN m.type='ENTRADA' THEN m.quantity ELSE -m.quantity END),0)").fetchall()
            for row in rows:
                print(row)
            print('Divergências após a migração:',len(rows))
            if rows:
                raise SystemExit(1)
        else:
            conn.execute("DELETE FROM login_limits WHERE window_start<now()-interval '1 day'")
            print('Limites antigos removidos.')


if __name__ == '__main__':
    main()
