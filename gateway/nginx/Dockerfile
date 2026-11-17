# ==============================================================================
# 👉 [MOSTRAR NO VÍDEO 7]: DOCKERFILE PRÓPRIO E CUSTOMIZADO DO API GATEWAY
# - Imagem base mínima Nginx Alpine (~23MB) com alta performance e baixo consumo.
# - Não é uma imagem pronta de terceiro sem customização: ela embute as regras
#   arquiteturais do ONGSec (roteamento reverso, rate limiting, healthcheck de borda
#   e injeção do header de rastreabilidade distribuída X-Correlation-ID).
# ==============================================================================
FROM nginx:alpine

# Copia a configuração customizada do Gateway para dentro do container
COPY nginx.conf /etc/nginx/nginx.conf

# Escuta na porta 80 interna (mapeada no Compose como porta única publicada: 8080)
EXPOSE 80

# Inicializa o Nginx em modo foreground para controle do Docker
CMD ["nginx", "-g", "daemon off;"]
