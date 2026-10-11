#!/usr/bin/env bash
#
# Installs this repo's Claude Code agents for your user account, so every
# agent (design, marketing, sales, engineering, Office Manager, ...) is
# available in any folder you open Claude Code in — not just this repo.
#
# Also copies the office playbook to ~/.claude/office-playbook.md so the
# Office Manager agent can find its rules outside this repo.
#
# Usage (from a clone of this repo, on the branch that has the agents):
#   ./scripts/install-agents-local.sh
#
# Re-run it after pulling to pick up new or updated agents. Existing agent
# files with the same name are overwritten; other agents you have are kept.
#
# Env vars:
#   CLAUDE_CONFIG_DIR  Claude Code config root (default: ~/.claude)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC_DIR="${REPO_ROOT}/.claude/agents"
CONFIG_DIR="${CLAUDE_CONFIG_DIR:-${HOME}/.claude}"
DEST_DIR="${CONFIG_DIR}/agents"

if [[ ! -d "${SRC_DIR}" ]] || ! ls "${SRC_DIR}"/*.md >/dev/null 2>&1; then
  echo "No agents found in ${SRC_DIR}." >&2
  echo "Check out the branch that has them first, e.g.:" >&2
  echo "  git checkout claude/intelligent-volta-uw8dm7" >&2
  exit 1
fi

mkdir -p "${DEST_DIR}"
cp "${SRC_DIR}"/*.md "${DEST_DIR}/"
count="$(ls "${SRC_DIR}"/*.md | wc -l | tr -d ' ')"

if [[ -f "${REPO_ROOT}/docs/office/playbook.md" ]]; then
  cp "${REPO_ROOT}/docs/office/playbook.md" "${CONFIG_DIR}/office-playbook.md"
fi

echo "Installed ${count} agents into ${DEST_DIR}"
echo
echo "Next:"
echo "  cd <the folder with your business files>"
echo "  claude"
echo "Then ask in plain words, e.g. 'design an Instagram carousel for my offer'."
echo "Run /agents inside Claude Code to see the full list."
