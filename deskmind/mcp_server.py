"""DeskMind MCP Server — integrate with Claude Desktop and Claude Code.

Exposes tools:
- scan_desktop    — list files on the desktop
- preview_organize — preview what the AI would do (no changes)
- organize         — execute the organization
- undo_last        — undo the last organization
- set_rule         — update the organizing rule
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mcp.server import Server, NotificationOptions
from mcp.server.models import InitializationOptions
from mcp.types import (
    GetPromptResult,
    Prompt,
    PromptArgument,
    PromptMessage,
    TextContent,
    Tool,
)

from deskmind.config.settings import (
    get_default_rules_path,
    load_config,
    save_config,
)
from deskmind.core.classifier import BaseClassifier
from deskmind.core.organizer import Organizer
from deskmind.core.rules_engine import (
    build_llm_rule_text,
    load_rules_from_yaml,
    pre_match_files,
)
from deskmind.core.scanner import scan_desktop
from deskmind.models.schemas import DeskMindConfig, FileInfo, LLMConfig, OrganizePlan

server = Server("deskmind")

# Store the user's latest rule in memory
_latest_rule: str = ""
_latest_plan: OrganizePlan | None = None


def _config() -> DeskMindConfig:
    return load_config()


def _files_to_text(files: list[FileInfo], max_items: int = 50) -> str:
    """Format file list as readable text for MCP output."""
    if not files:
        return "No files found."
    lines = [f"{'Name':<40} {'Size':<10} {'Modified':<20} {'Type'}"]
    lines.append("-" * 90)
    for f in files[:max_items]:
        modified = f.modified_at.strftime("%Y-%m-%d %H:%M")
        size = f"{f.size_bytes / 1024:.1f} KB" if f.size_bytes > 1024 else f"{f.size_bytes} B"
        ftype = "DIR" if f.is_directory else f.extension or "(no ext)"
        lines.append(f"{f.name:<40} {size:<10} {modified:<20} {ftype}")
    if len(files) > max_items:
        lines.append(f"... and {len(files) - max_items} more items")
    return "\n".join(lines)


def _plan_to_text(plan: OrganizePlan) -> str:
    """Format an OrganizePlan as readable text."""
    if not plan.actions:
        return "No actions in the plan."

    lines = ["## Organization Plan", ""]
    lines.append(f"Summary: {plan.summary}")
    if plan.created_folders:
        lines.append(f"Folders to create: {', '.join(plan.created_folders)}")

    arrange_zones = set(a.zone for a in plan.actions if a.action == "arrange" and a.zone)
    if arrange_zones:
        lines.append(f"Desktop zones: {', '.join(sorted(arrange_zones))}")
    lines.append("")

    lines.append(f"{'Action':<8} {'File':<35} {'Target':<20} {'Reason'}")
    lines.append("-" * 90)

    for a in plan.actions:
        if a.skip:
            continue
        if a.action == "arrange":
            from deskmind.core.arranger import zone_to_folder
            dest = zone_to_folder(a.zone or "center")
        else:
            dest = a.target_folder or ""
            if a.new_name:
                dest += f" → {a.new_name}"
        lines.append(f"{a.action.value:<8} {a.file_path.name:<35} {dest:<20} {a.reason}")

    arrange_notes = [a for a in plan.actions if a.action == "arrange"]
    if arrange_notes:
        lines.append("")
        lines.append("Note: 'arrange' files will be moved to zone-named folders "
                      "(Windows limitation).")

    return "\n".join(lines)


# ── Tools ──────────────────────────────────────────────────────────────────────


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="scan_desktop",
            description="Scan the desktop and list all files with their metadata.",
            inputSchema={
                "type": "object",
                "properties": {
                    "max_items": {
                        "type": "integer",
                        "description": "Maximum number of files to list (default 50)",
                        "default": 50,
                    }
                },
            },
        ),
        Tool(
            name="preview_organize",
            description="Preview the organization plan. Shows what the AI will do without making changes.",
            inputSchema={
                "type": "object",
                "properties": {
                    "rule": {
                        "type": "string",
                        "description": "Natural language rule for organizing (e.g. 'group files by project')",
                    }
                },
                "required": ["rule"],
            },
        ),
        Tool(
            name="organize",
            description="Execute the organization plan. Moves files according to the last previewed plan or generates a new one.",
            inputSchema={
                "type": "object",
                "properties": {
                    "rule": {
                        "type": "string",
                        "description": "Natural language rule for organizing. If empty, uses the last set rule.",
                    },
                    "confirm": {
                        "type": "boolean",
                        "description": "Must be set to true to confirm execution.",
                        "default": False,
                    },
                },
                "required": ["confirm"],
            },
        ),
        Tool(
            name="undo_last",
            description="Undo the last desktop organization. Restores files to their original locations.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="set_rule",
            description="Set the default organizing rule for future use.",
            inputSchema={
                "type": "object",
                "properties": {
                    "rule": {
                        "type": "string",
                        "description": "Natural language rule (e.g. 'Keep work documents in Work folder, personal in Personal')",
                    }
                },
                "required": ["rule"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    global _latest_rule, _latest_plan

    config = _config()

    if name == "scan_desktop":
        files = scan_desktop(config)
        max_items = arguments.get("max_items", 50)
        text = _files_to_text(files, max_items)
        return [TextContent(type="text", text=text)]

    if name == "preview_organize":
        rule = arguments.get("rule", _latest_rule)
        if not rule:
            return [TextContent(type="text", text="Please provide a rule for organizing (e.g. 'group files by type').")]

        _latest_rule = rule
        _latest_plan = _build_plan(config, rule)
        return [TextContent(type="text", text=_plan_to_text(_latest_plan))]

    if name == "organize":
        rule = arguments.get("rule", _latest_rule)
        confirmed = arguments.get("confirm", False)

        if not confirmed:
            return [TextContent(
                type="text",
                text="Execution requires confirmation. Set confirm=true to proceed.\n"
                     "Run preview_organize first to see what will happen."
            )]

        if not _latest_plan or rule != _latest_rule:
            if rule:
                _latest_rule = rule
                _latest_plan = _build_plan(config, rule)
            elif _latest_plan is None:
                return [TextContent(type="text", text="No plan to execute. Run preview_organize first with a rule.")]

        # Save position snapshot (optional, for reference)
        try:
            from deskmind.core.arranger import save_snapshot
            save_snapshot(config.resolved_desktop)
        except Exception:
            pass

        # Convert arrange actions to move actions (zone name → folder name)
        from deskmind.core.arranger import zone_to_folder
        for action in _latest_plan.actions:
            if action.action == "arrange" and not action.skip:
                action.action = "move"
                action.target_folder = zone_to_folder(action.zone or "Center")

        # Execute all actions via Organizer
        organizer = Organizer(config)
        results = organizer.execute(_latest_plan)
        executed = len([a for a in results if not a.skip])
        skipped = len([a for a in results if a.skip])

        return [TextContent(
            type="text",
            text=f"Done! {executed} files organized, {skipped} skipped.\n"
                 f"Use undo_last to revert if needed."
        )]

    if name == "undo_last":
        organizer = Organizer(config)
        count = organizer.undo_last()

        if count > 0:
            return [TextContent(type="text", text=f"Restored {count} files to their original locations.")]
        return [TextContent(type="text", text="No undo history found.")]

    if name == "set_rule":
        rule = arguments.get("rule", "")
        if rule:
            _latest_rule = rule
            return [TextContent(type="text", text=f"Rule set: {rule}")]
        return [TextContent(type="text", text="No rule provided.")]

    raise ValueError(f"Unknown tool: {name}")


# ── Prompts ──────────────────────────────────────────────────────────────────────


@server.list_prompts()
async def list_prompts() -> list[Prompt]:
    return [
        Prompt(
            name="organize_desktop",
            description="Create a prompt for organizing the desktop",
            arguments=[
                PromptArgument(
                    name="rule",
                    description="Natural language rule for organizing",
                    required=True,
                )
            ],
        ),
    ]


@server.get_prompt()
async def get_prompt(
    name: str, arguments: dict[str, str] | None
) -> GetPromptResult:
    if name == "organize_desktop":
        rule = arguments.get("rule", "organize by type") if arguments else "organize by type"
        return GetPromptResult(
            messages=[
                PromptMessage(
                    role="user",
                    content=TextContent(
                        type="text",
                        text=f"Please organize my desktop. Rule: {rule}\n\n"
                             f"First use scan_desktop to see my files, "
                             f"then preview_organize with the rule, "
                             f"and finally organize with confirm=true if I approve.",
                    ),
                )
            ],
        )

    raise ValueError(f"Unknown prompt: {name}")


# ── Helpers ────────────────────────────────────────────────────────────────────


def _build_plan(config: DeskMindConfig, rule: str) -> OrganizePlan:
    """Build an organization plan from config + rule."""
    files = scan_desktop(config)
    rules_path = Path(config.rules_path) if config.rules_path else get_default_rules_path()
    rules = load_rules_from_yaml(rules_path) if rules_path.exists() else []

    prematched, remaining = pre_match_files(files, rules)

    if not remaining:
        return OrganizePlan(
            actions=prematched,
            summary="All files matched by structured rules.",
        )

    llm_rule = build_llm_rule_text(rules, rule)
    classifier = BaseClassifier.create(config.llm)
    llm_plan = classifier.classify(remaining, llm_rule)

    return OrganizePlan(
        actions=prematched + llm_plan.actions,
        summary=llm_plan.summary,
        created_folders=llm_plan.created_folders,
    )


# ── Entry Point ────────────────────────────────────────────────────────────────


async def main():
    async with server.run() as running:
        await running


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
