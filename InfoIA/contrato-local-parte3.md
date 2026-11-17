## Parte 3 — Contrato de implementacao local

Este documento propoe um contrato comum para a implementacao da Parte 3. A ideia e evitar que cada integrante escolha portas, nomes de servicos ou caminhos de API incompativeis. Confirmem as escolhas no grupo antes de comecar; qualquer alteracao deve ser atualizada aqui e comunicada aos demais.

## 1. Arquitetura e estrutura do repositorio

```
frontend/
web-gestao/ # Painel Web de Gestao (React + Vite)
mobile-publico/ # App Mobile Publico (React Native + Expo)
backend/
services/
org-service/ # FastAPI
audit-service/ # FastAPI
task-service/ # FastAPI
badge-service/ # FastAPI
bffs/
gestao/ # FastAPI
publico/ # FastAPI
gateway/
nginx/ # API Gateway e servidor do Painel Web
infra/
compose/ # Docker Compose, variaveis locais de exemplo
kubernetes/
base/ # Namespace e recursos comuns
config/ # ConfigMaps e referencias a Secrets
workloads/ # Deployments e StatefulSets
networking/ # Services e Ingress
storage/ # PVCs dos bancos
docs/
parte3/ # Contratos e instrucoes da Parte 3
```

O App Mobile e executado pelo Expo no computador ou em um celular/emulador; ele nao precisa de imagem Docker. O Painel Web e um container separado, servido pelo Gateway. Os quatro bancos usam a imagem oficial do PostgreSQL, cada um com seu proprio volume persistente.


## 2. Portas

| Componente | Porta no | Porta publicada | Observacoes |
| --- | --- | --- | --- |
|   | container/cluster | localmente |   |
| API Gateway (Nginx) 80 |   | 8080 | Unica porta HTTP publicada pelo Compose |
| Painel Web de | 80 | — | Servido pelo Gateway em |
| Gestao |   |   | http://localhost:8080/gestao/ |
| org-service | 8000 | — | Acesso interno via http://org-service:8000 |
| audit-service | 8000 | — | Acesso interno via http://audit-service:8000 |
| task-service | 8000 | — | Acesso interno via http://task-service:8000 |
| badge-service | 8000 | — | Acesso interno via http://badge-service:8000 |
| BFF Gestao | 8000 | — | Acesso interno via http://bff-gestao:8000 |
| BFF Publico | 8000 | — | Acesso interno via http://bff-publico:8000 |
| PostgreSQL de cada | 5432 | — | Rede interna; sem porta publicada por padrao |
| servico |   |   |   |
| Expo Metro | 8081 (padrao Expo) | 8081 | Servidor de desenvolvimento do app, nao faz parte do |
|   |   |   | Gateway |

Todas as aplicacoes HTTP devem escutar em 0.0.0.0 dentro do container. Cada servico FastAPI deve expor GET /healthz , retornando HTTP 200 quando estiver pronto. Nao use localhost para comunicacao entre containers: use o nome DNS do servico.

Se for necessario acessar um banco pelo computador para depuracao, publiquem sua porta somente localmente e temporariamente, usando portas distintas (por exemplo, 5433 a 5436). Isso nao e necessario para a execucao normal.

## 3. Nomes de servico e URLs internas

| Origem | Destino | URL interna |
| --- | --- | --- |
| BFF Gestao | org-service | http://org-service:8000 |
| BFF Gestao | audit-service | http://audit-service:8000 |
| BFF Gestao | task-service | http://task-service:8000 |
| BFF Gestao | badge-service | http://badge-service:8000 |
| BFF Publico | badge-service | http://badge-service:8000 |
| API Gateway | BFF Gestao | http://bff-gestao:8000 |
| API Gateway | BFF Publico | http://bff-publico:8000 |
| API Gateway | Painel Web | http://web-gestao:80 |

O badge-service tambem pode chamar audit-service e task-service na SAGA usando os nomes DNS acima. O acesso externo as APIs passa pelo Gateway; bancos e servicos de dominio nao devem ser expostos diretamente ao host.


## 4. Rotas externas

| Metodo/caminho | Destino | Acesso |
| --- | --- | --- |
| GET /healthz | API Gateway | Verificacao da borda |
| /gestao/ | Painel Web | Navegador |
| /api/gestao/* | BFF Gestao | JWT exigido nas rotas protegidas |
| /api/publico/* | BFF Publico | Consulta anonima de selo |

O app mobile usa GET /api/publico/selos/{ongId} atraves do Gateway. O painel usa /api/gestao/* . O

Gateway encaminha essas rotas aos BFFs; os BFFs chamam os servicos de dominio pela rede interna. As rotas internas dos microsservicos nao sao publicadas diretamente.

Para o app em emulador Android, localhost dentro do emulador nao e o computador anfitriao: configure a base URL do app para http://10.0.2.2:8080 . Em um celular fisico, use o IP local do computador e mantenha computador e celular na mesma rede Wi-Fi. O navegador no computador usa http://localhost:8080 .

## 5. Bancos e configuracao

| Servico | Nome do banco no ambiente local |
| --- | --- |
| org-service | org-db |
| audit-service | audit-db |
| task-service | task-db |
| badge-service | badge-db |

Cada banco deve ter credenciais e volume proprios. As aplicacoes recebem a conexao por variaveis de ambiente, por exemplo DATABASE_URL , sem credenciais fixas no codigo. Valores locais ficam em um arquivo .env ignorado pelo Git; versionem apenas .env.example sem senhas reais. No Kubernetes, use ConfigMaps para configuracoes nao sensiveis e Secrets para credenciais. Nao versionem Secrets com valores reais.

## 6. Docker Compose

O arquivo sera infra/compose/docker-compose.yml . Da raiz do repositorio, subir todo o ambiente com:

docker compose -f infra/compose/docker-compose.yml up --build

O Compose deve iniciar o Gateway, o Painel Web, os dois BFFs, os quatro servicos de dominio e os quatro bancos. Deve definir health checks e volumes persistentes. Para isolar as camadas, use:

- edge : Gateway, Painel Web e BFFs;

- app : BFFs e os quatro servicos de dominio;

- uma rede de dados por servico (por exemplo, org-data ): apenas o servico e seu

proprio banco.

Os servicos de dominio e bancos nao publicam portas no host. O badge-service consegue chamar audit-service e task-service pela rede app para executar a SAGA.

O enunciado pede Dockerfile proprio para cada servico. Criem Dockerfiles para os quatro microsservicos, os dois BFFs, o Gateway e o Painel Web. Usem a imagem oficial do PostgreSQL para os bancos. Multi-stage build


deve ser aplicado onde trouxer beneficio mensuravel e justificado; nao e necessario forcar esse padrao em imagens onde nao se aplica.

O mobile roda separadamente na pasta frontend/mobile-publico :

```
Set-Location frontend/mobile-publico
npm install
npx expo start
```

Ele consome a API publicada pelo Gateway em http://localhost:8080 no computador, http://10.0.2.2:8080 no emulador Android, ou http://<IP-DO-COMPUTADOR>:8080 em aparelho fisico.

## 7. Kubernetes local

Usar Minikube localmente. Construir/carregar as imagens no cluster local (sem depender de registry publico), habilitar o Ingress Controller e encaminhar o Ingress para o Service do API Gateway. Use tags locais previsiveis, por exemplo ongsec/org-service:dev , e imagePullPolicy: IfNotPresent para evitar exigir um registry. Cada aplicacao HTTP usa um Service ClusterIP na porta 80, com targetPort: 8000 (Gateway e Painel Web usam porta 80). Os quatro bancos usam StatefulSets, Services internos e PVCs.

Exemplo de build local de uma imagem a partir da raiz do repositorio:

```
minikube image build -t ongsec/org-service:dev backend/services/org-service
```

Repita para as outras imagens, usando a pasta correspondente como contexto.

O conjunto de manifests deve cobrir:

- Namespace do projeto;

- Deployments para Gateway, Painel Web, BFFs e quatro servicos de dominio;

- StatefulSets e PVCs para os quatro bancos;

- Services para os componentes;

- Ingress que roteia trafego ao Gateway;

- ConfigMaps e Secrets;

- probes de readiness/liveness;

- escalabilidade demonstravel, por exemplo, aumentando replicas do BFF Publico.

Manifests nao devem conter credenciais reais. Para a demonstracao, mostrar pods prontos, Services, regra de Ingress e replicas adicionais em execucao.

Para verificar o Ingress sem configurar DNS local, use o IP do Minikube e envie o host definido no manifest, por exemplo:

```
curl.exe -H "Host: ongsec.local" http://<IP-DO-MINIKUBE>/healthz
```

Para abrir o Painel Web no navegador, pode-se adicionar ongsec.local ao arquivo hosts do Windows apontando para o IP local do Ingress, ou usar encaminhamento de porta para o Service do Gateway durante a demonstracao.


## 8. Divisao inicial do trabalho

| Integrante | Entrega inicial |   |
| --- | --- | --- |
| Lucas | org-service e audit-service , endpoints minimos, /healthz | e Dockerfiles |
| Tainara | task-service e badge-service , endpoints minimos, /healthz | e Dockerfiles |
| Nicolas | BFF Gestao, BFF Publico, configuracao Nginx do Gateway, roteamento e integracao do Compose |   |
| Marco | Manifests Kubernetes, ConfigMaps/Secrets, Ingress, PVCs e teste de escalabilidade |   |

Todos devem alinhar nomes de variaveis e validar a integracao. Nicolas e os responsaveis por cada aplicacao devem fornecer Dockerfiles e instrucoes que Marco possa usar para construir/carregar as imagens no Minikube. A divisao nao substitui revisao cruzada, PRs e contribuicoes proprias de todos.

## 9. Criterio minimo de demonstracao

- 1. Subir o ambiente local com um comando e mostrar os containers saudaveis.

- 2. Abrir o Painel Web pelo Gateway e chamar uma rota protegida do BFF Gestao.

- 3. Abrir o App Mobile no emulador/aparelho e consultar um selo pela rota publica.

- 4. Demonstrar os quatro bancos com volumes persistentes e as redes isoladas.

- 5. Subir a mesma arquitetura no Minikube e mostrar Deployments, Services, Ingress,

ConfigMaps, Secrets e PVCs.

- 1. Escalar o BFF Publico e mostrar as replicas prontas.

- 2. No video de ate 10 minutos, todos os quatro integrantes aparecem e explicam

contribuicoes distintas, alem de mostrar o sistema levantado e em execucao.
