# syntax=docker/dockerfile:1
# The sole session MCP image: skills, runtime imports, and policy-gated fetch.
# Build the reviewed upstream skills implementation at an immutable commit.
FROM rust:trixie AS builder
ARG MCP_JS_COMMIT=723fe32d4cc31c18f8255af2639059f7d8450324
RUN apt-get update && apt-get install -y --no-install-recommends git python3 pkg-config libssl-dev \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /src
RUN git init && git remote add origin https://github.com/r33drichards/mcp-js.git \
    && git fetch --depth 1 origin "$MCP_JS_COMMIT" && git checkout --detach FETCH_HEAD \
    && test "$(git rev-parse HEAD)" = "$MCP_JS_COMMIT"
RUN cargo build --locked --release -p server && cp target/release/server /mcp-v8

FROM python:3.13-slim AS documentation
COPY site/tutorials/ /source/site/tutorials/
COPY site/guides/ /source/site/guides/
COPY site/reference/ /source/site/reference/
COPY site/explanation/ /source/site/explanation/
COPY images/mcp-js/prepare-skills.py images/mcp-js/test_prepare_skills.py /
RUN python3 /test_prepare_skills.py && python3 /prepare-skills.py /source /skills

FROM debian:trixie-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -m -u 1000 mcpuser \
    && mkdir -p /data && chown mcpuser:mcpuser /data
COPY --from=builder --chmod=755 /mcp-v8 /usr/local/bin/mcp-v8
RUN mcp-v8 --version
COPY images/mcp-js/mcp_tools.rego images/mcp-js/filesystem.rego images/mcp-js/fetch.rego images/mcp-js/mcp-servers.json images/mcp-js/mcp-servers.no-exec.json images/mcp-js/run_js.md images/mcp-js/instructions.md /etc/mcp/
COPY --chmod=755 images/mcp-js/start.sh /usr/local/bin/start.sh
COPY --from=documentation /skills/ /etc/mcp/skills/
ENV PORT=8080 \
    MCP_V8_HTTP_PORT=8080 \
    MCP_V8_ALLOWED_HOSTS=* \
    MCP_V8_HEAP_STORE=none \
    MCP_V8_MCP_CONFIG=/etc/mcp/mcp-servers.json \
    MCP_V8_POLICIES_JSON='{"mcp_tools":{"policies":[{"url":"file:///etc/mcp/mcp_tools.rego"}]},"filesystem":{"policies":[{"url":"file:///etc/mcp/filesystem.rego"}]},"fetch":{"policies":[{"url":"file:///etc/mcp/fetch.rego"}]}}' \
    MCP_V8_RUN_JS_DESCRIPTION=@/etc/mcp/run_js.md \
    MCP_V8_INSTRUCTIONS=@/etc/mcp/instructions.md \
    MCP_V8_SESSION_DB_PATH=/data/mcp/sessions \
    MCP_V8_SKILLS_DIR=/etc/mcp/skills
USER mcpuser
EXPOSE 8080
ENTRYPOINT ["/usr/local/bin/start.sh"]
CMD []
