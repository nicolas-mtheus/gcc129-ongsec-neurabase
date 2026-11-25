# Kubernetes local — Partes 3 e 4

Os manifests usam Minikube local. As imagens `ongsec/*:dev` são construídas
localmente a partir dos Dockerfiles do repositório (veja a seção de build) e não
precisam ser publicadas em nenhum registry.

## Pré-requisitos locais

- Docker Desktop em execução;
- `kubectl` e Minikube instalados;
- Minikube com recursos suficientes para os quatro bancos, o Redis e onze
  componentes HTTP (recomendado: 4 CPUs e 6 GiB de memória);
- Ollama em execução no computador, com o modelo `deephat:latest` baixado
  (`ollama pull deephat:latest`). O `ai-service` acessa o Ollama pelo endereço
  `http://host.minikube.internal:11434`. Se o serviço de IA não conseguir
  conectar, inicie o Ollama com a variável `OLLAMA_HOST=0.0.0.0` e teste de novo.

## Componentes do cluster

| Tipo | Componentes |
|---|---|
| Bancos (StatefulSet, 1 volume cada) | `org-db`, `audit-db`, `task-db`, `badge-db` |
| Microsserviços de domínio | `org-service`, `audit-service`, `task-service`, `badge-service` |
| Orquestração e IA | `saga-orchestrator`, `ai-service` |
| BFFs | `bff-gestao`, `bff-publico` |
| Clientes | `web-gestao` (painel), `mobile-publico` (app mobile PWA) |
| Infraestrutura | `api-gateway` (Nginx), `redis`, Ingress |

Todos os containers HTTP escutam na porta 8000, exceto Gateway, Painel Web e App
Mobile, que são Nginx e escutam na porta 80. No cluster, os Services das aplicações
expõem a porta 80; use nomes DNS como `http://org-service:80` e
`http://bff-publico:80` nas chamadas internas. As APIs respondem a
`GET /healthz`; o Painel Web e o App Mobile usam `GET /` como probe.

## Configuração (ConfigMap e Secrets)

Os quatro microsserviços de domínio leem `DB_HOST`, `DB_PORT`, `DB_NAME`,
`DB_USER` e `DB_PASSWORD`. O `saga-orchestrator` recebe as URLs de org, audit,
task e badge e chama esses serviços durante a SAGA. O `ai-service` recebe as URLs
dos quatro serviços (usadas pelas tools do LangChain) e o endereço do Ollama. Os
BFFs recebem as URLs dos serviços que consomem. As URLs e demais valores públicos
ficam no ConfigMap `ongsec-app-config` (`config/app-config.yaml`).

Informações sensíveis ficam em Secrets: uma senha para cada banco e o segredo do
JWT (`JWT_SECRET`), compartilhado pelos serviços que emitem ou validam tokens.

## Subir o cluster

Na raiz do repositório:

```powershell
minikube start --driver=docker --cpus=4 --memory=6144
minikube addons enable ingress
minikube addons enable metrics-server
kubectl apply -f infra/kubernetes/base/namespace.yaml
kubectl apply -f infra/kubernetes/config/app-config.yaml
# No Windows (PowerShell):
powershell -ExecutionPolicy Bypass -File .\infra\kubernetes\config\create-local-secrets.ps1
# No Linux/macOS (Bash):
./infra/kubernetes/config/create-local-secrets.sh
```

O script cria senhas aleatórias para cada banco e um segredo de JWT dentro do
cluster. Os valores não são gravados em arquivos do repositório nem impressos.
O script preserva Secrets que já existem, para que uma segunda execução não
troque a senha da aplicação sem trocar a senha armazenada no banco. Para reiniciar
as credenciais locais do zero, apague primeiro os quatro PVCs e os cinco Secrets;
o PostgreSQL só aplica `POSTGRES_PASSWORD` quando inicializa um volume vazio.

## Construir e carregar as imagens locais

São 11 imagens. O `Dockerfile` de cada aplicação está na pasta indicada abaixo.

```powershell
minikube image build -t ongsec/org-service:dev backend/services/org-service
minikube image build -t ongsec/audit-service:dev backend/services/audit-service
minikube image build -t ongsec/task-service:dev backend/services/task-service
minikube image build -t ongsec/badge-service:dev backend/services/badge-service
minikube image build -t ongsec/saga-orchestrator:dev backend/services/saga-orchestrator
minikube image build -t ongsec/ai-service:dev backend/services/ai-service
minikube image build -t ongsec/bff-gestao:dev backend/bffs/gestao
minikube image build -t ongsec/bff-publico:dev backend/bffs/publico
minikube image build -t ongsec/api-gateway:dev gateway/nginx
minikube image build -t ongsec/web-gestao:dev frontend/web-gestao
minikube image build -t ongsec/mobile-publico:dev frontend/mobile-publico
```

As imagens ficam locais ao Minikube. Se alguma delas faltar, o pod correspondente
fica em `ErrImagePull` ou `ImagePullBackOff`.

## Implantar e verificar

```powershell
kubectl apply -k infra/kubernetes
kubectl -n ongsec rollout status statefulset/org-db
kubectl -n ongsec rollout status statefulset/audit-db
kubectl -n ongsec rollout status statefulset/task-db
kubectl -n ongsec rollout status statefulset/badge-db
kubectl -n ongsec get deployments,pods,services,pvc,ingress,hpa
```

Todos os pods devem chegar a `Running` e `1/1`. Para conferir os componentes da
Parte 4 (no Linux/macOS, troque `findstr` por `grep`):

```powershell
kubectl -n ongsec get pods | findstr "saga ai-service mobile redis"
```

O Ingress recebe `http://ongsec.local/` e envia tudo ao API Gateway. O Gateway
roteia `/api/gestao/*` para `bff-gestao`, `/api/publico/*` para `bff-publico`,
`/gestao/*` para `web-gestao` (painel) e `/publico/*` para `mobile-publico`
(app mobile). O Gateway responde a `GET /healthz`.

Para testar sem editar o arquivo `hosts`:

```powershell
$minikubeIp = minikube ip
curl.exe -H "Host: ongsec.local" "http://$minikubeIp/healthz"
```

Para abrir o sistema no navegador sem usar o Ingress, mantenha este comando em
execução:

```powershell
kubectl -n ongsec port-forward service/api-gateway 8080:80
```

- Painel de gestão: `http://localhost:8080/gestao/`
- App mobile público: `http://localhost:8080/publico/`

O encaminhamento precisa continuar ativo enquanto o sistema estiver em uso.

Se o Ingress não ficar pronto, verifique `kubectl -n ingress-nginx get pods,services`
e os eventos com `kubectl -n ongsec get events --sort-by=.lastTimestamp`.

## Demonstrar escalabilidade

O HPA do `bff-publico` usa CPU média alvo de 70%, com 1 a 3 réplicas. O cluster
precisa do metrics-server; confira com `kubectl top pods -n ongsec`.

Sem carga suficiente de CPU, o HPA pode permanecer em uma réplica. Por isso a
demonstração eleva temporariamente o mínimo do HPA para 3:

No PowerShell 5.1, as aspas duplas do JSON precisam ser escapadas:

```powershell
kubectl -n ongsec patch hpa bff-publico --type merge -p '{\"spec\":{\"minReplicas\":3}}'
kubectl -n ongsec get pods -l app.kubernetes.io/name=bff-publico -w
```

No Bash, use aspas simples normais: `-p '{"spec":{"minReplicas":3}}'`.

Depois da demonstração, restaure o mínimo definido no manifest:

```powershell
kubectl -n ongsec patch hpa bff-publico --type merge -p '{\"spec\":{\"minReplicas\":1}}'
```

Para observar o HPA reagindo à CPU, gere carga de teste controlada e acompanhe
`kubectl -n ongsec get hpa bff-publico -w`.


## Limpar o cluster

```powershell
kubectl delete namespace ongsec
minikube stop
```

A exclusão do namespace apaga os PVCs e os dados de demonstração locais.
