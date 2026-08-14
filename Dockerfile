FROM python:3.11-slim

WORKDIR /app

# Instalar dependencias del sistema
RUN apt-get update && apt-get install -y \
    gcc \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Binario standalone de Codex (sin Node/npm/Rust), pineado a 0.147.0.
# El paquete npm "@openai/codex-linux-x64" es un alias; el tarball real del dist-tag de
# plataforma vive en @openai/codex@0.147.0-linux-x64 (registry.npmjs.org).
# sha256 del tarball (verificado el 2026-08-14):
#   c969740cf8297e4c31905cd551efeb2c99af5080c12c236bdf825598b250139a
# Layout interno: package/vendor/x86_64-unknown-linux-musl/bin/codex (build musl estatico).
RUN set -eux; \
    curl -fsSL -o /tmp/codex.tgz \
      https://registry.npmjs.org/@openai/codex/-/codex-0.147.0-linux-x64.tgz; \
    echo "c969740cf8297e4c31905cd551efeb2c99af5080c12c236bdf825598b250139a  /tmp/codex.tgz" | sha256sum -c -; \
    mkdir -p /tmp/codex-tarball; \
    tar -xzf /tmp/codex.tgz -C /tmp/codex-tarball \
      package/vendor/x86_64-unknown-linux-musl/bin/codex; \
    install -m 0755 /tmp/codex-tarball/package/vendor/x86_64-unknown-linux-musl/bin/codex \
      /usr/local/bin/codex; \
    rm -rf /tmp/codex.tgz /tmp/codex-tarball; \
    codex --version

# Copiar requirements e instalar
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar código
COPY . .

# Puerto para Koyeb (health check en 8000)
EXPOSE 8000

# Comando de inicio
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
