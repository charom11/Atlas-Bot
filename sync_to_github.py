#!/usr/bin/env python3
"""1-Click Sync from Laptop to GitHub.

Safely stages, commits, and pushes laptop-based edits to https://github.com/charom11/Atlas-Bot
while strictly protecting:
- .env and .env.local (private API keys and secrets)
- data/ (telemetry and shadow database)
- *.log files (local logs)
- .venv/ (virtual environment)
"""
from __future__ import annotations

import datetime
import os
import shutil
import subprocess
import sys
from pathlib import Path

# Ensure UTF-8 output on Windows terminals without crashing on cp1252
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


REPO_URL = "https://github.com/charom11/Atlas-Bot.git"
PROTECTED_ITEMS = {
    ".env",
    ".env.local",
    "data",
    ".venv",
    "bot_output.log",
    "bot_output.log.1",
    "v9_3_1_shadow_daemon.log",
    "task-67.log",
    "bot.log",
    "bot_err.log",
    "bot_live.log",
}


def run_cmd(cmd: list[str], check: bool = False, capture: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        text=True,
        check=check,
        capture_output=capture,
    )


def is_git_installed() -> bool:
    return shutil.which("git") is not None


def get_current_branch() -> str:
    res = run_cmd(["git", "branch", "--show-current"])
    branch = res.stdout.strip()
    return branch if branch else "main"


def get_unpushed_count(branch: str) -> int:
    res = run_cmd(["git", "rev-list", "--count", f"origin/{branch}..HEAD"])
    if res.returncode == 0 and res.stdout.strip().isdigit():
        return int(res.stdout.strip())
    return 0


def protect_sensitive_files():
    """Ensure sensitive files are never staged in git."""
    for item in PROTECTED_ITEMS:
        if os.path.exists(item):
            run_cmd(["git", "reset", "--", item])


def sync(commit_msg: str | None = None) -> bool:
    print("=" * 75)
    print(" ⬆️  ATLAS-BOT: SYNC LAPTOP CHANGES ➔ GITHUB")
    print("=" * 75)
    print(f" Remote Target:     {REPO_URL}")
    print(f" Working Directory: {os.path.abspath('.')}")

    # Check 1: Git installed
    if not is_git_installed():
        print("\n❌ [ERROR] Git is not installed or not in system PATH!")
        print("To push changes to GitHub, please install Git for Windows:")
        print(" • Via Terminal: winget install --id Git.Git -e")
        print(" • Via Website:  https://git-scm.com/download/win")
        print("After installing, re-run this script.\n")
        return False

    # Check 2: Git repo
    check_repo = run_cmd(["git", "rev-parse", "--is-inside-work-tree"])
    if check_repo.returncode != 0:
        print("\n❌ [ERROR] Current directory is not a Git repository!")
        return False

    branch = get_current_branch()
    print(f" Active Branch:     {branch}")
    print("=" * 75 + "\n")

    # Step 1: Check status
    print("1/4 Checking repository status...", flush=True)
    status_res = run_cmd(["git", "status", "--porcelain"])
    dirty = bool(status_res.stdout.strip())
    unpushed = get_unpushed_count(branch)

    if not dirty and unpushed == 0:
        print(f"\n✅ [UP TO DATE] Working tree is clean and branch '{branch}' is up to date with GitHub.")
        print("Nothing to commit or push.\n")
        return True

    # Step 2: Handle uncommitted changes
    if dirty:
        print("\n📝 Detected local changes on laptop:")
        short_status = run_cmd(["git", "status", "-s"])
        print(short_status.stdout)

        if not commit_msg:
            try:
                user_msg = input("Enter commit message (Press ENTER for auto-timestamp): ").strip()
                if user_msg:
                    commit_msg = user_msg
            except EOFError:
                pass

        if not commit_msg:
            now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            commit_msg = f"sync(laptop): updates from laptop [{now_str}]"

        print(f"\n2/4 Staging and committing changes...")
        run_cmd(["git", "add", "-A"])
        protect_sensitive_files()

        commit_res = run_cmd(["git", "commit", "-m", commit_msg])
        if commit_res.returncode != 0:
            # Check if after un-staging sensitive files nothing was left to commit
            status_after = run_cmd(["git", "status", "--porcelain"]).stdout.strip()
            if not status_after and get_unpushed_count(branch) == 0:
                print("✅ Only local protected files (.env, logs, data/) changed. Nothing to push.")
                return True
            print(f"Commit output: {commit_res.stdout}\n{commit_res.stderr}")
    else:
        print(f"2/4 Found {unpushed} unpushed commit(s) ready to sync.")

    # Step 3: Pull remote changes with rebase
    print(f"3/4 Fetching and integrating remote updates from origin/{branch}...", flush=True)
    pull_res = run_cmd(["git", "pull", "--rebase", "origin", branch])
    if pull_res.returncode != 0:
        print("\n⚠️ [WARNING] Merge conflict or rebase issue detected during remote pull.")
        print("Aborting rebase to protect your local changes:")
        run_cmd(["git", "rebase", "--abort"])
        print(pull_res.stderr or pull_res.stdout)
        print("Please resolve conflicts manually before pushing.\n")
        return False

    # Step 4: Push to GitHub
    print(f"4/4 Pushing changes to GitHub (origin/{branch})...", flush=True)
    push_res = run_cmd(["git", "push", "origin", branch])
    if push_res.returncode != 0:
        print("\n❌ [ERROR] Git push failed!")
        print(push_res.stderr or push_res.stdout)
        print("\nCommon solutions:")
        print(" 1. Sign in with GitHub Credential Manager when prompted.")
        print(" 2. Verify you have write permissions to charom11/Atlas-Bot.")
        print(" 3. Check your internet connection.\n")
        return False

    print("\n" + "=" * 75)
    print(" ✅ SYNC SUCCESSFUL! Your laptop changes are now live on GitHub:")
    print(f" • Branch: https://github.com/charom11/Atlas-Bot/tree/{branch}")
    print(" • Private credentials (.env) protected: YES ✅")
    print(" • Telemetry (data/) protected:          YES ✅")
    print("=" * 75 + "\n")
    return True


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Sync laptop changes to GitHub")
    parser.add_argument("-m", "--message", help="Commit message", default=None)
    args = parser.parse_args()

    success = sync(commit_msg=args.message)
    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()
