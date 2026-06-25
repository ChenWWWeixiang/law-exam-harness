"""法考 AI 学习 Harness - Flask 后端入口。

路由:
  GET  /api/health
  GET  /api/config
  POST /api/config
  POST /api/chat
  POST /api/generate-question
  POST /api/grade-answer
  GET  /api/history?type=questions|answers|mistakes|sessions
  DELETE /api/history/<kind>/<id>

静态资源:
  GET  /          -> app/index.html
  GET  /<path>    -> app/<path>
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

from . import ai_client
from . import storage

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("harness")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
APP_DIR = PROJECT_ROOT / "app"


def create_app() -> Flask:
    storage.ensure_data_files()
    app = Flask(__name__, static_folder=None)

    # ---- 错误处理 ----
    @app.errorhandler(ai_client.AIError)
    def handle_ai_error(e: ai_client.AIError):
        log.warning("AIError: %s", e)
        return jsonify({"error": str(e), "detail": e.detail}), e.status_code

    @app.errorhandler(404)
    def handle_404(e):
        # API 404 返回 JSON,前端路径返回 index.html(SPA 路由由前端 hash 处理)
        if request.path.startswith("/api/"):
            return jsonify({"error": "not found", "path": request.path}), 404
        return send_from_directory(APP_DIR, "index.html")

    @app.errorhandler(400)
    def handle_400(e):
        return jsonify({"error": str(e)}), 400

    @app.errorhandler(500)
    def handle_500(e):
        log.exception("500: %s", e)
        return jsonify({"error": "internal server error"}), 500

    # ---- 健康检查 ----
    @app.get("/api/health")
    def health():
        cfg = storage.load_config()
        return jsonify({
            "ok": True,
            "configured": ai_client.is_configured(cfg),
            "model": cfg.get("model", ""),
            "webSearchEnabled": bool(cfg.get("webSearchEnabled")),
        })

    # ---- 配置 ----
    @app.get("/api/config")
    def get_config():
        cfg = storage.load_config()
        # 不回传完整 API Key,仅返回是否已配置
        safe = dict(cfg)
        api_key = safe.pop("apiKey", "")
        web_key = safe.pop("webSearchApiKey", "")
        safe["apiKeyConfigured"] = bool(api_key)
        safe["webSearchApiKeyConfigured"] = bool(web_key)
        return jsonify(safe)

    @app.post("/api/config")
    def post_config():
        body = request.get_json(silent=True) or {}
        if not isinstance(body, dict):
            return jsonify({"error": "请求体必须是 JSON 对象"}), 400
        cfg = storage.load_config()
        # 允许部分字段更新;apiKey/webSearchApiKey 若传空字符串则保留原值
        for key, value in body.items():
            if key in ("apiKey", "webSearchApiKey") and (value is None or value == ""):
                continue
            cfg[key] = value
        storage.save_config(cfg)
        return jsonify({"ok": True})

    # ---- 知识点咨询 ----
    @app.post("/api/chat")
    def chat():
        body = request.get_json(silent=True) or {}
        question = (body.get("question") or "").strip()
        if not question:
            return jsonify({"error": "问题不能为空"}), 400

        subject = body.get("subject", "不限科目")
        style = body.get("style", "简明解释")
        use_search = bool(body.get("webSearch"))
        conversation_id = body.get("conversationId")

        # 联网搜索(可选)
        search_results: list[dict] = []
        cfg = storage.load_config()
        if use_search and cfg.get("webSearchEnabled") and cfg.get("webSearchApiKey"):
            from .search_client import do_search
            search_results = do_search(
                cfg.get("webSearchProvider", "tavily"),
                cfg.get("webSearchApiKey"),
                question,
                max_results=int(body.get("webSearchMaxResults", 5)),
            )

        result = ai_client.call_explain(
            subject=subject,
            question=question,
            style=style,
            web_search_results=search_results or None,
            cfg=cfg,
        )

        # 保存会话
        if conversation_id:
            _append_message(conversation_id, "user", question, subject=subject)
            _append_message(
                conversation_id,
                "assistant",
                result.get("answer", ""),
                subject=subject,
                sources=[r.get("url") for r in search_results if r.get("url")],
            )

        result["searchResults"] = search_results
        return jsonify(result)

    # ---- 例题生成 ----
    @app.post("/api/generate-question")
    def generate_question():
        body = request.get_json(silent=True) or {}
        subject = body.get("subject", "不限科目")
        topic = body.get("topic", "通用")
        qtype = body.get("questionType", "案例分析题")
        difficulty = body.get("difficulty", "中等")
        try:
            count = int(body.get("count", 1))
        except (TypeError, ValueError):
            count = 1
        count = max(1, min(count, 10))
        avoid_duplicate = bool(body.get("avoidDuplicate"))

        cfg = storage.load_config()
        history = (
            storage.question_summaries_for_dedup(subject, topic)
            if avoid_duplicate else []
        )

        questions = ai_client.call_generate_questions(
            subject=subject,
            topic=topic,
            question_type=qtype,
            difficulty=difficulty,
            count=count,
            history_summaries=history,
            cfg=cfg,
        )
        storage.append_questions(questions)
        return jsonify({"questions": questions})

    # ---- 批改 ----
    @app.post("/api/grade-answer")
    def grade_answer():
        body = request.get_json(silent=True) or {}
        question = body.get("question") or {}
        user_answer = (body.get("userAnswer") or "").strip()
        if not user_answer:
            return jsonify({"error": "用户答案不能为空"}), 400
        try:
            max_score = int(body.get("maxScore", 20))
        except (TypeError, ValueError):
            max_score = 20
        max_score = max(1, min(max_score, 100))
        rubric = body.get("rubric", "")
        add_to_mistakes = bool(body.get("addToMistakes"))

        cfg = storage.load_config()
        feedback = ai_client.call_grade_answer(
            question=question,
            user_answer=user_answer,
            max_score=max_score,
            rubric=rubric,
            cfg=cfg,
        )

        from .storage import gen_id
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        answer_record = {
            "id": gen_id("a"),
            "questionId": question.get("id", ""),
            "answeredAt": now,
            "userAnswer": user_answer,
            "score": feedback.get("score", 0),
            "maxScore": feedback.get("maxScore", max_score),
            "feedback": feedback,
        }
        storage.append_answer(answer_record)

        if add_to_mistakes:
            storage.append_mistake({
                "id": gen_id("m"),
                "questionId": question.get("id", ""),
                "addedAt": now,
                "reason": feedback.get("verdict", ""),
                "reviewed": False,
            })

        return jsonify({"answer": answer_record, "feedback": feedback})

    # ---- 历史 ----
    @app.get("/api/history")
    def history():
        kind = request.args.get("type", "questions")
        if kind == "questions":
            items = storage.list_questions()
        elif kind == "answers":
            items = storage.list_answers()
        elif kind == "mistakes":
            items = storage.list_mistakes()
        elif kind == "sessions":
            items = storage.list_sessions()
        else:
            return jsonify({"error": f"未知的 type: {kind}"}), 400
        # 按时间倒序
        items.sort(key=lambda x: x.get("createdAt") or x.get("answeredAt") or x.get("updatedAt") or x.get("addedAt") or "", reverse=True)
        return jsonify({"items": items, "type": kind})

    @app.delete("/api/history/<kind>/<item_id>")
    def delete_history(kind: str, item_id: str):
        ok = storage.delete_history_item(kind, item_id)
        if not ok:
            return jsonify({"error": "未找到该记录", "kind": kind, "id": item_id}), 404
        return jsonify({"ok": True})

    # ---- 静态资源(SPA) ----
    @app.get("/")
    def index():
        return send_from_directory(APP_DIR, "index.html")

    @app.get("/<path:filename>")
    def static_files(filename: str):
        # 防止跳出 app/ 目录
        target = (APP_DIR / filename).resolve()
        if APP_DIR.resolve() not in target.parents and target != APP_DIR.resolve():
            return jsonify({"error": "forbidden"}), 403
        if not target.exists() or not target.is_file():
            return send_from_directory(APP_DIR, "index.html")
        return send_from_directory(APP_DIR, filename)

    return app


def _append_message(session_id: str, role: str, content: str, *, subject: str = "", sources: list[str] | None = None) -> None:
    """追加一条会话消息,若 session 不存在则创建。"""
    sessions = storage.list_sessions()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    target = next((s for s in sessions if s.get("id") == session_id), None)
    if target is None:
        target = {
            "id": session_id,
            "createdAt": now,
            "updatedAt": now,
            "subject": subject or "不限科目",
            "messages": [],
        }
        sessions.append(target)
    target["updatedAt"] = now
    if subject:
        target["subject"] = subject
    msg = {"role": role, "content": content, "at": now}
    if sources:
        msg["sources"] = sources
    target["messages"].append(msg)
    storage.save_json(storage.DATA_FILES["sessions"], sessions)


if __name__ == "__main__":
    # 通过 `python -m server.server` 启动,以便相对导入正常工作
    app = create_app()
    host = "127.0.0.1"
    port = 5057
    log.info("法考 AI Harness 启动: http://%s:%s", host, port)
    app.run(host=host, port=port, debug=False)