"""supporter_dialog.py — Donate window for GameVault by MeN9CH

- SupportersDialog: QR codes to scan, list of supporters (fetched from the
  shared MeN9CH API so it matches every other MeN9CH app/website), and a
  button to open the submission form.
- SupporterUploadDialog: multi-channel proof-of-donation form (bank slip /
  bank manual / TrueMoney), ported from Broadcast Playroom's dialog.
"""
from __future__ import annotations

import os
import sys

from PyQt6.QtCore import Qt, QThread, pyqtSignal as Signal, QDate, QTime
from PyQt6.QtGui import QPixmap, QAction
from PyQt6.QtWidgets import (
    QDialog, QWidget, QFrame, QLabel, QPushButton, QLineEdit, QVBoxLayout,
    QHBoxLayout, QFormLayout, QFileDialog, QMessageBox, QComboBox, QDoubleSpinBox,
    QProgressBar, QTextEdit, QDateEdit, QTimeEdit, QButtonGroup, QRadioButton,
    QScrollArea, QSizePolicy,
)
# PyQt6 Enum Compatibility Shims
if not hasattr(QFormLayout, "ExpandingFieldsGrow"):
    QFormLayout.ExpandingFieldsGrow = QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow
if not hasattr(QMessageBox, "Yes"):
    QMessageBox.Yes = QMessageBox.StandardButton.Yes
    QMessageBox.No = QMessageBox.StandardButton.No
if not hasattr(QSizePolicy, "Fixed"):
    QSizePolicy.Fixed = QSizePolicy.Policy.Fixed
if not hasattr(QDialog, "Accepted"):
    QDialog.Accepted = QDialog.DialogCode.Accepted
if not hasattr(Qt, "PointingHandCursor"):
    Qt.PointingHandCursor = Qt.CursorShape.PointingHandCursor
if not hasattr(Qt, "AlignCenter"):
    Qt.AlignCenter = Qt.AlignmentFlag.AlignCenter
if not hasattr(Qt, "AlignRight"):
    Qt.AlignRight = Qt.AlignmentFlag.AlignRight
if not hasattr(Qt, "AlignLeft"):
    Qt.AlignLeft = Qt.AlignmentFlag.AlignLeft
if not hasattr(Qt, "KeepAspectRatio"):
    Qt.KeepAspectRatio = Qt.AspectRatioMode.KeepAspectRatio
if not hasattr(Qt, "SmoothTransformation"):
    Qt.SmoothTransformation = Qt.TransformationMode.SmoothTransformation

from supporters_api import fetch_supporters, get_tier, format_amount, SUPPORTERS_API_URL

_BASE_DIR = sys._MEIPASS if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(_BASE_DIR, "assets")

BANKS = [
    ("SCB", "ธนาคารไทยพาณิชย์"),
    ("KBANK", "ธนาคารกสิกรไทย"),
    ("BBL", "ธนาคารกรุงเทพ"),
    ("KTB", "ธนาคารกรุงไทย"),
    ("BAY", "ธนาคารกรุงศรีอยุธยา"),
    ("TTB", "ธนาคารทหารไทยธนชาต"),
    ("GHB", "ธนาคารอาคารสงเคราะห์"),
    ("CIMB", "ธนาคารซีไอเอ็มบีไทย"),
    ("UOB", "ธนาคารยูโอบี"),
    ("LH", "ธนาคารแลนด์ แอนด์ ฮาวส์"),
    ("OTHER", "อื่นๆ"),
]

_DIALOG_STYLESHEET = """
    QDialog { background-color: #0f172a; color: #e2e8f0; }
    QLabel { color: #e2e8f0; }
    QLabel[role="title"] { font-size: 18px; font-weight: 700; color: #10b981; }
    QLabel[role="subtitle"] { color: #94a3b8; font-size: 12px; }
    QLabel[role="section-label"] { color: #f59e0b; font-size: 13px; font-weight: 700; margin-top: 8px; }
    QLabel[role="field-label"] { color: #94a3b8; font-size: 12px; font-weight: 600; }
    QLabel[role="hint"] { color: #64748b; font-size: 11px; }
    QLabel[role="filename"] { color: #10b981; font-size: 12px; font-weight: 600; }
    QLineEdit, QTextEdit, QDoubleSpinBox, QComboBox, QDateEdit, QTimeEdit {
        background-color: #1e293b; border: 1px solid #334155; border-radius: 6px;
        padding: 8px; color: #e2e8f0; font-size: 13px;
    }
    QLineEdit:focus, QTextEdit:focus, QDoubleSpinBox:focus, QComboBox:focus,
    QDateEdit:focus, QTimeEdit:focus { border-color: #7c3aed; }
    QComboBox::drop-down { border: none; }
    QComboBox QAbstractItemView { background-color: #1e293b; color: #e2e8f0; selection-background-color: #7c3aed; }
    QPushButton#Primary {
        background-color: #10b981; color: white; font-weight: 700;
        border: none; border-radius: 6px; padding: 12px;
    }
    QPushButton#Primary:hover { background-color: #059669; }
    QPushButton#Primary:disabled { background-color: #334155; color: #64748b; }
    QPushButton#Secondary {
        background-color: #334155; color: #e2e8f0; font-weight: 600;
        border: none; border-radius: 6px; padding: 12px;
    }
    QPushButton#Secondary:hover { background-color: #475569; }
    QPushButton#FileDrop {
        background-color: #1e293b; border: 2px dashed #334155; border-radius: 8px;
        color: #94a3b8; padding: 20px; font-size: 13px; text-align: center;
    }
    QPushButton#FileDrop:hover { border-color: #7c3aed; background-color: #1e1b4b; }
    QRadioButton { color: #e2e8f0; font-size: 13px; padding: 8px; }
    QRadioButton::indicator { width: 16px; height: 16px; }
    QRadioButton::indicator:unchecked { border: 2px solid #475569; border-radius: 9px; background: #1e293b; }
    QRadioButton::indicator:checked { border: 2px solid #7c3aed; border-radius: 9px; background: #7c3aed; }
    QProgressBar {
        background-color: #1e293b; border: 1px solid #334155; border-radius: 4px;
        text-align: center; color: #e2e8f0; height: 6px;
    }
    QProgressBar::chunk { background-color: #10b981; border-radius: 3px; }
"""


def _channel_radio(text: str) -> QRadioButton:
    return QRadioButton(text)


class _SubmitThread(QThread):
    finished_sig = Signal(dict)
    progress_sig = Signal(int)

    def __init__(self, payload: dict, api_url: str):
        super().__init__()
        self.payload = payload
        self.api_url = api_url

    def run(self):
        try:
            from supporters_api import submit_supporter
            self.progress_sig.emit(20)
            result = submit_supporter(api_url=self.api_url, **self.payload)
            self.progress_sig.emit(100)
            self.finished_sig.emit(result)
        except Exception as e:
            self.finished_sig.emit({"ok": False, "error": f"เกิดข้อผิดพลาด: {e}"})


class SupporterUploadDialog(QDialog):
    """ฟอร์มส่งหลักฐานการสนับสนุน — multi-channel reactive form"""

    def __init__(self, parent=None, api_url: str = SUPPORTERS_API_URL):
        super().__init__(parent)
        self._api_url = api_url
        self._slip_path = None
        self._thread = None

        self.setWindowTitle("💚 ส่งหลักฐานการสนับสนุน")
        self.setModal(True)
        self.setMinimumWidth(480)
        self.setStyleSheet(_DIALOG_STYLESHEET)

        self._build_ui()
        self._on_channel_change()
        self._on_method_change()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(6)

        title = QLabel("💚 ส่งหลักฐานการสนับสนุน")
        title.setProperty("role", "title")
        title.setToolTip("ขอบคุณที่สนับสนุน GameVault by MeN9CH")
        layout.addWidget(title)

        channel_row = QHBoxLayout()
        channel_row.setSpacing(10)
        channel_row.addWidget(QLabel("ช่องทาง:"))
        self.channel_group = QButtonGroup(self)
        self.rb_bank = _channel_radio("🏦 ธนาคาร")
        self.rb_tm = _channel_radio("💵 True Money")
        self.channel_group.addButton(self.rb_bank)
        self.channel_group.addButton(self.rb_tm)
        self.rb_bank.setChecked(True)
        self.rb_bank.toggled.connect(self._on_channel_change)
        channel_row.addWidget(self.rb_bank)
        channel_row.addWidget(self.rb_tm)
        channel_row.addStretch(1)
        layout.addLayout(channel_row)

        method_row = QHBoxLayout()
        method_row.setSpacing(10)
        self.method_label = QLabel("แจ้งยอด:")
        method_row.addWidget(self.method_label)
        self.method_group = QButtonGroup(self)
        self.rb_slip = _channel_radio("📷 แนบสลิป")
        self.rb_manual = _channel_radio("✍️ กรอกข้อมูล")
        self.method_group.addButton(self.rb_slip)
        self.method_group.addButton(self.rb_manual)
        self.rb_slip.setChecked(True)
        self.rb_slip.toggled.connect(self._on_method_change)
        method_row.addWidget(self.rb_slip)
        method_row.addWidget(self.rb_manual)
        method_row.addStretch(1)
        layout.addLayout(method_row)

        self.slip_label = QLabel("📷 สลิป (PNG/JPG/WebP/GIF ≤5MB):")
        self.slip_label.setProperty("role", "field-label")
        layout.addWidget(self.slip_label)

        slip_row = QHBoxLayout()
        self.btn_file = QPushButton("📎 เลือกไฟล์รูป...")
        self.btn_file.setObjectName("FileDrop")
        self.btn_file.setCursor(Qt.PointingHandCursor)
        self.btn_file.clicked.connect(self._pick_file)
        slip_row.addWidget(self.btn_file, 1)

        self.filename_label = QLabel("")
        self.filename_label.setProperty("role", "filename")
        slip_row.addWidget(self.filename_label)
        layout.addLayout(slip_row)

        self.slip_preview = QLabel()
        self.slip_preview.setAlignment(Qt.AlignCenter)
        self.slip_preview.setMaximumHeight(90)
        layout.addWidget(self.slip_preview)

        self.form = QFormLayout()
        self.form.setContentsMargins(0, 4, 0, 4)
        self.form.setSpacing(6)
        self.form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        layout.addLayout(self.form)

        self.bank_label = QLabel("🏦 ธนาคาร:")
        self.bank_combo = QComboBox()
        for code, name in BANKS:
            self.bank_combo.addItem(f"{code} — {name}", code)
        self.form.addRow(self.bank_label, self.bank_combo)

        self.datetime_label = QLabel("🕐 วันที่/เวลาโอน:")
        datetime_field = QWidget()
        datetime_row = QHBoxLayout(datetime_field)
        datetime_row.setContentsMargins(0, 0, 0, 0)
        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDate(QDate.currentDate())
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        datetime_row.addWidget(self.date_edit, 1)
        self.time_edit = QTimeEdit()
        self.time_edit.setTime(QTime.currentTime())
        self.time_edit.setDisplayFormat("HH:mm")
        datetime_row.addWidget(self.time_edit, 1)
        self.form.addRow(self.datetime_label, datetime_field)

        amount_field = QWidget()
        amount_row = QHBoxLayout(amount_field)
        amount_row.setContentsMargins(0, 0, 0, 0)
        self.amount_input = QDoubleSpinBox()
        self.amount_input.setMinimum(1)
        self.amount_input.setMaximum(9999999)
        self.amount_input.setDecimals(2)
        self.amount_input.setValue(100)
        amount_row.addWidget(self.amount_input, 1)
        self.currency_combo = QComboBox()
        for cur in ["THB", "USD", "JPY", "EUR"]:
            self.currency_combo.addItem(cur)
        self.currency_combo.setFixedWidth(80)
        amount_row.addWidget(self.currency_combo)
        self.form.addRow("💰 จำนวนเงิน:", amount_field)

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("เช่น คุณAAA")
        self.name_input.setMaxLength(50)
        self.form.addRow("👤 ชื่อที่แสดง:", self.name_input)

        platform_field = QWidget()
        platform_row = QHBoxLayout(platform_field)
        platform_row.setContentsMargins(0, 0, 0, 0)
        self.platform_combo = QComboBox()
        self.platform_combo.addItem("— ไม่ระบุ —", "")
        self.platform_combo.addItem("🟣 Twitch", "twitch")
        self.platform_combo.addItem("🔴 YouTube", "youtube")
        self.platform_combo.addItem("🟢 Kick", "kick")
        self.platform_combo.addItem("🎵 TikTok", "tiktok")
        self.platform_combo.addItem("🔴 MyLive", "mylive")
        platform_row.addWidget(self.platform_combo, 1)
        self.channel_url_input = QLineEdit()
        self.channel_url_input.setPlaceholderText("ลิงก์ช่อง (ไม่บังคับ)")
        platform_row.addWidget(self.channel_url_input, 2)
        self.form.addRow("📺 แพลตฟอร์ม:", platform_field)

        self.message_input = QTextEdit()
        self.message_input.setPlaceholderText("สู้ๆครับ / ขอบคุณสำหรับโปรแกรมดีๆ")
        self.message_input.setMaximumHeight(44)
        self.form.addRow("💬 ข้อความ:", self.message_input)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.progress.setTextVisible(False)
        layout.addWidget(self.progress)

        btn_row = QHBoxLayout()
        btn_cancel = QPushButton("ยกเลิก")
        btn_cancel.setObjectName("Secondary")
        btn_cancel.clicked.connect(self.reject)
        self.btn_submit = QPushButton("ส่ง ✉️")
        self.btn_submit.setObjectName("Primary")
        self.btn_submit.clicked.connect(self._on_submit)
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(self.btn_submit, 1)
        layout.addLayout(btn_row)

        warning = QLabel("⚠️ ส่งข้อมูลเท็จ ระบบจะแบนไม่ให้ใช้งานโปรแกรม")
        warning.setAlignment(Qt.AlignCenter)
        warning.setStyleSheet(
            "font-size: 10px; color: #ef4444; "
            "background: rgba(239, 68, 68, 0.08); "
            "border: 1px solid rgba(239, 68, 68, 0.3); "
            "border-radius: 4px; padding: 4px;"
        )
        layout.addWidget(warning)

    def _on_channel_change(self):
        is_bank = self.rb_bank.isChecked()
        self.method_label.setVisible(is_bank)
        self.rb_slip.setVisible(is_bank)
        self.rb_manual.setVisible(is_bank)

        if not is_bank:
            self._show_slip_fields(False)
            self._show_bank_fields(False)
            self._show_datetime_fields(True)
        else:
            self._on_method_change()

    def _on_method_change(self):
        if not self.rb_bank.isChecked():
            return
        is_slip = self.rb_slip.isChecked()
        self._show_slip_fields(is_slip)
        self._show_bank_fields(not is_slip)
        self._show_datetime_fields(not is_slip)

    def _show_slip_fields(self, show: bool):
        for w in [self.slip_label, self.btn_file, self.filename_label, self.slip_preview]:
            w.setVisible(show)
        if not show:
            self._slip_path = None
            self.filename_label.setText("")

    def _show_bank_fields(self, show: bool):
        self.form.setRowVisible(self.bank_combo, show)

    def _show_datetime_fields(self, show: bool):
        self.form.setRowVisible(self.date_edit.parentWidget(), show)

    def _pick_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "เลือกรูปสลิป", "", "Images (*.png *.jpg *.jpeg *.webp *.gif);;All Files (*.*)"
        )
        if path:
            self._slip_path = path
            filename = os.path.basename(path)
            size_kb = os.path.getsize(path) / 1024
            self.filename_label.setText(f"✅ {filename} ({size_kb:.0f} KB)")
            self.btn_file.setText("📎 เลือกใหม่...")
            pix = QPixmap(path)
            if not pix.isNull():
                self.slip_preview.setPixmap(pix.scaledToHeight(90, Qt.SmoothTransformation))

    def _build_payload(self):
        name = self.name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "ข้อมูลไม่ครบ", "กรุณากรอกชื่อที่ต้องการแสดง")
            return None

        amount = self.amount_input.value()
        currency = self.currency_combo.currentText()
        message = self.message_input.toPlainText().strip()[:200]

        try:
            from machine_id import get_machine_id
            machine_id = get_machine_id()
        except Exception:
            machine_id = ""

        payload = {
            "name": name,
            "amount": amount,
            "currency": currency,
            "message": message,
            "machine_id": machine_id,
            "platform": self.platform_combo.currentData() or "",
            "channel_url": self.channel_url_input.text().strip(),
        }

        is_bank = self.rb_bank.isChecked()
        if is_bank:
            payload["channel"] = "bank"
            is_slip = self.rb_slip.isChecked()
            if is_slip:
                payload["method"] = "slip"
                if not self._slip_path or not os.path.exists(self._slip_path):
                    QMessageBox.warning(self, "ข้อมูลไม่ครบ", "กรุณาเลือกไฟล์รูปสลิป")
                    return None
                payload["slip_path"] = self._slip_path
            else:
                payload["method"] = "manual"
                payload["bank"] = self.bank_combo.currentData()
                payload["transfer_date"] = self.date_edit.date().toString("yyyy-MM-dd")
                payload["transfer_time"] = self.time_edit.time().toString("HH:mm")
        else:
            payload["channel"] = "truemoney"
            payload["transfer_date"] = self.date_edit.date().toString("yyyy-MM-dd")
            payload["transfer_time"] = self.time_edit.time().toString("HH:mm")

        return payload

    def _on_submit(self):
        payload = self._build_payload()
        if payload is None:
            return

        channel_text = "ธนาคาร" if payload["channel"] == "bank" else "True Money"
        if payload["channel"] == "bank" and payload.get("method") == "slip":
            channel_text += " (แนบสลิป)"
        elif payload["channel"] == "bank":
            channel_text += f" ({payload.get('bank', '?')})"

        reply = QMessageBox.question(
            self, "ยืนยันการส่ง",
            f"ยืนยันส่งข้อมูลการสนับสนุน?\n\n"
            f"ช่องทาง: {channel_text}\n"
            f"จำนวน: {payload['amount']} {payload['currency']}\n"
            f"ชื่อ: {payload['name']}",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes,
        )
        if reply != QMessageBox.Yes:
            return

        self.btn_submit.setEnabled(False)
        self.btn_submit.setText("กำลังส่ง...")
        self.progress.setVisible(True)
        self.progress.setValue(0)

        self._thread = _SubmitThread(payload, self._api_url)
        self._thread.progress_sig.connect(self.progress.setValue)
        self._thread.finished_sig.connect(self._on_finished)
        self._thread.start()

    def _on_finished(self, result: dict):
        self.btn_submit.setEnabled(True)
        self.btn_submit.setText("ส่ง ✉️")
        self.progress.setVisible(False)

        if result.get("ok"):
            QMessageBox.information(
                self, "✅ ส่งสำเร็จ",
                "ขอบคุณสำหรับการสนับสนุนเรา\n\n"
                "หลังจากตรวจสอบข้อมูลถูกต้องแล้ว\n"
                "ข้อมูลการสนับสนุนของคุณจะขึ้นบนหน้านี้",
            )
            self.accept()
        else:
            QMessageBox.critical(self, "❌ ส่งไม่สำเร็จ", result.get("error", "เกิดข้อผิดพลาดไม่ทราบสาเหตุ"))

    def closeEvent(self, event):
        if self._thread and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(3000)
        super().closeEvent(event)


class _FetchThread(QThread):
    done = Signal(dict)

    def run(self):
        try:
            result = fetch_supporters()
        except Exception as e:
            result = {"ok": False, "error": str(e)}
        self.done.emit(result)


class SupportersDialog(QDialog):
    """หน้าต่างสนับสนุน — QR code สแกนบริจาค + รายชื่อผู้สนับสนุน + ปุ่มส่งหลักฐาน"""

    def __init__(self, parent=None, api_url: str = SUPPORTERS_API_URL):
        super().__init__(parent)
        self._api_url = api_url
        self._fetch_thread = None
        self._loading = False

        self.setWindowTitle("💚 สนับสนุน GameVault by MeN9CH")
        self.setModal(True)
        self.resize(560, 700)
        self.setStyleSheet(_DIALOG_STYLESHEET)

        self._build_ui()
        self._reload()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 16)
        layout.setSpacing(10)

        title = QLabel("💚 สนับสนุน GameVault by MeN9CH")
        title.setProperty("role", "title")
        layout.addWidget(title)

        subtitle = QLabel("สแกน QR เพื่อบริจาค แล้วกด \"ส่งหลักฐานการสนับสนุน\" เพื่อให้ชื่อขึ้นในรายชื่อด้านล่าง")
        subtitle.setProperty("role", "subtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        qr_row = QHBoxLayout()
        qr_row.setSpacing(12)
        qr_row.addWidget(self._make_qr_card("promptpay_qr.png", "🏦 PromptPay"))
        qr_row.addWidget(self._make_qr_card("truemoney_qr.png", "💵 True Money"))
        layout.addLayout(qr_row)

        btn_submit = QPushButton("💚 ส่งหลักฐานการสนับสนุน")
        btn_submit.setObjectName("Primary")
        btn_submit.setMinimumHeight(40)
        btn_submit.clicked.connect(self._open_upload)
        layout.addWidget(btn_submit)

        list_label = QLabel("รายชื่อผู้สนับสนุน")
        list_label.setProperty("role", "section-label")
        layout.addWidget(list_label)

        status_row = QHBoxLayout()
        self.status_label = QLabel("")
        self.status_label.setProperty("role", "hint")
        status_row.addWidget(self.status_label, 1)
        self.btn_reload = QPushButton("🔄")
        self.btn_reload.setFixedWidth(36)
        self.btn_reload.setToolTip("โหลดรายชื่อใหม่")
        self.btn_reload.clicked.connect(self._reload)
        status_row.addWidget(self.btn_reload)
        layout.addLayout(status_row)

        self.list_container = QWidget()
        self.list_layout = QVBoxLayout(self.list_container)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(6)
        self.list_layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.list_container)
        scroll.setStyleSheet("QScrollArea { border: 1px solid #334155; border-radius: 8px; background: #0b1220; }")
        layout.addWidget(scroll, 1)

        btn_close = QPushButton("ปิด")
        btn_close.setObjectName("Secondary")
        btn_close.clicked.connect(self.accept)
        layout.addWidget(btn_close)

    def _make_qr_card(self, filename: str, title: str) -> QWidget:
        card = QFrame()
        card.setStyleSheet("QFrame { background: #1e293b; border: 1px solid #334155; border-radius: 8px; }")
        col = QVBoxLayout(card)
        col.setContentsMargins(10, 10, 10, 10)
        col.setSpacing(6)

        lbl_title = QLabel(title)
        lbl_title.setAlignment(Qt.AlignCenter)
        lbl_title.setStyleSheet("font-size: 13px; font-weight: 700; color: #f59e0b; background: transparent; border: none;")
        col.addWidget(lbl_title)

        qr_path = os.path.join(ASSETS_DIR, filename)
        img_lbl = QLabel()
        img_lbl.setAlignment(Qt.AlignCenter)
        pix = QPixmap(qr_path)
        if not pix.isNull():
            img_lbl.setPixmap(pix.scaled(200, 200, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            img_lbl.setCursor(Qt.PointingHandCursor)
            img_lbl.setToolTip("คลิกเพื่อดูขนาดเต็ม")
            img_lbl.mousePressEvent = lambda _e, f=filename, t=title: self._show_qr_full(f, t)
        else:
            img_lbl.setText("(ไม่พบไฟล์ QR)")
            img_lbl.setStyleSheet("color: #64748b; background: transparent; border: none;")
        col.addWidget(img_lbl)
        return card

    def _show_qr_full(self, filename: str, title: str):
        qr_path = os.path.join(ASSETS_DIR, filename)
        pix = QPixmap(qr_path)
        if pix.isNull():
            return
        popup = QDialog(self)
        popup.setWindowTitle(f"QR {title}")
        popup.setModal(True)
        pop_layout = QVBoxLayout(popup)
        pop_layout.setContentsMargins(24, 24, 24, 16)
        pop_layout.setSpacing(12)

        title_lbl = QLabel(f"💳 {title}")
        title_lbl.setAlignment(Qt.AlignCenter)
        title_lbl.setStyleSheet("font-size: 14px; font-weight: 700; color: #f59e0b;")
        pop_layout.addWidget(title_lbl)

        img_lbl = QLabel()
        img_lbl.setPixmap(pix)
        img_lbl.setAlignment(Qt.AlignCenter)
        img_lbl.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        img_lbl.setFixedSize(pix.size())
        pop_layout.addWidget(img_lbl)

        btn_close = QPushButton("ปิด")
        btn_close.setMinimumHeight(36)
        btn_close.clicked.connect(popup.accept)
        pop_layout.addWidget(btn_close)

        popup.setFixedSize(pix.width() + 48, pix.height() + 130)
        popup.exec()

    def _open_upload(self):
        dlg = SupporterUploadDialog(self, api_url=self._api_url)
        if dlg.exec() == QDialog.Accepted:
            self._reload()

    def _reload(self):
        # Rapid repeat clicks used to spawn overlapping fetch threads that
        # stomped on the same list widgets from two threads at once - hang,
        # then a crash. Ignore new clicks until the current fetch lands.
        if self._loading:
            return
        self._loading = True
        self.btn_reload.setEnabled(False)
        self.status_label.setText("⏳ กำลังโหลดรายชื่อผู้สนับสนุน...")
        self._fetch_thread = _FetchThread()
        self._fetch_thread.done.connect(self._on_fetched)
        self._fetch_thread.start()

    def _on_fetched(self, result: dict):
        self._loading = False
        self.btn_reload.setEnabled(True)
        while self.list_layout.count() > 1:
            item = self.list_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        if not result.get("ok"):
            self.status_label.setText(f"❌ โหลดไม่สำเร็จ: {result.get('error', 'ไม่ทราบสาเหตุ')}")
            return

        supporters = result.get("supporters", [])
        if not supporters:
            self.status_label.setText("ยังไม่มีผู้สนับสนุน — เป็นคนแรกได้เลย!")
            return

        try:
            supporters = sorted(supporters, key=lambda s: float(s.get("amount") or 0), reverse=True)
        except Exception:
            pass

        self.status_label.setText(f"✅ {len(supporters)} ผู้สนับสนุน")

        for idx, sup in enumerate(supporters):
            if not isinstance(sup, dict):
                continue
            row = self._make_row(sup, idx)
            self.list_layout.insertWidget(self.list_layout.count() - 1, row)

    def _make_row(self, sup: dict, idx: int) -> QWidget:
        name = str(sup.get("name", "ผู้สนับสนุน")).strip() or "ผู้สนับสนุน"
        amount = sup.get("amount", 0)
        currency = str(sup.get("currency", "THB")).upper()
        date = str(sup.get("date", "")).strip()
        message = str(sup.get("message", "")).strip()

        tier = get_tier(amount, currency)
        amount_str = format_amount(amount, currency)
        bg = "#1a1f2e" if idx % 2 == 0 else "#1f2937"

        row = QFrame()
        row.setStyleSheet(f"QFrame {{ background: {bg}; border: none; border-radius: 6px; }}")
        col = QVBoxLayout(row)
        col.setContentsMargins(12, 8, 12, 8)
        col.setSpacing(2)

        top = QHBoxLayout()
        name_lbl = QLabel(f"{tier['icon']} {name}")
        name_lbl.setStyleSheet("font-size: 13px; font-weight: 700; color: #f3f4f6; background: transparent; border: none;")
        top.addWidget(name_lbl, 1)
        amount_lbl = QLabel(amount_str)
        amount_lbl.setStyleSheet("font-size: 13px; font-weight: 700; color: #10b981; background: transparent; border: none;")
        top.addWidget(amount_lbl)
        col.addLayout(top)

        if message or date:
            bottom = QLabel(" · ".join(p for p in [message, date] if p))
            bottom.setStyleSheet("font-size: 11px; color: #94a3b8; background: transparent; border: none;")
            bottom.setWordWrap(True)
            col.addWidget(bottom)

        return row

    def closeEvent(self, event):
        if self._fetch_thread and self._fetch_thread.isRunning():
            self._fetch_thread.quit()
            self._fetch_thread.wait(3000)
        super().closeEvent(event)
