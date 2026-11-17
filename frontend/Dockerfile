# ==============================================================================
# CVS-ACS Frontend Production Dockerfile
# Multi-stage Build: Node 22 Build -> Nginx Alpine Static Serving
# ==============================================================================

# Stage 1: Build React/Vite SPA
FROM node:22-alpine AS builder

WORKDIR /app

COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci

COPY frontend/ ./
ARG VITE_API_BASE_URL=""
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL

RUN npm run build

# Stage 2: Serve with lightweight Nginx Alpine
FROM nginx:1.27-alpine

COPY --from=builder /app/dist /usr/share/nginx/html
COPY config/nginx/frontend-nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

HEALTHCHECK --interval=15s --timeout=3s --retries=3 \
    CMD wget -qO- http://localhost/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
