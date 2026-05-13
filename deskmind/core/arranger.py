"""Desktop icon position snapshot — read/restore icon positions via Windows API.

On Windows 10/11, desktop ListView supports READING positions (via cross-process
memory), but SETTING positions is overridden by the shell. We save position
snapshots for undo and use folder-based organization for zone arrangement.

APIs used:
- VirtualAllocEx: allocate memory in explorer.exe for cross-process API calls
- LVM_GETITEMPOSITION: read icon positions
- LVM_GETITEMTEXTW: read icon text labels
"""

from __future__ import annotations

import ctypes
import json
from ctypes import wintypes
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import win32gui

# ── Constants ──────────────────────────────────────────────────────────────────

LVM_FIRST = 0x1000
LVM_GETITEMCOUNT = LVM_FIRST + 4
LVM_GETITEMPOSITION = LVM_FIRST + 16
LVM_GETITEMTEXTW = 0x102D

LVIF_TEXT = 0x0001
MEM_COMMIT = 0x1000
PAGE_READWRITE = 0x04
PROCESS_ALL_ACCESS = 0x1F0FFF

PROGMAN_CLASS = "Progman"
DEFVIEW_CLASS = "SHELLDLL_DefView"
LISTVIEW_CLASS = "SysListView32"
WORKERW_CLASS = "WorkerW"


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class LVITEMW(ctypes.Structure):
    _fields_ = [
        ("mask", wintypes.UINT),
        ("iItem", wintypes.INT),
        ("iSubItem", wintypes.INT),
        ("state", wintypes.UINT),
        ("stateMask", wintypes.UINT),
        ("pszText", wintypes.LPVOID),
        ("cchTextMax", wintypes.INT),
        ("iImage", wintypes.INT),
        ("lParam", wintypes.LPARAM),
        ("iIndent", wintypes.INT),
    ]


# ── Data models ────────────────────────────────────────────────────────────────


@dataclass
class IconPosition:
    """Position of a single desktop icon."""
    index: int
    name: str
    x: int
    y: int

    def to_dict(self) -> dict:
        return {"index": self.index, "name": self.name, "x": self.x, "y": self.y}


@dataclass
class PositionSnapshot:
    """Full snapshot of all icon positions before a reorganization."""
    timestamp: str
    positions: list[IconPosition] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "positions": [p.to_dict() for p in self.positions],
        }


# ── Desktop ListView access ────────────────────────────────────────────────────


def _find_desktop_listview() -> Optional[int]:
    """Find the desktop SysListView32 window handle via WorkerW."""
    def _enum_windows(h, ctx):
        if win32gui.GetClassName(h) == WORKERW_CLASS:
            defview = win32gui.FindWindowEx(h, 0, DEFVIEW_CLASS, None)
            if defview:
                lv = win32gui.FindWindowEx(defview, 0, LISTVIEW_CLASS, None)
                if lv:
                    ctx.append(lv)
        return True

    handles: list[int] = []
    win32gui.EnumWindows(_enum_windows, handles)
    return handles[0] if handles else None


def _open_explorer_process(hwnd: int) -> Optional[int]:
    pid = wintypes.DWORD()
    ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    kernel32 = ctypes.windll.kernel32
    return kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, pid.value)


# ── Read positions ─────────────────────────────────────────────────────────────


def get_all_icon_positions() -> list[IconPosition]:
    """Read all desktop icon positions + names.

    Uses cross-process memory allocation (VirtualAllocEx) to read the
    desktop ListView in the explorer.exe process.
    """
    hwnd = _find_desktop_listview()
    if hwnd is None:
        raise RuntimeError("Could not find desktop ListView window.")

    h_process = _open_explorer_process(hwnd)
    if not h_process:
        raise RuntimeError("Could not open explorer.exe process.")

    try:
        count = win32gui.SendMessage(hwnd, LVM_GETITEMCOUNT, 0, 0)
        kernel32 = ctypes.windll.kernel32

        # Allocate remote memory
        remote_pt = kernel32.VirtualAllocEx(
            h_process, None, ctypes.sizeof(POINT), MEM_COMMIT, PAGE_READWRITE
        )
        remote_buf = kernel32.VirtualAllocEx(
            h_process, None, 520, MEM_COMMIT, PAGE_READWRITE
        )
        remote_lvitem = kernel32.VirtualAllocEx(
            h_process, None, ctypes.sizeof(LVITEMW), MEM_COMMIT, PAGE_READWRITE
        )

        if not all([remote_pt, remote_buf, remote_lvitem]):
            raise RuntimeError("Failed to allocate remote memory in explorer.exe.")

        written = ctypes.c_size_t()
        results: list[IconPosition] = []

        for i in range(count):
            # Read position
            pt = POINT(0, 0)
            kernel32.WriteProcessMemory(
                h_process, remote_pt, ctypes.byref(pt),
                ctypes.sizeof(POINT), ctypes.byref(written)
            )
            pos_result = win32gui.SendMessage(hwnd, LVM_GETITEMPOSITION, i, remote_pt)

            name = ""
            if pos_result:
                kernel32.ReadProcessMemory(
                    h_process, remote_pt, ctypes.byref(pt),
                    ctypes.sizeof(POINT), ctypes.byref(written)
                )

            # Read name
            lvitem = LVITEMW(
                mask=LVIF_TEXT, iItem=i, iSubItem=0,
                pszText=remote_buf, cchTextMax=260,
            )
            kernel32.WriteProcessMemory(
                h_process, remote_lvitem, ctypes.byref(lvitem),
                ctypes.sizeof(LVITEMW), ctypes.byref(written)
            )
            name_result = win32gui.SendMessage(hwnd, LVM_GETITEMTEXTW, i, remote_lvitem)
            if name_result > 0:
                name_buf = ctypes.create_unicode_buffer(260)
                kernel32.ReadProcessMemory(
                    h_process, remote_buf, name_buf, 520, ctypes.byref(written)
                )
                name = name_buf.value.strip()

            results.append(IconPosition(
                index=i, name=name, x=pt.x, y=pt.y,
            ))

        # Cleanup
        for ptr in [remote_pt, remote_buf, remote_lvitem]:
            if ptr:
                kernel32.VirtualFreeEx(h_process, ptr, 0, 0x8000)

        return results

    finally:
        ctypes.windll.kernel32.CloseHandle(h_process)


# ── Snapshot I/O ────────────────────────────────────────────────────────────────


def _snapshot_path(desktop: Path) -> Path:
    snap_dir = desktop / ".deskmind"
    snap_dir.mkdir(exist_ok=True)
    return snap_dir / "positions_snapshot.json"


def save_snapshot(desktop: Path) -> list[IconPosition]:
    """Save current icon positions to a snapshot file. Returns the positions."""
    positions = get_all_icon_positions()
    snap = PositionSnapshot(
        timestamp=datetime.now().isoformat(),
        positions=positions,
    )
    with open(_snapshot_path(desktop), "w", encoding="utf-8") as f:
        json.dump(snap.to_dict(), f, ensure_ascii=False, indent=2)
    return positions


def load_snapshot(desktop: Path) -> Optional[list[IconPosition]]:
    """Load the last position snapshot."""
    path = _snapshot_path(desktop)
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return [IconPosition(**p) for p in data.get("positions", [])]


# ── Zone helpers ────────────────────────────────────────────────────────────────


def zone_to_folder(zone_name: str) -> str:
    """Convert a zone name to a folder name for desktop organization.

    Since we can't position icons at arbitrary coordinates on Windows 10/11,
    we create folders named after zones instead. The user can visually
    arrange these folders on their desktop.
    """
    mapping = {
        "top-left": "[Zone] Top Left",
        "top-center": "[Zone] Top Center",
        "top-right": "[Zone] Top Right",
        "middle-left": "[Zone] Middle Left",
        "center": "[Zone] Center",
        "middle-center": "[Zone] Center",
        "middle-right": "[Zone] Middle Right",
        "bottom-left": "[Zone] Bottom Left",
        "bottom-center": "[Zone] Bottom Center",
        "bottom-right": "[Zone] Bottom Right",
        "top": "[Zone] Top",
        "middle": "[Zone] Middle",
        "bottom": "[Zone] Bottom",
        "left": "[Zone] Left",
        "right": "[Zone] Right",
    }
    if zone_name in mapping:
        return mapping[zone_name]
    # Replace hyphens with spaces for cleaner folder names
    display = zone_name.replace("-", " ").title()
    return f"[Zone] {display}"
