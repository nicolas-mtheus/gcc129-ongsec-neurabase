# ONGSec 🛡️
**Startup de Cibersegurança e Conformidade LGPD para o Terceiro Setor e Pequenos Negócios.**

Projeto desenvolvido para a disciplina **GCC129 — Sistemas Distribuídos** (2026/2).

## 👥 Integrantes (Equipe NeuraBase)
* Nicolas Matheus Lima Oliveira
* Marco Antônio Maia
* Tainara de Fátima Matias Souza
* LUCAS DE JESUS GONÇALVES

---

## 🎯 O Problema
Comércios locais e pequenas associações sem fins lucrativos frequentemente lidam com dados sensíveis (CPFs de doadores, fichas médicas, endereços de pessoas em situação de vulnerabilidade). No entanto, essas entidades não possuem orçamento para consultorias de cibersegurança ou ferramentas de adequação à Lei Geral de Proteção de Dados (LGPD), recorrendo a processos inseguros, como troca de documentos via WhatsApp e armazenamento de planilhas sem senha.

### Impacto Social Esperado
Democratizar a segurança da informação, oferecendo uma ferramenta automatizada e acessível que protege os dados de populações vulneráveis e garante a continuidade de projetos sociais e pequenos negócios, mitigando o risco de multas e vazamentos.

---

## 💡 A Solução e História de Uso
O **ONGSec** atua como um consultor de segurança automatizado e emissor de selos de conformidade. 

**Exemplo Prático (Associação Cuidar):**
Dona Maria, diretora de um pequeno abrigo, acessa o **Dashboard Web (BFF 1)**. Ela responde a um diagnóstico simples (ex: "Vocês usam a mesma senha no computador?"). O sistema processa as respostas e gera um plano de ação tático. Ao tentar resolver a tarefa *"Criar Política de Privacidade"*, Dona Maria aciona o **Assistente de IA**, que utiliza as cartilhas oficiais (via RAG) e o contexto da tarefa (via LangChain Tools) para gerar o documento automaticamente.

Após concluir as tarefas, o sistema recalcula sua nota e emite um Selo Digital. Semanas depois, um doador em potencial acessa o **Portal Público (BFF 2)**, busca pelo nome da associação e valida o selo (arquitetura CQRS focada em leitura rápida), sentindo-se seguro para realizar a doação.

---

## 🏗️ Esboço da Arquitetura Distribuída

O sistema adota o padrão de microsserviços (*Database per service*), orquestrados para lidar com regras de negócio complexas através de coreografia/orquestração (SAGA).

| Microsserviço | Responsabilidade | Banco de Dados |
| :--- | :--- | :--- |
| **1. Entidades (Org)** | Cadastro, autenticação e gestão de ONGs e comércios locais. | PostgreSQL |
| **2. Auditoria (Audit)** | Gerencia checklists de segurança e calcula o *score* de risco. | MongoDB |
| **3. Remediação (Task)** | Gera e gerencia o ciclo de vida do plano de ação (to-do list). | PostgreSQL |
| **4. Certificação (Badge)** | Emite o selo público de conformidade (CQRS para o Portal Público). | Redis / PostgreSQL |

*A arquitetura completa, endpoints da API e fluxos de compensação (SAGA) estarão documentados na pasta `/docs` a partir da Parte 2.*

---

## 📚 Fundamentação e Referências Técnicas
Os questionários de auditoria e a base de conhecimento da Inteligência Artificial (RAG) são estritamente fundamentados em diretrizes e frameworks oficiais de órgãos governamentais e instituições de referência:

1. **ANPD (Autoridade Nacional de Proteção de Dados):** *Guia Orientativo para Agentes de Tratamento de Pequeno Porte.* Base para a flexibilização e adequação dos processos de ONGs à LGPD.
2. **CERT.br (Centro de Estudos, Resposta e Tratamento de Incidentes de Segurança no Brasil):** *Cartilha de Segurança para a Internet.* Utilizada para a geração de tarefas de remediação tática (higiene cibernética).
3. **CIS Controls v8:** *Implementation Group 1 (IG1).* Framework global de cibersegurança focado em defesas essenciais para pequenas empresas com recursos limitados de TI.
4. **Sebrae:** *Cartilhas de Adequação LGPD para Micro e Pequenas Empresas.* Fonte de linguagem acessível e pragmática para a comunicação da IA com os usuários finais.

---

## 🚀 Instruções de Execução (Local)

> **Nota:** Estas instruções cobrem a estrutura base. O ambiente completo containerizado será entregue na Parte 3.

**Pré-requisitos:**
* [Git](https://git-scm.com/)
* [Docker](https://www.docker.com/) e Docker Compose

**Passo a passo:**
1. Clone o repositório:
   ```bash
   git clone [https://github.com/nicolas-mtheus/gcc129-ongsec-neurabase.git](https://github.com/nicolas-mtheus/gcc129-ongsec-neurabase.git)
   cd gcc129-ongsec-neurabase
