"""Organizer — executes file organization operations."""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

from deskmind.models.schemas import ActionType, DeskMindConfig, OrganizeAction, OrganizePlan


class Organizer:
    """Executes an OrganizePlan: moves/copies/archives files on the filesystem."""

    def __init__(self, config: DeskMindConfig):
        self.config = config
        self.desktop = config.resolved_desktop

    def execute(self, plan: OrganizePlan) -> list[OrganizeAction]:
        """Execute the plan. Returns list of successfully executed actions."""
        results: list[OrganizeAction] = []
        undo_log: list[dict] = []

        for action in plan.actions:
            if action.skip:
                results.append(action)
                continue

            result = self._execute_action(action)
            if result:
                undo_log.append(result)
            results.append(action)

        # Save undo log
        if undo_log:
            self._save_undo_log(undo_log)

        return results

    def _execute_action(self, action: OrganizeAction) -> Optional[dict]:
        """Execute a single action. Returns undo info or None on failure."""
        src = action.file_path
        if not src.exists():
            action.skip = True
            action.reason = f"File not found: {src}"
            return None

        if action.action == ActionType.delete:
            return self._delete_file(action)

        if action.action in (ActionType.move, ActionType.archive):
            return self._move_file(action)

        if action.action == ActionType.copy:
            return self._copy_file(action)

        return None

    def _get_target_path(self, action: OrganizeAction) -> Optional[Path]:
        """Determine the target path for a move/copy action."""
        target_folder = action.target_folder or "_Uncategorized"
        folder_path = self.desktop / target_folder

        try:
            folder_path.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            action.skip = True
            action.reason = f"Cannot create folder '{target_folder}': {e}"
            return None

        name = action.new_name or action.file_path.name
        return folder_path / name

    def _move_file(self, action: OrganizeAction) -> Optional[dict]:
        """Move a file to its target folder."""
        target = self._get_target_path(action)
        if target is None:
            return None

        if target.exists():
            # Add suffix to avoid overwrite
            target = self._resolve_conflict(target)

        undo_info = {
            "from": str(target),
            "to": str(action.file_path),
            "action": "move",
            "timestamp": datetime.now().isoformat(),
        }

        try:
            shutil.move(str(action.file_path), str(target))
            action.reason = f"Moved to {target.parent.name}/"
        except OSError as e:
            action.skip = True
            action.reason = f"Move failed: {e}"
            return None

        return undo_info

    def _copy_file(self, action: OrganizeAction) -> Optional[dict]:
        """Copy a file to its target folder."""
        target = self._get_target_path(action)
        if target is None:
            return None

        if target.exists():
            target = self._resolve_conflict(target)

        try:
            shutil.copy2(str(action.file_path), str(target))
            action.reason = f"Copied to {target.parent.name}/"
        except OSError as e:
            action.skip = True
            action.reason = f"Copy failed: {e}"
            return None

        return None  # copies don't need undo

    def _delete_file(self, action: OrganizeAction) -> Optional[dict]:
        """Delete (send to trash) a file."""
        from send2trash import send2trash

        undo_info = {
            "from": "trash",
            "to": str(action.file_path),
            "action": "restore_from_trash",
            "timestamp": datetime.now().isoformat(),
        }

        try:
            send2trash(str(action.file_path))
            action.reason = "Sent to trash"
        except OSError as e:
            action.skip = True
            action.reason = f"Delete failed: {e}"
            return None

        return undo_info

    def _resolve_conflict(self, path: Path) -> Path:
        """Resolve filename conflict by adding a suffix."""
        stem = path.stem
        suffix = path.suffix
        counter = 1
        while True:
            new_path = path.parent / f"{stem}_{counter}{suffix}"
            if not new_path.exists():
                return new_path
            counter += 1

    def _save_undo_log(self, actions: list[dict]):
        """Save undo log to a JSON file on the desktop."""
        undo_dir = self.desktop / ".deskmind"
        undo_dir.mkdir(exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_path = undo_dir / f"undo_{timestamp}.json"
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(actions, f, ensure_ascii=False, indent=2)

    def undo_last(self) -> int:
        """Undo the last organization (reverse the last undo log)."""
        undo_dir = self.desktop / ".deskmind"
        if not undo_dir.exists():
            return 0

        logs = sorted(undo_dir.glob("undo_*.json"), reverse=True)
        if not logs:
            return 0

        restored = 0
        log_path = logs[0]
        with open(log_path, encoding="utf-8") as f:
            actions = json.load(f)

        for entry in reversed(actions):
            src = Path(entry["from"])
            dst = Path(entry["to"])
            if entry["action"] == "move" and src.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                try:
                    shutil.move(str(src), str(dst))
                    restored += 1
                except OSError:
                    pass

        log_path.unlink(missing_ok=True)
        return restored
