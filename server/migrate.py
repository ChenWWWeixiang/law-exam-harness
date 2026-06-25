"""一次性迁移脚本:把旧 JSON 行存储的数据搬到 SQLite。

用法:
    python -m server.migrate

幂等:已迁过的不会重复导入(检查 schema_meta 中 migrated_from_json 标记)。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from . import db, storage


def _read_json(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def _already_migrated() -> bool:
    # 先确保 schema 存在(否则查询会报错)
    db.init_schema()
    conn = db.get_conn()
    try:
        row = conn.execute(
            "SELECT value FROM schema_meta WHERE key='migrated_from_json'"
        ).fetchone()
        return row is not None and row["value"] == "1"
    finally:
        conn.close()


def _mark_migrated() -> None:
    conn = db.get_conn()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO schema_meta(key, value) VALUES('migrated_from_json', '1')"
        )
        conn.commit()
    finally:
        conn.close()


def migrate() -> dict:
    """执行迁移,返回统计 {questions, answers, mistakes, exams, exam_attempts}。"""
    if _already_migrated():
        print("✓ 已迁移过,跳过")
        return {"skipped": True}

    storage.ensure_data_files()

    stats = {"questions": 0, "answers": 0, "mistakes": 0, "sessions": 0, "exams": 0, "exam_attempts": 0}

    # 1. questions
    for q in _read_json(db.LEGACY_JSON_FILES["questions"]):
        storage.append_question(q)
        stats["questions"] += 1
    # 兼容老路径 generated_questions.json(原 storage.DATA_FILES["questions"])
    gen_q_path = db.DATA_DIR / "generated_questions.json"
    if gen_q_path.exists() and gen_q_path != db.LEGACY_JSON_FILES["questions"]:
        for q in _read_json(gen_q_path):
            storage.append_question(q)
            stats["questions"] += 1

    # 2. answers -> attempts(mode='free')
    for a in _read_json(db.LEGACY_JSON_FILES["answers"]):
        # 旧 schema 的 feedback 字段整包塞到 aiVerdict
        fb = a.get("feedback") or {}
        verdict = fb.get("verdict") if isinstance(fb, dict) else str(fb)
        ref_ans = fb.get("referenceAnswer") if isinstance(fb, dict) else None
        storage.append_attempt({
            "id": a.get("id"),
            "mode": "free",
            "question_id": a.get("questionId", ""),
            "user_answer": a.get("userAnswer", ""),
            "duration_ms": 0,
            "score": a.get("score", 0),
            "max_score": a.get("maxScore", 0),
            "is_correct": (a.get("score", 0) >= a.get("maxScore", 1) * 0.6) if a.get("maxScore") else False,
            "ai_verdict": verdict,
            "reference_answer": ref_ans,
            "submitted_at": a.get("answeredAt"),
        })
        stats["answers"] += 1

    # 3. mistakes -> 旧 schema 是 questionId,要建一个 placeholder attempt
    # 这里为简化:先插 mistakes,但 attempt_id 是临时合成的(指向一条 dummy attempt)
    # 实际使用上,前端展示时如果找不到 attempt,fallback 到 questionId
    # 简单起见,旧的 mistakes 不迁移(标注警告,让用户重新加)
    if db.LEGACY_JSON_FILES["mistakes"].exists():
        # 只标记,不迁;用户重新勾选"加入错题本"即可
        stats["mistakes_skipped"] = sum(1 for _ in _read_json(db.LEGACY_JSON_FILES["mistakes"]))

    # 4. sessions -> chat_sessions + chat_messages
    for s in _read_json(db.LEGACY_JSON_FILES["sessions"]):
        sid = s["id"]
        for msg in s.get("messages", []):
            storage._append_message(
                sid,
                msg.get("role", "user"),
                msg.get("content", ""),
                subject=s.get("subject", ""),
                sources=msg.get("sources") or [],
            )
        stats["sessions"] += 1

    # 5. exams + exam_questions(exam 内嵌 questions 拆开存)
    for e in _read_json(db.LEGACY_JSON_FILES["exams"]):
        # exam 元数据
        questions = e.get("questions", [])
        exam_record = {
            "id": e.get("id"),
            "subject": e.get("subject"),
            "title": None,
            "durationMinutes": e.get("durationMinutes", 90),
            "totalQuestions": len(questions),
            "createdAt": e.get("createdAt"),
            "questions": questions,   # append_exam 会建 exam_questions 关联 + snapshot
        }
        # 题先入库(若没在 questions.json 里)
        for q in questions:
            storage.append_question(q)
            stats["questions"] += 1
        storage.append_exam(exam_record)
        stats["exams"] += 1

    # 6. exam_attempts -> attempts(mode='exam')
    # 旧 schema: 一次考试一行 exam_attempt,内嵌 answers + results
    for ea in _read_json(db.LEGACY_JSON_FILES["exam_attempts"]):
        results = ea.get("results", [])
        answers = ea.get("answers", [])
        ua_by_qid = {a.get("questionId"): a for a in answers}
        exam_id = ea.get("examId")
        for r in results:
            qid = r.get("questionId")
            ua = ua_by_qid.get(qid, {})
            fb = r.get("feedback") or {}
            storage.append_attempt({
                "mode": "exam",
                "exam_id": exam_id,
                "question_id": qid,
                "exam_no": r.get("examQuestionNo"),
                "user_answer": ua.get("userAnswer") or r.get("userAnswer", ""),
                "duration_ms": int(ua.get("durationMs") or r.get("durationMs") or 0),
                "score": r.get("score", 0),
                "max_score": r.get("maxScore", 0),
                "is_correct": r.get("isCorrect", False),
                "rubric_hits": [],
                "ai_verdict": fb.get("verdict") if isinstance(fb, dict) else None,
                "reference_answer": r.get("correctAnswer") or (fb.get("referenceAnswer") if isinstance(fb, dict) else None),
                "submitted_at": ea.get("submittedAt"),
            })
            stats["exam_attempts"] += 1

    _mark_migrated()
    return stats


if __name__ == "__main__":
    print("=" * 60)
    print("迁移旧 JSON 数据到 SQLite")
    print("=" * 60)
    result = migrate()
    if result.get("skipped"):
        print("(已迁移,无新操作)")
    else:
        print(f"✓ 完成:")
        for k, v in result.items():
            print(f"  - {k}: {v}")
    print()
    print(f"DB 文件: {db.DB_PATH}")
    print(f"DB 大小: {db.DB_PATH.stat().st_size / 1024:.1f} KB")
    sys.exit(0)