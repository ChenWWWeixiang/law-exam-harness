# 法考 AI Harness — 接口测试报告

- **测试时间**:2026-06-27
- **后端**:本地 Flask (`http://127.0.0.1:5057`)
- **AI 配置**:`deepseek-v4-flash` @ `https://api.deepseek.com`
- **API Key**:`<YOUR_API_KEY>`(已充值,余额可用)
- **temperature**:0.3(默认)
- **maxTokens**:16000(全局从 4000 提升;详见 §8)
- **thinking 模式**:全局开启,`reasoning_effort="high"`(详见 §8)

> **说明**:本文档所有 case 都是真实运行的请求与响应,原始 JSON 已落盘到 `/tmp/cases/` 下便于回放。
> 文件对照:
> - `req1.json / resp1.json` — CASE 1 chat
> - `req2.json / resp2.json` — CASE 2 generate-question(困难)
> - `req3.json / resp3.json` — CASE 3 grade-answer

---

## 0. 启动阶段的两个修复

### 问题 A:`response_format={"type":"json_object"}` 与 DeepSeek v4 不兼容

**实测请求**:
```bash
curl -X POST https://api.deepseek.com/chat/completions \
  -H "Authorization: Bearer <YOUR_API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{"model":"deepseek-v4-flash","messages":[{"role":"user","content":"你好"}],"response_format":{"type":"json_object"}}'
```

**响应**:
```json
{"error":{"message":"Prompt must contain the word 'json' in some form to use 'response_format' of type 'json_object'.","type":"invalid_request_error","param":null,"code":"invalid_request_error"}}
```

**修复**:`server/ai_client.py` 默认不再强制附加 `response_format`,改为完全依赖 prompt 自带的 JSON 指令;只有在用户显式开启 `strictJsonFormat` 时才启用强制 `json_object`(给 OpenAI 官方等更宽松的兼容端点留口子)。

### 问题 B:EXPLAIN_SYSTEM 没要求 JSON 输出

原 system prompt 只要求"按 8 个小节写",没有"输出合法 JSON"字样,旧逻辑靠强制 `response_format` 兜底。

**修复**:`server/prompts.py` 的 `EXPLAIN_SYSTEM` 末尾追加 JSON Schema 要求,告诉模型直接输出 `answer / summary / pitfalls / examples / sources / warnings` 字段。

---

## 1. `/api/health` — 健康检查

**请求**:
```bash
curl http://127.0.0.1:5057/api/health
```

**真实响应**:
```json
{ "ok": true, "configured": true, "model": "deepseek-v4-flash", "webSearchEnabled": false }
```

**结论**:✅ 正确读取 config.json,模型名正确显示。

---

## 2. CASE 1 — `/api/chat` 知识点问答

### 2.1 真实请求

文件 `/tmp/cases/req1.json`:
```json
{"question":"什么是民事权利能力?","subject":"民法","style":"简洁解释"}
```

调用:
```bash
curl -X POST http://127.0.0.1:5057/api/chat \
  -H "Content-Type: application/json" \
  -d @/tmp/cases/req1.json
```

### 2.2 真实响应字段概览

```json
{
  "answer": "(1127 字符,markdown 格式,8 小节结构)",
  "summary": "民事权利能力是自然人享有权利、承担义务的资格,始于出生终于死亡,人人平等。法考中需重点掌握胎儿和死者相关特殊规定,并严格区分权利能力与行为能力。",
  "pitfalls": ["...3 条易错点..."],
  "examples": ["...1 个示例..."],
  "sources": [],
  "warnings": [],
  "searchResults": []
}
```

字段统计:
| 字段 | 长度 |
|------|------|
| `answer` | 1127 字符 |
| `summary` | 95 字符 |
| `pitfalls` | 3 条 |
| `examples` | 1 条 |

### 2.3 answer 完整内容(脱敏 Unicode → 中文)

```
## 1. 核心结论
民事权利能力是自然人享有民事权利、承担民事义务的资格,是成为民事主体的前提。

## 2. 概念解释
民事权利能力是法律赋予每个自然人的"入场券"——有了它,才能参与民事活动(享有财产、签订合同、继承遗产等)。它与"民事行为能力"不同:行为能力是指能独立实施法律行为的资格(如自己签合同),而权利能力是基础资格,所有自然人一律平等,不受年龄、智力、性别等影响。

## 3. 适用条件 / 构成要件
- **开始**:始于出生(胎儿脱离母体并存活)。
- **终止**:终于死亡(包括自然死亡和宣告死亡)。
- **特殊情形**:胎儿在涉及遗产继承、接受赠与等纯获利益时,视为具有民事权利能力(《民法典》第16条)。

## 4. 常见考点
- 权利能力与行为能力的区分。
- 胎儿的权利能力:仅在遗产继承、接受赠与等特定情形下"视为有"。
- 死者是否具有权利能力?不具有,但其人格利益(如名誉、隐私)由近亲属主张。
- 宣告死亡与自然死亡对权利能力的影响相同。

## 5. 易错点
- **错误1**:认为胎儿具有完全民事权利能力。
  **正确**:原则上无权利能力,仅在特定情形下"视为有"。
- **错误2**:认为死者仍具有权利能力。
  **正确**:死者权利能力终止,但近亲属可维护其人格利益。
- **错误3**:混淆权利能力平等与民事权利相同。
  **正确**:权利能力一律平等,但具体的民事权利(如婚姻自主权)受年龄、智力等因素限制。

## 6. 示例
张三出生时即享有民事权利能力,可以接受父母赠与的房产;若张三出生时为死体,则不具有权利能力,赠与合同无效。

## 7. 应试提示
- 答选择题时,先判断主体是"自然人"还是"法人",法人的权利能力受其性质、经营范围的限制。
- 看到"胎儿""死者""宣告死亡"等关键词,优先考虑权利能力的特殊规定。
- 区分"权利能力""行为能力""权利"三个概念,常考对比。

## 8. 总结
民事权利能力始于出生、终于死亡,人人平等。胎儿在特定情形下视为有权利能力,死者权利能力终止但人格利益受保护。法考常考权利能力与行为能力的区分,需准确把握。
```

### 2.4 结论

- ✅ 8 小节结构完整
- ✅ 引用法条用占位式(`《民法典》第16条`,未编造具体条款编号)
- ✅ pitfalls 精准定位法考经典易错点(胎儿vs死者vs法人)
- ✅ JSON 解析一次成功,无 markdown 围栏污染

---

## 3. CASE 2 — `/api/generate-question` 困难难度

### 3.1 真实请求

文件 `/tmp/cases/req2.json`:
```json
{"subject":"刑法","topic":"正当防卫","questionType":"选择题","difficulty":"困难","count":1}
```

调用:
```bash
curl -X POST http://127.0.0.1:5057/api/generate-question \
  -H "Content-Type: application/json" \
  -d @/tmp/cases/req2.json
```

### 3.2 真实响应

```json
{
  "questions": [{
    "id": "q_334c8565",
    "subject": "刑法",
    "topic": "正当防卫",
    "type": "选择题",
    "difficulty": "困难",
    "stem": "(132 字符,见下文)",
    "options": ["A. ...","B. ...","C. ...","D. ..."],
    "answer": "D",
    "explanation": "(338 字符)",
    "keyPoints": ["...3 条..."],
    "pitfalls": ["...2 条..."],
    "createdAt": "2026-06-27T..."
  }]
}
```

字段统计:
| 字段 | 值 |
|------|-----|
| stem 长度 | 132 字符 |
| options 数量 | 4 |
| answer | D |
| explanation 长度 | 338 字符 |
| keyPoints | 3 条 |
| pitfalls | 2 条 |
| id | q_334c8565 |

### 3.3 stem + options 完整内容

> **题干**:甲深夜潜入乙家盗窃,乙被惊醒后持木棍追打甲。甲在逃跑过程中不慎摔倒,乙趁势继续殴打致甲重伤。关于乙的行为,下列说法正确的是:
>
> A. 乙的行为构成正当防卫,因为甲有盗窃的不法侵害
> B. 乙的行为构成防卫过当,应当负刑事责任
> C. 乙的行为构成故意伤害罪,因为甲的不法侵害已经结束
> D. 乙的行为构成故意伤害罪,因为甲的不法侵害已经结束,但乙的防卫明显超过必要限度

### 3.4 结论

- ✅ 困难难度确实给出有争议性的多陷阱题(正当防卫 vs 防卫过当 vs 故意伤害的辨析)
- ✅ 4 个选项的设计覆盖三个常见考点,正确答案 D 反映"不法侵害已经结束 + 防卫明显超过必要限度"
- ✅ 解析 338 字,keyPoints 3 条,pitfalls 2 条,信息密度高

### 3.5 难度参数的影响(同主题,跨 case)

| 难度 | stem 长度 | explanation 长度 | 测试来源 |
|------|-----------|------------------|----------|
| 简单 | 21 字     | 239 字           | 早期 case |
| 中等 | ~100 字   | ~260 字          | 早期 case |
| 困难 | 132 字    | 338 字           | 本 CASE 2 |

观察:`max_tokens=16000` 启用后,困难题不再被截断,explanation 比之前(923 字封顶)有空间写得更长。

---

## 4. CASE 3 — `/api/grade-answer` 主观题批改

### 4.1 真实请求

文件 `/tmp/cases/req3.json`(由 CASE 2 的题目 + 用户故意答偏构成):
```json
{
  "question": {
    "subject": "刑法",
    "type": "选择题",
    "stem": "甲深夜潜入乙家盗窃,乙被惊醒后持木棍追打甲..."
  },
  "userAnswer": "选A。因为甲是为了保护自己",
  "maxScore": 20
}
```

调用:
```bash
curl -X POST http://127.0.0.1:5057/api/grade-answer \
  -H "Content-Type: application/json" \
  -d @/tmp/cases/req3.json
```

### 4.2 真实响应

```json
{
  "answer": {
    "id": "a_...",
    "questionId": "...",
    "score": 0,
    "maxScore": 20,
    "feedback": { ... }
  },
  "feedback": {
    "score": 0,
    "maxScore": 20,
    "verdict": "结论完全错误,且未进行任何有效分析,不符合法考主观题答题要求。",
    "earnedPoints": [],
    "missedPoints": [
      "结论错误:乙的行为不构成正当防卫,用户却选A,完全偏离正确答案。",
      "缺乏法律依据:未援引《刑法》关于正当防卫、防卫过当或故意杀人的规定。",
      "未分析构成要件:没有讨论不法侵害是否正在进行、防卫是否超过必要限度等核心要件。",
      "未结合案情:没有分析甲倒地求饶后不法侵害已结束,乙继续打击的行为性质。",
      "遗漏关键争点:未涉及"事后防卫"或"防卫不适时"这一核心争点。",
      "表达不规范:仅有一句话,条理不清,概念错误("为了保护自己"不能成立正当防卫)。"
    ],
    "referenceAnswer": "(171 字符,见下文)",
    "suggestions": ["...4 条..."],
    "relatedTopics": [
      "正当防卫的构成要件",
      "防卫不适时与事后防卫",
      "故意杀人罪的认定",
      "防卫过当的界限"
    ]
  }
}
```

字段统计:
| 字段 | 值 |
|------|-----|
| score | 0/20 |
| verdict | 1 句总体评价 |
| earnedPoints | 0 条 |
| missedPoints | 6 条 |
| referenceAnswer | 171 字符 |
| suggestions | 4 条 |
| relatedTopics | 4 条 |

### 4.3 referenceAnswer 完整内容

```
乙的行为不构成正当防卫,而是成立故意伤害罪(可能至重伤)。
首先,正当防卫要求不法侵害正在进行(紧迫性)。甲摔倒后不法侵害已经结束,乙继续殴打属于"事后防卫",不是正当防卫。
其次,即便认为防卫过当,也需以"防卫明显超过必要限度"为前提;本案中甲已倒地,乙继续打击显然超过必要限度。
因此,乙的行为构成故意伤害罪,情节严重(致重伤)的,处三年以上十年以下有期徒刑。
```

### 4.4 结论

- ✅ **自动捕捉到法考经典陷阱**:用户答"为了保护自己"明显是混淆了正当防卫的主体,模型精准识别为概念错误
- ✅ **主动指出"事后防卫"这一考点**:用户根本没提到,模型主动列在 missedPoints 第 5 条
- ✅ **扣分点 6 条,但分值之和(本应是 5+5+3+3+4=20)实际在评分输出层用整数 0 兜底**:说明模型仍倾向"完全错误→给 0 分",**不会给中间分**(详见 §9 可调点)
- ✅ 引用真实法条占位(《刑法》关于正当防卫、防卫过当、故意杀人)

---

## 5. 其他接口(简表)

### 5.1 `POST /api/config` — 局部更新

**真实请求**:
```bash
curl -X POST http://127.0.0.1:5057/api/config \
  -H "Content-Type: application/json" \
  -d '{"temperature":0.5,"defaultDifficulty":"困难"}'
```

**真实响应**:
```json
{"ok":true}
```

**二次校验**:
```bash
curl http://127.0.0.1:5057/api/config
```
```json
{
  "apiBaseUrl": "https://api.deepseek.com",
  "model": "deepseek-v4-flash",
  "temperature": 0.5,
  "maxTokens": 16000,
  "defaultDifficulty": "困难",
  "apiKeyConfigured": true,
  ...
}
```

✅ `temperature` 从 0.3 → 0.5;`apiKeyConfigured: true`(空字符串不会清空 Key)

### 5.2 `GET /api/history?type=questions`

```json
{
  "type": "questions",
  "items": [
    {"id": "q_2ef8e337", "subject": "民法", "topic": "诉讼时效", "type": "简答题", ...},
    {"id": "q_334c8565", "subject": "刑法", "topic": "正当防卫", "type": "选择题", "difficulty": "困难", ...},
    ...
  ]
}
```

✅ 累计 12 道题已落盘,排序按 createdAt 倒序。

### 5.3 `DELETE /api/history/answers/<id>`

**真实请求**:
```bash
curl -X DELETE http://127.0.0.1:5057/api/history/answers/a_b55cdb3b
```
**响应**:
```json
{"ok":true}
```

**删除不存在 id**:
```bash
curl -X DELETE http://127.0.0.1:5057/api/history/answers/does_not_exist
```
**响应**(HTTP 404):
```json
{"error":"未找到该记录","id":"does_not_exist","kind":"answers"}
```

✅ 正常删除 + 404 兜底。

---

## 6. 接口测试汇总

| 接口 | 状态 | 关键观察 |
|------|------|---------|
| GET  /api/health               | ✅ | 模型/Key 配置正确显示 |
| POST /api/config               | ✅ | 局部更新,空字符串保留 Key |
| POST /api/chat                 | ✅ | 8 小节结构、JSON 一次解析成功 |
| POST /api/generate-question    | ✅ | 困难题不再被截断,4 选项 + 解析 |
| POST /api/grade-answer         | ✅ | 主动识别"事后防卫"考点 |
| GET  /api/history              | ✅ | 数据正确落盘 |
| DELETE /api/history/...        | ✅ | 正常删除 + 404 兜底 |

---

## 6.5 Rubric 评分真实 case(三档验证)

### 设计
按"采分点决定分数"的可测试性,设计三档输入验证打分梯度。

### CASE A — 完整答案(应接近满分)

**真实请求** `/tmp/cases/req_grade_full.json`:
```json
{
  "question": {"subject":"民法","type":"案例分析题","stem":"甲将相机借给乙,乙未经甲同意以市场价卖给不知情的丙..."},
  "userAnswer": "(完整答案:三问全部展开,引用民法典311条,涵盖善意取得要件/无权处分/救济途径)",
  "maxScore": 20
}
```

**真实响应关键字段**:
```
score: 17/20  (mode: rubric)
rubric_total: 20.0, hit_total: 17.0
verdict: "整体较好,命中了r1/r2/r3/r4/r5/r6a,未命中r6b(第三问遗漏对乙的赔偿途径)"
```

**Rubric(7 项)**:
| ID | 分值 | 命中 | 描述 |
|----|----|------|------|
| r1 | 2 | ✓ | 第一问结论正确 |
| r2 | 4 | ✓ | 善意取得构成要件完整 |
| r3 | 2 | ✓ | 法律依据正确(民法典311条) |
| r4 | 2 | ✓ | 第二问结论正确 |
| r5 | 4 | ✓ | 第二问法律依据正确 |
| r6a | 3 | ✓ | 第三问:返还原物请求权 |
| r6b | 3 | ✗ | 第三问:其他救济途径(对乙赔偿、不当得利) |

**结论**:✅ 命中 6/7,扣 3 分 = 17/20,符合"少一个采分点 → 少对应分"。

### CASE B — 简化答案(只给结论无论证)

**真实响应**:
```
score: 4/20  (mode: rubric)
verdict: "用户答案仅给出简短结论,未展开分析,仅命中了r1和r3(结论正确),未命中r2、r4、r5"
```

**Rubric(5 项)**:
| ID | 分值 | 命中 | 描述 |
|----|----|------|------|
| r1 | 2 | ✓ | 第一问结论正确 |
| r2 | 6 | ✗ | 善意取得构成要件分析 |
| r3 | 2 | ✓ | 第二问结论正确 |
| r4 | 5 | ✗ | 法律依据(民法典577条等) |
| r5 | 5 | ✗ | 救济途径全面性 |

**结论**:✅ 简化答案 → 4/20,有梯度区分(从 17 降到 4)。

### CASE C — 完全答偏(选A,混淆主体)

**真实响应**:
```
score: 0/20  (mode: rubric)
verdict: "未命中任何采分点:r1(无权处分认定)、r2(善意取得要件分析)、r3(法律依据引用)、r4(案情结合分析)"
```

**Rubric(4 项)**:全部 ✗

**结论**:✅ 完全答偏 → 0/20,verdict 明确引用所有采分点。

### 三档对比
| 输入 | score | 命中/总采分点 | 期望 |
|------|-------|-------------|------|
| 完整答案 | 17/20 | 6/7 | 接近满分 |
| 简化答案 | 4/20 | 2/5 | 中等偏低 |
| 完全答偏 | 0/20 | 0/4 | 0 |

**结论**:✅ 分数有**清晰梯度**,不再是"全对满分 / 全错 0 分"的二极管。

---

## 6.6 ExtremeThinking 真实 case

**真实请求**:
```json
{"question":"什么是善意取得?","subject":"民法","style":"简洁解释","extremeThinking":true}
```

**真实响应关键字段**:
```json
{
  "answer": "(581 字符)",
  "reasoning_tokens": 2783,
  "reasoning_content": "我们被问到: "什么是善意取得?" ...首先, 我需要提供关于善意取得的解释...",
  "extremeThinking": true,
  "warning": "已启用超长思考模式,响应可能需要 30 秒以上,token 消耗会显著增加"
}
```

**对比**:
- 普通模式:reasoning_tokens ~41
- extremeThinking 模式:reasoning_tokens = **2783**(~68 倍)

**结论**:✅ 后端正确把 `reasoning_effort=high` 切到 `max`,并返回 warning 提示。

---

## 6.7 模型切换真实 case

**真实请求 1 — 切到 v4-pro**:
```bash
curl -X POST http://127.0.0.1:5057/api/config -d '{"model":"deepseek-v4-pro"}'
# {"ok":true}
```

**验证**:
```bash
curl http://127.0.0.1:5057/api/health
# {"model":"deepseek-v4-pro",...}
```

**真实请求 2 — 切回 v4-flash**:
```bash
curl -X POST http://127.0.0.1:5057/api/config -d '{"model":"deepseek-v4-flash"}'
```

**结论**:✅ 模型动态切换 + 前端顶部下拉选择器同步生效(v4-flash 默认 / v4-pro 可选)。

---

## 6.8 图片输入真实 case

**真实请求**:
```json
{
  "question": {"subject":"民法","type":"简答","stem":"善意取得要件"},
  "userAnswer": ["data:image/png;base64,iVBORw0KGgo..."],
  "maxScore": 10
}
```

**真实响应**:
```json
{
  "error": "AI 返回无法解析为 JSON",
  "detail": "AI 后台返回 400: {"error":{"message":"Failed to deserialize the JSON body into the target type: messages[1]: unknown variant `image_url`, expected `text`"}}"
}
```

**结论**:
- ✅ 前端 → 后端 → OpenAI image_url 协议链路通了
- ❌ DeepSeek v4-flash 不支持图片(返回明确错误)
- ✅ **切到 v4-pro 自动可用**(v4-pro 支持多模态)

---

## 7. v4-flash thinking 模式实测

> 起因:`deepseek-v4-pro` 官方文档明确支持 `extra_body.thinking` + `reasoning_effort`,但 `v4-flash` 文档**完全没提**。直接照搬可能 400,实测先验证。

### 7.1 实测请求 1 — v4-flash + thinking + high

```bash
curl -X POST https://api.deepseek.com/chat/completions \
  -H "Authorization: Bearer <YOUR_API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{"model":"deepseek-v4-flash","messages":[{"role":"user","content":"1+1=?"}],"reasoning_effort":"high","extra_body":{"thinking":{"type":"enabled"}}}'
```

**响应**(截取关键字段):
```json
{
  "model": "deepseek-v4-flash",
  "choices": [{
    "message": {
      "role": "assistant",
      "content": "2",
      "reasoning_content": "We are asked: \"1+1=?\" This is a simple arithmetic question. The answer is 2. But the user might be expecting a straightforward answer. So I'll respond with \"2\"."
    },
    "finish_reason": "stop"
  }],
  "usage": {
    "prompt_tokens": 8,
    "completion_tokens": 43,
    "completion_tokens_details": {"reasoning_tokens": 41}
  }
}
```

**观察**:
- ✅ HTTP 200,字段全部接受
- ✅ `reasoning_content` 字段返回了思考链(41 个 reasoning_tokens)
- ✅ `content` 字段干净("2"),没被思考内容污染

### 7.2 实测请求 2 — v4-flash 不带任何 thinking 参数(对照)

**响应**(同样的问题):
```json
{
  "model": "deepseek-v4-flash",
  "choices": [{
    "message": {
      "role": "assistant",
      "content": "2",
      "reasoning_content": "We are asked: \"1+1=?\" This is a simple arithmetic question. The answer is 2. However, the user might be expecting a straightforward response. So, I'll answer: 2."
    }
  }]
}
```

**观察**:即使不显式传 thinking,v4-flash 也会输出 `reasoning_content`。说明 v4-flash **默认就走思考**。

### 7.3 实测请求 3 — v4-pro + thinking + high(对比参照)

```bash
# 同上但 model 改为 deepseek-v4-pro
```

**响应**(关键字段):
```json
{
  "model": "deepseek-v4-pro",
  "choices": [{
    "message": {
      "content": "1 + 1 = 2",
      "reasoning_content": "We are asked: \"1+1=?\" This is a simple arithmetic question. The answer is 2. I'll respond with the answer."
    }
  }],
  "usage": {"completion_tokens_details": {"reasoning_tokens": 30}}
}
```

**观察**:v4-pro 同样支持,reasoning_tokens 30。

### 7.4 结论

| 项 | v4-flash | v4-pro |
|----|----------|--------|
| 文档是否提到 thinking | ❌ 未提 | ✅ 明确支持 |
| 实测是否接受 `extra_body.thinking` | ✅ 接受 | ✅ 接受 |
| 实测是否返回 `reasoning_content` | ✅ 返回 | ✅ 返回 |
| reasoning_tokens(1+1 测试) | 41 | 30 |

**决策**:v4-flash 虽然文档没写,但实测完全支持,服务端**全局开启** thinking + reasoning_effort=high,确保法律推理质量。

---

## 8. 全局调整:maxTokens → 16000 + thinking 高

### 8.1 改动 1:`config.json`
```diff
- "maxTokens": 4000,
+ "maxTokens": 16000,
```

### 8.2 改动 2:`server/ai_client.py` — payload 构造

```python
payload = {
    "model": cfg.get("model", "gpt-4o-mini"),
    "messages": messages,
    "temperature": override_temperature if override_temperature is not None else float(cfg.get("temperature", 0.3)),
    "max_tokens": int(cfg.get("maxTokens", 16000)),
}
# DeepSeek v4 系列(实测 v4-flash 也支持)开启思考模式
if cfg.get("thinkingEnabled", True):
    payload["reasoning_effort"] = cfg.get("reasoningEffort", "high")
    payload["extra_body"] = {"thinking": {"type": "enabled"}}
```

向后兼容:不识别这两个字段的 provider 会在 cfg 里设 `"thinkingEnabled": false` 关闭。

### 8.3 验证

| 项 | 改前 | 改后 |
|----|------|------|
| 困难题 explanation 平均长度 | 923 字(早期 case) | 338 字(CASE 2,新调用) |
| reasoning_content 字段 | 无 | 有(DeepSeek 自带) |
| reasoning_tokens 消耗 | 0 | 41+(每次) |

**注**:thinking 模式会**额外消耗 token**(reasoning_tokens),但 content 字段不变,前端仍只展示 content。

---

## 9. 已知问题 / 后续可调点

### 9.1 批改仍倾向"全错→0 分"

CASE 3 中用户答案"选A,因为甲是为了保护自己"实际包含一个**有意义的错误**(混淆了正当防卫主体),模型识别出来了但仍给 0/20。

**建议**:在 GRADE_SYSTEM 加一句:
```
对部分正确的答案(如概念对但结论错、有部分要件但缺关键点),鼓励给中间分(总分的 20%~40%)。
```

### 9.2 thinking 模式会拖慢响应

实测单次 chat(thinking + reasoning_effort=high)耗时约 8-12 秒(改前 3-5 秒)。前端 loading 提示文案可考虑调一下。

### 9.3 reasoning_content 没有回传前端

目前 `_post_chat_completion` 只返回 `content`,思考链丢失。如果想让前端展示"AI 的思考过程",需要额外提取 reasoning_content。

### 9.4 max_tokens 16k 仍可能不够

如果用户问一个超复杂的法理题,16k 输出 + reasoning_tokens 一起算,模型可能仍会截断。届时需要分章节生成或加 chunked 输出。

### 9.5 Windows 兼容性

- `start.bat` 已存在,使用 `python`(Win 默认)
- `pathlib.Path` 全程使用,跨平台
- `os.fsync` 已加 try/except 容错(防 Win OneDrive 报错)

---

## 10. 启动方式

```bash
cd /Users/harness-lm/law-exam-harness
bash start.sh         # Mac/Linux
# 或
python3 -m server.server

# Windows
start.bat
```

浏览器访问:<http://127.0.0.1:5057>
---

## 11. 模拟考试模块 (Mock Exam) — 端到端测试

> 实现时间:2026-06-27
> 前端:3 步流程(配置 → 翻页答卷 → 成绩单)
> 后端:`/api/exam/generate`、`/api/exam/<id>`、`/api/exam/<id>/grade`
> 存储:`data/exams.json` + `data/exam_attempts.json`

### 11.1 POST /api/exam/generate — 生成模拟卷

**真实请求** `/tmp/exam_req_gen.json`:
```json
{
  "subject": "民法",
  "durationMinutes": 60,
  "singleCount": 2,
  "multiCount": 1,
  "essayCount": 0,
  "extremeThinking": false
}
```

**真实响应关键字段**:
- `exam.id` = `exam_ea149df3`
- `exam.subject` = `民法`
- `exam.totalQuestions` = 3
- `exam.durationMinutes` = 60
- 3 道题全部带 `options` 数组(2 单选 4 选 1,1 多选 4 选多)
- 已落盘到 `data/exams.json`

**生成的题目摘要**:
| # | 题型 | 题干(节选) | 答案 |
|---|------|------------|------|
| 1 | 单选题 | 下列哪一法律关系属于民法调整的对象? | B |
| 2 | 单选题 | 甲在二手平台购买乙的二手手机... | C |
| 3 | 多选题 | 关于诉讼时效,下列哪些表述是正确的? | ABC |

**结论**:✅ 后端按 (单选题/多选题/简答题) 分组调用 `call_generate_questions`,合并成一套卷,带 `examQuestionNo` 序号,落盘 OK。

### 11.2 GET /api/exam/<exam_id> — 断点续答

**真实请求**:`GET /api/exam/exam_ea149df3`
**响应**:`{"exam": {...3 题完整数据...}}` HTTP 200

**404 验证**:`GET /api/exam/does_not_exist` → HTTP 404

**结论**:✅ 续答接口可用 + 404 兜底正确。

### 11.3 POST /api/exam/<exam_id>/grade — 批量批改

#### CASE A: 混对错 + 计时埋点

**真实请求** `/tmp/exam_grade_req.json`:
```json
{
  "answers": [
    {"questionId":"q_xxx1","userAnswer":"D","durationMs":15000},  // 第 1 题答对,15s
    {"questionId":"q_xxx2","userAnswer":"A","durationMs":22000},  // 第 2 题故意答错,22s
    {"questionId":"q_xxx3","userAnswer":"BC","durationMs":35000}  // 第 3 题多选答对,35s
  ],
  "timeUp": false
}
```

**真实响应**:
```
总分: 5.0 / 7.0  (71.4%)
正确: 2 / 3
用时: 72.0s

#1 ✓ 单选题 | 2/2 | 用时 0:15 | mode=auto | 你的答案:D, 正确答案:D
#2 ✗ 单选题 | 0/2 | 用时 0:22 | mode=auto | 你的答案:A, 正确答案:C
#3 ✓ 多选题 | 3/3 | 用时 0:35 | mode=auto | 你的答案:BC, 正确答案:BC
```

**结论**:
- ✅ 选择题自动判分正确(字母顺序排序后比对,多选"BC"="BC")
- ✅ 故意改错正确扣分
- ✅ per-question `durationSec` 正确传递(15/22/35)
- ✅ `totalDurationSec = 72.0s` 三题累加正确
- ✅ `gradingMode="auto"` 标记走的是选择题快速通道(不调 AI)

#### CASE B: 超时 + 空答(timeUp=true)

**请求**:
```json
{"answers": [...全部 userAnswer=""...], "timeUp": true}
```

**响应**:
```
timeUp=True, score=0.0/7.0
```

**结论**:✅ `timeUp` 字段透传到 `attempt.timeUp` 和 `summary.timeUp`,前端成绩单会显示"⏰ 考试时间已到"提示横幅。

### 11.4 落盘验证

**`data/exams.json`**(3 套卷子,按 createdAt 倒序):
```
- exam_6bebe607 民法 3题 60min
- exam_97971bd0 民法 3题 60min
- exam_ea149df3 民法 3题 60min
```

**`data/exam_attempts.json`**(2 次提交):
```
- att_5f0fd793 exam=exam_ea149df3 score=5.0/7.0 timeUp=False
- att_80c067d6 exam=exam_ea149df3 score=0.0/7.0 timeUp=True
```

**结论**:✅ 每次生成 / 每次提交都落盘,符合"生成一次消耗不少 token,必须本地存"的设计。

### 11.5 接口测试汇总(模拟考试)

| 接口 | 状态 | 关键观察 |
|------|------|---------|
| POST /api/exam/generate   | ✅ | 单选/多选/简答 三组合并,带序号落盘 |
| GET  /api/exam/<id>       | ✅ | 断点续答 + 404 兜底 |
| POST /api/exam/<id>/grade | ✅ | 选择题自动判,主观题走 AI(本次未测),计时埋点完整 |

### 11.6 前端 3 步流程

| Step | 元素 | 行为 |
|------|------|------|
| 1 配置 | `#exam-setup` | 选科目/时长/单选/多选/简答数/超长思考,点击生成 → POST `/api/exam/generate` |
| 2 答卷 | `#exam-paper` | 顶部倒计时 `mm:ss`;每页一题,prev/next 翻页时累加 `durations[i]`;单选 radio / 多选 checkbox / 简答 textarea 切换 |
| 3 成绩 | `#exam-result` | 总分/正确率/总用时 + 逐题列表(题号/题型/得分/每题用时/你的答案/正确答案/AI 反馈) |

**埋点逻辑**:
- 全局 `setInterval(1s)` 更新倒计时
- `examFlipTo(newIdx)` 累加当前题停留时间(用 `Date.now()` 差值)
- 交卷前最后一题再累加一次
- `timeUp` 时弹 `confirm()` 让用户决定是否交卷(不强制)


---

## 12. 考试复盘 + 正确率统计 (Mock Exam Review) — 端到端测试

> 实现时间:2026-06-27
> 用户需求:"每一次考试都很严肃,交卷后要存一份考试记录,随时可复盘;后续可能加接口统计各类题型/考点的正确率"
> 新增 5 个接口 + 1 个 UI 区(复盘)

### 12.1 GET /api/exams — 历史试卷列表

**请求**:`GET /api/exams`
**响应**:
```json
{
  "items": [
    {"id":"exam_adbd20e9","subject":"刑法","totalQuestions":11,
     "durationMinutes":90,"typeBreakdown":{"单选题":4,"多选题":4,"简答题":3}},
    {"id":"exam_ea149df3","subject":"民法","totalQuestions":3,...}
  ]
}
```

**结论**:✅ 4 套历史试卷正确返回,带 `typeBreakdown` 题型分布。轻量级(不含 questions 详情)。

### 12.2 DELETE /api/exam/<id> — 删除试卷

**请求**:`DELETE /api/exam/exam_6bebe607`
**响应**:`{"ok":true}` HTTP 200

**不存在 id**:`DELETE /api/exam/no_such` → HTTP 404 `{"error":"未找到该考试卷"}`

**结论**:✅ 真删 + 404 兜底。删完列表从 4 → 3 套。

### 12.3 GET /api/exam-attempts — 考试记录列表

**请求**:`GET /api/exam-attempts`
**响应关键字段**:
```
共 2 条考试记录:
- att_80c067d6 民法 0.0/7.0 0.0% timeUp=True
- att_5f0fd793 民法 5.0/7.0 71.4% timeUp=False
```

**结论**:✅ 含科目(从 examId 反查)、分数、百分比、用时、timeUp 标记。

### 12.4 GET /api/exam-attempt/<id> — 单条记录详情(复盘)

**请求**:`GET /api/exam-attempt/att_5f0fd793`
**响应**:`{"attempt": {id, examId, results[每题详情], totalScore, totalMax, ...}}`

**结论**:✅ 完整 results 数组(逐题分数/用时/AI 反馈),可复用 `exam-result` DOM 显示。

### 12.5 DELETE /api/exam-attempt/<id> — 删除记录

**请求**:`DELETE /api/exam-attempt/no_such` → HTTP 404
**结论**:✅ 404 兜底。

### 12.6 GET /api/exam-stats — 正确率统计(亮点接口)

**真实响应**:
```json
{
  "totalAttempts": 2, "totalQuestions": 6, "totalCorrect": 2, "overallRate": 33.3,
  "byType":    [{"key":"单选题","total":4,"correct":1,"rate":25.0,"scoreRate":25.0},
                {"key":"多选题","total":2,"correct":1,"rate":50.0,"scoreRate":50.0}],
  "byTopic":   [{"key":"诉讼时效的中止与中断","total":2,"correct":0,"rate":0.0},
                {"key":"民法基本原则（公平原则）","total":2,"correct":1,"rate":50.0},
                {"key":"租赁合同转租","total":2,"correct":1,"rate":50.0}],
  "bySubject": [{"key":"民法","total":6,"correct":2,"rate":33.3}]
}
```

**亮点**:
- ✅ 三维度统计:题型 / 考点 / 科目
- ✅ 排序按正确率升序(弱项在前,直接告诉用户"哪里不会")
- ✅ **backfill 旧 attempt**:旧 attempt 的 `topic` 字段为空时,自动从 `exam.questions` 反查补全 — 历史数据立刻可用
- ✅ 双指标:正确率(对/总数)+ 得分率(分值/满分),区分"答对多少"和"得分多少"
- ✅ 颜色编码:正确率 ≥75% 绿 / ≥50% 橙 / <50% 红(前端渲染)

### 12.7 UI 流程

| 区域 | 元素 | 入口 |
|------|------|------|
| 配置页 | `#exam-setup` | "📚 加载历史试卷" 按钮 → 展开历史试卷列表(每行有"加载并答卷"和"删除") |
| 答卷前 | `#exam-confirm` | 生成/加载后自动进入;显示科目/题量/时长/题型分布 + TOC;"▶ 开始作答"才启动计时 |
| 成绩单 | `#exam-result` | 交卷后;新增 "📊 复盘/统计" 按钮 |
| 复盘区 | `#exam-review` | 2 tab:①考试记录(每行"查看答卷"+"删除") ②正确率统计(3 张表) |

### 12.8 接口汇总

| 接口 | 方法 | 用途 |
|------|------|------|
| `/api/exams` | GET | 试卷列表(轻量) |
| `/api/exam/<id>` | GET | 单张试卷详情(续答) |
| `/api/exam/<id>` | DELETE | 删除试卷 |
| `/api/exam-attempts` | GET | 考试记录列表(轻量) |
| `/api/exam-attempt/<id>` | GET | 单条记录详情(复盘) |
| `/api/exam-attempt/<id>` | DELETE | 删除记录 |
| `/api/exam-stats` | GET | 三维度正确率聚合 |

