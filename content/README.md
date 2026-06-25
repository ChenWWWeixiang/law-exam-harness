# 学习内容目录 (占位)

第一阶段不内置权威法考资料库。本目录用于后续扩展:

```
content/
  civil-law/         民法
    contract.md
    property.md
  criminal-law/      刑法
    crime-constitution.md
    joint-crime.md
  administrative-law/ 行政法
  civil-procedure/   民诉
  criminal-procedure/ 刑诉
  commercial-law/    商经法
  theory-law/        理论法
  international-law/ 三国法
```

每个 Markdown 文件可包含:概念、构成要件、易错点、例题、笔记等结构化内容。

MVP 阶段通过 `/api/chat` 的 `subject` 字段选择科目,内容文件本身不影响 AI 回答 — 它们将在后续接入 RAG 检索时作为知识源被向量化与检索。