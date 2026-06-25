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
from . import db

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
        # question 可以是 str 或 list(含 data:image/... 的图片)
        raw_question = body.get("question")
        if isinstance(raw_question, list):
            question = [x for x in raw_question if x]
            if not question:
                return jsonify({"error": "问题不能为空"}), 400
        else:
            question = (raw_question or "").strip()
            if not question:
                return jsonify({"error": "问题不能为空"}), 400

        subject = body.get("subject", "不限科目")
        style = body.get("style", "简明解释")
        use_search = bool(body.get("webSearch"))
        conversation_id = body.get("conversationId")
        extreme_thinking = bool(body.get("extremeThinking"))

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
            extreme_thinking=extreme_thinking,
        )

        # 超长思考模式提示
        if extreme_thinking:
            result["extremeThinking"] = True
            result["warning"] = "已启用超长思考模式,响应可能需要 30 秒以上,token 消耗会显著增加"

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

        extreme_thinking = bool(body.get("extremeThinking"))
        questions = ai_client.call_generate_questions(
            subject=subject,
            topic=topic,
            question_type=qtype,
            difficulty=difficulty,
            count=count,
            history_summaries=history,
            cfg=cfg,
            extreme_thinking=extreme_thinking,
        )
        storage.append_questions(questions)
        resp = {"questions": questions}
        if extreme_thinking:
            resp["extremeThinking"] = True
            resp["warning"] = "已启用超长思考模式,响应可能需要 30 秒以上"
        return jsonify(resp)

    # ---- 批改 ----
    @app.post("/api/grade-answer")
    def grade_answer():
        body = request.get_json(silent=True) or {}
        question = body.get("question") or {}
        # userAnswer 可以是 str 或 list[str](含 data:image/... 的图片)
        raw_answer = body.get("userAnswer")
        if isinstance(raw_answer, list):
            user_answer = [x for x in raw_answer if x]
            if not user_answer:
                return jsonify({"error": "用户答案不能为空"}), 400
        else:
            user_answer = (raw_answer or "").strip()
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
        extreme_thinking = bool(body.get("extremeThinking"))
        qtype = question.get("type", "")

        # 选择题走 auto-grade(法考标准:单选严格,多选少选/多选/错选=0分)
        # 走 AI 反而会让模型以为用户在"答主观题"而扣分,逻辑错误。
        if storage.is_choice_question(qtype) and not isinstance(user_answer, list):
            is_correct, score, actual_max = storage.grade_choice_answer(question, user_answer)
            feedback = {
                "score": score,
                "maxScore": actual_max,
                "verdict": ("✓ 答对" if is_correct else "✗ 答错"),
                "rubric": [],
                "earnedPoints": ([{"id": "answer", "points": actual_max, "criterion": "选项完全正确"}] if is_correct else []),
                "missedPoints": ([] if is_correct else [{"id": "answer", "points": actual_max, "criterion": f"标准答案: {question.get('answer', '')},你的答案: {user_answer}"}]),
                "referenceAnswer": question.get("answer", ""),
                "suggestions": [],
                "relatedTopics": [question.get("topic", "")] if question.get("topic") else [],
                "userAnswerAnalysis": (
                    "答案完全正确。"
                    if is_correct else
                    f"法考多选题标准:少选/多选/错选均不得分。你的答案 '{user_answer}' 与正确答案 '{question.get('answer', '')}' 不完全一致。"
                    if qtype == "多选题" else
                    f"你的答案 '{user_answer}' 与正确答案 '{question.get('answer', '')}' 不一致。"
                ),
                "gradingMode": "auto",
            }
        else:
            # 主观题(含简答/案例分析/论述)走 AI 批改
            feedback = ai_client.call_grade_answer(
                question=question,
                user_answer=user_answer,
                max_score=max_score,
                rubric=rubric,
                cfg=cfg,
                extreme_thinking=extreme_thinking,
            )
            feedback["gradingMode"] = "ai"

        from .storage import gen_id
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        attempt_id = gen_id("att")
        score = feedback.get("score", 0)
        actual_max = feedback.get("maxScore", max_score)
        attempt_record = {
            "id": attempt_id,
            "mode": "free",
            "question_id": question.get("id", ""),
            "user_answer": user_answer,
            "duration_ms": 0,
            "score": score,
            "max_score": actual_max,
            "is_correct": (score >= actual_max * 0.6) if actual_max else False,
            "rubric_hits": feedback.get("rubric", []),
            "ai_verdict": feedback.get("verdict", ""),
            "reference_answer": feedback.get("referenceAnswer", ""),
            "submitted_at": now,
        }
        storage.append_attempt(attempt_record)

        # 兼容旧 answer 字段(给前端历史 tab 用)
        answer_record = {
            "id": attempt_id,
            "questionId": question.get("id", ""),
            "answeredAt": now,
            "userAnswer": user_answer,
            "score": feedback.get("score", 0),
            "maxScore": feedback.get("maxScore", max_score),
            "feedback": feedback,
        }

        if add_to_mistakes:
            storage.append_mistake({
                "id": gen_id("m"),
                "attemptId": attempt_id,
                "addedAt": now,
                "reason": feedback.get("verdict", ""),
                "reviewed": False,
            })

        return jsonify({"answer": answer_record, "feedback": feedback, "attemptId": attempt_id})

    # ---- 历史 ----
    # ---- 模拟考试 ----
    @app.post("/api/exam/generate")
    def exam_generate():
        """生成一套完整模拟卷,落盘到 data/exams.json。"""
        body = request.get_json(silent=True) or {}
        subject = body.get("subject", "民法")
        # 配置:total=题量, 单选/多选/简答 数量分配
        try:
            single_n = int(body.get("singleCount", 8))
            multi_n = int(body.get("multiCount", 4))
            essay_n = int(body.get("essayCount", 3))
        except (TypeError, ValueError):
            single_n, multi_n, essay_n = 8, 4, 3
        try:
            duration_minutes = int(body.get("durationMinutes", 90))
        except (TypeError, ValueError):
            duration_minutes = 90
        avoid_duplicate = bool(body.get("avoidDuplicate"))
        extreme_thinking = bool(body.get("extremeThinking"))

        cfg = storage.load_config()

        # 三种题型分别生成,合并成一套卷
        from datetime import datetime, timezone
        from .storage import gen_id
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        exam_id = gen_id("exam")
        all_questions: list[dict] = []
        plan = [
            ("单选题", single_n, "民法基础"),
            ("多选题", multi_n, "民法重点"),
            ("简答题", essay_n, "民法案例分析"),
        ]
        for qtype, count, topic in plan:
            if count <= 0:
                continue
            # 拉历史题目用于避重
            history = (
                storage.question_summaries_for_dedup(subject, topic)
                if avoid_duplicate else []
            )
            qs = ai_client.call_generate_questions(
                subject=subject,
                topic=topic,
                question_type=qtype,
                difficulty="中等",
                count=count,
                history_summaries=history,
                cfg=cfg,
                extreme_thinking=extreme_thinking,
            )
            for q in qs:
                q["examQuestionNo"] = len(all_questions) + 1
                all_questions.append(q)

        # 给每道题加 exam 元数据 + 用 append_exam(会自动写 exam_questions 关联表)
        exam_record = {
            "id": exam_id,
            "subject": subject,
            "createdAt": now,
            "durationMinutes": duration_minutes,
            "totalQuestions": len(all_questions),
            "questions": all_questions,
            "config": {
                "singleCount": single_n,
                "multiCount": multi_n,
                "essayCount": essay_n,
                "extremeThinking": extreme_thinking,
            },
        }
        storage.append_exam(exam_record)
        # 回传用 get_exam_full 才能拿到 questions
        return jsonify({"exam": storage.get_exam_full(exam_id)})

    @app.get("/api/exam/<exam_id>")
    def exam_get(exam_id: str):
        """获取已生成的考试卷(用于断点续答)。"""
        exam = storage.get_exam_full(exam_id)
        if not exam:
            return jsonify({"error": "未找到该考试卷"}), 404
        return jsonify({"exam": exam})

    @app.get("/api/exams")
    def exam_list():
        """列出所有已生成的考试卷(元数据,不含 questions 详情)。"""
        exams = storage.list_exams()
        # 按 createdAt 倒序
        exams.sort(key=lambda x: x.get("createdAt", ""), reverse=True)
        items = [
            {
                "id": e.get("id"),
                "subject": e.get("subject"),
                "createdAt": e.get("createdAt"),
                "durationMinutes": e.get("durationMinutes"),
                "totalQuestions": e.get("totalQuestions"),
                # 题型分布
                "typeBreakdown": _count_types(e.get("questions", [])),
            }
            for e in exams
        ]
        return jsonify({"items": items})

    @app.delete("/api/exam/<exam_id>")
    def exam_delete(exam_id: str):
        """删除一张历史试卷。"""
        exams = storage.list_exams()
        new_exams = [e for e in exams if e.get("id") != exam_id]
        if len(new_exams) == len(exams):
            return jsonify({"error": "未找到该考试卷"}), 404
        storage.save_json(storage.DATA_FILES["exams"], new_exams)
        return jsonify({"ok": True})

    # ---- 考试记录(attempt)列表 + 详情 ----
    @app.get("/api/exam-attempts")
    def exam_attempts_list():
        """列出所有历史考试记录(轻量,不含 answers 详情)。"""
        attempts = storage.list_exam_attempts()
        attempts.sort(key=lambda x: x.get("submittedAt", ""), reverse=True)
        items = [
            {
                "id": a.get("id"),
                "examId": a.get("examId"),
                "subject": _lookup_exam_subject(a.get("examId")),
                "submittedAt": a.get("submittedAt"),
                "timeUp": a.get("timeUp", False),
                "totalScore": a.get("totalScore", 0),
                "totalMax": a.get("totalMax", 0),
                "percent": round(a.get("totalScore", 0) / a.get("totalMax", 1) * 100, 1) if a.get("totalMax") else 0,
                "totalDurationSec": round(a.get("totalDurationMs", 0) / 1000, 1),
                "questionCount": len(a.get("results", [])),
            }
            for a in attempts
        ]
        return jsonify({"items": items})

    @app.get("/api/exam-attempt/<attempt_id>")
    def exam_attempt_get(attempt_id: str):
        """获取单次考试记录详情(用于复盘)。"""
        attempts = storage.list_exam_attempts()
        target = next((a for a in attempts if a.get("id") == attempt_id), None)
        if not target:
            return jsonify({"error": "未找到该考试记录"}), 404
        return jsonify({"attempt": target})

    @app.delete("/api/exam-attempt/<attempt_id>")
    def exam_attempt_delete(attempt_id: str):
        """删除单次考试记录。"""
        attempts = storage.list_exam_attempts()
        new_attempts = [a for a in attempts if a.get("id") != attempt_id]
        if len(new_attempts) == len(attempts):
            return jsonify({"error": "未找到该考试记录"}), 404
        storage.save_json(storage.DATA_FILES["exam_attempts"], new_attempts)
        return jsonify({"ok": True})

    # ---- 正确率统计(按题型 / 考点 / 科目) ----
    @app.get("/api/exam-stats")
    def exam_stats():
        """聚合所有 attempts,按 type / topic / subject 三维度统计正确率(SQL JOIN)。"""
        return jsonify(storage.exam_stats())

    # ---- 新:详情接口(基于 SQLite JOIN) ----
    @app.get("/api/question/<qid>")
    def question_detail(qid: str):
        """题目详情(从 SQLite 直接拿)。"""
        q = storage.get_question(qid)
        if not q:
            return jsonify({"error": "未找到该题目"}), 404
        # 顺便带上该题的历史作答次数
        attempts = storage.list_attempts_for_question(qid)
        return jsonify({
            "question": q,
            "attemptCount": len(attempts),
            "attempts": attempts,
        })

    @app.get("/api/attempt/<aid>")
    def attempt_detail(aid: str):
        """单次作答详情(JOIN question 一次性返回)。"""
        a = storage.get_attempt_full(aid)
        if not a:
            return jsonify({"error": "未找到该作答"}), 404
        return jsonify({"attempt": a})

    @app.post("/api/exam/<exam_id>/grade")
    def exam_grade(exam_id: str):
        """批量批改一套模拟卷,返回总分和每题详情。"""
        body = request.get_json(silent=True) or {}
        user_answers = body.get("answers") or []  # [{questionId, userAnswer, durationMs}]
        time_up = bool(body.get("timeUp"))

        exam = storage.get_exam(exam_id)
        if not exam:
            return jsonify({"error": "未找到该考试卷"}), 404

        cfg = storage.load_config()
        from datetime import datetime, timezone
        from .storage import gen_id

        # 索引化
        q_by_id = {q["id"]: q for q in exam["questions"]}
        ua_by_id = {a.get("questionId"): a for a in user_answers if a.get("questionId")}

        results: list[dict] = []
        total_score = 0.0
        total_max = 0.0
        for q in exam["questions"]:
            ua = ua_by_id.get(q["id"], {})
            user_answer = ua.get("userAnswer", "")
            duration_ms = int(ua.get("durationMs", 0))
            qtype = q.get("type", "单选题")
            base_points = {"单选题": 2, "多选题": 3, "简答题": 10}.get(qtype, 5)
            total_max += base_points

            # 选择题自动判
            if qtype in ("单选题", "多选题"):
                std = (q.get("answer") or "").strip().upper()
                usr = (user_answer or "").strip().upper()
                # 简单比对:多选支持字母排序后比较
                is_correct = "".join(sorted(std.replace(",", "").replace(" ", "").split())) ==                              "".join(sorted(usr.replace(",", "").replace(" ", "").split())) if std and usr else False
                score = base_points if is_correct else 0
                total_score += score
                results.append({
                    "questionId": q["id"],
                    "examQuestionNo": q.get("examQuestionNo"),
                    "type": qtype,
                    "topic": q.get("topic", ""),
                    "stem": q.get("stem", ""),
                    "userAnswer": user_answer,
                    "correctAnswer": q.get("answer", ""),
                    "isCorrect": is_correct,
                    "score": score,
                    "maxScore": base_points,
                    "durationMs": duration_ms,
                    "durationSec": round(duration_ms / 1000, 1),
                    "explanation": q.get("explanation", ""),
                    "gradingMode": "auto",
                })
            else:
                # 主观题:走 AI 批改
                try:
                    fb = ai_client.call_grade_answer(
                        question=q,
                        user_answer=user_answer or "(未作答)",
                        max_score=base_points,
                        cfg=cfg,
                    )
                    score = fb.get("score", 0)
                    total_score += score
                    results.append({
                        "questionId": q["id"],
                        "examQuestionNo": q.get("examQuestionNo"),
                        "type": qtype,
                        "topic": q.get("topic", ""),
                        "stem": q.get("stem", ""),
                        "userAnswer": user_answer,
                        "correctAnswer": fb.get("referenceAnswer", ""),
                        "isCorrect": (score >= base_points * 0.6),
                        "score": score,
                        "maxScore": base_points,
                        "durationMs": duration_ms,
                        "durationSec": round(duration_ms / 1000, 1),
                        "explanation": q.get("explanation", ""),
                        "feedback": fb,
                        "gradingMode": "ai",
                    })
                except Exception as e:
                    results.append({
                        "questionId": q["id"],
                        "examQuestionNo": q.get("examQuestionNo"),
                        "type": qtype,
                        "stem": q.get("stem", ""),
                        "userAnswer": user_answer,
                        "score": 0,
                        "maxScore": base_points,
                        "durationMs": duration_ms,
                        "durationSec": round(duration_ms / 1000, 1),
                        "error": str(e),
                        "gradingMode": "failed",
                    })

        # 总时长统计
        total_duration_ms = sum(int(a.get("durationMs", 0)) for a in user_answers)

        attempt = {
            "id": gen_id("att"),
            "examId": exam_id,
            "submittedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "timeUp": time_up,
            "answers": user_answers,
            "results": results,
            "totalScore": total_score,
            "totalMax": total_max,
            "totalDurationMs": total_duration_ms,
        }
        storage.append_exam_attempt(attempt)

        return jsonify({
            "attempt": attempt,
            "summary": {
                "totalScore": total_score,
                "totalMax": total_max,
                "percent": round((total_score / total_max) * 100, 1) if total_max else 0,
                "correctCount": sum(1 for r in results if r.get("isCorrect")),
                "totalQuestions": len(results),
                "timeUp": time_up,
                "totalDurationSec": round(total_duration_ms / 1000, 1),
            },
        })

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

    @app.get("/api/session/<session_id>")
    def session_detail(session_id: str):
        """单条聊天会话详情(含完整消息列表)。"""
        # list_sessions 已经把消息组装好了,直接 find
        for s in storage.list_sessions():
            if s.get("id") == session_id:
                return jsonify({"session": s})
        return jsonify({"error": "未找到该会话"}), 404

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


def _count_types(questions: list[dict]) -> dict[str, int]:
    """统计题型分布,如 {'单选题': 8, '多选题': 4, '简答题': 3}。"""
    out: dict[str, int] = {}
    for q in questions:
        t = q.get("type", "其他")
        out[t] = out.get(t, 0) + 1
    return out


def _lookup_exam_subject(exam_id: str) -> str:
    """从 examId 反查科目;找不到返回空串。"""
    if not exam_id:
        return ""
    exam = storage.get_exam(exam_id)
    return exam.get("subject", "") if exam else ""


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
    # 落 SQLite(替代旧的 save_json 走 JSON 文件)
    storage._append_message(session_id, role, content, subject=subject, sources=sources or [])


if __name__ == "__main__":
    # 通过 `python -m server.server` 启动,以便相对导入正常工作
    app = create_app()
    host = "127.0.0.1"
    port = 5057
    log.info("法考 AI Harness 启动: http://%s:%s", host, port)
    app.run(host=host, port=port, debug=False)