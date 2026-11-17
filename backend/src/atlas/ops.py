"""Backup, restore, and demo reset utilities. Works with local SQLite + object store; documents pg_dump for Postgres."""
from __future__ import annotations

import shutil
import sqlite3
import tarfile
import tempfile
from pathlib import Path

from atlas.config import get_settings
from atlas.db import create_all, reset_engine, session_scope
from atlas.seed import seed


def _sqlite_path() -> Path:
    url = get_settings().database_url
    if not url.startswith("sqlite:///"):
        raise RuntimeError("Local file backup helper supports sqlite:///; use pg_dump / pg_restore for PostgreSQL (see RUNBOOK.md)")
    return Path(url.removeprefix("sqlite:///"))


def backup_state(archive_path: Path) -> Path:
    db_file = _sqlite_path()
    obj_dir = get_settings().object_store_dir
    sbx_file = get_settings().sandbox_state_file
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        if db_file.exists():
            dst_db = tmp_dir / "atlas.db"
            src_conn = sqlite3.connect(str(db_file))
            dst_conn = sqlite3.connect(str(dst_db))
            with dst_conn:
                src_conn.backup(dst_conn)
            src_conn.close()
            dst_conn.close()
        if obj_dir.exists():
            shutil.copytree(obj_dir, tmp_dir / "objects")
        if sbx_file.exists():
            shutil.copy2(sbx_file, tmp_dir / "sandbox_publisher.json")
        with tarfile.open(archive_path, "w:gz") as tar:
            for item in tmp_dir.iterdir():
                tar.add(item, arcname=item.name)
    return archive_path


def restore_state(archive_path: Path) -> None:
    reset_engine()
    db_file = _sqlite_path()
    obj_dir = get_settings().object_store_dir
    sbx_file = get_settings().sandbox_state_file
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        with tarfile.open(archive_path, "r:gz") as tar:
            tar.extractall(tmp_dir, filter="data")
        if (tmp_dir / "atlas.db").exists():
            db_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(tmp_dir / "atlas.db", db_file)
        if (tmp_dir / "objects").exists():
            if obj_dir.exists():
                shutil.rmtree(obj_dir)
            shutil.copytree(tmp_dir / "objects", obj_dir)
        if (tmp_dir / "sandbox_publisher.json").exists():
            sbx_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(tmp_dir / "sandbox_publisher.json", sbx_file)


def reset_demo() -> dict[str, str]:
    reset_engine()
    db_file = _sqlite_path()
    for f in [db_file, Path(str(db_file) + "-wal"), Path(str(db_file) + "-shm"), get_settings().sandbox_state_file]:
        if f.exists():
            f.unlink()
    if get_settings().object_store_dir.exists():
        shutil.rmtree(get_settings().object_store_dir)
    create_all()
    with session_scope() as s:
        return seed(s)
