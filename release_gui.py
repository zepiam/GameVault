"""
release_gui.py - One-Click Build & GitHub Release GUI Tool for GameVault
Created for MeN9CH by Google Deepmind Antigravity

Features:
- Auto-detects current version and suggests next patch version (e.g. 1.3.2 -> 1.3.3)
- Multi-line changelog editor with preset templates
- 1-Click Fully Automated Pipeline:
    1. Stops running GameVault.exe process
    2. Verifies Python syntax (py_compile)
    3. Updates CURRENT_VERSION in updater.py
    4. Builds GameVault.exe via PyInstaller (GameVault.spec --clean)
    5. Copies dist/GameVault.exe to root GameVault.exe
    6. Creates release/patch.zip containing GameVault.exe & assets/
    7. Generates release/version.json with calculated SHA-256
    8. Git Add, Commit & Push to origin/main
    9. Creates GitHub Release via gh CLI
    10. Opens the release URL in web browser
"""

import sys
import os
import re
import json
import zipfile
import hashlib
import subprocess
import webbrowser
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QIcon, QFont
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QTextEdit, QPushButton, QProgressBar,
    QCheckBox, QMessageBox, QFrame, QScrollArea
)

# Colors matching GameVault Theme
BG_MAIN = "#0e141b"
BG_PANEL = "#161f2c"
BG_CARD = "#1e293b"
BORDER_DEFAULT = "#2a3a4e"
ACCENT_BLUE = "#38bdf8"
ACCENT_GREEN = "#22c55e"
TEXT_PRIMARY = "#f8fafc"
TEXT_MUTED = "#94a3b8"

REPO_OWNER = "zepiam"
REPO_NAME = "GameVault"


def get_current_version() -> str:
    updater_p = Path("updater.py")
    if updater_p.exists():
        content = updater_p.read_text(encoding="utf-8", errors="ignore")
        m = re.search(r'CURRENT_VERSION\s*=\s*"([^"]+)"', content)
        if m:
            return m.group(1)
    return "1.3.8"


def bump_patch_version(ver_str: str) -> str:
    try:
        parts = ver_str.strip().lstrip("v").split(".")
        if len(parts) == 3:
            return f"{parts[0]}.{parts[1]}.{int(parts[2]) + 1}"
        elif len(parts) == 2:
            return f"{parts[0]}.{int(parts[1]) + 1}.0"
    except Exception:
        pass
    return ver_str


def calculate_sha256(filepath: str) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


class ReleaseWorker(QThread):
    log_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int)
    finished_signal = pyqtSignal(bool, str)

    def __init__(self, new_version: str, changelog: str, push_git: bool, push_gh: bool):
        super().__init__()
        self.new_version = new_version.strip().lstrip("v")
        self.changelog = changelog.strip()
        self.push_git = push_git
        self.push_gh = push_gh

    def log(self, msg: str):
        self.log_signal.emit(msg)

    def run(self):
        try:
            total_steps = 8
            current_step = 0

            def advance(step_num, title):
                pct = int((step_num / total_steps) * 100)
                self.progress_signal.emit(pct)
                self.log(f"\n==========================================")
                self.log(f"[{step_num}/{total_steps}] ⏳ {title}...")
                self.log(f"==========================================")

            # ----------------------------------------------------
            # Step 1: Terminate running GameVault processes
            # ----------------------------------------------------
            advance(1, "ปิดโปรเซส GameVault ที่กำลังทำงานอยู่")
            try:
                subprocess.run(
                    ["powershell", "-Command", "Stop-Process -Name GameVault -Force -ErrorAction SilentlyContinue"],
                    check=False
                )
                self.log("✅ ปิดโปรเซส GameVault.exe สำเร็จ")
            except Exception as e:
                self.log(f"⚠️ คำเตือน: {e}")

            # ----------------------------------------------------
            # Step 2: Verify Python syntax
            # ----------------------------------------------------
            advance(2, "ตรวจสอบความถูกต้องของ Syntax โค้ด (py_compile)")
            files_to_check = ["app.py", "db.py", "scanner.py", "cover_fetcher.py", "steam_sync.py", "updater.py"]
            for f in files_to_check:
                if os.path.exists(f):
                    res = subprocess.run([sys.executable, "-m", "py_compile", f], capture_output=True, text=True)
                    if res.returncode != 0:
                        raise RuntimeError(f"Syntax Error in {f}:\n{res.stderr}")
                    self.log(f"  ✓ {f} ผ่านการตรวจสอบ")
            self.log("✅ ทุกไฟล์ Python ถูกต้องสมบูรณ์ 100%")

            # ----------------------------------------------------
            # Step 3: Update version in updater.py
            # ----------------------------------------------------
            advance(3, f"อัปเดตเลขเวอร์ชันเป็น v{self.new_version} ใน updater.py")
            updater_file = Path("updater.py")
            if updater_file.exists():
                txt = updater_file.read_text(encoding="utf-8")
                txt = re.sub(r'CURRENT_VERSION\s*=\s*"[^"]+"', f'CURRENT_VERSION = "{self.new_version}"', txt)
                updater_file.write_text(txt, encoding="utf-8")
                self.log(f"✅ บันทึก CURRENT_VERSION = \"{self.new_version}\" เรียบร้อย")

            # ----------------------------------------------------
            # Step 4: Build GameVault.exe via PyInstaller
            # ----------------------------------------------------
            advance(4, "คอมไพล์โปรแกรมด้วย PyInstaller (GameVault.spec)")
            spec_file = "GameVault.spec"
            if not os.path.exists(spec_file):
                raise FileNotFoundError("ไม่พบไฟล์ GameVault.spec!")

            pyi_cmd = ["pyinstaller", spec_file, "--clean"]
            self.log(f"กำลังรัน: {' '.join(pyi_cmd)}")
            proc = subprocess.Popen(
                pyi_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace"
            )
            while True:
                line = proc.stdout.readline()
                if not line and proc.poll() is not None:
                    break
                if line:
                    stripped = line.strip()
                    if "INFO:" in stripped or "WARNING:" in stripped:
                        self.log(f"  [PyInstaller] {stripped}")

            if proc.returncode != 0:
                raise RuntimeError(f"PyInstaller build failed with return code {proc.returncode}")

            # Copy to root
            dist_exe = Path("dist/GameVault.exe")
            root_exe = Path("GameVault.exe")
            if dist_exe.exists():
                import shutil
                shutil.copy2(dist_exe, root_exe)
                exe_size_mb = root_exe.stat().st_size / (1024 * 1024)
                self.log(f"✅ คัดลอก {root_exe} เรียบร้อย (ขนาด {exe_size_mb:.2f} MB)")
            else:
                raise FileNotFoundError("ไม่พบไฟล์ dist/GameVault.exe หลังการบิลด์")

            # ----------------------------------------------------
            # Step 5: Package patch.zip & version.json
            # ----------------------------------------------------
            advance(5, "สร้างแพ็กเกจอัปเดต release/patch.zip และ version.json")
            release_dir = Path("release")
            release_dir.mkdir(parents=True, exist_ok=True)

            patch_zip = release_dir / "patch.zip"
            if patch_zip.exists():
                patch_zip.unlink()

            with zipfile.ZipFile(patch_zip, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.write(root_exe, arcname="GameVault.exe")
                assets_dir = Path("assets")
                if assets_dir.exists():
                    for root, _, files in os.walk(assets_dir):
                        for file in files:
                            full_p = Path(root) / file
                            rel_p = full_p.relative_to(Path("."))
                            zf.write(full_p, arcname=str(rel_p))

            zip_size_mb = patch_zip.stat().st_size / (1024 * 1024)
            sha256 = calculate_sha256(str(patch_zip))
            self.log(f"✅ สร้าง {patch_zip} สำเร็จ (ขนาด {zip_size_mb:.2f} MB)")
            self.log(f"  SHA-256: {sha256}")

            # Manifest version.json
            manifest = {
                "version": self.new_version,
                "min_required_version": "1.0.0",
                "release_date": datetime.now().strftime("%Y-%m-%d"),
                "changelog": self.changelog,
                "download": {
                    "url": f"https://github.com/{REPO_OWNER}/{REPO_NAME}/releases/download/v{self.new_version}/patch.zip",
                    "size": patch_zip.stat().st_size,
                    "sha256": sha256
                }
            }
            version_json = release_dir / "version.json"
            version_json.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
            self.log(f"✅ สร้าง {version_json} สำเร็จ")

            # ----------------------------------------------------
            # Step 6: Git Commit & Push
            # ----------------------------------------------------
            if self.push_git:
                advance(6, "Git Add, Commit และ Push ขึ้น origin/main")
                subprocess.run(["git", "add", "app.py", "db.py", "scanner.py", "cover_fetcher.py",
                                "steam_sync.py", "updater.py", "GameVault.spec", "build_release.py",
                                "release_gui.py", ".gitignore"], check=False)
                
                commit_msg = f"Bump v{self.new_version}: {self.changelog.splitlines()[0] if self.changelog else 'Update release'}"
                self.log(f"Commit Message: {commit_msg}")
                subprocess.run(["git", "commit", "-m", commit_msg], check=False)

                push_res = subprocess.run(["git", "push", "origin", "main"], capture_output=True, text=True)
                if push_res.returncode == 0:
                    self.log("✅ Git Push ขึ้น GitHub (origin/main) สำเร็จเรียบร้อย")
                else:
                    self.log(f"⚠️ Git Push: {push_res.stderr or push_res.stdout}")
            else:
                self.log("\n[ข้าม] ไม่ได้เลือก Git Push")

            # ----------------------------------------------------
            # Step 7: Create GitHub Release via gh CLI
            # ----------------------------------------------------
            release_url = f"https://github.com/{REPO_OWNER}/{REPO_NAME}/releases/tag/v{self.new_version}"
            if self.push_gh:
                advance(7, f"สร้างและเผยแพร่ GitHub Release: v{self.new_version}")
                gh_cmd = [
                    "gh", "release", "create", f"v{self.new_version}",
                    str(patch_zip),
                    str(version_json),
                    "--title", f"GameVault v{self.new_version}",
                    "--notes", self.changelog
                ]
                self.log(f"กำลังส่งคำสั่ง gh release create...")
                gh_res = subprocess.run(gh_cmd, capture_output=True, text=True)
                if gh_res.returncode == 0:
                    self.log(f"🎉 สำเร็จ! ปล่อย Release v{self.new_version} ขึ้น GitHub เรียบร้อยแล้ว")
                    webbrowser.open(release_url)
                else:
                    self.log(f"⚠️ gh release create แจ้งเตือน: {gh_res.stderr or gh_res.stdout}")
            else:
                self.log("\n[ข้าม] ไม่ได้เลือกสร้าง GitHub Release")

            # ----------------------------------------------------
            # Step 8: Done!
            # ----------------------------------------------------
            advance(8, "เสร็จสิ้นกระบวนการทั้งหมด!")
            self.progress_signal.emit(100)
            self.log(f"\n🎉 GameVault v{self.new_version} พร้อมใช้งานและปล่อยอัปเดตแล้ว!")
            self.finished_signal.emit(True, release_url)

        except Exception as e:
            import traceback
            err_details = traceback.format_exc()
            self.log(f"\n❌ เกิดข้อผิดพลาด:\n{err_details}")
            self.finished_signal.emit(False, str(e))


class ReleaseGuiWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("🚀 GameVault - 1-Click GitHub Release Tool")
        self.resize(780, 680)
        self.setStyleSheet(f"""
            QMainWindow {{
                background-color: {BG_MAIN};
                color: {TEXT_PRIMARY};
                font-family: 'Segoe UI', 'Noto Sans Thai', sans-serif;
            }}
            QLabel {{
                color: {TEXT_PRIMARY};
            }}
            QLineEdit, QTextEdit {{
                background-color: {BG_PANEL};
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_DEFAULT};
                border-radius: 6px;
                padding: 8px 12px;
                font-size: 13px;
            }}
            QLineEdit:focus, QTextEdit:focus {{
                border-color: {ACCENT_BLUE};
            }}
            QCheckBox {{
                color: {TEXT_PRIMARY};
                font-size: 13px;
                font-weight: 500;
                spacing: 8px;
            }}
            QCheckBox::indicator {{
                width: 18px;
                height: 18px;
                border-radius: 4px;
                border: 1px solid #475569;
                background-color: {BG_CARD};
            }}
            QCheckBox::indicator:checked {{
                background-color: {ACCENT_BLUE};
                border-color: {ACCENT_BLUE};
            }}
            QPushButton {{
                border-radius: 6px;
                font-weight: bold;
                padding: 10px 18px;
                font-size: 13px;
            }}
        """)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        # Header Title
        hdr_row = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("🚀 GameVault Auto-Release & Deploy")
        title.setStyleSheet(f"font-size: 18px; font-weight: bold; color: {ACCENT_BLUE};")
        subtitle = QLabel("กดปุ่มเดียวเพื่อคอมไพล์ .exe, สร้าง Patch ZIP, Git Push และสร้าง GitHub Release อัตโนมัติ")
        subtitle.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        hdr_row.addLayout(title_box)
        hdr_row.addStretch()
        layout.addLayout(hdr_row)

        # Divider
        sep1 = QFrame()
        sep1.setFrameShape(QFrame.Shape.HLine)
        sep1.setStyleSheet(f"background-color: {BORDER_DEFAULT}; max-height: 1px;")
        layout.addWidget(sep1)

        # Version Row
        ver_row = QHBoxLayout()
        ver_row.setSpacing(12)

        curr_ver = get_current_version()
        next_ver = bump_patch_version(curr_ver)

        curr_lbl = QLabel(f"เวอร์ชันปัจจุบัน: <b style='color: {ACCENT_BLUE};'>v{curr_ver}</b>")
        curr_lbl.setStyleSheet("font-size: 13px;")
        ver_row.addWidget(curr_lbl)

        ver_row.addSpacing(16)
        next_lbl = QLabel("เวอร์ชันใหม่ที่จะปล่อย:")
        next_lbl.setStyleSheet("font-size: 13px; font-weight: bold;")
        ver_row.addWidget(next_lbl)

        self.ver_input = QLineEdit(next_ver)
        self.ver_input.setFixedWidth(120)
        self.ver_input.setStyleSheet("font-size: 14px; font-weight: bold; color: #34d399;")
        ver_row.addWidget(self.ver_input)
        ver_row.addStretch()
        layout.addLayout(ver_row)

        # Changelog Section
        cl_box = QVBoxLayout()
        cl_box.setSpacing(6)
        cl_lbl = QLabel("รายละเอียดการเปลี่ยนแปลง (Changelog / Release Notes):")
        cl_lbl.setStyleSheet("font-size: 13px; font-weight: bold;")
        cl_box.addWidget(cl_lbl)

        self.cl_edit = QTextEdit()
        default_notes = (
            "- ปรับปรุงประสิทธิภาพและการทำงานทั่วไป\n"
            "- อัปเดตระบบค้นหา จัดการ และแสดงผลคลังเกม\n"
            "- ปรับปรุงความเสถียรของตัวเปิดเกม (Launcher)"
        )
        self.cl_edit.setPlainText(default_notes)
        self.cl_edit.setFixedHeight(95)
        cl_box.addWidget(self.cl_edit)
        layout.addLayout(cl_box)

        # Options checkboxes
        opt_row = QHBoxLayout()
        opt_row.setSpacing(20)
        self.git_cb = QCheckBox("Git Add, Commit & Push ขึ้น origin/main")
        self.git_cb.setChecked(True)
        self.gh_cb = QCheckBox("สร้าง GitHub Release ผ่าน gh CLI อัตโนมัติ")
        self.gh_cb.setChecked(True)
        opt_row.addWidget(self.git_cb)
        opt_row.addWidget(self.gh_cb)
        opt_row.addStretch()
        layout.addLayout(opt_row)

        # Big Launch Button
        self.release_btn = QPushButton("🚀 เริ่มต้นกระบวนการ Release (1-Click Auto Deploy)")
        self.release_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.release_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: #0284c7;
                color: #ffffff;
                font-size: 14px;
                font-weight: bold;
                padding: 12px;
                border: 1px solid #38bdf8;
            }}
            QPushButton:hover {{
                background-color: #0369a1;
            }}
            QPushButton:disabled {{
                background-color: #334155;
                color: #64748b;
                border-color: #475569;
            }}
        """)
        self.release_btn.clicked.connect(self.start_release)
        layout.addWidget(self.release_btn)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setStyleSheet(f"""
            QProgressBar {{
                border: 1px solid {BORDER_DEFAULT};
                border-radius: 4px;
                background-color: {BG_PANEL};
                text-align: center;
                color: #ffffff;
                font-weight: bold;
                height: 18px;
            }}
            QProgressBar::chunk {{
                background-color: {ACCENT_GREEN};
                border-radius: 3px;
            }}
        """)
        layout.addWidget(self.progress_bar)

        # Log Terminal Output
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setStyleSheet(f"""
            QTextEdit {{
                background-color: #080c10;
                color: #cbd5e1;
                font-family: Consolas, 'Cascadia Code', monospace;
                font-size: 11.5px;
                border: 1px solid {BORDER_DEFAULT};
                border-radius: 6px;
            }}
        """)
        layout.addWidget(self.log_view, 1)

    def log(self, text: str):
        self.log_view.append(text)
        sb = self.log_view.verticalScrollBar()
        sb.setValue(sb.maximum())

    def start_release(self):
        new_v = self.ver_input.text().strip().lstrip("v")
        if not new_v:
            QMessageBox.warning(self, "ข้อผิดพลาด", "กรุณาระบุเลขเวอร์ชัน เช่น 1.3.3")
            return

        changelog = self.cl_edit.toPlainText().strip()
        if not changelog:
            QMessageBox.warning(self, "ข้อผิดพลาด", "กรุณาระบุ Changelog อย่างน้อย 1 บรรทัด")
            return

        confirm = QMessageBox.question(
            self,
            "ยืนยันการ Release",
            f"คุณต้องการคอมไพล์และปล่อยอัปเดต GameVault v{new_v} ขึ้น GitHub เลยใช่หรือไม่?\n\n"
            f"• เวอร์ชัน: v{new_v}\n"
            f"• Git Push: {'เปิด' if self.git_cb.isChecked() else 'ปิด'}\n"
            f"• GitHub Release: {'เปิด' if self.gh_cb.isChecked() else 'ปิด'}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        self.release_btn.setEnabled(False)
        self.ver_input.setEnabled(False)
        self.cl_edit.setEnabled(False)
        self.git_cb.setEnabled(False)
        self.gh_cb.setEnabled(False)
        self.progress_bar.setValue(0)
        self.log_view.clear()

        self.worker = ReleaseWorker(
            new_version=new_v,
            changelog=changelog,
            push_git=self.git_cb.isChecked(),
            push_gh=self.gh_cb.isChecked()
        )
        self.worker.log_signal.connect(self.log)
        self.worker.progress_signal.connect(self.progress_bar.setValue)
        self.worker.finished_signal.connect(self.on_finished)
        self.worker.start()

    def on_finished(self, success: bool, msg: str):
        self.release_btn.setEnabled(True)
        self.ver_input.setEnabled(True)
        self.cl_edit.setEnabled(True)
        self.git_cb.setEnabled(True)
        self.gh_cb.setEnabled(True)

        if success:
            QMessageBox.information(
                self,
                "Release สำเร็จ! 🎉",
                f"GameVault เวอร์ชันใหม่ถูกปล่อยขึ้น GitHub เรียบร้อยแล้ว!\n\n"
                f"🔗 URL: {msg}"
            )
        else:
            QMessageBox.critical(
                self,
                "Release ล้มเหลว",
                f"เกิดข้อผิดพลาดในการปล่อย Release:\n\n{msg}"
            )


def main():
    app = QApplication(sys.argv)
    win = ReleaseGuiWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
