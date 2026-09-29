# Implantação e operação

## Primeira publicação com dados existentes

1. Agende uma janela sem alterações pelo sistema antigo. Essa versão não deve escrever ao mesmo tempo que o sistema anterior: as regras de histórico e saldo são diferentes.
2. Faça backup PostgreSQL em formato custom (`pg_dump --format=custom`) e guarde-o em armazenamento com acesso restrito. Verifique a restauração em um banco separado com `pg_restore --no-owner --no-acl`. Não coloque URLs com senha em comandos compartilhados ou logs; use variáveis de ambiente ou arquivo de credenciais com acesso restrito.
3. Restaure uma cópia para homologação. Execute `python migrate.py --report` e revise quantidades inválidas, vínculos órfãos e divergências entre histórico antigo e saldo atual. O relatório é diagnóstico, não conciliação automática.
4. Confirme o fuso dos timestamps antigos, defina `LEGACY_TIMEZONE` e, após revisar o backup e a linha de base, `LEGACY_MIGRATION_ACK=yes`. Execute `python migrate.py`. Não edite os arquivos SQL depois que forem aplicados; futuras mudanças devem ser novas migrações.
5. Compare contagens, amostras de saldos, valores arredondados, responsáveis e datas. Execute `python manage.py reconcile`: o resultado esperado é zero divergências após a linha de base.
6. Publique em homologação e verifique login de cada perfil, custos ocultos para operador, disputa pelo último item, estorno, CSV e reconexão.
7. Repita backup e migração no banco de produção durante a janela. Publique esta versão e libere os usuários após verificar `/health/ready` e o fluxo principal.
8. Remova as variáveis de autorização legada após a migração bem-sucedida. Proteja e retenha o backup segundo a política da empresa.

Se o banco em uso for SQLite, esta versão **não importa automaticamente esse arquivo**. O caminho de migração é PostgreSQL; será necessário exportar e transformar a base SQLite em uma cópia PostgreSQL, preservando IDs, e validar contagens/saldos antes dos passos acima. Nenhuma base de dados real foi alterada nesta entrega.

## Reversão de implantação

As migrações desta versão não possuem downgrade automático. Antes de aceitar novas operações, uma falha de implantação permite voltar à aplicação antiga e restaurar o backup em banco separado, após conferência. Depois de novas operações, **não restaure um backup antigo por cima da base atual**: isso apagaria trabalho válido. Suspenda gravações, preserve um novo backup, identifique os lançamentos posteriores e faça recuperação assistida.

Healthcheck com sucesso só confirma conexão e versão de esquema; não confirma conciliação, permissões ou backup. Teste esses itens separadamente.

## Permissões do banco

Prefira um papel proprietário usado apenas por `MIGRATION_DATABASE_URL` e um papel de aplicação em `DATABASE_URL`. Após a migração, conceda ao papel de aplicação CONNECT no banco e USAGE no schema e sequências. As permissões necessárias são:

| Tabela | Operações da aplicação |
|---|---|
| users, role_permissions, products | SELECT, INSERT, UPDATE |
| categories, branches | SELECT, INSERT, UPDATE, DELETE |
| movements, audit_events, product_baselines | SELECT, INSERT |
| operation_keys | SELECT, INSERT, UPDATE |
| login_limits | SELECT, INSERT, UPDATE, DELETE |
| schema_migrations | SELECT |

O papel da aplicação não deve ser proprietário, superusuário, criar tabelas nem desativar triggers. `manage.py create-admin` e `reconcile` funcionam com os privilégios acima. Ajuste grants explicitamente para o nome do papel escolhido; não distribua credenciais administrativas no serviço web.

## Monitoramento e suporte

- Registre disponibilidade de `/health/ready` com monitor externo. O healthcheck de deploy não substitui monitoramento contínuo.
- Acompanhe taxa de 5xx, latência, reinícios, uso de memória e conexões do Postgres. Investigue ocorrências recorrentes de `database_unavailable` e `realtime_delivery_failed`.
- Cada erro de API inclui um protocolo `request_id`. Busque esse valor nos logs JSON. Não peça ao usuário cookies, senha ou a URL de conexão.
- Os logs da aplicação não registram corpos, cookies, senhas ou texto das exceções SQL. Políticas do provedor e outros componentes também devem restringir exposição e retenção.
- Conflito de saldo: conferir a disponibilidade e corrigir a quantidade. Conflito de versão: reabrir o cadastro atualizado e reaplicar a alteração.
- Falha de rede após confirmação: use **Verificar / repetir o mesmo envio**. Não crie outro lançamento até conhecer o resultado. A mesma identificação de envio impede duplicação no servidor.
- Execute `python manage.py reconcile` periodicamente e após incidentes. Divergências exigem investigação; o comando não corrige saldos silenciosamente.
- Execute `python manage.py purge-login-limits` periodicamente para remover janelas antigas. Chaves de operações são mantidas para conservar a proteção contra repetição; qualquer política de expurgo precisa definir primeiro a janela de recuperação suportada.

## Backups e recuperação

Configure backups automáticos compatíveis com o plano contratado e uma cópia independente protegida. Defina com a empresa o RPO (quanto trabalho pode ser perdido) e RTO (prazo para restabelecimento). Teste a restauração regularmente em ambiente separado e registre duração, contagens, conciliação e resultado de login. Um backup que nunca foi restaurado não comprova recuperabilidade.

## Limites conhecidos

- A entrega trata falhas esperadas com mensagens amigáveis, mas nenhum software pode garantir disponibilidade absoluta. Se o servidor nem conseguir entregar HTML, a tela de erro pode ser do proxy ou navegador; isso é coberto por monitoramento e recuperação de infraestrutura.
- Desempenho depende de CPU, memória, latência, volume e plano Railway. O teste local de concorrência não é uma medição desse provedor.
- Histórico legado pode ter inconsistências anteriores. Elas são apontadas e preservadas, não corrigidas por suposição.
- O histórico é protegido contra edição pela aplicação e por triggers. Um administrador do banco ainda pode alterar ou remover esses mecanismos; controles de acesso e backups continuam necessários.
- Exportação limitada a 10.000 linhas por solicitação; reduza o período ou filtro quando ultrapassar. Exportações maiores exigem processamento em segundo plano.
- Falha de rede mantém o formulário aberto, mas fechar a aba ou encerrar a sessão pode perder o rascunho. Confira o histórico antes de iniciar outra operação nessas situações.
