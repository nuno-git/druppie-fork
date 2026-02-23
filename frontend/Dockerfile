# Druppie Frontend Dockerfile
FROM node:20-alpine AS builder

WORKDIR /app

# Copy package files
COPY package*.json ./

# Install dependencies
RUN npm install

# Copy source
COPY . .

# Build arguments
ARG VITE_API_URL=http://localhost:8000
ARG VITE_KEYCLOAK_URL=http://localhost:8080
ARG VITE_KEYCLOAK_REALM=druppie
ARG VITE_KEYCLOAK_CLIENT_ID=druppie-frontend
ARG VITE_GITEA_URL=http://localhost:3000

# Set environment variables for build
ENV VITE_API_URL=$VITE_API_URL
ENV VITE_KEYCLOAK_URL=$VITE_KEYCLOAK_URL
ENV VITE_KEYCLOAK_REALM=$VITE_KEYCLOAK_REALM
ENV VITE_KEYCLOAK_CLIENT_ID=$VITE_KEYCLOAK_CLIENT_ID
ENV VITE_GITEA_URL=$VITE_GITEA_URL

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

# Expose port
EXPOSE 5173

# Run
CMD ["serve", "-s", "dist", "-l", "5173"]
