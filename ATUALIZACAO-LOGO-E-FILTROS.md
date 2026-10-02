> Documento histórico. As regras de saldo e de filtros descritas abaixo foram substituídas pela migração 008. Use [ESTOQUE-POR-UNIDADE.md](ESTOQUE-POR-UNIDADE.md) para a versão atual.

# Logo da empresa e filtros por unidade — 30/09/2026

A imagem fornecida da YVI foi incluída no login e no canto superior esquerdo. O arquivo PNG foi copiado integralmente, preservando transparência, cores e proporções. O fundo branco foi removido: um contorno branco fino acompanha o desenho da logo, integrando-a aos temas claro e escuro.

## Como usar

Selecione uma unidade em **Filtrar por unidade**, acima do conteúdo de qualquer página. O seletor foi ampliado para facilitar a leitura e a operação. A escolha continua ativa ao navegar entre as páginas. Selecione **Todas as academias** para voltar a mostrar todas as unidades; o botão **Limpar filtro** foi removido. As exportações CSV usam a mesma seleção. Ao registrar entrada ou saída, a unidade selecionada já aparece no campo de destino, que pode ser alterado no formulário.

Os filtros de unidade, busca, categoria e situação ficam na memória da própria aba do navegador. Não são gravados como preferência compartilhada no banco nem transmitidos a outros usuários. Cada consulta envia seus próprios filtros ao servidor. Alterar ou remover um filtro não afeta as consultas de outra pessoa, nem as de outra aba. Recarregar a página reinicia os filtros; sair da conta também limpa a seleção.

## O que o filtro representa

O sistema atual mantém um estoque central. O vínculo com cada unidade é o destino registrado nas movimentações. A seleção funciona assim:

| Página | Resultado com uma unidade selecionada |
| --- | --- |
| Visão geral | Gráfico e últimas movimentações da unidade; indicadores e saldo central das peças com movimentos para ela |
| Peças e Estoque | Peças que têm movimentações registradas para a unidade |
| Movimentações | Entradas e saídas com esse destino, incluindo estornos |
| Reposição | Peças relacionadas à unidade cujo saldo central está no mínimo ou esgotado |
| Categorias | Categorias dessas peças, com contagem dos itens relacionados |
| Unidades da rede | Cadastro da unidade selecionada |
| Usuários e acessos | Contas que registraram movimentações para essa unidade |
| Relatórios | Exportações de peças relacionadas e de movimentos para a unidade; combinam com busca e datas |

Saldo, mínimo e valoração continuam pertencendo ao estoque central. Usuários são relacionados pela autoria das movimentações; contas novas aparecem em **Todas as academias** até registrarem um movimento. Uma unidade sem movimentações mostra listas vazias, com mensagem de estado vazio. Peças sem destino aparecem em **Todas as academias**.

O filtro é uma ferramenta de consulta. As permissões de cada perfil continuam sendo verificadas pelo servidor. Todas as consultas usam parâmetros validados; a paginação e os CSV mantêm a unidade selecionada. Movimentos repetidos para a mesma unidade não duplicam peças nem categorias.

## Atualizar no Railway

1. Publique o conteúdo atualizado de **gym_inventory_app** no repositório ligado ao serviço da aplicação.
2. Confirme o comando pré-deploy `python3 migrate.py` (ou `python migrate.py`, conforme seu ambiente).
3. Faça o deploy. A migração `004_branch_filters.sql`, incluída na atualização anterior, adiciona dois índices para acelerar os filtros. Esta revisão visual não exige outra migração; os arquivos de migração antigos devem permanecer intactos.
4. Aguarde `/health/ready` retornar `{"status":"ready"}` e atualize a página do sistema para carregar o novo JavaScript e CSS.

Caso o pré-deploy não esteja configurado, execute `cd /app` e `python3 migrate.py` no terminal do serviço da aplicação antes de reiniciar. Não é necessário recriar o banco, usuários ou estoque, nem adicionar variáveis de ambiente. A migração foi aplicada ao banco de demonstração local; o Railway será atualizado pelo seu deploy.

## Validação

- 50 testes de backend passaram em 58,67 segundos, usando PostgreSQL local e bancos descartáveis, incluindo um teste de isolamento entre dois usuários autenticados.
- 5 testes do cliente HTTP passaram; módulos JavaScript tiveram a sintaxe conferida.
- Filtros verificados em produtos, reposição, categorias, unidades, usuários, dashboard, movimentos e CSV, incluindo parâmetros inválidos, paginação, unidades vazias e permissões.
- Conferência visual da revisão feita nos dois temas, no login e no cabeçalho. Em ambiente somente de leitura com dados fictícios, duas abas mantiveram unidades diferentes; selecionar Todas as academias em uma delas não alterou a outra. A captura `yvi-logo-contorno-filtro.png` mostra o contorno e o seletor ampliado.
- A imagem usada no sistema tem o mesmo SHA-256 do PNG enviado: `711a9cecfcc1c41222cc69cd3297db51b52f739c2b55024a04fe623b483a04d6`.

Capturas desta atualização mostram dados fictícios de teste. O aplicativo hospedado só receberá a atualização após publicar os arquivos e executar o deploy.
