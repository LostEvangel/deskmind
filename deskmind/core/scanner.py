"""Desktop file scanner — extract metadata from files on the desktop."""

from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from deskmind.models.schemas import DeskMindConfig, FileInfo


def _get_file_info(path: Path) -> FileInfo | None:
    """Extract metadata from a single file."""
    try:
        stat = path.stat()
        ext = path.suffix.lower()
        return FileInfo(
            path=path,
            name=path.name,
            extension=ext,
            size_bytes=stat.st_size,
            created_at=datetime.fromtimestamp(stat.st_ctime),
            modified_at=datetime.fromtimestamp(stat.st_mtime),
            is_directory=path.is_dir(),
        )
    except (OSError, PermissionError):
        return None


def _get_creation_time(file_info: FileInfo | None) -> float:
    if file_info is None:
        return 0
    return file_info.created_at.timestamp()


def scan_desktop(config: DeskMindConfig) -> list[FileInfo]:
    """Scan the desktop and return a sorted list of FileInfo objects.

    Sorted by creation time ascending (oldest first).
    """
    desktop = config.resolved_desktop
    if not desktop.exists() or not desktop.is_dir():
        raise FileNotFoundError(f"Desktop path not found: {desktop}")

    exclude_exts = set(config.exclude_extensions)
    exclude_names = set(config.exclude_names)

    paths = list(desktop.iterdir())
    results: list[FileInfo] = []
    exts_found: dict[str, int] = {}
    total_size = 0

    with ThreadPoolExecutor(max_workers=os.cpu_count()) as pool:
        futures = {pool.submit(_get_file_info, p): p for p in paths}
        for future in as_completed(futures):
            info = future.result()
            if info is None:
                continue
            if info.name in exclude_names:
                continue
            if info.extension in exclude_exts:
                continue
            exts_found[info.extension] = exts_found.get(info.extension, 0) + 1
            total_size += info.size_bytes
            results.append(info)

    results.sort(key=_get_creation_time)
    return results
