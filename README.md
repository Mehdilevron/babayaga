# babayaga

Personal sandbox of MCP server configs and Claude Code skills.

## MCP servers

### n8n-mcp

Registered in [`.mcp.json`](./.mcp.json), running via `npx n8n-mcp`
([czlonkowski/n8n-mcp](https://github.com/czlonkowski/n8n-mcp)). Gives Claude
structured access to n8n's node library and docs (properties, operations,
versions) plus a workflow template index, so it can help design and validate
n8n workflows.

Works out of the box in documentation-only mode. To also let Claude manage
workflows on a real n8n instance (create/update/deploy/execute), export these
before starting Claude Code — `.mcp.json` pulls them in via `${VAR}`
substitution rather than hardcoding secrets in the repo:

```bash
export N8N_API_URL="https://your-n8n-instance.com"
export N8N_API_KEY="your-api-key"
```

### n8n-instance

Also registered in [`.mcp.json`](./.mcp.json): a direct connection to a live n8n
instance via n8n's built-in **Instance-level MCP** server (Settings →
Instance-level MCP → Connection details). Unlike `n8n-mcp` above, this talks to
the running instance over HTTP and can discover, run, and iterate on workflows
that have been opted in to MCP access. No paid Public-API key required — it uses
the instance MCP server's own bearer token.

Set these before starting Claude Code (kept out of the repo via `${VAR}`
substitution):

```bash
export N8N_MCP_URL="https://your-instance.app.n8n.cloud/mcp-server/http"
export N8N_MCP_TOKEN="your-instance-mcp-access-token"
```

## Skills

`.claude/skills/` contains vendored Claude Code skill bundles (UI/UX design
suite, etc.).
