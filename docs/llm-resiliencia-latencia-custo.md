# LLM como Serviço Distribuído: LangChain, Resiliência, Latência e Custo

Este documento detalha a integração do modelo local **`deephat:latest`** (via **Ollama**) no microsserviço [`backend/services/ai-service/`](../backend/services/ai-service/), cobrindo a composição com **LangChain**, os mecanismos de **resiliência distribuída**, a **latência medida** em execução real e a **estimativa de custo em escala**.

---

## 1. Propósito no Domínio e Composição com LangChain

O LLM não é um chatbot genérico: ele atua como **Consultor Virtual de Conformidade LGPD** integrado diretamente ao estado da ONG no sistema.

* **Chains (`app/chains.py`):** Composição declarativa via LCEL (`ChatPromptTemplate | ChatOllama | StrOutputParser`), separando o prompt fundamentado com RAG do prompt de controle sem RAG.
* **Tools integradas aos serviços reais (`app/tools.py`):**
  1. `consultar_perfil_ong`: consulta `org-service` (`GET /v1/organizacoes/{ongId}`) para obter nome institucional, CNPJ e responsável legal.
  2. `consultar_diagnostico_e_plano`: consulta `audit-service` (`score` e `status` do diagnóstico) e `task-service` (`plano_id`, `tarefas_pendentes` e lista de tarefas).
  3. `consultar_selo_publico_cqrs`: consulta a projeção pública CQRS no `badge-service` (`GET /v1/consulta/organizacoes/{ongId}`).

---

## 2. Mecanismos de Resiliência Implementados (`app/resilience.py`)

O provedor LLM (Ollama) é tratado como dependência remota falível, protegido por **4 mecanismos**:

1. **Cache por Chave Normalizada (`ResponseCache`):**
   - Chave gerada por `SHA-256(ong_id + pergunta_normalizada + usar_rag + hash_estado_tarefas_e_selo)` com TTL de **600 segundos**.
   - Se o estado das tarefas ou do selo da ONG mudar no sistema (por exemplo, após uma compensação da SAGA), a chave muda automaticamente e invalida a resposta antiga.
2. **Timeout + Política de Retry com Exponential Backoff:**
   - Timeout configurável por chamada (`LLM_TIMEOUT_SECONDS=60s`).
   - Em caso de falha transitória de rede ou provedor, realiza até `LLM_MAX_RETRIES=2` tentativas adicionais com *exponential backoff* (`0.4s` → `0.8s`).
3. **Circuit Breaker (`CLOSED` → `OPEN` → `HALF_OPEN`):**
   - Abre automaticamente após **2 falhas consecutivas** (`failure_threshold=2`) e permanece aberto por **25 segundos** (`recovery_timeout=25s`), evitando desperdício de recursos e timeouts em cascata enquanto o Ollama estiver fora do ar.
   - Permite abertura/fechamento controlado via `POST /api/gestao/ia/circuit-breaker` para demonstração ao vivo.
4. **Estratégia de Fallback Contextualizado:**
   - Quando o Ollama falha após os retries ou o Circuit Breaker está `OPEN`, o serviço sintetiza automaticamente uma resposta técnica determinística combinando os **dados reais das LangChain Tools** com os **trechos normativos recuperados do RAG**, devolvendo HTTP `200` com `modo_operacao="FALLBACK_RESILIENTE"`.

---

## 3. Análise de Latência Medida (Execução Real)

Medições coletadas via `GET /api/gestao/ia/metricas` em execução real passando por **Nginx Gateway → BFF Gestão → ai-service → Ollama (`deephat:latest`, 4.2 GB)**:

| Cenário / Operação | Amostras | Latência Mínima | Latência Média | Latência Máxima | Observação |
|---|---|---|---|---|---|
| **Ollama `deephat:latest` (Warm)** | 10 | `2.411,12 ms` | `5.642,42 ms` | `7.871,71 ms` | Inferência local após o modelo já estar carregado na GPU |
| **Ollama `deephat:latest` (Cold Start)** | 1 | `44.495,19 ms` | `44.495,19 ms` | `44.495,19 ms` | Primeira requisição carregando pesos de 4,2 GB do disco |
| **Geral Ollama (Cold + Warm)** | 11 | `2.411,12 ms` | `9.174,49 ms` | `44.495,19 ms` | Mitigado em produção por `OLLAMA_KEEP_ALIVE=30m` |
| **Cache Hit (`CACHE_HIT`)** | 1 | `0,09 ms` | `0,09 ms` | `0,09 ms` | Redução > **99,99%** na latência em perguntas repetidas |
| **Falha com Retry + Abertura CB** | 1 | `400,50 ms` | `400,50 ms` | `400,50 ms` | Backoff de `0,4s` antes de acionar fallback |
| **Fallback com Circuit Breaker `OPEN`** | 1 | `0,08 ms` | `0,08 ms` | `0,08 ms` | Resposta imediata sem aguardar timeout de rede |

---

## 4. Estimativa de Custo por Operação em Escala

Considerando uma média de **850 tokens por consulta** (prompt com dados das tools + 3 chunks RAG + resposta gerada de ~250 tokens):

| Cenário | Custo por Consulta | 1.000 Consultas/mês | 50.000 Consultas/mês | Observações |
|---|---|---|---|---|
| **Ollama Local (`deephat:latest`)** | **US\$ 0,00** (sem taxa por token) | **US\$ 0,00** | Custo fixo de GPU/servidor | Zero custo variável de API; dados sensíveis da ONG não saem da infraestrutura |
| **API Cloud Compacta (Ref. US\$ 0,0015 / 1k tokens)** | US\$ 0,001275 | US\$ 1,28 | US\$ 63,75 | Modelo compacto equivalente em nuvem |
| **API Cloud com Cache de 30% (*hits*)** | US\$ 0,000893 efetivo | US\$ 0,89 | US\$ 44,63 | Economia direta de **30%** pelo `ResponseCache` |

> **Decisão Arquitetural:** Para o público-alvo do ONGSec (ONGs e pequenos negócios), rodar o `deephat:latest` localmente via Ollama elimina custo variável por token e impede o envio de informações internas da organização para provedores externos de IA, mantendo disponibilidade contínua por meio de Cache, Retry/Backoff, Circuit Breaker e Fallback.
