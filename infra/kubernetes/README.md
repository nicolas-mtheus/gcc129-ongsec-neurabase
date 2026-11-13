# Kubernetes local — Parte 3

Os manifests usam Minikube local e imagens ainda fornecidas pelos integrantes.
As tags `ongsec/*:dev` sao nomes de integracao previstos; o cluster so iniciara
as aplicacoes quando os respectivos Dockerfiles e codigos estiverem prontos.

## Pre-requisitos locais

- Docker Desktop em execucao;
- `kubectl` e Minikube instalados;
- Minikube com recursos suficientes para os quatro bancos e oito componentes
  HTTP (recomendado: 4 CPUs e 6 GiB de memoria);
- imagem propria para cada aplicacao: quatro servicos de dominio, dois BFFs,
  API Gateway e Painel Web.

O App Mobile Publico e executado pelo Expo fora do cluster. Configure a base URL
para o Gateway: `http://10.0.2.2:8080` no emulador Android, ou
`http://<IP-DO-MINIKUBE>`/porta encaminhada em um aparelho fisico.

Todos os containers HTTP escutam na porta 8000, exceto Gateway e Painel Web, que
escutam na porta 80. No cluster, os Services das aplicacoes expõem a porta 80;
use nomes DNS como `http://org-service:80` e `http://bff-publico:80` nas chamadas
internas. As APIs recebem `GET /healthz`; o Painel Web usa `GET /` como probe.

Os microsservicos devem ler `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER` e
`DB_PASSWORD`. O badge-service tambem recebe `AUDIT_SERVICE_URL` e
`TASK_SERVICE_URL`; os BFFs recebem as URLs dos microsservicos que consomem.
`org-service`, `bff-gestao` e Gateway recebem `JWT_SECRET`. Endpoints internos e
nomes de variaveis estao definidos em `config/app-config.yaml` e nos Deployments.

## Subir o cluster

Na raiz do repositorio:

```powershell
minikube start --driver=docker --cpus=4 --memory=6144
minikube addons enable ingress
minikube addons enable metrics-server
kubectl apply -f infra/kubernetes/base/namespace.yaml
kubectl apply -f infra/kubernetes/config/app-config.yaml
powershell -ExecutionPolicy Bypass -File .\infra\kubernetes\config\create-local-secrets.ps1
```

O script cria passwords aleatorias para cada banco e um segredo de JWT dentro do
cluster. Os valores nao sao gravados em arquivos do repositorio nem impressos.
O script preserva Secrets que ja existem, para que uma segunda execucao nao
troque a senha da aplicacao sem trocar a senha armazenada no banco. Para reiniciar
as credenciais locais do zero, apague primeiro os quatro PVCs e os cinco Secrets;
Postgres so aplica `POSTGRES_PASSWORD` quando inicializa um volume vazio.

## Construir e carregar as imagens locais

Execute depois que os Dockerfiles correspondentes existirem. O `Dockerfile` de
cada aplicacao deve estar na pasta abaixo e usar a porta acordada no contrato.

```powershell
minikube image build -t ongsec/org-service:dev backend/services/org-service
minikube image build -t ongsec/audit-service:dev backend/services/audit-service
minikube image build -t ongsec/task-service:dev backend/services/task-service
minikube image build -t ongsec/badge-service:dev backend/services/badge-service
minikube image build -t ongsec/bff-gestao:dev backend/bffs/gestao
minikube image build -t ongsec/bff-publico:dev backend/bffs/publico
minikube image build -t ongsec/api-gateway:dev gateway/nginx
minikube image build -t ongsec/web-gestao:dev frontend/web-gestao
```

As imagens sao locais ao Minikube; nao e necessario publicar em registry. O app
mobile nao tem Deployment: ele roda no Expo em um computador ou telefone.

## Implantar e verificar

```powershell
kubectl apply -k infra/kubernetes
kubectl -n ongsec rollout status statefulset/org-db
kubectl -n ongsec rollout status statefulset/audit-db
kubectl -n ongsec rollout status statefulset/task-db
kubectl -n ongsec rollout status statefulset/badge-db
kubectl -n ongsec get deployments,pods,services,pvc,ingress,hpa
```

O `Ingress` recebe `http://ongsec.local/` e envia tudo ao API Gateway. O Gateway
deve rotear `/api/gestao/*` para `bff-gestao`, `/api/publico/*` para `bff-publico`
e `/gestao/*` para `web-gestao`. O Gateway precisa expor `GET /healthz`; todos
os outros servicos HTTP precisam expor `GET /healthz` na porta 8000.

Para testar sem editar o arquivo `hosts`:

```powershell
$minikubeIp = minikube ip
curl.exe -H "Host: ongsec.local" "http://$minikubeIp/healthz"
```

Para conectar o app Expo ao Gateway no cluster local, mantenha este comando em
execucao:

```powershell
kubectl -n ongsec port-forward service/api-gateway 8080:80
```

Use `http://10.0.2.2:8080` no emulador Android e
`http://<IP-DO-COMPUTADOR>:8080` no telefone fisico. O forwarding precisa
continuar ativo enquanto o app estiver em uso. O navegador no computador pode
abrir o Painel Web em `http://localhost:8080/gestao/` durante o mesmo forwarding.

Se o ingress ainda nao estiver pronto, verifique `kubectl -n ingress-nginx get
pods,services` e os eventos com `kubectl -n ongsec get events --sort-by=.lastTimestamp`.

## Demonstrar escalabilidade

O HPA do BFF Publico usa CPU media alvo de 70%, com 1 a 3 replicas. O cluster
precisa do metrics-server; confira `kubectl top pods -n ongsec`. Para demonstrar
o aumento para tres replicas sem depender de carga de CPU, ajuste
temporariamente o minimo do HPA:

```powershell
kubectl -n ongsec patch hpa bff-publico --type merge -p '{"spec":{"minReplicas":3}}'
kubectl -n ongsec get pods -l app.kubernetes.io/name=bff-publico -w
```

Depois da demonstracao, restaure a escala minima definida no manifest:

```powershell
kubectl -n ongsec patch hpa bff-publico --type merge -p '{"spec":{"minReplicas":1}}'
```

Para demonstrar o HPA reagindo a CPU, gerem carga de teste controlada e observem
`kubectl -n ongsec get hpa bff-publico -w`; sem carga, ele pode permanecer em uma
replica. Nao prometam autoscaling observado se nao houver carga suficiente.

## Limpar o cluster

```powershell
kubectl delete namespace ongsec
minikube stop
```

A exclusao do namespace apaga os PVCs e os dados de demonstracao locais.
