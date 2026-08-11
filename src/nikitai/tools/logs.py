"""Local notes/log access for the Platform Nerd sub-agent.

These tools give NikitAI read/append access to the user's own maintained notes on
their home network and hosting setup, stored as ``.txt`` files in the directory
named by the ``NIKITAI_HOME_INFRA_NOTES_DIR`` environment variable.

Safety: every path is resolved and confirmed to live inside the notes directory
before any I/O, so ``../`` traversal, absolute paths, and symlinks that escape the
directory are all rejected. Append never creates, truncates, overwrites, or deletes
— it only adds to existing ``.txt`` files.
"""

from __future__ import annotations

import os
from pathlib import Path

_NOTES_DIR_ENV = "NIKITAI_HOME_INFRA_NOTES_DIR"


def _notes_dir() -> Path:
    """Return the resolved notes directory, or raise if unset/missing."""
    raw = os.environ.get(_NOTES_DIR_ENV)
    if not raw:
        raise RuntimeError(
            f"{_NOTES_DIR_ENV} is not set. Point it at the local folder holding your "
            "home network / hosting notes."
        )
    base = Path(raw).expanduser().resolve()
    if not base.is_dir():
        raise RuntimeError(f"{_NOTES_DIR_ENV} does not point to a directory: {base}")
    return base


def _resolve_within(base: Path, filename: str) -> Path:
    """Resolve ``filename`` against ``base`` and confirm it stays inside ``base``.

    Rejects ``../`` traversal, absolute paths, and symlinks resolving outside the
    notes directory. Also requires a ``.txt`` extension.
    """
    if not filename:
        raise ValueError("filename must be provided.")
    if not filename.endswith(".txt"):
        raise ValueError(f"Only .txt files are allowed: {filename!r}")

    candidate = (base / filename).resolve()
    if candidate != base and base not in candidate.parents:
        raise ValueError(f"Refusing to access path outside the notes directory: {filename!r}")
    return candidate


def list_log_files() -> list[str]:
    """List ``.txt`` filenames directly inside the notes directory (non-recursive)."""
    base = _notes_dir()
    return sorted(
        entry.name for entry in base.iterdir() if entry.is_file() and entry.suffix == ".txt"
    )


def read_log_file(filename: str, max_lines: int = 200) -> str:
    """Return up to the last ``max_lines`` lines of a note file (tail behavior).

    If the file has more than ``max_lines`` lines, only the tail is returned and a
    truncation note is prepended so the caller knows earlier content exists.
    """
    base = _notes_dir()
    path = _resolve_within(base, filename)
    if not path.is_file():
        raise FileNotFoundError(f"No such note file: {filename!r}")

    lines = path.read_text(encoding="utf-8").splitlines()
    if len(lines) > max_lines:
        tail = lines[-max_lines:]
        note = f"[showing last {max_lines} of {len(lines)} lines of {filename}]"
        return "\n".join([note, *tail])
    return "\n".join(lines)


def append_to_log(filename: str, content: str) -> dict:
    """Append ``content`` as a new block to an existing ``.txt`` note file.

    Pure append: never creates a new file, never truncates/overwrites existing
    content. Rejects paths outside the notes directory and non-``.txt`` extensions.
    Returns a small confirmation dict.
    """
    base = _notes_dir()
    path = _resolve_within(base, filename)
    if not path.is_file():
        raise FileNotFoundError(
            f"Refusing to append: {filename!r} does not already exist (new files are not created)."
        )

    block = content if content.endswith("\n") else content + "\n"
    # Ensure the appended block starts on its own line if the file doesn't end in one.
    existing = path.read_text(encoding="utf-8")
    prefix = "" if existing == "" or existing.endswith("\n") else "\n"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(prefix + block)

    lines_appended = block.count("\n")
    return {"filename": filename, "lines_appended": lines_appended}
