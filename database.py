"""
database.py — File-based storage using Railway's persistent volume.

Set the RAILWAY_VOLUME_MOUNT_PATH environment variable in Railway (e.g. /data).
All data is stored as JSON files under that directory.
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

DATA_DIR = Path(os.environ.get("RAILWAY_VOLUME_MOUNT_PATH", "./data"))


def _now() -> str:
    return datetime.utcnow().isoformat()


class Database:
    def __init__(self):
        self.folders_file = DATA_DIR / "folders.json"
        self.logs_file    = DATA_DIR / "logs.json"

    # ── Schema ───────────────────────────────────────────────────────────────

    def init(self):
        """Create data directory and files if they don't exist."""
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        if not self.folders_file.exists():
            self._write(self.folders_file, [])
        if not self.logs_file.exists():
            self._write(self.logs_file, [])
        logger.info(f"Database initialised at {DATA_DIR}")

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _read(self, path: Path) -> list:
        return json.loads(path.read_text(encoding="utf-8"))

    def _write(self, path: Path, data: list):
        path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

    def _next_id(self, records: list) -> int:
        return max((r["id"] for r in records), default=0) + 1

    # ── Folders ──────────────────────────────────────────────────────────────

    def create_folder(self, name: str) -> int:
        folders = self._read(self.folders_file)
        folder_id = self._next_id(folders)
        folders.append({"id": folder_id, "name": name, "created_at": _now()})
        self._write(self.folders_file, folders)
        return folder_id

    def get_folders(self) -> list:
        folders = self._read(self.folders_file)
        logs    = self._read(self.logs_file)

        counts = {}
        for c in logs:
            counts[c["folder_id"]] = counts.get(c["folder_id"], 0) + 1

        for f in folders:
            f["log_count"] = counts.get(f["id"], 0)

        return sorted(folders, key=lambda f: f["created_at"], reverse=True)

    def get_folder(self, folder_id: int) -> dict | None:
        folders = self._read(self.folders_file)
        return next((f for f in folders if f["id"] == folder_id), None)

    def delete_folder(self, folder_id: int):
        """Cascade deletes all logs inside."""
        folders = self._read(self.folders_file)
        self._write(self.folders_file, [f for f in folders if f["id"] != folder_id])
        logs = self._read(self.logs_file)
        self._write(self.logs_file, [c for c in logs if c["folder_id"] != folder_id])

    # ── Logs ─────────────────────────────────────────────────────────────────

    def add_log(self, folder_id: int, code: str, description: str = "") -> int:
        logs = self._read(self.logs_file)
        log_id = self._next_id(logs)
        logs.append({
            "id":          log_id,
            "folder_id":   folder_id,
            "code":        code,
            "description": description,
            "created_at":  _now(),
        })
        self._write(self.logs_file, logs)
        return log_id

    def get_logs(self, folder_id: int) -> list:
        logs = self._read(self.logs_file)
        return sorted(
            [c for c in logs if c["folder_id"] == folder_id],
            key=lambda c: c["created_at"],
            reverse=True,
        )

    def get_all_logs(self) -> list:
        """Returns all logs with their folder name (for admin delete list)."""
        logs    = self._read(self.logs_file)
        folders = {f["id"]: f["name"] for f in self._read(self.folders_file)}
        result  = []
        for c in logs:
            c = dict(c)
            c["folder_name"] = folders.get(c["folder_id"], "Unknown")
            result.append(c)
        return sorted(result, key=lambda c: c["created_at"], reverse=True)

    def get_log(self, log_id: int) -> dict | None:
        logs = self._read(self.logs_file)
        return next((c for c in logs if c["id"] == log_id), None)

    def delete_log(self, log_id: int):
        logs = self._read(self.logs_file)
        self._write(self.logs_file, [c for c in logs if c["id"] != log_id])
