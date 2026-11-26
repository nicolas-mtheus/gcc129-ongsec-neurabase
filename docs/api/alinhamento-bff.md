# Alinhamento dos contratos com os BFFs

Os JSON abaixo são os mesmos de [`docs/gateway-bffs.md`](../gateway-bffs.md). Os contratos em `docs/openapi/` não substituem essas rotas do gateway: o BFF monta a resposta externa a partir dos serviços.

## BFF Público

Rota no gateway: `GET /api/publico/selos/ong-123`

Chamada interna: `GET http://badge-service:8080/v1/consulta/organizacoes/ong-123`

O BFF devolve o corpo sem acrescentar campo. A rota interna não aparece no gateway, então o limite de taxa e o anonimato continuam valendo só na borda.

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

Esse objeto é o schema `ConsultaPublica` em `docs/openapi/badge-service.yaml`.

## BFF Gestão

Rota no gateway: `GET /api/gestao/selos/ong-123/detalhes`

O BFF não lê um único serviço. Cada campo tem uma origem:

| Campo no BFF Gestão | Origem |
|---|---|
| `id_selo`, `status_conformidade`, `historico_saga_emissao` | `GET /v1/organizacoes/ong-123/certificacao` no badge-service |
| `score_auditoria` | `score` do diagnóstico `CONCLUIDO` em `GET /v1/organizacoes/ong-123/diagnosticos` no audit-service. No exemplo, `92` |
| `instituicao.ong_id`, `instituicao.responsavel_legal` | `GET /v1/organizacoes/ong-123` no org-service. No exemplo, `Maria da Silva` |
| `tarefas_pendentes` | `GET /v1/organizacoes/ong-123/plano-atual` no task-service. No exemplo, `0` |
| `nome_instituicao` da consulta pública | Projeção de leitura do badge-service. A cópia do nome e a defasagem aceitável ficam no documento de CQRS |

Corpo externo já combinado com o gateway:

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

Os nomes `DIAGNOSTICO_CONCLUIDO`, `TAREFAS_REMEDIADAS` e `SELO_GERADO` são os mesmos do schema `EventoSaga` no badge-service. O audit-service produz o primeiro ao concluir o diagnóstico; o task-service produz o segundo quando `tarefas_pendentes` chega a zero.

## HATEOAS: link interno e link do gateway

O navegador não recebe `href` de `http://badge-service`. O BFF Gestão reescreve a navegação:

| Link no BFF Gestão | Chamada interna |
|---|---|
| `self` → `/api/gestao/selos/ong-123/detalhes` | Composição descrita na tabela acima. Não existe um GET único no badge-service com esse caminho |
| `auditoria` → `GET /api/gestao/ong-123/auditoria` | `GET /v1/organizacoes/ong-123/diagnosticos` no audit-service |
| `revogar_selo` → `POST /api/gestao/selos/ong-123/revogar` | `POST /v1/selos/CERT-2026-998/revogacao` no badge-service |

No domínio, o HATEOAS está em dois recursos:

- `GET /v1/tarefas/tar-77` no `task-service`, com `self`, `plano`, `concluir` e `reabrir`
- `GET /v1/solicitacoes/sol-998` no `saga-orchestrator`, com `self`, `consulta_publica`, `certificacao` e `revogar`

`revogar.href` na solicitação (`/v1/selos/CERT-2026-998/revogacao`, método `POST`) é o que o BFF publica como `revogar_selo`. O identificador do caminho externo é `ong-123` porque o cliente do painel conhece a ONG, não o id interno do selo. O BFF faz essa tradução.

---

## Endpoints de IA no BFF Gestão (`/api/gestao/ia/*`)

O BFF Gestão expõe as funcionalidades do [`ai-service`](../openapi/ai-service.yaml) sob o prefixo autenticado `/api/gestao/ia/*` com controle de acesso por perfil (`GESTOR` vs `ADMIN`):

| Rota externa no Gateway/BFF | Método | Perfil exigido | Chamada interna (`ai-service`) | Observação |
|---|---|---|---|---|
| `/api/gestao/ia/consultoria` | `POST` | `GESTOR` ou `ADMIN` (dono da ONG) | `POST /v1/ia/consultoria` | Valida escopo LGPD/segurança (`FORA_DO_ESCOPO`). Apenas `ADMIN` pode enviar `simular_falha_llm: true` (`403` para `GESTOR`). |
| `/api/gestao/ia/comparar-rag` | `POST` | `ADMIN` (`403` para `GESTOR`) | `POST /v1/ia/comparar-rag` | Executa a pergunta com e sem recuperação RAG para demonstração e análise técnica. |
| `/api/gestao/ia/metricas` | `GET` | `ADMIN` (`403` para `GESTOR`) | `GET /v1/ia/metricas` | Retorna latências medidas, cache hits/misses, retries, fallbacks e estimativa de custo. |
| `/api/gestao/ia/circuit-breaker` | `POST` | `ADMIN` (`403` para `GESTOR`) | `POST /v1/ia/circuit-breaker` | Controla estado do Circuit Breaker (`abrir`, `fechar`) ou limpa o cache (`limpar_cache`). |

Além das rotas explícitas `/api/gestao/ia/*`, os fluxos de diagnóstico e plano de ação do BFF consomem internamente o `ai-service`:

- `POST /api/gestao/{ong_id}/diagnosticos/gerar-hibrido` → chama `POST /v1/ia/diagnostico/perguntas-dinamicas` para gerar 5 perguntas dinâmicas personalizadas pelo perfil da ONG.
- `POST /api/gestao/{ong_id}/diagnosticos/responder` → chama `POST /v1/ia/plano-acao/personalizar` para adaptar as ações corretivas de itens marcados como `NAO` à realidade da instituição.

### Exemplos de Contrato (`/api/gestao/ia/*`)

**`POST /api/gestao/ia/consultoria`**

```json
// Request
{
  "ong_id": "ong-123",
  "pergunta": "Segundo a Resolução CD/ANPD nº 2/2022, nossa ONG precisa de DPO formal?",
  "usar_rag": true,
  "usar_cache": true,
  "simular_falha_llm": false
}
```

```json
// Response (200 OK)
{
  "ong_id": "ong-123",
  "pergunta": "Segundo a Resolução CD/ANPD nº 2/2022, nossa ONG precisa de DPO formal?",
  "usar_rag": true,
  "modelo": "deephat:latest",
  "resposta": "...",
  "modo_operacao": "OLLAMA_DEEPHAT",
  "cache_hit": false,
  "retries": 0,
  "latencia_ms": 3420.5,
  "circuit_breaker": { "estado": "CLOSED", "falhas_consecutivas": 0 },
  "rag_fontes": [],
  "dados_tools": {}
}
```

**`POST /api/gestao/ia/circuit-breaker`** (`ADMIN`)

```json
// Request
{ "acao": "abrir" }

// Response (200 OK)
{
  "acao_executada": "abrir",
  "circuit_breaker": { "estado": "OPEN", "falhas_consecutivas": 0, "forcado_aberto": true },
  "cache": { "hits": 1, "misses": 2 }
}
```
