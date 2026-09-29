# Padronização visual YVI — 29/09/2026

- Marca YVI nos títulos, navegação, nomes dos relatórios CSV, ícone do navegador e documentação atual do projeto.
- Aba e título “Peças e Estoque”.
- Situação de estoque com bolinha, texto em negrito e fundo suave: verde para disponível, âmbar para reposição e vermelho para esgotado.
- Entradas em verde e saídas em vermelho nas ações, confirmações, histórico e gráfico, com cores adequadas aos temas claro e escuro.
- Ícones vetoriais próprios em todas as abas. Barra lateral inicialmente recolhida, com expansão e recolhimento pelo botão superior. Não abre ao passar o mouse.
- Nomes acessíveis e identificação por tooltip continuam disponíveis quando só os ícones aparecem. A animação respeita a preferência do sistema por movimento reduzido.
- Em telas pequenas, o menu expandido sobrepõe o conteúdo sem alargar a página.

Os registros históricos continuam preservados no banco. A identificação da marca em nomes de responsáveis antigos é apresentada como YVI na interface e no CSV, sem reescrever os lançamentos.

Validação: 33 testes de backend aprovados após a padronização inicial; navegação e recolhimento conferidos no navegador, temas claro e escuro inspecionados e largura de 390 px conferida sem transbordamento horizontal da página. A tabela tem rolagem própria quando necessário.
