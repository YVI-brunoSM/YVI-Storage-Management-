# Configurações administrativas e acesso por unidade

## O que mudou

- A gestão de usuários e permissões fica em **Usuários e acessos**. E-mails ficam em **Notificações**; categorias e unidades mantêm suas próprias páginas. A aba Configurações foi removida. As APIs de administração exigem o perfil ADMIN.
- **Notificações** aparece acima de **Relatórios** no menu lateral.
- Ao criar ou editar usuários, o administrador usa **Unidades selecionadas**, sempre visível: **Todas as academias** é a primeira opção, seguida das unidades individuais. Marcar uma unidade desmarca o acesso geral; marcar Todas as academias limpa a seleção individual.
- Uma unidade autorizada fixa o filtro. Várias unidades permitem consultar todas as autorizadas em conjunto ou escolher uma delas. O servidor impede a consulta a unidades fora dessa lista, inclusive em buscas, detalhes de peças, relatórios CSV e movimentações.
- Alterar o usuário encerra suas sessões antigas. O acesso atualizado é aplicado quando ele entra novamente.
- O ícone da aba do navegador agora é a engrenagem preta com o cérebro vermelho no centro, sem áreas brancas e com fundo transparente.

## Como publicar

Atualize o repositório usado pelo Railway com a aplicação de `yvi-sistema-atualizado.zip` e faça o deploy. Mantenha **Pre-deploy Command** como `python migrate.py` no serviço web. Esta versão exige a nova migração **006_user_branch_access**. O serviço de envio de e-mails deve usar a mesma versão do código e o mesmo banco.

Caso a migração não esteja configurada antes do deploy, execute `python migrate.py` no serviço web usando a mesma `DATABASE_URL` da aplicação. Não altere nem reaplique manualmente arquivos históricos de migração. A migração acrescenta o campo e a tabela de autorização e mantém os dados existentes.

As contas existentes preservam o acesso geral. Após publicar, abra **Usuários e acessos → Editar** e defina as unidades de cada gerente/operador. Administradores mantêm acesso geral. Para novos usuários, a janela sugere selecionar as unidades explicitamente.

Para João acessar apenas uma academia: selecione o perfil Gerente, escolha **Somente as unidades selecionadas**, marque a academia e salve. Para acesso a várias, marque todas as permitidas. João precisará entrar novamente após a alteração.

Se o navegador ainda mostrar o ícone antigo, atualize a página ou feche e reabra a aba; o novo ícone usa um endereço de arquivo diferente.

## Estoque central e registros compartilhados

O sistema continua com um estoque central. A associação das peças às unidades usa as movimentações registradas para cada destino. Os filtros limitam as peças relacionadas e o histórico visível; não criam saldos separados por academia. Peças sem histórico de vínculo não aparecem para usuários restritos.

Para evitar que um usuário limitado altere cadastros compartilhados com outras unidades, ele não pode criar/editar/arquivar peças centrais nem alterar categorias e unidades. Essas ações devem ser realizadas por um administrador ou usuário com acesso geral e a permissão correspondente. Entradas e saídas continuam disponíveis conforme as permissões do perfil, somente para destinos autorizados e peças vinculadas às unidades permitidas.

Unidades vinculadas a usuários não podem ser excluídas enquanto esse vínculo existir. O administrador deve revisar a autorização antes de excluir uma unidade sem outros registros relacionados.

## E-mails

Os alertas de operações de outra unidade não são enviados a gerentes restritos a destinos diferentes. Os resumos são filtrados por destinatário. Alertas de alteração do mínimo central são limitados às peças vinculadas às unidades autorizadas. Mensagens antigas de movimentação sem identificação segura de unidade são canceladas para destinatários restritos.

O serviço verifica o acesso ao reservar o envio e novamente após renovar a autorização Google. Mensagens já enviadas não podem ser retiradas da caixa de entrada. Administradores continuam recebendo alertas gerais. A configuração de unidades não muda a expiração de sete dias do Gmail em modo Teste.

## Validação

Os 104 testes do backend e os 8 testes de JavaScript passaram. Testes usam PostgreSQL local descartável e respostas Google simuladas. Foram verificadas tentativas de acessar outra unidade pela URL, detalhes, pesquisas, exportações, gravações, seleção múltipla, atribuições inválidas, troca de perfil, encerramento de sessões e restrições nos e-mails. As interfaces administrativas, seleção múltipla e filtro fixo foram conferidas no navegador com dados fictícios.

Esta atualização foi preparada localmente; o assistente não publicou no Railway e não enviou e-mails reais nos testes.
