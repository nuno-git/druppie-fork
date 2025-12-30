# Build Stage
FROM golang:1.22-alpine AS builder

WORKDIR /app

# Copy go mod and sum files
COPY go.mod go.sum ./
RUN go mod download

# Copy source code
COPY . .

# Build the binary
RUN CGO_ENABLED=0 GOOS=linux go build -o /app/druppie-core ./cmd

# Run Stage
FROM gcr.io/distroless/static:nonroot

WORKDIR /

COPY --from=builder /app/druppie-core /druppie-core

# Expose port
EXPOSE 8080

USER 65532:65532

ENTRYPOINT ["/druppie-core"]
