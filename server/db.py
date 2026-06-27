"""SQLite 数据库管理:连接、schema 初始化、版本迁移。

数据文件:data/harness.db(SQLite 单文件)
设计目标:
- 零外部依赖(python 自带 sqlite3)
- 跨平台(Win/Mac/Linux 同份文件)
- 真外键 + 真 JOIN,替代旧的 JSON 行存储
- 启动时自动建表,迁移按 schema_version 走
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "harness.db"

# 旧 JSON 文件(只用于一次性迁移)
LEGACY_JSON_FILES = {
    "questions": DATA_DIR / "generated_questions.json",
    "answers": DATA_DIR / "answers.json",
    "mistakes": DATA_DIR / "mistakes.json",
    "sessions": DATA_DIR / "sessions.json",
    "exams": DATA_DIR / "exams.json",
    "exam_attempts": DATA_DIR / "exam_attempts.json",
}

CURRENT_SCHEMA_VERSION = "2"


# ---- Schema 定义 ----

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS questions (
    id              TEXT PRIMARY KEY,
    subject         TEXT NOT NULL,
    topic           TEXT,
    type            TEXT NOT NULL,
    difficulty      TEXT,
    stem            TEXT NOT NULL,
    options_json    TEXT,           -- JSON 数组:["A. ...","B. ..."]
    answer          TEXT,
    explanation     TEXT,
    rubric_json     TEXT,           -- JSON:[{"id","points","criterion","hit","reason"}]
    key_points_json TEXT,           -- JSON 数组
    pitfalls_json   TEXT,           -- JSON 数组
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_q_subject_topic ON questions(subject, topic);
CREATE INDEX IF NOT EXISTS idx_q_type ON questions(type);
CREATE INDEX IF NOT EXISTS idx_q_created ON questions(created_at);

CREATE TABLE IF NOT EXISTS exams (
    id               TEXT PRIMARY KEY,
    subject          TEXT NOT NULL,
    title            TEXT,
    duration_minutes INTEGER NOT NULL,
    total_questions  INTEGER NOT NULL,
    config_json      TEXT,           -- 生成配置快照
    created_at       TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_exam_created ON exams(created_at);

CREATE TABLE IF NOT EXISTS exam_questions (
    exam_id      TEXT NOT NULL REFERENCES exams(id) ON DELETE CASCADE,
    question_id  TEXT NOT NULL REFERENCES questions(id) ON DELETE RESTRICT,
    exam_no      INTEGER NOT NULL,
    section      TEXT,
    max_score    REAL NOT NULL,
    snapshot_json TEXT NOT NULL,    -- 题目快照,防题库修改影响历史试卷
    PRIMARY KEY (exam_id, question_id)
);

CREATE INDEX IF NOT EXISTS idx_eq_exam_no ON exam_questions(exam_id, exam_no);

CREATE TABLE IF NOT EXISTS attempts (
    id                TEXT PRIMARY KEY,
    mode              TEXT NOT NULL CHECK(mode IN ('free','exam')),
    exam_id           TEXT REFERENCES exams(id) ON DELETE SET NULL,
    question_id       TEXT,  -- 旧数据可能为空,不强制 FK;新数据应填
    exam_no           INTEGER,
    user_answer       TEXT,
    duration_ms       INTEGER NOT NULL DEFAULT 0,
    score             REAL NOT NULL DEFAULT 0,
    max_score         REAL NOT NULL DEFAULT 0,
    is_correct        INTEGER NOT NULL DEFAULT 0,
    rubric_hits_json  TEXT,
    ai_verdict        TEXT,
    reference_answer  TEXT,
    submitted_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_att_exam ON attempts(exam_id);
CREATE INDEX IF NOT EXISTS idx_att_question ON attempts(question_id);
CREATE INDEX IF NOT EXISTS idx_att_mode_submitted ON attempts(mode, submitted_at);

CREATE TABLE IF NOT EXISTS mistakes (
    id             TEXT PRIMARY KEY,
    attempt_id     TEXT NOT NULL REFERENCES attempts(id) ON DELETE CASCADE,
    reason         TEXT,
    reviewed       INTEGER NOT NULL DEFAULT 0,
    auto_practice  INTEGER NOT NULL DEFAULT 0,
    added_at       TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_mistake_attempt ON mistakes(attempt_id);

CREATE TABLE IF NOT EXISTS chat_sessions (
    id         TEXT PRIMARY KEY,
    subject    TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    role       TEXT NOT NULL,
    content    TEXT NOT NULL,
    sources_json TEXT,
    at         TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_msg_session ON chat_messages(session_id, id);
"""


def _connect() -> sqlite3.Connection:
    """打开 SQLite 连接。row_factory 设为 Row,支持字段名访问。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=10.0)
    conn.row_factory = sqlite3.Row
    # 外键必须每连接开启
    conn.execute("PRAGMA foreign_keys = ON")
    # WAL 模式:读写并发更好,跨进程更安全
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def get_conn() -> sqlite3.Connection:
    """获取连接(供 storage 层使用)。每次调用返回新连接,sqlite3 默认线程安全。"""
    return _connect()


def init_schema() -> None:
    """启动时调用:建表 + 检查 schema_version,处理老库增量迁移。"""
    conn = _connect()
    try:
        conn.executescript(SCHEMA_SQL)
        # ---- 增量迁移:老库缺列时补上 ----
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(mistakes)").fetchall()}
        if "auto_practice" not in cols:
            conn.execute("ALTER TABLE mistakes ADD COLUMN auto_practice INTEGER NOT NULL DEFAULT 0")
        # 写 schema_version
        conn.execute(
            "INSERT OR REPLACE INTO schema_meta(key, value) VALUES('schema_version', ?)",
            (CURRENT_SCHEMA_VERSION,),
        )
        conn.commit()
    finally:
        conn.close()


def db_exists() -> bool:
    return DB_PATH.exists()


# ---- JSON 列辅助 ----

def jdump(obj) -> str | None:
    """把 Python 对象序列化成 JSON 字符串;None 存 NULL。"""
    if obj is None:
        return None
    return json.dumps(obj, ensure_ascii=False)


def jload(s: str | None, default=None):
    """从 JSON 字符串还原;NULL/坏 JSON 返回 default。"""
    if not s:
        return default
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError):
        return default