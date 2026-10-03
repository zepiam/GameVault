"""supporters_api.py — ดึงรายชื่อผู้สนับสนุนจาก men9ch.com API

★ API Contract (ฝั่งเว็บต้อง return JSON):
    {
        "ok": true,
        "supporters": [
            {"name": "...", "amount": 500, "currency": "THB", "date": "YYYY-MM-DD", "message": "..."},
            ...
        ]
    }

★ Error response:
    {"ok": false, "error": "เหตุผล"}

★ Functions:
    - fetch_supporters()      — GET approved list (โปรแกรมแสดงในหน้าสนับสนุน)
    - submit_supporter()      — POST อัพโหลดหลักฐาน (multipart)
    - delete_supporter()      — POST ลบผู้สนับสนุน (admin)
    - fetch_pending()         — POST ดู pending list (admin)
    - open_approve_url()      — เปิดหน้า approve ในเบราว์เซอร์

★ ดึงครั้งเดียวตอนเปิดโปรแกรม (user ตั้งค่า cache policy)
"""
from __future__ import annotations

import json
import logging
import ssl
import time
import urllib.request
import urllib.error
import urllib.parse

_log = logging.getLogger(__name__)

# ★ API endpoint — user สามารถเปลี่ยนได้ภายหลัง
SUPPORTERS_API_URL = "https://men9ch.com/api"
# ★ ใช้ User-Agent เหมือน browser จริง — security plugin ของ host บล็อก bot UA
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"


def _browser_headers(extra=None):
    """สร้าง headers เหมือน browser จริง (กัน security plugin block)"""
    h = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Origin": "https://men9ch.com",
        "Referer": "https://men9ch.com/api/upload.html",
    }
    if extra:
        h.update(extra)
    return h

# ★ Tier thresholds (เปรียบเทียบในหน่วย THB — สกุลอื่นแปลงเป็น THB ก่อนถ้ามีอัตรา)
#   ตอนนี้ใช้ง่ายๆ: ทุกสกุลเทียบ amount ตรงๆ (assume THB)
_TIER_THRESHOLDS = [
    (10000, "👑", "Diamond"),
    (5000,  "💎", "Platinum"),
    (2000,  "🥇", "Gold"),
    (500,   "🥈", "Silver"),
    (1,     "🥉", "Bronze"),
]

# ★ currency symbol map
_CURRENCY_SYMBOL = {
    "THB": "฿",
    "USD": "$",
    "JPY": "¥",
    "EUR": "€",
    "GBP": "£",
}


def get_tier(amount: float, currency: str = "THB") -> dict:
    """คำนวณ tier จากยอด → คืน {"icon": "...", "name": "..."}

    ★ ตอนนี้ใช้ amount ตรงๆ (assume THB-equivalent)
      ถ้ามีหลายสกุลจริงๆ จะต้องแปลงเป็น THB ก่อนเปรียบเทียบ
    """
    amt = float(amount or 0)
    for threshold, icon, name in _TIER_THRESHOLDS:
        if amt >= threshold:
            return {"icon": icon, "name": name}
    # amount = 0 หรือติดลบ → ไม่มี tier
    return {"icon": "💚", "name": "Supporter"}


def format_amount(amount, currency: str = "THB") -> str:
    """แปลง amount → string พร้อม symbol เช่น '500฿' / '$10'"""
    try:
        amt = float(amount or 0)
    except (TypeError, ValueError):
        amt = 0

    symbol = _CURRENCY_SYMBOL.get(currency.upper(), currency.upper() + " ")

    # ★ format ตามธรรมเนียม: THB/JPY ใส่ symbol หลัง, USD/EUR/GBP ใส่ symbol หน้า
    if amt == int(amt):
        amt_str = f"{int(amt):,}"
    else:
        amt_str = f"{amt:,.2f}"

    if currency.upper() in ("THB", "JPY"):
        return f"{amt_str}{symbol}"
    elif currency.upper() in ("USD", "EUR", "GBP"):
        return f"{symbol}{amt_str}"
    else:
        return f"{amt_str} {currency.upper()}"


def fetch_supporters(url: str = SUPPORTERS_API_URL, timeout: int = 8, retries: int = 2) -> dict:
    """ดึงรายชื่อผู้สนับสนุนจาก API

    Returns:
        {"ok": True, "supporters": [...]} — สำเร็จ
        {"ok": False, "error": "msg"}     — ล้มเหลว (network / parse / server error)

    ★ รันใน background thread เสมอ (urlopen เป็น blocking call)
    """
    # ★ normalize URL → api.php endpoint
    if not url.endswith('api.php'):
        if url.endswith('/'):
            url = url + 'api.php'
        else:
            url = url.rstrip('/') + '/api.php'

    last_error = "unknown error"

    # ★ SSL context สำหรับ HTTPS (เหมือน pattern ใน settings.py)
    ctx = ssl.create_default_context()
    ctx.load_default_certs()

    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=_browser_headers({
                "Accept": "application/json",
                "Cache-Control": "no-cache",
            }))
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                raw = resp.read().decode("utf-8", errors="replace")

            data = json.loads(raw)

            # ★ validate response shape
            if not isinstance(data, dict):
                raise ValueError("response ไม่ใช่ JSON object")

            if data.get("ok") is False:
                # server ส่ง error มาเอง
                err = data.get("error", "server error ไม่ระบุ")
                _log.warning("Supporters API returned error: %s", err)
                return {"ok": False, "error": str(err)}

            if data.get("ok") is not True:
                # บาง server อาจไม่ส่ง ok field → treat as ok ถ้ามี supporters
                if "supporters" not in data:
                    raise ValueError("response ไม่มี field 'supporters'")

            supporters = data.get("supporters", [])
            if not isinstance(supporters, list):
                raise ValueError("field 'supporters' ไม่ใช่ array")

            _log.info("Supporters API: fetched %d supporter(s)", len(supporters))
            return {"ok": True, "supporters": supporters, "count": len(supporters)}

        except urllib.error.HTTPError as e:
            last_error = f"HTTP {e.code}: {e.reason}"
            _log.warning("Supporters API HTTPError (attempt %d): %s", attempt + 1, last_error)
        except urllib.error.URLError as e:
            last_error = f"ไม่สามารถเชื่อมต่อ server ได้: {e.reason}"
            _log.warning("Supporters API URLError (attempt %d): %s", attempt + 1, last_error)
        except (json.JSONDecodeError, ValueError) as e:
            last_error = f"ข้อมูล JSON ไม่ถูกต้อง: {e}"
            _log.warning("Supporters API parse error (attempt %d): %s", attempt + 1, last_error)
            # parse error → ไม่ retry (คงเป็น server ส่ง format ผิด)
            break
        except Exception as e:
            last_error = f"เกิดข้อผิดพลาด: {e}"
            _log.warning("Supporters API error (attempt %d): %s", attempt + 1, last_error)

        # retry delay
        if attempt < retries:
            time.sleep(1)

    return {"ok": False, "error": last_error}


# ════════════════════════════════════════════════════════════════
# ★ Submit (อัพโหลดหลักฐานสนับสนุน)
# ════════════════════════════════════════════════════════════════

def submit_supporter(
    name: str,
    amount: float,
    api_url: str = SUPPORTERS_API_URL,
    currency: str = "THB",
    message: str = "",
    channel: str = "bank",
    method: str = "slip",
    bank: str = "",
    transfer_date: str = "",
    transfer_time: str = "",
    slip_path: str = "",
    machine_id: str = "",
    platform: str = "",
    channel_url: str = "",
    timeout: int = 30,
) -> dict:
    """★ ส่งหลักฐานการสนับสนุน (multipart/form-data) — multi-channel

    Args:
        name: ชื่อที่จะแสดง
        amount: จำนวนเงิน
        currency: THB/USD/JPY/...
        message: ข้อความ (ไม่บังคับ)
        channel: "bank" หรือ "truemoney"
        method: "slip" (แนบสลิป) หรือ "manual" (กรอกข้อมูล) — ใช้เฉพาะ channel="bank"
        bank: รหัสธนาคาร (SCB/KBANK/...) — ใช้เฉพาะ bank + manual
        transfer_date: YYYY-MM-DD — ใช้เฉพาะ manual / truemoney
        transfer_time: HH:MM — ใช้เฉพาะ manual / truemoney
        slip_path: path ไฟล์รูปสลิป (PNG/JPG/WebP/GIF) — ใช้เฉพาะ bank + slip
        api_url: base API URL (default = men9ch.com)
                 ★ จะ append /submit.php อัตโนมัติ

    Returns:
        {"ok": True, "id": "...", "message": "..."} — สำเร็จ
        {"ok": False, "error": "..."}              — ล้มเหลว
    """
    import mimetypes
    import os
    import uuid

    # ★ หา submit.php endpoint
    if api_url.endswith("api.php"):
        submit_url = api_url.replace("api.php", "submit.php")
    elif api_url.endswith("/"):
        submit_url = api_url + "submit.php"
    elif "submit.php" in api_url:
        submit_url = api_url
    else:
        submit_url = api_url.rstrip("/") + "/submit.php"

    # ★ validate slip file (ถ้าเป็น bank + slip)
    has_slip = bool(slip_path)
    if has_slip:
        if not os.path.exists(slip_path):
            return {"ok": False, "error": f"ไม่พบไฟล์: {slip_path}"}
        file_size = os.path.getsize(slip_path)
        if file_size > 5 * 1024 * 1024:
            return {"ok": False, "error": "ไฟล์ใหญ่เกิน 5MB"}
        if file_size < 1024:
            return {"ok": False, "error": "ไฟล์เล็กเกินไป"}

    # ★ สร้าง multipart/form-data body (manual — ไม่ต้องติดตั้ง requests)
    boundary = uuid.uuid4().hex

    def _field(name, value):
        return (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
            f"{value}\r\n"
        ).encode("utf-8")

    # ★ build body — text fields
    body_parts = []
    body_parts.append(_field("name", name))
    body_parts.append(_field("amount", str(amount)))
    body_parts.append(_field("currency", currency))
    body_parts.append(_field("message", message))
    if machine_id:
        body_parts.append(_field("machine_id", machine_id))
    if platform:
        body_parts.append(_field("platform", platform))
    if channel_url:
        body_parts.append(_field("channel_url", channel_url))
    body_parts.append(_field("channel", channel))
    if channel == "bank":
        body_parts.append(_field("method", method))
        if method == "manual":
            body_parts.append(_field("bank", bank))
            body_parts.append(_field("transfer_date", transfer_date))
            body_parts.append(_field("transfer_time", transfer_time))
    else:  # truemoney
        body_parts.append(_field("transfer_date", transfer_date))
        body_parts.append(_field("transfer_time", transfer_time))

    # ★ file part (ถ้ามี slip)
    if has_slip:
        filename = os.path.basename(slip_path)
        mime_type = mimetypes.guess_type(slip_path)[0] or "image/png"
        with open(slip_path, "rb") as f:
            file_data = f.read()
        file_header = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="slip"; filename="{filename}"\r\n'
            f"Content-Type: {mime_type}\r\n\r\n"
        ).encode("utf-8")
        body_parts.append(file_header)
        body_parts.append(file_data)

    body_parts.append(f"\r\n--{boundary}--\r\n".encode("utf-8"))
    body = b"".join(body_parts)

    # ★ send POST
    ctx = ssl.create_default_context()
    ctx.load_default_certs()

    try:
        req = urllib.request.Request(
            submit_url,
            data=body,
            headers=_browser_headers({
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            }),
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        data = json.loads(raw)
        if data.get("ok"):
            _log.info("Submit supporter OK: %s (channel=%s)", data.get("id"), channel)
            return {"ok": True, "id": data.get("id"), "message": data.get("message", "ส่งสำเร็จ")}
        else:
            return {"ok": False, "error": data.get("error", "server error")}
    except urllib.error.HTTPError as e:
        try:
            err_body = e.read().decode("utf-8", errors="replace")
            err_data = json.loads(err_body)
            return {"ok": False, "error": err_data.get("error", f"HTTP {e.code}")}
        except Exception:
            return {"ok": False, "error": f"HTTP {e.code}: {e.reason}"}
    except urllib.error.URLError as e:
        return {"ok": False, "error": f"ไม่สามารถเชื่อมต่อ server: {e.reason}"}
    except Exception as e:
        return {"ok": False, "error": f"เกิดข้อผิดพลาด: {e}"}


# ════════════════════════════════════════════════════════════════
# ★ Admin actions (ลบผู้สนับสนุน + ดู pending)
# ════════════════════════════════════════════════════════════════

def delete_supporter(
    supporter_id: str,
    admin_secret: str,
    api_url: str = SUPPORTERS_API_URL,
    timeout: int = 10,
) -> dict:
    """★ ลบผู้สนับสนุน (admin only)

    Returns:
        {"ok": True, "message": "..."} หรือ {"ok": False, "error": "..."}
    """
    if not admin_secret:
        return {"ok": False, "error": "ยังไม่ได้ตั้ง admin secret (ไปที่ ตั้งค่า > สนับสนุน)"}

    url = api_url.rstrip("/")
    if not url.endswith("api.php"):
        url = url + "/api.php"
    url = f"{url}?action=delete&id={urllib.parse.quote(supporter_id)}&token={urllib.parse.quote(admin_secret)}"

    ctx = ssl.create_default_context()
    ctx.load_default_certs()

    try:
        req = urllib.request.Request(url, data=b"", method="POST", headers=_browser_headers())
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        data = json.loads(raw)
        return data
    except urllib.error.HTTPError as e:
        try:
            err_data = json.loads(e.read().decode("utf-8", errors="replace"))
            return {"ok": False, "error": err_data.get("error", f"HTTP {e.code}")}
        except Exception:
            return {"ok": False, "error": f"HTTP {e.code}: {e.reason}"}
    except urllib.error.URLError as e:
        return {"ok": False, "error": f"ไม่สามารถเชื่อมต่อ server: {e.reason}"}
    except Exception as e:
        return {"ok": False, "error": f"เกิดข้อผิดพลาด: {e}"}


def fetch_pending(
    admin_secret: str,
    api_url: str = SUPPORTERS_API_URL,
    timeout: int = 10,
) -> dict:
    """★ ดู pending list (admin only) — สำหรับ admin panel

    Returns:
        {"ok": True, "pending": [...], "count": N} หรือ {"ok": False, "error": "..."}
    """
    if not admin_secret:
        return {"ok": False, "error": "ยังไม่ได้ตั้ง admin secret"}

    url = api_url.rstrip("/")
    if not url.endswith("api.php"):
        url = url + "/api.php"
    url = f"{url}?action=fetch_pending&token={urllib.parse.quote(admin_secret)}"

    ctx = ssl.create_default_context()
    ctx.load_default_certs()

    try:
        req = urllib.request.Request(url, data=b"", method="POST", headers=_browser_headers())
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        data = json.loads(raw)
        return data
    except urllib.error.HTTPError as e:
        try:
            err_data = json.loads(e.read().decode("utf-8", errors="replace"))
            return {"ok": False, "error": err_data.get("error", f"HTTP {e.code}")}
        except Exception:
            return {"ok": False, "error": f"HTTP {e.code}: {e.reason}"}
    except urllib.error.URLError as e:
        return {"ok": False, "error": f"ไม่สามารถเชื่อมต่อ server: {e.reason}"}
    except Exception as e:
        return {"ok": False, "error": f"เกิดข้อผิดพลาด: {e}"}


def open_approve_url(supporter_id: str, admin_secret: str, api_url: str = SUPPORTERS_API_URL):
    """★ เปิดหน้า approve ในเบราว์เซอร์ (สำหรับ pending entries)"""
    import webbrowser
    base = api_url.rstrip("/")
    if base.endswith("api.php"):
        base = base.replace("api.php", "")
    url = f"{base}/approve.php?id={urllib.parse.quote(supporter_id)}&token={urllib.parse.quote(admin_secret)}"
    try:
        webbrowser.open(url)
    except Exception:
        pass
    return url


def open_admin_url(admin_secret: str, api_url: str = SUPPORTERS_API_URL):
    """★ เปิดหน้า admin ในเบราว์เซอร์"""
    import webbrowser
    base = api_url.rstrip("/")
    if base.endswith("api.php"):
        base = base.replace("api.php", "")
    url = f"{base}/admin.php?token={urllib.parse.quote(admin_secret)}"
    try:
        webbrowser.open(url)
    except Exception:
        pass
    return url

