"""
build_release.py - Automated Build & GitHub Release Packaging for GameVault
Usage:
    python build_release.py [version] [changelog]
Example:
    python build_release.py 1.3.3 "Fix settings crash & improve launcher"
"""

import os
import sys
import json
import zipfile
import hashlib
import subprocess
import shutil
import re
from datetime import datetime
from pathlib import Path

APP_NAME = "GameVault"
REPO_OWNER = "zepiam"
REPO_NAME = "GameVault"
DIST_EXE = os.path.join("dist", f"{APP_NAME}.exe")
ROOT_EXE = f"{APP_NAME}.exe"
RELEASE_DIR = "release"
PATCH_ZIP = os.path.join(RELEASE_DIR, "patch.zip")
VERSION_FILE = os.path.join(RELEASE_DIR, "version.json")


def stop_running_process():
    print("🛑 กำลังตรวจสอบและปิดโปรเซส GameVault.exe ที่ทำงานอยู่...")
    try:
        subprocess.run(
            ["powershell", "-Command", "Stop-Process -Name GameVault -Force -ErrorAction SilentlyContinue"],
            check=False
        )
    except Exception as e:
        print(f"⚠️ {e}")


def calculate_sha256(filepath: str) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def update_current_version_in_code(new_ver: str):
    """อัปเดต CURRENT_VERSION ใน updater.py ให้ตรงกับเวอร์ชันใหม่"""
    updater_file = "updater.py"
    if os.path.exists(updater_file):
        with open(updater_file, "r", encoding="utf-8") as f:
            content = f.read()

        updated = re.sub(r'CURRENT_VERSION\s*=\s*"[^"]+"', f'CURRENT_VERSION = "{new_ver}"', content)
        with open(updater_file, "w", encoding="utf-8") as f:
            f.write(updated)
        print(f"✅ อัปเดต CURRENT_VERSION ใน updater.py เป็น {new_ver} เรียบร้อย")


def check_syntax():
    print("🔍 ตรวจสอบความถูกต้องของ Syntax โค้ด...")
    files = ["app.py", "db.py", "scanner.py", "cover_fetcher.py", "steam_sync.py", "updater.py"]
    for f in files:
        if os.path.exists(f):
            res = subprocess.run([sys.executable, "-m", "py_compile", f], capture_output=True, text=True)
            if res.returncode != 0:
                print(f"❌ Syntax Error in {f}:\n{res.stderr}")
                sys.exit(1)
    print("✅ Syntax ถูกต้องทุกไฟล์")


def build_executable():
    """คอมไพล์โปรแกรม GameVault.exe ผ่าน PyInstaller (GameVault.spec)"""
    print("🔨 กำลังคอมไพล์โปรแกรมด้วย PyInstaller (GameVault.spec --clean)...")
    spec_file = "GameVault.spec"
    if not os.path.exists(spec_file):
        print(f"❌ ไม่พบไฟล์ {spec_file}")
        sys.exit(1)

    cmd = ["pyinstaller", spec_file, "--clean"]
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print("❌ การคอมไพล์ล้มเหลว!")
        sys.exit(1)

    if os.path.exists(DIST_EXE):
        shutil.copy2(DIST_EXE, ROOT_EXE)
        print(f"✅ คัดลอก {DIST_EXE} ไปยัง {ROOT_EXE} เรียบร้อย")
    print("✅ คอมไพล์โปรแกรม GameVault.exe สำเร็จ")


def create_patch_zip():
    """บีบอัด GameVault.exe และ assets/ เป็น patch.zip"""
    os.makedirs(RELEASE_DIR, exist_ok=True)
    if os.path.exists(PATCH_ZIP):
        os.remove(PATCH_ZIP)

    print("📦 กำลังสร้าง patch.zip สำหรับปล่อยอัปเดต...")
    with zipfile.ZipFile(PATCH_ZIP, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(ROOT_EXE, arcname=f"{APP_NAME}.exe")
        assets_dir = "assets"
        if os.path.exists(assets_dir):
            for root, _, files in os.walk(assets_dir):
                for file in files:
                    full_p = os.path.join(root, file)
                    rel_p = os.path.relpath(full_p, ".")
                    zf.write(full_p, arcname=rel_p)

    mb = os.path.getsize(PATCH_ZIP) / (1024 * 1024)
    print(f"✅ สร้าง {PATCH_ZIP} เรียบร้อย (ขนาด {mb:.2f} MB)")


def generate_manifest(new_version: str, changelog_text: str):
    """คำนวณ SHA-256 และสร้าง version.json"""
    print("📝 กำลังสร้าง version.json manifest...")
    sha256 = calculate_sha256(PATCH_ZIP)
    file_size = os.path.getsize(PATCH_ZIP)
    download_url = f"https://github.com/{REPO_OWNER}/{REPO_NAME}/releases/download/v{new_version}/patch.zip"

    manifest = {
        "version": new_version,
        "min_required_version": "1.0.0",
        "release_date": datetime.now().strftime("%Y-%m-%d"),
        "changelog": changelog_text,
        "download": {
            "url": download_url,
            "size": file_size,
            "sha256": sha256
        }
    }

    with open(VERSION_FILE, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    print(f"✅ สร้าง manifest {VERSION_FILE} เรียบร้อย (SHA-256: {sha256[:12]}...)")


def git_commit_and_push(new_version: str, changelog_text: str):
    print("📤 กำลัง Git Add, Commit และ Push ขึ้น origin/main...")
    subprocess.run(["git", "add", "app.py", "db.py", "scanner.py", "cover_fetcher.py",
                    "steam_sync.py", "updater.py", "GameVault.spec", "build_release.py",
                    "release_gui.py", "release.bat", ".gitignore"], check=False)
    
    msg = f"Bump v{new_version}: {changelog_text.splitlines()[0] if changelog_text else 'Release update'}"
    subprocess.run(["git", "commit", "-m", msg], check=False)
    res = subprocess.run(["git", "push", "origin", "main"], capture_output=True, text=True)
    if res.returncode == 0:
        print("✅ Git Push ขึ้น GitHub สำเร็จเรียบร้อย")
    else:
        print(f"⚠️ Git Push: {res.stderr or res.stdout}")


def push_github_release(new_version: str, changelog_text: str):
    """สร้าง GitHub Release ผ่าน gh CLI"""
    tag = f"v{new_version}"
    print(f"🚀 กำลังสร้าง GitHub Release: {tag}...")

    cmd = [
        "gh", "release", "create", tag,
        PATCH_ZIP,
        VERSION_FILE,
        "--title", f"GameVault {tag}",
        "--notes", changelog_text
    ]
    result = subprocess.run(cmd)
    if result.returncode == 0:
        print(f"🎉 สำเร็จ! ปล่อย Release {tag} ขึ้น GitHub เรียบร้อยแล้ว")
        print(f"👉 ตรวจสอบได้ที่: https://github.com/{REPO_OWNER}/{REPO_NAME}/releases/tag/{tag}")
    else:
        print(f"⚠️ การอัปโหลด Release ผ่าน gh CLI ไม่สำเร็จ กรุณาตรวจสอบการตั้งค่า gh")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        new_ver = input("ระบุเวอร์ชันใหม่ที่ต้องการปล่อย (เช่น 1.3.3): ").strip().lstrip("v")
    else:
        new_ver = sys.argv[1].strip().lstrip("v")

    if not new_ver:
        print("❌ ต้องระบุเลขเวอร์ชัน เช่น 1.3.3")
        sys.exit(1)

    if len(sys.argv) >= 3:
        changelog_input = sys.argv[2].strip()
    else:
        changelog_input = input("กรอก Changelog (หรือกด Enter เพื่อใช้ค่าเริ่มต้น): ").strip()

    if not changelog_input:
        changelog_input = "- ปรับปรุงประสิทธิภาพและการทำงานทั่วไป\n- อัปเดตระบบจัดการและแสดงผลคลังเกม"

    stop_running_process()
    check_syntax()
    update_current_version_in_code(new_ver)
    build_executable()
    create_patch_zip()
    generate_manifest(new_ver, changelog_input)
    git_commit_and_push(new_ver, changelog_input)
    push_github_release(new_ver, changelog_input)
    print(f"\n🎉 สำเร็จทุกขั้นตอน! GameVault v{new_ver} พร้อมใช้งานบน GitHub Releases แล้ว")
