# Regras de Negócio e Arquitetura de Certificação do ONGSec

## 1. Ciclo de Vida da Certificação Digital LGPD
Na plataforma ONGSec, a emissão do Selo Digital de Conformidade segue pré-condições auditáveis distribuídas entre os serviços:
1. **Cadastro (`org-service`):** A instituição deve estar cadastrada com CNPJ válido, razão social e responsável legal identificado.
2. **Diagnóstico (`audit-service`):** O questionário oficial `q-lgpd-ig1` deve estar com status `CONCLUIDO` e possuir um `score` calculado. Para elegibilidade plena de certificação recomenda-se **score mínimo de 80%**.
3. **Plano de Remediação (`task-service`):** Todas as tarefas corretivas geradas para a instituição (como elaboração de política de privacidade e ativação de 2FA) devem estar com status `CONCLUIDA`, resultando em **`tarefas_pendentes = 0`**.

## 2. Orquestração SAGA e Compensações
A solicitação do selo é coordenada pelo serviço dedicado **`saga-orchestrator`** (`POST /v1/solicitacoes`, resposta `202 Accepted`), que valida `audit-service` e `task-service` e aciona o `badge-service` (`POST /v1/selos`).
- Se ocorrer falha na emissão ou se uma não conformidade for detectada posteriormente, a SAGA executa **compensação na ordem inversa**: revoga o selo ativo (`REVOGADO`), marca a solicitação como `COMPENSADA` e solicita ao `task-service` a **reabertura das tarefas** (`REABERTA`, voltando `tarefas_pendentes > 0`).
- O `score` do diagnóstico no `audit-service` **nunca é apagado** durante a compensação, pois representa um fato histórico de medição.

## 3. Consulta Pública CQRS e Padrão Outbox
O `badge-service` grava a emissão/revogação do selo e o evento (`SELO_GERADO` ou `SELO_REVOGADO`) na tabela `outbox` na mesma transação local, evitando *Dual Write*. Um projetor atualiza a tabela desnormalizada `selo_publico` (CQRS), permitindo consultas públicas anônimas instantâneas por doadores via `GET /api/publico/selos/{ongId}` com defasagem máxima aceitável de 2 segundos para revogação e 5 segundos para emissão.

