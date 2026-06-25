"""数据访问层(SQLite 版)。

设计要点:
- 用 SQLite 替代旧的 JSON 行存储
- 保留旧函数签名(load_config/save_config/append_question/list_questions 等),
  让 server.py 不需要大改
- 加新函数:get_question_full / get_attempt_with_question / list_attempts_for_question 等
- 所有 ID 仍是 uuid8+前缀(q_xxx/att_xxx/exam_xxx)
- 跨平台:sqlite3 内置,零依赖
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .db import (
    CURRENT_SCHEMA_VERSION,
    DATA_DIR,
    DB_PATH,
    PROJECT_ROOT,
    get_conn,
    jdump,
    jload,
    init_schema,
)

# ---- config.json(不变,仍用文件) ----
CONFIG_PATH = PROJECT_ROOT / "config.json"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def gen_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


@contextmanager
def _db() -> Iterator[sqlite3.Connection]:
    conn = get_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---- 启动 ----

def ensure_data_files() -> None:
    """启动时调用:建 SQLite 表 + config.json。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    init_schema()
    if not CONFIG_PATH.exists():
        example = PROJECT_ROOT / "config.example.json"
        if example.exists():
            CONFIG_PATH.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")


# ---- config(继续走 JSON 文件,因为简单) ----

def load_config() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_config(cfg: dict) -> None:
    atomic_write_json(CONFIG_PATH, cfg)


def atomic_write_json(path: Path, data: Any) -> None:
    """保留旧 atomic_write_json 给 config 用。"""
    import os, tempfile
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ---- 题目 ----

def append_question(question: dict) -> None:
    """插入一道题。"""
    qid = question.get("id") or gen_id("q")
    now = question.get("createdAt") or _now()
    with _db() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO questions(
                id, subject, topic, type, difficulty, stem,
                options_json, answer, explanation,
                rubric_json, key_points_json, pitfalls_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            qid,
            question.get("subject", ""),
            question.get("topic", ""),
            question.get("type", "案例分析题"),
            question.get("difficulty", ""),
            question.get("stem", ""),
            jdump(question.get("options", [])),
            question.get("answer", ""),
            question.get("explanation", ""),
            jdump(question.get("rubric", [])),
            jdump(question.get("keyPoints", [])),
            jdump(question.get("pitfalls", [])),
            now,
        ))


def append_questions(questions: list[dict]) -> None:
    """批量插入(用于生成时)。"""
    with _db() as conn:
        for q in questions:
            qid = q.get("id") or gen_id("q")
            now = q.get("createdAt") or _now()
            conn.execute("""
                INSERT OR REPLACE INTO questions(
                    id, subject, topic, type, difficulty, stem,
                    options_json, answer, explanation,
                    rubric_json, key_points_json, pitfalls_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                qid,
                q.get("subject", ""),
                q.get("topic", ""),
                q.get("type", "案例分析题"),
                q.get("difficulty", ""),
                q.get("stem", ""),
                jdump(q.get("options", [])),
                q.get("answer", ""),
                q.get("explanation", ""),
                jdump(q.get("rubric", [])),
                jdump(q.get("keyPoints", [])),
                jdump(q.get("pitfalls", [])),
                now,
            ))


def _row_to_question(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "subject": row["subject"],
        "topic": row["topic"],
        "type": row["type"],
        "difficulty": row["difficulty"],
        "stem": row["stem"],
        "options": jload(row["options_json"], []),
        "answer": row["answer"],
        "explanation": row["explanation"],
        "rubric": jload(row["rubric_json"], []),
        "keyPoints": jload(row["key_points_json"], []),
        "pitfalls": jload(row["pitfalls_json"], []),
        "createdAt": row["created_at"],
    }


def list_questions(limit: int | None = None, subject: str | None = None) -> list[dict]:
    """列出题目(默认按 created_at 倒序)。"""
    sql = "SELECT * FROM questions"
    args: list = []
    if subject:
        sql += " WHERE subject = ?"
        args.append(subject)
    sql += " ORDER BY created_at DESC"
    if limit:
        sql += " LIMIT ?"
        args.append(limit)
    with _db() as conn:
        return [_row_to_question(r) for r in conn.execute(sql, args).fetchall()]


def get_question(qid: str) -> dict | None:
    with _db() as conn:
        row = conn.execute("SELECT * FROM questions WHERE id = ?", (qid,)).fetchone()
        return _row_to_question(row) if row else None


def question_summaries_for_dedup(subject: str, topic: str, limit: int = 30) -> list[str]:
    """保留旧函数签名:返回同 subject+topic 下最近 N 条题干摘要。"""
    with _db() as conn:
        rows = conn.execute("""
            SELECT stem FROM questions
            WHERE subject = ? AND topic = ?
            ORDER BY created_at DESC LIMIT ?
        """, (subject, topic, limit)).fetchall()
        return [r["stem"][:120] for r in rows]


# ---- 答题(attempts) ----

def append_attempt(attempt: dict) -> None:
    """插入一条作答记录。
    attempt: {
        id, mode ('free'|'exam'), exam_id?, question_id, exam_no?,
        user_answer, duration_ms, score, max_score, is_correct,
        rubric_hits?, ai_verdict?, reference_answer?
    }
    """
    aid = attempt.get("id") or gen_id("att")
    now = attempt.get("submittedAt") or _now()
    with _db() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO attempts(
                id, mode, exam_id, question_id, exam_no,
                user_answer, duration_ms, score, max_score, is_correct,
                rubric_hits_json, ai_verdict, reference_answer, submitted_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            aid,
            attempt.get("mode", "free"),
            attempt.get("exam_id") or attempt.get("examId"),
            attempt.get("question_id") or attempt.get("questionId") or "",
            attempt.get("exam_no") or attempt.get("examNo"),
            attempt.get("user_answer") or attempt.get("userAnswer") or "",
            int(attempt.get("duration_ms") or attempt.get("durationMs") or 0),
            float(attempt.get("score") or 0),
            float(attempt.get("max_score") or attempt.get("maxScore") or 0),
            1 if attempt.get("is_correct") or attempt.get("isCorrect") else 0,
            jdump(attempt.get("rubric_hits") or attempt.get("rubricHits") or []),
            attempt.get("ai_verdict") or attempt.get("aiVerdict"),
            attempt.get("reference_answer") or attempt.get("referenceAnswer"),
            now,
        ))


def _row_to_attempt(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "mode": row["mode"],
        "examId": row["exam_id"],
        "questionId": row["question_id"],
        "examNo": row["exam_no"],
        "userAnswer": row["user_answer"],
        "durationMs": row["duration_ms"],
        "durationSec": round(row["duration_ms"] / 1000, 1),
        "score": row["score"],
        "maxScore": row["max_score"],
        "isCorrect": bool(row["is_correct"]),
        "rubricHits": jload(row["rubric_hits_json"], []),
        "aiVerdict": row["ai_verdict"],
        "referenceAnswer": row["reference_answer"],
        "submittedAt": row["submitted_at"],
    }


def get_attempt(aid: str) -> dict | None:
    """取单条 attempt(不含关联 question)。"""
    with _db() as conn:
        row = conn.execute("SELECT * FROM attempts WHERE id = ?", (aid,)).fetchone()
        return _row_to_attempt(row) if row else None


def get_attempt_full(aid: str) -> dict | None:
    """取 attempt + 关联 question(扁平 dict,直接给前端)。"""
    with _db() as conn:
        row = conn.execute("""
            SELECT
                a.*, q.subject AS q_subject, q.topic AS q_topic, q.stem AS q_stem,
                q.options_json AS q_options_json, q.answer AS q_answer,
                q.explanation AS q_explanation, q.rubric_json AS q_rubric_json,
                q.key_points_json AS q_key_points_json, q.pitfalls_json AS q_pitfalls_json,
                q.difficulty AS q_difficulty, q.type AS q_type
            FROM attempts a
            LEFT JOIN questions q ON q.id = a.question_id
            WHERE a.id = ?
        """, (aid,)).fetchone()
        if not row:
            return None
        attempt = _row_to_attempt(row)
        attempt["question"] = {
            "id": row["question_id"],
            "subject": row["q_subject"],
            "topic": row["q_topic"],
            "type": row["q_type"],
            "difficulty": row["q_difficulty"],
            "stem": row["q_stem"],
            "options": jload(row["q_options_json"], []),
            "answer": row["q_answer"],
            "explanation": row["q_explanation"],
            "rubric": jload(row["q_rubric_json"], []),
            "keyPoints": jload(row["q_key_points_json"], []),
            "pitfalls": jload(row["q_pitfalls_json"], []),
        }
        return attempt


def list_attempts(mode: str | None = None, limit: int = 100) -> list[dict]:
    """列出 attempt(默认最近 100 条,按 submitted_at 倒序)。
    自由练习历史 = mode='free';考试记录 = mode='exam'。
    """
    sql = "SELECT * FROM attempts"
    args: list = []
    if mode:
        sql += " WHERE mode = ?"
        args.append(mode)
    sql += " ORDER BY submitted_at DESC LIMIT ?"
    args.append(limit)
    with _db() as conn:
        return [_row_to_attempt(r) for r in conn.execute(sql, args).fetchall()]


def list_attempts_for_question(qid: str) -> list[dict]:
    """某道题的全部作答历史(查"我做过几次")。"""
    with _db() as conn:
        return [_row_to_attempt(r) for r in conn.execute(
            "SELECT * FROM attempts WHERE question_id = ? ORDER BY submitted_at DESC", (qid,)
        ).fetchall()]


def list_attempts_for_exam(eid: str) -> list[dict]:
    """某场考试的每题作答(用 exam_no 排序)。"""
    with _db() as conn:
        return [_row_to_attempt(r) for r in conn.execute(
            "SELECT * FROM attempts WHERE exam_id = ? ORDER BY exam_no", (eid,)
        ).fetchall()]


# ---- 兼容旧 answers.json 的接口(返回 list,字段映射成旧 shape) ----

def list_answers() -> list[dict]:
    """返回 list[dict],字段尽量兼容旧 schema,前端可平滑过渡。"""
    items = list_attempts(mode="free", limit=200)
    # 旧 schema 用 answeredAt / feedback(整个 feedback 字典)
    out = []
    for a in items:
        out.append({
            "id": a["id"],
            "questionId": a["questionId"],
            "answeredAt": a["submittedAt"],
            "userAnswer": a["userAnswer"],
            "score": a["score"],
            "maxScore": a["maxScore"],
            "feedback": {
                "score": a["score"],
                "maxScore": a["maxScore"],
                "verdict": a.get("aiVerdict") or "",
                "referenceAnswer": a.get("referenceAnswer") or "",
            },
        })
    return out


# ---- 错题 ----

def append_mistake(mistake: dict) -> None:
    mid = mistake.get("id") or gen_id("m")
    now = mistake.get("addedAt") or _now()
    with _db() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO mistakes(id, attempt_id, reason, reviewed, added_at)
            VALUES (?, ?, ?, ?, ?)
        """, (
            mid,
            mistake["attemptId"] or mistake["attempt_id"],
            mistake.get("reason", ""),
            1 if mistake.get("reviewed") else 0,
            now,
        ))


def list_mistakes() -> list[dict]:
    """返回错题列表(含关联 attempt 摘要)。"""
    with _db() as conn:
        rows = conn.execute("""
            SELECT m.id, m.attempt_id, m.reason, m.reviewed, m.added_at,
                   a.question_id, a.user_answer, a.score, a.max_score, a.submitted_at,
                   q.subject AS q_subject, q.stem AS q_stem
            FROM mistakes m
            JOIN attempts a ON a.id = m.attempt_id
            LEFT JOIN questions q ON q.id = a.question_id
            ORDER BY m.added_at DESC
        """).fetchall()
        return [{
            "id": r["id"],
            "attemptId": r["attempt_id"],
            "questionId": r["question_id"],
            "addedAt": r["added_at"],
            "reason": r["reason"],
            "reviewed": bool(r["reviewed"]),
            "userAnswer": r["user_answer"],
            "score": r["score"],
            "maxScore": r["max_score"],
            "answeredAt": r["submitted_at"],
            "subject": r["q_subject"],
            "stem": r["q_stem"],
        } for r in rows]


# ---- 试卷 ----

def append_exam(exam: dict) -> None:
    """插入试卷 + 关联 exam_questions(snapshot)。"""
    eid = exam.get("id") or gen_id("exam")
    now = exam.get("createdAt") or _now()
    questions = exam.get("questions", [])  # 用于建 exam_questions 关联

    with _db() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO exams(
                id, subject, title, duration_minutes, total_questions, config_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            eid,
            exam.get("subject", ""),
            exam.get("title"),
            int(exam.get("durationMinutes") or exam.get("duration_minutes") or 90),
            int(exam.get("totalQuestions") or exam.get("total_questions") or len(questions)),
            jdump(exam.get("config") or {}),
            now,
        ))
        # 关联表
        for q in questions:
            qid = q["id"]
            snapshot = {
                "stem": q.get("stem", ""),
                "options": q.get("options", []),
                "answer": q.get("answer", ""),
                "explanation": q.get("explanation", ""),
            }
            conn.execute("""
                INSERT OR REPLACE INTO exam_questions(
                    exam_id, question_id, exam_no, section, max_score, snapshot_json
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, (
                eid,
                qid,
                int(q.get("examQuestionNo") or q.get("exam_no") or 0),
                q.get("section"),
                float(q.get("maxScore") or q.get("max_score") or _default_score_for(q.get("type", ""))),
                jdump(snapshot),
            ))


def _default_score_for(qtype: str) -> float:
    return {"单选题": 2, "多选题": 3, "简答题": 10}.get(qtype, 5)


# 选择题严格判分(法考标准:多选必须全对才算对)
# - 单选题:答案完全一致才得分
# - 多选题:选项集合完全一致(少选/多选/错选=0分)
# - 判断题:答案完全一致
# 返回 (is_correct: bool, score: float, max_score: float)
def grade_choice_answer(question: dict, user_answer: str) -> tuple[bool, float, float]:
    """选择题严格判分。返回 (is_correct, score, max_score)。

    规则(法考标准):
    - 单选题:严格匹配,正确=满分,错误=0
    - 多选题:**少选/多选/错选 = 0 分**(全对才得分)
    - 判断题:严格匹配

    user_answer 支持 "A" / "A,B" / "ABC" 等多种格式,统一规范化比对。
    """
    qtype = question.get("type", "")
    if qtype == "单选题":
        max_score = 2.0
    elif qtype == "多选题":
        max_score = 3.0
    elif qtype == "判断题":
        max_score = 1.0
    else:
        # 非选择题,不该走这里
        return False, 0.0, _default_score_for(qtype)

    # 规范化:大写、移除分隔符和空白
    def _norm(s: str) -> frozenset[str]:
        if not s:
            return frozenset()
        # 支持 "A" / "A,B,C" / "ABC" / "A B C" 多种写法
        # 思路:把大写字母提出来
        import re
        return frozenset(re.findall(r"[A-Z]", s.upper()))

    std_set = _norm(question.get("answer", ""))
    usr_set = _norm(user_answer)

    # 都为空(用户未作答或题目无答案)→ 不算正确
    if not std_set or not usr_set:
        return False, 0.0, max_score

    is_correct = (std_set == usr_set)
    return is_correct, (max_score if is_correct else 0.0), max_score


def is_choice_question(qtype: str) -> bool:
    """选择题类(单选/多选/判断)用 auto-grade,不走 AI。"""
    return qtype in ("单选题", "多选题", "判断题")


def list_exams() -> list[dict]:
    """列出试卷元数据(不含 questions 详情)。"""
    with _db() as conn:
        rows = conn.execute(
            "SELECT * FROM exams ORDER BY created_at DESC"
        ).fetchall()
        out = []
        for r in rows:
            # 题型分布
            type_rows = conn.execute("""
                SELECT q.type, COUNT(*) AS cnt FROM exam_questions eq
                JOIN questions q ON q.id = eq.question_id
                WHERE eq.exam_id = ? GROUP BY q.type
            """, (r["id"],)).fetchall()
            breakdown = {tr["type"]: tr["cnt"] for tr in type_rows}
            out.append({
                "id": r["id"],
                "subject": r["subject"],
                "title": r["title"],
                "createdAt": r["created_at"],
                "durationMinutes": r["duration_minutes"],
                "totalQuestions": r["total_questions"],
                "config": jload(r["config_json"], {}),
                "typeBreakdown": breakdown,
            })
        return out


def get_exam(exam_id: str) -> dict | None:
    """取试卷元数据(不含 questions)。"""
    with _db() as conn:
        row = conn.execute("SELECT * FROM exams WHERE id = ?", (exam_id,)).fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "subject": row["subject"],
            "title": row["title"],
            "createdAt": row["created_at"],
            "durationMinutes": row["duration_minutes"],
            "totalQuestions": row["total_questions"],
            "config": jload(row["config_json"], {}),
        }


def get_exam_full(exam_id: str) -> dict | None:
    """取试卷 + 关联的题目(snapshot 优先,题目已删则用 snapshot)。"""
    exam = get_exam(exam_id)
    if not exam:
        return None
    with _db() as conn:
        rows = conn.execute("""
            SELECT eq.exam_no, eq.section, eq.max_score, eq.snapshot_json,
                   eq.question_id,
                   q.id AS q_id, q.subject, q.topic, q.type, q.difficulty, q.stem,
                   q.options_json, q.answer, q.explanation
            FROM exam_questions eq
            LEFT JOIN questions q ON q.id = eq.question_id
            WHERE eq.exam_id = ?
            ORDER BY eq.exam_no
        """, (exam_id,)).fetchall()
        questions = []
        for r in rows:
            snap = jload(r["snapshot_json"], {}) or {}
            questions.append({
                "id": r["q_id"] or "",  # 若题目已删,id 可能为空
                "examQuestionNo": r["exam_no"],
                "section": r["section"],
                "maxScore": r["max_score"],
                "type": r["type"] or "",
                "topic": r["topic"] or "",
                "subject": r["subject"] or exam["subject"],
                # snapshot 优先
                "stem": r["stem"] or snap.get("stem", ""),
                "options": jload(r["options_json"], []) or snap.get("options", []),
                "answer": r["answer"] or snap.get("answer", ""),
                "explanation": r["explanation"] or snap.get("explanation", ""),
            })
        exam["questions"] = questions
        return exam


def delete_exam(exam_id: str) -> bool:
    """删试卷(级联删 exam_questions,attempts.exam_id 置 NULL)。"""
    with _db() as conn:
        cur = conn.execute("DELETE FROM exams WHERE id = ?", (exam_id,))
        return cur.rowcount > 0


# ---- 兼容旧 exam_attempts 的接口(轻量,只 exam 级聚合) ----

def list_exam_attempts() -> list[dict]:
    """返回 list[dict],按 examId 分组聚合,字段尽量兼容旧 schema。"""
    with _db() as conn:
        # 按 exam_id 聚合(只有 mode='exam' 的 attempts)
        rows = conn.execute("""
            SELECT exam_id, COUNT(*) AS qcnt,
                   SUM(duration_ms) AS total_ms,
                   MIN(submitted_at) AS first_at,
                   MAX(submitted_at) AS last_at
            FROM attempts WHERE mode = 'exam' AND exam_id IS NOT NULL
            GROUP BY exam_id
            ORDER BY last_at DESC
        """).fetchall()
        out = []
        for r in rows:
            attempts = list_attempts_for_exam(r["exam_id"])
            total_score = sum(a["score"] for a in attempts)
            total_max = sum(a["maxScore"] for a in attempts)
            submitted_at = r["last_at"]
            # 旧的 schema 没有统一 attempt id,用 first attempt id 表示一次考试
            out.append({
                "id": f"exam_group_{r['exam_id']}",  # 虚拟 id
                "examId": r["exam_id"],
                "submittedAt": submitted_at,
                "timeUp": False,
                "totalScore": total_score,
                "totalMax": total_max,
                "totalDurationMs": r["total_ms"] or 0,
                "questionCount": r["qcnt"],
                "attemptIds": [a["id"] for a in attempts],
            })
        return out


def append_exam_attempt(attempt: dict) -> None:
    """旧接口兼容:整场考试的批量 attempt 落库。"""
    eid = attempt.get("examId") or attempt.get("exam_id")
    time_up = bool(attempt.get("timeUp"))
    answers = attempt.get("answers", [])  # [{questionId, userAnswer, durationMs}]
    results = attempt.get("results", [])  # AI/auto 评分结果

    # 把 results 合并到 answers(每题一行 attempt)
    by_qid = {a.get("questionId"): a for a in answers}
    with _db() as conn:
        for r in results:
            qid = r["questionId"]
            ua = by_qid.get(qid, {})
            attempt_row = {
                "mode": "exam",
                "exam_id": eid,
                "question_id": qid,
                "exam_no": r.get("examQuestionNo"),
                "user_answer": ua.get("userAnswer") or "",
                "duration_ms": int(ua.get("durationMs") or r.get("durationMs") or 0),
                "score": r.get("score", 0),
                "max_score": r.get("maxScore", 0),
                "is_correct": r.get("isCorrect", False),
                "rubric_hits": [],
                "ai_verdict": (r.get("feedback") or {}).get("verdict"),
                "reference_answer": r.get("correctAnswer") or (r.get("feedback") or {}).get("referenceAnswer"),
                "submitted_at": attempt.get("submittedAt") or _now(),
            }
            conn.execute("""
                INSERT OR REPLACE INTO attempts(
                    id, mode, exam_id, question_id, exam_no,
                    user_answer, duration_ms, score, max_score, is_correct,
                    rubric_hits_json, ai_verdict, reference_answer, submitted_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                gen_id("att"),
                attempt_row["mode"], attempt_row["exam_id"], attempt_row["question_id"], attempt_row["exam_no"],
                attempt_row["user_answer"], attempt_row["duration_ms"],
                attempt_row["score"], attempt_row["max_score"],
                1 if attempt_row["is_correct"] else 0,
                jdump(attempt_row["rubric_hits"]),
                attempt_row["ai_verdict"],
                attempt_row["reference_answer"],
                attempt_row["submitted_at"],
            ))


# ---- 统计 ----

def exam_stats() -> dict:
    """三维度正确率统计:题型 / 考点 / 科目。
    返回:{totalAttempts, totalQuestions, totalCorrect, overallRate, byType, byTopic, bySubject}
    """
    with _db() as conn:
        rows = conn.execute("""
            SELECT a.is_correct, a.score, a.max_score,
                   q.type AS q_type, q.topic AS q_topic, q.subject AS q_subject
            FROM attempts a
            LEFT JOIN questions q ON q.id = a.question_id
            WHERE a.mode = 'exam'
        """).fetchall()

        # 总览
        total_exam_attempts = conn.execute(
            "SELECT COUNT(DISTINCT exam_id) FROM attempts WHERE mode='exam' AND exam_id IS NOT NULL"
        ).fetchone()[0]
        total_q = len(rows)
        total_c = sum(1 for r in rows if r["is_correct"])

        def bucket(key_fn):
            b: dict[str, dict] = {}
            for r in rows:
                k = key_fn(r["q_type"], r["q_topic"], r["q_subject"])
                if not k:
                    k = "未分类"
                bb = b.setdefault(k, {"total": 0, "correct": 0, "ssum": 0.0, "smax": 0.0})
                bb["total"] += 1
                if r["is_correct"]:
                    bb["correct"] += 1
                bb["ssum"] += r["score"] or 0
                bb["smax"] += r["max_score"] or 0
            return [{
                "key": k,
                "total": v["total"],
                "correct": v["correct"],
                "rate": round(v["correct"] / v["total"] * 100, 1) if v["total"] else 0,
                "scoreRate": round(v["ssum"] / v["smax"] * 100, 1) if v["smax"] else 0,
            } for k, v in b.items()]

        return {
            "totalAttempts": total_exam_attempts,
            "totalQuestions": total_q,
            "totalCorrect": total_c,
            "overallRate": round(total_c / total_q * 100, 1) if total_q else 0,
            "byType": sorted(bucket(lambda t, _, __: t), key=lambda x: x["rate"]),
            "byTopic": sorted(bucket(lambda _, tp, __: tp or "未分类"), key=lambda x: x["rate"]),
            "bySubject": sorted(bucket(lambda _, __, sb: sb or "未分类"), key=lambda x: x["rate"]),
        }


# ---- 聊天会话 ----

def _append_message(session_id: str, role: str, content: str, *, subject: str = "", sources: list[str] | None = None) -> None:
    """追加一条会话消息。"""
    now = _now()
    with _db() as conn:
        row = conn.execute("SELECT id FROM chat_sessions WHERE id = ?", (session_id,)).fetchone()
        if row is None:
            conn.execute("""
                INSERT INTO chat_sessions(id, subject, created_at, updated_at)
                VALUES (?, ?, ?, ?)
            """, (session_id, subject or "不限科目", now, now))
        else:
            conn.execute("UPDATE chat_sessions SET updated_at = ?, subject = COALESCE(NULLIF(?, ''), subject) WHERE id = ?",
                         (now, subject, session_id))
        conn.execute("""
            INSERT INTO chat_messages(session_id, role, content, sources_json, at)
            VALUES (?, ?, ?, ?, ?)
        """, (session_id, role, content, jdump(sources or []), now))


def list_sessions() -> list[dict]:
    """返回 list[dict],字段兼容旧 schema: messages 数组 + subject。"""
    with _db() as conn:
        sessions = conn.execute("SELECT * FROM chat_sessions ORDER BY updated_at DESC").fetchall()
        out = []
        for s in sessions:
            msgs = conn.execute("""
                SELECT role, content, sources_json, at FROM chat_messages
                WHERE session_id = ? ORDER BY id
            """, (s["id"],)).fetchall()
            out.append({
                "id": s["id"],
                "createdAt": s["created_at"],
                "updatedAt": s["updated_at"],
                "subject": s["subject"],
                "messages": [{
                    "role": m["role"],
                    "content": m["content"],
                    "sources": jload(m["sources_json"], []),
                    "at": m["at"],
                } for m in msgs],
            })
        return out


# ---- 旧接口 delete_history_item(为兼容 server.py) ----

def delete_history_item(kind: str, item_id: str) -> bool:
    """统一删除入口(历史 tab 用)。"""
    if kind == "questions":
        with _db() as conn:
            cur = conn.execute("DELETE FROM questions WHERE id = ?", (item_id,))
            return cur.rowcount > 0
    elif kind == "answers":
        # 自由练习 attempt
        with _db() as conn:
            cur = conn.execute("DELETE FROM attempts WHERE id = ? AND mode = 'free'", (item_id,))
            return cur.rowcount > 0
    elif kind == "mistakes":
        with _db() as conn:
            cur = conn.execute("DELETE FROM mistakes WHERE id = ?", (item_id,))
            return cur.rowcount > 0
    elif kind == "sessions":
        with _db() as conn:
            cur = conn.execute("DELETE FROM chat_sessions WHERE id = ?", (item_id,))
            return cur.rowcount > 0
    return False