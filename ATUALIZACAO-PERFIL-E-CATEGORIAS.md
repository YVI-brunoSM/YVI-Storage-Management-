# Atualização — 29/09/2026

- Registrar entrada/saída: busca integrada ao campo Peça, por nome ou SKU; sugestões, saldo, navegação por teclado e seleção obrigatória. A barra de busca separada foi removida.
- Categorias: 12 ícones vetoriais selecionáveis em Novo cadastro e Editar categoria; categorias existentes recebem o desenho correspondente ou uma pasta como padrão.
- Meu perfil: cada usuário pode enviar e remover sua própria foto. Fotos também aparecem na lista administrativa de usuários. A API restringe alterações à conta autenticada.
- Fotos são validadas como JPEG/PNG/WebP (até 2 MB e 16 megapixels), recortadas ao centro, reduzidas a 256 × 256 e regravadas como JPEG sem metadados. Armazenamento no Postgres, com migração 003_profile_photo, sem dependência do disco efêmero do servidor.
- Guia DEPLOY-RAILWAY.md: publicação, banco, variáveis, migrações, primeiro administrador, domínio HTTPS e backups.

Validação: 36 testes Python passaram em 40,47 segundos; 5 testes do cliente HTTP passaram; sintaxe dos módulos JavaScript conferida. Incluem autorização, CSRF, rejeição de imagens inválidas/grandes, leitura/removal de foto, miniatura sem metadados e persistência dos ícones. Biblioteca Pillow fixada em 12.3.0.

Migração aplicada ao banco local sem alterar estoques ou movimentos. O servidor local usa a porta 5088. A conferência visual autenticada ficou pendente do login manual escolhido pelo usuário; o deploy Railway e o teste do container Linux ainda não foram realizados.

Os relatórios anteriores de carga e dependências descrevem a versão e a data neles registradas; não constituem uma nova auditoria desta dependência adicional.
