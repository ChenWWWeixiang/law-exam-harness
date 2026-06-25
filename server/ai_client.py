"""AI 调用客户端 — 走 OpenAI-compatible Chat Completions 协议。

- 通过 config 中的 apiBaseUrl/apiKey/model 适配 OpenAI/Claude/Gemini/本地模型
- 强制要求返回结构化 JSON(给三类任务各自的 schema 提示)
- 解析失败重试一次(降低 temperature),二次失败抛出明确错误
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import requests

from . import prompts
from . import storage as _storage  # noqa: F401  # 用于 gen_id,datetime 等

log = logging.getLogger(__name__)


class AIError(Exception):
    """AI 调用或解析错误。"""

    def __init__(self, message: str, *, status_code: int = 502, detail: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail


# ---- 配置读取 ----

def load_runtime_config() -> dict:
    from .storage import load_config
    return load_config()


def is_configured(cfg: dict | None = None) -> bool:
    cfg = cfg if cfg is not None else load_runtime_config()
    return bool(cfg.get("apiKey")) and bool(cfg.get("apiBaseUrl")) and bool(cfg.get("model"))


# ---- 核心:OpenAI-compatible 调用 ----

def _post_chat_completion(
    messages: list[dict],
    *,
    response_format_json: bool = True,
    cfg: dict | None = None,
    override_temperature: float | None = None,
) -> str:
    """向 /chat/completions 发送请求,返回 assistant 的文本内容。"""
    cfg = cfg if cfg is not None else load_runtime_config()

    if not is_configured(cfg):
        raise AIError(
            "AI 尚未配置,请先在「设置」页填写 API Base URL / API Key / Model",
            status_code=400,
        )

    url = cfg["apiBaseUrl"].rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {cfg['apiKey']}",
        "Content-Type": "application/json",
    }
    payload: dict[str, Any] = {
        "model": cfg.get("model", "gpt-4o-mini"),
        "messages": messages,
        "temperature": (
            override_temperature
            if override_temperature is not None
            else float(cfg.get("temperature", 0.3))
        ),
        "max_tokens": int(cfg.get("maxTokens", 4000)),
    }
    # 多数 OpenAI-compatible 服务支持 response_format={"type":"json_object"}
    # 但部分代理不支持,故只在开启 response_format_json 时附带
    if response_format_json:
        payload["response_format"] = {"type": "json_object"}

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=60)
    except requests.RequestException as e:
        raise AIError(f"网络错误: {e}", status_code=502) from e

    if resp.status_code >= 400:
        # 截断返回体避免泄露太多细节
        snippet = (resp.text or "")[:500]
        raise AIError(
            f"AI 后台返回 {resp.status_code}: {snippet}",
            status_code=502 if resp.status_code >= 500 else 400,
        )

    try:
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
    except (KeyError, ValueError, IndexError) as e:
        raise AIError(f"AI 返回结构异常: {e}", status_code=502) from e

    if not isinstance(content, str):
        raise AIError("AI 返回内容不是字符串", status_code=502)

    return content


def _parse_json_with_retry(
    messages_factory,
    *,
    cfg: dict | None = None,
) -> dict:
    """让 messages_factory(temperature) -> messages,然后调用直到拿到合法 JSON。

    失败重试策略:第一次用 config 的 temperature,第二次降低 0.1。
    """
    cfg = cfg if cfg is not None else load_runtime_config()
    base_temp = float(cfg.get("temperature", 0.3))

    last_err: Exception | None = None
    last_raw: str = ""
    for attempt, temp in enumerate([base_temp, max(0.0, base_temp - 0.1)]):
        messages = messages_factory(temp)
        try:
            raw = _post_chat_completion(
                messages, response_format_json=True, cfg=cfg, override_temperature=temp
            )
        except AIError as e:
            last_err = e
            continue

        last_raw = raw
        parsed = _try_extract_json(raw)
        if parsed is not None:
            return parsed

    raise AIError(
        "AI 返回无法解析为 JSON",
        status_code=502,
        detail={"last_raw": last_raw[:500], "last_error": str(last_err)},
    )


def _try_extract_json(text: str) -> dict | None:
    """尝试从文本提取 JSON 对象;支持 markdown 围栏、附加前缀/后缀文本。"""
    if not text:
        return None
    text = text.strip()

    # 1) 直接解析
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass

    # 2) 去掉 markdown ```json 围栏
    fenced = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE | re.MULTILINE).strip()
    try:
        obj = json.loads(fenced)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass

    # 3) 提取首个 { ... } 块
    m = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if m:
        try:
            obj = json.loads(m.group(0))
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            pass

    return None


# ---- 三个对外业务接口 ----

def call_explain(
    *,
    subject: str,
    question: str,
    style: str,
    web_search_results: list[dict] | None = None,
    cfg: dict | None = None,
) -> dict:
    """知识点咨询。返回 {answer, summary, pitfalls, examples, sources, warnings}。"""
    cfg = cfg if cfg is not None else load_runtime_config()

    if web_search_results:
        lines = ["\n以下为联网搜索结果(可能不完全准确):"]
        for i, r in enumerate(web_search_results, 1):
            lines.append(f"[来源 {i}] {r.get('title','')} - {r.get('url','')}\n  {r.get('snippet','')[:300]}")
        search_block = "\n".join(lines)
    else:
        search_block = "(未启用联网搜索)"

    user_text = prompts.EXPLAIN_USER_TEMPLATE.format(
        subject=subject or "不限科目",
        style=style or "简明解释",
        question=question.strip(),
        search_block=search_block,
    )

    def make_messages(temp: float):
        return [
            {"role": "system", "content": prompts.EXPLAIN_SYSTEM},
            {"role": "user", "content": user_text},
        ]

    parsed = _parse_json_with_retry(make_messages, cfg=cfg)

    # 兼容两种返回形态:严格 JSON 字段 或 整篇 markdown
    if "answer" in parsed:
        return {
            "answer": parsed.get("answer", ""),
            "summary": parsed.get("summary", ""),
            "pitfalls": parsed.get("pitfalls", []),
            "examples": parsed.get("examples", []),
            "sources": parsed.get("sources", []),
            "warnings": parsed.get("warnings", []),
        }

    # 兜底:把整段 JSON 当 markdown 返回
    fallback = parsed.get("content") or json.dumps(parsed, ensure_ascii=False)
    return {
        "answer": fallback,
        "summary": "",
        "pitfalls": [],
        "examples": [],
        "sources": [r.get("url", "") for r in (web_search_results or []) if r.get("url")],
        "warnings": [],
    }


def call_generate_questions(
    *,
    subject: str,
    topic: str,
    question_type: str,
    difficulty: str,
    count: int,
    history_summaries: list[str] | None = None,
    cfg: dict | None = None,
) -> list[dict]:
    """例题生成。返回题目字典列表(已分配 id、createdAt)。"""
    cfg = cfg if cfg is not None else load_runtime_config()

    if history_summaries:
        history_block = "以下为该科目与知识点下已有的题目摘要,请避免重复或高度相似:\n" + "\n".join(
            f"- {s}" for s in history_summaries
        )
    else:
        history_block = "(暂无历史题目)"

    user_text = prompts.GENERATE_USER_TEMPLATE.format(
        subject=subject or "不限科目",
        topic=topic or "通用",
        question_type=question_type or "案例分析题",
        difficulty=difficulty or "中等",
        count=count,
        history_block=history_block,
    )

    schema_hint = (
        '{"questions":[{"subject":"","topic":"","type":"","difficulty":"",'
        '"stem":"","options":[],"answer":"","explanation":"",'
        '"keyPoints":[],"pitfalls":[]}]}'
    )

    def make_messages(temp: float):
        return [
            {"role": "system", "content": prompts.GENERATE_SYSTEM},
            {"role": "user", "content": user_text + "\n\n请输出形如: " + schema_hint},
        ]

    parsed = _parse_json_with_retry(make_messages, cfg=cfg)
    questions = parsed.get("questions", [])
    if not isinstance(questions, list):
        raise AIError("AI 返回的 questions 字段不是数组", status_code=502)

    # 兜底:补字段
    from .storage import gen_id
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for q in questions:
        q.setdefault("id", gen_id("q"))
        q.setdefault("subject", subject)
        q.setdefault("topic", topic)
        q.setdefault("type", question_type)
        q.setdefault("difficulty", difficulty)
        q.setdefault("options", [])
        q.setdefault("keyPoints", [])
        q.setdefault("pitfalls", [])
        q.setdefault("createdAt", now)
    return questions


def call_grade_answer(
    *,
    question: dict,
    user_answer: str,
    max_score: int,
    rubric: str = "",
    cfg: dict | None = None,
) -> dict:
    """批改。返回 {score, maxScore, verdict, earnedPoints, missedPoints, ...}。"""
    cfg = cfg if cfg is not None else load_runtime_config()

    rubric_block = f"评分标准/补充说明:\n{rubric.strip()}" if rubric and rubric.strip() else "(无额外评分标准)"
    user_answer_block = f"用户答案:\n{user_answer.strip()}"

    user_text = prompts.GRADE_USER_TEMPLATE.format(
        subject=question.get("subject", "不限科目"),
        question_type=question.get("type", "主观题"),
        max_score=max_score,
        stem=question.get("stem", "").strip(),
        user_answer_block=user_answer_block,
        rubric_block=rubric_block,
    )

    def make_messages(temp: float):
        return [
            {"role": "system", "content": prompts.GRADE_SYSTEM},
            {"role": "user", "content": user_text},
        ]

    parsed = _parse_json_with_retry(make_messages, cfg=cfg)

    # 字段兜底
    parsed.setdefault("score", 0)
    parsed.setdefault("maxScore", max_score)
    parsed.setdefault("verdict", "")
    parsed.setdefault("earnedPoints", [])
    parsed.setdefault("missedPoints", [])
    parsed.setdefault("userAnswerAnalysis", "")
    parsed.setdefault("referenceAnswer", "")
    parsed.setdefault("suggestions", [])
    parsed.setdefault("relatedTopics", [])

    # 评分钳制到 [0, maxScore]
    try:
        s = float(parsed["score"])
        s = max(0.0, min(float(max_score), s))
        parsed["score"] = int(s) if abs(s - int(s)) < 1e-6 else round(s, 1)
    except (TypeError, ValueError):
        parsed["score"] = 0

    return parsed