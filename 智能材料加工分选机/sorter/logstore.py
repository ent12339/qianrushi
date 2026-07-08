from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any


class LogStore:
    def __init__(self, database_path: str):
        self.database_path = str(Path(database_path).resolve())
        Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self._init_database()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10.0)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_database(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS system_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    level TEXT NOT NULL,
                    source TEXT NOT NULL,
                    message TEXT NOT NULL,
                    details_json TEXT
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_logs_timestamp "
                "ON system_logs(timestamp DESC)"
            )

    def write(
        self,
        level: str,
        source: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        timestamp = time.time()
        details_json = json.dumps(details, ensure_ascii=False) if details else None
        with self.lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO system_logs(timestamp, level, source, message, details_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (timestamp, level.upper(), source, message, details_json),
            )
        print(f"[{level.upper()}] [{source}] {message}")

    def info(self, source: str, message: str, details: dict[str, Any] | None = None) -> None:
        self.write("INFO", source, message, details)

    def warning(self, source: str, message: str, details: dict[str, Any] | None = None) -> None:
        self.write("WARNING", source, message, details)

    def error(self, source: str, message: str, details: dict[str, Any] | None = None) -> None:
        self.write("ERROR", source, message, details)

    def recent(self, limit: int = 100) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 1000))
        with self.lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, timestamp, level, source, message, details_json
                FROM system_logs
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        result: list[dict[str, Any]] = []
        for row in rows:
            details = None
            if row["details_json"]:
                try:
                    details = json.loads(row["details_json"])
                except json.JSONDecodeError:
                    details = {"raw": row["details_json"]}
            result.append(
                {
                    "id": row["id"],
                    "timestamp": row["timestamp"],
                    "level": row["level"],
                    "source": row["source"],
                    "message": row["message"],
                    "details": details,
                }
            )
        return result
