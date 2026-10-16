# Arquitetura de Borda: API Gateway e BFFs

Este documento detalha a camada de borda do **ONGSec (NeuraBase)**, responsável por centralizar o acesso externo, proteger os microsserviços internos e otimizar a entrega de dados para os diferentes consumidores da plataforma: o **Painel Web de Gestão** (gestores de ONGs e auditores) e o **App/Portal Mobile Público** (doadores e público geral).

## 1. API Gateway: Regras de Roteamento e Responsabilidades

O API Gateway atua como o ponto único de entrada (*Single Point of Entry*) para todo o tráfego externo. Ele não contém regras de negócio relacionadas à emissão do selo LGPD ou à orquestração da SAGA, funcionando exclusivamente como proxy reverso inteligente, roteador de contexto e barreira de segurança perimetral.

### 1.1 Fluxo de Requisições na Borda

```mermaid
graph TD
    %% Clientes Externos
    App[📱 App/Portal Mobile Público]
    Web[💻 Painel Web de Gestão]

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

    %% Roteamento Público (Sem JWT)
    App -->|/api/publico/*| Gateway
    Gateway -->|Acesso Público (Sem JWT, Rate Limiting)| BFF_Pub
    BFF_Pub -.->|Consulta CQRS Leve| MS_Badge

    %% Roteamento Gestão (Protegido por JWT)
    Web -->|/api/gestao/*| Gateway
    Gateway -->|Valida Token JWT & Roteia| BFF_Gest
    BFF_Gest -.->|Agrega Dados| MS_Audit
    BFF_Gest -.->|Agrega Dados| MS_Task
    BFF_Gest -.->|Agrega Dados| MS_Org
    BFF_Gest -.->|Agrega Dados| MS_Badge
```

### 1.2 Responsabilidades e Regras Principais

-   **Roteamento Dinâmico por Contexto:** Direciona as requisições para o BFF correspondente com base no *path* da URI:
    -   Rotas `/api/publico/*` (originadas pelo **App/Portal Mobile Público**) são direcionadas para o **BFF Público**.
    -   Rotas `/api/gestao/*` (originadas pelo **Painel Web de Gestão**) são direcionadas para o **BFF Gestão**.

-   **Tratamento de Autenticação Diferenciado por Rota:**
    -   **Rotas Públicas (`/api/publico/*`):** São rotas **abertas e anônimas**. Como o **App/Portal Mobile Público** é destinado a doadores e ao público geral para verificação da idoneidade e conformidade de uma ONG, **não há exigência de autenticação ou token JWT**. A proteção na borda é garantida por **Rate Limiting** agressivo por IP (protegendo contra DoS, abusos e raspagem de dados) e sanitização de parâmetros de consulta.
    -   **Rotas de Gestão (`/api/gestao/*`):** São rotas protegidas que exigem obrigatoriamente token JWT válido no cabeçalho `Authorization: Bearer <token>`, gerado pelo serviço de autenticação (`org-service`).

-   **Offloading de Autenticação Seletiva (Apenas na Gestão):** O Gateway intercepta as requisições administrativas (`/api/gestao/*`) e valida a assinatura digital e o prazo de expiração do JWT. Caso o token esteja ausente, corrompido ou expirado, o Gateway responde diretamente na borda com `401 Unauthorized`, impedindo que requisições inválidas consumam recursos dos microsserviços internos.

-   **Security by Design (Defesa de Borda):** Centraliza a terminação TLS/HTTPS, impõe políticas de Rate Limiting por rota/IP e realiza a sanitização de cabeçalhos HTTP.

-   **Rastreabilidade Distribuída (Tracing):** Injeta o cabeçalho `X-Correlation-ID` em todas as requisições de entrada (tanto públicas quanto autenticadas). Esse identificador é propagado para os BFFs e microsserviços, permitindo que os logs sejam rastreados de ponta a ponta durante auditorias e na execução da SAGA de certificação.

---

## 2. O Padrão BFF (Backend for Frontend)

Para evitar os problemas de *over-fetching* (trafegar dados desnecessários) e *under-fetching* (forçar o cliente a fazer múltiplas requisições), implementamos dois BFFs distintos. Eles orquestram as chamadas para os microsserviços internos (via contratos REST) e formatam a resposta sob medida para a tela de cada cliente.

### 2.1 BFF Público (Foco no App/Portal Mobile Público e Doadores)

-   **Objetivo:** Atender ao **App/Portal Mobile Público**, utilizado por doadores para verificar a validade do selo de conformidade de uma ONG de forma ágil e sem necessidade de autenticação.
-   **Autenticação:** Acesso aberto (sem JWT), protegido por Rate Limiting na borda.
-   **Justificativa Arquitetural:** Redes móveis oscilam e o foco do cidadão é apenas a verificação de reputação. O BFF Público faz chamadas internas diretas ao modelo de leitura (CQRS) do `badge-service`, descarta metadados sensíveis de auditoria e entrega uma resposta extremamente enxuta, consumindo pouca banda e garantindo alta disponibilidade.

### 2.2 BFF Gestão (Foco no Painel Web de Gestão e Auditores)

-   **Objetivo:** Atender ao **Painel Web de Gestão** (SPA), utilizado por gestores (ex.: diretoria da ONG) e auditores da plataforma.
-   **Autenticação:** Restrita (autenticação obrigatória via JWT).
-   **Justificativa Arquitetural:** O painel de gestão exige uma visão ampla e detalhada. Este BFF compõe dados de múltiplos microsserviços (agrega dados do `org-service`, `audit-service` e `task-service`), lida com o detalhamento do plano de ação, expõe o histórico de compensações da SAGA e fornece links HATEOAS para facilitar a navegação e a resolução de vulnerabilidades.

---

## 3. Comparativo de Respostas: Consulta de Status do Selo

Para deixar explícita a diferença de responsabilidades e justificar a separação dos BFFs na arquitetura, abaixo demonstramos o comportamento de cada BFF ao receber uma requisição de consulta do mesmo selo.

### 3.1 Resposta do BFF Público (App/Portal Mobile Público)

**Rota de Entrada no Gateway:** `GET /api/publico/selos/ong-123`  
**Autenticação:** Nenhuma (Pública / Sem JWT)  
**Proteção de Borda:** Rate Limiting por IP  

O BFF orquestra a chamada, consulta apenas a projeção CQRS e retorna um *payload* leve, ocultando detalhes técnicos e vulnerabilidades internas da ONG.

```json
{
  "id_selo": "CERT-2026-998",
  "ong_id": "ong-123",
  "nome_instituicao": "Associação Cuidar",
  "status_conformidade": "ATIVO",
  "emitido_em": "2026-10-10T14:00:00Z",
  "mensagem": "Instituição verificada e em conformidade com as diretrizes da LGPD."
}
```

### 3.2 Resposta do BFF Gestão (Painel Web de Gestão)

**Rota de Entrada no Gateway:** `GET /api/gestao/selos/ong-123/detalhes`  
**Autenticação:** Obrigatória (`Authorization: Bearer <JWT>`)  
**Proteção de Borda:** Validação de Token JWT + Rate Limiting  

O BFF Gestão compõe dados dos microsserviços, entregando o histórico de eventos da SAGA, dados cruzados das tarefas de remediação e contratos HATEOAS para ações administrativas.

```json
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
