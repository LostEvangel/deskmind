# DeskMind

AI-powered desktop files organization agent for Windows.

Organize your cluttered desktop with natural language. Works as a CLI tool or as an MCP Server for Claude Desktop / Claude Code.

## Features

- **AI-powered** — tell it what to do in plain Chinese/English
- **Multi-LLM** — supports Claude, OpenAI, DeepSeek, and local models (Ollama)
- **Structured rules** — exact glob-based matching (zero API cost)
- **Safe** — preview before executing, undo support, send2trash for deletes
- **Claude integration** — MCP Server for Claude Desktop and Claude Code
- **Open source** — MIT license

## Installation

### Via pip (recommended)

```bash
pip install deskmind
```

### Via pipx (isolated)

```bash
pipx install deskmind
```

### Or download the exe

Grab the latest `deskmind.exe` from [Releases](https://github.com/yourusername/deskmind/releases).

## Quick Start

```bash
# Set your API key (use Claude, OpenAI, or DeepSeek)
set ANTHROPIC_API_KEY=sk-ant-xxx

# Initialize config
deskmind init

# Preview what AI would do
deskmind run --rule "按类型整理" --preview

# Execute
deskmind run --rule "按类型整理"

# Undo if needed
deskmind undo
```

## Zone Organization

```bash
# Group files into zone-named folders
deskmind run --rule "游戏放右上角，工作文档放左边，截图放右下角"
```

Available zones: `top-left`, `top-center`, `top-right`, `middle-left`, `center`, `middle-right`, `bottom-left`, `bottom-center`, `bottom-right`, or custom names.

## Claude Integration (MCP Server)

### Claude Desktop

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "deskmind": {
      "command": "deskmind",
      "args": ["mcp"]
    }
  }
}
```

Then in Claude Desktop, just say:
> *"Scan my desktop and organize files, put games in the top-right zone"*

### Claude Code

Add to `.claude/settings.json`:

```json
{
  "mcpServers": {
    "deskmind": {
      "command": "deskmind",
      "args": ["mcp"]
    }
  }
}
```

## Structured Rules (YAML)

Edit `~/.deskmind/rules.yaml`:

```yaml
rules:
  - name: Documents
    folder: Documents
    include: ["*.pdf", "*.docx", "*.txt"]
    action: move

  - name: Images
    folder: Images
    include: ["*.png", "*.jpg", "*.gif"]
    action: move

  - name: Old Archives
    folder: Archive
    include: ["*.zip"]
    age: "> 30d"
    action: archive
```

Structured rules are matched locally first (free, no API cost). Unmatched files go to the LLM.

## Multi-LLM Support

Edit `~/.deskmind/config.yaml`:

```yaml
llm:
  provider: claude           # claude | openai | deepseek | local
  api_key: sk-ant-xxx
  model: claude-sonnet-4-20250514
```

For local models (Ollama):

```yaml
llm:
  provider: local
  api_base: http://localhost:11434/v1
  model: qwen2.5:7b
```

## CLI Reference

| Command | Description |
|---------|-------------|
| `deskmind init` | Create default config and rules file |
| `deskmind run --rule "..."` | Scan and organize desktop |
| `deskmind run --rule "..." --preview` | Preview only, no changes |
| `deskmind list` | List desktop files |
| `deskmind undo` | Undo last organization |
| `deskmind mcp` | Start MCP Server for Claude |

## Development

```bash
git clone https://github.com/yourusername/deskmind.git
cd deskmind
uv pip install -e ".[dev]"
```

## License

MIT
