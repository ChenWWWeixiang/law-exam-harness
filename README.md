# 法考 AI 学习 Harness

本地可运行、方便迁移的法考 AI 学习 App(对应需求文档 `gogogo.md` 第一阶段)。

## ✨ 核心特性

- 🤖 **多模型支持**:OpenAI / Claude / Gemini / DeepSeek / Ollama 等任意 OpenAI 兼容端点
- 🧠 **超长思考模式**:`reasoning_effort=max` + DeepSeek `thinking` 协议,法理推理更准
- 📷 **图片输入**:截图直接粘贴/上传,支持多模态模型(v4-pro)
- 🚫 **非法考内容拒绝**:无关问题 AI 直接拒绝,节省 token
- 📝 **模拟考试**:完整出卷 → 翻页答卷 → 计时埋点 → 批量批改 → 错题归档 → 复盘统计
- 📊 **SQLite 数据层**:7 张表,真外键真 JOIN,告别 JSON 行存储

## 启动

```bash
# Mac / Linux
bash start.sh

# Windows
start.bat
```

首次运行会自动:
1. 从 `config.example.json` 复制出 `config.json`(请填入 API Key)
2. 初始化 SQLite 数据库 `data/harness.db`
3. **首次自动迁移**(若存在旧 JSON 数据):`python -m server.migrate`

浏览器访问 <http://127.0.0.1:5057>

## 数据迁移(从 JSON 行存储到 SQLite)

如果是从早期版本升级,首次启动会自动检测并迁移旧 JSON 数据。也可手动跑:

```bash
python -m server.migrate
```

**幂等**:已迁移过的不会重复导入(检查 `schema_meta.migrated_from_json` 标记)。
迁移前会自动备份旧 JSON 到 `data/archive_<时间戳>/`。

数据文件结构:
```
data/
├── harness.db          # SQLite 数据库(7 张表,真外键)
├── harness.db-wal      # WAL 模式日志(并发读写更安全)
├── config.json         # API 配置
└── archive_<ts>/       # 迁移前自动备份的旧 JSON
    ├── questions.json
    ├── answers.json
    ├── mistakes.json
    ├── exams.json
    └── exam_attempts.json
```

### 7 张表(详见 [docs/SCHEMA.md](docs/SCHEMA.md))

| 表 | 作用 |
|------|------|
| `questions` | 题库(单一权威源) |
| `exams` | 试卷(只元数据) |
| `exam_questions` | 试卷↔题目关联,带 snapshot 防漂移 |
| `attempts` | 每次作答(自由练习 + 模拟考试都用) |
| `mistakes` | 错题(指向 attempt,能回看当时答错什么) |
| `chat_sessions` + `chat_messages` | 聊天 |
| `schema_meta` | 版本号 + 迁移标记 |

命令行直接看数据:
```bash
sqlite3 data/harness.db "SELECT id, score, max_score, is_correct FROM attempts ORDER BY submitted_at DESC LIMIT 10"
```

## 配置

`config.json` 字段说明:

| 字段 | 说明 |
|------|------|
| `apiBaseUrl` | OpenAI-compatible API 根 URL,如 `https://api.deepseek.com` |
| `apiKey` | API Key,**仅保存在本地,不会暴露给前端** |
| `model` | 模型名,如 `deepseek-v4-flash`、`deepseek-v4-pro`、`gpt-4o` |
| `temperature` | 0–1,默认 0.3 |
| `maxTokens` | 单次响应最大 token,默认 16000 |
| `webSearchEnabled` | 是否启用联网搜索 |
| `webSearchProvider` | 联网 provider,目前内置 `tavily` |
| `webSearchApiKey` | 联网搜索 API Key |

### 支持的后端 (OpenAI-compatible 协议)

- **OpenAI**: `apiBaseUrl=https://api.openai.com/v1`
- **DeepSeek**: `apiBaseUrl=https://api.deepseek.com`(注意不带 `/v1`)
- **Claude (Anthropic)**: Anthropic 提供的 OpenAI 兼容端点,或自建代理
- **Gemini**: Google 提供的 OpenAI 兼容端点,或自建代理
- **本地模型**: 任何兼容 OpenAI Chat Completions 的服务 (Ollama、vLLM 等)

## 主要功能

### 1. 知识点咨询(`#explain`)
- 4 种回答风格(简明/深入/举例/法考应试)
- 支持截图粘贴
- 智能识别"非法考内容"并拒绝,节省 token

### 2. 生成例题(`#generate`)
- 7 种题型,5 个难度
- 自动去重(基于历史题)
- 支持超长思考模式

### 3. 练习(`#practice`)
- **自由练习**:自由答题,AI 批改,可选加入错题本
- **模拟考试**:
  - 选择科目/题型/时长,生成完整模拟卷
  - **生成后先确认,不立刻计时**
  - 翻页答卷模式(每页一题,左右切换)
  - 全局倒计时 + 每题计时埋点
  - 时间到不强制交卷,弹窗询问
  - 交卷后批量批改(选择自动判、主观 AI 判)
  - 成绩单含每题用时、AI 反馈、参考答案

### 4. 历史记录 + 复盘(`#history` / 考试模块内)
- **题目库**:列出所有生成过的题,可直接"开始练习"
- **答题记录**:**点击"📖 展开完整答卷"看到题目正文 + 用户答案 + rubric + AI 反馈**(SQLite JOIN 一次拿全)
- **错题本**:指向 attempt,能回看"那次我答错了什么"
- **考试复盘**:查看历史考试的成绩单,每题详情
- **正确率统计**:按题型 / 考点 / 科目 三个维度聚合,弱项排序在前

## API 一览(详见 `docs/TEST_REPORT.md`)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查 + 当前模型 |
| GET/POST | `/api/config` | 读写 API 配置 |
| POST | `/api/chat` | 知识点咨询 |
| POST | `/api/generate-question` | 生成例题 |
| POST | `/api/grade-answer` | 批改主观题 |
| GET | `/api/question/<id>` | **题目详情 + 作答历史(JOIN)** |
| GET | `/api/attempt/<id>` | **作答详情 + 关联题目(JOIN)** |
| GET | `/api/history?type=...` | 列出历史记录 |
| DELETE | `/api/history/<kind>/<id>` | 删除记录 |
| POST | `/api/exam/generate` | 生成模拟卷 |
| GET | `/api/exam/<id>` | 取试卷(JOIN 关联表) |
| GET/DELETE | `/api/exam/<id>` | 列/删试卷 |
| GET | `/api/exams` | 试卷列表(轻量) |
| GET | `/api/exam-attempts` | 考试记录列表 |
| GET/DELETE | `/api/exam-attempt/<id>` | 单次考试详情/删除 |
| POST | `/api/exam/<id>/grade` | 批量批改 |
| GET | `/api/exam-stats` | 正确率三维度统计 |

## 目录结构

```
law-exam-harness/
├── app/                  前端 (原生 HTML/CSS/JS,无构建)
├── server/               Flask 后端
│   ├── server.py         路由入口
│   ├── ai_client.py      AI 调用 + reasoning_content 提取
│   ├── storage.py        数据访问层(SQLite)
│   ├── db.py             SQLite 连接 + schema 初始化
│   ├── migrate.py        旧 JSON → SQLite 一次性迁移
│   └── prompts.py        Prompt 模板
├── content/              预留:法条/教材笔记 (Markdown)
├── data/
│   ├── harness.db        SQLite 数据库(单一数据源)
│   ├── config.json       API 配置
│   └── archive_<ts>/     迁移前自动备份
├── config.example.json   配置模板
├── docs/
│   ├── SCHEMA.md         7 表 schema 设计文档
│   └── TEST_REPORT.md    接口测试报告
├── start.sh / start.bat  启动脚本
└── README.md
```

## 跨平台

- Win / Mac / Linux 同一份代码
- Python 3.9+ + Flask + openai + requests(其他都是标准库)
- SQLite 内置,**零外部数据库依赖**
- `os.fsync` 容错(Win 网盘同步目录场景)
- 路径全程 `pathlib`,不依赖平台分隔符

## 安全注意

- API Key 仅存储在本地 `config.json`,前端不会拿到
- 默认仅监听 `127.0.0.1`,不开放局域网
- 联网搜索结果作为不完全可信信息处理
- AI 回答仅供学习参考,重要法律问题请查阅正式法条与权威教材

## 后续扩展

参见需求文档第 12 节:权威资料库、RAG 检索、题库系统、学习计划、多模型支持。
Schema 已为以下扩展预留:
- 题目标签(`tags[]`):章节/法条/法考年份
- 试卷命名(`title`):用户可给卷子取名
- 错题复习模式:基于 mistakes 自动出重做卷

---
power by deepseek v4 flash + Minimax M3