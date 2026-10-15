"""supporter_dialog.py — Donate window for MeN9CH Applications

- SupportersDialog: QR codes to scan, list of supporters with origin badges and
  platform links (fetched from the shared MeN9CH API so it matches every MeN9CH app/website),
  sort toggles (newest date / amount), and buttons to open donation forms.
- SupporterUploadDialog: Bank transfer / PromptPay proof-of-donation form (slip / manual).
- TrueMoneyVoucherDialog: TrueMoney 2-step automated gift voucher flow.
"""
from __future__ import annotations

import os
import sys
import math

from PySide6.QtCore import Qt, QThread, Signal, QDate, QTime, QUrl, QSize
from PySide6.QtGui import QPixmap, QIcon, QDesktopServices
from PySide6.QtWidgets import (
    QDialog, QWidget, QFrame, QLabel, QPushButton, QLineEdit, QVBoxLayout,
    QHBoxLayout, QFormLayout, QFileDialog, QMessageBox, QComboBox, QDoubleSpinBox,
    QProgressBar, QTextEdit, QDateEdit, QTimeEdit, QButtonGroup, QRadioButton,
    QScrollArea, QSizePolicy,
)

from supporters_api import (
    fetch_supporters, format_amount, SUPPORTERS_API_URL,
    redeem_truemoney_voucher, complete_truemoney_supporter,
)

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

PLATFORMS = [
    ("", "— ไม่ระบุ —", None),
    ("facebook", "Facebook", "facebook.png"),
    ("x", "X (Twitter)", "x.png"),
    ("youtube", "YouTube", "youtube.png"),
    ("twitch", "Twitch", "twitch.png"),
    ("tiktok", "TikTok", "tiktok.png"),
    ("soop", "SOOP", "soop.png"),
    ("mylive", "MyLive", "mylive.png"),
    ("kick", "Kick", "kick.png"),
    ("other", "เว็บไซต์ / อื่นๆ", "homepage.png"),
]


def _populate_platform_combo(combo: QComboBox):
    """เติมรายชื่อแพลตฟอร์มพร้อมไอคอน PNG จริง (ไม่ใช่วงกลมสี)"""
    combo.setIconSize(QSize(16, 16))
    for code, label, icon_file in PLATFORMS:
        if icon_file:
            icon_path = os.path.join(ASSETS_DIR, icon_file)
            if os.path.exists(icon_path):
                combo.addItem(QIcon(icon_path), label, code)
                continue
        combo.addItem(label, code)


_DIALOG_STYLESHEET = """
    QDialog { background-color: #0f172a; color: #f8fafc; }
    QLabel { color: #f8fafc; }
    QLabel[role="title"] { font-size: 20px; font-weight: 600; color: #ffffff; }
    QLabel[role="subtitle"] { color: #cbd5e1; font-size: 12.5px; }
    QLabel[role="section-label"] { color: #34d399; font-size: 16px; font-weight: 600; margin-top: 6px; }
    QLabel[role="field-label"] { color: #cbd5e1; font-size: 12px; font-weight: 700; }
    QLabel[role="hint"] { color: #94a3b8; font-size: 11.5px; font-weight: 600; }
    QLabel[role="filename"] { color: #34d399; font-size: 12px; font-weight: 700; }
    QLineEdit, QTextEdit, QDoubleSpinBox, QComboBox, QDateEdit, QTimeEdit {
        background-color: #1e293b; border: 1.5px solid #334155; border-radius: 0px;
        padding: 8px 10px; color: #f8fafc; font-size: 13px;
    }
    QLineEdit:focus, QTextEdit:focus, QDoubleSpinBox:focus, QComboBox:focus,
    QDateEdit:focus, QTimeEdit:focus { border-color: #10b981; }
    QComboBox::drop-down { border: none; }
    QComboBox QAbstractItemView { background-color: #1e293b; color: #f8fafc; selection-background-color: #059669; }
    QPushButton#Primary {
        background-color: #10b981; color: white; font-weight: 700; font-size: 13px;
        border: none; border-radius: 0px; padding: 12px;
    }
    QPushButton#Primary:hover { background-color: #059669; }
    QPushButton#Primary:disabled { background-color: #334155; color: #64748b; }
    QPushButton#Secondary {
        background-color: #1e293b; color: #cbd5e1; font-weight: 600; font-size: 13px;
        border: 1px solid #334155; border-radius: 0px; padding: 10px;
    }
    QPushButton#Secondary:hover { background-color: #334155; color: #ffffff; }
    QPushButton#FileDrop {
        background-color: #1e293b; border: 2px dashed #475569; border-radius: 0px;
        color: #94a3b8; padding: 18px; font-size: 13px; text-align: center;
    }
    QPushButton#FileDrop:hover { border-color: #10b981; background-color: #064e3b; color: #34d399; }
    QRadioButton { color: #e2e8f0; font-size: 13px; padding: 6px; }
    QRadioButton::indicator { width: 16px; height: 16px; }
    QRadioButton::indicator:unchecked { border: 2px solid #64748b; border-radius: 0px; background: #1e293b; }
    QRadioButton::indicator:checked { border: 2px solid #10b981; border-radius: 0px; background: #10b981; }
    QProgressBar {
        background-color: #1e293b; border: 1px solid #334155; border-radius: 0px;
        text-align: center; color: #e2e8f0; height: 6px;
    }
    QProgressBar::chunk { background-color: #10b981; border-radius: 0px; }
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


class _RedeemTMThread(QThread):
    finished_sig = Signal(dict)

    def __init__(self, voucher_url: str, api_url: str):
        super().__init__()
        self.voucher_url = voucher_url
        self.api_url = api_url

    def run(self):
        try:
            from supporters_api import redeem_truemoney_voucher
            result = redeem_truemoney_voucher(self.voucher_url, api_url=self.api_url)
            self.finished_sig.emit(result)
        except Exception as e:
            self.finished_sig.emit({"ok": False, "error": f"เกิดข้อผิดพลาด: {e}"})


class _CompleteTMThread(QThread):
    finished_sig = Signal(dict)

    def __init__(self, tx_id: str, name: str, channel_url: str, message: str, platform: str, source: str, api_url: str):
        super().__init__()
        self.tx_id = tx_id
        self.name = name
        self.channel_url = channel_url
        self.message = message
        self.platform = platform
        self.source = source
        self.api_url = api_url

    def run(self):
        try:
            from supporters_api import complete_truemoney_supporter
            result = complete_truemoney_supporter(
                tx_id=self.tx_id,
                name=self.name,
                channel_url=self.channel_url,
                message=self.message,
                platform=self.platform,
                source=self.source,
                api_url=self.api_url,
            )
            self.finished_sig.emit(result)
        except Exception as e:
            self.finished_sig.emit({"ok": False, "error": f"เกิดข้อผิดพลาด: {e}"})


class SupporterUploadDialog(QDialog):
    """ฟอร์มแจ้งโอนเงินธนาคาร / แนบสลิป — สำหรับผู้โอนผ่าน พร้อมเพย์ หรือ บัญชีธนาคาร"""

    def __init__(self, parent=None, app_name: str = "Sprite Cropper by MeN9CH", api_url: str = SUPPORTERS_API_URL):
        super().__init__(parent)
        self._app_name = app_name
        self._api_url = api_url
        self._slip_path = None
        self._thread = None

        self.setWindowTitle("💚 แจ้งโอนเงินธนาคาร / แนบสลิป")
        self.setModal(True)
        self.setMinimumWidth(480)
        self.setStyleSheet(_DIALOG_STYLESHEET)

        self._build_ui()
        self._on_method_change()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(8)

        title = QLabel("💚 แจ้งโอนเงินพร้อมเพย์ / บัญชีธนาคาร")
        title.setProperty("role", "title")
        title.setToolTip(f"ขอบคุณที่สนับสนุน {self._app_name}")
        layout.addWidget(title)

        method_row = QHBoxLayout()
        method_row.setSpacing(10)
        self.method_label = QLabel("รูปแบบหลักฐาน:")
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

        # Bank Slip Fields
        self.slip_label = QLabel("📷 สลิป (PNG/JPG/WebP/GIF ≤5MB):")
        self.slip_label.setProperty("role", "field-label")
        layout.addWidget(self.slip_label)

        slip_row = QHBoxLayout()
        self.btn_file = QPushButton("📎 เลือกไฟล์รูปสลิป...")
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

        # Form Layout
        self.form = QFormLayout()
        self.form.setContentsMargins(0, 4, 0, 4)
        self.form.setSpacing(8)
        self.form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        layout.addLayout(self.form)

        self.bank_label = QLabel("🏦 ธนาคาร:")
        self.bank_combo = QComboBox()
        for code, name in BANKS:
            self.bank_combo.addItem(f"{code} — {name}", code)
        self.form.addRow(self.bank_label, self.bank_combo)

        self.datetime_label = QLabel("🕐 วันที่/เวลาโอน:")
        self.datetime_field = QWidget()
        datetime_row = QHBoxLayout(self.datetime_field)
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
        self.form.addRow(self.datetime_label, self.datetime_field)

        self.amount_field = QWidget()
        amount_row = QHBoxLayout(self.amount_field)
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
        self.form.addRow("💰 จำนวนเงิน:", self.amount_field)

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("เช่น คุณAAA, ผู้สนับสนุนใจดี")
        self.name_input.setMaxLength(50)
        self.form.addRow("👤 ชื่อที่แสดง:", self.name_input)

        self.platform_field = QWidget()
        platform_row = QHBoxLayout(self.platform_field)
        platform_row.setContentsMargins(0, 0, 0, 0)
        self.platform_combo = QComboBox()
        _populate_platform_combo(self.platform_combo)
        platform_row.addWidget(self.platform_combo, 1)
        self.channel_url_input = QLineEdit()
        self.channel_url_input.setPlaceholderText("ลิงก์ช่องโปรโมทตัวเอง (ไม่บังคับ)")
        platform_row.addWidget(self.channel_url_input, 2)
        self.form.addRow("📺 โปรโมตช่อง:", self.platform_field)

        self.message_input = QTextEdit()
        self.message_input.setPlaceholderText("สู้ๆครับ / ขอบคุณสำหรับโปรแกรมดีๆ (ไม่บังคับ)")
        self.message_input.setMaximumHeight(50)
        self.form.addRow("💬 ข้อความ:", self.message_input)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.progress.setTextVisible(False)
        layout.addWidget(self.progress)

        btn_row = QHBoxLayout()
        self.btn_cancel = QPushButton("ยกเลิก")
        self.btn_cancel.setObjectName("Secondary")
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_submit = QPushButton("ส่งหลักฐาน ✉️")
        self.btn_submit.setObjectName("Primary")
        self.btn_submit.clicked.connect(self._on_submit)
        btn_row.addWidget(self.btn_cancel)
        btn_row.addWidget(self.btn_submit, 1)
        layout.addLayout(btn_row)

        warning = QLabel("⚠️ ส่งข้อมูลเท็จ ระบบจะแบนไม่ให้ใช้งานโปรแกรม")
        warning.setAlignment(Qt.AlignCenter)
        warning.setStyleSheet(
            "font-size: 10px; color: #ef4444; "
            "background: rgba(239, 68, 68, 0.08); "
            "border: 1px solid rgba(239, 68, 68, 0.3); "
            "border-radius: 0px; padding: 4px;"
        )
        layout.addWidget(warning)

    def _on_method_change(self):
        is_slip = self.rb_slip.isChecked()
        self._show_slip_fields(is_slip)
        self.form.setRowVisible(self.bank_combo, not is_slip)
        self.form.setRowVisible(self.datetime_field, not is_slip)

    def _show_slip_fields(self, show: bool):
        for w in [self.slip_label, self.btn_file, self.filename_label, self.slip_preview]:
            w.setVisible(show)
        if not show:
            self._slip_path = None
            self.filename_label.setText("")

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
            "channel": "bank",
            "source": self._app_name,
        }

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

        return payload

    def _on_submit(self):
        payload = self._build_payload()
        if payload is None:
            return

        channel_text = "ธนาคาร (แนบสลิป)" if payload.get("method") == "slip" else f"ธนาคาร ({payload.get('bank', '?')})"
        reply = QMessageBox.question(
            self, "ยืนยันการส่ง",
            f"ยืนยันส่งข้อมูลการสนับสนุน?\n\n"
            f"ช่องทาง: {channel_text}\n"
            f"จำนวน: {payload['amount']} {payload['currency']}\n"
            f"ชื่อ: {payload['name']}\n"
            f"ที่มา: {self._app_name}",
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
        self.btn_submit.setText("ส่งหลักฐาน ✉️")
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
            self._thread.wait(2000)
        super().closeEvent(event)


class TrueMoneyVoucherDialog(QDialog):
    """ฟอร์มส่งซองของขวัญ TrueMoney — ระบบอัตโนมัติ 2 สเต็ป (ตรวจรับเงินทันที ➔ กรอกรายละเอียด)"""

    def __init__(self, parent=None, app_name: str = "Sprite Cropper by MeN9CH", api_url: str = SUPPORTERS_API_URL):
        super().__init__(parent)
        self._app_name = app_name
        self._api_url = api_url
        self._redeem_thread = None
        self._complete_thread = None
        self._tx_id = None
        self._amount = 0.0
        self._currency = "THB"

        self.setWindowTitle("🍊 ส่งซอง TrueMoney (ตรวจรับเงินทันที)")
        self.setModal(True)
        self.setMinimumWidth(480)
        self.setStyleSheet(_DIALOG_STYLESHEET)

        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(8)

        title = QLabel("🍊 ส่งซอง TrueMoney")
        title.setProperty("role", "title")
        title.setStyleSheet("font-size: 17px; font-weight: 700; color: #ea580c;")
        title.setToolTip(f"ขอบคุณที่สนับสนุน {self._app_name}")
        layout.addWidget(title)

        # Step 1 Container
        self.step1_widget = QWidget()
        s1_layout = QVBoxLayout(self.step1_widget)
        s1_layout.setContentsMargins(0, 2, 0, 4)
        s1_layout.setSpacing(8)

        guide = QFrame()
        guide.setStyleSheet("QFrame { background: #1c1917; border: 1px solid #78350f; border-radius: 0px; }")
        g_layout = QVBoxLayout(guide)
        g_layout.setContentsMargins(12, 10, 12, 10)
        g_layout.setSpacing(4)
        g_title = QLabel("⚡ ระบบตรวจรับเงินอัตโนมัติ")
        g_title.setStyleSheet("font-size: 12.5px; font-weight: 700; color: #f97316; background: transparent; border: none;")
        g_layout.addWidget(g_title)
        g_steps = QLabel("1. เปิดแอป TrueMoney ➔ เมนู \"ส่งซองทรูมันนี่\"\n2. เลือก \"ส่งให้คนเดียว\" ➔ ระบุจำนวนเงินที่ต้องการส่ง\n3. คัดลอกลิงก์ซองของขวัญมาวางในช่องด้านล่าง")
        g_steps.setStyleSheet("font-size: 11.5px; color: #cbd5e1; background: transparent; border: none; line-height: 1.45;")
        g_layout.addWidget(g_steps)
        s1_layout.addWidget(guide)

        self.voucher_input = QLineEdit()
        self.voucher_input.setPlaceholderText("วางลิงก์ซอง https://gift.truemoney.com/campaign/?v=...")
        self.voucher_input.returnPressed.connect(self._on_redeem)
        s1_layout.addWidget(self.voucher_input)

        self.btn_redeem = QPushButton("⚡ ตรวจสอบและรับเงินสนับสนุน")
        self.btn_redeem.setCursor(Qt.PointingHandCursor)
        self.btn_redeem.setStyleSheet(
            "QPushButton { background: linear-gradient(135deg, #f97316, #ea580c); color: white; font-weight: 700; font-size: 13px; "
            "border: none; border-radius: 0px; padding: 11px; }"
            "QPushButton:hover { background: #c2410c; }"
            "QPushButton:disabled { background: #334155; color: #64748b; }"
        )
        self.btn_redeem.clicked.connect(self._on_redeem)
        s1_layout.addWidget(self.btn_redeem)
        layout.addWidget(self.step1_widget)

        # Step 2 Container (Success Banner & Thank You)
        self.step2_widget = QWidget()
        s2_layout = QVBoxLayout(self.step2_widget)
        s2_layout.setContentsMargins(0, 2, 0, 4)
        s2_layout.setSpacing(6)

        chibi_lbl = QLabel()
        chibi_lbl.setAlignment(Qt.AlignCenter)
        chibi_path = os.path.join(ASSETS_DIR, "supporter_thankyou.png")
        chibi_pix = QPixmap(chibi_path)
        if not chibi_pix.isNull():
            chibi_lbl.setPixmap(chibi_pix.scaledToHeight(90, Qt.SmoothTransformation))
        s2_layout.addWidget(chibi_lbl)

        self.thankyou_text = QLabel("เราได้รับยอดเงินสนับสนุนของคุณแล้ว ขอขอบพระคุณเป็นอย่างสูง")
        self.thankyou_text.setAlignment(Qt.AlignCenter)
        self.thankyou_text.setStyleSheet("font-size: 13.5px; font-weight: 800; color: #10b981;")
        self.thankyou_text.setWordWrap(True)
        s2_layout.addWidget(self.thankyou_text)

        self.amount_badge = QLabel("💰 ได้รับยอดเงินสนับสนุน: — (ตรวจอัตโนมัติสำเร็จ)")
        self.amount_badge.setAlignment(Qt.AlignCenter)
        self.amount_badge.setStyleSheet("font-size: 12.5px; font-weight: 700; color: #f59e0b;")
        s2_layout.addWidget(self.amount_badge)
        layout.addWidget(self.step2_widget)
        self.step2_widget.setVisible(False)

        # Step 2 Supporter Info Form
        self.form_widget = QWidget()
        self.form = QFormLayout(self.form_widget)
        self.form.setContentsMargins(0, 4, 0, 4)
        self.form.setSpacing(8)
        self.form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("ชื่อหรือฉายาของคุณ *")
        self.name_input.setMaxLength(50)
        self.form.addRow("👤 ชื่อที่แสดง:", self.name_input)

        platform_field = QWidget()
        p_row = QHBoxLayout(platform_field)
        p_row.setContentsMargins(0, 0, 0, 0)
        self.platform_combo = QComboBox()
        _populate_platform_combo(self.platform_combo)
        p_row.addWidget(self.platform_combo, 1)
        self.channel_url_input = QLineEdit()
        self.channel_url_input.setPlaceholderText("ลิงก์ช่องโปรโมทตัวเอง (ไม่บังคับ)")
        p_row.addWidget(self.channel_url_input, 2)
        self.form.addRow("📺 โปรโมตช่อง:", platform_field)

        self.message_input = QTextEdit()
        self.message_input.setPlaceholderText("ข้อความส่งถึงเรา (ไม่บังคับ)")
        self.message_input.setMaximumHeight(50)
        self.form.addRow("💬 ข้อความ:", self.message_input)
        layout.addWidget(self.form_widget)
        self.form_widget.setVisible(False)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.progress.setTextVisible(False)
        layout.addWidget(self.progress)

        btn_row = QHBoxLayout()
        self.btn_cancel = QPushButton("ยกเลิก")
        self.btn_cancel.setObjectName("Secondary")
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_submit = QPushButton("✨ บันทึกและขึ้นรายชื่อทันที")
        self.btn_submit.setObjectName("Primary")
        self.btn_submit.clicked.connect(self._on_complete)
        self.btn_submit.setVisible(False)
        btn_row.addWidget(self.btn_cancel)
        btn_row.addWidget(self.btn_submit, 1)
        layout.addLayout(btn_row)

    def _on_redeem(self):
        url = self.voucher_input.text().strip()
        if not url:
            QMessageBox.warning(self, "ข้อมูลไม่ครบ", "กรุณาวางลิงก์ซองของขวัญ TrueMoney")
            self.voucher_input.setFocus()
            return

        if "gift.truemoney.com" not in url:
            QMessageBox.warning(
                self, "ลิงก์ไม่ถูกต้อง",
                "กรุณาใช้ลิงก์ซองของขวัญจาก TrueMoney\n(ขึ้นต้นด้วย https://gift.truemoney.com/...)"
            )
            return

        self.btn_redeem.setEnabled(False)
        self.btn_redeem.setText("⚡ กำลังตรวจสอบและดึงเงิน...")
        self.progress.setVisible(True)
        self.progress.setValue(0)

        self._redeem_thread = _RedeemTMThread(url, self._api_url)
        self._redeem_thread.finished_sig.connect(self._on_redeemed)
        self._redeem_thread.start()

    def _on_redeemed(self, result: dict):
        self.btn_redeem.setEnabled(True)
        self.btn_redeem.setText("⚡ ตรวจสอบและรับเงินสนับสนุน")
        self.progress.setVisible(False)

        if not result.get("ok"):
            err = result.get("error", "ไม่สามารถดึงเงินจากซองได้ กรุณาตรวจสอบลิงก์อีกครั้ง")
            QMessageBox.critical(self, "❌ รับยอดเงินไม่สำเร็จ", err)
            return

        self._tx_id = result.get("tx_id")
        self._amount = float(result.get("amount") or 0)
        self._currency = result.get("currency", "THB")

        amt_str = format_amount(self._amount, self._currency)
        self.amount_badge.setText(f"💰 ได้รับยอดเงินสนับสนุน: {amt_str} (ตรวจสอบสำเร็จ)")

        # Switch to Step 2
        self.step1_widget.setVisible(False)
        self.step2_widget.setVisible(True)
        self.form_widget.setVisible(True)
        self.btn_submit.setVisible(True)
        self.btn_cancel.setText("เสร็จสิ้น / ปิด")
        self.name_input.setFocus()

    def _on_complete(self):
        name = self.name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "ข้อมูลไม่ครบ", "กรุณาระบุชื่อที่ต้องการให้แสดงบนรายการผู้สนับสนุน")
            self.name_input.setFocus()
            return

        platform = self.platform_combo.currentData() or ""
        channel_url = self.channel_url_input.text().strip()
        message = self.message_input.toPlainText().strip()[:200]

        self.btn_submit.setEnabled(False)
        self.btn_submit.setText("กำลังบันทึกข้อมูล...")
        self.progress.setVisible(True)
        self.progress.setValue(0)

        self._complete_thread = _CompleteTMThread(
            tx_id=self._tx_id,
            name=name,
            channel_url=channel_url,
            message=message,
            platform=platform,
            source=self._app_name,
            api_url=self._api_url,
        )
        self._complete_thread.finished_sig.connect(self._on_completed)
        self._complete_thread.start()

    def _on_completed(self, result: dict):
        self.btn_submit.setEnabled(True)
        self.btn_submit.setText("✨ บันทึกและขึ้นรายชื่อทันที")
        self.progress.setVisible(False)

        if result.get("ok"):
            QMessageBox.information(
                self, "🎉 ขึ้นรายชื่อสำเร็จ",
                f"ขอบพระคุณสำหรับการสนับสนุน {self._amount} {self._currency} ครับ!\n\n"
                f"ชื่อ: {self.name_input.text().strip()}\n"
                f"ที่มา: {self._app_name}\n\n"
                "ระบบได้นำชื่อของคุณขึ้นบนหน้ารายชื่อผู้สนับสนุนเรียบร้อยแล้ว",
            )
            self.accept()
        else:
            err = result.get("error", "ไม่สามารถบันทึกข้อมูลได้")
            QMessageBox.warning(self, "บันทึกข้อมูลไม่สำเร็จ", err)

    def closeEvent(self, event):
        if self._redeem_thread and self._redeem_thread.isRunning():
            self._redeem_thread.quit()
            self._redeem_thread.wait(2000)
        if self._complete_thread and self._complete_thread.isRunning():
            self._complete_thread.quit()
            self._complete_thread.wait(2000)
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
    """หน้าต่างสนับสนุน — QR code สแกนบริจาค + รายชื่อผู้สนับสนุน (เท่าเทียม ไม่จัด Ranking) + ปุ่มส่งหลักฐาน"""

    def __init__(self, parent=None, app_name: str = "GameVault by MeN9CH", api_url: str = SUPPORTERS_API_URL):
        super().__init__(parent)
        self._app_name = app_name
        self._api_url = api_url
        self._fetch_thread = None
        self._loading = False
        self._sort_mode = "date"  # "date" (default ล่าสุด) หรือ "amount" (ยอดเงิน)
        self._current_page = 1
        self._per_page = 5
        self._total_pages = 1
        self._supporters_data: list = []

        self.setWindowTitle(f"💚 สนับสนุน {self._app_name}")
        self.setModal(True)
        self.resize(560, 720)
        self.setStyleSheet(_DIALOG_STYLESHEET)

        self._build_ui()
        self._reload()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(11)

        title_box = QVBoxLayout()
        title_box.setSpacing(3)
        lbl_title = QLabel(f"💚 สนับสนุน {self._app_name}")
        lbl_title.setStyleSheet("font-size: 19px; font-weight: 600; color: #ffffff;")
        lbl_sub = QLabel("ร่วมสนับสนุนการพัฒนาโปรแกรม รายชื่อจะอัปเดตแสดงบนหน้านี้ทันที")
        lbl_sub.setStyleSheet("font-size: 12px; color: #94a3b8;")
        title_box.addWidget(lbl_title)
        title_box.addWidget(lbl_sub)
        layout.addLayout(title_box)

        # 1. TrueMoney Strip
        layout.addWidget(self._make_horizontal_tm_card())

        # 2. PromptPay Combo Strip
        layout.addWidget(self._make_promptpay_combo())

        # Header for Supporters Wall with Sort controls
        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 4, 0, 0)
        list_label = QLabel("รายชื่อผู้สนับสนุน")
        list_label.setStyleSheet("font-size: 15px; font-weight: 600; color: #34d399;")
        header_row.addWidget(list_label, 1)

        # Sort Pills (Date vs Amount)
        self.btn_sort_date = QPushButton("📅 ล่าสุด")
        self.btn_sort_date.setCursor(Qt.PointingHandCursor)
        self.btn_sort_date.clicked.connect(lambda: self._set_sort_mode("date"))

        self.btn_sort_amount = QPushButton("💰 ยอดเงิน")
        self.btn_sort_amount.setCursor(Qt.PointingHandCursor)
        self.btn_sort_amount.clicked.connect(lambda: self._set_sort_mode("amount"))

        self._update_sort_button_styles()

        header_row.addWidget(self.btn_sort_date)
        header_row.addWidget(self.btn_sort_amount)

        self.btn_reload = QPushButton("🔄")
        self.btn_reload.setFixedWidth(30)
        self.btn_reload.setToolTip("โหลดรายชื่อใหม่")
        self.btn_reload.clicked.connect(self._reload)
        self.btn_reload.setStyleSheet("background: #1e293b; color: #cbd5e1; border: 1px solid #334155; border-radius: 0px; padding: 3px;")
        header_row.addWidget(self.btn_reload)
        layout.addLayout(header_row)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("font-size: 11.5px; color: #94a3b8;")
        layout.addWidget(self.status_label)

        self.list_container = QWidget()
        self.list_container.setStyleSheet("background: transparent;")
        self.list_layout = QVBoxLayout(self.list_container)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(6)
        self.list_layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.list_container)
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 0px; } "
            "QScrollBar:vertical { background: #0c121e; width: 6px; margin: 0px; } "
            "QScrollBar::handle:vertical { background: #334155; border-radius: 0px; min-height: 20px; }"
        )
        layout.addWidget(scroll, 1)

        # Pagination Bar (Next / Prev / Page Count)
        self.pagination_bar = QHBoxLayout()
        self.pagination_bar.setContentsMargins(0, 2, 0, 2)
        self.pagination_bar.setSpacing(8)

        self.btn_prev = QPushButton("◀ ก่อนหน้า")
        self.btn_prev.setCursor(Qt.PointingHandCursor)
        self.btn_prev.setStyleSheet(
            "QPushButton { background: #141c2e; color: #94a3b8; border: 1px solid rgba(255, 255, 255, 0.1); "
            "border-radius: 0px; padding: 5px 12px; font-size: 11px; } "
            "QPushButton:hover:!disabled { background: #334155; border-color: #38bdf8; color: #38bdf8; } "
            "QPushButton:disabled { color: #64748b; background: rgba(30, 41, 59, 0.4); border-color: rgba(255, 255, 255, 0.05); }"
        )
        self.btn_prev.clicked.connect(self._prev_page)
        self.pagination_bar.addWidget(self.btn_prev)

        self.page_label = QLabel("หน้า 1 / 1")
        self.page_label.setAlignment(Qt.AlignCenter)
        self.page_label.setStyleSheet("font-size: 11.5px; color: #64748b; background: transparent; border: none;")
        self.pagination_bar.addWidget(self.page_label, 1)

        self.btn_next = QPushButton("ถัดไป ▶")
        self.btn_next.setCursor(Qt.PointingHandCursor)
        self.btn_next.setStyleSheet(
            "QPushButton { background: #141c2e; color: #94a3b8; border: 1px solid rgba(255, 255, 255, 0.1); "
            "border-radius: 0px; padding: 5px 12px; font-size: 11px; } "
            "QPushButton:hover:!disabled { background: #334155; border-color: #38bdf8; color: #38bdf8; } "
            "QPushButton:disabled { color: #64748b; background: rgba(30, 41, 59, 0.4); border-color: rgba(255, 255, 255, 0.05); }"
        )
        self.btn_next.clicked.connect(self._next_page)
        self.pagination_bar.addWidget(self.btn_next)

        layout.addLayout(self.pagination_bar)

        btn_close = QPushButton("ปิด")
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.setStyleSheet(
            "QPushButton { background: #1e293b; color: #cbd5e1; font-weight: 600; font-size: 12.5px; "
            "border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 0px; padding: 8px; } "
            "QPushButton:hover { background: #334155; color: #ffffff; }"
        )
        btn_close.clicked.connect(self.accept)
        layout.addWidget(btn_close)

    def _update_sort_button_styles(self):
        active_style = "background: #10b981; color: white; font-weight: 700; font-size: 11px; border-radius: 0px; padding: 4px 10px; border: none;"
        inactive_style = "background: #1e293b; color: #94a3b8; font-weight: 600; font-size: 11px; border-radius: 0px; padding: 4px 10px; border: 1px solid #334155;"
        self.btn_sort_date.setStyleSheet(active_style if self._sort_mode == "date" else inactive_style)
        self.btn_sort_amount.setStyleSheet(active_style if self._sort_mode == "amount" else inactive_style)

    def _prev_page(self):
        if self._current_page > 1:
            self._current_page -= 1
            self._render_supporters()

    def _next_page(self):
        if self._current_page < self._total_pages:
            self._current_page += 1
            self._render_supporters()

    def _set_sort_mode(self, mode: str):
        if self._sort_mode == mode:
            return
        self._sort_mode = mode
        self._current_page = 1
        self._update_sort_button_styles()
        self._render_supporters()

    def _make_horizontal_tm_card(self) -> QWidget:
        card = QFrame()
        card.setObjectName("TMCard")
        card.setStyleSheet(
            "QFrame#TMCard { background: #141c2e; border: 1px solid rgba(249, 115, 22, 0.35); "
            "border-left: 4px solid #f97316; border-radius: 0px; } "
            "QFrame#TMCard:hover { background: #172238; border-color: #f97316; }"
        )
        row = QHBoxLayout(card)
        row.setContentsMargins(14, 10, 14, 10)
        row.setSpacing(12)

        icon_lbl = QLabel("🍊")
        icon_lbl.setStyleSheet("font-size: 22px; background: transparent; border: none;")
        row.addWidget(icon_lbl)

        mid_col = QVBoxLayout()
        mid_col.setSpacing(2)

        lbl_title = QLabel("TrueMoney ส่งซองของขวัญ")
        lbl_title.setStyleSheet("font-size: 14px; font-weight: 600; color: #ffedd5; background: transparent; border: none;")
        mid_col.addWidget(lbl_title)

        desc = QLabel("ระบบส่งยอดสนับสนุนเข้าระบบอัตโนมัติ พร้อมขึ้นชื่อและโปรโมทช่องทันที")
        desc.setStyleSheet("font-size: 11px; color: #94a3b8; background: transparent; border: none;")
        mid_col.addWidget(desc)
        row.addLayout(mid_col, 1)

        btn_tm = QPushButton("ส่งซอง ➔")
        btn_tm.setCursor(Qt.PointingHandCursor)
        btn_tm.setStyleSheet(
            "QPushButton { background: #ea580c; color: white; font-weight: 700; font-size: 12px; "
            "border: none; border-radius: 0px; padding: 8px 16px; } "
            "QPushButton:hover { background: #c2410c; }"
        )
        btn_tm.clicked.connect(self._open_truemoney_voucher)
        row.addWidget(btn_tm)

        card.setCursor(Qt.PointingHandCursor)
        card.mousePressEvent = lambda _e: self._open_truemoney_voucher()
        return card

    def _make_promptpay_combo(self) -> QWidget:
        """PromptPay and Bank Transfer / Slip Notification seamlessly attached with 0 padding/gap"""
        container = QFrame()
        container.setObjectName("PPCard")
        container.setStyleSheet(
            "QFrame#PPCard { background: #141c2e; border: 1px solid rgba(56, 189, 248, 0.35); "
            "border-left: 4px solid #38bdf8; border-radius: 0px; }"
        )
        col = QVBoxLayout(container)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)

        # Upper row: PromptPay info & Open QR button
        upper = QWidget()
        upper.setCursor(Qt.PointingHandCursor)
        upper.mousePressEvent = lambda _e: self._show_qr_full("promptpay_qr.png", "พร้อมเพย์")
        pp_row = QHBoxLayout(upper)
        pp_row.setContentsMargins(14, 10, 14, 10)
        pp_row.setSpacing(12)

        icon_lbl = QLabel("📱")
        icon_lbl.setStyleSheet("font-size: 22px; background: transparent; border: none;")
        pp_row.addWidget(icon_lbl)

        mid_col = QVBoxLayout()
        mid_col.setSpacing(2)

        lbl_title = QLabel("พร้อมเพย์ (PromptPay)")
        lbl_title.setStyleSheet("font-size: 14px; font-weight: 600; color: #e0f2fe; background: transparent; border: none;")
        mid_col.addWidget(lbl_title)

        desc = QLabel("สแกน QR Code โอนเงินตรงถึงผู้พัฒนา ไม่โดนหักธรรมเนียม")
        desc.setStyleSheet("font-size: 11px; color: #94a3b8; background: transparent; border: none;")
        mid_col.addWidget(desc)
        pp_row.addLayout(mid_col, 1)

        btn_qr = QPushButton("เปิด QR ➔")
        btn_qr.setCursor(Qt.PointingHandCursor)
        btn_qr.setStyleSheet(
            "QPushButton { background: #0284c7; color: white; font-weight: 700; font-size: 12px; "
            "border: none; border-radius: 0px; padding: 8px 16px; } "
            "QPushButton:hover { background: #0369a1; }"
        )
        btn_qr.clicked.connect(lambda: self._show_qr_full("promptpay_qr.png", "พร้อมเพย์"))
        pp_row.addWidget(btn_qr)

        col.addWidget(upper)

        # Lower row: Bank Transfer / Slip Notification
        btn_slip = QPushButton("โอนผ่านธนาคาร / พร้อมเพย์แล้ว? แจ้งโอนเงิน / แนบสลิปที่นี่ ➔")
        btn_slip.setCursor(Qt.PointingHandCursor)
        btn_slip.setStyleSheet(
            "QPushButton { "
            "  background: rgba(56, 189, 248, 0.05); "
            "  color: #38bdf8; "
            "  font-weight: 600; "
            "  font-size: 11.5px; "
            "  border: none; "
            "  border-top: 1px solid rgba(56, 189, 248, 0.16); "
            "  border-radius: 0px; "
            "  padding: 8px 14px; "
            "  text-align: center; "
            "} "
            "QPushButton:hover { "
            "  background: rgba(56, 189, 248, 0.14); "
            "  color: #bae6fd; "
            "}"
        )
        btn_slip.clicked.connect(self._open_upload)
        col.addWidget(btn_slip)

        return container

    def _make_horizontal_promptpay_card(self) -> QWidget:
        card = QFrame()
        card.setStyleSheet(
            "QFrame { background: #1e293b; border: 1px solid rgba(255, 255, 255, 0.12); "
            "border-left: 4px solid #38bdf8; border-radius: 0px; }"
            "QFrame:hover { background: rgba(30, 41, 59, 0.95); border-color: #38bdf8; }"
        )
        row = QHBoxLayout(card)
        row.setContentsMargins(14, 10, 14, 10)
        row.setSpacing(12)

        icon_lbl = QLabel("📱 🏦")
        icon_lbl.setStyleSheet("font-size: 22px; background: transparent; border: none;")
        row.addWidget(icon_lbl)

        mid_col = QVBoxLayout()
        mid_col.setSpacing(2)

        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        lbl_title = QLabel("พร้อมเพย์")
        lbl_title.setStyleSheet("font-size: 15.5px; font-weight: 600; color: #ffffff; background: transparent; border: none;")
        title_row.addWidget(lbl_title)
        title_row.addStretch(1)
        mid_col.addLayout(title_row)

        desc = QLabel("สแกน QR Code เพื่อโอนเงินสนับสนุนโดยตรง ไม่โดนหักธรรมเนียมแม้แต่ % เดียว")
        desc.setStyleSheet("font-size: 11px; color: #cbd5e1; background: transparent; border: none;")
        mid_col.addWidget(desc)
        row.addLayout(mid_col, 1)

        btn_qr = QPushButton("เปิด QR ➔")
        btn_qr.setCursor(Qt.PointingHandCursor)
        btn_qr.setStyleSheet(
            "QPushButton { background: #0284c7; color: white; font-weight: 700; font-size: 12px; "
            "border: none; border-radius: 0px; padding: 8px 16px; }"
            "QPushButton:hover { background: #0369a1; }"
        )
        btn_qr.clicked.connect(lambda: self._show_qr_full("promptpay_qr.png", "PromptPay"))
        row.addWidget(btn_qr)

        card.setCursor(Qt.PointingHandCursor)
        card.mousePressEvent = lambda _e: self._show_qr_full("promptpay_qr.png", "PromptPay")
        return card

    def _make_qr_card(self, filename: str, title: str) -> QWidget:
        card = QFrame()
        card.setStyleSheet("QFrame { background: #1e293b; border: 1.5px solid rgba(56, 189, 248, 0.35); border-radius: 0px; }")
        col = QVBoxLayout(card)
        col.setContentsMargins(12, 12, 12, 12)
        col.setSpacing(6)

        lbl_title = QLabel(title)
        lbl_title.setAlignment(Qt.AlignCenter)
        lbl_title.setStyleSheet("font-size: 13px; font-weight: 800; color: #38bdf8; background: transparent; border: none;")
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
        title_lbl.setStyleSheet("font-size: 14px; font-weight: 800; color: #38bdf8;")
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

    def _make_tm_card(self) -> QWidget:
        card = QFrame()
        card.setStyleSheet("QFrame { background: #1e293b; border: 1.5px solid rgba(249, 115, 22, 0.45); border-radius: 0px; }")
        col = QVBoxLayout(card)
        col.setContentsMargins(14, 14, 14, 14)
        col.setSpacing(8)

        lbl_title = QLabel("🍊 TrueMoney")
        lbl_title.setAlignment(Qt.AlignCenter)
        lbl_title.setStyleSheet("font-size: 13px; font-weight: 800; color: #fb923c; background: transparent; border: none;")
        col.addWidget(lbl_title)

        icon_lbl = QLabel("🎁")
        icon_lbl.setAlignment(Qt.AlignCenter)
        icon_lbl.setStyleSheet("font-size: 38px; background: transparent; border: none;")
        col.addWidget(icon_lbl)

        badge = QLabel("⚡ ตรวจสอบและขึ้นชื่อทันที")
        badge.setAlignment(Qt.AlignCenter)
        badge.setStyleSheet("font-size: 12px; font-weight: 700; color: #10b981; background: transparent; border: none;")
        col.addWidget(badge)

        desc = QLabel("1. ส่งซองทรูมันนี่ ➔ ส่งให้คนเดียว\n2. นำลิงก์ซองมากรอกในระบบ\nระบบส่งยอดสนับสนุนเข้าระบบอัตโนมัติ")
        desc.setAlignment(Qt.AlignCenter)
        desc.setStyleSheet("font-size: 11px; color: #cbd5e1; background: transparent; border: none; line-height: 1.45;")
        desc.setWordWrap(True)
        col.addWidget(desc, 1)

        btn_tm = QPushButton("🎁 ส่งซอง TrueMoney")
        btn_tm.setCursor(Qt.PointingHandCursor)
        btn_tm.setStyleSheet(
            "QPushButton { background: linear-gradient(135deg, #f97316, #ea580c); color: white; font-weight: 700; font-size: 12px; "
            "border: none; border-radius: 0px; padding: 10px; }"
            "QPushButton:hover { background: #c2410c; }"
        )
        btn_tm.clicked.connect(self._open_truemoney_voucher)
        col.addWidget(btn_tm)
        return card

    def _open_truemoney_voucher(self):
        dlg = TrueMoneyVoucherDialog(self, app_name=self._app_name, api_url=self._api_url)
        if dlg.exec() == QDialog.Accepted:
            self._reload()

    def _open_upload(self):
        dlg = SupporterUploadDialog(self, app_name=self._app_name, api_url=self._api_url)
        if dlg.exec() == QDialog.Accepted:
            self._reload()

    def _reload(self):
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

        if not result.get("ok"):
            self.status_label.setText(f"❌ โหลดไม่สำเร็จ: {result.get('error', 'ไม่ทราบสาเหตุ')}")
            return

        self._supporters_data = result.get("supporters", [])
        self._render_supporters()

    def _render_supporters(self):
        while self.list_layout.count() > 1:
            item = self.list_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        if not self._supporters_data:
            self.status_label.setText("ยังไม่มีผู้สนับสนุน — เป็นคนแรกได้เลย!")
            return

        supporters = list(self._supporters_data)
        if self._sort_mode == "amount":
            supporters.sort(key=lambda s: float(s.get("amount") or 0), reverse=True)
        else:
            # Default: เรียงตามวันที่ล่าสุด (Newest date first)
            supporters.sort(
                key=lambda s: str(s.get("date") or s.get("approved_at") or ""),
                reverse=True
            )

        total_count = len(supporters)
        self._total_pages = max(1, math.ceil(total_count / self._per_page)) if total_count > 0 else 1
        if self._current_page > self._total_pages:
            self._current_page = self._total_pages
        if self._current_page < 1:
            self._current_page = 1

        start_idx = (self._current_page - 1) * self._per_page
        end_idx = start_idx + self._per_page
        page_items = supporters[start_idx:end_idx]

        self.status_label.setText(f"✅ ผู้สนับสนุนทั้งหมด {total_count} ท่าน")
        self.page_label.setText(f"หน้า {self._current_page} / {self._total_pages} (แสดง {len(page_items)} จาก {total_count} ท่าน)")
        self.btn_prev.setEnabled(self._current_page > 1)
        self.btn_next.setEnabled(self._current_page < self._total_pages)

        for idx, sup in enumerate(page_items):
            if not isinstance(sup, dict):
                continue
            row = self._make_row(sup, start_idx + idx)
            self.list_layout.insertWidget(self.list_layout.count() - 1, row)

    def _make_row(self, sup: dict, idx: int) -> QWidget:
        name = str(sup.get("name", "ผู้สนับสนุนใจดี")).strip() or "ผู้สนับสนุนใจดี"
        amount = sup.get("amount", 0)
        currency = str(sup.get("currency", "THB")).upper()
        date = str(sup.get("date", "")).strip()
        message = str(sup.get("message", "")).strip()
        source = str(sup.get("source", "")).strip()
        platform = str(sup.get("platform", "")).strip().lower()
        channel_url = str(sup.get("channel_url", "")).strip()

        amount_str = format_amount(amount, currency)

        row = QFrame()
        row.setObjectName("SupporterRow")
        row.setStyleSheet(
            "QFrame#SupporterRow { background: #131b2a; border: 1px solid rgba(255, 255, 255, 0.05); "
            "border-left: 2px solid #10b981; border-radius: 0px; } "
            "QFrame#SupporterRow:hover { background: #172235; border-color: rgba(56, 189, 248, 0.25); }"
        )
        col = QVBoxLayout(row)
        col.setContentsMargins(12, 9, 12, 9)
        col.setSpacing(4)

        # -------------------------------------------------------------
        # Row 1: [ชื่อ] [ลิ้งค์โปรโมทตัวเอง] .......... [ยอดเงิน (ขวาสุด)]
        # -------------------------------------------------------------
        top = QHBoxLayout()
        top.setSpacing(8)

        name_lbl = QLabel(f"💚 {name}")
        name_lbl.setStyleSheet("font-size: 14px; font-weight: 600; color: #ffffff; background: transparent; border: none;")
        top.addWidget(name_lbl)

        # Promo channel button (ลิ้งค์โปรโมทตัวเอง) on the same line as name
        if channel_url:
            icon_file = "homepage.png"
            plat_name = "เว็บไซต์"
            matched_code = ""
            for p_code, pname, ifile in PLATFORMS:
                if p_code and (p_code == platform or p_code in channel_url.lower()):
                    icon_file = ifile
                    plat_name = pname
                    matched_code = p_code
                    break

            btn_text = " ↗" if matched_code == "x" else f" {plat_name} ↗"
            plat_btn = QPushButton(btn_text)
            plat_btn.setCursor(Qt.PointingHandCursor)
            icon_p = os.path.join(ASSETS_DIR, icon_file) if icon_file else ""
            if icon_p and os.path.exists(icon_p):
                plat_btn.setIcon(QIcon(icon_p))
                plat_btn.setIconSize(QSize(12, 12))
            plat_btn.setStyleSheet(
                "QPushButton { font-size: 10px; font-weight: 600; color: #cbd5e1; "
                "background: rgba(255, 255, 255, 0.06); border: 1px solid rgba(255, 255, 255, 0.12); "
                "border-radius: 0px; padding: 2px 7px; text-align: left; } "
                "QPushButton:hover { background: rgba(56, 189, 248, 0.1); color: #38bdf8; border-color: #38bdf8; }"
            )
            plat_btn.clicked.connect(lambda _, u=channel_url: QDesktopServices.openUrl(QUrl(u)))
            top.addWidget(plat_btn)

        top.addStretch(1)

        amount_lbl = QLabel(amount_str)
        amount_lbl.setStyleSheet(
            "font-size: 13px; font-weight: 700; color: #34d399; "
            "background: rgba(16, 185, 129, 0.12); border: 1px solid rgba(16, 185, 129, 0.25); "
            "border-radius: 0px; padding: 2px 8px; font-family: monospace;"
        )
        top.addWidget(amount_lbl)
        col.addLayout(top)

        # -------------------------------------------------------------
        # Row 2: [วันที่] [สนับสนุนจากแพลตฟอร์มไหน] (Text สีแยกกัน ไม่มีกรอบ)
        # -------------------------------------------------------------
        sub = QHBoxLayout()
        sub.setSpacing(10)

        if date:
            date_lbl = QLabel(f"📅 {date}")
            date_lbl.setStyleSheet("font-size: 11px; color: #64748b; font-weight: 500; background: transparent; border: none;")
            sub.addWidget(date_lbl)

        if source:
            src_label = source
            src_color = "#38bdf8"
            src_lower = source.lower()
            if "gamevault" in src_lower or "game vault" in src_lower:
                src_label = "🕹️ จาก GameVault"
                src_color = "#34d399"
            elif "broadcast playroom" in src_lower:
                src_label = "🎮 จาก Broadcast Playroom"
                src_color = "#d8b4fe"
            elif "vip" in src_lower:
                src_label = f"⭐ จาก {source}"
                src_color = "#fde047"
            elif "cropper" in src_lower or "sprite" in src_lower:
                src_label = f"✂️ จาก {source}"
                src_color = "#5eead4"
            elif "extension" in src_lower or "x video" in src_lower:
                src_label = f"🧩 จาก {source}"
                src_color = "#7dd3fc"
            elif "web" in src_lower:
                src_label = "🌐 จาก หน้าเว็บไซต์ MeN9CH"
                src_color = "#94a3b8"
            else:
                src_label = f"📍 จาก {source}"

            src_lbl = QLabel(src_label)
            src_lbl.setStyleSheet(
                f"font-size: 11px; font-weight: 600; color: {src_color}; "
                f"background: transparent; border: none; padding: 0px;"
            )
            sub.addWidget(src_lbl)

        sub.addStretch(1)
        if date or source:
            col.addLayout(sub)

        # -------------------------------------------------------------
        # Row 3: ข้อความจากผู้สนับสนุน (ถ้ามี)
        # -------------------------------------------------------------
        if message:
            msg_lbl = QLabel(f'"{message}"')
            msg_lbl.setStyleSheet(
                "font-size: 11.5px; color: #cbd5e1; font-style: italic; background: transparent; "
                "border: none; padding-left: 4px; padding-top: 2px;"
            )
            msg_lbl.setWordWrap(True)
            col.addWidget(msg_lbl)

        return row
    def closeEvent(self, event):
        if self._fetch_thread and self._fetch_thread.isRunning():
            self._fetch_thread.quit()
            self._fetch_thread.wait(3000)
        super().closeEvent(event)
