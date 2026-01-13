FROM golang:1.24 AS builder

WORKDIR /app

COPY go.mod go.sum ./
RUN go mod download

ARG TARGETARCH
# Install wget and bzip2 to download and extract dependencies
RUN apt-get update && apt-get install -y wget bzip2

# Download and install sherpa-onnx shared libraries
ENV SHERPA_ONNX_VERSION=v1.12.20
RUN set -ex \
    && if [ "$TARGETARCH" = "amd64" ]; then \
    file="sherpa-onnx-${SHERPA_ONNX_VERSION}-linux-x64-shared.tar.bz2"; \
    url="https://github.com/k2-fsa/sherpa-onnx/releases/download/${SHERPA_ONNX_VERSION}/$file"; \
    dir="sherpa-onnx-${SHERPA_ONNX_VERSION}-linux-x64-shared"; \
    elif [ "$TARGETARCH" = "arm64" ]; then \
    file="sherpa-onnx-${SHERPA_ONNX_VERSION}-linux-aarch64-shared-cpu.tar.bz2"; \
    url="https://github.com/k2-fsa/sherpa-onnx/releases/download/${SHERPA_ONNX_VERSION}/$file"; \
    dir="sherpa-onnx-${SHERPA_ONNX_VERSION}-linux-aarch64-shared-cpu"; \
    else \
    echo "Unsupported architecture: $TARGETARCH"; exit 1; \
    fi \
    && echo "Downloading $url" \
    && wget "$url" -O "$file" \
    && tar xf "$file" \
    && ls -la \
    && mkdir -p /usr/local/lib \
    && cp -r "$dir"/lib/* /usr/local/lib/ \
    && ([ -d "$dir"/include ] && cp -r "$dir"/include/* /usr/local/include/ || echo "No include directory found") \
    && rm -rf "$file" "$dir"

# Configure linker specific to builder
ENV LD_LIBRARY_PATH=/usr/local/lib
ENV C_INCLUDE_PATH=/usr/local/include

COPY . .

# Enable CGO for sherpa-onnx
ENV CGO_ENABLED=1
ENV GOOS=linux

RUN go build -ldflags "-r /usr/local/lib" -o sherpa-server .

FROM debian:bookworm-slim

WORKDIR /app

# Install certificates and runtime deps
RUN apt-get update && apt-get install -y ca-certificates && rm -rf /var/lib/apt/lists/*

# Copy compiled binary
COPY --from=builder /app/sherpa-server /app/sherpa-server

# Copy shared libraries
COPY --from=builder /usr/local/lib/ /usr/local/lib/
# Update linker cache
RUN ldconfig

EXPOSE 8081

# Explicitly set LD_LIBRARY_PATH in CMD to ensure it's picked up
ENV LD_LIBRARY_PATH=/usr/local/lib

# Debugging: List libs to ensure they are there
RUN ls -la /usr/local/lib

CMD ["/bin/sh", "-c", "export LD_LIBRARY_PATH=/usr/local/lib && /app/sherpa-server"]
