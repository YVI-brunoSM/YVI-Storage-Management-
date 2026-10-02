# Estoque Geral por academia

## O que mudou

- Cada peça possui um cadastro único e pode ser vinculada a várias academias.
- Cada vínculo guarda seu próprio saldo e estoque mínimo. A peça aparece para a unidade mesmo sem movimentações e com saldo zero.
- Em Peças e Estoque, o saldo geral soma as unidades autorizadas; o filtro mostra o saldo da unidade escolhida. A coluna Unidades / saldos detalha a distribuição.
- Administradores veem todas as academias. Funcionários e gerentes veem somente as unidades definidas em Usuários e acessos. Essa regra também vale nas APIs, buscas, painel, relatórios e emails.
- Entradas, saídas e estornos alteram o saldo da unidade indicada. Saldo de outra academia nunca cobre automaticamente uma saída.
- Transferir registra uma saída na origem e uma entrada no destino na mesma transação, sem mudar o saldo geral. O usuário precisa de permissão de entrada e saída e acesso às duas unidades.
- A situação Repor considera a falta em qualquer unidade visível, mesmo se a soma geral for suficiente. Cada alerta de email informa o saldo e o mínimo da academia afetada.

## Criar ou editar uma peça

1. Abra Peças e Estoque → Nova peça ou Editar.
2. Preencha os dados da peça e marque as academias em Unidades selecionadas.
3. Todas as academias marca as unidades atualmente cadastradas. Também é possível selecionar somente algumas. Uma academia criada futuramente deve ser vinculada às peças desejadas.
4. No cadastro novo, informe o saldo inicial e o mínimo de cada academia. Saldo zero é permitido.
5. Na edição, o saldo atual é exibido para consulta; as alterações de quantidade são feitas por entrada, saída ou transferência. O mínimo pode ser ajustado por unidade.
6. Uma unidade só pode ser desvinculada quando seu saldo estiver zerado. O histórico permanece preservado.

O cadastro da peça é compartilhado entre academias. Sua criação e edição continuam reservadas a usuários com acesso geral e permissão de gerenciar peças. Funcionários restritos movimentam as peças de suas unidades conforme as permissões de seu perfil.

## Definir acesso de funcionários

Abra Usuários e acessos → Novo usuário ou Editar. Em Unidades selecionadas, marque uma ou mais academias, ou Todas as academias para acesso geral. Administradores mantêm acesso geral. Alterar as autorizações encerra sessões anteriores; o usuário deve entrar novamente.

Ter acesso a Miramar permite consultar as peças vinculadas a Miramar e apenas os saldos dessa unidade. Não é necessário registrar uma entrada para tornar a peça visível.

## Atualizar no Railway

1. Faça backup do Postgres e escolha uma janela sem movimentações na versão anterior. As versões antiga e nova usam regras de saldo diferentes.
2. Atualize o repositório com a aplicação de `yvi-sistema-atualizado.zip`.
3. No serviço web, mantenha **Pre-deploy Command:** `python3 migrate.py`.
4. Mantenha **Start Command:** `gunicorn --config gunicorn.conf.py app:app` e **Healthcheck Path:** `/health/ready`.
5. Publique a nova versão. A migração **008_unit_stock** precisa concluir antes de iniciar os serviços.
6. Atualize o serviço separado de emails para o mesmo código, mantendo **Start Command:** `python3 email_worker.py`.
7. Entre como administrador e conclua a distribuição dos saldos anteriores, conforme abaixo. Confira um perfil restrito antes de liberar a operação normal.

Não é preciso criar outro banco, apagar usuários nem cadastrar uma nova conta Google. As migrações anteriores não foram modificadas.

## Distribuir os saldos anteriores

O modelo anterior mantinha um saldo único. Seus destinos históricos não comprovam quanto existe fisicamente em cada academia. Por isso, a atualização preserva esse saldo e marca as peças com quantidade positiva como **A conferir**.

1. Em Peças e Estoque, clique em **Distribuir saldo**.
2. Confira o total anterior mostrado, marque as unidades e distribua as quantidades entre elas.
3. A soma precisa ser igual ao total preservado. Informe uma referência ou motivo da conferência e confirme.
4. A distribuição é auditada e só pode ser concluída uma vez. Não são inventadas entradas ou saídas para reescrever o histórico.

Até essa conferência, as movimentações da peça ficam bloqueadas. Os totais do painel incluem apenas saldos conferidos, e a exportação identifica explicitamente as pendências. Peças com saldo anterior zero não precisam dessa distribuição, mas precisam estar vinculadas às unidades que as utilizarão.

Se a contagem física for diferente do total anterior, preserve primeiro a distribuição do total registrado e depois lance entradas ou saídas justificadas na unidade correta para ajustar a diferença. Não altere saldos diretamente no banco.

## Conferir a operação

- Cadastre uma peça em duas unidades com saldos diferentes, incluindo uma com zero. O administrador deve ver a soma; cada gerente deve ver somente sua parte.
- Uma saída maior que o saldo local deve ser recusada, mesmo quando há estoque em outra unidade.
- Uma transferência deve preservar o saldo geral e aparecer em dois lançamentos identificados no histórico.
- Histórico anterior à migração e pernas individuais de uma transferência não podem ser estornados isoladamente. Para corrigir uma transferência, registre uma transferência compensatória com justificativa.
- `python3 manage.py reconcile` verifica o histórico geral, o saldo de cada unidade e a soma das unidades. Também informa quantas peças ainda aguardam distribuição; zero divergências não significa que essa distribuição já terminou.

As gravações usam transações, bloqueio de saldos e identificação de envio para evitar duplicações em reenvios. Testes cobrem permissões, somas, saldo zero, distribuição inicial, transferências, estorno, emails e concorrência.
