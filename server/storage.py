"""JSON 文件存储工具。

设计要点:
- 所有写操作走 atomic_write(临时文件 + rename),防止半写导致 JSON 损坏
- 启动时自动初始化缺失文件为空列表
- 所有 ID 用 uuid4 前 8 位,带语义前缀便于人工识别
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any

# 项目根目录 = server/ 的上一级
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
CONFIG_PATH = PROJECT_ROOT / "config.json"

DATA_FILES = {
    "sessions": DATA_DIR / "sessions.json",
    "questions": DATA_DIR / "generated_questions.json",
    "answers": DATA_DIR / "answers.json",
    "mistakes": DATA_DIR / "mistakes.json",
}


def ensure_data_files() -> None:
    """启动时调用,确保 data 目录与所有 JSON 文件存在。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for path in DATA_FILES.values():
        if not path.exists():
            atomic_write_json(path, [])


def atomic_write_json(path: Path, data: Any) -> None:
    """原子写入 JSON:先写临时文件,fsync,再 rename。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        # 失败清理临时文件
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def load_json(path: Path, default: Any = None) -> Any:
    """读取 JSON 文件;不存在或损坏时返回 default。"""
    if not path.exists():
        return default if default is not None else []
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default if default is not None else []


def save_json(path: Path, data: Any) -> None:
    """保存 JSON(原子写)。"""
    atomic_write_json(path, data)


def gen_id(prefix: str) -> str:
    """生成带语义前缀的 ID,如 q_a1b2c3d4。"""
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def load_config() -> dict:
    """读取 config.json;不存在时返回 config.example.json 的内容。"""
    if CONFIG_PATH.exists():
        cfg = load_json(CONFIG_PATH, default={})
        if cfg:
            return cfg
    example = PROJECT_ROOT / "config.example.json"
    if example.exists():
        return load_json(example, default={})
    return {}


def save_config(cfg: dict) -> None:
    """写入 config.json。"""
    atomic_write_json(CONFIG_PATH, cfg)


# ---- 业务数据便捷读写 ----

def list_sessions() -> list[dict]:
    return load_json(DATA_FILES["sessions"], default=[])

def append_session(session: dict) -> None:
    sessions = list_sessions()
    sessions.append(session)
    save_json(DATA_FILES["sessions"], sessions)

def list_questions() -> list[dict]:
    return load_json(DATA_FILES["questions"], default=[])

def append_questions(questions: list[dict]) -> None:
    items = list_questions()
    items.extend(questions)
    save_json(DATA_FILES["questions"], items)

def list_answers() -> list[dict]:
    return load_json(DATA_FILES["answers"], default=[])

def append_answer(answer: dict) -> None:
    items = list_answers()
    items.append(answer)
    save_json(DATA_FILES["answers"], items)

def list_mistakes() -> list[dict]:
    return load_json(DATA_FILES["mistakes"], default=[])

def append_mistake(mistake: dict) -> None:
    items = list_mistakes()
    items.append(mistake)
    save_json(DATA_FILES["mistakes"], items)

def delete_history_item(kind: str, item_id: str) -> bool:
    """删除指定类型中指定 ID 的记录;返回是否真的删了。"""
    path = DATA_FILES.get(kind)
    if path is None:
        return False
    items = load_json(path, default=[])
    new_items = [x for x in items if x.get("id") != item_id]
    if len(new_items) == len(items):
        return False
    save_json(path, new_items)
    return True


# ---- 历史摘要(用于例题生成的去重) ----

def question_summaries_for_dedup(subject: str, topic: str, limit: int = 30) -> list[str]:
    """返回同一科目+知识点下最近 N 条题目的题干摘要,供 Prompt 去重。"""
    items = list_questions()
    filtered = [
        q for q in items
        if q.get("subject") == subject and q.get("topic") == topic
    ]
    filtered.sort(key=lambda x: x.get("createdAt", ""), reverse=True)
    return [q.get("stem", "")[:120] for q in filtered[:limit]]