# YVI — publicação no Railway com PostgreSQL

Guia preparado em 29/09/2026. A aplicação foi validada localmente; o deploy na sua conta Railway ainda não foi executado. Os serviços geram cobrança conforme plano e consumo: confira a estimativa no painel antes de contratar.

## 1. Prepare os arquivos

Use a pasta **gym_inventory_app** desta entrega. Coloque seu conteúdo na raiz de um repositório privado no GitHub: `Dockerfile`, `app.py`, `requirements.txt`, `inventory/`, `migrations/`, `static/` e `templates/` devem ficar juntos. Você pode usar o GitHub Desktop para criar o repositório local e publicar marcando **Keep this code private**.

Não publique `.env`, senhas, cópias de banco, a pasta `work`, ambientes virtuais ou arquivos pessoais. O pacote entregue não inclui o banco de demonstração. Criar um banco novo no Railway não transfere automaticamente seu estoque local.

## 2. Crie o projeto e o banco

No Railway, crie um projeto vazio. Dentro dele, adicione um serviço PostgreSQL pelo catálogo de bancos. Aguarde ficar disponível e mantenha o volume persistente do banco. Adicione outro serviço usando seu repositório GitHub privado e selecione a branch desejada.

Use a mesma região para os dois serviços. Se os arquivos estão dentro de uma subpasta no GitHub, informe essa subpasta em **Root Directory** do serviço da aplicação. Se estão na raiz, não precisa alterar.

O banco fornece a variável `DATABASE_URL`; a aplicação pode referenciá-la pela rede privada. [Documentação do PostgreSQL no Railway](https://docs.railway.com/databases/postgresql).

## 3. Configure as variáveis da aplicação

Abra **Variables** no serviço da aplicação, e não no banco:

| Nome | Valor |
| --- | --- |
| `APP_ENV` | `production` |
| `SECRET_KEY` | Uma chave aleatória exclusiva, conforme abaixo |
| `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` |
| `TRUST_PROXY` | `1` quando o acesso vier pelo proxy padrão do Railway |
| `DB_POOL_SIZE` | `8` |
| `DB_POOL_TIMEOUT` | `3` |
| `DB_STATEMENT_TIMEOUT_MS` | `5000` |

Se seu serviço de banco tiver outro nome, substitua **Postgres** pelo nome exato. Prefira a opção de inserir referência disponível no editor de variáveis. Não use `localhost` nem a conexão do banco de testes no Railway. [Referências entre serviços](https://docs.railway.com/variables).

Gere a chave uma vez, no terminal do seu computador com Python instalado:

```powershell
python -c "import secrets; print(secrets.token_hex(32))"
```

Copie o resultado para `SECRET_KEY` e guarde em local seguro. Não coloque no GitHub. Preserve a mesma chave nos próximos deploys; trocá-la encerra as sessões existentes.

Deixe `REDIS_URL` sem configurar nesta instalação de uma réplica. `MIGRATION_DATABASE_URL` é opcional: inicialmente as migrações usam `DATABASE_URL`. Para separar usuário de migração e usuário de aplicação com privilégios mínimos, siga **OPERACAO.md**, antes de liberar o uso real.

## 4. Confira as configurações de build e deploy

Configure estes valores no painel do serviço da aplicação:

| Configuração | Valor |
| --- | --- |
| Builder | Dockerfile |
| Dockerfile | `Dockerfile` |
| Pre-deploy command | `python migrate.py` |
| Start command | `gunicorn --config gunicorn.conf.py app:app` |
| Healthcheck path | `/health/ready` |
| Healthcheck timeout | `120` segundos |
| Réplicas | `1` |
| Restart policy | On Failure, até `5` tentativas |

Não configure comandos de instalação adicionais: o Dockerfile instala as dependências. O Gunicorn já usa 1 processo e 64 threads e lê a porta `PORT` fornecida pelo ambiente. Mantenha esta configuração inicial; ampliar processos/réplicas exige revisar conexões e comunicação em tempo real.

A documentação atual informa que `railway.toml` está em processo de descontinuação, com suporte legado até 01/12/2026. Ele continua incluído como referência, mas confira explicitamente os valores no painel para um projeto novo. [Configuração como código](https://docs.railway.com/config-as-code/reference).

A migração prepara o banco antes de iniciar a aplicação e inclui a tabela de versões e as fotos de perfil. Se ela falhar, o deploy não prossegue: leia o erro antes de repetir. Nunca apague o banco para corrigir uma migração de produção. [Comandos pré-deploy](https://docs.railway.com/deployments/pre-deploy-command).

## 5. Publique e gere o endereço

Aplique as alterações e aguarde o build e o deploy. Em **Settings → Networking**, gere um domínio público para **a aplicação**. Abra o endereço HTTPS gerado. O PostgreSQL pode continuar acessível somente pela rede privada.

No navegador, abra também `https://SEU-DOMINIO/health/ready`: o resultado esperado é `{"status":"ready"}`. Depois volte à página inicial. A tela de login não cria usuários automaticamente. [Rede pública e HTTPS](https://docs.railway.com/networking/public-networking).

## 6. Crie o primeiro administrador

Instale a CLI oficial do Railway seguindo [a página de instalação](https://docs.railway.com/cli). Com Node.js instalado, a opção via npm é:

```powershell
npm install -g @railway/cli
railway login
railway link
railway ssh
```

No vínculo, escolha seu projeto, ambiente de produção e **serviço da aplicação**, não o Postgres. Você também pode copiar o comando SSH específico pelo painel do Railway. A CLI pode pedir para registrar sua chave SSH na primeira conexão. [Acesso SSH ao serviço](https://docs.railway.com/cli/ssh).

Já no terminal remoto, execute:

```sh
python manage.py create-admin --username administrador --name "Seu nome"
```

Informe uma senha de pelo menos 12 caracteres e confirme quando solicitado. Ela não aparece enquanto você digita. Não coloque a senha no comando, no GitHub ou em mensagens. Esse comando cria uma conta nova; não redefine contas existentes. Digite `exit` para sair do terminal remoto.

Entre pelo domínio HTTPS com essa conta e cadastre as demais em **Usuários e acessos**. Cada pessoa deve usar um login próprio. A conta `preview` do ambiente local não é criada no Railway.

## 7. Cadastre e teste a operação

Cadastre categorias e unidades da rede, depois as peças. Cada categoria permite escolher um dos 12 ícones na criação e na edição. Em **Meu perfil**, cada usuário envia ou remove sua própria foto. São aceitos JPG, PNG e WebP até 2 MB e 16 megapixels; o servidor gera uma imagem de 256 × 256 sem metadados. As miniaturas ficam no Postgres e acompanham seus backups, sem exigir volume na aplicação.

Valide com duas contas: entrada, saída, saldo atualizado e tentativa de retirar mais que o disponível. Confira permissões do operador, tema claro/escuro e busca de peças no campo da movimentação. Use peças de teste identificadas e, se necessário, estorne as movimentações: preserve o histórico.

O teste de carga local anterior usou 20 usuários simultâneos. Isso não substitui medir latência e consumo no seu plano Railway. Acompanhe CPU, memória, erros e conexões antes de ampliar recursos.

## 8. Backups, atualizações e dados existentes

Ative backups do volume do PostgreSQL no painel e defina retenção apropriada. Faça uma restauração de teste em ambiente separado antes de depender deles. [Backups de volumes](https://docs.railway.com/volumes/backups).

Para aproveitar um banco já usado pela empresa, siga o procedimento de backup, relatório de migração e conferência de saldos em **OPERACAO.md**. Não importe sobre um banco com movimentações novas. Não habilite as opções de migração legada sem revisar o relatório e o fuso dos registros antigos.

Para atualizar, publique a nova versão na branch conectada ao Railway. Confira o backup, acompanhe a migração e os logs, e teste o acesso. Reverter apenas o código não desfaz alterações no banco; siga a estratégia de reversão descrita em OPERACAO.md.

## Quando algo não funcionar

| Sintoma | Conferir |
| --- | --- |
| Build não encontra arquivos | Root Directory e presença do Dockerfile |
| Migração não conecta ao banco | Referência DATABASE_URL, banco disponível e mesmo projeto/ambiente |
| Healthcheck fica pendente | Logs da migração e comando de início; PORT e caminho `/health/ready` |
| Login volta à tela inicial | HTTPS, APP_ENV=production, chave estável e TRUST_PROXY correto |
| Primeiro login não funciona | Conta criada por `manage.py create-admin` no serviço e ambiente corretos |
| Alterações demoram a aparecer | Logs de conexão em tempo real; a atualização periódica funciona como alternativa |
| Foto rejeitada | Formato, limite de 2 MB e dimensões até 16 megapixels |

Ao pedir suporte, envie a mensagem amigável e o número de protocolo mostrado. Não compartilhe senhas, chaves ou strings de conexão.
