# Divisão de Atividades e Planejamento - Parte 3

Na pasta atual há documentação da arquitetura, mas ainda não encontrei código dos serviços, Dockerfiles, Compose ou manifests Kubernetes. Então a equipe precisa primeiro criar versões mínimas executáveis, com base nos contratos e decisões da Parte 2 — não apenas adicionar containers a algo já implementado.

| **Integrante** | **Responsabilidade** | **Parte para apresentarno vídeo** |
| --- | --- | --- |
| **Lucas** | Implementar `org-service` e `audit-service`, com endpoint de saúde, Dockerfilede cada um e endpoints mínimos coerentescom os contratos existentes. | Inicialização efuncionamento dosserviços de entidades eauditoria. |
| **Tainara** | Implementar `task-service` e `badge-service`, com endpoint de saúde, Dockerfilede cada um e endpoints mínimos coerentescom os contratos. | Serviços de remediação ecertificação; explicarcomo os bancos ficampersistentes. |
| **Nicolas** | Implementar o Gateway Nginx e os doisBFFs, cada qual com Dockerfile. Configurar etestar as rotas distintas de Gestão e Público. | Mostrar que o Gatewayencaminha para BFFsdiferentes e que asrespostas diferem. |
| **Marco** | Kubernetes: Deployments e Services,Ingress, ConfigMaps, Secrets edemonstração de escalabilidade; integrar etestar os manifests com as imagens doscolegas. | Subir/mostrar a aplicaçãono Kubernetes e escalarum serviço. |

**Integração compartilhada:** Nicolas pode coordenar o `docker-compose.yml`, mas cada responsável deve fornecer e testar a configuração do seu serviço. Tainara define com o grupo os quatro bancos isolados e seus volumes; os outros devem conferir que seus serviços se conectam a eles sem expor credenciais. Assim, a integração não fica baseada em um Compose que ninguém além do autor consegue validar.

## Convenções para começar sem bloqueios

Como ainda não há implementação, proponho adotar estas convenções para o trabalho:

- **Aplicações:** Python com FastAPI; Gateway com Nginx.
- **Porta interna:** cada aplicação escuta em `8000`; o nome DNS do serviço diferencia destinos. O Gateway pode ser acessado localmente em `localhost:8080`.
- **Saúde:** cada serviço expõe `GET /healthz`.
- **Bancos:** quatro instâncias PostgreSQL independentes, porta interna `5432`; volumes persistentes no Compose.
- **Imagens:** um Dockerfile por serviço da aplicação — quatro microsserviços, dois BFFs e Gateway. Os bancos usam a imagem oficial do PostgreSQL.
- **Kubernetes local:** uma opção simples é Minikube usando o driver Docker e o addon de Ingress. Confirmem que essa opção funciona nas máquinas da equipe antes de depender dela para a gravação.
- **Configuração:** ConfigMaps para configurações não sensíveis; Secrets para credenciais. Não versionem valores reais de senhas ou tokens.

São escolhas propostas para destravar o desenvolvimento, não decisões que encontrei já implementadas. Alinhem-nas no grupo antes de codificar, especialmente se alguém já tiver alguma restrição de ambiente.

## Sequência sugerida até a apresentação

- **09/11:** confirmar as convenções, dividir os serviços e acordar contratos de ambiente — portas, nomes, variáveis e `/healthz`.
- **10–11/11:** implementar os quatro serviços de domínio e criar as imagens. Em paralelo, Nicolas começa Gateway e BFFs; Marco prepara a estrutura Kubernetes a partir dos nomes e portas combinados.
- **12–13/11:** integrar o Compose com bancos, volumes e redes; montar Deployments e Services; testar cada parte em conjunto.
- **14/11:** configurar Ingress, ConfigMaps e Secrets; fazer as rotas públicas e de gestão funcionarem no cluster.
- **15/11:** validar persistência, saúde dos serviços e escalabilidade — por exemplo, aumentar as réplicas do BFF Público e mostrar os pods prontos.
- **16/11:** ensaiar e gravar o vídeo. Reservem tempo para corrigir falhas e confirmar que o vídeo está no repositório, com até 10 minutos.

<div></div>

- **17/11:** apresentação e arguição, conforme o `enunciado.txt`.

No vídeo, cada pessoa deve explicar uma contribuição própria e aparecer falando. Mostrem a inicialização e os recursos em execução, não só os manifests. Registrem contribuições reais em branches/PRs e revisões cruzadas; não criem commits artificiais para cumprir uma contagem.

---

[^2]: 

[^3]: 
