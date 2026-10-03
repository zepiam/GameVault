"""
build_release.py - Automated Build & GitHub Release Packaging for GameVault
Usage:
    python build_release.py 1.0.0
"""

import os
import sys
import json
import zipfile
import hashlib
import subprocess
import shutil
from datetime import datetime

APP_NAME = "GameVault"
REPO_OWNER = "zepiam"
REPO_NAME = "GameVault"
DIST_EXE = os.path.join("dist", f"{APP_NAME}.exe")
RELEASE_DIR = "release"
PATCH_ZIP = os.path.join(RELEASE_DIR, "patch.zip")
VERSION_FILE = os.path.join(RELEASE_DIR, "version.json")


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

        import re
        updated = re.sub(r'CURRENT_VERSION\s*=\s*"[^"]+"', f'CURRENT_VERSION = "{new_ver}"', content)
        with open(updater_file, "w", encoding="utf-8") as f:
            f.write(updated)
        print(f"✅ อัปเดต CURRENT_VERSION ใน updater.py เป็น {new_ver} เรียบร้อย")


def build_executable():
    """คอมไพล์โปรแกรม GameVault.exe ผ่าน PyInstaller"""
    print("🔨 กำลังคอมไพล์โปรแกรมด้วย PyInstaller (อาจใช้เวลาประมาณ 20-30 วินาที)...")
    cmd = [
        "pyinstaller",
        "--noconsole",
        "--onefile",
        "--clean",
        "--name", APP_NAME,
        "--icon", "icon.ico",
        "--add-data", "assets;assets",
        "--add-data", "icon.ico;.",
        "--add-data", "icon.png;.",
        "--exclude-module", "PySide6",
        "app.py"
    ]
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print("❌ การคอมไพล์ล้มเหลว!")
        sys.exit(1)
    print("✅ คอมไพล์โปรแกรม GameVault.exe สำเร็จ")


def create_patch_zip():
    """บีบอัด GameVault.exe และ assets/ เป็น patch.zip"""
    os.makedirs(RELEASE_DIR, exist_ok=True)
    if os.path.exists(PATCH_ZIP):
        os.remove(PATCH_ZIP)

    print("📦 กำลังสร้าง patch.zip สำหรับปล่อยอัปเดต...")
    with zipfile.ZipFile(PATCH_ZIP, "w", zipfile.ZIP_DEFLATED) as zf:
        # ใส่ GameVault.exe
        zf.write(DIST_EXE, arcname=f"{APP_NAME}.exe")

        # ใส่ assets
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
        new_ver = input("ระบุเวอร์ชันใหม่ที่ต้องการปล่อย (เช่น 1.0.0): ").strip().lstrip("v")
    else:
        new_ver = sys.argv[1].strip().lstrip("v")

    if not new_ver:
        print("❌ ต้องระบุเลขเวอร์ชัน เช่น 1.0.0")
        sys.exit(1)

    changelog_input = input("กรอก Changelog บรรทัดเดียว (หรือกด Enter เพื่อใช้ค่าเริ่มต้น): ").strip()
    if not changelog_input:
        changelog_input = "- ปรับปรุงประสิทธิภาพและการทำงานทั่วไป\n- อัปเดตระบบค้นหาและจัดการปกเกม"

    # ขั้นตอนที่ 1: อัปเดตเวอร์ชันในโค้ด
    update_current_version_in_code(new_ver)

    # ขั้นตอนที่ 2: คอมไพล์โปรแกรม
    build_executable()

    # ขั้นตอนที่ 3: สร้าง Patch ZIP
    create_patch_zip()

    # ขั้นตอนที่ 4: สร้าง version.json
    generate_manifest(new_ver, changelog_input)

    # ขั้นตอนที่ 5: ถามว่าจะอัปโหลดขึ้น GitHub เลยหรือไม่
    choice = input("\nต้องการปล่อย Release ขึ้น GitHub ทันทีเลยหรือไม่? (y/n): ").strip().lower()
    if choice == 'y':
        push_github_release(new_ver, changelog_input)
    else:
        print(f"\n💡 ไฟล์แพตช์พร้อมอยู่ที่โฟลเดอร์ '{RELEASE_DIR}' คุณสามารถอัปโหลดด้วยคำสั่ง:")
        print(f"gh release create v{new_ver} {PATCH_ZIP} {VERSION_FILE} --title \"GameVault v{new_ver}\"")
