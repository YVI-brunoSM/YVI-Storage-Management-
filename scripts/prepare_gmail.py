"""Create a PRIVATE Railway variables file; never print credentials."""
import argparse
import json
from pathlib import Path
from cryptography.fernet import Fernet


def main():
    parser = argparse.ArgumentParser(description='Preparar variáveis privadas de Gmail para o Railway.')
    parser.add_argument('--credentials', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit('O arquivo de saída já existe. Preserve a chave atual; não substitua sem revisão.')
    try:
        data = json.loads(args.credentials.read_text(encoding='utf-8'))['web']
        values = [data['client_id'], data['client_secret']]
        if not all(isinstance(v, str) and v and not any(c in v for c in '\r\n\x00') for v in values):
            raise ValueError()
    except (OSError, ValueError, KeyError, TypeError):
        raise SystemExit('Não foi possível ler credenciais OAuth Web válidas.') from None
    env = {'APP_BASE_URL':'https://yvi-storage--management.up.railway.app',
        'GOOGLE_CLIENT_ID':data['client_id'], 'GOOGLE_CLIENT_SECRET':data['client_secret'],
        'EMAIL_TOKEN_KEY':Fernet.generate_key().decode(), 'GMAIL_SENDER':'yvigestaofitness@gmail.com',
        'EMAIL_REPLY_TO':'yvibrunosilva@gmail.com', 'EMAIL_ENABLED':'true', 'EMAIL_DAILY_LIMIT':'100'}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8', newline='\n') as file:
        file.write('# PRIVADO: importar nas variáveis do Railway. Nunca publicar no GitHub.\n')
        file.write('\n'.join(key+'='+json.dumps(value) for key,value in env.items())+'\n')
    print('Arquivo privado preparado. Nenhuma credencial foi exibida.')


if __name__ == '__main__':
    main()
