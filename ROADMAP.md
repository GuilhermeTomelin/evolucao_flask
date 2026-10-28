# Próximas etapas — planejamento, ainda não implementado

A etapa A está implementada: revisão da base, cadastro pendente, aprovação,
rejeição, bloqueio e papéis. Este documento registra as escolhas solicitadas
para B a F; não afirma que elas já funcionam.

Em todas as etapas: preservar Flask, SQLite, Streamlit e histórico; autorização
no Flask; migrações revisadas e testadas com dados em SQLite temporário; nunca
migrar o banco principal automaticamente. Não publicar nem integrar pagamentos reais.

## B. Regras e confirmação de empréstimos/devoluções

- Separar solicitação, entrega física, pedido de devolução e recebimento.
  O prazo só começa quando atendente/administrador confirma a entrega.
  O pedido de devolução não libera o exemplar; somente o recebimento libera.
- Registrar responsável e horário de cada confirmação. Impedir pedidos duplicados
  e manter a restrição de apenas um empréstimo ativo por exemplar.
- Painel administrativo: prazo inicial de 14 dias, limite de 3 empréstimos por
  leitor e 1 renovação. Esses limites configuráveis ainda não existem na etapa A.
- Salvar no empréstimo uma cópia das regras aplicadas; mudanças posteriores
  não devem recalcular obrigações antigas.
- Multas somente simuladas, inicialmente desativadas. Administrador precisa
  definir diária e teto em centavos inteiros antes de ativar.
- Proposta de cálculo a implementar/testar: horários persistidos em UTC e
  apresentados em America/Sao_Paulo; após due_at, cada período de 24 horas
  iniciado conta como um dia, limitado pelo teto. O recebimento encerra a contagem.
  A interface deve explicar essa regra antes de ativar multas.
- Registrar quitação simulada e isenção, responsável e justificativa; sem pagamento.
- Atraso ativo ou multa pendente bloqueia novas retiradas e renovações, mas
  permite consultas e devoluções. Bloqueio administrativo de conta continua
  impedindo login; a equipe pode receber seus exemplares.
- Renovação não pode prejudicar uma fila existente (integração com C).

Aceite: testes de transição, simultaneidade, autoria de confirmações, limite,
renovação, fronteiras de prazo, teto, snapshots de regras e permissão por papel.

## C. Reservas e fila de 48 horas

- Fila por livro, ordem de entrada, sem reserva ativa duplicada do mesmo leitor.
- Atribuir um exemplar livre ao primeiro elegível e mantê-lo reservado por 48 horas.
  Outro leitor não pode emprestá-lo durante a prioridade.
- Prazo persistido em UTC. Ao atingir exatamente expires_at, a prioridade expira.
- Cancelamento e bloqueio de usuário liberam a oportunidade e avançam a fila.
- Planejar um comando de manutenção idempotente, também chamado pelas operações
  relevantes da API. Documentar execução manual e agendamento local no Windows.
- O avanço não dependerá de uma tela aberta. Não haverá alegação de serviço
  automático enquanto um agendamento real não estiver configurado.

Aceite: relógio controlado em testes, limites de 48 horas, ordem, cancelamento,
bloqueio, disputas concorrentes e renovação com fila.

## D. QR Code e etiquetas

- Gerar QR e etiqueta imprimível por exemplar, com identificador ou link;
  nunca incluir credenciais, senhas ou cookies.
- Atendente identifica exemplar por leitor que digita o código ou entrada manual.
  Avaliar câmera compatível com Streamlit sem torná-la obrigatória.
- Ler o código apenas consulta dados; entrega ou devolução exige confirmação
  separada e autorização da API.

Aceite: etiqueta legível/imprimível, QR válido, alternativa manual e leitura sem
efeitos colaterais. Não instalar bibliotecas de QR antes desta etapa.

## E. Loja simulada

- Estoque de venda separado dos exemplares de empréstimo.
- Carrinho e pedidos, sempre com aviso “Compra simulada”; sem cartão, dados
  bancários, cobrança real ou provedor de pagamentos.
- Preços e totais calculados no backend em centavos. Itens guardam o preço no pedido.
- Reserva transacional de estoque ao criar pedido pendente; confirmação final
  pelo administrador; cancelamento/expiração devolve a reserva uma única vez.
- Proposta de expiração: 24 horas para pedido pendente, validada no servidor.
  Documentar um comando de manutenção e seu agendamento local.
- Chave de idempotência por conta evita duplicação por reenvio; operações
  condicionais no banco impedem estoque negativo e vendas acima do estoque.

Aceite: total adulterado pelo cliente, estoque concorrente, reenvios, confirmação,
cancelamento/expiração repetidos e acesso somente aos próprios pedidos.

## F. Acervo, visual, extras e relatórios (por último)

- Editar livros e exemplares na interface; categoria, ISBN opcional, capa e
  localização física. Não buscar imagens/dados externos automaticamente.
- Capa padrão local, desativação de registros com histórico e disponibilidade
  calculada. A edição de livros por API já existe; esses novos campos ainda não.
- Aparência de livraria: azul, fundo claro, capas, legibilidade, filtros e detalhes.
  Navegação por áreas, estados vazios, confirmação de ações e formulários que
  conservam valores após erros.
- Leitor: catálogo, empréstimos, reservas, carrinho/pedidos e conta.
  Atendente: solicitações, entrega/recebimento e códigos.
  Administrador: acervo, usuários, configurações e relatórios.
- Favoritos; uma avaliação editável por leitor/livro; avisos internos sobre
  prazos, reservas e pedidos.
- Relatórios de empréstimos, atrasos, disponibilidade e vendas simuladas.
- Registro de ações administrativas sem dados secretos.
- CSV: modelo, prévia, validação e relatório de erros. Política proposta:
  rejeitar ISBN duplicado quando informado; sem ISBN, apontar título/autor
  coincidentes para revisão explícita, sem sobrescrever registros automaticamente.
- Exportações administrativas somente de campos autorizados, nunca senhas,
  hashes ou cookies.

Aceite: testes de permissão, validação de CSV, duplicidades, exportação sem
segredos, isolamento de sessão e verificação visual no navegador.

## Limite de escopo

Publicação na internet e pagamentos reais não são entregas destas etapas.
A preparação para produção exigiria uma avaliação própria.
