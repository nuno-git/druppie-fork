# Sandbox image. Runs under `docker run --runtime=kata-runtime` — each container
# is its own microVM with its own kernel. Running as root inside the VM is safe:
# VM-root ≠ host-root, and dockerd can initialise its namespaces/cgroups against
# the VM's guest kernel without touching the host.
#
# Everything the agent might want is pre-installed:
#   - bash, curl, git, jq, ripgrep, fd, build tools
#   - Node.js 22 + npm
#   - Python 3 + pip
#   - Docker Engine + compose plugin + buildx (so agents can `docker compose up`)
#   - aiohttp (for the exec daemon)

FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl gnupg git build-essential python3 python3-pip \
        ripgrep fd-find jq openssh-client \
    && ln -s /usr/bin/fdfind /usr/local/bin/fd \
    && rm -rf /var/lib/apt/lists/*

# Node.js 22 LTS
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Docker Engine + compose plugin + buildx
# (https://docs.docker.com/engine/install/debian/)
RUN install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc \
    && chmod a+r /etc/apt/keyrings/docker.asc \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian bookworm stable" \
        > /etc/apt/sources.list.d/docker.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin \
        iptables \
    && rm -rf /var/lib/apt/lists/*

# Python libs for the exec daemon
RUN pip3 install --no-cache-dir --break-system-packages aiohttp==3.11.10

RUN mkdir -p /workspace /out /app

COPY daemon.py /app/daemon.py
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

WORKDIR /workspace

ENV PYTHONUNBUFFERED=1 \
    HOME=/root \
    NPM_CONFIG_CACHE=/root/.npm \
    PIP_CACHE_DIR=/root/.pip

EXPOSE 8000
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
