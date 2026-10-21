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

- `GET /v1/tarefas/tar-77` no task-service, com `self`, `plano`, `concluir` e `reabrir`
- `GET /v1/solicitacoes/sol-998` no badge-service, com `self`, `consulta_publica`, `certificacao` e `revogar`

`revogar.href` na solicitação (`/v1/selos/CERT-2026-998/revogacao`, método `POST`) é o que o BFF publica como `revogar_selo`. O identificador do caminho externo é `ong-123` porque o cliente do painel conhece a ONG, não o id interno do selo. O BFF faz essa tradução.
