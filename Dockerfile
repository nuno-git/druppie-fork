# Build Stage
FROM golang:alpine AS builder

# Install git and upx for dependencies and compression
RUN apk add --no-cache git upx

WORKDIR /app

# Copy core directory first (sacrificing some caching for reliability)
COPY core/ ./core/
WORKDIR /app/core
RUN go mod download

WORKDIR /app
# Copy EVERYTHING to capture all documentation, assets, and source code
COPY . .

# Build the binary
WORKDIR /app/core
ARG VERSION=dev
RUN if [ -d "../.git" ]; then \
    export GIT_VERSION=$(git describe --tags --always --dirty 2>/dev/null || echo "$VERSION"); \
    else \
    export GIT_VERSION=$VERSION; \
    fi && \
    echo "Building Version: $GIT_VERSION" && \
    GOOS=linux go build -ldflags="-s -w -X main.Version=$GIT_VERSION" -o /app/druppie ./druppie
# Compress binary
RUN upx --best --lzma /app/druppie

# Generate Search Index
WORKDIR /app
RUN /app/druppie generate

# Run Stage
FROM python:3.11-slim-bookworm

# Install basic tools and runtimes needed by agents
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    ca-certificates \
    gnupg \
    build-essential \
    ffmpeg \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && curl -fsSL https://go.dev/dl/go1.21.6.linux-amd64.tar.gz | tar -C /usr/local -xzf - \
    && rm -rf /var/lib/apt/lists/*

ENV PATH="/usr/local/go/bin:${PATH}"

WORKDIR /app

# Create a non-root user
RUN groupadd -g 65532 druppie && \
    useradd -u 65532 -g druppie -m -s /bin/bash druppie && \
    chown -R druppie:druppie /app

# Copy Binary
COPY --from=builder --chown=druppie:druppie /app/druppie /app/druppie

# Copy Project Documentation & Portal Assets
COPY --from=builder --chown=druppie:druppie /app/index.html /app/index.html
COPY --from=builder --chown=druppie:druppie /app/doc_registry.js /app/doc_registry.js
COPY --from=builder --chown=druppie:druppie /app/search_index.json /app/search_index.json
COPY --from=builder --chown=druppie:druppie /app/druppie_logo.svg /app/druppie_logo.svg
COPY --from=builder --chown=druppie:druppie /app/druppie_logo.png /app/druppie_logo.png
COPY --from=builder --chown=druppie:druppie /app/druppie_cli.png /app/druppie_cli.png
COPY --from=builder --chown=druppie:druppie /app/druppie_k3d.png /app/druppie_k3d.png
COPY --from=builder --chown=druppie:druppie /app/README.md /app/README.md
COPY --from=builder --chown=druppie:druppie /app/LICENSE.md /app/LICENSE.md
COPY --from=builder --chown=druppie:druppie /app/manifest.json /app/manifest.json


# Copy Concept Folders
COPY --from=builder --chown=druppie:druppie /app/agents /app/agents
COPY --from=builder --chown=druppie:druppie /app/blocks /app/blocks
COPY --from=builder --chown=druppie:druppie /app/compliance /app/compliance
COPY --from=builder --chown=druppie:druppie /app/design /app/design
COPY --from=builder --chown=druppie:druppie /app/mcp /app/mcp
COPY --from=builder --chown=druppie:druppie /app/research /app/research
COPY --from=builder --chown=druppie:druppie /app/script /app/script
COPY --from=builder --chown=druppie:druppie /app/skills /app/skills
COPY --from=builder --chown=druppie:druppie /app/story /app/story
COPY --from=builder --chown=druppie:druppie /app/tools /app/tools
COPY --from=builder --chown=druppie:druppie /app/ui /app/ui

# Setup environment for persistence
ENV HOME=/app

# Define volume for configuration and logs
VOLUME /app/.druppie

# Expose port
EXPOSE 8080

USER druppie

ENTRYPOINT ["/app/druppie", "serve"]
