# 法考 AI 学习 Harness

本地可运行、方便迁移的法考 AI 学习 App(对应需求文档 `gogogo.md` 第一阶段)。

## 启动

```bash
# Mac / Linux
bash start.sh

# Windows
start.bat
```

首次运行会自动创建 `config.json`(从 `config.example.json` 复制),请编辑填入 API Key。

浏览器访问 <http://127.0.0.1:5057>

## 配置

`config.json` 字段说明:

| 字段 | 说明 |
|------|------|
| `apiBaseUrl` | OpenAI-compatible API 根 URL,如 `https://api.openai.com/v1` |
| `apiKey` | API Key,**仅保存在本地,不会暴露给前端** |
| `model` | 模型名,如 `gpt-4o-mini`、`claude-opus-4-7`、`gemini-1.5-pro` |
| `temperature` | 0–1,默认 0.3 |
| `maxTokens` | 单次响应最大 token,默认 4000 |
| `webSearchEnabled` | 是否启用联网搜索 |
| `webSearchProvider` | 联网 provider,目前内置 `tavily` |
| `webSearchApiKey` | 联网搜索 API Key |

### 支持的后端 (OpenAI-compatible 协议)

- **OpenAI**: `apiBaseUrl=https://api.openai.com/v1`
- **Claude (Anthropic)**: 使用 Anthropic 提供的 OpenAI 兼容端点,或自建代理
- **Gemini**: Google 提供的 OpenAI 兼容端点,或自建代理
- **本地模型**: 任何兼容 OpenAI Chat Completions 的服务 (Ollama、vLLM 等)

## 目录结构

```
law-exam-harness/
├── app/                  前端 (原生 HTML/CSS/JS,无构建)
├── server/               Flask 后端
├── content/              预留:法条/教材笔记 (Markdown)
├── data/                 运行时数据 (聊天/题目/答题/错题)
├── config.example.json   配置模板
├── start.sh / start.bat  启动脚本
└── README.md
```

## 迁移

整个项目目录复制到新机器即可,只需 Python 3.9+ 与 `pip install -r requirements.txt`。
`config.json` 与 `data/` 可单独保留或单独复制。

## 安全注意

- API Key 仅存储在本地 `config.json`,前端不会拿到
- 默认仅监听 `127.0.0.1`,不开放局域网
- 联网搜索结果作为不完全可信信息处理
- AI 回答仅供学习参考,重要法律问题请查阅正式法条与权威教材

## 后续扩展

参见需求文档第 12 节:权威资料库、RAG 检索、题库系统、学习计划、多模型支持。