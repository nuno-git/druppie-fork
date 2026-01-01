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
RUN CGO_ENABLED=0 GOOS=linux go build -ldflags="-s -w" -o /app/druppie ./cmd
# Compress binary
RUN upx --best --lzma /app/druppie

# Generate Search Index
WORKDIR /app
RUN /app/druppie generate

# Run Stage
FROM gcr.io/distroless/static:nonroot

WORKDIR /app

# Copy Binary
COPY --from=builder /app/druppie /app/druppie

# Copy Project Documentation & Portal Assets
COPY --from=builder /app/index.html /app/index.html
COPY --from=builder /app/doc_registry.js /app/doc_registry.js
COPY --from=builder /app/search_index.json /app/search_index.json
COPY --from=builder /app/druppie_logo.svg /app/druppie_logo.svg
COPY --from=builder /app/druppie_logo.png /app/druppie_logo.png
COPY --from=builder /app/druppie_cli.png /app/druppie_cli.png
COPY --from=builder /app/druppie_k3d.png /app/druppie_k3d.png
COPY --from=builder /app/README.md /app/README.md
COPY --from=builder /app/LICENSE.md /app/LICENSE.md


# Copy Concept Folders
COPY --from=builder /app/agents /app/agents
COPY --from=builder /app/blocks /app/blocks
COPY --from=builder /app/compliance /app/compliance
COPY --from=builder /app/design /app/design
COPY --from=builder /app/mcp /app/mcp
COPY --from=builder /app/research /app/research
COPY --from=builder /app/script /app/script
COPY --from=builder /app/skills /app/skills
# COPY --from=builder /app/story /app/story
COPY --from=builder /app/tools /app/tools
COPY --from=builder /app/ui /app/ui

# Setup environment for persistence
ENV HOME=/app

# Define volume for configuration and logs
VOLUME /app/.druppie

# Expose port
EXPOSE 8080

USER 65532:65532

ENTRYPOINT ["/app/druppie", "serve"]
