# Novo modelo de notificação de estoque

O assunto passa a ser `YVI GESTÃO - REPOR <nome da peça>` ou `YVI GESTÃO - ESGOTADO <nome da peça>`.

O email contém três blocos separados:

1. **Dados da peça:** nome, código, categoria, localização e estoque mínimo da unidade.
2. **Estoque Atual:** saldo da unidade após o registro que gerou o alerta, destacado visualmente. Uma nota identifica esse saldo como a posição no momento do registro.
3. **Última movimentação:** data e hora de São Paulo, ocorrência, quantidade movimentada, unidade e responsável. Observações aparecem quando informadas.

O saldo anterior foi retirado do email para evitar misturar os estados antes e depois da operação. Quantidades usam a formatação brasileira, sem casas decimais desnecessárias: `1.000 un`, `2 un` e `1.234,5 m`.

Alertas por cadastro, conferência ou alteração do estoque mínimo usam o título **Registro que gerou o alerta**, pois essas operações não devem ser apresentadas como movimentações. Em transferências, o campo **Unidade da movimentação** identifica a unidade cujo saldo gerou o alerta, sem chamar a origem de destino.

## Publicação no Railway

Atualize o código do serviço web e do serviço de envio de emails. Ambos precisam da mesma versão do projeto, incluindo `templates/emails/stock_alert.html`.

- Serviço web: mantenha o Start Command `gunicorn --config gunicorn.conf.py app:app`.
- Serviço de emails: mantenha o Start Command `python3 email_worker.py` e faça um novo deploy para carregar o modelo.
- Mantenha o Pre-deploy `python3 migrate.py` conforme a configuração existente. Esta alteração do email não acrescenta uma migração nem exige mudar credenciais Gmail.

Mensagens ainda na fila usarão o novo modelo quando processadas pela versão atualizada. Emails que já foram enviados permanecem como estavam.

O pacote também contém a atualização anterior de estoque por unidade. Se ela ainda não foi publicada, siga `ESTOQUE-POR-UNIDADE.md`, especialmente a distribuição dos saldos antigos em **Distribuir saldo** após a migração 008.
