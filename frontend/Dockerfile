# Druppie Frontend Dockerfile
FROM node:20-alpine AS builder

WORKDIR /app

# Copy package files
COPY package*.json ./

# Install dependencies
RUN npm install

ARG CACHEBUST
# Copy source
COPY . .

# Build with placeholders that get replaced at container startup
ENV VITE_API_URL=__VITE_API_URL__
ENV VITE_KEYCLOAK_URL=__VITE_KEYCLOAK_URL__
ENV VITE_KEYCLOAK_REALM=__VITE_KEYCLOAK_REALM__
ENV VITE_KEYCLOAK_CLIENT_ID=__VITE_KEYCLOAK_CLIENT_ID__
ENV VITE_GITEA_URL=__VITE_GITEA_URL__

# Build
RUN npm run build

# Production stage
FROM node:20-alpine

WORKDIR /app

# Install serve
RUN npm install -g serve

# Copy built files
COPY --from=builder /app/dist ./dist
COPY --from=builder /app/public ./public

# Copy silent-check-sso.html for Keycloak
COPY public/silent-check-sso.html ./dist/

# Copy entrypoint that replaces placeholders with runtime env vars
COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Expose port
EXPOSE 5173

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["serve", "-s", "dist", "-l", "5173"]
