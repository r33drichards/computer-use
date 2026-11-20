FROM debian:trixie-slim AS browser-source
ARG COMPUTER_USE_REV=63bab526d2a999af969657f70a342dfebe1cbb63
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates git \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /src
RUN git init && git remote add origin https://github.com/r33drichards/computer-use.git && \
    git fetch --depth 1 origin "$COMPUTER_USE_REV" && git checkout --detach FETCH_HEAD && \
    test "$(git rev-parse HEAD)" = "$COMPUTER_USE_REV"
WORKDIR /src/images/browser
# Apply the local narrow overlay on Debian (sed is not in nixos/nix).
# Require each exact upstream process line and its PID bookkeeping before
# disabling the public VNC gateway. Keep the original loopback exec server.
RUN test "$(grep -c '^EXEC_LOG_DIR=.*bash "\$EXEC_SERVER" &$' browser/entrypoint.sh)" = 1 && \
    test "$(grep -c '^websockify --web .* &$' browser/entrypoint.sh)" = 1 && \
    grep -A1 '^EXEC_LOG_DIR=' browser/entrypoint.sh | grep -Fx 'pids+=($!)' && \
    grep -A1 '^websockify --web' browser/entrypoint.sh | grep -Fx 'pids+=($!)' && \
    test "$(grep -Fc "listen(PORT, '::'" browser/server.js)" = 1 && \
    sed -i '/^websockify --web/{N;d;}' browser/entrypoint.sh && \
    sed -i "s/listen(PORT, '::'/listen(PORT, '127.0.0.1'/" browser/server.js && \
    grep -Fq -- '--bind-address 127.0.0.1' browser/exec-server.sh && \
    grep -Fq -- '--reject-browser-requests' browser/exec-server.sh && \
    ! grep -Eq '^websockify --web' browser/entrypoint.sh && \
    test "$(grep -Fc "listen(PORT, '127.0.0.1'" browser/server.js)" = 1 && \
    bash -n browser/entrypoint.sh

# Nix 2.34 includes the upstream PTY EIO handling needed on gVisor.
FROM nixos/nix:2.34.9@sha256:53b5ec518b696373829ea305c3c07a8c870113e44648c88ec484ef078550fd4f AS desktop
WORKDIR /src
COPY --from=browser-source /src/images/browser/ ./
RUN nix --extra-experimental-features "nix-command flakes" --option filter-syscalls false \
      build .#runtime -o /desktop-runtime && \
    mkdir -p /out/nix/store && \
    cp -a $(nix-store -qR /desktop-runtime) /out/nix/store/ && \
    ln -s "$(readlink -f /desktop-runtime)/bin/browser-entrypoint" /out/desktop-entrypoint

FROM rust:trixie AS mcp
ARG MCP_JS_REV=453c6b29e4797efa204e417c2baf966fec6bc4ff
RUN apt-get update && apt-get install -y --no-install-recommends git python3 pkg-config libssl-dev \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /src
RUN git init && git remote add origin https://github.com/r33drichards/mcp-js.git && \
    git fetch --depth 1 origin "$MCP_JS_REV" && git checkout --detach FETCH_HEAD && \
    test "$(git rev-parse HEAD)" = "$MCP_JS_REV" && \
    cargo build --locked --release --jobs 2 -p server

FROM python:3.12-slim-trixie
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates dbus libssl3t64 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -g 1000 desktop && useradd -m -u 1000 -g desktop desktop \
    && groupadd -g 1001 mcp && useradd -m -u 1001 -g mcp mcp \
    && install -d -m 700 -o desktop -g desktop /var/lib/modal-desktop \
    && install -d -m 700 -o mcp -g mcp /var/lib/modal-mcp \
    && mkdir -p /etc/mcp && dbus-uuidgen --ensure=/etc/machine-id
COPY --from=desktop /out/ /
COPY --from=mcp /src/target/release/server /usr/local/bin/mcp-v8
COPY requirements-runtime.txt /opt/requirements-runtime.txt
RUN pip install --no-cache-dir -r /opt/requirements-runtime.txt && mcp-v8 --version

# Bundle the same gateway and verifier tested by the amd64 image CI job.
WORKDIR /opt/computer-use
COPY gateway.py runtime.py verify.py ./
ENV PYTHONPATH=/opt/computer-use PYTHONDONTWRITEBYTECODE=1
LABEL org.opencontainers.image.source=https://github.com/r33drichards/computer-use
