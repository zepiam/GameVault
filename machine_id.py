"""machine_id.py — สร้าง machine fingerprint สำหรับระบบแบนผู้สนับสนุนเท็จ

ใช้ข้อมูลฮาร์ดแวร์ผสมกัน -> hash SHA256 -> เก็บ cache ไว้ที่ ~/.men9ch/machine_id.json
(โฟลเดอร์เดียวกันกับโปรแกรมอื่นๆ ของ MeN9CH เพื่อให้ระบบแบนสอดคล้องกันข้ามโปรแกรม)
ครั้งแรก generate + cache, ครั้งต่อไปอ่านจาก cache (เร็ว + stable ข้าม session)

หมายเหตุ: fingerprint ไม่สมบูรณ์ 100% (ผู้ใช้ที่มีความรู้สามารถปลอมได้)
แต่เพียงพอสำหรับกันผู้ใช้ทั่วไปที่ส่งข้อมูลเท็จเล่น
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import re
import uuid

logger = logging.getLogger(__name__)

_cache: str | None = None


def _shared_data_dir() -> str:
    return os.path.join(os.path.expanduser("~"), ".men9ch")


def _collect_hardware_info() -> str:
    parts = []

    try:
        mac = uuid.getnode()
        parts.append(f"mac:{mac:012x}")
    except Exception:
        parts.append("mac:0")

    try:
        parts.append(f"os:{platform.system()}")
        parts.append(f"os_ver:{platform.version()}")
        parts.append(f"os_rel:{platform.release()}")
    except Exception:
        pass

    try:
        parts.append(f"node:{platform.node()}")
    except Exception:
        pass

    try:
        parts.append(f"mach:{platform.machine()}")
    except Exception:
        pass

    try:
        parts.append(f"proc:{platform.processor()}")
    except Exception:
        pass

    if platform.system() == "Windows":
        try:
            import subprocess
            result = subprocess.run(
                ["vol", "C:"], capture_output=True, text=True, timeout=3, shell=True,
            )
            output = (result.stdout or "") + (result.stderr or "")
            match = re.search(r"([0-9A-Fa-f]{4}-[0-9A-Fa-f]{4})", output)
            if match:
                parts.append(f"vol:{match.group(1)}")
        except Exception:
            pass

    return "|".join(parts)


def generate_machine_id() -> str:
    """สร้าง machine ID (SHA256 hash ของข้อมูลฮาร์ดแวร์), 64-char hex string"""
    raw = _collect_hardware_info()
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def get_machine_id() -> str:
    """คืน machine ID (cache ใน memory + file, stable ข้าม restart)"""
    global _cache
    if _cache:
        return _cache

    data_dir = _shared_data_dir()
    cache_file = os.path.join(data_dir, "machine_id.json")

    try:
        if os.path.exists(cache_file):
            with open(cache_file, encoding="utf-8") as f:
                data = json.load(f)
            cached = data.get("machine_id", "")
            if cached and len(cached) == 64:
                _cache = cached
                return _cache
    except Exception as e:
        logger.debug(f"Cannot read machine_id cache: {e}")

    _cache = generate_machine_id()

    try:
        os.makedirs(data_dir, exist_ok=True)
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump({"machine_id": _cache}, f)
    except Exception as e:
        logger.debug(f"Cannot save machine_id cache: {e}")

    return _cache
