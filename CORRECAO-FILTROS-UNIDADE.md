> Documento histórico. As regras de saldo e de filtros descritas abaixo foram substituídas pela migração 008. Use [ESTOQUE-POR-UNIDADE.md](ESTOQUE-POR-UNIDADE.md) para a versão atual.

# Correção dos filtros por unidade

O cadastro anterior gravava a unidade como texto de localização, enquanto os filtros dependiam das movimentações. Peças sem histórico ficavam ocultas para perfis restritos.

A versão corrigida grava o ID da unidade na peça. Acesso, consultas, categorias, painel, relatórios, busca de peças para movimentações e destinatários de email usam esse vínculo. A unidade atribuída prevalece sobre movimentações antigas para outros destinos. O histórico de movimentos mantém os destinos originais.

## Publicar no Railway

1. Atualize o repositório com os arquivos de `yvi-sistema-atualizado.zip`.
2. No serviço web, mantenha **Pre-deploy Command:** `python3 migrate.py`.
3. Mantenha **Start Command:** `gunicorn --config gunicorn.conf.py app:app` e **Healthcheck Path:** `/health/ready`.
4. Publique o site e o serviço de emails com a mesma versão. A migração **007_product_branch** deve concluir antes da inicialização dos serviços.
5. Com administrador, revise **Unidade da peça** nos cadastros cuja localização antiga não correspondia a uma unidade. Correspondências sem ambiguidade são recuperadas automaticamente.
6. Teste um usuário autorizado à unidade: a peça deve aparecer mesmo com saldo zero e sem movimentos. Peças de outras unidades devem continuar ocultas.

Os saldos, usuários e movimentos existentes são preservados. Renomear uma unidade não muda o acesso. Peças antigas ainda sem unidade atribuída mantêm o vínculo histórico para compatibilidade.
