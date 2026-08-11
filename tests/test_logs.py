"""Unit tests for nikitai.tools.logs."""

from __future__ import annotations

import os

import pytest

from nikitai.tools import logs


@pytest.fixture
def notes_dir(tmp_path, monkeypatch):
    """A temp notes dir wired into NIKITAI_HOME_INFRA_NOTES_DIR."""
    d = tmp_path / "notes"
    d.mkdir()
    monkeypatch.setenv("NIKITAI_HOME_INFRA_NOTES_DIR", str(d))
    return d


# ── environment handling ──────────────────────────────────────────────────────


def test_list_log_files_raises_when_env_unset(monkeypatch):
    monkeypatch.delenv("NIKITAI_HOME_INFRA_NOTES_DIR", raising=False)

    with pytest.raises(RuntimeError, match="NIKITAI_HOME_INFRA_NOTES_DIR is not set"):
        logs.list_log_files()


def test_read_log_file_raises_when_env_unset(monkeypatch):
    monkeypatch.delenv("NIKITAI_HOME_INFRA_NOTES_DIR", raising=False)

    with pytest.raises(RuntimeError, match="NIKITAI_HOME_INFRA_NOTES_DIR is not set"):
        logs.read_log_file("router.txt")


# ── list_log_files ────────────────────────────────────────────────────────────


def test_list_log_files_returns_only_txt_non_recursive(notes_dir):
    (notes_dir / "router.txt").write_text("a")
    (notes_dir / "pi.txt").write_text("b")
    (notes_dir / "notes.md").write_text("c")  # wrong extension
    sub = notes_dir / "sub"
    sub.mkdir()
    (sub / "nested.txt").write_text("d")  # nested, must be excluded

    assert logs.list_log_files() == ["pi.txt", "router.txt"]


# ── read_log_file ─────────────────────────────────────────────────────────────


def test_read_log_file_returns_content(notes_dir):
    (notes_dir / "router.txt").write_text("line1\nline2\nline3")

    assert logs.read_log_file("router.txt") == "line1\nline2\nline3"


def test_read_log_file_tails_and_notes_truncation(notes_dir):
    (notes_dir / "big.txt").write_text("\n".join(str(i) for i in range(10)))

    result = logs.read_log_file("big.txt", max_lines=3)

    assert result.splitlines()[0] == "[showing last 3 of 10 lines of big.txt]"
    assert result.splitlines()[1:] == ["7", "8", "9"]


def test_read_log_file_missing_file_raises(notes_dir):
    with pytest.raises(FileNotFoundError, match="No such note file"):
        logs.read_log_file("nope.txt")


@pytest.mark.parametrize("bad", ["../outside.txt", "../../etc/hosts.txt"])
def test_read_log_file_rejects_parent_traversal(notes_dir, tmp_path, bad):
    # Create a real file just outside the notes dir to prove traversal is blocked.
    (tmp_path / "outside.txt").write_text("secret")

    with pytest.raises(ValueError, match="outside the notes directory"):
        logs.read_log_file(bad)


def test_read_log_file_rejects_absolute_path(notes_dir):
    with pytest.raises(ValueError, match="outside the notes directory"):
        logs.read_log_file("/etc/hosts.txt")


def test_read_log_file_rejects_non_txt_extension(notes_dir):
    (notes_dir / "secrets.env").write_text("x")

    with pytest.raises(ValueError, match="Only .txt files are allowed"):
        logs.read_log_file("secrets.env")


def test_read_log_file_rejects_symlink_escaping_dir(notes_dir, tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("secret")
    link = notes_dir / "link.txt"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported on this platform")

    with pytest.raises(ValueError, match="outside the notes directory"):
        logs.read_log_file("link.txt")


# ── append_to_log ─────────────────────────────────────────────────────────────


def test_append_to_log_appends_without_truncating(notes_dir):
    f = notes_dir / "router.txt"
    f.write_text("existing line\n")

    result = logs.append_to_log("router.txt", "opened port 443")

    assert f.read_text() == "existing line\nopened port 443\n"
    assert result == {"filename": "router.txt", "lines_appended": 1}


def test_append_to_log_inserts_newline_when_file_lacks_trailing_newline(notes_dir):
    f = notes_dir / "router.txt"
    f.write_text("no trailing newline")

    logs.append_to_log("router.txt", "new entry")

    assert f.read_text() == "no trailing newline\nnew entry\n"


def test_append_to_log_rejects_nonexistent_file(notes_dir):
    with pytest.raises(FileNotFoundError, match="does not already exist"):
        logs.append_to_log("brand_new.txt", "content")


def test_append_to_log_rejects_non_txt_extension(notes_dir):
    (notes_dir / "config.env").write_text("x")

    with pytest.raises(ValueError, match="Only .txt files are allowed"):
        logs.append_to_log("config.env", "content")


@pytest.mark.parametrize("bad", ["../outside.txt", "/tmp/evil.txt"])
def test_append_to_log_rejects_traversal_and_absolute(notes_dir, tmp_path, bad):
    (tmp_path / "outside.txt").write_text("existing")

    with pytest.raises(ValueError, match="outside the notes directory"):
        logs.append_to_log(bad, "content")


def test_append_to_log_rejects_symlink_escaping_dir(notes_dir, tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("existing\n")
    link = notes_dir / "link.txt"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported on this platform")

    with pytest.raises(ValueError, match="outside the notes directory"):
        logs.append_to_log("link.txt", "content")

    # And the outside file must remain untouched.
    assert outside.read_text() == "existing\n"
    assert "NIKITAI_HOME_INFRA_NOTES_DIR" in os.environ
