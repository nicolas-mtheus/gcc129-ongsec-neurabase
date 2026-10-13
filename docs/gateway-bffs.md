# Arquitetura de Borda: API Gateway e BFFs

Este documento detalha a camada de borda do **ONGSec (NeuraBase)**,
responsável por centralizar o acesso externo, proteger os microsserviços
internos e otimizar a entrega de dados para os diferentes consumidores
da plataforma (gestores de ONGs e doadores/público geral).

## 1. API Gateway: Regras de Roteamento e Responsabilidades

O API Gateway atua como o ponto único de entrada (*Single Point of
Entry*) para todo o tráfego externo. Ele não contém regras de negócio
relacionadas à emissão do selo LGPD ou à orquestração da SAGA,
funcionando exclusivamente como um proxy reverso inteligente e barreira
de segurança.

**Responsabilidades e Regras Principais:**

-   **Roteamento Dinâmico por Contexto:** Direciona as requisições para
    o BFF correspondente com base no *path* da URI.
    -   Rotas `/api/publico/*` (ou `/api/mobile/*`) são direcionadas
        para o **BFF Público**.
    -   Rotas `/api/gestao/*` são direcionadas para o **BFF Gestão**.
-   **Security by Design (Defesa de Borda):** Centraliza a terminação
    TLS, impõe políticas rigorosas de *Rate Limiting* (essencial para
    evitar abusos no portal público de consulta de selos) e realiza a
    sanitização de cabeçalhos HTTP.
-   **Offloading de Autenticação:** Valida a assinatura e a expiração
    dos tokens JWT antes de repassar a requisição para a rede interna.
    Requisições inválidas recebem um `401 Unauthorized` diretamente na
    borda, poupando recursos dos microsserviços do cluster.
-   **Rastreabilidade Distribuída (Tracing):** Injeta um cabeçalho
    `X-Correlation-ID` em cada requisição de entrada. Esse ID é
    repassado para os BFFs e microsserviços, garantindo que os logs
    possam ser rastreados de ponta a ponta durante a execução da SAGA de
    certificação.

## 2. O Padrão BFF (Backend for Frontend)

Para evitar os problemas de *over-fetching* (trafegar dados
desnecessários) e *under-fetching* (forçar o cliente a fazer múltiplas
requisições), implementamos dois BFFs distintos. Eles orquestram as
chamadas para os microsserviços internos (via contratos REST) e formatam
a resposta sob medida para a tela de cada cliente.

### 2.1 BFF Público / Mobile (Foco no Doador e Sociedade)

-   **Objetivo:** Atender ao aplicativo/portal público utilizado por
    doadores para verificar a validade do selo de conformidade de uma
    ONG.
-   **Justificativa Arquitetural:** Redes móveis oscilam e o foco do
    cidadão é apenas a verificação de reputação. O BFF Público faz
    chamadas internas diretas ao modelo de leitura (CQRS) do
    `badge-service`, descarta metadados sensíveis de auditoria e entrega
    uma resposta extremamente enxuta, consumindo pouca banda e
    garantindo alta disponibilidade.

### 2.2 BFF Gestão / Backoffice (Foco na ONG e Auditores)

-   **Objetivo:** Atender ao painel administrativo (SPA) utilizado por
    gestores (ex.: diretoria da ONG) e auditores da plataforma.
-   **Justificativa Arquitetural:** O painel de gestão exige uma visão
    ampla e detalhada. Este BFF compõe dados de múltiplos microsserviços
    (agrega dados do `org-service`, `audit-service` e `task-service`),
    lida com o detalhamento do plano de ação, expõe o histórico de
    compensações da SAGA e fornece links HATEOAS para facilitar a
    navegação e a resolução de vulnerabilidades.

------------------------------------------------------------------------

## 3. Comparativo de Respostas: Consulta de Status do Selo

Para deixar explícita a diferença de responsabilidades e justificar a
separação dos BFFs na arquitetura, abaixo demonstramos o comportamento
de cada BFF ao receber uma requisição de consulta do mesmo selo.

### 3.1 Resposta do BFF Público

**Rota de Entrada no Gateway:** `GET /api/publico/selos/ong-123`

O BFF orquestra a chamada, consulta apenas a projeção CQRS e retorna um
*payload* leve, ocultando detalhes técnicos e vulnerabilidades internas
da ONG.

``` json
{
  "id_selo": "CERT-2026-998",
  "ong_id": "ong-123",
  "nome_instituicao": "Associação Cuidar",
  "status_conformidade": "ATIVO",
  "emitido_em": "2026-10-10T14:00:00Z",
  "mensagem": "Instituição verificada e em conformidade com as diretrizes da LGPD."
}
```

### 3.2 Resposta do BFF Gestão

**Rota de Entrada no Gateway:** `GET /api/gestao/selos/ong-123/detalhes`

O BFF Gestão compõe dados dos microsserviços, entregando o histórico de
eventos da SAGA, dados cruzados das tarefas de remediação e contratos
HATEOAS para ações administrativas.

``` json
{
  "id_selo": "CERT-2026-998",
  "status_conformidade": "ATIVO",
  "score_auditoria": 92,
  "instituicao": {
    "ong_id": "ong-123",
    "responsavel_legal": "Maria da Silva"
  },
  "historico_saga_emissao": [
    {
      "evento": "DIAGNOSTICO_CONCLUIDO",
      "servico": "audit-service",
      "sucesso": true
    },
    {
      "evento": "TAREFAS_REMEDIADAS",
      "servico": "task-service",
      "sucesso": true
    },
    {
      "evento": "SELO_GERADO",
      "servico": "badge-service",
      "sucesso": true
    }
  ],
  "tarefas_pendentes": 0,
  "_links": {
    "self": {
      "href": "/api/gestao/selos/ong-123/detalhes"
    },
    "auditoria": {
      "href": "/api/gestao/ong-123/auditoria"
    },
    "revogar_selo": {
      "href": "/api/gestao/selos/ong-123/revogar",
      "method": "POST"
    }
  }
}
```

# Arquitetura de Borda: API Gateway e BFFs

Este documento detalha a camada de borda do **ONGSec (NeuraBase)**, responsável por centralizar o acesso externo, proteger os microsserviços internos e otimizar a entrega de dados para os diferentes consumidores da plataforma (gestores de ONGs e doadores/público geral).

### Fluxo de Requisições na Borda

```mermaid
graph TD
    %% Clientes Externos
    App[📱 App Mobile / Portal Público]
    Web[💻 Painel Web / Backoffice]

    %% Borda
    Gateway{API Gateway}

    %% BFFs
    BFF_Pub[BFF Público]
    BFF_Gest[BFF Gestão]

    %% Rede Interna (Microsserviços)
    subgraph RedeInterna [Rede Interna Isolada]
        MS_Badge[Badge Service]
        MS_Audit[Audit Service]
        MS_Task[Task Service]
        MS_Org[Org Service]
    end

    %% Roteamento Público
    App -->|/api/publico/*| Gateway
    Gateway -->|Valida Token & Roteia| BFF_Pub
    BFF_Pub -.->|Consulta CQRS Leve| MS_Badge

    %% Roteamento Gestão
    Web -->|/api/gestao/*| Gateway
    Gateway -->|Valida Token & Roteia| BFF_Gest
    BFF_Gest -.->|Agrega Dados| MS_Audit
    BFF_Gest -.->|Agrega Dados| MS_Task
    BFF_Gest -.->|Agrega Dados| MS_Org
    BFF_Gest -.->|Agrega Dados| MS_Badge
