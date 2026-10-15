# Versionamento e convenções dos contratos REST

Os quatro microsserviços de domínio expõem HTTP próprio, na rede interna. O API Gateway não publica esses caminhos. Ele só encaminha `/api/publico/*` ao BFF Público e `/api/gestao/*` ao BFF Gestão, como em [`docs/gateway-bffs.md`](../gateway-bffs.md).

Contrato normativo de cada serviço:

| Serviço | Contrato |
|---|---|
| org-service | [`docs/openapi/org-service.yaml`](../openapi/org-service.yaml) |
| audit-service | [`docs/openapi/audit-service.yaml`](../openapi/audit-service.yaml) |
| task-service | [`docs/openapi/task-service.yaml`](../openapi/task-service.yaml) |
| badge-service | [`docs/openapi/badge-service.yaml`](../openapi/badge-service.yaml) |

A conferência com os JSON dos BFFs está em [`docs/api/alinhamento-bff.md`](alinhamento-bff.md).

## Estratégia escolhida

Cada serviço versiona a URI com o prefixo **`/v1`**. Exemplo: `GET /v1/organizacoes/ong-123` no org-service.

O número muda só quando a alteração é incompatível: campo obrigatório removido ou renomeado, tipo alterado, significado de um código de status alterado, ou recurso removido. Inclusão de campo opcional, de query param opcional ou de novo link HATEOAS permanece em `/v1`.

A versão nova convive com a anterior. O BFF migra as chamadas internas e só então o `/v1` deixa de ser atendido. Não há reescrita silenciosa de `/v1` para `/v2`.

### Por que a versão fica no caminho

O gateway e os BFFs já roteiam por caminho (`/api/publico/*` e `/api/gestao/*`). Colocar `/v1` na URI do serviço deixa a versão visível no log, no `X-Correlation-ID` e no `href` do HATEOAS, sem depender de um cabeçalho que um cliente esqueça.

Duas alternativas foram descartadas:

- **Cabeçalho** (`Accept-Version` ou semelhante). Some em favoritos, em cache intermediário e no link de navegação. O recurso HATEOAS deixaria de identificar a versão que o cliente deve chamar.
- **Media type versionado** (`application/vnd.ongsec.v1+json`). Exige que todo cliente monte o `Accept` certo e complica o exemplo público do selo, que precisa ser JSON comum para o BFF Público devolver o corpo já combinado com o gateway.

O prefixo `/api/gestao` e `/api/publico` não é a versão do microsserviço. É o roteamento do gateway para o BFF. Os BFFs desta etapa mantêm as rotas já publicadas, sem segmento `/v1`, porque o contrato externo estável são os dois JSON de selo. A versão evolui atrás do BFF, nos serviços.

## Verbos e recursos

O recurso é o substantivo (`organizacoes`, `diagnosticos`, `tarefas`, `selos`, `solicitacoes`). O verbo HTTP é o método, não parte do nome, com uma exceção controlada: transição de negócio que não substitui o documento inteiro usa `POST` num sub-recurso de ação.

| Situação | Método | Exemplo |
|---|---|---|
| Leitura | `GET` | `GET /v1/organizacoes/ong-123` |
| Criação | `POST` | `POST /v1/organizacoes` |
| Substituição integral de um conjunto | `PUT` | `PUT /v1/diagnosticos/{id}/respostas` |
| Alteração parcial | `PATCH` | `PATCH /v1/organizacoes/{ongId}` |
| Remoção | `DELETE` | `DELETE /v1/sessoes/atual` |
| Transição de estado | `POST` | `POST /v1/diagnosticos/{id}/conclusao` |

`PUT` no diagnóstico inteiro obrigaria o cliente a reenviar pergunta, score e status juntos. Concluir, revogar, reabrir e compensar são ações. A idempotência dessas ações fica no cabeçalho `Idempotency-Key`, não no uso de `PUT`.

`GET` não tem corpo e não altera estado. `POST` de criação devolve `201` e o cabeçalho `Location`. Início da solicitação de selo devolve `202`, porque a emissão continua na SAGA e o estado final não está pronto na mesma resposta.

## Códigos de status

Todos os serviços usam a mesma tabela. O corpo de erro é `application/problem+json` (RFC 7807), com `type`, `title`, `status` e `detail`.

| Código | Quando |
|---|---|
| `200` | Leitura ou transição concluída, com corpo do recurso |
| `201` | Recurso criado |
| `202` | Solicitação de selo aceita; a SAGA ainda não terminou |
| `204` | Sessão encerrada, sem corpo |
| `400` | JSON inválido ou campo obrigatório ausente |
| `401` | JWT ausente ou inválido |
| `403` | JWT válido, mas o usuário não administra aquela ONG |
| `404` | Identificador inexistente |
| `409` | Conflito com o estado atual (CNPJ duplicado, selo já revogado, plano já aberto) |
| `422` | JSON válido, regra de negócio recusada (questionário incompleto, tarefa ainda pendente) |

`401` de usuário do Painel Web de Gestão continua sendo decidido no gateway, antes do BFF. Os serviços repetem `401` porque também recebem chamada direta do BFF e não confiam só na borda. A consulta pública de selo é anônima no gateway (`GET /api/publico/selos/{ongId}`); o BFF Público chama o modelo de leitura do badge-service pela rede interna, e esse `GET` interno não é publicado no gateway.

## HATEOAS

Dois recursos carregam `_links` de navegação:

- `Tarefa` no task-service (`self`, `plano`, `concluir`, `reabrir`)
- `SolicitacaoSelo` no badge-service (`self`, `consulta_publica`, `certificacao`, `revogar`)

O `href` aponta para o serviço que executa a ação, com o `/v1` incluso. O BFF Gestão não repassa esses `href` crus ao navegador. Ele monta os links do gateway já documentados (`/api/gestao/...`). O mapa está no documento de alinhamento. Assim o cliente externo não recebe endereço interno do cluster, e o recurso de domínio continua navegável para o BFF.

## Correlação e idempotência

Toda requisição aceita `X-Correlation-ID`. Se o gateway ou o BFF não enviar, o serviço gera um. O mesmo valor volta no cabeçalho da resposta e acompanha os eventos `DIAGNOSTICO_CONCLUIDO`, `TAREFAS_REMEDIADAS` e `SELO_GERADO`.

`POST` de plano, conclusão, reabertura, solicitação, compensação e revogação exige `Idempotency-Key`. Repetir a mesma chave com o mesmo corpo devolve a mesma resposta e não aplica a transição duas vezes. Isso cobre o retry do orquestrador da SAGA sem duplicar tarefa nem selo.

## O que estes contratos não decidem

A modelagem da SAGA (caminho feliz, falha e compensações) usa estes endpoints, mas o diagrama de sequência fica no documento de SAGA. A tecnologia de cada banco, o outbox e a defasagem do modelo de leitura ficam no documento de persistência e CQRS. Os YAML apenas separam, no badge-service, o `POST` da solicitação (escrita) do `GET /v1/consulta/organizacoes/{ongId}` (leitura pública).
