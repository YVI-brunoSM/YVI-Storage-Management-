# Ativar as notificações YVI pelo Gmail

Implementação preparada em 30/09/2026. Nenhum e-mail real foi enviado nesta preparação e nenhuma configuração foi publicada no Railway ou no Google Cloud.

Remetente: **yvigestaofitness@gmail.com**. Respostas e teste: **yvibrunosilva@gmail.com**. Alertas: administradores e gerentes ativos com endereço válido no cadastro. Não há confirmação de endereço para os destinatários.

## 1. Publique os arquivos atualizados

Extraia `yvi-sistema-atualizado.zip` e atualize o conteúdo do repositório que já está ligado ao Railway. O ZIP contém os arquivos do aplicativo na raiz. Preserve suas variáveis do Railway e as migrações antigas; não recrie o banco nem os usuários.

Confira no serviço web os comandos usados no deploy:

| Configuração | Valor |
| --- | --- |
| Build | Dockerfile existente |
| Pré-deploy | `python migrate.py` |
| Inicialização | `gunicorn --config gunicorn.conf.py app:app` |
| Healthcheck | `/health/ready` |

A migração `005_email_notifications.sql` cria a fila, o histórico e a conexão protegida. A migração começa com os alertas **desativados**. Aguarde a conclusão do deploy antes de conectar o Gmail. O sistema permanece utilizável se as variáveis de e-mail ainda não estiverem configuradas.

## 2. Cadastre o retorno no Google Cloud

Abra o projeto em que ativou a Gmail API. Acesse **Google Auth Platform → Clientes → seu cliente OAuth Web**.

Em **URIs de redirecionamento autorizados**, adicione exatamente:

```text
https://yvi-storage--management.up.railway.app/integrations/gmail/callback
```

Não inclua `/#dashboard`, barra extra no final ou espaços. Salve. Não é necessário preencher Origens JavaScript autorizadas: a troca de tokens acontece no servidor.

Em **Acesso a dados**, confira os escopos:

```text
https://www.googleapis.com/auth/gmail.send
openid
https://www.googleapis.com/auth/userinfo.email
```

O sistema pede `openid email` para confirmar que a conta conectada é o Gmail remetente esperado. Isso identifica o endereço autorizado; não dá acesso à leitura de mensagens. `email` corresponde ao escopo de informações do endereço no console.

Em **Branding / Marca**, informe a página inicial `https://yvi-storage--management.up.railway.app/` e a política de privacidade `https://yvi-storage--management.up.railway.app/politica-de-privacidade`. Publique esta versão do sistema antes de cadastrar o link e confirme que ele abre em uma janela anônima, sem login. A política também fica no rodapé da Visão geral. Utilize um nome de aplicativo coerente com a política, como **YVI — Notificações**.

O endereço público dos **Termos de Serviço** é `https://yvi-storage--management.up.railway.app/termos-de-servico`. Após publicar a atualização, informe esse endereço no campo correspondente de **Branding / Marca** e confira que abre sem login.

Em **Público-alvo**, use **Externo**, pois a conta é Gmail comum. Se estiver em Teste, adicione `yvigestaofitness@gmail.com` como usuário de teste. Os destinatários não precisam ser adicionados.

Para operação contínua, altere o status para **Em produção / Publicar aplicativo** antes da autorização definitiva. Em Teste, o token de renovação desse acesso expira em sete dias. Publicar não é o mesmo que concluir verificação do Google e não torna o estoque público. O Google prevê exceções de verificação para uso pessoal limitado; caso o console exija uma etapa adicional, registre a mensagem e peça orientação. Autorizações ainda podem ser revogadas depois de publicadas, por exemplo por alterações na conta.

Referências: [consentimento e escopos](https://developers.google.com/workspace/guides/configure-oauth-consent), [OAuth e tokens](https://developers.google.com/identity/protocols/oauth2), [exceções de verificação](https://support.google.com/cloud/answer/13464323?hl=pt-BR).

## 3. Importe as variáveis privadas no serviço web

Foi preparado um arquivo privado **fora do ZIP**:

```text
C:\Users\finan\Documents\Codex\2026-09-25\tenho-um-sistema-de-controle-de\work\email-private\.env.gmail
```

Ele contém as credenciais recebidas e uma chave nova de criptografia. Abra localmente como texto. No Railway, selecione o serviço **da aplicação** → **Variables** → **RAW Editor**. Adicione as linhas do arquivo às variáveis existentes. **Não apague as variáveis já presentes**, principalmente `DATABASE_URL` e `SECRET_KEY`. Também é possível usar New Variable para adicionar uma por vez; nesse caso, não inclua aspas envolvendo os valores.

| Variável | Finalidade |
| --- | --- |
| `APP_BASE_URL` | URL base HTTPS do sistema, sem `/#dashboard` |
| `GOOGLE_CLIENT_ID` | Identificação do cliente OAuth Web |
| `GOOGLE_CLIENT_SECRET` | Segredo do mesmo cliente |
| `EMAIL_TOKEN_KEY` | Chave que protege o token guardado no Postgres |
| `GMAIL_SENDER` | `yvigestaofitness@gmail.com` |
| `EMAIL_REPLY_TO` | `yvibrunosilva@gmail.com` |
| `EMAIL_ENABLED` | `true`, libera o processamento e o teste |
| `EMAIL_DAILY_LIMIT` | `100`, limite local inicial de tentativas em 24 horas |

`EMAIL_ENABLED=true` não ativa os alertas automaticamente: ainda será necessário conectar, testar e ativar na tela do sistema. Salve as alterações e faça o deploy.

Guarde uma cópia segura da chave `EMAIL_TOKEN_KEY`; use a mesma nos dois serviços e preserve-a nos próximos deploys. Nunca envie o arquivo privado, o JSON do cliente ou tokens para o GitHub. A perda da chave exige reconectar o Gmail. O aplicativo não precisa da sua senha Google.

Referência: [variáveis no Railway](https://docs.railway.com/variables).

## 4. Crie o serviço que processará a fila

No **mesmo projeto e ambiente** do Railway:

1. Crie um serviço a partir do **mesmo repositório GitHub** da aplicação. Nome sugerido: **yvi-emails**.
2. Use a mesma pasta raiz do código. Configure o build com o Dockerfile existente.
3. Nas configurações de deploy, defina o **Start Command** como `python email_worker.py`.
4. Deixe o **Healthcheck Path vazio** e mantenha uma réplica com reinicialização em caso de falha. Esse processo não é um site e não precisa de domínio público.
5. Desative o modo de suspensão/serverless, caso esteja habilitado para esse serviço: a fila precisa ser processada mesmo sem visitas ao site.
6. Importe as mesmas variáveis privadas do passo 3.
7. Configure `DATABASE_URL` apontando para o **mesmo Postgres da aplicação** e `SECRET_KEY` com o valor usado no serviço web. Use as referências de variáveis do Railway para evitar copiar segredos manualmente.
8. Configure `APP_ENV=production` e `DB_POOL_SIZE=2` nesse serviço de e-mail. O serviço web mantém seu pool atual.
9. Publique o serviço após a migração do serviço web ter terminado.

Confira nos detalhes do deploy que o comando efetivo é `python email_worker.py`, não Gunicorn, e que não há healthcheck HTTP. As configurações de deploy do Railway podem ser definidas no painel; serviços antigos com `railway.toml` podem ter valores herdados do arquivo, então confira a origem indicada pelo painel. A configuração existente do serviço web continua separada. [Configuração do Railway](https://docs.railway.com/config-as-code).

Não crie outro Postgres. O novo serviço compartilha a fila no banco atual. Não é necessário adicionar Redis para os e-mails. A API Gmail é gratuita para uso padrão dentro dos limites; o processo adicional consome recursos da hospedagem Railway.

## 5. Conecte o Gmail pelo sistema

Abra o sistema no seu navegador habitual e entre como **administrador**.

1. Abra **Notificações** na barra lateral.
2. Confira o remetente e o endereço de resposta.
3. Clique em **Conectar Gmail**.
4. No Google, escolha **yvigestaofitness@gmail.com**.
5. Confira que o aplicativo é o cliente criado por você e autorize envio de e-mail e identificação do endereço. Complete o login ou a verificação em duas etapas pessoalmente.
6. Ao retornar à página **Gmail conectado**, clique em **Voltar ao sistema**.

Se escolher outra conta, o sistema recusará a conexão. Não é preciso copiar um token: a autorização renovável fica criptografada no Postgres. Somente administradores podem conectar, desconectar ou administrar os envios.

## 6. Teste antes de ativar

1. Na aba Notificações, confira **Serviço de envio em execução**. Se não aparecer, verifique o serviço yvi-emails e as variáveis.
2. Clique em **Enviar teste**. O destinatário é fixo: `yvibrunosilva@gmail.com`.
3. Aguarde alguns segundos e clique em **Atualizar**. Procure o status **Aceito pelo Gmail** no histórico.
4. Abra seu Gmail profissional e confira a caixa de entrada e o spam. A aceitação pelo Gmail não comprova entrega ou leitura.
5. Confira, em **Usuários e acessos**, os endereços dos administradores e gerentes ativos. A seção **Quem recebe** apresenta esses destinatários; operadores não recebem os alertas.
6. Volte a Notificações e clique em **Ativar alertas**, depois de confirmar o recebimento do teste.
7. Opcionalmente clique em **Enviar resumo das pendências** para enviar a situação atual, sem alterar quantidades de estoque. O resumo pode ser solicitado uma vez por hora e inclui até 1.000 peças, com link para a lista completa.

Não faça movimentações falsas no estoque real para testar o envio. O botão de teste e o resumo permitem validar a integração sem alterar saldos.

## Regras implementadas

- Disponível → Repor, ou Disponível/Repor → Esgotado: gera um novo alerta.
- Permanecer em Repor após outra saída: não repete a mensagem.
- Esgotado → Repor por entrada parcial: não dispara um novo alerta de falta.
- Normalizar e depois voltar a faltar: gera nova ocorrência.
- Cadastro com saldo baixo/zero, alteração do mínimo e estorno: também são avaliados.
- Alertas desligados: novas ocorrências não geram mensagens. Mensagens antigas pendentes aguardam reativação; envios já em andamento podem concluir.
- Alertas ativados não geram um disparo retroativo automático. Use o resumo para as pendências existentes.
- Destinatários são verificados novamente antes do envio; usuários desativados, com perfil removido ou e-mail alterado têm aquela mensagem cancelada.
- Os filtros pessoais de unidade e busca não alteram disparos ou destinatários. O saldo informado é o estoque central, com a unidade de destino da movimentação quando houver.
- Mensagens apresentam nome, código, categoria, localização, saldos, mínimo, medida, data, operação, responsável e destino/observação quando disponíveis. Preços não são enviados.
- Tentativas automáticas em falhas seguramente anteriores ao envio ou rejeições temporárias: até cinco. Falhas de rede durante o envio e respostas ambíguas ficam para conferência, sem repetição automática.
- Registros encerrados são mantidos por 90 dias. Pendências, falhas e resultados incertos são preservados para revisão.

## Se algo não funcionar

| Situação | O que fazer |
| --- | --- |
| Notificações informa banco em atualização | No serviço web do Railway, execute `python migrate.py` e confirme que termina sem erro. Use a mesma `DATABASE_URL` da aplicação. Configure também esse comando em **Settings → Deploy → Pre-deploy Command** para os próximos deploys; não dependa apenas do arquivo railway.toml |
| Notificações mostra erro com protocolo | Nos logs do serviço web, localize o protocolo e envie ao suporte apenas `exception` e `frames`. Não envie credenciais, tokens, conteúdo de variáveis nem dados do banco. O protocolo sozinho não identifica a causa |
| `redirect_uri_mismatch` no Google | Confira o URI exato do passo 2, no mesmo cliente do arquivo JSON |
| Conta não permitida em Teste | Adicione o Gmail remetente aos usuários de teste desse projeto |
| Conectar Gmail desabilitado | Abra Ver configuração pendente e confira as variáveis do serviço web |
| Serviço de envio sem comunicação | Confira Start Command, banco, variáveis, logs e deploy do serviço yvi-emails |
| Fila sem progresso após muitas tentativas | Confira o limite local de 100 tentativas em 24h e eventuais limites do Google |
| Reconexão necessária | Confira credenciais/chave, reconecte e execute outro teste; reconectar pausa os alertas |
| Conferir envio | Procure a referência `YVI-<número>` no corpo ou `[YVI #<número>]` no assunto da pasta Enviados do remetente. Só reenvie se confirmar que não foi enviado |
| Mensagem aceita mas não recebida | Confira spam, endereço cadastrado e eventuais mensagens de devolução na conta remetente |

Desconectar remove as credenciais do sistema e cancela mensagens pendentes. Para revogar também a permissão no Google, use as conexões de terceiros da Conta Google. A desconexão local não chama a revogação remota automaticamente.

## Validação desta entrega

Uma execução completa passou com 70 testes de backend. Após a revisão final, os 27 testes específicos de notificações passaram, incluindo sete verificações adicionais de falhas HTTP e destinatário revogado durante renovação de token. Os cinco testes do cliente HTTP passaram; a sintaxe dos módulos JavaScript foi conferida.

Na atualização de 01/10/2026, os 81 testes de backend passaram, incluindo acesso público à política e erros recuperáveis de estrutura/configuração do banco de e-mails.

Os testes usam Postgres local descartável e respostas Google simuladas. A autorização Google real e a entrega na caixa de entrada só poderão ser confirmadas após os passos acima.
