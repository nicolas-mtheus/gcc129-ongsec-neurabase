# ==============================================================================
# Multi-Stage Build - Painel Web de Gestão (ONGSec)
# Justificativa do Ganho Arquitetural:
# - Estágio 1 (Builder): Utiliza ambiente Node.js para validação e montagem dos
#   artefatos de distribuição.
# - Estágio 2 (Produção): Imagem final mínima baseada em Nginx Alpine (~25MB),
#   descartando totalmente o ambiente Node.js, compiladores e ferramentas (~300MB+).
# - Benefício: Redução superior a 90% no tamanho da imagem final, tempo de deploy
#   reduzido e mitigação de vulnerabilidades em tempo de execução (menor superfície de ataque).
# ==============================================================================

# Estágio 1: Build
FROM node:20-alpine AS builder

WORKDIR /app

COPY package.json ./
COPY . .

RUN npm run build

# Estágio 2: Produção (Nginx Alpine)
FROM nginx:alpine

COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]

