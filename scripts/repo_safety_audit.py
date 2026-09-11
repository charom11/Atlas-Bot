#!/usr/bin/env python3
"""Static repository safety checks for Atlas-Bot.

This audit is deliberately non-invasive: it never calls an exchange and never
changes trading configuration. It prevents common repository-level failures:
tracked runtime logs, committed dotenv/secrets, obvious credential literals,
and workflows without an explicit permissions block.
"""
from __future__ import annotations

from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
IGNORED_DIRS = {".git", "node_modules", "__pycache__", ".pytest_cache"}
SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"(?i)\b(?:BINANCE_API_SECRET|TELEGRAM_BOT_TOKEN)\s*=\s*['\"]?[A-Za-z0-9:_\-]{24,}"),
)
FORBIDDEN_TRACKED_NAMES = {".env", ".env.local", ".env.production"}
RUNTIME_LOG_SUFFIXES = (".log", ".log.1", ".log.2", ".log.3")


def tracked_files() -> list[Path]:
    """Return repository files known to git; fall back to a filesystem walk."""
    import subprocess

    try:
        out = subprocess.check_output(
            ["git", "ls-files", "-z"], cwd=ROOT, text=False
        )
        return [ROOT / p for p in out.decode().split("\0") if p]
    except Exception:
        files: list[Path] = []
        for p in ROOT.rglob("*"):
            if not p.is_file() or any(part in IGNORED_DIRS for part in p.parts):
                continue
            files.append(p)
        return files


def main() -> int:
    errors: list[str] = []
    files = tracked_files()

    for path in files:
        rel = path.relative_to(ROOT).as_posix()
        name = path.name
        if name in FORBIDDEN_TRACKED_NAMES:
            errors.append(f"tracked dotenv file: {rel}")
        if any(name == suffix or name.endswith(suffix) for suffix in RUNTIME_LOG_SUFFIXES):
            errors.append(f"tracked runtime log: {rel}")

        if path.suffix.lower() not in {".py", ".yml", ".yaml", ".json", ".js", ".ts", ".tsx", ".md", ".txt"}:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError as exc:
            errors.append(f"cannot read {rel}: {exc}")
            continue
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                errors.append(f"possible credential literal in {rel} ({pattern.pattern})")

    for workflow in (ROOT / ".github" / "workflows").glob("*.y*ml"):
        try:
            text = workflow.read_text(encoding="utf-8")
        except OSError as exc:
            errors.append(f"cannot read workflow {workflow}: {exc}")
            continue
        if not re.search(r"(?m)^permissions:\s*$", text):
            errors.append(f"workflow missing explicit permissions block: {workflow.relative_to(ROOT)}")

    if errors:
        print("Repository safety audit FAILED:")
        for error in errors:
            print(f" - {error}")
        return 1

    print(f"Repository safety audit passed ({len(files)} tracked files checked).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
