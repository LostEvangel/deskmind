"""DeskMind CLI — command-line interface for desktop organization."""

from __future__ import annotations

import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table
from rich.text import Text

from deskmind import __version__

console = Console()
err_console = Console(stderr=True)


@click.group()
@click.version_option(version=__version__, message="DeskMind v%(version)s")
def cli():
    """DeskMind — AI-powered desktop files organization agent."""


@cli.command()
@click.option(
    "--rule", "-r",
    default="",
    help="Natural language rule for organizing (e.g. 'group by project')",
)
@click.option(
    "--preview", is_flag=True, default=False,
    help="Preview only, don't execute",
)
@click.option(
    "--config", "config_path",
    default=None,
    help="Path to config file",
    type=click.Path(exists=True, path_type=Path),
)
def run(rule: str, preview: bool, config_path: Path | None):
    """Scan the desktop and organize files."""
    from deskmind.config.settings import get_default_rules_path, load_config
    from deskmind.core.classifier import BaseClassifier
    from deskmind.core.organizer import Organizer
    from deskmind.core.rules_engine import (
        build_llm_rule_text,
        load_rules_from_yaml,
        pre_match_files,
    )
    from deskmind.core.scanner import scan_desktop

    config = load_config(config_path)
    files = scan_desktop(config)

    if not files:
        console.print("[yellow]No files found on desktop to organize.[/]")
        return

    console.print(f"[bold]Scanning...[/] Found {len(files)} items on desktop.")

    # Load rules
    rules_path = Path(config.rules_path) if config.rules_path else get_default_rules_path()
    rules = load_rules_from_yaml(rules_path) if rules_path.exists() else []

    # Pre-match structured rules
    prematched, remaining = pre_match_files(files, rules)
    if prematched:
        console.print(f"[green]Pre-matched {len(prematched)} files by structured rules.[/]")

    if not remaining:
        from deskmind.models.schemas import OrganizePlan
        final_plan = OrganizePlan(
            actions=prematched,
            summary="All files matched by structured rules.",
        )
    else:
        # LLM classification for remaining files
        console.print(f"[bold]Sending {len(remaining)} files to LLM for classification...[/]")

        llm_rule = build_llm_rule_text(rules, rule)
        classifier = BaseClassifier.create(config.llm)
        llm_plan = classifier.classify(remaining, llm_rule)

        # Combine prematched + LLM results
        from deskmind.models.schemas import OrganizePlan
        final_plan = OrganizePlan(
            actions=prematched + llm_plan.actions,
            summary=llm_plan.summary,
            created_folders=llm_plan.created_folders,
        )

    # Show the plan
    _show_plan(final_plan, files)

    if preview:
        console.print("\n[dim]Preview mode — no changes made.[/]")
        return

    # Confirm
    if config.preview_required:
        confirm = click.confirm("\nExecute this plan?", default=True)
        if not confirm:
            console.print("[yellow]Cancelled.[/]")
            return

    # Save position snapshot before any changes (for undo reference)
    try:
        from deskmind.core.arranger import save_snapshot
        save_snapshot(config.resolved_desktop)
    except Exception:
        pass  # snapshot is optional

    # Convert arrange actions to move actions (zone → folder)
    from deskmind.core.arranger import zone_to_folder
    for action in final_plan.actions:
        if action.action == "arrange" and not action.skip:
            action.action = "move"
            action.target_folder = zone_to_folder(action.zone or "Center")

    # Execute all actions via Organizer
    organizer = Organizer(config)
    results = organizer.execute(final_plan)
    executed = len([a for a in results if not a.skip])
    skipped = len([a for a in results if a.skip])

    console.print(f"\n[green]Done![/] {executed} files organized, {skipped} skipped.")
    console.print("[dim]Use 'deskmind undo' to revert if needed.[/]")


@cli.command()
def undo():
    """Undo the last desktop organization. Restores files to original locations."""
    from deskmind.config.settings import load_config
    from deskmind.core.organizer import Organizer

    config = load_config()
    organizer = Organizer(config)
    count = organizer.undo_last()

    if count > 0:
        console.print(f"[green]Restored {count} files to their original locations.[/]")
    else:
        console.print("[yellow]No undo history found.[/]")


@cli.command()
def init():
    """Create a default DeskMind config and rules file."""
    from deskmind.config.settings import (
        get_default_rules_path,
        load_config,
        save_config,
        save_default_rules,
    )

    config_path = Path.home() / ".deskmind" / "config.yaml"
    config = load_config()
    save_config(config)
    save_default_rules()

    console.print(f"[green]Created:[/] {config_path}")
    console.print(f"[green]Created:[/] {get_default_rules_path()}")
    console.print("\nEdit these files to configure rules and LLM settings.")
    console.print("Then run: [bold]deskmind run --rule \"your rule here\"[/]")


@cli.command()
def mcp():
    """Start the DeskMind MCP server for Claude Desktop/Code integration."""
    from deskmind.mcp_server import main as mcp_main
    mcp_main()


@cli.command("list")
def list_files():
    """List files on the desktop."""
    from deskmind.config.settings import load_config
    from deskmind.core.scanner import scan_desktop

    config = load_config()
    files = scan_desktop(config)

    if not files:
        console.print("[yellow]No files found.[/]")
        return

    table = Table(title=f"Desktop — {len(files)} items")
    table.add_column("Name", style="cyan")
    table.add_column("Size", justify="right")
    table.add_column("Modified", style="dim")
    table.add_column("Type")

    for f in files:
        size = _format_size(f.size_bytes)
        mod = f.modified_at.strftime("%Y-%m-%d %H:%M")
        ftype = "DIR" if f.is_directory else f.extension or ""
        table.add_row(f.name, size, mod, ftype)

    console.print(table)


def _show_plan(plan, files):
    """Display the organization plan as a rich table."""
    if not plan.actions:
        console.print("[yellow]No actions in the plan.[/]")
        return

    table = Table(title="Organization Plan")
    table.add_column("File", style="cyan")
    table.add_column("Action", style="yellow")
    table.add_column("Target")
    table.add_column("Reason")

    file_map = {f.path: f for f in files}

    from deskmind.core.arranger import zone_to_folder

    for action in plan.actions:
        if action.skip:
            continue

        display_name = action.file_path.name
        if src_obj := file_map.get(action.file_path):
            if src_obj.is_directory:
                display_name = f"[DIR] {display_name}"

        if action.action == "arrange":
            target = zone_to_folder(action.zone or "center")
        elif action.target_folder:
            target = action.target_folder
            if action.new_name:
                target = f"{target} → {action.new_name}"
        else:
            target = ""

        table.add_row(
            display_name,
            action.action.value,
            target,
            action.reason,
        )

    console.print(table)

    if plan.summary:
        console.print(f"\n[dim]{plan.summary}[/]")

    if plan.created_folders:
        folders = ", ".join(plan.created_folders)
        console.print(f"\nFolders to create: [bold]{folders}[/]")

    arrange_actions = [a for a in plan.actions if a.action == "arrange"]
    if arrange_actions:
        zones = set(a.zone for a in arrange_actions if a.zone)
        console.print(f"Desktop zones: [bold]{', '.join(sorted(zones))}[/]")
        console.print("[dim]Files will be moved to zone-named folders (Windows limitation:"
                      " icon position API is blocked).[/]")


def _format_size(bytes_: int) -> str:
    if bytes_ < 1024:
        return f"{bytes_} B"
    elif bytes_ < 1024**2:
        return f"{bytes_ / 1024:.1f} KB"
    else:
        return f"{bytes_ / 1024**2:.1f} MB"


def main():
    """Entry point for the CLI."""
    if len(sys.argv) == 1:
        # Running without arguments (e.g. double-clicked)
        cli(args=["--help"])
        print("\nPress Enter to exit...", end="")
        input()
        return
    cli()


if __name__ == "__main__":
    main()
