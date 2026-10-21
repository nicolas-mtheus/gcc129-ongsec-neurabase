Decomposição dos Microsserviços — ONGSec

1. Visão geral

A plataforma ONGSec adota uma arquitetura baseada em quatro microsserviços independentes, organizados de acordo com as principais responsabilidades de negócio.

Essa divisão busca reduzir o acoplamento, facilitar a manutenção e permitir a evolução independente dos componentes.

2. Microsserviços

2.1. org-service — Gestão de Entidades

Responsável pelo cadastro e gerenciamento das ONGs, usuários e perfis de acesso.

Responsabilidades:

- Cadastrar e atualizar informações das organizações.
- Gerenciar usuários e suas permissões.
- Manter os dados cadastrais das entidades.

Fronteira: não realiza auditorias, não gerencia tarefas de remediação e não emite selos digitais.

2.2. audit-service — Auditoria

Responsável por avaliar a conformidade das organizações com os requisitos de segurança e proteção de dados.

Responsabilidades:

- Gerenciar questionários de diagnóstico.
- Registrar respostas e avaliações.
- Calcular indicadores de risco e conformidade.
- Disponibilizar resultados para o processo de certificação.

Fronteira: não gerencia a execução das tarefas corretivas nem publica certificados.

2.3. task-service — Remediação

Responsável pelo acompanhamento das ações necessárias para corrigir problemas identificados nas auditorias.

Responsabilidades:

- Criar tarefas a partir de não conformidades.
- Controlar prazos e estados das tarefas.
- Registrar a conclusão das ações corretivas.
- Informar se existem pendências que impedem a certificação.

Fronteira: não calcula o resultado da auditoria e não emite selos digitais.

2.4. badge-service — Certificação

Responsável pelo processo de emissão, manutenção e consulta dos selos digitais de conformidade.

Responsabilidades:

- Receber solicitações de certificação.
- Coordenar o processo de emissão do selo.
- Registrar o estado dos certificados.
- Disponibilizar a validação pública dos selos.

Fronteira: não modifica diretamente os resultados das auditorias ou o estado das tarefas dos demais serviços.

3. Comunicação entre os serviços

Os clientes externos acessam a plataforma por meio do API Gateway e dos respectivos BFFs.

Cada microsserviço possui seu próprio banco de dados, evitando o compartilhamento direto de tabelas entre serviços.

A emissão do selo envolve uma SAGA orquestrada, que coordena a verificação da auditoria, a validação das pendências e a certificação.

4. Justificativa da decomposição

A divisão proposta utiliza responsabilidades de negócio como critério principal. Cada serviço mantém autonomia sobre seus dados e operações.

Essa abordagem facilita a manutenção, o isolamento de falhas e a evolução dos componentes, embora exija mecanismos explícitos de comunicação e consistência distribuída.
