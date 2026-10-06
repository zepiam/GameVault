"""
GameVault Auto-Updater Module
Manifest-based updater powered by GitHub Releases
"""

import os
import sys
import json
import urllib.request
import hashlib
import tempfile
import subprocess
from typing import Optional, Dict, Tuple
from packaging import version

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTextEdit, QProgressBar, QMessageBox
)

CURRENT_VERSION = "1.1.0"
REPO_OWNER = "zepiam"
REPO_NAME = "GameVault"
MANIFEST_URL = f"https://github.com/{REPO_OWNER}/{REPO_NAME}/releases/latest/download/version.json"


def get_current_version() -> str:
    return CURRENT_VERSION


def check_for_updates() -> Optional[Dict]:
    """
    ตรวจสอบว่ามีเวอร์ชันใหม่จาก GitHub หรือไม่
    ดาวน์โหลดตรงจาก version.json ใน latest release เพื่อไม่ให้ติด GitHub API rate limit
    """
    try:
        req = urllib.request.Request(
            MANIFEST_URL,
            headers={"User-Agent": f"GameVault-Updater/{CURRENT_VERSION}"}
        )
        with urllib.request.urlopen(req, timeout=6) as res:
            if res.status != 200:
                return None
            data = json.loads(res.read().decode("utf-8"))

        remote_ver = data.get("version")
        if remote_ver and version.parse(remote_ver) > version.parse(CURRENT_VERSION):
            return data
    except Exception as e:
        print(f"[updater] Check update failed or offline: {e}")
    return None


def calculate_sha256(filepath: str) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


class DownloadWorker(QThread):
    progress_changed = pyqtSignal(int, int)  # bytes_downloaded, total_bytes
    download_finished = pyqtSignal(str)      # temp_zip_path
    download_failed = pyqtSignal(str)        # error message

    def __init__(self, download_url: str, expected_sha256: str, expected_size: int = 0):
        super().__init__()
        self.download_url = download_url
        self.expected_sha256 = expected_sha256
        self.expected_size = expected_size
        self._is_cancelled = False

    def run(self):
        try:
            temp_zip = os.path.join(tempfile.gettempdir(), f"gv_patch_{os.getpid()}.zip")
            req = urllib.request.Request(
                self.download_url,
                headers={"User-Agent": f"GameVault-Updater/{CURRENT_VERSION}"}
            )

            with urllib.request.urlopen(req, timeout=15) as response, open(temp_zip, "wb") as out_file:
                total_length = response.headers.get("Content-Length")
                total_bytes = int(total_length) if total_length else self.expected_size
                downloaded = 0
                chunk_size = 65536

                while True:
                    if self._is_cancelled:
                        out_file.close()
                        if os.path.exists(temp_zip):
                            os.remove(temp_zip)
                        return

                    chunk = response.read(chunk_size)
                    if not chunk:
                        break
                    out_file.write(chunk)
                    downloaded += len(chunk)
                    self.progress_changed.emit(downloaded, total_bytes)

            # Check integrity
            computed_sha256 = calculate_sha256(temp_zip)
            if computed_sha256.lower() != self.expected_sha256.lower():
                if os.path.exists(temp_zip):
                    os.remove(temp_zip)
                self.download_failed.emit("Checksum SHA-256 ไม่ตรงกับไฟล์ต้นฉบับ ไฟล์อาจเสียหายขณะดาวน์โหลด")
                return

            self.download_finished.emit(temp_zip)
        except Exception as e:
            self.download_failed.emit(str(e))

    def cancel(self):
        self._is_cancelled = True


def apply_update_and_restart(patch_zip_path: str):
    """
    สลับไฟล์โปรแกรมเป็นเวอร์ชันใหม่ผ่าน Batch script ใน %TEMP%
    ใช้ Windows native tar -xf เพื่อแตกไฟล์ทับ
    """
    if getattr(sys, 'frozen', False):
        main_exe = sys.executable
        app_dir = os.path.dirname(main_exe)
    else:
        app_dir = os.path.dirname(os.path.abspath(__file__))
        main_exe = os.path.join(app_dir, "GameVault.exe")

    batch_script = os.path.join(tempfile.gettempdir(), f"gv_update_{os.getpid()}.bat")
    
    script_content = f"""@echo off
chcp 65001 > nul
timeout /t 2 /nobreak > nul
:retry
tar -xf "{patch_zip_path}" -C "{app_dir}"
if errorlevel 1 (
    timeout /t 1 /nobreak > nul
    goto retry
)
del /f /q "{patch_zip_path}" > nul 2>&1
start "" "{main_exe}"
del "%~f0"
"""

    with open(batch_script, "w", encoding="utf-8") as f:
        f.write(script_content)

    subprocess.Popen(
        ["cmd.exe", "/c", batch_script],
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    )
    sys.exit(0)


class UpdateDialog(QDialog):
    """หน้าต่างแสดงผลการตรวจสอบและติดตั้งอัปเดต"""

    def __init__(self, update_info: Dict, parent=None):
        super().__init__(parent)
        self.update_info = update_info
        self.worker = None

        new_ver = update_info.get("version", "Unknown")
        self.setWindowTitle(f"พบเวอร์ชันใหม่ — GameVault v{new_ver}")
        self.setFixedSize(520, 420)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        # Style colors
        self.setStyleSheet("""
            QDialog {
                background-color: #0f1117;
                color: #e6e6e6;
                font-family: 'Segoe UI', 'Noto Sans Thai', sans-serif;
            }
            QLabel {
                color: #e6e6e6;
            }
            QTextEdit {
                background-color: #1a1d27;
                color: #d1d5db;
                border: 1px solid #2e3446;
                border-radius: 8px;
                padding: 10px;
                font-size: 13px;
                line-height: 1.5;
            }
            QProgressBar {
                border: 1px solid #2e3446;
                border-radius: 6px;
                background-color: #1a1d27;
                text-align: center;
                color: #ffffff;
                font-weight: bold;
                height: 22px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #3b82f6, stop:1 #6366f1);
                border-radius: 5px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(22, 22, 22, 22)

        # Header Title
        title_box = QHBoxLayout()
        icon_lbl = QLabel("🚀")
        icon_lbl.setStyleSheet("font-size: 32px;")
        title_box.addWidget(icon_lbl)

        info_box = QVBoxLayout()
        header_lbl = QLabel(f"<b>GameVault v{new_ver} พร้อมให้อัปเดตแล้ว!</b>")
        header_lbl.setStyleSheet("font-size: 16px; color: #ffffff;")
        sub_lbl = QLabel(f"เวอร์ชันปัจจุบันของคุณ: <b>v{CURRENT_VERSION}</b>")
        sub_lbl.setStyleSheet("font-size: 12px; color: #9ca3af;")
        info_box.addWidget(header_lbl)
        info_box.addWidget(sub_lbl)
        title_box.addLayout(info_box)
        title_box.addStretch()
        layout.addLayout(title_box)

        # Changelog Label
        ch_lbl = QLabel("<b>มีอะไรใหม่ในเวอร์ชันนี้:</b>")
        ch_lbl.setStyleSheet("font-size: 13px; color: #60a5fa;")
        layout.addWidget(ch_lbl)

        # Changelog Box
        changelog = update_info.get("changelog", "ไม่มีรายละเอียดการเปลี่ยนแปลง")
        self.changelog_view = QTextEdit()
        self.changelog_view.setReadOnly(True)
        self.changelog_view.setPlainText(changelog)
        layout.addWidget(self.changelog_view)

        # Progress Bar (hidden by default)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        self.status_lbl = QLabel("")
        self.status_lbl.setStyleSheet("font-size: 12px; color: #9ca3af;")
        self.status_lbl.setVisible(False)
        layout.addWidget(self.status_lbl)

        # Buttons
        self.btn_layout = QHBoxLayout()
        self.btn_layout.addStretch()

        self.cancel_btn = QPushButton("ไว้คราวหน้า (Later)")
        self.cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #1e2230;
                color: #9ca3af;
                border: 1px solid #2e3446;
                border-radius: 6px;
                padding: 8px 18px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2e3446;
                color: #ffffff;
            }
        """)
        self.cancel_btn.clicked.connect(self.reject)
        self.btn_layout.addWidget(self.cancel_btn)

        self.update_btn = QPushButton("📥 อัปเดตทันที (Update Now)")
        self.update_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.update_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #2563eb, stop:1 #4f46e5);
                color: #ffffff;
                border: none;
                border-radius: 6px;
                padding: 8px 22px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1d4ed8, stop:1 #4338ca);
            }
        """)
        self.update_btn.clicked.connect(self.start_download)
        self.btn_layout.addWidget(self.update_btn)

        layout.addLayout(self.btn_layout)

    def start_download(self):
        download_data = self.update_info.get("download", {})
        url = download_data.get("url")
        sha256 = download_data.get("sha256")
        size = download_data.get("size", 0)

        if not url or not sha256:
            QMessageBox.critical(self, "ผิดพลาด", "ข้อมูล URL ดาวน์โหลดหรือ Checksum ใน Manifest ไม่ถูกต้อง")
            return

        self.update_btn.setEnabled(False)
        self.cancel_btn.setText("ยกเลิก")
        self.progress_bar.setVisible(True)
        self.status_lbl.setVisible(True)
        self.status_lbl.setText("กำลังดาวน์โหลดแพตช์...")

        self.worker = DownloadWorker(url, sha256, size)
        self.worker.progress_changed.connect(self.on_progress)
        self.worker.download_finished.connect(self.on_download_finished)
        self.worker.download_failed.connect(self.on_download_failed)
        self.worker.start()

    def on_progress(self, downloaded: int, total: int):
        if total > 0:
            percent = int((downloaded / total) * 100)
            self.progress_bar.setValue(percent)
            dl_mb = downloaded / (1024 * 1024)
            tot_mb = total / (1024 * 1024)
            self.status_lbl.setText(f"กำลังดาวน์โหลด: {dl_mb:.1f} MB / {tot_mb:.1f} MB ({percent}%)")
        else:
            dl_mb = downloaded / (1024 * 1024)
            self.status_lbl.setText(f"กำลังดาวน์โหลด: {dl_mb:.1f} MB...")

    def on_download_finished(self, temp_zip: str):
        self.status_lbl.setText("ดาวน์โหลดและตรวจสอบความถูกต้องสำเร็จ! กำลังรีสตาร์ท...")
        QMessageBox.information(
            self,
            "อัปเดตพร้อมใช้งาน",
            "ดาวน์โหลดเวอร์ชันใหม่เรียบร้อยแล้ว!\nโปรแกรมจะปิดตัวและติดตั้งอัปเดตให้อัตโนมัติ"
        )
        apply_update_and_restart(temp_zip)

    def on_download_failed(self, error_msg: str):
        self.update_btn.setEnabled(True)
        self.status_lbl.setText("การดาวน์โหลดล้มเหลว")
        QMessageBox.critical(self, "อัปเดตล้มเหลว", f"เกิดข้อผิดพลาดในการดาวน์โหลด:\n{error_msg}")

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait()
        super().closeEvent(event)
