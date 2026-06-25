# 法考 AI Harness — 数据 Schema 设计

> 7 张"表"(JSON 文件) + 轻量 join,不动数据库。
> 设计目标:消除数据冗余,支持"看回当时答题详情"和"按题目聚合统计"。

## 实体关系

```
                          Question
                          ────────
                          id (PK)
                          subject / topic
                          type / difficulty
                          stem / options / answer
                          explanation
                          rubric[]  ← 采分点(NEW)
                          keyPoints[] / pitfalls[]
                              ▲
                              │ (1:N)
                              │
            ┌─────────────────┼─────────────────┐
            │                 │                 │
       ExamQuestion       Attempt            Mistake
       (M:N 关联)         (一次作答)         (错题)
            │                 │                 │
            ▼                 ▼                 ▼
          Exam            ───►            (指向 attempt)
                       (attempt.exam_id 指 exam)
                       (自由练习时 exam_id = null)
```

## 7 张表

### 1. `questions.json` — 题库(单一权威源)

```json
{
  "id": "q_a1b2c3d4",
  "subject": "民法",
  "topic": "善意取得",       ← 细粒度考点(用于统计)
  "type": "单选题",
  "difficulty": "中等",
  "stem": "甲将相机借给乙...",
  "options": ["A. ...", "B. ...", "C. ...", "D. ..."],
  "answer": "B",
  "explanation": "...",
  "rubric": [                ← 采分点(主观题用;选择题可空)
    {"id": "r1", "points": 4, "criterion": "善意取得构成要件完整"},
    {"id": "r2", "points": 4, "criterion": "引用民法典311条"}
  ],
  "keyPoints": ["善意取得三要件"],
  "pitfalls": ["不能与无权代理混淆"],
  "createdAt": "2026-06-27T..."
}
```

### 2. `exams.json` — 试卷(只元数据)

```json
{
  "id": "exam_e5f6g7h8",
  "subject": "民法",
  "title": null,             ← 可选名字;默认 null = "{科目}模拟卷"
  "createdAt": "2026-06-27T...",
  "durationMinutes": 90,
  "totalQuestions": 15,
  "config": {                ← 生成时的配置快照(可复盘)
    "singleCount": 8,
    "multiCount": 4,
    "essayCount": 3,
    "extremeThinking": false
  }
}
```

### 3. `exam_questions.json` — 试卷↔题目关联(带 snapshot)

```json
{
  "examId": "exam_e5f6g7h8",
  "questionId": "q_a1b2c3d4",
  "examNo": 1,              ← 卷内题号
  "section": "一、单项选择题",  ← 章节标题(可选)
  "maxScore": 2,            ← 该题在此卷的分值(可与题目默认不同)
  "snapshot": {              ← 题目快照,防题库修改影响历史试卷
    "stem": "...",
    "options": [...],
    "answer": "B",
    "explanation": "..."
  }
}
```

**为何 snapshot**:题目可能重生成、修订;历史试卷应当冻结当时样子。

### 4. `attempts.json` — 每次作答(统一表)

```json
{
  "id": "att_x9y8z7w6",
  "mode": "free" | "exam",      ← 自由练习 / 模拟考试
  "examId": null | "exam_xxx",   ← free=null, exam=试卷 id
  "questionId": "q_xxx",         ← FK
  "examNo": null | 5,            ← 在卷内题号(自由练习无)
  "userAnswer": "...",
  "durationMs": 15000,
  "score": 4,                    ← 自由练习:满分 maxScore;exam:该题得分
  "maxScore": 20,
  "isCorrect": false,
  "rubricHits": [                ← 命中的采分点
    {"id": "r1", "hit": true},
    {"id": "r2", "hit": false}
  ],
  "aiVerdict": "结论完全错误...", ← AI 总评
  "referenceAnswer": "...",       ← AI 生成的参考答案(自由练习才存)
  "submittedAt": "2026-06-27T..."
}
```

**关键变化**:旧 `answers.json` + `exam_attempts.results[]` 合并成一张表。
- 自由练习:`examId=null`,`mode="free"`
- 模拟考试:每题一行,`examId="exam_xxx"`,`mode="exam"`;一次考试的所有 attempt 用相同 `examId` 查询得到

### 5. `mistakes.json` — 错题(指向 attempt)

```json
{
  "id": "m_xxx",
  "attemptId": "att_xxx",      ← 改!原 schema 是 questionId
  "addedAt": "...",
  "reason": "...",              ← 从 aiVerdict 复制
  "reviewed": false
}
```

**好处**:能展示"我那次答错了什么",而不是只看题面。

### 6. `sessions.json` — 聊天(不变)

### 7. (取消)`generated_questions.json` → 并入 `questions.json`

## 查询接口设计(storage 层)

| 函数 | 返回 | 用途 |
|------|------|------|
| `get_question(qid)` | Question | 详情 |
| `get_exam_full(eid)` | Exam + exam_questions[] + snapshot 展开 | 答卷/复盘 |
| `list_attempts_for_question(qid)` | Attempt[] | "我做过几次这题" |
| `list_attempts_for_exam(eid)` | Attempt[] | "这场考试我的全部作答" |
| `list_attempts(...)` | Attempt[] | 自由练习历史(可过滤 mode/时间) |
| `get_attempt_full(aid)` | Attempt + 关联 Question + exam_no | 复盘详情 |

## 迁移策略(零破坏)

1. 保留旧 `answers.json` / `exam_attempts.json` / `generated_questions.json` / `mistakes.json`(读兼容)
2. 新数据写入新表
3. 提供一次性 migration 脚本(可手动执行):把旧数据搬进新表
4. 旧文件保留 N 个版本后自动归档到 `data/archive/`

## 不变的部分

- ✅ `config.json` 不变
- ✅ JSON 文件存储(atomic write)不变
- ✅ 接口契约变化做向后兼容(老字段保留)
- ✅ 跨平台(Win/Mac/Linux)不变

## 后续可拓展(已为这些预留)

- 题目标签(tags[]):章节/法条/法考年份
- 试卷命名(title):用户可给卷子取名"民法冲刺 6 月"
- 答题快照:attempts 里保留 question 的 stem 摘要(查表快、不用 join)
- 错题复习模式:基于 mistakes 自动出重做卷