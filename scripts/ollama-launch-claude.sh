#!/usr/bin/env bash
#
# Launches Claude Code routed through a local Ollama model via claude-code-router.
#
# Claude Code only speaks Anthropic's Messages API, so claude-code-router (ccr)
# sits in between and translates requests to Ollama's OpenAI-compatible API.
#
# Usage:
#   ./scripts/ollama-launch-claude.sh [-- <args passed to claude code>]
#
# Env vars:
#   OLLAMA_MODEL  Ollama model tag to use (default: qwen2.5-coder:32b)
#   OLLAMA_HOST   Ollama API base, no trailing slash (default: http://localhost:11434)

set -euo pipefail

OLLAMA_MODEL="${OLLAMA_MODEL:-qwen2.5-coder:32b}"
OLLAMA_HOST="${OLLAMA_HOST:-http://localhost:11434}"
ROUTER_CONFIG_DIR="${HOME}/.claude-code-router"
ROUTER_CONFIG_FILE="${ROUTER_CONFIG_DIR}/config.json"

log() { printf '[ollama-launch-claude] %s\n' "$1"; }

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    log "Missing required command: $1 ($2)"
    exit 1
  fi
}

require_cmd ollama "install from https://ollama.com"
require_cmd npm "install Node.js from https://nodejs.org"
require_cmd curl "needed to check Ollama's status"

# --- Ensure Ollama server is running ---
if ! curl -sf "${OLLAMA_HOST}/api/version" >/dev/null 2>&1; then
  log "Starting Ollama server..."
  nohup ollama serve >/tmp/ollama-serve.log 2>&1 &
  for _ in $(seq 1 30); do
    curl -sf "${OLLAMA_HOST}/api/version" >/dev/null 2>&1 && break
    sleep 1
  done
  if ! curl -sf "${OLLAMA_HOST}/api/version" >/dev/null 2>&1; then
    log "Ollama server did not become ready; check /tmp/ollama-serve.log"
    exit 1
  fi
fi
log "Ollama server is up at ${OLLAMA_HOST}"

# --- Ensure the target model is pulled ---
if ! ollama list | awk '{print $1}' | grep -qx "${OLLAMA_MODEL}"; then
  log "Pulling model ${OLLAMA_MODEL} (this may take a while)..."
  ollama pull "${OLLAMA_MODEL}"
fi

# --- Ensure claude-code-router and claude code are installed ---
if ! command -v ccr >/dev/null 2>&1; then
  log "Installing @musistudio/claude-code-router..."
  npm install -g @musistudio/claude-code-router
fi
if ! command -v claude >/dev/null 2>&1; then
  log "Installing @anthropic-ai/claude-code..."
  npm install -g @anthropic-ai/claude-code
fi

# --- Write/refresh the router config for the Ollama provider ---
mkdir -p "${ROUTER_CONFIG_DIR}"
if [[ -f "${ROUTER_CONFIG_FILE}" ]]; then
  cp "${ROUTER_CONFIG_FILE}" "${ROUTER_CONFIG_FILE}.bak"
  log "Backed up existing config to ${ROUTER_CONFIG_FILE}.bak"
fi

cat > "${ROUTER_CONFIG_FILE}" <<EOF
{
  "LOG": true,
  "Providers": [
    {
      "name": "ollama",
      "api_base_url": "${OLLAMA_HOST}/v1/chat/completions",
      "api_key": "ollama",
      "models": ["${OLLAMA_MODEL}"]
    }
  ],
  "Router": {
    "default": "ollama,${OLLAMA_MODEL}",
    "background": "ollama,${OLLAMA_MODEL}",
    "think": "ollama,${OLLAMA_MODEL}",
    "longContext": "ollama,${OLLAMA_MODEL}"
  }
}
EOF
log "Wrote router config to ${ROUTER_CONFIG_FILE} (model: ${OLLAMA_MODEL})"

ccr restart >/dev/null 2>&1 || true

log "Launching Claude Code via claude-code-router..."
exec ccr code "$@"
