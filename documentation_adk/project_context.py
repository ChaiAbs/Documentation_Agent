from __future__ import annotations

import os
from pathlib import Path


MAX_FILE_BYTES = 24_000
MAX_TEXT_FILES = 18
MAX_TOTAL_CHARS = 80_000

IGNORED_DIRS = {
    ".git",
    ".idea",
    ".vscode",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
    ".next",
    ".venv",
    "venv",
    "coverage",
}

PRIORITY_FILES = {
    "readme.md",
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "setup.py",
    "pom.xml",
    "build.gradle",
    "go.mod",
    "cargo.toml",
    "dockerfile",
}

TEXT_SUFFIXES = {
    ".md",
    ".txt",
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".java",
    ".go",
    ".rb",
    ".php",
    ".cs",
    ".rs",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".env",
    ".sql",
    ".html",
    ".css",
    ".scss",
    ".sh",
}


def _is_probably_text(path: Path) -> bool:
    if path.suffix.lower() in TEXT_SUFFIXES:
        return True
    return path.name.lower() in PRIORITY_FILES


def _safe_read_text(path: Path) -> str | None:
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return None
        raw = path.read_bytes()
        if b"\x00" in raw:
            return None
        return raw.decode("utf-8", errors="ignore").strip()
    except OSError:
        return None


def build_project_context(project_dir: str | Path) -> str:
    root = Path(project_dir)
    all_files: list[Path] = []

    for current_root, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(name for name in dirnames if name not in IGNORED_DIRS)
        for filename in sorted(filenames):
            path = Path(current_root) / filename
            if path.is_file():
                all_files.append(path)

    relative_files = [path.relative_to(root).as_posix() for path in all_files]
    tree = "\n".join(f"- {name}" for name in relative_files[:250])

    def sort_key(path: Path) -> tuple[int, int, str]:
        rel_name = path.relative_to(root).as_posix()
        is_priority = 0 if path.name.lower() in PRIORITY_FILES else 1
        shallow_score = len(path.parts)
        return (is_priority, shallow_score, rel_name)

    selected_paths = [
        path for path in sorted(all_files, key=sort_key) if _is_probably_text(path)
    ][:MAX_TEXT_FILES]

    excerpts: list[str] = []
    total_chars = 0
    for path in selected_paths:
        text = _safe_read_text(path)
        if not text:
            continue
        rel_path = path.relative_to(root).as_posix()
        snippet = text[:4000]
        chunk = f"## File: {rel_path}\n{snippet}"
        next_size = total_chars + len(chunk)
        if next_size > MAX_TOTAL_CHARS:
            break
        excerpts.append(chunk)
        total_chars = next_size

    return (
        "Project file tree:\n"
        f"{tree or '- No readable files found'}\n\n"
        "Representative file excerpts:\n"
        f"{chr(10).join(excerpts) or 'No readable source excerpts were found.'}"
    )
