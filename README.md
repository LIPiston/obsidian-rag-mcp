# obsidian-rag-mcp

一个基于 **MCP (Model Context Protocol)** 的 RAG 服务器：把 **Obsidian 笔记库**变成任何 AI 客户端（ZCode、Claude Desktop、Cursor、goose……）都可检索的知识库。

> 支持 MCP 的 AI 客户端会自动决定何时调用工具：先从你的 Obsidian 笔记中**语义检索**相关片段，再结合这些片段回答/分析——让你的笔记成为 AI 的「第二大脑」。

## ✨ 功能

- 📁 **读取 Obsidian vault**：扫描 `*.md` 笔记，自动忽略 `.obsidian`、`.trash`、`.git` 等隐藏目录
- 🧠 **可配置 Embedding 模型**：支持 OpenAI 兼容 API 与 Ollama 本地模型（也内置 `fake` 模式用于零依赖测试）
- 🔍 **语义检索**：纯 Python 余弦相似度，无需重型向量数据库
- 🧩 **MCP 标准协议**：stdio / SSE / streamable-http 三种传输，可接入任何 MCP 客户端
- 🔧 **7 个工具**：索引、搜索、RAG 检索、列笔记、读笔记、查配置、查索引状态

## 🛠 工具一览

| 工具 | 说明 |
|------|------|
| `obsidian_index(force)` | 扫描 vault 并构建/重建 embedding 索引 |
| `obsidian_search(query, top_k)` | 语义搜索笔记片段 |
| `obsidian_rag(question, top_k)` | 检索与问题最相关的笔记上下文（供分析） |
| `obsidian_list_notes(keyword)` | 列出 vault 中的笔记 |
| `obsidian_read_note(path)` | 读取单篇笔记全文（防路径穿越） |
| `obsidian_get_config()` | 查看当前配置（不含 API Key） |
| `obsidian_index_status()` | 检查索引是否存在且模型匹配 |

## 🚀 快速开始

### 1. 克隆并安装

```bash
git clone https://github.com/<your-org>/obsidian-rag-mcp.git
cd obsidian-rag-mcp
uv sync
```

### 2. 配置环境变量

在 MCP 客户端的服务器配置中设置（或在终端导出）：

| 变量 | 必填 | 说明 | 默认值 |
|------|------|------|--------|
| `OBSIDIAN_VAULT_PATH` | ✅ | Obsidian vault 的绝对路径 | — |
| `EMBEDDING_BASE_URL` | | Embedding API 地址（Ollama 用 `http://localhost:11434`） | 无地址且无 key 时为离线测试模式 |
| `EMBEDDING_MODEL` | | Embedding 模型名 | `text-embedding-3-small`（OpenAI 兼容） |
| `EMBEDDING_API_KEY` | OpenAI 兼容时必填 | API Key（Ollama 本地无需） | — |
| `EMBEDDING_PROVIDER` | | 手动覆盖后端识别 | 自动识别（openai / ollama / fake） |
| `OBSIDIAN_INDEX_PATH` | | 索引文件保存位置 | `~/.obsidian-rag/index.json` |
| `OBSIDIAN_CHUNK_SIZE` | | 分块字符数 | `1500` |
| `OBSIDIAN_MAX_NOTES` | | 最多索引的笔记数 | `1000` |

> **后端自动识别**：只需配置地址 + 模型 + key，无需指定 provider。
> 地址含 Ollama 默认端口 `11434` 或以 `/api` 结尾 → 自动按 Ollama 调用；
> 其他地址 → 自动按 OpenAI 兼容 `POST {base}/embeddings` 调用。
> 自动识别不满足需求时，可用 `EMBEDDING_PROVIDER=openai|ollama|fake` 手动覆盖。

### 3. 在客户端中注册

启动命令统一为（任意客户端都一样）：

```
uv run --directory D:/path/to/obsidian-rag-mcp obsidian-rag-mcp
```

```json
{
  "mcp": {
    "servers": {
      "obsidian-rag": {
        "command": "uv",
        "args": ["run", "--directory", "D:/path/to/obsidian-rag-mcp", "obsidian-rag-mcp"],
        "env": {
          "OBSIDIAN_VAULT_PATH": "D:/path/to/your/vault",
          "EMBEDDING_BASE_URL": "https://api.openai.com/v1",
          "EMBEDDING_MODEL": "text-embedding-3-small",
          "EMBEDDING_API_KEY": "<你的 key>"
        }
      }
    }
  }
}
```


> 其他 MCP 客户端（VS Code、Claude Code、Windsurf……）的注册格式大同小异，都是 `command` + `args` + `env` 三段式，照抄上面的结构即可。

### 4. 使用

注册并重启会话后，AI 会自动决定何时调用工具。你可以直接说：
> 「用我的 Obsidian 笔记分析一下这个方案的可行性」「检索我笔记里关于网站改版的内容」

## 📂 项目结构

```
obsidian-rag-mcp/
├── obsidian_rag/
│   ├── server.py       # MCP 服务器与工具定义
│   ├── config.py       # 环境变量配置
│   ├── embeddings.py   # OpenAI/Ollama/fake embedding 客户端
│   ├── vault.py        # vault 扫描与 markdown 分块
│   └── store.py        # 向量存储与余弦相似度检索
├── recipes/
│   └── obsidian-rag.yaml   # goose 专用 slash command recipe（可选）
├── examples/sample-vault/  # 示例笔记库
└── tests/
```

## 📄 License

MIT
