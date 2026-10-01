# YVI estoque — versão revisada

Sistema interno Flask + JavaScript, com PostgreSQL obrigatório. Interface em português, temas claro/escuro persistidos no navegador, fontes locais Manrope e EB Garamond, layout responsivo e navegação por teclado.

## O que mudou

- Notificações de estoque por Gmail, com fila no Postgres, conexão OAuth protegida e histórico administrativo. Alertas começam desativados. Siga [CONFIGURAR-GMAIL.md](CONFIGURAR-GMAIL.md) para concluir Google e Railway.
- Estoque e lançamento gravados na mesma transação. Bloqueio de linha por peça impede duas saídas de consumirem o mesmo saldo.
- Movimentações têm identificação única por usuário: repetir um envio não repete o lançamento. O formulário mantém o preenchimento quando ocorre uma falha recuperável.
- Edições usam uma versão do registro. Se outra pessoa o alterou, a atualização antiga recebe uma mensagem de conflito.
- Histórico imutável: correções por estorno administrativo, sem apagar o lançamento original. Produtos são arquivados somente com saldo zero.
- Custos são filtrados no servidor em consultas, painel e CSV. Sessões verificam usuário ativo e permissões atuais a cada requisição.
- CSRF, cookies seguros em produção, senhas com hash scrypt, limitação de tentativas de login, consultas parametrizadas e renderização por texto no navegador.
- Pool de até 8 conexões por processo, timeouts, paginação e índices para o histórico. Quantidades e dinheiro usam `NUMERIC`/`Decimal`.
- Respostas de erro amigáveis com protocolo; registros estruturados no backend, sem devolver stack traces ou detalhes do banco ao usuário.
- Nenhuma conta ou dado de demonstração é criado ao iniciar a aplicação.

## Executar localmente

Requisitos: Python 3.12 e PostgreSQL 17. Crie um banco vazio destinado ao desenvolvimento. Não aponte uma instalação de teste para o banco da empresa.

```text
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
```

Copie `.env.example` para `.env`. Defina `APP_ENV=development`, `TRUST_PROXY=0`, `DATABASE_URL` do banco local e uma `SECRET_KEY` aleatória. Para gerar a chave:

```text
python -c "import secrets; print(secrets.token_hex(32))"
python migrate.py
python manage.py create-admin --username administrador --name "Administrador"
python run.py
```

A senha é solicitada de forma interativa, sem ficar no código. Acesse `http://127.0.0.1:5000`. O servidor de desenvolvimento não deve ser exposto na internet.

## Railway

Veja o passo a passo atualizado em [DEPLOY-RAILWAY.md](DEPLOY-RAILWAY.md). Confira as configurações no painel: o suporte legado a railway.toml está em descontinuação.

1. Suba **esta pasta** em um repositório privado ou como diretório raiz do serviço. O Dockerfile define o build; configure migração, servidor e healthcheck conforme o guia. `railway.toml` preserva a configuração legada como referência.
2. Adicione PostgreSQL ao projeto. Configure `DATABASE_URL` por referência ao serviço Postgres, preferindo a rede privada. Use TLS com validação conforme as exigências do endpoint se acessar uma conexão externa.
3. Configure `SECRET_KEY` aleatória, `APP_ENV=production`, `TRUST_PROXY=1` quando houver somente o proxy confiável do Railway na frente, `DB_POOL_SIZE=8`, `DB_POOL_TIMEOUT=3`, `DB_STATEMENT_TIMEOUT_MS=5000`.
4. Mantenha **uma réplica e um worker Gunicorn**, com 64 threads. Isso comporta concorrência de requisições sem quebrar o roteamento de sessões Socket.IO. O pool limita as conexões reais a 8. O `PORT` é lido automaticamente.
5. Para banco novo, a migração cria somente o esquema e perfis. Execute `python manage.py create-admin ...` em uma sessão interativa segura conectada ao mesmo banco para criar o primeiro acesso.
6. Verifique `/health/ready`, login, uma entrada/saída e o CSV em homologação, usando HTTPS. Faça o teste de carga no plano Railway escolhido antes de liberar para toda a equipe.

O banco precisa reservar conexões para administração, migração e sobreposição de deploys: com duas instâncias durante uma troca, considere até 16 conexões de aplicação, além da reserva operacional. Confirme `max_connections` do serviço. Não aumente workers ou réplicas sem rever o limite.

Redis é opcional e não é necessário com uma réplica. Escala horizontal com Socket.IO exige distribuição de eventos e afinidade de sessão para polling, ou uma arquitetura exclusivamente WebSocket validada. Configurar somente `REDIS_URL` não resolve o roteamento entre instâncias. A aplicação recarrega os dados periodicamente se os eventos em tempo real falharem.

Referências usadas: [deploy Flask-SocketIO](https://flask-socketio.readthedocs.io/en/stable/deployment.html), [pre-deploy Railway](https://docs.railway.com/deployments/pre-deploy-command), [healthchecks Railway](https://docs.railway.com/deployments/healthchecks).

## Migrar o banco atual

Leia `OPERACAO.md` antes de executar. As migrações são transacionais, possuem checksum e bloqueio de execução simultânea. Não fazem alterações durante importação ou inicialização do servidor.

```text
python migrate.py --report
```

Para um banco legado, a migração exige `LEGACY_MIGRATION_ACK=yes` e `LEGACY_TIMEZONE` confirmado a partir da origem real dos horários. Não suponha que o banco usava UTC ou São Paulo sem conferir. Um exemplo válido, se os horários antigos eram locais, é `America/Sao_Paulo`.

O saldo atual é registrado como linha de base. O histórico anterior é identificado como legado, preservado e não pode ser estornado automaticamente. A migração não inventa movimentações para encobrir divergências antigas. IDs de peças excluídas são preservados em `legacy_product_id`, além dos dados históricos disponíveis.

Preços antigos em ponto flutuante são convertidos para duas casas decimais. Quantidades passam a três casas, mas unidades `un`, `par` e `cx` continuam exigindo inteiros. Dados incompatíveis interrompem e revertem a migração para correção assistida. Confira os relatórios e a conversão em uma cópia restaurada antes de produção.

Contas existentes e seus hashes são preservados. Troque senhas de contas padrão antigas e desative as que não devem operar; não há reativação automática. A chave de sessão nova invalida os cookies antigos.

## Testes

```text
pip install -r requirements-dev.txt
python -m pytest -q
node --test tests/http.test.mjs
```

Defina `YVI_TEST_ADMIN_URL` apontando para um Postgres **local descartável**, com permissão para criar bancos. A suíte cria nomes `yvi_test_*` exclusivos e remove apenas esses bancos ao terminar. Ela recusa hosts remotos e nunca usa `DATABASE_URL` como alternativa.

O teste de carga e o relatório de validação entregues ao lado do pacote registram ambiente e limites da medição. Os testes locais não substituem homologação do serviço Railway nem garantem ausência absoluta de falhas.

Para reproduzir a carga local, com a mesma variável `YVI_TEST_ADMIN_URL` e a porta 5090 livre, execute `python benchmarks/local_load.py`. O script cria seu próprio banco descartável, prepara 10.000 produtos e 100.000 lançamentos históricos, executa 20 sessões HTTP durante cerca de dois minutos e remove o banco de teste ao terminar. O relatório JSON é impresso na saída. Instale antes `requirements-dev.txt`.

## Estrutura

`inventory/`: aplicação, permissões, transações, APIs e eventos. `migrations/`: esquema versionado. `static/` e `templates/`: interface e recursos locais. `tests/`: verificações com banco real. `manage.py`: operações administrativas explícitas. `migrate.py`: migração e diagnóstico prévio.

Licenças das fontes e do cliente Socket.IO estão em `static/fonts/` e `static/vendor/`. `static/asset-sources.json` registra origem e hashes desses recursos. Nenhum serviço de fontes externo é chamado pela interface.

## Administração e unidades autorizadas

A aba Configurações reúne os recursos administrativos. Usuários podem ter acesso geral ou a uma lista de unidades. Publique com `python migrate.py` para aplicar `006_user_branch_access` antes de iniciar esta versão. As contas existentes preservam o acesso geral até serem revisadas. Veja [o guia de configuração de unidades](ACESSO-UNIDADES.md).
