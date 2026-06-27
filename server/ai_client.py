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
        "max_tokens": int(cfg.get("maxTokens", 16000)),
    }
    # DeepSeek v4 系列(实测 v4-flash 也支持)开启思考模式:
    # - reasoning_effort:high → 让模型在思考阶段更用力
    # - extra_body.thinking.enabled:true → 显式开启思考链
    # 响应里会多一个 reasoning_content 字段,但 content 字段仍是干净的最终答案。
    # 对不识别这两个字段的 provider(如旧版 OpenAI / 一些本地代理)会被静默忽略或返回 400,
    # 此时可在 config.json 设 thinkingEnabled=false 关闭。
    thinking_enabled = cfg.get("thinkingEnabled", True)
    if thinking_enabled:
        # 支持 "extremeThinking": True 单次覆盖 → reasoning_effort=max
        if cfg.get("_extremeThinking"):
            payload["reasoning_effort"] = "max"
        else:
            payload["reasoning_effort"] = cfg.get("reasoningEffort", "high")
        payload["extra_body"] = {"thinking": {"type": "enabled"}}
        # extremeThinking 时也允许临时提高 max_tokens(默认 64k)
        if cfg.get("_extremeThinking"):
            payload["max_tokens"] = int(cfg.get("extremeMaxTokens", 128000))
    # 多数 OpenAI-compatible 服务支持 response_format={"type":"json_object"}
    # 但 DeepSeek v4-flash 等模型在开启 json_object 时要求 prompt 含 "json" 字样,
    # 且部分代理/OpenRouter 等不支持该字段。这里只把 JSON 要求交给 prompt 自己控制,
    # 解析层已有 markdown 围栏与首块 {...} 的兜底提取,所以更稳。
    # 如确实需要强制 json_object(兼容性更好的 OpenAI 官方模型),可通过 cfg 打开。
    use_strict_format = bool(cfg.get("strictJsonFormat")) if cfg else False
    if response_format_json and use_strict_format:
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
        msg = data["choices"][0]["message"]
        content = msg.get("content") or ""
        reasoning = msg.get("reasoning_content") or ""
    except (KeyError, ValueError, IndexError) as e:
        raise AIError(f"AI 返回结构异常: {e}", status_code=502) from e

    if not isinstance(content, str):
        raise AIError("AI 返回内容不是字符串", status_code=502)

    # 把 usage 里 reasoning_tokens 也带出来,前端可显示"本次思考消耗 X tokens"
    usage = data.get("usage", {}) if isinstance(data, dict) else {}
    reasoning_tokens = (
        usage.get("completion_tokens_details", {}).get("reasoning_tokens", 0)
        if isinstance(usage.get("completion_tokens_details"), dict)
        else 0
    )

    return {
        "content": content,
        "reasoning_content": reasoning,
        "reasoning_tokens": reasoning_tokens,
        "usage": usage,
    }


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
    last_result: dict | None = None
    for attempt, temp in enumerate([base_temp, max(0.0, base_temp - 0.1)]):
        messages = messages_factory(temp)
        try:
            result = _post_chat_completion(
                messages, response_format_json=True, cfg=cfg, override_temperature=temp
            )
        except AIError as e:
            last_err = e
            continue

        # result 现在是 dict {content, reasoning_content, reasoning_tokens, usage}
        raw = result.get("content", "") if isinstance(result, dict) else str(result)
        last_result = result if isinstance(result, dict) else None
        last_raw = raw
        parsed = _try_extract_json(raw)
        if parsed is not None:
            # 把 reasoning 信息挂在返回 dict 上,上层可选用
            if last_result:
                parsed["_reasoning_content"] = last_result.get("reasoning_content", "")
                parsed["_reasoning_tokens"] = last_result.get("reasoning_tokens", 0)
                parsed["_usage"] = last_result.get("usage", {})
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
    question,  # str 或 list[str](含 data:image/... 的图片,OpenAI image_url 协议)
    style: str,
    web_search_results: list[dict] | None = None,
    cfg: dict | None = None,
    extreme_thinking: bool = False,
    history_messages: list[dict] | None = None,
) -> dict:
    """知识点咨询。返回 {answer, summary, pitfalls, examples, sources, warnings, reasoning_content}。

    支持图片输入:question 可以传 list[str](含 data URL)。
    注意:DeepSeek v4-flash 当前不支持多模态,切换到 v4-pro 后自动可用。

    history_messages: 可选历史对话 [{role: user|assistant, content: str}, ...],
    若提供则按顺序注入到 system 之后、本次问题之前,让模型看到上下文。
    """
    cfg = cfg if cfg is not None else load_runtime_config()
    if extreme_thinking:
        cfg = {**cfg, "_extremeThinking": True}

    if web_search_results:
        lines = ["\n以下为联网搜索结果(可能不完全准确):"]
        for i, r in enumerate(web_search_results, 1):
            lines.append(f"[来源 {i}] {r.get('title','')} - {r.get('url','')}\n  {r.get('snippet','')[:300]}")
        search_block = "\n".join(lines)
    else:
        search_block = "(未启用联网搜索)"

    # 提取纯文本部分(供 prompt 模板用)
    if isinstance(question, list):
        text_parts = [x for x in question if isinstance(x, str) and not x.startswith("data:image")]
        text_question = "\n".join(text_parts).strip() or "用户上传了图片,请先识别图片内容再回答"
        has_images = any(isinstance(x, str) and x.startswith("data:image") for x in question)
    else:
        text_question = question.strip()
        has_images = False

    # 历史对话 → 注入到 user 消息的 history_block
    # 同时把每一对 user/assistant 作为单独的 message 追加,让模型看到完整多轮上下文
    history_messages = history_messages or []
    if history_messages:
        lines = ["以下是之前的对话历史,请基于此上下文继续回答本次提问:"]
        for m in history_messages:
            role = m.get("role")
            content = (m.get("content") or "").strip()
            if not content:
                continue
            label = "用户" if role == "user" else "AI"
            # 截断过长的历史,避免单次 prompt 膨胀
            if len(content) > 1500:
                content = content[:1500] + "…(已截断)"
            lines.append(f"[{label}]: {content}")
        history_block = "\n".join(lines)
    else:
        history_block = "(无历史对话)"

    user_text = prompts.EXPLAIN_USER_TEMPLATE.format(
        subject=subject or "不限科目",
        style=style or "简明解释",
        question=text_question,
        search_block=search_block,
        history_block=history_block,
    )

    def make_messages(temp: float):
        messages = [{"role": "system", "content": prompts.EXPLAIN_SYSTEM}]
        # 把历史 user/assistant 注入为多轮 message(在 system 之后、本次 user 之前)
        for m in history_messages:
            role = m.get("role")
            content = (m.get("content") or "").strip()
            if not content or role not in ("user", "assistant"):
                continue
            if len(content) > 1500:
                content = content[:1500] + "…(已截断)"
            messages.append({"role": role, "content": content})
        if has_images:
            # 多模态:OpenAI image_url 协议
            image_parts = [
                {"type": "image_url", "image_url": {"url": url}}
                for url in question
                if isinstance(url, str) and url.startswith("data:image")
            ]
            content = [{"type": "text", "text": user_text + "\n(用户上传了图片,请参考)"}] + image_parts
            messages.append({"role": "user", "content": content})
        else:
            messages.append({"role": "user", "content": user_text})
        return messages

    parsed = _parse_json_with_retry(make_messages, cfg=cfg)

    # 兼容两种返回形态:严格 JSON 字段 或 整篇 markdown
    base = {}
    if "answer" in parsed:
        base = {
            "answer": parsed.get("answer", ""),
            "summary": parsed.get("summary", ""),
            "pitfalls": parsed.get("pitfalls", []),
            "examples": parsed.get("examples", []),
            "sources": parsed.get("sources", []),
            "warnings": parsed.get("warnings", []),
        }
    else:
        # 兜底:把整段 JSON 当 markdown 返回
        fallback = parsed.get("content") or json.dumps(parsed, ensure_ascii=False)
        base = {
            "answer": fallback,
            "summary": "",
            "pitfalls": [],
            "examples": [],
            "sources": [r.get("url", "") for r in (web_search_results or []) if r.get("url")],
            "warnings": [],
        }

    # 透出 thinking 思考链给前端展示
    base["reasoning_content"] = parsed.get("_reasoning_content", "")
    base["reasoning_tokens"] = parsed.get("_reasoning_tokens", 0)
    # 透出相关性判定(非法考问题时给前端显示标准拒绝 banner)
    base["isRelevant"] = bool(parsed.get("isRelevant", True))
    if not base["isRelevant"]:
        # 兜底文案
        if not base.get("answer"):
            base["answer"] = "抱歉,这个问题与法考/法律学习无关,我无法回答。我只能帮你解答法律职业资格考试相关的知识点。"
        if not base.get("warnings"):
            base["warnings"] = ["问题与法考无关,本次未消耗 token 进行实质回答"]
    return base


def call_generate_questions(
    *,
    subject: str,
    topic: str,
    question_type: str,
    difficulty: str,
    count: int,
    history_summaries: list[str] | None = None,
    cfg: dict | None = None,
    extreme_thinking: bool = False,
) -> list[dict]:
    """例题生成。返回题目字典列表(已分配 id、createdAt)。"""
    cfg = cfg if cfg is not None else load_runtime_config()
    if extreme_thinking:
        cfg = {**cfg, "_extremeThinking": True}

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
        q["reasoning_content"] = parsed.get("_reasoning_content", "")
        q["reasoning_tokens"] = parsed.get("_reasoning_tokens", 0)
    return questions


def call_grade_answer(
    *,
    question: dict,
    user_answer: str,
    max_score: int,
    rubric: str = "",
    cfg: dict | None = None,
    extreme_thinking: bool = False,
) -> dict:
    """批改。返回 {score, maxScore, verdict, rubric, earnedPoints, missedPoints, ..., reasoning_content}。"""
    cfg = cfg if cfg is not None else load_runtime_config()
    if extreme_thinking:
        cfg = {**cfg, "_extremeThinking": True}

    rubric_block = f"评分标准/补充说明:\n{rubric.strip()}" if rubric and rubric.strip() else "(无额外评分标准)"

    # 构建 user 消息:支持纯文本 / 文本+图片 两种
    has_images = isinstance(user_answer, list) and any(
        isinstance(x, str) and x.startswith("data:image") for x in user_answer
    )

    if has_images:
        # 多模态消息:OpenAI image_url 协议
        text_parts = [x for x in user_answer if not (isinstance(x, str) and x.startswith("data:image"))]
        text_part = "\n".join(text_parts) if text_parts else "请批改用户上传的截图答案"
        image_parts = [
            {"type": "image_url", "image_url": {"url": url}}
            for url in user_answer
            if isinstance(url, str) and url.startswith("data:image")
        ]
        user_content = [{"type": "text", "text": f"用户答案(可能含截图):\n{text_part}"}] + image_parts
    else:
        # 纯文本路径
        text = user_answer.strip() if isinstance(user_answer, str) else "\n".join(user_answer or [])
        user_answer_block = f"用户答案:\n{text}"
        user_content = prompts.GRADE_USER_TEMPLATE.format(
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
            {"role": "user", "content": user_content},
        ]

    parsed = _parse_json_with_retry(make_messages, cfg=cfg)

    # 字段兜底
    parsed.setdefault("maxScore", max_score)
    parsed.setdefault("verdict", "")
    parsed.setdefault("earnedPoints", [])
    parsed.setdefault("missedPoints", [])
    parsed.setdefault("userAnswerAnalysis", "")
    parsed.setdefault("referenceAnswer", "")
    parsed.setdefault("suggestions", [])
    parsed.setdefault("relatedTopics", [])
    parsed.setdefault("rubric", [])

    # ===== 按 rubric 重算 score =====
    # 模型给的 score 字段不被信任,后端按 rubric.hit 项的 points 之和算最终分。
    # 这样既保证了"采分点决定分数"的可测试性,也能避免模型乱给 0 分。
    rubric_items = parsed.get("rubric") or []
    rubric_total = 0
    rubric_hit_total = 0
    for item in rubric_items:
        if not isinstance(item, dict):
            continue
        try:
            pts = float(item.get("points", 0))
        except (TypeError, ValueError):
            pts = 0
        rubric_total += pts
        if item.get("hit") and pts > 0:
            rubric_hit_total += pts

    # 校验 rubric 完整性:若 model 没返回 rubric,或总分对不上 max_score,
    # 降级用模型给的 score(并钳制),但 verdict 注明"未走结构化采分点"
    if not rubric_items or abs(rubric_total - max_score) > 0.5:
        # 兜底:用模型给的 score 钳制
        try:
            s = float(parsed.get("score", 0))
        except (TypeError, ValueError):
            s = 0
        s = max(0.0, min(float(max_score), s))
        parsed["score"] = int(s) if abs(s - int(s)) < 1e-6 else round(s, 1)
        parsed["_scoring_mode"] = "fallback"
        if not parsed.get("verdict"):
            parsed["verdict"] = "模型未返回结构化采分点,使用原 score 字段兜底"
    else:
        # 主路径:score = 命中采分点之和
        rubric_hit_total = max(0.0, min(float(max_score), rubric_hit_total))
        parsed["score"] = (
            int(rubric_hit_total)
            if abs(rubric_hit_total - int(rubric_hit_total)) < 1e-6
            else round(rubric_hit_total, 1)
        )
        parsed["_scoring_mode"] = "rubric"
        parsed["_rubric_total"] = rubric_total
        parsed["_rubric_hit_total"] = rubric_hit_total

    # 透出 thinking 思考链
    parsed["reasoning_content"] = parsed.get("_reasoning_content", "")
    parsed["reasoning_tokens"] = parsed.get("_reasoning_tokens", 0)

    # 透出相关性判定
    parsed["isRelevant"] = bool(parsed.get("isRelevant", True))

    return parsed