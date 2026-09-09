#!/usr/bin/env python3
"""1-Click GitHub Updater for Laptops (Zero Git / Zero IDE Required).

Downloads the latest code from https://github.com/charom11/Atlas-Bot (strategy/candidate-v9-3-1 branch)
and synchronizes the local workspace while strictly protecting:
- .env (your private API keys)
- data/ (your telemetry and shadow data)
- log files
"""
import os
import sys
import shutil
import zipfile
import urllib.request

# Ensure UTF-8 output on Windows terminals without crashing on cp1252
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


REPO_ZIP_URL = "https://github.com/charom11/Atlas-Bot/archive/refs/heads/strategy/candidate-v9-3-1.zip"
FALLBACK_ZIP_URL = "https://github.com/charom11/Atlas-Bot/archive/refs/heads/main.zip"

PROTECTED_ITEMS = {
    ".env",
    "data",
    ".git",
    ".venv",
    "bot_output.log",
    "v9_3_1_shadow_daemon.log",
    "task-67.log",
}

def update():
    print("=" * 75)
    print(" 🔄 ATLAS-BOT / WEATHER-ENSEMBLE GITHUB UPDATER (NO GIT REQUIRED)")
    print("=" * 75)
    print(f" Target Repository: charom11/Atlas-Bot (strategy/candidate-v9-3-1)")
    print(f" Working Directory: {os.path.abspath('.')}")
    print("=" * 75 + "\n")

    zip_file = "_github_update_temp.zip"
    extract_folder = "_github_update_temp_dir"

    # Step 1: Download zip from GitHub
    print("1/3 Downloading latest code from GitHub...", flush=True)
    try:
        req = urllib.request.Request(
            REPO_ZIP_URL,
            headers={"User-Agent": "AtlasBot-LaptopUpdater/1.0"}
        )
        with urllib.request.urlopen(req, timeout=30) as resp, open(zip_file, "wb") as out_f:
            shutil.copyfileobj(resp, out_f)
    except Exception as e:
        print(f"Branch download failed ({e}), trying main branch...", flush=True)
        try:
            req = urllib.request.Request(
                FALLBACK_ZIP_URL,
                headers={"User-Agent": "AtlasBot-LaptopUpdater/1.0"}
            )
            with urllib.request.urlopen(req, timeout=30) as resp, open(zip_file, "wb") as out_f:
                shutil.copyfileobj(resp, out_f)
        except Exception as e2:
            print(f"\n❌ [ERROR] Could not download update: {e2}")
            print("Please check your laptop's internet connection.")
            return False

    print("2/3 Unpacking files...", flush=True)
    try:
        if os.path.exists(extract_folder):
            shutil.rmtree(extract_folder)
        with zipfile.ZipFile(zip_file, "r") as zf:
            zf.extractall(extract_folder)
    except Exception as e:
        print(f"❌ [ERROR] Failed to unpack zip: {e}")
        if os.path.exists(zip_file):
            os.remove(zip_file)
        return False

    # Step 2: Copy updated files over current directory
    print("3/3 Updating files (preserving .env and data/)...", flush=True)
    subdirs = [os.path.join(extract_folder, d) for d in os.listdir(extract_folder) if os.path.isdir(os.path.join(extract_folder, d))]
    source_root = subdirs[0] if subdirs else extract_folder

    updated_count = 0
    for item in os.listdir(source_root):
        if item in PROTECTED_ITEMS:
            continue
        src = os.path.join(source_root, item)
        dst = os.path.join(".", item)
        try:
            if os.path.isdir(src):
                if os.path.exists(dst):
                    shutil.rmtree(dst)
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)
            updated_count += 1
        except Exception as copy_err:
            print(f"  [WARN] Skipping {item}: {copy_err}")

    # Cleanup temp files
    try:
        if os.path.exists(zip_file):
            os.remove(zip_file)
        if os.path.exists(extract_folder):
            shutil.rmtree(extract_folder)
    except Exception:
        pass

    print("\n" + "=" * 75)
    print(f" ✅ UPDATE SUCCESSFUL! Synchronized {updated_count} files/folders from GitHub.")
    print(" • Private .env configuration preserved: YES ✅")
    print(" • Shadow telemetry (data/) preserved:    YES ✅")
    print("=" * 75 + "\n")
    return True


if __name__ == "__main__":
    success = update()
    if not success:
        sys.exit(1)
