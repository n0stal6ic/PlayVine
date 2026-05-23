"""
Rich-based console styling for PlayVine.

Replaces the coloredlogs timestamped-line look with a tighter, modern
terminal aesthetic:

  * Each log line is prefixed with a glyph indicating severity:
      ·  debug      ›  info       ⚠  warning    ✕  error / critical
  * Colors come from Rich, with vine-green as the brand accent.
  * No per-line timestamp on stdout. The file logger keeps the full
    timestamped format so grep-ability isn't lost.

The file logger is untouched - only the console (stdout) channel changes.
"""
from __future__ import annotations

import logging
import sys
from typing import Mapping

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text


# Force stdout/stderr to UTF-8 on Windows so the unicode glyphs below
# (›, ⚠, ✕, ·) render. Legacy cmd.exe uses cp1252 by default which
# can't encode them and would crash. Windows Terminal handles UTF-8
# natively. `errors="replace"` is a safety net so any other char that
# still can't encode is replaced with '?' instead of crashing.
if sys.platform == "win32":
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, Exception):
            pass

# Shared console singleton. Use this from anywhere that wants direct,
# styled stdout output (panels, tables, rules, etc.):
#
#     from playvine.utils.console import console
#     console.rule("Section")
#
# legacy_windows=False forces Rich to use its modern ANSI renderer
# instead of the cp1252-bound Win32 console API path.
console = Console(highlight=False, soft_wrap=False, legacy_windows=False)


# (glyph, rich-style) per log level. Glyph is rendered with the style at
# the start of every console log line.
_LEVEL_STYLE: dict[int, tuple[str, str]] = {
    logging.DEBUG:    ("·", "dim"),
    logging.INFO:     ("›", "green"),
    logging.WARNING:  ("⚠", "yellow"),
    logging.ERROR:    ("✕", "red bold"),
    logging.CRITICAL: ("✕", "white on red"),
}


class PlayVineLogHandler(logging.Handler):
    """
    Console log handler.

    Output shape:

        ›  Getting tracks for Some Movie (2024)
        ⚠  No CDM configured
        ✕  Could not parse license

    No timestamp, no logger name, no level word - the glyph carries all
    of that. Detail still lives in the file log if you need it.
    """

    def emit(self, record: logging.LogRecord) -> None:
        glyph, style = _LEVEL_STYLE.get(record.levelno, ("·", "dim"))
        # Run the configured formatter, then render via Rich.
        try:
            msg = self.format(record)
        except Exception:
            self.handleError(record)
            return
        line = Text()
        line.append(f"{glyph}  ", style=style)
        line.append(msg)
        console.print(line)


def install_handler(level: int = logging.INFO) -> PlayVineLogHandler:
    """
    Install PlayVineLogHandler as the stdout handler on the root logger.

    Removes any existing StreamHandler (such as one previously installed
    by coloredlogs) so the new style is the only console output. The
    FileHandler - if one was set up by ``logging.basicConfig`` - is left
    alone so disk logs keep their full timestamped format.
    """
    root = logging.getLogger()
    for h in list(root.handlers):
        if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler):
            root.removeHandler(h)
    handler = PlayVineLogHandler(level=level)
    # Bare format - the handler adds the glyph itself, and we don't
    # want timestamps/logger names duplicated in the message body.
    handler.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(handler)
    # Ensure the root logger lets at least this level through. If something
    # else (e.g. basicConfig with DEBUG for file logging) already opened
    # it wider, respect that.
    if root.level == logging.NOTSET or root.level > level:
        root.setLevel(level)
    return handler


def show_banner(paths: Mapping[str, object], version: str = "") -> None:
    """
    Print the PlayVine startup banner.

    A bordered panel with the project title and a two-column table of
    relevant directory paths. Replaces the old wall of seven separate
    ``[Config]    :`` log lines with one compact visual block.
    """
    table = Table.grid(padding=(0, 2))
    table.add_column(style="dim cyan", justify="right")
    table.add_column(style="bright_white")
    for label, value in paths.items():
        table.add_row(label, str(value))

    title = Text()
    title.append("PlayVine", style="bold green")
    if version:
        title.append(f" v{version}", style="dim")
    title.append("  ·  ", style="dim")
    title.append("DRM Content Archiver", style="bright_white")

    panel = Panel(
        table,
        title=title,
        title_align="left",
        border_style="green",
        padding=(0, 2),
    )
    console.print(panel)
