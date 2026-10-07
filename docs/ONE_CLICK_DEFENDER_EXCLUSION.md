# 🛡️ Universal 1-Click Windows Defender Exclusion Guide
**คู่มือระบบเพิ่มข้อยกเว้น Windows Defender อัตโนมัติในคลิกเดียว (พร้อมระบบตรวจจับการย้ายโฟลเดอร์)**

---

## 📌 บทนำและเป้าหมาย (Overview)

ในการพัฒนาโปรแกรมสำหรับ Windows โดยเฉพาะโปรแกรมที่เป็นไฟล์ `.exe` แจกจ่ายเอง (ผ่าน GitHub หรือ Direct Download) โดยไม่ได้ซื้อใบรับรอง Code Signing Certificate (ซึ่งมีค่าใช้จ่าย 300–500 USD/ปี) มักจะพบปัญหา:
1. **Windows SmartScreen หรือ Windows Defender** สแกนและกักกัน/ลบไฟล์ `.exe` หรือไฟล์อัปเดตอัตโนมัติ
2. ผู้ใช้ทั่วไปไม่ทราบวิธีเข้าหน้าการตั้งค่า Exclusions ของ Windows ซึ่งมีขั้นตอนซับซ้อน (6-7 ขั้นตอน)
3. หากผู้ใช้ **ย้ายโฟลเดอร์โปรแกรม** ข้อยกเว้นเดิมที่เคยทำไว้จะใช้งานไม่ได้ทันที

ระบบ **1-Click Windows Defender Exclusion** นี้ถูกออกแบบมาให้เป็น **โมดูลมาตรฐาน (Reusable Component)** ที่สามารถนำไปใช้กับโปรเจกต์ใดก็ได้ โดยจะ:
- ตรวจจับชื่อไฟล์ `.exe` และตำแหน่งโฟลเดอร์ของโปรเจกต์นั้นโดยอัตโนมัติ (Dynamic Auto-Detection)
- ยิงคำสั่ง PowerShell ผ่านสิทธิ์ Administrator (UAC) ในคลิกเดียว
- จดจำประวัติโฟลเดอร์ล่าสุด และเตือนผู้ใช้ทันทีหากมีการย้ายที่ตั้งโปรแกรม เพื่อให้กดอัปเดตปลายทางใหม่

---

## ⚙️ หลักการทำงานทางเทคนิค (Architecture)

### 1. คำสั่ง PowerShell สำหรับเพิ่มข้อยกเว้น
Windows มีคำสั่ง PowerShell สำหรับจัดการ Windows Defender ในตัว คือ:
```powershell
Add-MpPreference -ExclusionPath "<โฟลเดอร์ที่ตั้งโปรแกรม>"
Add-MpPreference -ExclusionProcess "<ชื่อไฟล์.exe>"
```
> **ข้อจำกัดของ Windows:** คำสั่งนี้จำเป็นต้องมีสิทธิ์ **Administrator** เท่านั้น จึงต้องรันผ่านคำสั่ง `Start-Process powershell -Verb RunAs` เพื่อเรียกหน้าต่าง UAC (User Account Control) ให้ผู้ใช้กด **"Yes"**

### 2. การตรวจจับ .exe และ Path แบบยืดหยุ่น (Universal Resolution)
โปรแกรมต้องไม่ฮาร์ดโค้ด (Hardcode) ชื่อไฟล์หรือตำแหน่งโฟลเดอร์ เพื่อให้โปรเจกต์ไหนเอาไปใช้ก็ทำงานได้ทันที:
- หากรันแบบคอมไพล์แล้ว (`getattr(sys, 'frozen', False)`):
  - Path โฟลเดอร์ = `Path(sys.executable).resolve().parent`
  - ชื่อไฟล์ EXE = `Path(sys.executable).name`
- หากรันด้วยสคริปต์ Python (`.py`):
  - Path โฟลเดอร์ = `Path(__file__).resolve().parent`
  - ชื่อไฟล์ EXE = `Path(__file__).name` (หรือตั้งชื่อเป้าหมายที่ต้องการ)

### 3. ระบบตรวจจับการย้ายโฟลเดอร์ (Relocation Detection)
- เมื่อผู้ใช้กดปุ่ม 1-Click สำเร็จ: บันทึก `current_dir` ลงในฐานข้อมูลหรือไฟล์คอนฟิก (เช่น `last_excluded_path`)
- เมื่อเปิดหน้าโปรแกรม / หน้าการตั้งค่า: ตรวจสอบว่า `current_dir == saved_excluded_path` หรือไม่:
  - หาก **ตรงกัน**: แสดงสถานะ `🟢 ได้รับการยกเว้นแล้ว (Active)`
  - หาก **ไม่ตรงกัน** หรือ **ยังไม่เคยตั้งค่า**: แสดงสถานะ `⚠️ ตรวจพบการย้ายโฟลเดอร์ กรุณากด 1-Click อีกครั้ง`

---

## 💻 โค้ดโมดูลตัวอย่าง (Drop-in Python Module)

คุณสามารถคัดลอกไฟล์นี้ไปวางในโปรเจกต์ใดก็ได้ (เช่น `defender_helper.py`):

```python
import sys
import os
import subprocess
from pathlib import Path
from typing import Tuple, Optional

class DefenderExclusionManager:
    """
    โมดูลจัดการ Windows Defender Exclusion อัตโนมัติ
    สามารถนำไปใช้กับโปรเจกต์ใดๆ ได้ทันทีโดยไม่ต้องแก้ไขชื่อไฟล์
    """
    
    @staticmethod
    def get_app_info() -> Tuple[Path, str]:
        """ดึง Path โฟลเดอร์ปัจจุบัน และชื่อไฟล์ Executable อัตโนมัติ"""
        if getattr(sys, 'frozen', False):
            # รันจาก PyInstaller (.exe)
            exe_path = Path(sys.executable).resolve()
            app_dir = exe_path.parent
            exe_name = exe_path.name
        else:
            # รันจาก Python script ปกติ
            app_dir = Path(__file__).resolve().parent
            exe_name = Path(sys.argv[0]).name
            if not exe_name.lower().endswith(".exe"):
                # หากยังเป็น .py ให้ตั้งชื่อ Default เป็นชื่อโฟลเดอร์หรือชื่อที่ต้องการ
                exe_name = f"{app_dir.name}.exe"
        return app_dir, exe_name

    @staticmethod
    def check_relocation_status(saved_path: Optional[str]) -> str:
        """
        ตรวจสอบสถานะการย้ายโฟลเดอร์:
        คืนค่า:
        - 'not_configured': ยังไม่เคยตั้งค่าข้อยกเว้น
        - 'relocated': เคยตั้งค่าแล้วแต่โฟลเดอร์ถูกย้ายที่ตั้ง
        - 'active': ข้อยกเว้นตรงกับโฟลเดอร์ปัจจุบัน
        """
        if not saved_path:
            return "not_configured"
        
        current_dir, _ = DefenderExclusionManager.get_app_info()
        norm_current = os.path.normpath(str(current_dir)).lower()
        norm_saved = os.path.normpath(str(saved_path)).lower()
        
        if norm_current != norm_saved:
            return "relocated"
        return "active"

    @staticmethod
    def apply_one_click_exclusion() -> bool:
        """
        ส่งคำสั่ง PowerShell พร้อมสิทธิ์ Administrator (UAC Prompt)
        เพื่อเพิ่มโฟลเดอร์และกระบวนการทำงานเข้า Windows Defender
        """
        app_dir, exe_name = DefenderExclusionManager.get_app_info()
        dir_str = str(app_dir).replace("'", "''")
        exe_str = exe_name.replace("'", "''")

        # คำสั่ง PowerShell ที่จะถูกส่งไปรันแบบ Elevated (RunAs)
        # ปิดหน้าต่างอัตโนมัติเมื่อรันเสร็จ (-WindowStyle Hidden หรือแสดงแจ้งผล)
        ps_script = (
            f"Add-MpPreference -ExclusionPath '{dir_str}'; "
            f"Add-MpPreference -ExclusionProcess '{exe_str}'; "
            f"[System.Console]::Beep(1000, 200)"
        )

        try:
            # เรียก Start-Process powershell -Verb RunAs เพื่อเปิดหน้าต่าง UAC
            runner_cmd = (
                f'Start-Process powershell -ArgumentList '
                f'\'-NoProfile -ExecutionPolicy Bypass -Command "{ps_script}"\' '
                f'-Verb RunAs'
            )
            subprocess.Popen(["powershell", "-Command", runner_cmd], shell=False)
            return True
        except Exception as e:
            print(f"Error launching elevation: {e}")
            return False
```

---

## 🎨 ตัวอย่างการต่อเข้ากับ UI (PyQt6 / PySide6)

```python
# ตัวอย่างการผูกปุ่มในหน้า Settings
def setup_ui(self):
    self.btn_exclusion = QPushButton("⚡ เพิ่มข้อยกเว้นอัตโนมัติ (1-Click Exclusion)")
    self.btn_exclusion.clicked.connect(self.on_click_exclusion)
    
    # อัปเดตข้อความแจ้งเตือนสถานะ
    self.update_exclusion_status_label()

def update_exclusion_status_label(self):
    saved_path = self.db.get_setting("last_defender_excluded_path", None)
    status = DefenderExclusionManager.check_relocation_status(saved_path)
    
    if status == "relocated":
        self.status_lbl.setText("⚠️ ตรวจพบโฟลเดอร์ถูกย้ายที่ตั้ง กรุณากดปุ่ม 1-Click อีกครั้งเพื่ออัปเดต")
        self.status_lbl.setStyleSheet("color: #eab308; font-weight: bold;")
    elif status == "active":
        self.status_lbl.setText("🟢 ได้รับการยกเว้นใน Windows Defender เรียบร้อยแล้ว")
        self.status_lbl.setStyleSheet("color: #22c55e; font-weight: bold;")
    else:
        self.status_lbl.setText("⚪ ยังไม่เคยตั้งค่าข้อยกเว้น")
        self.status_lbl.setStyleSheet("color: #94a3b8;")

def on_click_exclusion(self):
    # เรียกตัวจัดการ
    success = DefenderExclusionManager.apply_one_click_exclusion()
    if success:
        # บันทึก Path ปัจจุบันลง Database/Config
        current_dir, _ = DefenderExclusionManager.get_app_info()
        self.db.set_setting("last_defender_excluded_path", str(current_dir))
        
        QMessageBox.information(
            self,
            "ขอสิทธิ์ Administrator (UAC)",
            "ระบบกำลังเรียกหน้าต่างขอสิทธิ์จาก Windows (UAC)\n\n"
            "👉 กรุณากด 'Yes' ที่หน้าต่างแจ้งเตือน เพื่อยืนยันการตั้งค่าครับ!"
        )
        self.update_exclusion_status_label()
```

---

## 📋 ข้อแนะนำในการสื่อสารกับผู้ใช้งาน (UX Best Practice)

1. **ระบุชัดเจนเรื่องปุ่ม Yes ใน UAC:**
   - ผู้ใช้หลายคนตกใจเมื่อมีหน้าต่างสีส้มหรือสีฟ้าเด้งขึ้นมาเตือนเต็มจอ (Secure Desktop) ต้องใส่ข้อความที่ตัวโปรแกรมเสมอว่า:
   > *"เมื่อมีหน้าต่างขออนุญาต (User Account Control - UAC) เด้งขึ้นมาเต็มจอ ให้กด **Yes** เพื่อยืนยัน"*
2. **การย้ายโฟลเดอร์ (Relocation Alert):**
   - เตือนผู้ใช้ว่า หากผู้ใช้คัดลอกหรือย้ายโฟลเดอร์เกม/โปรแกรมไปไว้ที่ Drive อื่น (เช่น จาก C: ไป D:) ให้เปิดหน้า Settings แล้วกดปุ่มนี้ 1 ครั้งเพื่อบันทึกที่อยู่ใหม่ทันที
3. **ทางเลือกสำรอง (Manual Fallback):**
   - ควรมีปุ่มหรือลิงก์เล็กๆ สำหรับ `เปิดหน้า Windows Security (start windowsdefender:)` สำรองไว้เสมอ เผื่อกรณีที่เครื่องของผู้ใช้ถูกล็อกนโยบายความปลอดภัยขององค์กร (Group Policy) ที่ไม่อนุญาตให้รัน PowerShell แบบ RunAs
