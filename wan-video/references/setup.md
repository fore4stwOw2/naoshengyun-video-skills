# Host configuration

The server is a stdio MCP server: Python 3.9+, no third-party packages. Replace
`/ABS/PATH` with the real skill path and `sk-...` with the gateway token.

Resolve absolute paths first:

```bash
python3 -c "import sys; print(sys.executable)"   # interpreter path
echo "$HOME/.codex/skills/wan-video/scripts/mcp_server.py"
```

Use absolute paths everywhere. GUI hosts do not inherit a login shell, so `python3`
alone often fails to resolve and `~` is not always expanded.

## Tencent WorkBuddy

Video models cannot be added through Settings → Models. That dialog configures
chat-completions endpoints only. Use a custom connector instead.

1. Open the connector management page.
2. Click **自定义连接器 / Custom connector** in the top right.
3. Add a stdio MCP server:
   - Command: absolute interpreter path, e.g. `/usr/bin/python3`
   - Arguments: `/ABS/PATH/scripts/mcp_server.py`
   - Environment: `WAN_API_KEY=sk-...`
4. Enable the connector; the card shows a green dot when the handshake succeeds.
5. Ask for a video in a task. WorkBuddy calls the tools on its own.

## Codex CLI

Add to `~/.codex/config.toml`:

```toml
[mcp_servers.wan]
command = "/usr/bin/python3"
args = ["/ABS/PATH/scripts/mcp_server.py"]
env = { WAN_API_KEY = "sk-...", WAN_OUTPUT_DIR = "~/Downloads/wan" }
```

## Claude Desktop

Edit `~/Library/Application Support/Claude/claude_desktop_config.json` on macOS, or
`%APPDATA%\Claude\claude_desktop_config.json` on Windows:

```json
{
  "mcpServers": {
    "wan": {
      "command": "/usr/bin/python3",
      "args": ["/ABS/PATH/scripts/mcp_server.py"],
      "env": { "WAN_API_KEY": "sk-..." }
    }
  }
}
```

Restart Claude Desktop. The tools appear under the connector icon.

## Running alongside the seedance skill

Both servers can be registered at once under different names; they are independent
processes with separate environment variables. Register `wan` and `seedance` as
separate entries and the host will offer both toolsets.

## Verify

```bash
WAN_API_KEY=sk-... python3 /ABS/PATH/scripts/verify_setup.py
```

Or exercise the protocol directly:

```bash
printf '%s\n' \
 '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{}}}' \
 '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
 | WAN_API_KEY=sk-... python3 /ABS/PATH/scripts/mcp_server.py
```

Expect a handshake reply and four tools. Diagnostics go to stderr, protocol to stdout.

## Credential handling

Keep the key in host config or the environment, never in a prompt or a tracked file.
The server redacts `sk-` patterns from its own output, but a key pasted into a chat
message is already exposed. Rotate anything that leaks.

## Common problems

A server that fails to start is usually a wrong interpreter path or an unexpanded `~`.
Use absolute paths.

Tools present but every call returns 401 means the key is unset or rejected in that
host's environment; GUI hosts do not read your shell profile, so set the key in the
host config itself.

`CERTIFICATE_VERIFY_FAILED` on python.org builds means the trust store was never
populated. The client falls back to `certifi` and common system bundles; if it still
fails, run `/Applications/Python 3.x/Install Certificates.command`.
