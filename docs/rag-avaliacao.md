# Avaliação do Pipeline RAG — ONGSec (`ai-service`)

Este documento descreve o pipeline completo de **RAG (*Retrieval-Augmented Generation*)** implementado em [`backend/services/ai-service/`](../backend/services/ai-service/) e apresenta a avaliação experimental de **5 perguntas de teste** executadas ao vivo no modelo local **`deephat:latest`** via **Ollama**, comparando as respostas **COM recuperação** e **SEM recuperação**.

---

## 1. Pipeline Completo de RAG

1. **Ingestão (`knowledge_base/`):** Leitura de **5 documentos normativos** próprios do domínio da startup:
   - `01_anpd_agentes_pequeno_porte.md` (Resolução CD/ANPD nº 2/2022)
   - `02_certbr_higiene_digital_ongs.md` (Cartilha de Segurança CERT.br)
   - `03_cis_controls_ig1_terceiro_setor.md` (CIS Controls v8 — IG1)
   - `04_sebrae_politica_privacidade_lgpd.md` (Guia SEBRAE LGPD & Art. 14 ECA/LGPD)
   - `05_ongsec_regras_certificacao_saga.md` (Regras de certificação, SAGA e CQRS do ONGSec)
2. **Segmentação (*Chunking*):** `RecursiveCharacterTextSplitter` do LangChain (`chunk_size=550`, `chunk_overlap=90`), produzindo **25 chunks** com metadados (`chunk_id`, `documento`, `titulo`).
3. **Geração de Embeddings:** Vetorização TF-IDF (n-gramas `1,2`) reduzida por SVD (`TruncatedSVD`) e normalizada em norma L2, gerando vetores densos de **24 dimensões** (`tfidf-svd-dense-l2`).
4. **Armazenamento em Base Vetorial:** Persistência em disco no arquivo `vector_store/index.json` (e modelo em `vector_store/vectorizer.pkl`), carregado na inicialização do `ai-service`.
5. **Recuperação:** Cálculo de similaridade de cosseno entre o vetor da pergunta e a matriz de chunks, recuperando os **top-3 chunks** mais relevantes (`score_similaridade`).
6. **Geração (LangChain LCEL + Tools):** O contexto recuperado + os dados reais da organização obtidos pelas LangChain Tools (`consultar_perfil_ong`, `consultar_diagnostico_e_plano`, `consultar_selo_publico_cqrs`) são injetados no `ChatPromptTemplate` e enviados ao `ChatOllama(model="deephat:latest")`.

---

## 2. Comparativo Experimental: 5 Perguntas (COM RAG vs. SEM RAG)

Todas as medições abaixo foram obtidas via `POST /api/gestao/ia/comparar-rag` através do Gateway com `ong_id="ong-123"` (*Associação Cuidar*).

### Pergunta 1 — Dispensa de DPO pela ANPD
> *"Segundo a Resolução CD/ANPD nº 2/2022, uma ONG de pequeno porte precisa indicar um Encarregado (DPO) formal ou basta um canal de comunicação?"*

* **Chunks recuperados:** `01_anpd_agentes_pequeno_porte.md` (similaridades `0.9358`, `0.5487`, `0.3674`)
* **COM RAG (`44.495 ms`, inclui *cold start* de carregamento do modelo):** Respondeu com precisão que agentes de pequeno porte (Art. 11 da Resolução CD/ANPD nº 2/2022) ficam dispensados de DPO formal, mas precisam obrigatoriamente disponibilizar um canal de comunicação acessível (ex.: `privacidade@ong.org`) para titulares e ANPD.
* **SEM RAG (`3.291 ms`):** Acertou a dispensa de DPO, porém inseriu uma imprecisão jurídica (*"a responsabilidade deve ser compartilhada entre a ONG e o encarregado de tratamento de dados"* — contradizendo a própria dispensa do encarregado).

### Pergunta 2 — Política de Privacidade para Abrigo Infantil
> *"Quais itens obrigatórios a Política de Privacidade da Associação Cuidar deve conter para tratar dados de crianças e adolescentes?"*

* **Chunks recuperados:** `04_sebrae_politica_privacidade_lgpd.md` (similaridades `0.7972`, `0.7190`, `0.5740`)
* **COM RAG (`6.724 ms`):** Citou exatamente os itens do guia + **Art. 14 da LGPD** (identificação do controlador/CNPJ/canal, consentimento específico de pelo menos um dos pais ou responsável legal com verificação razoável de identidade, isolamento de imagens/endereços e melhor interesse do menor), além de cruzar com a **LangChain Tool** informando que a *Associação Cuidar* já concluiu a tarefa de elaborar política de privacidade.
* **SEM RAG (`7.495 ms`):** Produziu uma lista genérica sem citar o Art. 14 da LGPD, o melhor interesse do menor ou a dispensa de DPO da Associação Cuidar como ATPP.

### Pergunta 3 — Política de Backup e Planilhas via WhatsApp (CERT.br)
> *"Qual é a política de backup recomendada pela cartilha CERT.br e como devemos tratar planilhas de beneficiários enviadas por WhatsApp?"*

* **Chunks recuperados:** `02_certbr_higiene_digital_ongs.md` (similaridades `0.7869`, `0.4990`, `0.4258`)
* **COM RAG (`7.872 ms`):** Detalhou exatamente a **regra 3-2-1 criptografado** (3 cópias, 2 mídias diferentes, 1 cópia *off-site* desconectada + testes semestrais de restauração) e recomendou **proibir o tráfego de planilhas sensíveis em grupos de WhatsApp**, migrando para repositório institucional autenticado com auditoria.
* **SEM RAG (`4.975 ms`):** **Alucinação grave de segurança** — não citou a regra 3-2-1 e ainda sugeriu *"utilizar ferramentas de OCR para extrair informações de imagens de WhatsApp"*, normalizando um canal inseguro.

### Pergunta 4 — Prazo de Revogação de Credenciais de Ex-Voluntários (CIS IG1)
> *"Em quanto tempo devemos revogar as credenciais de ex-voluntários segundo o CIS Controls v8 IG1?"*

* **Chunks recuperados:** `03_cis_controls_ig1_terceiro_setor.md` (similaridades `0.8375`, `0.5599`, `0.4661`)
* **COM RAG (`5.552 ms`):** Cravou o prazo normativo adotado: **no máximo 24 horas** após o encerramento do vínculo.
* **SEM RAG (`2.411 ms`):** **Alucinou o prazo para "até 30 dias"**, criando uma janela crítica de exposição de dados sensíveis.

### Pergunta 5 — Regras de Emissão de Selo e Compensação SAGA no ONGSec
> *"Qual o score mínimo e a condição das tarefas no ONGSec para emitir o selo, e o que acontece com o score se a SAGA precisar compensar?"*

* **Chunks recuperados:** `05_ongsec_regras_certificacao_saga.md` (similaridades `0.7318`, `0.6557`, `0.4144`)
* **COM RAG (`6.934 ms`):** Citou exatamente o questionário `q-lgpd-ig1`, o **score mínimo de 80%**, a exigência de tarefas concluídas e o comportamento da compensação SAGA (revoga selo, marca solicitação como `COMPENSADA`, reabre tarefas no `task-service` e **nunca apaga o score** no `audit-service`).
* **SEM RAG (`7.597 ms`):** **Alucinou completamente o domínio** — inventou *"score mínimo de 90 pontos"* e afirmou que *"a SAGA pode solicitar revisão do diagnóstico por especialistas para aumentar o score"*.

---

## 3. Conclusão da Avaliação

| Critério | Sem RAG | Com RAG |
|---|---|---|
| **Aderência às normas (ANPD / CERT.br / CIS)** | Baixa (alucinou 30 dias na Q4 e OCR de WhatsApp na Q3) | Alta (100% fiel aos guias recuperados) |
| **Aderência às regras do ONGSec (Q5)** | Incorreta (inventou score 90 e papel inexistente da SAGA) | Exata (score 80%, `q-lgpd-ig1`, compensação preservando `audit-service`) |
| **Contexto real da ONG** | Superficial | Contextualizado via LangChain Tools + base normativa |

