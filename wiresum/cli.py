"""CLI for wiresum - talks to the server API."""

import html
import platform
import queue
import shutil
import subprocess
import threading
import webbrowser
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import click
import httpx
import readchar
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .config import load_config


def copy_to_clipboard(text: str) -> bool:
    """Copy text to clipboard. Returns True if successful.

    Supports macOS (pbcopy), Linux (xclip or xsel), and Windows (clip).
    """
    system = platform.system()

    try:
        if system == "Darwin":
            # macOS
            subprocess.run(["pbcopy"], input=text.encode(), check=True)
            return True
        elif system == "Linux":
            # Linux - try xclip first, then xsel
            if shutil.which("xclip"):
                subprocess.run(
                    ["xclip", "-selection", "clipboard"],
                    input=text.encode(),
                    check=True,
                )
                return True
            elif shutil.which("xsel"):
                subprocess.run(
                    ["xsel", "--clipboard", "--input"],
                    input=text.encode(),
                    check=True,
                )
                return True
            return False
        elif system == "Windows":
            # Windows
            subprocess.run(["clip"], input=text.encode(), check=True, shell=True)
            return True
        else:
            return False
    except Exception:
        return False


console = Console()


def get_domain(url: str | None) -> str:
    """Extract domain from URL (e.g., 'gemini.com' from 'https://www.gemini.com/path')."""
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        domain = parsed.netloc
        # Remove www. prefix
        if domain.startswith("www."):
            domain = domain[4:]
        return domain
    except Exception:
        return ""

# Color palette for interests (deterministically assigned via hash)
INTEREST_COLORS = [
    "bright_magenta",
    "bright_green",
    "bright_yellow",
    "bright_cyan",
    "bright_blue",
    "bright_red",
    "orange1",
    "turquoise2",
]


def get_interest_color(interest: str) -> str:
    """Get a deterministic color for an interest based on its hash."""
    if not interest:
        return "white"
    return INTEREST_COLORS[hash(interest) % len(INTEREST_COLORS)]


def format_date(iso_string: str | None) -> str:
    """Format ISO date as Today, Yesterday, or 'Jan 25'."""
    if not iso_string:
        return ""

    try:
        dt = datetime.fromisoformat(iso_string.replace("Z", "+00:00"))
        today = datetime.now(timezone.utc).date()
        entry_date = dt.date()

        if entry_date == today:
            return "Today"
        elif entry_date == today - timedelta(days=1):
            return "Yesterday"
        else:
            return dt.strftime("%b %d")
    except (ValueError, AttributeError):
        return ""


def get_client() -> httpx.Client:
    """Get HTTP client configured for the server."""
    config = load_config()
    return httpx.Client(base_url=config.server_url, timeout=30.0)


def handle_error(response: httpx.Response):
    """Handle HTTP errors."""
    if response.status_code >= 400:
        try:
            detail = response.json().get("detail", response.text)
        except Exception:
            detail = response.text
        console.print(f"[red]Error: {detail}")
        raise SystemExit(1)


# --- Grouped Digest View (default) ---


def format_day_label(day_offset: int) -> str:
    """Format day offset as readable label."""
    if day_offset == 0:
        return "Today"
    elif day_offset == 1:
        return "Yesterday"
    else:
        target_date = datetime.now(timezone.utc).date() - timedelta(days=day_offset)
        return target_date.strftime("%b %d")


def build_digest_display(
    digest_data: list, stats: dict, cursor: int = -1, day_offset: int = 0,
    last_refresh: datetime | None = None
) -> tuple[Group, list, int]:
    """Build the digest display with auto-expanding topic groups.

    Returns (display, all_entries, cursor_group_idx).
    """
    # Collect all entries with group info for flat navigation
    all_entries = []
    entry_to_group = {}  # Map entry index to group index

    for group_idx, group in enumerate(digest_data):
        for entry in group.get("entries", []):
            entry_to_group[len(all_entries)] = group_idx
            all_entries.append({
                **entry,
                "interest_key": group.get("interest_key"),
                "interest_label": group.get("interest_label"),
            })

    day_label = format_day_label(day_offset)
    total_signal = len(all_entries)
    total_processed = stats.get("total_entries", 0) - stats.get("unprocessed", 0)

    # Format refresh time
    if last_refresh:
        refresh_str = last_refresh.strftime("%H:%M")
    else:
        refresh_str = "--:--"

    # Calculate max title width based on terminal (leave room for indent and padding)
    max_title_width = console.size.width - 12

    # Determine which group should be expanded (the one containing cursor)
    expanded_group = entry_to_group.get(cursor, 0) if cursor >= 0 else 0

    if not digest_data:
        return Group(
            Panel(
                f"[dim]No entries for {day_label.lower()}.[/dim]",
                title=f"[bold]Wiresum[/bold] · {day_label} · [dim]{refresh_str}[/dim]",
                subtitle="[dim]←→ change day · q quit[/dim]",
                border_style="dim",
            )
        ), [], 0

    # Build the list panel content with auto-expanding groups
    list_lines = []
    global_entry_idx = 0

    for group_idx, group in enumerate(digest_data):
        interest_label = group.get("interest_label") or "Other"
        interest_key = group.get("interest_key") or ""
        entries = group.get("entries", [])
        count = len(entries)
        unread_count = sum(1 for e in entries if not e.get("read_at"))
        color = get_interest_color(interest_key)
        is_expanded = group_idx == expanded_group

        # Group header with count (green if unread items in collapsed group)
        if is_expanded:
            list_lines.append(f"[bold {color}]▼ {interest_label} ({count})[/bold {color}]")
        else:
            if unread_count > 0:
                list_lines.append(f"[dim]▶ {interest_label}[/dim] [green]({unread_count})[/green]")
            else:
                list_lines.append(f"[dim]▶ {interest_label} ({count})[/dim]")

        # Only show entries for expanded group
        if is_expanded:
            for entry in entries:
                title = html.unescape(entry.get("title") or entry.get("url") or "Untitled")
                # Truncate title based on terminal width
                if len(title) > max_title_width:
                    title = title[:max_title_width - 3] + "..."

                is_selected = global_entry_idx == cursor
                is_signal = entry.get("is_signal", True)
                is_read = entry.get("read_at") is not None

                if is_selected:
                    # Selected entry - cyan for signal, red for filtered
                    if is_signal:
                        list_lines.append(f"  [bold cyan]› {title}[/bold cyan]")
                    else:
                        list_lines.append(f"  [bold red]› {title}[/bold red]")
                else:
                    # Unselected entry - green if unread, dim if read
                    if not is_signal:
                        list_lines.append(f"    [dim strike]{title}[/dim strike]")
                    elif is_read:
                        list_lines.append(f"    [dim]{title}[/dim]")
                    else:
                        list_lines.append(f"    [green]{title}[/green]")

                global_entry_idx += 1
        else:
            global_entry_idx += count

        if is_expanded:
            list_lines.append("")  # Spacing after expanded group

    list_panel = Panel(
        "\n".join(list_lines).rstrip(),
        title=f"[bold]Wiresum[/bold] · {day_label} · {total_signal}/{total_processed} signal · [dim]{refresh_str}[/dim]",
        subtitle="[dim]↑↓ navigate · ←→ day · Enter open · c copy · q quit[/dim]",
        border_style="dim",
    )

    # Build the detail panel for selected entry
    if cursor >= 0 and cursor < len(all_entries):
        selected = all_entries[cursor]
        title = html.unescape(selected.get("title") or "Untitled")
        reasoning = selected.get("reasoning") or ""
        date = format_date(selected.get("published_at"))
        feed = selected.get("feed_name") or ""
        url = selected.get("url") or ""
        domain = get_domain(url)
        interest_key = selected.get("interest_key") or ""
        interest_label = selected.get("interest_label") or ""
        color = get_interest_color(interest_key)

        # Format bullets nicely
        detail_lines = []
        if reasoning:
            for bullet in reasoning.split('\n'):
                if bullet.strip():
                    detail_lines.append(f"  {bullet.strip()}")
        else:
            detail_lines.append("[dim]No insights available[/dim]")

        # Format source line: "Today · domain via Feed Name" or "Today · Feed Name"
        detail_lines.append("")
        if domain and feed:
            detail_lines.append(f"[dim]{date} · {domain} via {feed}[/dim]")
        else:
            detail_lines.append(f"[dim]{date} · {feed or domain}[/dim]")

        detail_panel = Panel(
            "\n".join(detail_lines),
            title=f"[bold]{title}[/bold]",
            subtitle=f"[{color}]{interest_label}[/{color}]",
            border_style="cyan",
            padding=(1, 2),
        )
    else:
        detail_panel = Panel("[dim]Select an entry to see details[/dim]", border_style="dim")

    return Group(list_panel, detail_panel), all_entries, expanded_group


def fetch_digest_for_day(
    client: httpx.Client, day_offset: int, include_all: bool = False
) -> tuple[list, dict]:
    """Fetch digest data for a specific day."""
    # Calculate the date range for this day
    today = datetime.now(timezone.utc).date()
    target_date = today - timedelta(days=day_offset)

    # Get stats (still use broader range for context)
    response = client.get("/stats", params={"since_hours": 48})
    handle_error(response)
    stats = response.json()

    # Get digest for specific day using date params
    params = {
        "date": target_date.isoformat(),
        "limit_per_interest": 50 if include_all else 10,
    }
    if include_all:
        params["include_all"] = "true"

    response = client.get("/digest", params=params)
    handle_error(response)
    digest_data = response.json()

    return digest_data, stats


def mark_entry_read(client: httpx.Client, entry_id: int):
    """Mark an entry as read via the API."""
    try:
        client.post(f"/entries/{entry_id}/read")
    except Exception:
        pass  # Silently ignore errors


def show_digest_view(include_all: bool = False):
    """Show the grouped digest view (default)."""
    day_offset = 0
    cursor = 0
    previous_cursor = -1  # Track previous cursor to detect changes

    # Shared state for background refresh
    refresh_lock = threading.Lock()
    shared_data = {
        "digest": None, "stats": None, "day_offset": 0,
        "updated": False, "last_refresh": None
    }
    stop_event = threading.Event()
    key_queue = queue.Queue()

    def background_refresh(client: httpx.Client):
        """Background thread that refreshes data every 30 seconds."""
        while not stop_event.wait(30):
            try:
                with refresh_lock:
                    current_day = shared_data["day_offset"]
                digest, stats = fetch_digest_for_day(client, current_day, include_all)
                with refresh_lock:
                    # Only update if we're still on the same day
                    if shared_data["day_offset"] == current_day:
                        shared_data["digest"] = digest
                        shared_data["stats"] = stats
                        shared_data["last_refresh"] = datetime.now()
                        shared_data["updated"] = True
            except Exception:
                pass  # Silently ignore refresh errors

    def key_reader():
        """Background thread that reads keyboard input."""
        while not stop_event.is_set():
            try:
                key = readchar.readkey()
                key_queue.put(key)
                if key == "q":
                    break
            except Exception:
                break

    with get_client() as client:
        digest_data, stats = fetch_digest_for_day(client, day_offset, include_all)
        last_refresh = datetime.now()
        display, all_entries, _ = build_digest_display(
            digest_data, stats, cursor, day_offset, last_refresh
        )

        # Initialize shared state and start background threads
        with refresh_lock:
            shared_data["digest"] = digest_data
            shared_data["stats"] = stats
            shared_data["day_offset"] = day_offset
            shared_data["last_refresh"] = last_refresh

        refresh_thread = threading.Thread(target=background_refresh, args=(client,), daemon=True)
        refresh_thread.start()

        key_thread = threading.Thread(target=key_reader, daemon=True)
        key_thread.start()

        with Live(console=console, refresh_per_second=4, screen=False) as live:
            live.update(display)

            # Mark initial entry as read (only in normal mode)
            if not include_all and all_entries:
                entry = all_entries[cursor]
                entry_id = entry.get("id")
                if entry_id and not entry.get("read_at"):
                    mark_entry_read(client, entry_id)
                    # Update digest_data directly so rebuild reflects read status
                    for group in digest_data:
                        for e in group.get("entries", []):
                            if e.get("id") == entry_id:
                                e["read_at"] = datetime.now().isoformat()
                                break
                previous_cursor = cursor
                display, all_entries, _ = build_digest_display(
                    digest_data, stats, cursor, day_offset, last_refresh
                )
                live.update(display)

            while True:
                # Check for background data updates
                with refresh_lock:
                    if shared_data["updated"]:
                        digest_data = shared_data["digest"]
                        stats = shared_data["stats"]
                        last_refresh = shared_data["last_refresh"]
                        shared_data["updated"] = False
                        # Preserve cursor position but clamp to valid range
                        if cursor >= len(all_entries):
                            cursor = max(0, len(all_entries) - 1)
                        display, all_entries, _ = build_digest_display(
                            digest_data, stats, cursor, day_offset, last_refresh
                        )
                        live.update(display)

                # Check for keyboard input (non-blocking with timeout)
                try:
                    key = key_queue.get(timeout=0.5)
                except queue.Empty:
                    continue  # No input, loop back to check for updates

                needs_refresh = False

                if key == readchar.key.UP or key == "k":
                    if all_entries:
                        cursor = (cursor - 1) % len(all_entries)
                elif key == readchar.key.DOWN or key == "j":
                    if all_entries:
                        cursor = (cursor + 1) % len(all_entries)
                elif key == readchar.key.LEFT or key == "h":
                    # Go back in time
                    day_offset = min(day_offset + 1, 30)  # Max 30 days back
                    cursor = 0
                    needs_refresh = True
                elif key == readchar.key.RIGHT or key == "l":
                    # Go forward in time
                    day_offset = max(day_offset - 1, 0)  # Can't go past today
                    cursor = 0
                    needs_refresh = True
                elif key == readchar.key.ENTER:
                    if all_entries:
                        url = all_entries[cursor].get("url")
                        if url:
                            webbrowser.open(url)
                elif key == "c":
                    if all_entries:
                        url = all_entries[cursor].get("url")
                        if url:
                            copy_to_clipboard(url)
                elif key == "q":
                    break

                if needs_refresh:
                    digest_data, stats = fetch_digest_for_day(client, day_offset, include_all)
                    last_refresh = datetime.now()
                    with refresh_lock:
                        shared_data["digest"] = digest_data
                        shared_data["stats"] = stats
                        shared_data["day_offset"] = day_offset
                        shared_data["last_refresh"] = last_refresh
                        shared_data["updated"] = False

                # Mark entry as read when cursor moves to it (only in normal mode, not -a)
                if not include_all and cursor != previous_cursor and all_entries:
                    entry = all_entries[cursor]
                    entry_id = entry.get("id")
                    if entry_id and not entry.get("read_at"):
                        mark_entry_read(client, entry_id)
                        # Update digest_data directly so rebuild reflects read status
                        for group in digest_data:
                            for e in group.get("entries", []):
                                if e.get("id") == entry_id:
                                    e["read_at"] = datetime.now().isoformat()
                                    break
                    previous_cursor = cursor

                display, all_entries, _ = build_digest_display(
                    digest_data, stats, cursor, day_offset, last_refresh
                )
                live.update(display)

        # Stop background threads
        stop_event.set()


# --- Flat List View (wiresum list) ---


def build_entries_table(
    entries: list, cursor: int, viewport_start: int, viewport_size: int, title: str = "Signal"
) -> Table:
    """Build a rich table with cursor highlighting and viewport scrolling."""
    total = len(entries)
    viewport_end = min(viewport_start + viewport_size, total)

    table = Table(
        title=f"{title} ({cursor + 1}/{total})",
        show_header=True,
        header_style="bold",
        expand=True,
    )
    table.add_column("#", style="dim", width=3)
    table.add_column("Date", style="dim", width=10)
    table.add_column("Source", style="dim", width=18)
    table.add_column("Interest", width=10)
    table.add_column("Title", style="white", no_wrap=False, ratio=1)
    table.add_column("Insight", style="italic", no_wrap=False, ratio=1)

    for i in range(viewport_start, viewport_end):
        entry = entries[i]
        date = format_date(entry.get("published_at"))
        source = entry.get("feed_name") or ""
        interest = entry.get("interest") or ""
        title_text = entry.get("title") or entry.get("url") or "Untitled"
        reasoning = entry.get("reasoning") or ""
        is_signal = entry.get("is_signal")

        # Get interest color
        interest_color = get_interest_color(interest)

        if i == cursor:
            # Highlighted row
            if is_signal is False:
                interest_display = "[bold dim]filtered[/bold dim]"
            else:
                interest_display = f"[bold {interest_color}]{interest}[/bold {interest_color}]"
            table.add_row(
                "[bold white]>[/bold white]",
                f"[bold]{date}[/bold]",
                f"[bold]{source}[/bold]",
                interest_display,
                f"[bold white]{title_text}[/bold white]",
                f"[bold italic]{reasoning}[/bold italic]",
            )
        elif is_signal is False:
            # Dim filtered-out entries
            table.add_row(
                f"[dim]{i + 1}[/dim]",
                f"[dim]{date}[/dim]",
                f"[dim]{source}[/dim]",
                "[dim]filtered[/dim]",
                f"[dim]{title_text}[/dim]",
                f"[dim]{reasoning}[/dim]",
            )
        else:
            table.add_row(
                str(i + 1),
                date,
                source,
                f"[{interest_color}]{interest}[/{interest_color}]",
                title_text,
                f"[italic]{reasoning}[/italic]",
            )

    return table


def interactive_list_with_live(entries: list, title: str = "Signal"):
    """Display an interactive list with keyboard navigation and scrolling."""
    if not entries:
        console.print("[dim]No entries to display.[/dim]")
        return

    cursor = 0
    viewport_start = 0
    viewport_size = 15  # Show 15 entries at a time

    console.print("[dim]↑/↓ or j/k: navigate  Enter: open in browser  q: quit[/dim]\n")

    with Live(console=console, refresh_per_second=10) as live:
        live.update(build_entries_table(entries, cursor, viewport_start, viewport_size, title))

        while True:
            key = readchar.readkey()

            try:
                if key == readchar.key.UP or key == "k":
                    cursor = max(0, cursor - 1)
                    # Scroll viewport up if cursor goes above visible area
                    if cursor < viewport_start:
                        viewport_start = cursor
                elif key == readchar.key.DOWN or key == "j":
                    cursor = min(len(entries) - 1, cursor + 1)
                    # Scroll viewport down if cursor goes below visible area
                    if cursor >= viewport_start + viewport_size:
                        viewport_start = cursor - viewport_size + 1
                elif key == readchar.key.ENTER:
                    url = entries[cursor].get("url")
                    if url:
                        webbrowser.open(url)
                elif key == "q" or key == "\x1b":
                    break
            except AttributeError:
                pass  # Ignore unrecognized keys

            live.update(build_entries_table(entries, cursor, viewport_start, viewport_size, title))

    console.print("\n")


# --- CLI Commands ---


@click.group(invoke_without_command=True)
@click.option("--all", "-a", "show_all", is_flag=True, help="Include filtered entries")
@click.pass_context
def cli(ctx, show_all: bool):
    """Wiresum: AI-powered feed filter.

    Run without arguments to see the digest view grouped by interest.
    Use 'wiresum list' for a flat table view.
    """
    if ctx.invoked_subcommand is None:
        show_digest_view(include_all=show_all)


@cli.command("list")
@click.option("--all", "-a", "show_all", is_flag=True, help="Show all entries, not just signal")
def list_entries(show_all: bool = False):
    """Show entries in a flat table view."""
    with get_client() as client:
        # Get stats
        response = client.get("/stats")
        handle_error(response)
        stats = response.json()

        # Get entries (signal only or all, sorted by published_at desc)
        params = {"limit": 50, "since_hours": 48}
        if not show_all:
            params["is_signal"] = True

        response = client.get("/entries", params=params)
        handle_error(response)
        entries = response.json()

    # Display stats
    console.print(
        Panel(
            f"[bold]Queue:[/bold] {stats['unprocessed']} unprocessed  |  "
            f"[bold]Signal:[/bold] {stats['signal']}  |  "
            f"[bold]Total:[/bold] {stats['total_entries']}",
            title="Wiresum",
        )
    )
    console.print()

    title = "All Entries (48h)" if show_all else "Signal (48h)"
    interactive_list_with_live(entries, title=title)


@cli.group()
def config():
    """Manage configuration."""
    pass


@config.command("show")
def config_show():
    """Show current configuration."""
    with get_client() as client:
        response = client.get("/config")
        handle_error(response)
        cfg = response.json()

    table = Table(title="Configuration")
    table.add_column("Key", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("model", cfg.get("model", ""))
    table.add_row("sync_interval", str(cfg.get("sync_interval", "")))
    process_after = cfg.get("process_after", "")
    table.add_row("process_after", process_after if process_after else "[dim](all entries)[/dim]")
    table.add_row("classification_prompt", cfg.get("classification_prompt", "")[:100] + "...")

    console.print(table)


@config.command("set")
@click.argument("key")
@click.argument("value")
def config_set(key: str, value: str):
    """Update a configuration value."""
    with get_client() as client:
        response = client.put("/config", json={"key": key, "value": value})
        handle_error(response)

    console.print(f"[green]Set {key} = {value}")


@cli.command()
@click.argument("entry_id", type=int)
def reprocess(entry_id: int):
    """Re-classify a specific entry."""
    with get_client() as client:
        response = client.post(f"/entries/{entry_id}/reprocess")
        handle_error(response)
        entry = response.json()

    console.print(f"[green]Reprocessed entry {entry_id}")
    console.print(f"  Interest: {entry.get('interest') or 'None'}")
    console.print(f"  Signal: {entry.get('is_signal')}")
    console.print(f"  Reasoning: {entry.get('reasoning')}")


@cli.group()
def interests():
    """Manage classification interests."""
    pass


@interests.command("list")
def interests_list():
    """List all interests."""
    with get_client() as client:
        response = client.get("/interests")
        handle_error(response)
        interests_data = response.json()

    table = Table(title="Interests")
    table.add_column("Key", style="cyan")
    table.add_column("Label", style="bold")
    table.add_column("Description", style="dim")

    for interest in interests_data:
        desc = interest.get("description") or ""
        if len(desc) > 60:
            desc = desc[:57] + "..."
        table.add_row(
            interest.get("key", ""),
            interest.get("label", ""),
            desc,
        )

    console.print(table)


@interests.command("add")
@click.argument("key")
@click.argument("label")
@click.argument("description", required=False)
def interests_add(key: str, label: str, description: str | None):
    """Add a new interest."""
    with get_client() as client:
        payload = {"key": key, "label": label}
        if description:
            payload["description"] = description

        response = client.post("/interests", json=payload)
        handle_error(response)

    console.print(f"[green]Created interest: {key}")


@interests.command("edit")
@click.argument("key")
@click.option("--label", "-l", help="New label")
@click.option("--desc", "-d", help="New description")
def interests_edit(key: str, label: str | None, desc: str | None):
    """Edit an interest."""
    if not label and not desc:
        console.print("[yellow]Nothing to update. Use --label or --desc.")
        return

    payload = {}
    if label:
        payload["label"] = label
    if desc:
        payload["description"] = desc

    with get_client() as client:
        response = client.put(f"/interests/{key}", json=payload)
        handle_error(response)

    console.print(f"[green]Updated interest: {key}")


@interests.command("delete")
@click.argument("key")
@click.confirmation_option(prompt="Are you sure you want to delete this interest?")
def interests_delete(key: str):
    """Delete an interest."""
    with get_client() as client:
        response = client.delete(f"/interests/{key}")
        handle_error(response)

    console.print(f"[green]Deleted interest: {key}")


@cli.command()
def sync():
    """Manually trigger a Feedbin sync."""
    config = load_config()
    # Use longer timeout for sync (paginating through Feedbin can take a while)
    with httpx.Client(base_url=config.server_url, timeout=300.0) as client:
        console.print("[dim]Syncing from Feedbin (this may take a moment)...[/dim]")
        response = client.post("/sync")
        handle_error(response)
        result = response.json()

    console.print(f"[green]Synced {result.get('synced', 0)} entries from Feedbin")


@cli.command()
@click.option("--hours", "-h", default=24, help="Requeue entries from last N hours")
def requeue(hours: int):
    """Mark entries for reprocessing.

    Clears processed status so they get picked up by the background classifier.
    """
    with get_client() as client:
        response = client.post("/entries/requeue", params={"since_hours": hours})
        handle_error(response)
        result = response.json()

    console.print(f"[green]Requeued {result.get('requeued', 0)} entries for reprocessing")
    console.print("[dim]Background classifier will process them (10 per minute).[/dim]")


@cli.command()
def stats():
    """Show database statistics."""
    with get_client() as client:
        response = client.get("/stats")
        handle_error(response)
        data = response.json()

    table = Table(title="Wiresum Statistics")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Total Entries", str(data.get("total_entries", 0)))
    table.add_row("Unprocessed", str(data.get("unprocessed", 0)))
    table.add_row("Signal", str(data.get("signal", 0)))

    console.print(table)


if __name__ == "__main__":
    cli()
