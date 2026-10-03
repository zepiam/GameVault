"""
GameVault - Steam-style Local Game Library & Launcher
Features:
- Drive & Folder scanner for game executables (with generic engine filtering)
- Automatic game name detection & cleanup
- Online cover fetching from Steam CDN (600x900)
- Custom cover image uploading
- Zoom / Card size slider for thumbnail customization
- Detailed Game View with Steam description & screenshots
- Search cover by keyword or paste Steam Store Link / AppID
- One-click Game Play launcher
"""

import sys
import os
import re
import subprocess
import time
import webbrowser
import urllib.parse
from pathlib import Path
from typing import Optional, List, Dict

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSize, QPoint, QUrl
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor, QFont, QAction, QCursor, QFontDatabase
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QLineEdit, QComboBox, QFileDialog,
    QProgressBar, QScrollArea, QGridLayout, QFrame, QDialog,
    QMessageBox, QMenu, QSizePolicy, QToolButton, QSlider, QTextEdit,
    QColorDialog, QListWidget, QListWidgetItem, QCheckBox, QSystemTrayIcon,
    QStackedWidget, QFileIconProvider, QRadioButton, QButtonGroup
)

import winreg
import scanner
import cover_fetcher
from db import LibraryDB
import updater

REG_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_REG_NAME = "GameVault"

def set_windows_autostart(enable: bool) -> bool:
    """Configures GameVault to launch automatically on Windows login (minimized to system tray)."""
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_RUN_KEY, 0, winreg.KEY_ALL_ACCESS)
        if enable:
            exe_candidate = str(get_app_dir() / "GameVault.exe")
            if getattr(sys, 'frozen', False):
                exe_path = sys.executable
                cmd = f'"{exe_path}" --minimized'
            elif os.path.exists(exe_candidate):
                cmd = f'"{exe_candidate}" --minimized'
            else:
                main_py = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.py")
                cmd = f'"{sys.executable}" "{main_py}" --minimized'
            winreg.SetValueEx(key, APP_REG_NAME, 0, winreg.REG_SZ, cmd)
        else:
            try:
                winreg.DeleteValue(key, APP_REG_NAME)
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
        return True
    except Exception as e:
        print(f"[Autostart] Error configuring registry: {e}")
        return False

def is_windows_autostart_enabled() -> bool:
    """Checks if GameVault is currently registered in Windows Run registry key."""
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_RUN_KEY, 0, winreg.KEY_READ)
        val, _ = winreg.QueryValueEx(key, APP_REG_NAME)
        winreg.CloseKey(key)
        return bool(val)
    except Exception:
        return False

# Theme Palette (Steam Modern Dark)
BG_MAIN = "#0e141b"
BG_PANEL = "#161f2c"
BG_CARD = "#1e293b"
BG_CARD_HOVER = "#27364b"
BORDER_DEFAULT = "#2a3a4e"
BORDER_HOVER = "#38bdf8"
ACCENT_BLUE = "#38bdf8"
ACCENT_GREEN = "#22c55e"
ACCENT_GREEN_HOVER = "#16a34a"
TEXT_PRIMARY = "#f8fafc"
TEXT_MUTED = "#94a3b8"

# Default neutral color palette for border categories (user can rename & add freely)
DEFAULT_BORDER_CATEGORIES = [
    {"color": "#ef4444", "name": "สีแดง"},
    {"color": "#38bdf8", "name": "สีฟ้า"},
    {"color": "#a855f7", "name": "สีม่วง"},
    {"color": "#22c55e", "name": "สีเขียว"},
    {"color": "#eab308", "name": "สีเหลือง"},
    {"color": "#f97316", "name": "สีส้ม"},
    {"color": "#ec4899", "name": "สีชมพู"},
]


def get_app_dir() -> Path:
    """Returns the persistent directory where games.json and covers/ reside."""
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def get_asset_path(filename: str) -> str:
    """Returns the path to bundled assets (supporting PyInstaller _MEIPASS)."""
    if hasattr(sys, '_MEIPASS'):
        p = os.path.join(sys._MEIPASS, filename)
        if os.path.exists(p):
            return p
    return str(get_app_dir() / filename)


_ICON_CACHE: Dict[str, QPixmap] = {}
_ICON_PROVIDER: Optional[QFileIconProvider] = None

def get_executable_icon(target_path: str, lnk_path: str = "", target_size: int = 128) -> QPixmap:
    """
    Extracts high-resolution native icon from Windows executable or shortcut (.lnk).
    Caches pixmaps in memory for maximum rendering performance.
    """
    global _ICON_PROVIDER
    cache_key = f"{target_path}|{lnk_path}|{target_size}"
    if cache_key in _ICON_CACHE:
        return _ICON_CACHE[cache_key]

    if _ICON_PROVIDER is None:
        _ICON_PROVIDER = QFileIconProvider()

    path_to_inspect = target_path
    if lnk_path and os.path.exists(lnk_path):
        try:
            import win32com.client
            shell = win32com.client.Dispatch("WScript.Shell")
            sc = shell.CreateShortcut(lnk_path)
            if sc.IconLocation:
                icon_loc = sc.IconLocation.split(",")[0].strip()
                if os.path.exists(icon_loc):
                    path_to_inspect = icon_loc
            elif sc.TargetPath and os.path.exists(sc.TargetPath):
                path_to_inspect = sc.TargetPath
        except Exception:
            pass
        if not path_to_inspect or not os.path.exists(path_to_inspect):
            path_to_inspect = lnk_path

    pix = QPixmap()
    if path_to_inspect and os.path.exists(path_to_inspect):
        try:
            qicon = _ICON_PROVIDER.icon(QtCore.QFileInfo(path_to_inspect))
            raw_pix = qicon.pixmap(256, 256)
            if not raw_pix.isNull():
                pix = raw_pix.scaled(
                    target_size, target_size,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
        except Exception as e:
            print(f"[IconExtract] Error extracting icon for {path_to_inspect}: {e}")

    _ICON_CACHE[cache_key] = pix
    return pix


_COVER_CACHE: Dict[str, QPixmap] = {}

def get_cached_cover_pixmap(cover_path: str, poster_width: int, poster_height: int) -> Optional[QPixmap]:
    """Caches scaled cover posters in memory to avoid repetitive disk I/O and expensive smooth transformations."""
    if not cover_path or not os.path.exists(cover_path):
        return None
    cache_key = f"{cover_path}|{poster_width}|{poster_height}"
    if cache_key in _COVER_CACHE:
        return _COVER_CACHE[cache_key]

    try:
        pix = QPixmap(cover_path)
        if pix.isNull():
            return None
        scaled = pix.scaled(
            poster_width, poster_height,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation
        )
        cropped = scaled.copy(0, 0, poster_width, poster_height)
        _COVER_CACHE[cache_key] = cropped
        return cropped
    except Exception as e:
        print(f"[CoverCache] Error loading {cover_path}: {e}")
        return None

def clear_cover_cache(cover_path: Optional[str] = None):
    """Invalidates cached cover pixmaps when a cover is downloaded or updated."""
    global _COVER_CACHE
    if cover_path:
        keys_to_del = [k for k in _COVER_CACHE if k.startswith(f"{cover_path}|")]
        for k in keys_to_del:
            _COVER_CACHE.pop(k, None)
    else:
        _COVER_CACHE.clear()


def get_game_platform(game: Dict) -> str:
    """
    Detects the gaming platform / source of a game based on paths, executable, and shortcut.
    Returns: 'software', 'steam', 'epic', 'ubisoft', 'gog', 'ea', 'bluestacks', or 'local'.
    Manual override in game['platform'] takes absolute priority!
    """
    if game.get("is_software") or game.get("item_type") == "software":
        return "software"

    override = game.get("platform") or game.get("platform_override")
    if override and override.lower() in ("software", "steam", "epic", "ubisoft", "gog", "ea", "bluestacks", "local"):
        return override.lower()

    folder = (game.get("folder_path") or "").lower()
    exe = (game.get("exe_path") or "").lower()
    lnk = (game.get("lnk_path") or "").lower()
    args = (game.get("launch_args") or "").lower()

    # 1. Android / BlueStacks shortcuts or players (MUST specifically contain bluestacks or hd-player)
    # Generic Windows desktop shortcuts (.lnk) are NOT treated as BlueStacks!
    if "bluestacks" in exe or "hd-player" in exe or "bluestacks" in folder or "bluestacks" in lnk or "hd-player" in lnk or "bluestacks" in args:
        return "bluestacks"

    norm_path = f"{folder} {exe} {lnk}".replace("/", "\\")

    # 2. Steam Library
    if "steamlibrary" in norm_path or "steamapps" in norm_path or "\\steam\\" in norm_path:
        return "steam"

    # 3. Epic Games Store
    if "\\epic games\\" in norm_path or "\\epicgames\\" in norm_path or "\\epic games" in folder or "/epic games" in folder:
        return "epic"

    # 4. Ubisoft Connect / Uplay
    if "\\ubisoft" in norm_path or "\\uplay" in norm_path or "ubisoft game launcher" in norm_path:
        return "ubisoft"

    # 5. GOG Galaxy
    if "\\gog games\\" in norm_path or "\\gog galaxy\\" in norm_path or "\\gog.com\\" in norm_path or folder.endswith("\\gog games") or "/gog games" in folder:
        return "gog"

    # 6. EA App / Origin
    if "\\ea games\\" in norm_path or "\\origin games\\" in norm_path or "\\ea\\" in norm_path or "\\origin\\" in norm_path:
        return "ea"

    return "local"


def is_steam_game(game: Dict) -> bool:
    """Backward compatibility helper."""
    return get_game_platform(game) == "steam"


PLATFORM_META = {
    "software": {
        "label": "💻 SOFTWARE",
        "bg": "#1e1b4b",
        "border": "#4338ca",
        "text": "#818cf8",
        "glow": "#6366f1",
        "tab_name": "💻 Software",
        "tip": "โปรแกรมและซอฟต์แวร์ (Application / Tool)"
    },
    "steam": {
        "label": "♨ STEAM",
        "bg": "#0c2738",
        "border": "#1e608f",
        "text": "#38bdf8",
        "glow": "#1e5a84",
        "tab_name": "♨ Steam",
        "tip": "เกมจาก Steam Library"
    },
    "epic": {
        "label": "⚡ EPIC",
        "bg": "#18181b",
        "border": "#3f3f46",
        "text": "#facc15",
        "glow": "#ca8a04",
        "tab_name": "⚡ Epic Games",
        "tip": "เกมจาก Epic Games Store"
    },
    "ubisoft": {
        "label": "🌀 UBISOFT",
        "bg": "#0f172a",
        "border": "#2563eb",
        "text": "#60a5fa",
        "glow": "#3b82f6",
        "tab_name": "🌀 Ubisoft",
        "tip": "เกมจาก Ubisoft Connect"
    },
    "gog": {
        "label": "👾 GOG",
        "bg": "#2e1065",
        "border": "#7c3aed",
        "text": "#c084fc",
        "glow": "#9333ea",
        "tab_name": "👾 GOG Galaxy",
        "tip": "เกมจาก GOG Galaxy"
    },
    "ea": {
        "label": "🎯 EA",
        "bg": "#2a0808",
        "border": "#dc2626",
        "text": "#f87171",
        "glow": "#ef4444",
        "tab_name": "🎯 EA App",
        "tip": "เกมจาก EA App / Origin"
    },
    "bluestacks": {
        "label": "📱 ANDROID",
        "bg": "#064e3b",
        "border": "#059669",
        "text": "#34d399",
        "glow": "#10b981",
        "tab_name": "📱 Android",
        "tip": "เกม Android (BlueStacks)"
    },
    "local": {
        "label": "📁 LOCAL",
        "bg": "#1a222d",
        "border": "#2e3d4f",
        "text": "#94a3b8",
        "glow": None,
        "tab_name": "📁 Non-Steam",
        "tip": "เกมทั่วไป (Local / Portable)"
    }
}


class ScannerThread(QThread):
    progress = pyqtSignal(str, int, int)
    finished_scan = pyqtSignal(list)

    def __init__(self, target_dir: Optional[str] = None, monitored_dirs: Optional[List[str]] = None, existing_checker=None):
        super().__init__()
        self.target_dir = target_dir
        self.monitored_dirs = monitored_dirs
        self.existing_checker = existing_checker
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        def cb(folder_name, current, total):
            self.progress.emit(folder_name, current, total)

        if self.monitored_dirs:
            results = scanner.scan_monitored_directories(
                self.monitored_dirs,
                existing_checker=self.existing_checker,
                progress_callback=cb,
                cancel_flag=lambda: self._is_cancelled
            )
        elif self.target_dir:
            results = scanner.scan_games_directory(
                self.target_dir,
                existing_checker=self.existing_checker,
                progress_callback=cb,
                cancel_flag=lambda: self._is_cancelled
            )
        else:
            results = []
        self.finished_scan.emit(results)


class CoverFetchWorker(QThread):
    cover_downloaded = pyqtSignal(str, str, dict)  # game_id, cover_path, details_dict

    def __init__(self, games_to_fetch: List[Dict]):
        super().__init__()
        self.games_to_fetch = games_to_fetch
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        for game in self.games_to_fetch:
            if self._is_cancelled:
                break
            cover_path = game.get("cover_path")
            if cover_path and not os.path.exists(cover_path):
                details = cover_fetcher.fetch_cover_for_game(game["name"], cover_path)
                if details and os.path.exists(cover_path):
                    self.cover_downloaded.emit(game["id"], cover_path, details)
                time.sleep(0.2)


class ScreenshotViewerDialog(QDialog):
    """Full-size screenshot popup viewer."""
    def __init__(self, image_url_or_path: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Screenshot Preview")
        self.resize(960, 560)
        self.setStyleSheet(f"background-color: {BG_MAIN};")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        self.img_label = QLabel("Loading image...")
        self.img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.img_label.setStyleSheet(f"color: {TEXT_MUTED};")
        layout.addWidget(self.img_label)

        # Load local or remote image
        if os.path.exists(image_url_or_path):
            pix = QPixmap(image_url_or_path)
            self.display_pixmap(pix)
        else:
            # Load from web in background or simple download
            local_cache = str(get_app_dir() / "covers" / f"temp_view_{int(time.time()*1000)}.jpg")
            if cover_fetcher.download_file_to(image_url_or_path, local_cache):
                pix = QPixmap(local_cache)
                self.display_pixmap(pix)
                try:
                    os.remove(local_cache)
                except OSError:
                    pass
            else:
                self.img_label.setText("Failed to load full screenshot.")

    def display_pixmap(self, pix: QPixmap):
        if not pix.isNull():
            scaled = pix.scaled(
                self.width() - 30, self.height() - 30,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            self.img_label.setPixmap(scaled)
            self.img_label.setText("")


class CoverResultCard(QFrame):
    """
    Visual Card in Search Results showing the actual Steam Cover Art,
    Title, AppID, and selection button.
    """
    chosen = pyqtSignal(dict)

    def __init__(self, item: Dict, net_manager: QNetworkAccessManager, parent=None):
        super().__init__(parent)
        self.item = item
        self.net_manager = net_manager
        self.setFixedSize(235, 420)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {BG_PANEL};
                border: 2px solid {BORDER_DEFAULT};
                border-radius: 8px;
            }}
            QFrame:hover {{
                border-color: {BORDER_HOVER};
                background-color: {BG_CARD};
            }}
        """)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        # Image Container (2:3 Aspect Ratio)
        self.img_label = QLabel("⏳ Loading Cover...")
        self.img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.img_label.setFixedSize(219, 305)
        self.img_label.setStyleSheet(f"""
            background-color: #101721;
            color: {TEXT_MUTED};
            border-radius: 6px;
            font-size: 11px;
            font-weight: bold;
        """)
        lay.addWidget(self.img_label)

        # Game Title
        title = QLabel(item['name'])
        title.setStyleSheet(f"font-weight: bold; font-size: 13px; color: {TEXT_PRIMARY};")
        metrics = title.fontMetrics()
        elided = metrics.elidedText(item['name'], Qt.TextElideMode.ElideRight, 215)
        title.setText(elided)
        title.setToolTip(item['name'])
        lay.addWidget(title)

        # Source & Info Badge
        source_badge = QLabel()
        if item.get('source') == 'steamgriddb':
            source_badge.setText("🎨 SteamGridDB (Custom)")
            source_badge.setStyleSheet(f"""
                background-color: #0c2d48;
                color: {ACCENT_BLUE};
                border: 1px solid #1e4976;
                border-radius: 4px;
                padding: 2px 6px;
                font-size: 11px;
                font-weight: bold;
            """)
        else:
            appid_str = f"AppID: {item['appid']}" if item.get('appid') else ""
            source_badge.setText(f"🎮 Steam Official  {appid_str}".strip())
            source_badge.setStyleSheet(f"""
                background-color: #052e16;
                color: {ACCENT_GREEN};
                border: 1px solid #166534;
                border-radius: 4px;
                padding: 2px 6px;
                font-size: 11px;
                font-weight: bold;
            """)
        lay.addWidget(source_badge)

        # Select Button
        btn = QPushButton("✔ Use This Cover")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {ACCENT_GREEN};
                color: white;
                font-weight: bold;
                border-radius: 4px;
                padding: 6px 12px;
                font-size: 12px;
            }}
            QPushButton:hover {{ background-color: {ACCENT_GREEN_HOVER}; }}
        """)
        btn.clicked.connect(lambda: self.chosen.emit(self.item))
        lay.addWidget(btn)

        # Asynchronously fetch image
        self.load_image(item['poster_url'], fallback_url=item.get('header_url'))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.chosen.emit(self.item)

    def load_image(self, url: str, fallback_url: Optional[str] = None):
        if not url:
            self.img_label.setText("No Image")
            return
        req = QNetworkRequest(QUrl(url))
        req.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute, True)
        reply = self.net_manager.get(req)
        reply.finished.connect(lambda: self.on_image_finished(reply, fallback_url))

    def on_image_finished(self, reply, fallback_url):
        data = reply.readAll().data()
        reply.deleteLater()
        pix = QPixmap()
        if data and pix.loadFromData(data) and not pix.isNull():
            scaled = pix.scaled(
                219, 305,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation
            )
            cropped = scaled.copy(0, 0, 219, 305)
            self.img_label.setPixmap(cropped)
            self.img_label.setText("")
        elif fallback_url:
            self.load_image(fallback_url, fallback_url=None)
        else:
            self.img_label.setText("No Cover Found")


class SettingsDialog(QDialog):
    """
    Modern Settings Dialog for GameVault.
    Cardless, clean layout designed with Noto Sans Thai typography.
    """
    def __init__(self, db: LibraryDB, parent=None):
        super().__init__(parent)
        self.db = db
        self.setWindowTitle("การตั้งค่า - GameVault")
        self.resize(860, 620)
        self.setMinimumSize(820, 560)
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {BG_MAIN};
                color: {TEXT_PRIMARY};
                font-family: 'Noto Sans Thai', 'Segoe UI Variable', 'Segoe UI', 'Leelawadee UI', sans-serif;
            }}
            QLabel {{
                color: {TEXT_PRIMARY};
                font-family: 'Noto Sans Thai', 'Segoe UI Variable', 'Segoe UI', 'Leelawadee UI', sans-serif;
            }}
            QLineEdit {{
                background-color: {BG_PANEL};
                border: 1px solid {BORDER_DEFAULT};
                border-radius: 6px;
                padding: 10px 14px;
                color: {TEXT_PRIMARY};
                font-size: 13.5px;
                font-family: 'Noto Sans Thai', 'Segoe UI Variable', 'Segoe UI', 'Leelawadee UI', sans-serif;
            }}
            QLineEdit:focus {{
                border-color: {ACCENT_BLUE};
            }}
            QListWidget {{
                background-color: #0b1118;
                border: 1px solid {BORDER_DEFAULT};
                border-radius: 6px;
                padding: 6px;
                color: {TEXT_PRIMARY};
                font-size: 13px;
                font-family: 'Noto Sans Thai', 'Segoe UI Variable', 'Segoe UI', 'Leelawadee UI', sans-serif;
            }}
            QListWidget::item {{
                padding: 8px 12px;
                border-radius: 4px;
                border-bottom: 1px solid #1e293b;
            }}
            QListWidget::item:selected {{
                background-color: #1e3a5f;
                color: #38bdf8;
                font-weight: bold;
            }}
            QCheckBox {{
                color: {TEXT_PRIMARY};
                font-size: 13.5px;
                font-weight: 600;
                spacing: 10px;
                font-family: 'Noto Sans Thai', 'Segoe UI Variable', 'Segoe UI', 'Leelawadee UI', sans-serif;
            }}
            QCheckBox::indicator {{
                width: 19px;
                height: 19px;
                border-radius: 4px;
                border: 1px solid #475569;
                background-color: #1e293b;
            }}
            QCheckBox::indicator:checked {{
                background-color: {ACCENT_BLUE};
                border-color: {ACCENT_BLUE};
            }}
            QRadioButton {{
                color: {TEXT_PRIMARY};
                font-size: 13.5px;
                font-weight: 600;
                spacing: 8px;
                font-family: 'Noto Sans Thai', 'Segoe UI Variable', 'Segoe UI', 'Leelawadee UI', sans-serif;
            }}
            QRadioButton::indicator {{
                width: 17px;
                height: 17px;
                border-radius: 9px;
                border: 1px solid #475569;
                background-color: #1e293b;
            }}
            QRadioButton::indicator:checked {{
                background-color: {ACCENT_BLUE};
                border-color: {ACCENT_BLUE};
            }}
            QPushButton {{
                background-color: {BG_PANEL};
                border: 1px solid {BORDER_DEFAULT};
                color: {TEXT_PRIMARY};
                font-weight: 600;
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 13px;
                font-family: 'Noto Sans Thai', 'Segoe UI Variable', 'Segoe UI', 'Leelawadee UI', sans-serif;
            }}
            QPushButton:hover {{
                background-color: {BG_CARD};
                border-color: {BORDER_HOVER};
            }}
        """)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(24, 20, 24, 20)
        main_layout.setSpacing(16)

        # ---------------- Top Header ----------------
        header_row = QHBoxLayout()
        header_row.setSpacing(12)

        h_title_box = QVBoxLayout()
        h_title_box.setSpacing(4)
        h_title = QLabel("⚙️ การตั้งค่าระบบ (Settings)")
        h_title.setStyleSheet("font-size: 20px; font-weight: bold; color: #f8fafc;")
        h_sub = QLabel("ปรับแต่งโฟลเดอร์คลังเกม, ระบบเริ่มต้นอัตโนมัติ, การแสดงผล Software และการเชื่อมต่อ SteamGridDB")
        h_sub.setStyleSheet("font-size: 13px; color: #94a3b8;")
        h_title_box.addWidget(h_title)
        h_title_box.addWidget(h_sub)
        header_row.addLayout(h_title_box)
        header_row.addStretch()
        main_layout.addLayout(header_row)

        # Top separator
        top_sep = QFrame()
        top_sep.setFrameShape(QFrame.Shape.HLine)
        top_sep.setStyleSheet("background-color: #1e293b; border: none; max-height: 1px;")
        main_layout.addWidget(top_sep)

        # ---------------- Body (Sidebar + Content Pages) ----------------
        body_layout = QHBoxLayout()
        body_layout.setSpacing(20)

        # Left Sidebar (Nav) - Clean, borderless sidebar
        nav_widget = QWidget()
        nav_widget.setFixedWidth(220)
        nav_layout = QVBoxLayout(nav_widget)
        nav_layout.setContentsMargins(0, 4, 12, 4)
        nav_layout.setSpacing(6)

        self.nav_btns = []
        nav_items = [
            ("📁 โฟลเดอร์คลังเกม", "Monitored Folders"),
            ("⚙️ ระบบ & ถาดงาน", "General & System"),
            ("💻 คลังโปรแกรม", "Software & Icons"),
            ("🎨 คลังภาพ SteamGridDB", "Cover Integration"),
            ("🚀 อัปเดต & เกี่ยวกับ", "Updates & About"),
        ]

        for idx, (title_th, sub_en) in enumerate(nav_items):
            btn = QPushButton(f"{title_th}\n{sub_en}")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(self._nav_btn_style(idx == 0))
            btn.clicked.connect(lambda _, i=idx: self.switch_page(i))
            nav_layout.addWidget(btn)
            self.nav_btns.append(btn)

        nav_layout.addStretch()
        body_layout.addWidget(nav_widget)

        # Vertical Divider between sidebar and content
        v_sep = QFrame()
        v_sep.setFrameShape(QFrame.Shape.VLine)
        v_sep.setStyleSheet("background-color: #1e293b; border: none; max-width: 1px;")
        body_layout.addWidget(v_sep)

        # Right Pages Stack
        self.pages = QStackedWidget()

        # ==================== Page 0: Monitored Game Folders ====================
        page_folders = QWidget()
        pf_layout = QVBoxLayout(page_folders)
        pf_layout.setContentsMargins(8, 4, 8, 4)
        pf_layout.setSpacing(16)

        # Section Header
        sec0_head = QVBoxLayout()
        sec0_head.setSpacing(4)
        sec0_title = QLabel("โฟลเดอร์ตรวจหาเกม (Monitored Folders)")
        sec0_title.setStyleSheet("font-size: 16px; font-weight: bold; color: #38bdf8;")
        sec0_desc = QLabel(
            "GameVault จะคอยตรวจหาเกมใหม่จากโฟลเดอร์เหล่านี้เมื่อสั่งสแกนหรือเมื่อเปิดโปรแกรม\n"
            "ระบบจะเพิ่มเฉพาะเกมใหม่เข้ามายังคลัง โดยไม่ลบหรือเปลี่ยนแปลงเกมเดิมที่คุณปรับแต่งไว้"
        )
        sec0_desc.setWordWrap(True)
        sec0_desc.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 13px; line-height: 1.5;")
        sec0_head.addWidget(sec0_title)
        sec0_head.addWidget(sec0_desc)
        pf_layout.addLayout(sec0_head)

        # List Widget
        self.folder_list = QListWidget()
        self.folder_list.setFixedHeight(180)
        self.refresh_folder_list()
        pf_layout.addWidget(self.folder_list)

        # Folder Actions
        f_btn_box = QHBoxLayout()
        f_btn_box.setSpacing(10)
        add_f_btn = QPushButton("➕ เพิ่มโฟลเดอร์ (Add Folder...)")
        add_f_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_f_btn.setStyleSheet(f"background-color: #064e3b; color: #34d399; border: 1px solid #059669; font-size: 13px; padding: 7px 16px; font-weight: bold;")
        add_f_btn.clicked.connect(self.add_folder)
        f_btn_box.addWidget(add_f_btn)

        remove_f_btn = QPushButton("🗑 ลบที่เลือก (Remove)")
        remove_f_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        remove_f_btn.setStyleSheet("background-color: #3f1d24; border: 1px solid #7f1d1d; color: #fca5a5; font-size: 13px; padding: 7px 16px;")
        remove_f_btn.clicked.connect(self.remove_folder)
        f_btn_box.addWidget(remove_f_btn)
        f_btn_box.addStretch()
        pf_layout.addLayout(f_btn_box)

        # Hairline divider
        sep0 = QFrame()
        sep0.setFrameShape(QFrame.Shape.HLine)
        sep0.setStyleSheet("background-color: #1e293b; border: none; max-height: 1px;")
        pf_layout.addWidget(sep0)

        # Option: Auto-scan on startup
        opt0_box = QVBoxLayout()
        opt0_box.setSpacing(4)
        self.auto_scan_cb = QCheckBox("ตรวจหาเกมใหม่อัตโนมัติเมื่อเปิดโปรแกรม (Auto-check on Startup)")
        auto_scan_val = self.db.get_setting("auto_scan_on_startup", True) if self.db else True
        self.auto_scan_cb.setChecked(auto_scan_val)
        opt0_box.addWidget(self.auto_scan_cb)
        opt0_sub = QLabel("ตรวจเช็คเฉพาะเกมใหม่ที่เพิ่มเข้ามาในโฟลเดอร์ที่บันทึกไว้ในเบื้องหลังอย่างเงียบๆ โดยไม่แสดงหน้าต่างกวนใจ")
        opt0_sub.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12.5px; padding-left: 29px;")
        opt0_box.addWidget(opt0_sub)
        pf_layout.addLayout(opt0_box)

        pf_layout.addStretch()
        self.pages.addWidget(page_folders)

        # ==================== Page 1: General & System Settings ====================
        page_general = QWidget()
        pg_layout = QVBoxLayout(page_general)
        pg_layout.setContentsMargins(8, 4, 8, 4)
        pg_layout.setSpacing(18)

        # Section Header
        sec1_head = QVBoxLayout()
        sec1_head.setSpacing(4)
        sec1_title = QLabel("ระบบและการทำงานเบื้องหลัง (General & System)")
        sec1_title.setStyleSheet("font-size: 16px; font-weight: bold; color: #38bdf8;")
        sec1_desc = QLabel("กำหนดพฤติกรรมการเปิดโปรแกรมและการทำงานร่วมกับ Windows System Tray")
        sec1_desc.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 13px;")
        sec1_head.addWidget(sec1_title)
        sec1_head.addWidget(sec1_desc)
        pg_layout.addLayout(sec1_head)

        # Item 1: Windows Autostart
        item1_box = QVBoxLayout()
        item1_box.setSpacing(4)
        self.run_startup_cb = QCheckBox("เริ่มทำงานอัตโนมัติเมื่อเปิดคอมพิวเตอร์ (Run on Windows Startup)")
        startup_val = self.db.get_setting("run_on_startup", is_windows_autostart_enabled()) if self.db else True
        self.run_startup_cb.setChecked(startup_val)
        item1_box.addWidget(self.run_startup_cb)
        item1_sub = QLabel("เปิดโปรแกรมขึ้นมาทำงานอัตโนมัติใน System Tray อย่างเงียบๆ ทันทีที่เข้าสู่ระบบ Windows")
        item1_sub.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12.5px; padding-left: 29px;")
        item1_box.addWidget(item1_sub)
        pg_layout.addLayout(item1_box)

        # Hairline divider
        sep1_1 = QFrame()
        sep1_1.setFrameShape(QFrame.Shape.HLine)
        sep1_1.setStyleSheet("background-color: #1e293b; border: none; max-height: 1px;")
        pg_layout.addWidget(sep1_1)

        # Item 2: Close to Tray
        item2_box = QVBoxLayout()
        item2_box.setSpacing(4)
        self.min_tray_close_cb = QCheckBox("ย่อลง System Tray เมื่อกดปิดหน้าต่าง [X] (Minimize to Tray on Close)")
        min_tray_val = self.db.get_setting("minimize_to_tray_on_close", True) if self.db else True
        self.min_tray_close_cb.setChecked(min_tray_val)
        item2_box.addWidget(self.min_tray_close_cb)
        item2_sub = QLabel("เมื่อกดปุ่ม [X] ปิดหน้าต่าง โปรแกรมจะยังคงสแตนด์บายอยู่ในถาด Taskbar ขวาล่าง และคลิกขวาเพื่อเลือกเปิดเกมล่าสุดได้ทันที")
        item2_sub.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12.5px; padding-left: 29px;")
        item2_box.addWidget(item2_sub)
        pg_layout.addLayout(item2_box)

        # Hairline divider
        sep1_2 = QFrame()
        sep1_2.setFrameShape(QFrame.Shape.HLine)
        sep1_2.setStyleSheet("background-color: #1e293b; border: none; max-height: 1px;")
        pg_layout.addWidget(sep1_2)

        # Item 3: Platform Badges
        item3_box = QVBoxLayout()
        item3_box.setSpacing(4)
        self.show_badges_cb = QCheckBox("แสดงป้ายกำกับแพลตฟอร์มบนการ์ดเกม (Show Platform Badges)")
        show_badges_val = self.db.get_setting("show_source_badges", True) if self.db else True
        self.show_badges_cb.setChecked(show_badges_val)
        item3_box.addWidget(self.show_badges_cb)
        item3_sub = QLabel("แสดงป้ายระบุค่ายของเกม (Steam, Epic, Ubisoft, GOG, EA, Android, Local, Software) ที่มุมการ์ด")
        item3_sub.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12.5px; padding-left: 29px;")
        item3_box.addWidget(item3_sub)
        pg_layout.addLayout(item3_box)

        pg_layout.addStretch()
        self.pages.addWidget(page_general)

        # ==================== Page 2: Software Settings & Icon Mode ====================
        page_software = QWidget()
        psw_layout = QVBoxLayout(page_software)
        psw_layout.setContentsMargins(8, 4, 8, 4)
        psw_layout.setSpacing(18)

        # Section Header
        sec2_head = QVBoxLayout()
        sec2_head.setSpacing(4)
        sec2_title = QLabel("การจัดการแท็บ Software & โปรแกรม (Software Library)")
        sec2_title.setStyleSheet("font-size: 16px; font-weight: bold; color: #38bdf8;")
        sec2_desc = QLabel("ปรับแต่งการแสดงผลและพฤติกรรมของโปรแกรมทำงานที่คุณเพิ่มเข้ามาในคลัง")
        sec2_desc.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 13px;")
        sec2_head.addWidget(sec2_title)
        sec2_head.addWidget(sec2_desc)
        psw_layout.addLayout(sec2_head)

        # Software Display Mode
        sw_disp_box = QVBoxLayout()
        sw_disp_box.setSpacing(10)
        sw_disp_title = QLabel("รูปแบบการแสดงผลสำหรับรายการ Software (Display Mode):")
        sw_disp_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #f8fafc;")
        sw_disp_box.addWidget(sw_disp_title)

        sw_disp_desc = QLabel(
            "การตั้งค่านี้มีผลเฉพาะรายการในแท็บ 'Software' เท่านั้น สำหรับคลังเกมปกติจะยังคงแสดงเป็นภาพปก Cover เสมอ"
        )
        sw_disp_desc.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12.5px;")
        sw_disp_box.addWidget(sw_disp_desc)

        self.sw_mode_group = QButtonGroup(self)

        # Radio 1: Icon Mode
        r1_box = QVBoxLayout()
        r1_box.setSpacing(3)
        self.radio_icon = QRadioButton("แสดงเป็นไอคอนของโปรแกรมตรงๆ (Program Icon Mode) [แนะนำ]")
        self.sw_mode_group.addButton(self.radio_icon, 0)
        r1_box.addWidget(self.radio_icon)
        r1_sub = QLabel("ดึงไอคอนโปรแกรมความละเอียดสูง (.exe / .lnk) มาแสดงตรงๆ ปรับขยายขนาดตาม Size Slider ได้อย่างอิสระ")
        r1_sub.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12.5px; padding-left: 27px;")
        r1_box.addWidget(r1_sub)
        sw_disp_box.addLayout(r1_box)

        # Radio 2: Cover Mode
        r2_box = QVBoxLayout()
        r2_box.setSpacing(3)
        self.radio_cover = QRadioButton("แสดงเป็นรูปภาพหน้าปกแนวตั้ง (Cover Poster Mode)")
        self.sw_mode_group.addButton(self.radio_cover, 1)
        r2_box.addWidget(self.radio_cover)
        r2_sub = QLabel("แสดงเป็นภาพโปสเตอร์อัตราส่วน 600×900 เหมือนเกม สามารถดาวน์โหลดหรืออัปโหลดรูปปกโปรแกรมเองได้")
        r2_sub.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12.5px; padding-left: 27px;")
        r2_box.addWidget(r2_sub)
        sw_disp_box.addLayout(r2_box)

        current_sw_mode = self.db.get_setting("software_display_mode", "icon") if self.db else "icon"
        if current_sw_mode == "cover":
            self.radio_cover.setChecked(True)
        else:
            self.radio_icon.setChecked(True)

        psw_layout.addLayout(sw_disp_box)

        # Hairline divider
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet("background-color: #1e293b; border: none; max-height: 1px;")
        psw_layout.addWidget(sep2)

        # System Tray Include Software
        tray_sw_box = QVBoxLayout()
        tray_sw_box.setSpacing(4)
        tray_sw_title = QLabel("การแสดงผลบน System Tray (ถาดงานมุมขวาล่าง):")
        tray_sw_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #f8fafc;")
        tray_sw_box.addWidget(tray_sw_title)

        self.tray_include_sw_cb = QCheckBox("รวมโปรแกรม / Software ในเมนูคลิกขวา System Tray (Include Recent Software)")
        tray_inc_sw = self.db.get_setting("tray_include_software", False) if self.db else False
        self.tray_include_sw_cb.setChecked(tray_inc_sw)
        tray_sw_box.addWidget(self.tray_include_sw_cb)

        tray_sw_sub = QLabel("ค่าเริ่มต้น: แสดงเฉพาะ 5 เกมล่าสุดเท่านั้น (ติ๊กถูกหากต้องการให้แสดงโปรแกรมที่คุณใช้งานล่าสุดร่วมด้วย)")
        tray_sw_sub.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12.5px; padding-left: 29px;")
        tray_sw_box.addWidget(tray_sw_sub)
        psw_layout.addLayout(tray_sw_box)

        psw_layout.addStretch()
        self.pages.addWidget(page_software)

        # ==================== Page 3: SteamGridDB Cover Integration & Tutorial ====================
        page_sgdb = QWidget()
        ps_layout = QVBoxLayout(page_sgdb)
        ps_layout.setContentsMargins(8, 4, 8, 4)
        ps_layout.setSpacing(14)

        # Section Header
        sec3_head = QVBoxLayout()
        sec3_head.setSpacing(4)
        sec3_title = QLabel("การเชื่อมต่อคลังภาพปก SteamGridDB (API Key)")
        sec3_title.setStyleSheet("font-size: 16px; font-weight: bold; color: #38bdf8;")
        sec3_desc = QLabel("SteamGridDB เป็นคลังภาพปกเกมแนวตั้ง (Vertical 600×900) และ Fan-art คุณภาพสูงที่ใหญ่ที่สุด")
        sec3_desc.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 13px;")
        sec3_head.addWidget(sec3_title)
        sec3_head.addWidget(sec3_desc)
        ps_layout.addLayout(sec3_head)

        # Tutorial Box (Clean typography-focused walkthrough, no heavy rounded cards)
        tut_layout = QVBoxLayout()
        tut_layout.setSpacing(8)

        tut_header_row = QHBoxLayout()
        tut_title = QLabel("📖 วิธีขอรับ API Key ฟรี (ทำเพียงครั้งเดียว):")
        tut_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #f8fafc;")
        tut_header_row.addWidget(tut_title)
        tut_header_row.addStretch()

        get_key_btn = QPushButton("🌐 เปิดหน้าขอรับ API Key (steamgriddb.com)")
        get_key_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        get_key_btn.setStyleSheet(f"background-color: #0c2738; border: 1px solid #1e608f; color: {ACCENT_BLUE}; font-size: 13px; padding: 6px 14px; font-weight: bold;")
        get_key_btn.clicked.connect(lambda: webbrowser.open("https://www.steamgriddb.com/profile/preferences/api"))
        tut_header_row.addWidget(get_key_btn)
        tut_layout.addLayout(tut_header_row)

        steps_text = QLabel(
            "1. กดปุ่มสีฟ้าด้านบนเพื่อเปิดเว็บ <b>steamgriddb.com</b> แล้วล็อกอินด้วยบัญชี Steam ของคุณ (ฟรี ไม่เสียค่าใช้จ่าย)<br>"
            "2. กดที่ <b>รูปโปรไฟล์</b> ของคุณที่มุมขวาบน ➔ เลือกเมนู <b>Preferences</b><br>"
            "3. เลื่อนลงมาด้านล่างสุดที่หัวข้อ <b>API</b> ➔ กดปุ่ม <b>Create Key</b> (สร้างคีย์ใหม่)<br>"
            "4. คัดลอก (Copy) โค้ด API Key ที่ได้ มาวางลงในช่องกรอกด้านล่างนี้<br>"
            "5. กดปุ่ม <b>🧪 ทดสอบการเชื่อมต่อ</b> เพื่อยืนยันว่าใช้งานได้ แล้วกด <b>💾 บันทึกการตั้งค่า</b>"
        )
        steps_text.setWordWrap(True)
        steps_text.setStyleSheet(f"color: #cbd5e1; font-size: 13px; line-height: 1.7; padding-left: 4px;")
        tut_layout.addWidget(steps_text)
        ps_layout.addLayout(tut_layout)

        # Hairline divider
        sep3 = QFrame()
        sep3.setFrameShape(QFrame.Shape.HLine)
        sep3.setStyleSheet("background-color: #1e293b; border: none; max-height: 1px;")
        ps_layout.addWidget(sep3)

        # API Key Input Row
        input_box = QVBoxLayout()
        input_box.setSpacing(8)

        input_lbl = QLabel("SteamGridDB API Key:")
        input_lbl.setStyleSheet("font-size: 13.5px; font-weight: bold; color: #f8fafc;")
        input_box.addWidget(input_lbl)

        self.key_input = QLineEdit()
        self.key_input.setPlaceholderText("วาง SteamGridDB API Key ที่นี่ (ตัวอย่าง: 1a2b3c4d5e...)...")
        saved_key = self.db.get_setting("sgdb_api_key", "") if self.db else ""
        self.key_input.setText(saved_key)
        input_box.addWidget(self.key_input)

        # Status & Test Button Row
        status_row = QHBoxLayout()
        status_row.setSpacing(10)

        self.status_lbl = QLabel()
        if saved_key:
            self.status_lbl.setText("Status: 🔑 มีการบันทึก API Key แล้ว")
            self.status_lbl.setStyleSheet(f"color: {ACCENT_GREEN}; font-size: 13px; font-weight: bold;")
        else:
            self.status_lbl.setText("Status: ⚠️ ยังไม่ได้ตั้งค่า API Key (จะใช้การค้นหาภาพจาก Steam Store เป็นหลัก)")
            self.status_lbl.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 13px;")
        status_row.addWidget(self.status_lbl)
        status_row.addStretch()

        test_btn = QPushButton("🧪 ทดสอบการเชื่อมต่อ (Test Connection)")
        test_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        test_btn.setStyleSheet(f"background-color: {BG_CARD}; border: 1px solid {BORDER_HOVER}; color: {TEXT_PRIMARY}; font-size: 13px; padding: 7px 16px; font-weight: bold;")
        test_btn.clicked.connect(self.test_key)
        status_row.addWidget(test_btn)
        input_box.addLayout(status_row)

        ps_layout.addLayout(input_box)
        ps_layout.addStretch()

        self.pages.addWidget(page_sgdb)

        # ==================== Page 4: Updates & About ====================
        page_about = QWidget()
        pa_outer = QVBoxLayout(page_about)
        pa_outer.setContentsMargins(0, 0, 0, 0)

        about_scroll = QScrollArea()
        about_scroll.setWidgetResizable(True)
        about_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        about_content = QWidget()
        pa_layout = QVBoxLayout(about_content)
        pa_layout.setContentsMargins(8, 4, 14, 16)
        pa_layout.setSpacing(16)

        # Section Header
        sec4_head = QVBoxLayout()
        sec4_head.setSpacing(4)
        sec4_title = QLabel("อัปเดต & เกี่ยวกับโปรแกรม (Updates & About)")
        sec4_title.setStyleSheet("font-size: 16px; font-weight: bold; color: #38bdf8;")
        sec4_desc = QLabel(
            "GameVault - Game & Software Library by MeN9CH\n"
            "ระบบตรวจสอบและติดตั้งเวอร์ชันใหม่อัตโนมัติผ่าน GitHub Releases"
        )
        sec4_desc.setWordWrap(True)
        sec4_desc.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 13px; line-height: 1.5;")
        sec4_head.addWidget(sec4_title)
        sec4_head.addWidget(sec4_desc)
        pa_layout.addLayout(sec4_head)

        about_card = QFrame()
        about_card.setStyleSheet(f"""
            QFrame {{
                background-color: #0b1118;
                border: 1px solid {BORDER_DEFAULT};
                border-radius: 8px;
                padding: 16px;
            }}
        """)
        ac_lay = QVBoxLayout(about_card)
        ac_lay.setSpacing(10)

        curr_ver = updater.get_current_version()
        v_lbl = QLabel(f"🏷️ <b>เวอร์ชันปัจจุบัน:</b> <span style='color: #38bdf8; font-weight: bold;'>v{curr_ver}</span>")
        v_lbl.setStyleSheet("font-size: 14px;")
        ac_lay.addWidget(v_lbl)

        dev_lbl = QLabel("👤 <b>ผู้พัฒนา:</b> MeN9CH")
        dev_lbl.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 13px;")
        ac_lay.addWidget(dev_lbl)

        repo_link = QLabel("🌐 <b>GitHub Repository:</b> <a style='color: #60a5fa;' href='https://github.com/zepiam/GameVault'>https://github.com/zepiam/GameVault</a>")
        repo_link.setOpenExternalLinks(True)
        repo_link.setStyleSheet("font-size: 13px;")
        ac_lay.addWidget(repo_link)

        pa_layout.addWidget(about_card)

        # Update action box
        update_action_box = QVBoxLayout()
        update_action_box.setSpacing(12)

        self.auto_update_cb = QCheckBox("ตรวจสอบการอัปเดตอัตโนมัติเมื่อเปิดโปรแกรม (Auto-check on startup)")
        self.auto_update_cb.setChecked(self.db.get_setting("auto_check_updates", True) if self.db else True)
        self.auto_update_cb.setCursor(Qt.CursorShape.PointingHandCursor)
        update_action_box.addWidget(self.auto_update_cb)

        check_row = QHBoxLayout()
        check_row.setSpacing(12)

        self.check_update_btn = QPushButton("🔄 ตรวจสอบการอัปเดตทันที (Check for Updates)")
        self.check_update_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.check_update_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {BG_CARD};
                border: 1px solid {ACCENT_BLUE};
                color: {ACCENT_BLUE};
                font-weight: bold;
                padding: 10px 18px;
                font-size: 13px;
                border-radius: 6px;
            }}
            QPushButton:hover {{
                background-color: #1e3a5f;
                color: #ffffff;
            }}
        """)
        self.check_update_btn.clicked.connect(self.manual_check_update)
        check_row.addWidget(self.check_update_btn)

        self.update_status_lbl = QLabel("")
        self.update_status_lbl.setStyleSheet("font-size: 13px; color: #94a3b8;")
        check_row.addWidget(self.update_status_lbl)
        check_row.addStretch()

        update_action_box.addLayout(check_row)
        pa_layout.addLayout(update_action_box)

        # ---------------- Antivirus / Defender Exclusion Card ----------------
        excl_card = QFrame()
        excl_card.setStyleSheet(f"""
            QFrame {{
                background-color: #16130d;
                border: 1px solid #b45309;
                border-radius: 8px;
                padding: 16px;
            }}
        """)
        excl_lay = QVBoxLayout(excl_card)
        excl_lay.setSpacing(10)

        excl_header = QLabel("🛡️ วิธีแก้ที่ผู้ใช้ต้องทำ ไม่เช่นนั้นโปรแกรมจะถูกแอนตี้ไวรัสในเครื่องลบทิ้ง")
        excl_header.setStyleSheet("color: #f59e0b; font-size: 14px; font-weight: bold;")
        excl_lay.addWidget(excl_header)

        excl_sub = QLabel("💡 <b>ต้องเพิ่ม Exception ใน Windows Defender (ทำครั้งเดียว แก้ได้ถาวร):</b>")
        excl_sub.setStyleSheet("color: #fbbf24; font-size: 13px;")
        excl_lay.addWidget(excl_sub)

        steps_text = QLabel(
            "<b>1.</b> กด <code>Windows + I</code> ดูที่แถบด้านซ้ายมือ ไปที่ <b>Privacy & security</b> แล้วเลือก <b>Windows Security</b><br>"
            "<b>2.</b> คลิก <b>Virus & threat protection</b> จะเปิดหน้าใหม่ขึ้นมา<br>"
            "<b>3.</b> ที่หัวข้อ <b>\"Virus & threat protection settings\"</b> กด <b>Manage settings</b><br>"
            "<b>4.</b> เลื่อนลงไปข้างล่างสุดจะเจอหัวข้อ <b>Exclusions</b> คลิก <b>Add or remove exclusions</b><br>"
            "<b>5.</b> คลิก <b>Add an exclusion</b> → เลือก <b>Folder</b><br>"
            "<b>6.</b> จากนั้นนำทางไปที่เก็บโฟลเดอร์โปรแกรมที่มีไฟล์ <code>GameVault.exe</code><br>"
            "<b>7.</b> คลิก <b>Select Folder</b>"
        )
        steps_text.setTextFormat(Qt.TextFormat.RichText)
        steps_text.setWordWrap(True)
        steps_text.setStyleSheet("color: #e2e8f0; font-size: 13px; line-height: 1.6;")
        excl_lay.addWidget(steps_text)

        open_sec_btn = QPushButton("🛡️ คลิกที่นี่เพื่อเปิดหน้า Windows Security ทันที (Open Windows Security)")
        open_sec_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        open_sec_btn.setStyleSheet("""
            QPushButton {
                background-color: #78350f;
                color: #fef3c7;
                border: 1px solid #d97706;
                border-radius: 6px;
                padding: 9px 18px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #92400e;
                color: #ffffff;
            }
        """)
        open_sec_btn.clicked.connect(lambda: subprocess.Popen(["cmd.exe", "/c", "start windowsdefender:"], shell=False))
        excl_lay.addWidget(open_sec_btn)

        note_box = QLabel(
            "✅ <i>หลังจากนี้ Windows Defender หรือ Antivirus จะไม่สแกนแล้วลบโปรแกรมอีกแล้ว เมื่อกดอัพเดทผ่านในโปรแกรม</i><br><br>"
            "<span style='color: #94a3b8; font-size: 12px;'>"
            "💬 <b>หมายเหตุ:</b> โปรแกรมไม่ได้อันตรายอะไรครับ วินโดว์เขาพูดให้มันดูน่ากลัวๆ คนจะไม่กล้าใช้ "
            "จะเรียกค่าไถ่โปรแกรม 400 ดอลล่า ต่อปีจากผู้พัฒนา (ใบรับรอง Code Signing) เพื่อให้ไม่โดนดักว่าเป็นโปรแกรมอันตรายแหน่ะ เลยต้องใช้วิธีนี้เอาครับ"
            "</span>"
        )
        note_box.setTextFormat(Qt.TextFormat.RichText)
        note_box.setWordWrap(True)
        note_box.setStyleSheet("color: #cbd5e1; font-size: 12.5px; line-height: 1.5; margin-top: 4px;")
        excl_lay.addWidget(note_box)

        pa_layout.addWidget(excl_card)
        pa_layout.addStretch()

        about_scroll.setWidget(about_content)
        pa_outer.addWidget(about_scroll)

        self.pages.addWidget(page_about)

        body_layout.addWidget(self.pages, stretch=1)
        main_layout.addLayout(body_layout, stretch=1)

        # Bottom Separator
        bottom_sep = QFrame()
        bottom_sep.setFrameShape(QFrame.Shape.HLine)
        bottom_sep.setStyleSheet("background-color: #1e293b; border: none; max-height: 1px;")
        main_layout.addWidget(bottom_sep)

        # ---------------- Bottom Action Bar ----------------
        btn_box = QHBoxLayout()
        btn_box.setSpacing(12)
        btn_box.addStretch()

        cancel_btn = QPushButton("✕ ยกเลิก (Cancel)")
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.setStyleSheet(f"background-color: transparent; color: {TEXT_MUTED}; border: 1px solid {BORDER_DEFAULT}; font-size: 13px; padding: 8px 18px;")
        cancel_btn.clicked.connect(self.reject)
        btn_box.addWidget(cancel_btn)

        save_btn = QPushButton("💾 บันทึกการตั้งค่า (Save Settings)")
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.setStyleSheet(f"background-color: {ACCENT_GREEN}; color: white; font-weight: bold; font-size: 13px; padding: 8px 22px; border-radius: 6px;")
        save_btn.clicked.connect(self.save_settings)
        btn_box.addWidget(save_btn)

        main_layout.addLayout(btn_box)

    def _nav_btn_style(self, active: bool) -> str:
        if active:
            return f"""
                QPushButton {{
                    background-color: #1e293b;
                    border: none;
                    border-left: 3px solid #38bdf8;
                    border-radius: 4px;
                    padding: 10px 14px;
                    color: #38bdf8;
                    font-weight: bold;
                    font-size: 13px;
                    text-align: left;
                    font-family: 'Noto Sans Thai', 'Segoe UI Variable', 'Segoe UI', 'Leelawadee UI', sans-serif;
                }}
            """
        else:
            return f"""
                QPushButton {{
                    background-color: transparent;
                    border: none;
                    border-left: 3px solid transparent;
                    border-radius: 4px;
                    padding: 10px 14px;
                    color: {TEXT_MUTED};
                    font-weight: 500;
                    font-size: 13px;
                    text-align: left;
                    font-family: 'Noto Sans Thai', 'Segoe UI Variable', 'Segoe UI', 'Leelawadee UI', sans-serif;
                }}
                QPushButton:hover {{
                    background-color: #162030;
                    color: {TEXT_PRIMARY};
                }}
            """

    def switch_page(self, idx: int):
        self.pages.setCurrentIndex(idx)
        for i, btn in enumerate(self.nav_btns):
            btn.setStyleSheet(self._nav_btn_style(i == idx))

    def refresh_folder_list(self):
        self.folder_list.clear()
        if self.db:
            folders = self.db.get_monitored_folders()
            for f in folders:
                self.folder_list.addItem(f)

    def add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Game Folder to Monitor")
        if folder and self.db:
            if self.db.add_monitored_folder(folder):
                self.refresh_folder_list()
            else:
                QMessageBox.information(self, "Notice", "โฟลเดอร์นี้มีอยู่ในรายการติดตามอยู่แล้ว")

    def remove_folder(self):
        current_item = self.folder_list.currentItem()
        if current_item and self.db:
            folder = current_item.text()
            self.db.remove_monitored_folder(folder)
            self.refresh_folder_list()

    def test_key(self):
        key = self.key_input.text().strip()
        if not key:
            self.status_lbl.setText("❌ กรุณาวาง API Key ก่อนกดทดสอบ")
            self.status_lbl.setStyleSheet("color: #ef4444; font-size: 13px;")
            return
        self.status_lbl.setText("⏳ กำลังทดสอบเชื่อมต่อไปยัง SteamGridDB...")
        self.status_lbl.setStyleSheet(f"color: {ACCENT_BLUE}; font-size: 13px;")
        QApplication.processEvents()

        ok, msg = cover_fetcher.test_steamgriddb_key(key)
        if ok:
            self.status_lbl.setText("✅ API Key ใช้งานได้สมบูรณ์ (Connected)")
            self.status_lbl.setStyleSheet(f"color: {ACCENT_GREEN}; font-weight: bold; font-size: 13px;")
            QMessageBox.information(self, "Success", "SteamGridDB API Key ถูกต้องและเชื่อมต่อสำเร็จ!")
        else:
            self.status_lbl.setText(f"❌ {msg}")
            self.status_lbl.setStyleSheet("color: #ef4444; font-size: 13px;")
            QMessageBox.warning(self, "Verification Failed", f"SteamGridDB API Key ไม่ถูกต้องหรือเชื่อมต่อไม่ได้:\n{msg}")

    def manual_check_update(self):
        self.check_update_btn.setEnabled(False)
        self.update_status_lbl.setText("⏳ กำลังตรวจสอบเวอร์ชันล่าสุดจาก GitHub...")
        self.update_status_lbl.setStyleSheet("color: #94a3b8; font-size: 13px;")
        QApplication.processEvents()

        try:
            update_info = updater.check_for_updates()
            if update_info:
                new_v = update_info.get("version", "")
                self.update_status_lbl.setText(f"🎉 พบเวอร์ชันใหม่: v{new_v}!")
                self.update_status_lbl.setStyleSheet("color: #22c55e; font-weight: bold; font-size: 13px;")
                dlg = updater.UpdateDialog(update_info, parent=self)
                dlg.exec()
            else:
                curr_v = updater.get_current_version()
                self.update_status_lbl.setText(f"✅ คุณกำลังใช้งานเวอร์ชันล่าสุดแล้ว (v{curr_v})")
                self.update_status_lbl.setStyleSheet("color: #22c55e; font-weight: bold; font-size: 13px;")
                QMessageBox.information(
                    self, "ไม่มีอัปเดตใหม่",
                    f"GameVault เวอร์ชันปัจจุบันของคุณ (v{curr_v}) เป็นเวอร์ชันล่าสุดแล้วครับ!"
                )
        except Exception as e:
            self.update_status_lbl.setText(f"❌ ไม่สามารถตรวจสอบได้: {e}")
            self.update_status_lbl.setStyleSheet("color: #ef4444; font-size: 13px;")
        finally:
            self.check_update_btn.setEnabled(True)

    def save_settings(self):
        key = self.key_input.text().strip()
        run_startup = self.run_startup_cb.isChecked()
        min_tray = self.min_tray_close_cb.isChecked()
        set_windows_autostart(run_startup)

        if self.db:
            self.db.set_setting("sgdb_api_key", key)
            self.db.set_setting("auto_scan_on_startup", self.auto_scan_cb.isChecked())
            self.db.set_setting("show_source_badges", self.show_badges_cb.isChecked())
            self.db.set_setting("run_on_startup", run_startup)
            self.db.set_setting("minimize_to_tray_on_close", min_tray)
            sw_mode = "cover" if self.radio_cover.isChecked() else "icon"
            self.db.set_setting("software_display_mode", sw_mode)
            self.db.set_setting("tray_include_software", self.tray_include_sw_cb.isChecked())
            self.db.set_setting("auto_check_updates", self.auto_update_cb.isChecked())
        QMessageBox.information(self, "Saved", "บันทึกการตั้งค่าเรียบร้อยแล้ว!")
        self.accept()


class OnlineCoverDialog(QDialog):
    """
    Dialog allowing user to:
    1. Search online by typing game title directly from Steam Store or SteamGridDB (showing visual poster previews).
    2. Paste a Steam Store Link / AppID OR direct image URL from any website (.jpg, .png, SteamGridDB, IGDB, etc.)
       which will be automatically downloaded and resized to 600x900.
    """
    def __init__(self, current_name: str, target_cover_path: Optional[str] = None, db=None, parent=None):
        super().__init__(parent)
        self.target_cover_path = target_cover_path
        self.db = db
        self.custom_image_applied = False
        self.setWindowTitle("Search Game Covers Online")
        self.setMinimumSize(920, 700)
        self.setStyleSheet(f"""
            QDialog {{ background-color: {BG_MAIN}; color: {TEXT_PRIMARY}; }}
            QLabel {{ color: {TEXT_PRIMARY}; }}
            QLineEdit {{
                background-color: {BG_PANEL};
                border: 1px solid {BORDER_DEFAULT};
                border-radius: 6px;
                padding: 8px 12px;
                color: {TEXT_PRIMARY};
                font-size: 13px;
            }}
            QLineEdit:focus {{ border-color: {ACCENT_BLUE}; }}
            QComboBox {{
                background-color: {BG_PANEL};
                border: 1px solid {BORDER_DEFAULT};
                border-radius: 6px;
                padding: 6px 12px;
                color: {TEXT_PRIMARY};
                font-weight: bold;
            }}
            QComboBox QAbstractItemView {{
                background-color: {BG_PANEL};
                color: {TEXT_PRIMARY};
                selection-background-color: {BG_CARD_HOVER};
            }}
            QPushButton {{
                background-color: {ACCENT_BLUE};
                color: #0b1320;
                font-weight: bold;
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 13px;
            }}
            QPushButton:hover {{ background-color: #7dd3fc; }}
            QScrollArea {{ border: none; background-color: transparent; }}
        """)

        self.net_manager = QNetworkAccessManager(self)
        self.selected_appid: Optional[int] = None
        self.selected_details: Optional[Dict] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        # Mode 1: Unified Search (Steam Store + SteamGridDB)
        title_box = QLabel("🔍 Method 1: Search Online Covers (แสดงทั้ง Steam Store Official และ SteamGridDB Fan-Art)")
        title_box.setStyleSheet(f"font-weight: bold; font-size: 14px; color: {ACCENT_BLUE};")
        layout.addWidget(title_box)

        search_bar = QHBoxLayout()
        search_bar.setSpacing(8)

        self.search_input = QLineEdit(current_name)
        self.search_input.setPlaceholderText("พิมพ์ชื่อเกมเพื่อค้นหาปก (e.g. Rune Factory 3 Special)...")
        self.search_input.returnPressed.connect(self.perform_name_search)
        search_bar.addWidget(self.search_input)

        search_btn = QPushButton("🔍 Search All")
        search_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        search_btn.clicked.connect(self.perform_name_search)
        search_bar.addWidget(search_btn)

        open_web_btn = QPushButton("🌐 Open SGDB Web")
        open_web_btn.setToolTip("เปิดหน้าค้นหาบนเว็บไซต์ SteamGridDB เพื่อดูภาพเพิ่มเติม")
        open_web_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        open_web_btn.setStyleSheet(f"background-color: {BG_PANEL}; border: 1px solid {BORDER_DEFAULT}; color: {TEXT_PRIMARY};")
        open_web_btn.clicked.connect(self.open_current_search_in_browser)
        search_bar.addWidget(open_web_btn)

        self.sgdb_key_btn = QPushButton("🔑 SGDB Key")
        self.sgdb_key_btn.setToolTip("ตั้งค่าหรือทดสอบ SteamGridDB API key")
        self.sgdb_key_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.update_sgdb_key_btn_appearance()
        self.sgdb_key_btn.clicked.connect(self.prompt_sgdb_api_key)
        search_bar.addWidget(self.sgdb_key_btn)

        layout.addLayout(search_bar)

        # Mode 2: Paste Steam URL or Direct Image URL
        url_box_lbl = QLabel("🔗 Method 2: Paste Steam Link / AppID หรือ ลิงก์รูปภาพเว็บอื่น (Direct Image URL)")
        url_box_lbl.setStyleSheet(f"font-weight: bold; font-size: 14px; color: {ACCENT_BLUE}; margin-top: 4px;")
        layout.addWidget(url_box_lbl)

        url_bar = QHBoxLayout()
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("Paste Steam URL / AppID หรือ ลิงก์รูปภาพ (.jpg, .png, SteamGridDB, IGDB ฯลฯ)...")
        self.url_input.returnPressed.connect(self.fetch_by_url_or_id)
        url_btn = QPushButton("Fetch from Link")
        url_btn.setStyleSheet(f"background-color: {ACCENT_GREEN}; color: white;")
        url_btn.clicked.connect(self.fetch_by_url_or_id)
        url_bar.addWidget(self.url_input)
        url_bar.addWidget(url_btn)
        layout.addLayout(url_bar)

        # Status Label
        self.status_label = QLabel("Search results with preview covers will appear below:")
        self.status_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px; margin-top: 4px;")
        layout.addWidget(self.status_label)

        # Scroll Area for Results
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.results_container = QWidget()
        self.results_layout = QGridLayout(self.results_container)
        self.results_layout.setSpacing(14)
        self.results_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.scroll.setWidget(self.results_container)
        layout.addWidget(self.scroll)

        # Perform initial search if name provided
        if current_name.strip():
            QtCore.QTimer.singleShot(150, self.perform_name_search)

    def update_sgdb_key_btn_appearance(self):
        has_key = bool(self.db.get_setting("sgdb_api_key", "")) if self.db else False
        if has_key:
            self.sgdb_key_btn.setText("🔑 SGDB Key (Active)")
            self.sgdb_key_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {BG_PANEL};
                    border: 1px solid {ACCENT_GREEN};
                    color: {ACCENT_GREEN};
                    font-size: 11px;
                    font-weight: bold;
                    padding: 6px 12px;
                    border-radius: 6px;
                }}
                QPushButton:hover {{ background-color: {BG_CARD}; }}
            """)
        else:
            self.sgdb_key_btn.setText("🔑 ใส่ SGDB Key")
            self.sgdb_key_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {BG_PANEL};
                    border: 1px solid {ACCENT_BLUE};
                    color: {ACCENT_BLUE};
                    font-size: 11px;
                    font-weight: bold;
                    padding: 6px 12px;
                    border-radius: 6px;
                }}
                QPushButton:hover {{ background-color: {BG_CARD}; }}
            """)

    def prompt_sgdb_api_key(self):
        dlg = SettingsDialog(self.db, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.update_sgdb_key_btn_appearance()
            if self.search_input.text().strip():
                self.perform_name_search()

    def open_current_search_in_browser(self):
        query = self.search_input.text().strip()
        if not query:
            return
        webbrowser.open(f"https://www.steamgriddb.com/search/grids?term={urllib.parse.quote(query)}")

    def perform_name_search(self):
        query = self.search_input.text().strip()
        if not query:
            return

        # Clear existing cards
        for i in reversed(range(self.results_layout.count())):
            w = self.results_layout.itemAt(i).widget()
            if w:
                w.setParent(None)

        self.status_label.setText(f"⏳ กำลังค้นหาปกเกมจากทั้ง Steam Store และ SteamGridDB สำหรับ '{query}'...")
        QApplication.processEvents()

        # 1. Fetch from Steam Store (Official)
        steam_results = cover_fetcher.search_steam_games(query, max_results=6)

        # 2. Fetch from SteamGridDB (Custom / Fan-art) if API key configured
        api_key = self.db.get_setting("sgdb_api_key", "") if self.db else ""
        sgdb_results = []
        if api_key:
            sgdb_results = cover_fetcher.search_steamgriddb_covers(query, api_key, max_results=12)

        # Merge results: Steam Official first, followed by SteamGridDB custom covers
        all_results = steam_results + sgdb_results

        if not all_results:
            msg = f"ไม่พบปกเกมสำหรับ '{query}' (ลองพิมพ์ชื่อเกมแบบอื่น หรือกด '🌐 Open SGDB Web' เพื่อเปิดเว็บดูได้ครับ)"
            if not api_key:
                msg += " | 💡 Tip: ยังไม่ได้ใส่ SteamGridDB API Key (กด '🔑 ใส่ SGDB Key' เพื่อเปิดใช้งาน)"
            self.status_label.setText(msg)
            return

        status_msg = f"พบทั้งหมด {len(all_results)} ปก (Steam Store: {len(steam_results)} ปก | SteamGridDB: {len(sgdb_results)} ปก) — คลิกที่ภาพเพื่อเลือกใช้ได้ทันที:"
        if not api_key:
            status_msg += "  [💡 Tip: ยังไม่ได้ใส่ SGDB Key - กดปุ่ม '🔑 ใส่ SGDB Key' เพื่อดึงปก Community เพิ่มเติม]"
        self.status_label.setText(status_msg)

        for idx, item in enumerate(all_results):
            card = CoverResultCard(item, self.net_manager)
            card.chosen.connect(self.select_item)
            row = idx // 3
            col = idx % 3
            self.results_layout.addWidget(card, row, col)

    def fetch_by_url_or_id(self):
        try:
            text = self.url_input.text().strip()
            if not text:
                return

            # 1. Check if it's a Steam Store Link or AppID
            appid = cover_fetcher.extract_steam_appid(text)
            if appid:
                self.status_label.setText(f"Fetching details for AppID {appid} from Steam...")
                QApplication.processEvents()
                details = cover_fetcher.get_steam_app_details(appid)
                self.selected_appid = appid
                self.selected_details = details or {"appid": appid}
                self.accept()
                return

            # 2. Check if it's an Image URL from any external website
            if text.startswith('http://') or text.startswith('https://'):
                self.status_label.setText("Downloading and resizing image to 600x900...")
                QApplication.processEvents()

                dest = self.target_cover_path or str(
                    get_app_dir() / "covers" / f"custom_web_{int(time.time()*1000)}.jpg"
                )
                success = cover_fetcher.download_and_process_image_url(text, dest, 600, 900)
                if success:
                    self.custom_image_applied = True
                    self.target_cover_path = dest
                    self.accept()
                    return
                else:
                    QMessageBox.warning(
                        self, "Download Failed",
                        "Could not download or open image from this URL.\n"
                        "Please verify that the link points to a valid public image (.jpg, .png, .webp, SteamGridDB, IGDB, etc.)."
                    )
                    return

            QMessageBox.warning(
                self, "Invalid Input",
                "Please paste a valid Steam Store URL, Steam AppID, or direct Image URL (http/https)."
            )
        except Exception as e:
            print(f"[fetch_by_url_or_id] Error: {e}")
            QMessageBox.critical(self, "Error", f"Failed to process URL or Steam ID:\n{e}")

    def select_item(self, item: Dict):
        if item.get('source') == 'steamgriddb':
            dest = self.target_cover_path or str(
                get_app_dir() / "covers" / f"custom_sgdb_{int(time.time()*1000)}.jpg"
            )
            poster_url = item.get('poster_url')
            if poster_url and cover_fetcher.download_and_process_image_url(poster_url, dest, 600, 900):
                self.custom_image_applied = True
                self.target_cover_path = dest
                self.accept()
                return
            else:
                QMessageBox.warning(self, "Error", "Failed to download cover from SteamGridDB.")
                return

        if item.get('appid'):
            self.selected_appid = item['appid']
            self.selected_details = cover_fetcher.get_steam_app_details(item['appid'])
            self.accept()
            return

        self.accept()


class BorderColorDialog(QDialog):
    """
    Dialog allowing user to:
    1. Select a border color for this game.
    2. FREELY NAME each border color with their own custom category / meaning!
    3. Add new colors or delete colors.
    4. Clear border color (Default).
    """
    def __init__(self, current_color: Optional[str] = None, game_name: str = "", db=None, parent=None):
        super().__init__(parent)
        self.selected_color: Optional[str] = current_color
        self.db = db
        self.setWindowTitle("🎨 ตั้งชื่อหมวดหมู่ & เลือกสีกรอบ (Card Border Color)")
        self.setMinimumSize(560, 520)
        self.setStyleSheet(f"""
            QDialog {{ background-color: {BG_MAIN}; color: {TEXT_PRIMARY}; }}
            QLabel {{ color: {TEXT_PRIMARY}; }}
            QPushButton {{
                background-color: {BG_PANEL};
                border: 1px solid {BORDER_DEFAULT};
                color: {TEXT_PRIMARY};
                font-weight: bold;
                border-radius: 6px;
                padding: 6px 12px;
                font-size: 12px;
            }}
            QPushButton:hover {{
                background-color: {BG_CARD};
                border-color: {BORDER_HOVER};
            }}
            QLineEdit {{
                background-color: {BG_PANEL};
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_DEFAULT};
                border-radius: 4px;
                padding: 5px 8px;
                font-size: 12px;
            }}
            QLineEdit:focus {{
                border-color: {ACCENT_BLUE};
            }}
        """)

        # Load categories from DB or defaults
        if self.db:
            raw_cats = self.db.get_border_categories()
            self.categories = [dict(c) for c in raw_cats]
        else:
            self.categories = [dict(c) for c in DEFAULT_BORDER_CATEGORIES]

        self.category_inputs = []  # list of (index, QLineEdit)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        title = QLabel(f"🎨 เลือกสีกรอบสำหรับ '{game_name}'" if game_name else "🎨 สีกรอบและการจัดหมวดหมู่เกม")
        title.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {TEXT_PRIMARY};")
        layout.addWidget(title)

        desc = QLabel(
            "คุณสามารถ<b>ตั้งชื่อหมวดหมู่ให้กับแต่ละสีได้เอง</b>ตามใจชอบ (เช่น เล่นจบแล้ว, RPG, เล่นกับเพื่อน ฯลฯ) "
            "และเลือกสีที่ต้องการใช้กับการ์ดเกมนี้:"
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px; line-height: 1.4;")
        layout.addWidget(desc)

        # Preview swatch box
        self.preview_frame = QFrame()
        self.preview_frame.setFixedHeight(46)
        p_lay = QHBoxLayout(self.preview_frame)
        p_lay.setContentsMargins(14, 4, 14, 4)
        self.preview_lbl = QLabel()
        self.preview_lbl.setStyleSheet("font-weight: bold; font-size: 13px;")
        p_lay.addWidget(self.preview_lbl)
        p_lay.addStretch()
        layout.addWidget(self.preview_frame)
        self.update_preview()

        # Scroll area for color categories
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: 1px solid #1e293b; border-radius: 6px; background-color: #0b1118; }")

        self.cat_container = QWidget()
        self.cat_layout = QVBoxLayout(self.cat_container)
        self.cat_layout.setContentsMargins(8, 8, 8, 8)
        self.cat_layout.setSpacing(8)
        scroll.setWidget(self.cat_container)
        layout.addWidget(scroll, stretch=1)

        self.render_categories()

        # Toolbar under categories list
        action_row = QHBoxLayout()
        add_btn = QPushButton("➕ เพิ่มสีและหมวดหมู่ใหม่ (Add New Color)...")
        add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_btn.setStyleSheet(f"background-color: {BG_CARD}; border: 1px solid {ACCENT_BLUE}; color: {ACCENT_BLUE}; font-weight: bold;")
        add_btn.clicked.connect(self.add_new_category)
        action_row.addWidget(add_btn)

        clear_border_btn = QPushButton("⚪ ล้างสีกรอบ (Default / ไม่มีสี)")
        clear_border_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        clear_border_btn.setStyleSheet(f"background-color: {BG_CARD}; border: 1px dashed {BORDER_DEFAULT}; color: {TEXT_MUTED};")
        clear_border_btn.clicked.connect(lambda: self.select_color(None))
        action_row.addWidget(clear_border_btn)
        action_row.addStretch()
        layout.addLayout(action_row)

        # Bottom buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        apply_btn = QPushButton("✔ บันทึก & นำสีไปใช้ (Apply)")
        apply_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        apply_btn.setStyleSheet(f"background-color: {ACCENT_GREEN}; color: white; font-weight: bold; padding: 7px 18px;")
        apply_btn.clicked.connect(self.save_and_apply)
        btn_row.addWidget(apply_btn)

        layout.addLayout(btn_row)

    def render_categories(self):
        # Clear layout
        while self.cat_layout.count() > 0:
            item = self.cat_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.category_inputs.clear()

        for idx, cat in enumerate(self.categories):
            row = QFrame()
            row.setStyleSheet(f"""
                QFrame {{
                    background-color: {BG_PANEL};
                    border: 1px solid {BORDER_DEFAULT};
                    border-radius: 6px;
                }}
            """)
            r_lay = QHBoxLayout(row)
            r_lay.setContentsMargins(8, 6, 8, 6)
            r_lay.setSpacing(8)

            color_hex = cat.get("color", "#ef4444")

            # Swatch Button (click to pick a different color)
            swatch = QPushButton()
            swatch.setFixedSize(28, 28)
            swatch.setCursor(Qt.CursorShape.PointingHandCursor)
            swatch.setStyleSheet(f"background-color: {color_hex}; border: 2px solid white; border-radius: 4px;")
            swatch.setToolTip("คลิกเพื่อเปลี่ยนโค้ดสีนี้")
            swatch.clicked.connect(lambda _, c_idx=idx: self.change_cat_color(c_idx))
            r_lay.addWidget(swatch)

            # Editable Category Name
            name_input = QLineEdit(cat.get("name", ""))
            name_input.setPlaceholderText("พิมพ์ชื่อหมวดหมู่สำหรับสีนี้...")
            r_lay.addWidget(name_input, stretch=1)
            self.category_inputs.append((idx, name_input))

            # Select button
            sel_btn = QPushButton("เลือกสีนี้")
            sel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            is_cur = (self.selected_color and self.selected_color.lower() == color_hex.lower())
            if is_cur:
                sel_btn.setText("✔ ใช้งานสีนี้")
                sel_btn.setStyleSheet(f"background-color: {color_hex}; color: #000; font-weight: bold; border-radius: 4px; padding: 5px 12px;")
            else:
                sel_btn.setStyleSheet(f"background-color: {BG_CARD}; border: 1px solid {color_hex}; color: {color_hex}; font-weight: bold; border-radius: 4px; padding: 5px 12px;")
            sel_btn.clicked.connect(lambda _, c=color_hex: self.select_color(c))
            r_lay.addWidget(sel_btn)

            # Delete button
            del_btn = QPushButton("✕")
            del_btn.setFixedSize(26, 26)
            del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            del_btn.setStyleSheet("background-color: transparent; border: 1px solid #475569; color: #94a3b8; font-weight: bold; border-radius: 4px;")
            del_btn.setToolTip("ลบสีนี้")
            del_btn.clicked.connect(lambda _, c_idx=idx: self.delete_category(c_idx))
            r_lay.addWidget(del_btn)

            self.cat_layout.addWidget(row)

        self.cat_layout.addStretch()

    def sync_inputs_to_categories(self):
        for idx, input_widget in self.category_inputs:
            if idx < len(self.categories):
                text = input_widget.text().strip()
                self.categories[idx]["name"] = text if text else self.categories[idx]["color"]

    def select_color(self, color_hex: Optional[str]):
        self.sync_inputs_to_categories()
        self.selected_color = color_hex
        self.update_preview()
        self.render_categories()

    def change_cat_color(self, idx: int):
        self.sync_inputs_to_categories()
        old_color = self.categories[idx].get("color", "#ef4444")
        chosen = QColorDialog.getColor(QColor(old_color), self, "Select Color")
        if chosen.isValid():
            new_hex = chosen.name()
            self.categories[idx]["color"] = new_hex
            if self.selected_color and self.selected_color.lower() == old_color.lower():
                self.selected_color = new_hex
            self.update_preview()
            self.render_categories()

    def add_new_category(self):
        self.sync_inputs_to_categories()
        chosen = QColorDialog.getColor(QColor("#06b6d4"), self, "Pick New Category Color")
        if chosen.isValid():
            new_hex = chosen.name()
            self.categories.append({"color": new_hex, "name": "หมวดหมู่ใหม่"})
            self.selected_color = new_hex
            self.update_preview()
            self.render_categories()

    def delete_category(self, idx: int):
        self.sync_inputs_to_categories()
        if 0 <= idx < len(self.categories):
            del self.categories[idx]
            self.render_categories()

    def save_and_apply(self):
        self.sync_inputs_to_categories()
        if self.db:
            self.db.set_border_categories(self.categories)
        self.accept()

    def update_preview(self):
        if self.selected_color:
            self.preview_frame.setStyleSheet(f"""
                QFrame {{
                    background-color: {BG_PANEL};
                    border: 3px solid {self.selected_color};
                    border-radius: 8px;
                }}
            """)
            cat_name = ""
            for c in self.categories:
                if c.get("color", "").lower() == self.selected_color.lower():
                    cat_name = f" ({c.get('name')})"
                    break
            self.preview_lbl.setText(f"สีกรอบที่เลือก: <span style='color: {self.selected_color}; font-weight: bold;'>{self.selected_color}{cat_name}</span>")
        else:
            self.preview_frame.setStyleSheet(f"""
                QFrame {{
                    background-color: {BG_PANEL};
                    border: 2px solid {BORDER_DEFAULT};
                    border-radius: 8px;
                }}
            """)
            self.preview_lbl.setText("สีกรอบที่เลือก: <span style='color: {TEXT_MUTED};'>Default (ไม่มีสีไฮไลท์)</span>")


class ChangeExeDialog(QDialog):
    """
    Dialog allowing user to:
    1. See current executable path.
    2. Pick from all .exe files detected in the game directory.
    3. Manually browse for any executable on disk.
    """
    def __init__(self, game: Dict, parent=None):
        super().__init__(parent)
        self.game = game
        self.selected_exe: Optional[str] = None

        self.setWindowTitle(f"Change Executable - {game['name']}")
        self.setMinimumSize(660, 500)
        self.setStyleSheet(f"""
            QDialog {{ background-color: {BG_MAIN}; color: {TEXT_PRIMARY}; }}
            QLabel {{ color: {TEXT_PRIMARY}; }}
            QPushButton {{
                border-radius: 6px;
                padding: 8px 14px;
                font-weight: bold;
                font-size: 12px;
            }}
            QScrollArea {{ border: none; background: transparent; }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        # Header Title
        hdr = QLabel(f"🎯 Select Executable for '{game['name']}'")
        hdr.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {TEXT_PRIMARY};")
        layout.addWidget(hdr)

        # Current Executable Display Box
        curr_box = QFrame()
        curr_box.setStyleSheet(f"""
            QFrame {{
                background-color: {BG_PANEL};
                border: 1px solid {BORDER_DEFAULT};
                border-radius: 6px;
                padding: 10px;
            }}
        """)
        curr_lay = QVBoxLayout(curr_box)
        curr_lay.setContentsMargins(8, 8, 8, 8)
        curr_lay.setSpacing(4)

        curr_title = QLabel("Current Executable (.exe) Path:")
        curr_title.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px; font-weight: bold;")
        curr_lay.addWidget(curr_title)

        self.curr_path_lbl = QLabel(game.get("exe_path", "None"))
        self.curr_path_lbl.setWordWrap(True)
        self.curr_path_lbl.setStyleSheet(f"color: {ACCENT_BLUE}; font-size: 12px; font-family: Consolas, monospace;")
        curr_lay.addWidget(self.curr_path_lbl)
        layout.addWidget(curr_box)

        # Manual Browse Button
        browse_row = QHBoxLayout()
        browse_btn = QPushButton("📂 Browse / Choose .exe Manually (ค้นหาไฟล์เอง)...")
        browse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        browse_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {ACCENT_BLUE};
                color: #091320;
                font-size: 13px;
                font-weight: bold;
                padding: 9px 16px;
            }}
            QPushButton:hover {{ background-color: #7dd3fc; }}
        """)
        browse_btn.clicked.connect(self.browse_manual)
        browse_row.addWidget(browse_btn)
        browse_row.addStretch()
        layout.addLayout(browse_row)

        # Auto-detected EXEs section
        folder = game.get("folder_path") or os.path.dirname(game.get("exe_path", ""))
        detected_exes = self.find_folder_executables(folder)

        sec_lbl = QLabel(f"Or select from .exe files found in this game folder ({len(detected_exes)} found):")
        sec_lbl.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px; font-weight: bold; margin-top: 4px;")
        layout.addWidget(sec_lbl)

        # Scroll area for exe list
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        self.list_layout = QVBoxLayout(container)
        self.list_layout.setSpacing(8)
        self.list_layout.setContentsMargins(0, 0, 0, 0)

        if not detected_exes:
            empty_lbl = QLabel("No other .exe files found in this game folder.\nPlease use 'Browse...' button above to locate the game's executable.")
            empty_lbl.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px; padding: 10px;")
            self.list_layout.addWidget(empty_lbl)
        else:
            for item in detected_exes:
                row_card = self.create_exe_item(item)
                self.list_layout.addWidget(row_card)

        self.list_layout.addStretch()
        scroll.setWidget(container)
        layout.addWidget(scroll)

        # Bottom buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        close_btn = QPushButton("Cancel")
        close_btn.setStyleSheet(f"background-color: {BG_PANEL}; border: 1px solid {BORDER_DEFAULT}; color: {TEXT_PRIMARY};")
        close_btn.clicked.connect(self.reject)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    def find_folder_executables(self, folder_path: str) -> List[Dict]:
        results = []
        if not folder_path or not os.path.exists(folder_path):
            return results

        current_exe = os.path.normpath(self.game.get("exe_path", "")).lower()

        for root, dirs, files in os.walk(folder_path):
            rel_depth = os.path.relpath(root, folder_path).count(os.sep)
            if rel_depth > 3:
                dirs.clear()
                continue
            for f in files:
                if f.lower().endswith('.exe'):
                    full_path = os.path.join(root, f)
                    is_current = os.path.normpath(full_path).lower() == current_exe
                    rel_path = os.path.relpath(full_path, folder_path)
                    try:
                        size_mb = os.path.getsize(full_path) / (1024 * 1024)
                    except OSError:
                        size_mb = 0

                    results.append({
                        "name": f,
                        "full_path": full_path,
                        "rel_path": rel_path,
                        "size_mb": size_mb,
                        "is_current": is_current
                    })

        # Sort: current at top, then largest file size first
        results.sort(key=lambda x: (not x["is_current"], -x["size_mb"]))
        return results

    def create_exe_item(self, item: Dict) -> QWidget:
        w = QFrame()
        is_cur = item["is_current"]
        w.setStyleSheet(f"""
            QFrame {{
                background-color: {BG_PANEL};
                border: 1px solid {'#10b981' if is_cur else BORDER_DEFAULT};
                border-radius: 6px;
                padding: 6px;
            }}
            QFrame:hover {{
                border-color: {BORDER_HOVER};
                background-color: {BG_CARD};
            }}
        """)
        hlay = QHBoxLayout(w)
        hlay.setContentsMargins(10, 8, 10, 8)
        hlay.setSpacing(10)

        icon_lbl = QLabel("▶" if is_cur else "⚙")
        icon_lbl.setStyleSheet(f"font-size: 16px; color: {'#10b981' if is_cur else TEXT_MUTED};")
        hlay.addWidget(icon_lbl)

        info_lay = QVBoxLayout()
        info_lay.setSpacing(2)

        name_lbl = QLabel(item["name"])
        name_lbl.setStyleSheet(f"font-weight: bold; font-size: 13px; color: {TEXT_PRIMARY};")
        info_lay.addWidget(name_lbl)

        sub_text = f"Path: {item['rel_path']}  |  Size: {item['size_mb']:.1f} MB"
        if is_cur:
            sub_text += "  [Currently Active]"
        sub_lbl = QLabel(sub_text)
        sub_lbl.setStyleSheet(f"color: {'#10b981' if is_cur else TEXT_MUTED}; font-size: 11px;")
        info_lay.addWidget(sub_lbl)
        hlay.addLayout(info_lay)

        hlay.addStretch()

        if not is_cur:
            sel_btn = QPushButton("Select This .exe")
            sel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            sel_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {ACCENT_GREEN};
                    color: white;
                    font-weight: bold;
                    border-radius: 4px;
                    padding: 6px 12px;
                    font-size: 11px;
                }}
                QPushButton:hover {{ background-color: {ACCENT_GREEN_HOVER}; }}
            """)
            sel_btn.clicked.connect(lambda _, p=item["full_path"]: self.apply_selection(p))
            hlay.addWidget(sel_btn)
        else:
            cur_tag = QLabel("Active")
            cur_tag.setStyleSheet("color: #10b981; font-weight: bold; font-size: 12px; padding-right: 8px;")
            hlay.addWidget(cur_tag)

        return w

    def browse_manual(self):
        start_dir = self.game.get("folder_path") or os.path.dirname(self.game.get("exe_path", ""))
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Executable File", start_dir, "Executables (*.exe)"
        )
        if file_path:
            self.apply_selection(file_path)

    def apply_selection(self, exe_path: str):
        self.selected_exe = exe_path
        self.accept()


class GameDetailDialog(QDialog):
    """
    Comprehensive Game Detail View:
    - Large 600x900 poster
    - Big PLAY button
    - Description summary from Steam
    - 3-4 Screenshot thumbnails with full-size viewer
    - Rename with auto-refetch
    - Attach Steam Link / AppID
    """
    def __init__(self, game: Dict, db: LibraryDB, on_update_callback, on_play_callback, parent=None):
        super().__init__(parent)
        self.game = game
        self.db = db
        self.on_update_callback = on_update_callback
        self.on_play_callback = on_play_callback

        self.setWindowTitle(game["name"])
        self.setMinimumSize(850, 600)
        self.setStyleSheet(f"""
            QDialog {{ background-color: {BG_MAIN}; color: {TEXT_PRIMARY}; }}
            QLabel {{ color: {TEXT_PRIMARY}; }}
            QPushButton {{
                border-radius: 6px;
                padding: 8px 14px;
                font-weight: bold;
                font-size: 12px;
            }}
            QScrollArea {{ border: none; background: transparent; }}
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(24)

        # ---------------- Left Column (Poster & Actions) ----------------
        left_col = QVBoxLayout()
        left_col.setSpacing(12)

        self.poster_label = QLabel()
        self.poster_label.setFixedSize(220, 330)
        self.poster_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.update_poster_border()
        left_col.addWidget(self.poster_label)

        play_btn = QPushButton("▶ PLAY GAME")
        play_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        play_btn.setFixedHeight(44)
        play_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {ACCENT_GREEN};
                color: white;
                font-size: 15px;
                font-weight: bold;
                border-radius: 6px;
            }}
            QPushButton:hover {{ background-color: {ACCENT_GREEN_HOVER}; }}
        """)
        play_btn.clicked.connect(self.launch_game)
        left_col.addWidget(play_btn)

        # Action Buttons
        upload_cover_btn = QPushButton("🖼 Upload Custom Image")
        upload_cover_btn.setStyleSheet(f"background-color: {BG_PANEL}; border: 1px solid {BORDER_DEFAULT}; color: {TEXT_PRIMARY};")
        upload_cover_btn.clicked.connect(self.upload_cover)
        left_col.addWidget(upload_cover_btn)

        search_cover_btn = QPushButton("🔍 Search Cover / Link")
        search_cover_btn.setStyleSheet(f"background-color: {BG_PANEL}; border: 1px solid {BORDER_DEFAULT}; color: {ACCENT_BLUE};")
        search_cover_btn.clicked.connect(self.search_online_cover)
        left_col.addWidget(search_cover_btn)

        border_color_btn = QPushButton("🎨 Set Border Color (สีกรอบ)")
        border_color_btn.setStyleSheet(f"background-color: {BG_PANEL}; border: 1px solid {BORDER_DEFAULT}; color: {TEXT_PRIMARY};")
        border_color_btn.clicked.connect(self.choose_border_color)
        left_col.addWidget(border_color_btn)

        open_folder_btn = QPushButton("📂 Open Game Folder")
        open_folder_btn.setStyleSheet(f"background-color: {BG_PANEL}; border: 1px solid {BORDER_DEFAULT}; color: {TEXT_PRIMARY};")
        open_folder_btn.clicked.connect(self.open_folder)
        left_col.addWidget(open_folder_btn)

        left_col.addStretch()
        layout.addLayout(left_col)

        # ---------------- Right Column (Info, Description, Screenshots) ----------------
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_container = QWidget()
        right_lay = QVBoxLayout(right_container)
        right_lay.setContentsMargins(4, 0, 10, 0)
        right_lay.setSpacing(14)

        # Header Title row
        title_row = QHBoxLayout()
        self.title_lbl = QLabel(game["name"])
        self.title_lbl.setStyleSheet(f"font-size: 22px; font-weight: 800; color: {TEXT_PRIMARY};")
        self.title_lbl.setWordWrap(True)
        title_row.addWidget(self.title_lbl)

        # Favorite Toggle Button
        self.fav_btn = QPushButton()
        self.fav_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.update_detail_fav_btn()
        self.fav_btn.clicked.connect(self.toggle_favorite)
        title_row.addWidget(self.fav_btn)

        rename_btn = QPushButton("✏ Rename")
        rename_btn.setStyleSheet(f"background-color: {BG_PANEL}; border: 1px solid {BORDER_DEFAULT}; color: {TEXT_PRIMARY}; padding: 6px 10px;")
        rename_btn.clicked.connect(self.rename_game)
        title_row.addWidget(rename_btn)
        right_lay.addLayout(title_row)

        # Steam & Refresh Toolbar
        tool_row = QHBoxLayout()
        self.refresh_btn = QPushButton("🔄 Refresh Info from Steam")
        self.refresh_btn.setStyleSheet(f"background-color: {BG_PANEL}; border: 1px solid {BORDER_DEFAULT}; color: {ACCENT_BLUE};")
        self.refresh_btn.clicked.connect(self.refresh_from_steam)
        tool_row.addWidget(self.refresh_btn)

        self.attach_link_btn = QPushButton("🔗 Attach Steam Store Link")
        self.attach_link_btn.setStyleSheet(f"background-color: {BG_PANEL}; border: 1px solid {BORDER_DEFAULT}; color: {TEXT_PRIMARY};")
        self.attach_link_btn.clicked.connect(self.attach_steam_link)
        tool_row.addWidget(self.attach_link_btn)

        self.steam_web_btn = QPushButton("🌐 View on Steam")
        self.steam_web_btn.setStyleSheet(f"background-color: {BG_PANEL}; border: 1px solid {BORDER_DEFAULT}; color: {TEXT_MUTED};")
        self.steam_web_btn.clicked.connect(self.open_steam_in_browser)
        tool_row.addWidget(self.steam_web_btn)

        tool_row.addStretch()
        right_lay.addLayout(tool_row)

        # Metadata Card
        meta_frame = QFrame()
        meta_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {BG_PANEL};
                border: 1px solid {BORDER_DEFAULT};
                border-radius: 8px;
                padding: 8px;
            }}
        """)
        meta_lay = QVBoxLayout(meta_frame)
        meta_lay.setSpacing(6)

        self.genres_lbl = QLabel(f"<b>Genres:</b> {game.get('genres') or 'N/A'}")
        self.genres_lbl.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
        meta_lay.addWidget(self.genres_lbl)

        self.release_lbl = QLabel(f"<b>Release Date:</b> {game.get('release_date') or 'N/A'}")
        self.release_lbl.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
        meta_lay.addWidget(self.release_lbl)

        self.dev_lbl = QLabel(f"<b>Developer:</b> {game.get('developers') or 'N/A'}")
        self.dev_lbl.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
        meta_lay.addWidget(self.dev_lbl)

        # Executable Row with Change Button
        exe_box = QHBoxLayout()
        exe_name = os.path.basename(game['exe_path'])
        self.exe_lbl = QLabel(f"<b>Executable:</b> <span style='color: {ACCENT_BLUE}; font-family: Consolas, monospace;'>{exe_name}</span> &nbsp;&nbsp;|&nbsp;&nbsp; <b>Plays:</b> {game.get('play_count', 0)}")
        self.exe_lbl.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
        exe_box.addWidget(self.exe_lbl)

        change_exe_btn = QPushButton("🎯 Change .exe")
        change_exe_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        change_exe_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {BG_CARD};
                border: 1px solid {BORDER_DEFAULT};
                border-radius: 4px;
                color: {ACCENT_BLUE};
                padding: 4px 10px;
                font-size: 11px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {BG_CARD_HOVER};
                border-color: {BORDER_HOVER};
            }}
        """)
        change_exe_btn.clicked.connect(self.change_executable)
        exe_box.addWidget(change_exe_btn)
        exe_box.addStretch()
        meta_lay.addLayout(exe_box)

        # Platform Selector Row
        plat_box = QHBoxLayout()
        plat_lbl = QLabel("<b>Platform / Store:</b>")
        plat_lbl.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
        plat_box.addWidget(plat_lbl)

        self.plat_combo = QComboBox()
        self.plat_combo.setStyleSheet(f"""
            QComboBox {{
                background-color: {BG_CARD};
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_DEFAULT};
                border-radius: 4px;
                padding: 4px 10px;
                font-size: 12px;
                font-weight: bold;
            }}
            QComboBox QAbstractItemView {{
                background-color: {BG_PANEL};
                color: {TEXT_PRIMARY};
                selection-background-color: {BG_CARD_HOVER};
            }}
        """)
        self.plat_combo.addItem("🔄 Auto-detect (ตรวจจับอัตโนมัติ)", "auto")
        self.plat_combo.addItem("♨ Steam", "steam")
        self.plat_combo.addItem("⚡ Epic Games", "epic")
        self.plat_combo.addItem("🌀 Ubisoft", "ubisoft")
        self.plat_combo.addItem("👾 GOG Galaxy", "gog")
        self.plat_combo.addItem("🎯 EA App", "ea")
        self.plat_combo.addItem("📱 Android (BlueStacks)", "bluestacks")
        self.plat_combo.addItem("📁 Local / Standalone PC", "local")

        curr_p = self.game.get("platform") or "auto"
        idx = self.plat_combo.findData(curr_p)
        if idx >= 0:
            self.plat_combo.setCurrentIndex(idx)

        self.plat_combo.currentIndexChanged.connect(self.on_platform_changed)
        plat_box.addWidget(self.plat_combo)
        plat_box.addStretch()
        meta_lay.addLayout(plat_box)

        right_lay.addWidget(meta_frame)

        # Description Section
        desc_hdr = QLabel("About The Game")
        desc_hdr.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {TEXT_PRIMARY};")
        right_lay.addWidget(desc_hdr)

        self.desc_text = QLabel()
        self.desc_text.setWordWrap(True)
        self.desc_text.setStyleSheet(f"""
            background-color: {BG_PANEL};
            border: 1px solid {BORDER_DEFAULT};
            border-radius: 8px;
            padding: 12px;
            color: {TEXT_PRIMARY};
            font-size: 13px;
            line-height: 1.4;
        """)
        self.update_description_display()
        right_lay.addWidget(self.desc_text)

        # Screenshots Section
        ss_hdr = QLabel("Screenshots")
        ss_hdr.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {TEXT_PRIMARY}; margin-top: 6px;")
        right_lay.addWidget(ss_hdr)

        self.ss_layout = QHBoxLayout()
        self.ss_layout.setSpacing(8)
        self.update_screenshots_display()
        right_lay.addLayout(self.ss_layout)

        right_lay.addStretch()
        right_scroll.setWidget(right_container)
        layout.addWidget(right_scroll)

        self.update_poster()

    def update_poster(self):
        cover_path = self.game.get("cover_path")
        if cover_path and os.path.exists(cover_path):
            pix = QPixmap(cover_path)
            if not pix.isNull():
                self.poster_label.setPixmap(
                    pix.scaled(220, 330, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
                )
                self.poster_label.setText("")
                return

        self.poster_label.setPixmap(QPixmap())
        self.poster_label.setText(f"🎮\n{self.game['name']}")

    def update_description_display(self):
        desc = self.game.get("description") or self.game.get("short_description")
        if desc:
            # Clean any stray HTML tags
            clean_desc = re.sub(r'<[^>]+>', '', desc)
            self.desc_text.setText(clean_desc)
        else:
            self.desc_text.setText(
                "No description available yet.\nClick 'Refresh Info from Steam' or 'Attach Steam Store Link' to fetch game details automatically!"
            )

    def update_screenshots_display(self):
        # Clear existing
        for i in reversed(range(self.ss_layout.count())):
            w = self.ss_layout.itemAt(i).widget()
            if w:
                w.setParent(None)

        screenshots = self.game.get("screenshots", [])
        if not screenshots:
            placeholder = QLabel("No screenshots available.")
            placeholder.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
            self.ss_layout.addWidget(placeholder)
            return

        for idx, sc_url in enumerate(screenshots[:4]):
            ss_widget = QLabel()
            ss_widget.setFixedSize(130, 75)
            ss_widget.setCursor(Qt.CursorShape.PointingHandCursor)
            ss_widget.setStyleSheet(f"""
                border: 1px solid {BORDER_DEFAULT};
                border-radius: 6px;
                background-color: {BG_CARD};
            """)
            ss_widget.setAlignment(Qt.AlignmentFlag.AlignCenter)

            # Check if cached locally
            local_cache = os.path.join(self.db.covers_dir, f"{self.game['id']}_ss_{idx}.jpg")
            if os.path.exists(local_cache):
                pix = QPixmap(local_cache)
                if not pix.isNull():
                    ss_widget.setPixmap(
                        pix.scaled(130, 75, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
                    )
            else:
                ss_widget.setText("Click to View")

            # Click to view full image
            full_url = self.game.get("screenshots_full", [])
            target = full_url[idx] if idx < len(full_url) else sc_url
            ss_widget.mousePressEvent = lambda _, u=target, p=local_cache: self.show_fullscreen_screenshot(p if os.path.exists(p) else u)
            self.ss_layout.addWidget(ss_widget)

    def show_fullscreen_screenshot(self, img_path_or_url: str):
        viewer = ScreenshotViewerDialog(img_path_or_url, self)
        viewer.exec()

    def launch_game(self):
        self.accept()
        self.on_play_callback(self.game)

    def upload_cover(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Choose Cover Image", "", "Images (*.png *.jpg *.jpeg *.webp *.bmp)"
        )
        if file_path:
            dest = self.game.get("cover_path")
            if not dest:
                dest = os.path.join(self.db.covers_dir, f"{self.game['id']}.jpg")
                self.game["cover_path"] = dest
            if cover_fetcher.save_custom_cover(file_path, dest):
                self.db.update_game(self.game["id"], cover_path=dest)
                self.update_poster()
                self.on_update_callback(self.game["id"])
                QMessageBox.information(self, "Success", "Game cover updated successfully!")

    def search_online_cover(self):
        dest = self.game.get("cover_path")
        if not dest:
            dest = os.path.join(self.db.covers_dir, f"{self.game['id']}.jpg")
            self.game["cover_path"] = dest

        dlg = OnlineCoverDialog(self.game["name"], target_cover_path=dest, db=self.db, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            if dlg.custom_image_applied:
                self.db.update_game(self.game["id"], cover_path=dest)
                self.update_poster()
                self.on_update_callback(self.game["id"])
                QMessageBox.information(self, "Success", "Custom web cover downloaded, resized to 600x900, and applied successfully!")
            elif dlg.selected_appid:
                self.apply_steam_details(dlg.selected_appid, dlg.selected_details)

    def attach_steam_link(self):
        try:
            url, ok = QtWidgets.QInputDialog.getText(
                self, "Attach Link",
                "Paste Steam Store URL, AppID, or Direct Image URL (http/https):"
            )
            if ok and url.strip():
                clean = url.strip()
                appid = cover_fetcher.extract_steam_appid(clean)
                if appid:
                    details = cover_fetcher.get_steam_app_details(appid)
                    self.apply_steam_details(appid, details)
                elif clean.startswith('http://') or clean.startswith('https://'):
                    dest = self.game.get("cover_path") or os.path.join(self.db.covers_dir, f"{self.game['id']}.jpg")
                    self.game["cover_path"] = dest
                    if cover_fetcher.download_and_process_image_url(clean, dest, 600, 900):
                        self.db.update_game(self.game["id"], cover_path=dest)
                        self.update_poster()
                        self.on_update_callback(self.game["id"])
                        QMessageBox.information(self, "Success", "Image downloaded from URL, resized to 600x900, and applied successfully!")
                    else:
                        QMessageBox.warning(self, "Download Failed", "Could not download or open image from the provided URL.")
                else:
                    QMessageBox.warning(self, "Invalid Input", "Please enter a valid Steam Store URL, AppID, or Image URL.")
        except Exception as e:
            print(f"[attach_steam_link] Error: {e}")
            QMessageBox.critical(self, "Error", f"Failed to attach link:\n{e}")

    def refresh_from_steam(self):
        try:
            appid = self.game.get("appid")
            if appid:
                details = cover_fetcher.get_steam_app_details(appid)
                if details:
                    self.apply_steam_details(appid, details)
                    return

            # Search by game name
            details = cover_fetcher.fetch_cover_for_game(self.game["name"], self.game["cover_path"])
            if details and isinstance(details, dict) and details.get("appid"):
                self.apply_steam_details(details["appid"], details)
            else:
                QMessageBox.information(
                    self, "Notice",
                    f"Could not find an exact match for '{self.game['name']}'. Please use 'Search Cover / Link' to pick manually."
                )
        except Exception as e:
            print(f"[refresh_from_steam] Error: {e}")
            QMessageBox.critical(self, "Error", f"Failed to refresh Steam details:\n{e}")

    def apply_steam_details(self, appid: int, details: Optional[Dict]):
        try:
            dest = self.game.get("cover_path")
            if not dest:
                dest = os.path.join(self.db.covers_dir, f"{self.game['id']}.jpg")
                self.game["cover_path"] = dest

            cover_fetcher.download_steam_cover(appid, dest)

            updates = {"appid": appid, "cover_path": dest}
            if details:
                updates["description"] = details.get("short_description", "")
                updates["genres"] = details.get("genres", "")
                updates["release_date"] = details.get("release_date", "")
                updates["developers"] = details.get("developers", "")
                updates["screenshots"] = details.get("screenshots", [])
                updates["screenshots_full"] = details.get("screenshots_full", [])
                updates["steam_url"] = details.get("steam_url", "")

                # Cache screenshot thumbnails locally
                cover_fetcher.cache_game_screenshots(self.game["id"], details.get("screenshots", []), self.db.covers_dir)

            updated_game = self.db.update_game(self.game["id"], **updates)
            if updated_game:
                self.game = updated_game

            self.update_poster()
            self.update_description_display()
            self.update_screenshots_display()
            if hasattr(self, "genres_lbl") and self.genres_lbl:
                self.genres_lbl.setText(f"<b>Genres:</b> {self.game.get('genres') or 'N/A'}")
            if hasattr(self, "release_lbl") and self.release_lbl:
                self.release_lbl.setText(f"<b>Release Date:</b> {self.game.get('release_date') or 'N/A'}")
            if hasattr(self, "dev_lbl") and self.dev_lbl:
                self.dev_lbl.setText(f"<b>Developer:</b> {self.game.get('developers') or 'N/A'}")

            self.on_update_callback(self.game["id"])
            QMessageBox.information(self, "Updated", f"Steam cover, description, and screenshots applied successfully!")
        except Exception as e:
            print(f"[apply_steam_details] Error: {e}")
            QMessageBox.critical(self, "Error", f"Failed to apply Steam details:\n{e}")

    def rename_game(self):
        is_sw = bool(self.game.get("is_software") or self.game.get("item_type") == "software")
        dialog_title = "Rename Software" if is_sw else "Rename Game"
        prompt_label = "Enter new software name:" if is_sw else "Enter new game title:"
        new_name, ok = QtWidgets.QInputDialog.getText(
            self, dialog_title, prompt_label, text=self.game["name"]
        )
        if ok and new_name.strip() and new_name.strip() != self.game["name"]:
            self.game["name"] = new_name.strip()
            self.db.update_game(self.game["id"], name=self.game["name"])
            self.title_lbl.setText(self.game["name"])
            self.setWindowTitle(self.game["name"])
            self.on_update_callback(self.game["id"])

            if not is_sw:
                # Ask user if they want to re-fetch from Steam based on the new name (only for games)
                prompt = QMessageBox.question(
                    self, "Search Cover",
                    f"Would you like to auto-fetch new cover & info from Steam for '{self.game['name']}'?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                if prompt == QMessageBox.StandardButton.Yes:
                    self.refresh_from_steam()

    def open_steam_in_browser(self):
        appid = self.game.get("appid")
        if appid:
            webbrowser.open(f"https://store.steampowered.com/app/{appid}/")
        else:
            clean = urllib.parse.quote(self.game["name"])
            webbrowser.open(f"https://store.steampowered.com/search/?term={clean}")

    def change_executable(self):
        dlg = ChangeExeDialog(self.game, self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.selected_exe:
            new_exe = dlg.selected_exe
            self.game["exe_path"] = new_exe
            self.db.update_game(self.game["id"], exe_path=new_exe)

            exe_name = os.path.basename(new_exe)
            self.exe_lbl.setText(f"<b>Executable:</b> <span style='color: {ACCENT_BLUE}; font-family: Consolas, monospace;'>{exe_name}</span> &nbsp;&nbsp;|&nbsp;&nbsp; <b>Plays:</b> {self.game.get('play_count', 0)}")
            self.on_update_callback(self.game["id"])
            QMessageBox.information(self, "Success", f"Executable updated to:\n{new_exe}")

    def open_folder(self):
        folder = self.game.get("folder_path")
        if folder and os.path.exists(folder):
            os.startfile(folder)
        else:
            exe_dir = os.path.dirname(self.game["exe_path"])
            if os.path.exists(exe_dir):
                os.startfile(exe_dir)

    def update_poster_border(self):
        color = self.game.get("border_color")
        border_css = f"3px solid {color}" if color else f"2px solid {BORDER_DEFAULT}"
        self.poster_label.setStyleSheet(f"""
            background-color: {BG_CARD};
            border: {border_css};
            border-radius: 8px;
        """)

    def on_platform_changed(self):
        new_val = self.plat_combo.currentData()
        plat_override = None if new_val == "auto" else new_val
        self.db.update_game(self.game["id"], platform=plat_override)
        self.game["platform"] = plat_override
        self.update_poster_border()
        self.on_update_callback(self.game["id"])

    def choose_border_color(self):
        dlg = BorderColorDialog(self.game.get("border_color"), game_name=self.game["name"], db=self.db, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            new_color = dlg.selected_color
            self.game["border_color"] = new_color
            self.db.update_game(self.game["id"], border_color=new_color)
            self.update_poster_border()
            self.on_update_callback(self.game["id"])

    def update_detail_fav_btn(self):
        if self.game.get("is_favorite"):
            self.fav_btn.setText("★ Favorited")
            self.fav_btn.setStyleSheet("""
                background-color: #854d0e;
                color: #fef08a;
                border: 1px solid #ca8a04;
                padding: 6px 12px;
                font-weight: bold;
                border-radius: 6px;
            """)
        else:
            self.fav_btn.setText("☆ Favorite")
            self.fav_btn.setStyleSheet(f"""
                background-color: {BG_PANEL};
                border: 1px solid {BORDER_DEFAULT};
                color: {TEXT_PRIMARY};
                padding: 6px 12px;
                border-radius: 6px;
            """)

    def toggle_favorite(self):
        new_val = self.db.toggle_favorite(self.game["id"])
        self.game["is_favorite"] = new_val
        self.update_detail_fav_btn()
        if self.on_update_callback:
            self.on_update_callback(self.game["id"])


class GameCard(QFrame):
    """
    Steam-style Game Poster Card.
    Supports dynamic resizing via set_card_size, Steam visual badge & border, and favorites.
    """
    clicked = pyqtSignal(dict)
    play_requested = pyqtSignal(dict)
    action_requested = pyqtSignal(str, dict)  # action_name, game

    def __init__(self, game: Dict, db=None, card_width: int = 180, parent=None):
        super().__init__(parent)
        self.game = game
        self.db = db
        self.card_width = card_width
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setObjectName("GameCard")

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(6, 6, 6, 8)
        self.main_layout.setSpacing(4)

        # Image poster container
        self.image_container = QWidget()
        self.img_layout = QVBoxLayout(self.image_container)
        self.img_layout.setContentsMargins(0, 0, 0, 0)

        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setStyleSheet("border-radius: 6px;")
        self.img_layout.addWidget(self.image_label)

        self.main_layout.addWidget(self.image_container)

        # Badge row: Steam/Local label on left, Favorite Star indicator on right (right-click to toggle)
        self.badge_box = QHBoxLayout()
        self.badge_box.setContentsMargins(2, 0, 2, 0)
        self.badge_box.setSpacing(4)

        self.source_badge = QLabel()
        self.source_badge.setFixedHeight(18)
        self.badge_box.addWidget(self.source_badge)

        self.badge_box.addStretch()

        self.fav_badge = QLabel("⭐")
        self.fav_badge.setFixedHeight(18)
        self.fav_badge.setStyleSheet("font-size: 11px;")
        self.fav_badge.setToolTip("เกมนี้อยู่ในรายการโปรด (คลิกขวาเพื่อจัดการ)")
        self.badge_box.addWidget(self.fav_badge)

        self.main_layout.addLayout(self.badge_box)

        # Game Title Label
        self.title_label = QLabel(game["name"])
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setStyleSheet(f"""
            color: {TEXT_PRIMARY};
            font-size: 13px;
            font-weight: bold;
            padding: 0 4px;
        """)
        self.title_label.setWordWrap(False)
        self.main_layout.addWidget(self.title_label)

        self.apply_border_style()
        self.update_badges()
        self.set_card_size(card_width)
        self.hide()

    def update_badges(self):
        show_source = True
        if self.db:
            show_source = self.db.get_setting("show_source_badges", True)

        if not show_source:
            self.source_badge.setVisible(False)
        else:
            self.source_badge.setVisible(True)
            platform = get_game_platform(self.game)
            meta = PLATFORM_META.get(platform, PLATFORM_META["local"])
            self.source_badge.setText(meta["label"])
            self.source_badge.setStyleSheet(f"""
                background-color: {meta['bg']};
                color: {meta['text']};
                border: 1px solid {meta['border']};
                border-radius: 4px;
                padding: 1px 6px;
                font-size: 10px;
                font-weight: 800;
            """)
            self.source_badge.setToolTip(meta["tip"])

        # Favorite indicator label (no click button under cover, user right-clicks)
        is_fav = bool(self.game.get("is_favorite", False))
        self.fav_badge.setVisible(is_fav)

    def apply_border_style(self):
        color = self.game.get("border_color")
        if color:
            self.setStyleSheet(f"""
                QFrame#GameCard {{
                    background-color: {BG_CARD};
                    border: 3px solid {color};
                    border-radius: 10px;
                }}
                QFrame#GameCard:hover {{
                    background-color: {BG_CARD_HOVER};
                    border: 3px solid {color};
                }}
            """)
        else:
            platform = get_game_platform(self.game)
            meta = PLATFORM_META.get(platform, PLATFORM_META["local"])
            glow = meta.get("glow")
            if glow:
                self.setStyleSheet(f"""
                    QFrame#GameCard {{
                        background-color: {meta['bg']};
                        border: 2px solid {meta['border']};
                        border-radius: 10px;
                    }}
                    QFrame#GameCard:hover {{
                        background-color: {BG_CARD_HOVER};
                        border: 2px solid {glow};
                    }}
                """)
            else:
                self.setStyleSheet(f"""
                    QFrame#GameCard {{
                        background-color: {BG_CARD};
                        border: 2px solid {BORDER_DEFAULT};
                        border-radius: 10px;
                    }}
                    QFrame#GameCard:hover {{
                        background-color: {BG_CARD_HOVER};
                        border: 2px solid {BORDER_HOVER};
                    }}
                """)

    def set_card_size(self, width: int):
        self.card_width = width
        # Poster aspect ratio is 2:3
        poster_height = int(width * 1.5)
        card_height = poster_height + 56

        self.setFixedSize(width, card_height)
        self.image_container.setFixedHeight(poster_height)

        # Truncate title
        metrics = self.title_label.fontMetrics()
        elided = metrics.elidedText(self.game["name"], Qt.TextElideMode.ElideRight, width - 15)
        self.title_label.setText(elided)

        self.refresh_cover()

    def refresh_cover(self):
        is_sw = bool(self.game.get("is_software") or self.game.get("item_type") == "software")
        poster_height = int(self.card_width * 1.5)
        poster_width = self.card_width - 12

        if is_sw:
            sw_mode = self.db.get_setting("software_display_mode", "icon") if self.db else "icon"
            if sw_mode == "icon":
                icon_dim = max(56, min(180, int(self.card_width * 0.62)))
                pix = get_executable_icon(
                    self.game.get("exe_path", ""),
                    self.game.get("lnk_path", ""),
                    target_size=icon_dim
                )
                if not pix.isNull():
                    self.image_label.setPixmap(pix)
                    self.image_label.setText("")
                    self.image_label.setStyleSheet("""
                        background-color: #0f172a;
                        border: 1px solid #1e293b;
                        border-radius: 8px;
                    """)
                    return
                else:
                    self.image_label.setPixmap(QPixmap())
                    self.image_label.setText(f"💻\n{self.game['name']}")
                    self.image_label.setStyleSheet(f"""
                        background-color: #0f172a;
                        color: #818cf8;
                        font-size: 11px;
                        font-weight: bold;
                        border-radius: 8px;
                        padding: 6px;
                    """)
                    return

        cover_path = self.game.get("cover_path")
        if cover_path:
            cropped = get_cached_cover_pixmap(cover_path, poster_width, poster_height)
            if cropped and not cropped.isNull():
                self.image_label.setPixmap(cropped)
                self.image_label.setText("")
                self.image_label.setStyleSheet("border-radius: 6px;")
                return

        # Sleek placeholder
        icon_sym = "💻" if is_sw else "🎮"
        self.image_label.setPixmap(QPixmap())
        self.image_label.setText(f"{icon_sym}\n{self.game['name']}")
        self.image_label.setStyleSheet(f"""
            background-color: #121820;
            color: {TEXT_MUTED};
            font-size: 11px;
            font-weight: bold;
            border-radius: 6px;
            padding: 6px;
        """)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.game)
        elif event.button() == Qt.MouseButton.RightButton:
            self.show_context_menu(event.globalPosition().toPoint())

    def show_context_menu(self, pos: QPoint):
        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{
                background-color: {BG_PANEL};
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_DEFAULT};
                border-radius: 6px;
                padding: 4px;
            }}
            QMenu::item {{
                padding: 8px 24px;
                border-radius: 4px;
            }}
            QMenu::item:selected {{
                background-color: {BG_CARD_HOVER};
                color: {ACCENT_BLUE};
            }}
        """)

        is_sw = bool(self.game.get("is_software") or self.game.get("item_type") == "software")
        act_play = menu.addAction("▶ เปิดโปรแกรม (Launch)" if is_sw else "▶ Play Game")
        menu.addSeparator()

        # Toggle between Game and Software
        if is_sw:
            act_toggle_type = menu.addAction("🎮 เปลี่ยนเป็นหมวด Game")
        else:
            act_toggle_type = menu.addAction("💻 เปลี่ยนเป็นหมวด Software")
        act_toggle_type.triggered.connect(lambda: self.action_requested.emit("toggle_type", self.game))
        menu.addSeparator()

        if self.game.get("is_favorite"):
            act_fav = menu.addAction("★ Remove from Favorites")
        else:
            act_fav = menu.addAction("⭐ Add to Favorites (ปักหมุดไว้บนสุด)")
        act_fav.triggered.connect(lambda: self.action_requested.emit("toggle_favorite", self.game))
        menu.addSeparator()

        # Border Color submenu
        color_menu = menu.addMenu("🎨 Border Color (สีกรอบ)")
        curr_color = (self.game.get("border_color") or "").lower()

        categories = self.db.get_border_categories() if self.db else DEFAULT_BORDER_CATEGORIES
        for item in categories:
            hex_code = item.get("color")
            label = item.get("name") or hex_code
            is_active = bool(hex_code and hex_code.lower() == curr_color)
            prefix = "✔ " if is_active else "   "
            act = color_menu.addAction(f"{prefix}■ {label}")
            act.triggered.connect(lambda _, c=hex_code: self.action_requested.emit(f"set_border_color:{c}", self.game))

        color_menu.addSeparator()
        is_none_active = not bool(curr_color)
        prefix_none = "✔ " if is_none_active else "   "
        act_none = color_menu.addAction(f"{prefix_none}⚪ ล้างสีกรอบ (Default / ไม่มีสี)")
        act_none.triggered.connect(lambda: self.action_requested.emit("set_border_color:None", self.game))

        color_menu.addSeparator()
        act_custom_color = color_menu.addAction("⚙ ตั้งชื่อหมวดหมู่ & จัดการสี (Manage Colors)...")
        act_custom_color.triggered.connect(lambda: self.action_requested.emit("choose_border_color", self.game))

        # Platform / Store submenu
        plat_menu = menu.addMenu("🏷️ แพลตฟอร์ม (Platform / Store)")
        curr_plat = get_game_platform(self.game)
        manual_override = self.game.get("platform")

        platform_options = [
            ("auto", "🔄 Auto-detect (ตรวจจับอัตโนมัติ)"),
            ("steam", "♨ Steam"),
            ("epic", "⚡ Epic Games"),
            ("ubisoft", "🌀 Ubisoft"),
            ("gog", "👾 GOG Galaxy"),
            ("ea", "🎯 EA App"),
            ("bluestacks", "📱 Android (BlueStacks)"),
            ("local", "📁 Local / Standalone PC"),
        ]
        for p_id, p_label in platform_options:
            if p_id == "auto":
                is_active = not bool(manual_override)
            else:
                is_active = (manual_override == p_id) if manual_override else (curr_plat == p_id)
            prefix = "✔ " if is_active else "   "
            p_act = plat_menu.addAction(f"{prefix}{p_label}")
            p_act.triggered.connect(lambda _, pid=p_id: self.action_requested.emit(f"set_platform:{pid}", self.game))

        menu.addSeparator()
        act_upload_cover = menu.addAction("🖼 Change Cover (Upload Image)")
        act_search_cover = menu.addAction("🔍 Search Cover Online / Link")
        act_refresh_steam = None
        if not is_sw:
            act_refresh_steam = menu.addAction("🔄 Auto-Update from Steam (ใช้ชื่อนี้)")
        act_rename = menu.addAction("✏ Rename Software" if is_sw else "✏ Rename Game")
        act_change_exe = menu.addAction("🎯 Change Executable (.exe)")
        act_open_dir = menu.addAction("📂 Open Folder" if is_sw else "📂 Open Game Folder")
        menu.addSeparator()
        act_remove = menu.addAction("🗑 Remove from Library")

        action = menu.exec(pos)
        if action == act_play:
            self.play_requested.emit(self.game)
        elif action == act_upload_cover:
            self.action_requested.emit("upload_cover", self.game)
        elif action == act_search_cover:
            self.action_requested.emit("search_cover", self.game)
        elif act_refresh_steam and action == act_refresh_steam:
            self.action_requested.emit("refresh_steam", self.game)
        elif action == act_rename:
            self.action_requested.emit("rename", self.game)
        elif action == act_change_exe:
            self.action_requested.emit("change_exe", self.game)
        elif action == act_open_dir:
            self.action_requested.emit("open_dir", self.game)
        elif action == act_remove:
            self.action_requested.emit("remove", self.game)


class SilentUpdateCheckThread(QThread):
    update_found = pyqtSignal(dict)

    def run(self):
        try:
            info = updater.check_for_updates()
            if info:
                self.update_found.emit(info)
        except Exception as e:
            print(f"[SilentUpdateCheckThread] Error: {e}")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("GameVault - Game & Software Library by MeN9CH")
        self.resize(1180, 780)
        self.setMinimumSize(880, 560)

        # Init Database
        base_dir = get_app_dir()
        db_path = str(base_dir / "games.json")
        covers_dir = str(base_dir / "covers")
        self.db = LibraryDB(db_path=db_path, covers_dir=covers_dir)

        icon_path = get_asset_path("icon.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        # Card size setting
        self.card_size = self.db.get_setting("card_size", 180)
        self.current_filter_category = "all"  # "all", "favorite", "software", "steam", "other"
        self.tab_buttons: Dict[str, QPushButton] = {}

        self.scanner_thread: Optional[ScannerThread] = None
        self.cover_thread: Optional[CoverFetchWorker] = None
        self.update_check_thread: Optional[SilentUpdateCheckThread] = None
        self.card_widgets: Dict[str, GameCard] = {}

        self.setAcceptDrops(True)
        self._force_quit = False

        # Debounce timer for instant search responsiveness (smooth 60+ FPS without typing stutter)
        self.search_timer = QtCore.QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(120)
        self.search_timer.timeout.connect(lambda: self.rearrange_grid(update_tabs=False))

        self.setup_ui()
        self.setup_system_tray()
        self.load_games_to_ui()
        self.check_missing_covers()

        # Startup auto-check for new games if enabled
        if self.db.get_setting("auto_scan_on_startup", True):
            QtCore.QTimer.singleShot(1000, lambda: self.start_monitored_scan(silent=True))

        # Startup auto-check for application updates in background
        if self.db.get_setting("auto_check_updates", True):
            QtCore.QTimer.singleShot(3000, self.check_app_updates_silently)

    def check_app_updates_silently(self):
        self.update_check_thread = SilentUpdateCheckThread(self)
        self.update_check_thread.update_found.connect(self.on_startup_update_found)
        self.update_check_thread.start()

    def on_startup_update_found(self, update_info: dict):
        new_v = update_info.get("version", "")
        reply = QMessageBox.question(
            self,
            "🚀 พบอัปเดตใหม่ - GameVault",
            f"พบ GameVault เวอร์ชันใหม่ (v{new_v}) ออกแล้ว!\n\nต้องการดูรายละเอียดการอัปเดตและติดตั้งทันทีหรือไม่?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            dlg = updater.UpdateDialog(update_info, parent=self)
            dlg.exec()

    def setup_ui(self):
        self.setStyleSheet(f"""
            QMainWindow {{ background-color: {BG_MAIN}; }}
            QWidget {{ font-family: 'Noto Sans Thai', 'Segoe UI Variable', 'Segoe UI', 'Leelawadee UI', sans-serif; }}
            QScrollBar:vertical {{
                background: {BG_MAIN};
                width: 10px;
                border-radius: 5px;
            }}
            QScrollBar::handle:vertical {{
                background: {BORDER_DEFAULT};
                min-height: 20px;
                border-radius: 5px;
            }}
            QScrollBar::handle:vertical:hover {{ background: {ACCENT_BLUE}; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        """)

        central_widget = QWidget()
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(16, 14, 16, 14)
        main_layout.setSpacing(10)

        # ---------------- Top Navigation Bar ----------------
        header_widget = QWidget()
        header_widget.setFixedHeight(44)
        header = QHBoxLayout(header_widget)
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)

        # Drive Selector Dropdown
        drive_lbl = QLabel("Drive:")
        drive_lbl.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px; font-weight: 600;")
        header.addWidget(drive_lbl)

        self.drive_combo = QComboBox()
        self.drive_combo.setStyleSheet(f"""
            QComboBox {{
                background-color: {BG_PANEL};
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_DEFAULT};
                border-radius: 6px;
                padding: 5px 8px;
                font-weight: bold;
                min-width: 60px;
                font-size: 12px;
            }}
            QComboBox::drop-down {{ border: none; }}
            QComboBox QAbstractItemView {{
                background-color: {BG_PANEL};
                color: {TEXT_PRIMARY};
                selection-background-color: {BG_CARD_HOVER};
            }}
        """)
        drives = scanner.get_available_drives()
        for d in drives:
            self.drive_combo.addItem(d)
        header.addWidget(self.drive_combo)

        # Scan Drive Button
        self.scan_drive_btn = QPushButton("Scan Drive")
        self.scan_drive_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.scan_drive_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {ACCENT_BLUE};
                color: #08111e;
                font-weight: bold;
                border-radius: 6px;
                padding: 6px 11px;
                font-size: 12px;
            }}
            QPushButton:hover {{ background-color: #7dd3fc; }}
        """)
        self.scan_drive_btn.clicked.connect(self.scan_selected_drive)
        header.addWidget(self.scan_drive_btn)

        # Scan Custom Folder Button
        self.scan_folder_btn = QPushButton("📁 Browse")
        self.scan_folder_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.scan_folder_btn.setToolTip("เลือกโฟลเดอร์เกมเพื่อสแกน (Browse Folder...)")
        self.scan_folder_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {BG_PANEL};
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_DEFAULT};
                border-radius: 6px;
                padding: 6px 10px;
                font-size: 12px;
                font-weight: 600;
            }}
            QPushButton:hover {{ background-color: {BG_CARD}; border-color: {BORDER_HOVER}; }}
        """)
        self.scan_folder_btn.clicked.connect(self.scan_custom_folder)
        header.addWidget(self.scan_folder_btn)

        # Check New Games from Monitored Directories Button
        self.sync_btn = QPushButton("🔄 Check New")
        self.sync_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.sync_btn.setToolTip("ตรวจหาเกมใหม่จากโฟลเดอร์ที่บันทึกไว้ (ข้ามเกมเดิม ไม่ลบที่แก้ไว้)")
        self.sync_btn.setStyleSheet("""
            QPushButton {
                background-color: #059669;
                color: white;
                font-weight: bold;
                border-radius: 6px;
                padding: 6px 10px;
                font-size: 12px;
            }
            QPushButton:hover { background-color: #10b981; }
        """)
        self.sync_btn.clicked.connect(lambda: self.start_monitored_scan(silent=False))
        header.addWidget(self.sync_btn)

        # Add Single Item (Game or Software) Button with Menu
        self.add_btn = QPushButton("➕ Add")
        self.add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_btn.setToolTip("เพิ่มเกมหรือโปรแกรมเข้าคลัง (+ Add Game / Software)")
        self.add_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {BG_PANEL};
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_DEFAULT};
                border-radius: 6px;
                padding: 6px 12px;
                font-size: 12px;
                font-weight: 600;
            }}
            QPushButton:hover {{ background-color: {BG_CARD}; border-color: {BORDER_HOVER}; }}
        """)
        add_menu = QMenu(self)
        add_menu.setStyleSheet(f"""
            QMenu {{
                background-color: {BG_PANEL};
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_DEFAULT};
                border-radius: 6px;
                padding: 4px;
            }}
            QMenu::item {{
                padding: 8px 18px;
                border-radius: 4px;
                font-size: 12px;
            }}
            QMenu::item:selected {{
                background-color: {BG_CARD_HOVER};
                color: {ACCENT_BLUE};
            }}
        """)
        act_add_g = add_menu.addAction("🎮 เพิ่มเกม (Add Game .exe / .lnk)...")
        act_add_s = add_menu.addAction("💻 เพิ่มโปรแกรม (Add Software .exe / .lnk)...")
        act_add_g.triggered.connect(lambda: self.add_single_item_manually(is_software=False))
        act_add_s.triggered.connect(lambda: self.add_single_item_manually(is_software=True))
        self.add_btn.setMenu(add_menu)
        header.addWidget(self.add_btn)

        # Settings & API Key Button
        settings_btn = QPushButton("⚙ Settings")
        settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        settings_btn.setToolTip("ตั้งค่าโปรแกรม, โฟลเดอร์คลังเกม และ SteamGridDB API Key")
        settings_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {BG_PANEL};
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_DEFAULT};
                border-radius: 6px;
                padding: 6px 10px;
                font-size: 12px;
                font-weight: 600;
            }}
            QPushButton:hover {{ background-color: {BG_CARD}; border-color: {BORDER_HOVER}; color: {ACCENT_BLUE}; }}
        """)
        settings_btn.clicked.connect(self.open_settings)
        header.addWidget(settings_btn)

        # Supporters / Donate Button
        self.donate_btn = QPushButton("💚 สนับสนุน")
        self.donate_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.donate_btn.setToolTip("สแกน QR บริจาค / ดูรายชื่อผู้สนับสนุน / ส่งหลักฐาน")
        self.donate_btn.setStyleSheet("""
            QPushButton {
                background-color: #064e3b;
                color: #34d399;
                border: 1px solid #059669;
                border-radius: 6px;
                padding: 6px 12px;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #059669;
                color: white;
            }
        """)
        self.donate_btn.clicked.connect(self.open_supporters_dialog)
        header.addWidget(self.donate_btn)

        header.addStretch()

        # Thumbnail Size Zoom Slider
        zoom_lbl = QLabel("Size:")
        zoom_lbl.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px; font-weight: 600;")
        header.addWidget(zoom_lbl)

        self.size_slider = QSlider(Qt.Orientation.Horizontal)
        self.size_slider.setRange(120, 260)
        self.size_slider.setValue(self.card_size)
        self.size_slider.setFixedWidth(75)
        self.size_slider.setStyleSheet(f"""
            QSlider::groove:horizontal {{
                height: 6px;
                background: {BG_PANEL};
                border-radius: 3px;
            }}
            QSlider::sub-page:horizontal {{
                background: {ACCENT_BLUE};
                border-radius: 3px;
            }}
            QSlider::handle:horizontal {{
                background: {TEXT_PRIMARY};
                border: 2px solid {ACCENT_BLUE};
                width: 14px;
                margin-top: -4px;
                margin-bottom: -4px;
                border-radius: 7px;
            }}
        """)
        self.size_slider.valueChanged.connect(self.on_card_size_changed)
        header.addWidget(self.size_slider)

        # Search Bar
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔍 Search library...")
        self.search_input.setFixedWidth(145)
        self.search_input.setStyleSheet(f"""
            QLineEdit {{
                background-color: {BG_PANEL};
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_DEFAULT};
                border-radius: 6px;
                padding: 6px 10px;
                font-size: 12px;
            }}
            QLineEdit:focus {{ border-color: {ACCENT_BLUE}; }}
        """)
        self.search_input.textChanged.connect(self.filter_games)
        header.addWidget(self.search_input)

        # Count Badge
        self.count_badge = QLabel("0 Items")
        self.count_badge.setStyleSheet(f"""
            background-color: {BG_PANEL};
            color: {TEXT_MUTED};
            border-radius: 6px;
            padding: 5px 10px;
            font-size: 11px;
            font-weight: 600;
        """)
        header.addWidget(self.count_badge)

        main_layout.addWidget(header_widget)

        # ---------------- Filter & Library Category Tabs ----------------
        tab_widget = QWidget()
        tab_widget.setFixedHeight(36)
        tab_row = QHBoxLayout(tab_widget)
        tab_row.setContentsMargins(0, 0, 0, 0)
        tab_row.setSpacing(8)

        tab_icon = QLabel("📁 Library:")
        tab_icon.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 13px; font-weight: bold;")
        tab_row.addWidget(tab_icon)

        self.tab_all_btn = QPushButton("🎮 All Games")
        self.tab_fav_btn = QPushButton("⭐ Favorites")
        self.tab_software_btn = QPushButton("💻 Software")
        self.tab_steam_btn = QPushButton("♨ Steam")
        self.tab_epic_btn = QPushButton("⚡ Epic")
        self.tab_ubisoft_btn = QPushButton("🌀 Ubisoft")
        self.tab_gog_btn = QPushButton("👾 GOG")
        self.tab_ea_btn = QPushButton("🎯 EA")
        self.tab_bluestacks_btn = QPushButton("📱 Android")
        self.tab_other_btn = QPushButton("📁 Local / Non-Steam")

        self.tab_buttons = {
            "all": self.tab_all_btn,
            "favorite": self.tab_fav_btn,
            "software": self.tab_software_btn,
            "steam": self.tab_steam_btn,
            "epic": self.tab_epic_btn,
            "ubisoft": self.tab_ubisoft_btn,
            "gog": self.tab_gog_btn,
            "ea": self.tab_ea_btn,
            "bluestacks": self.tab_bluestacks_btn,
            "other": self.tab_other_btn
        }

        for cat, btn in self.tab_buttons.items():
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _, c=cat: self.set_filter_category(c))
            tab_row.addWidget(btn)

        tab_row.addStretch()
        main_layout.addWidget(tab_widget)

        # Scanning Progress Banner
        self.progress_frame = QFrame()
        self.progress_frame.setVisible(False)
        self.progress_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {BG_PANEL};
                border: 1px solid {BORDER_DEFAULT};
                border-radius: 8px;
                padding: 8px;
            }}
        """)
        p_lay = QHBoxLayout(self.progress_frame)
        p_lay.setContentsMargins(8, 4, 8, 4)

        self.progress_label = QLabel("Scanning games...")
        self.progress_label.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 12px;")
        p_lay.addWidget(self.progress_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(12)
        self.progress_bar.setStyleSheet(f"""
            QProgressBar {{
                background-color: {BG_MAIN};
                border-radius: 6px;
                text-align: center;
            }}
            QProgressBar::chunk {{
                background-color: {ACCENT_BLUE};
                border-radius: 6px;
            }}
        """)
        p_lay.addWidget(self.progress_bar)

        self.cancel_scan_btn = QPushButton("Cancel")
        self.cancel_scan_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: #ef4444;
                color: white;
                border-radius: 4px;
                padding: 4px 10px;
                font-size: 11px;
                font-weight: bold;
            }}
            QPushButton:hover {{ background-color: #dc2626; }}
        """)
        self.cancel_scan_btn.clicked.connect(self.cancel_scan)
        p_lay.addWidget(self.cancel_scan_btn)
        main_layout.addWidget(self.progress_frame)

        # Main Library Scroll Area with Grid
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        self.grid_container = QWidget()
        self.grid_layout = QGridLayout(self.grid_container)
        self.grid_layout.setSpacing(14)
        self.grid_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.grid_layout.setContentsMargins(2, 2, 2, 16)
        self.scroll_area.setWidget(self.grid_container)

        main_layout.addWidget(self.scroll_area, stretch=1)

        # Empty State Centered Widget
        self.empty_widget = QWidget()
        empty_box = QVBoxLayout(self.empty_widget)
        empty_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_box.setSpacing(12)

        self.empty_icon = QLabel("🎮")
        self.empty_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_icon.setStyleSheet("font-size: 64px;")
        empty_box.addWidget(self.empty_icon)

        self.empty_title = QLabel("No games in your library yet")
        self.empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_title.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 20px; font-weight: bold;")
        empty_box.addWidget(self.empty_title)

        self.empty_desc = QLabel(
            "Select a drive or folder above and click 'Scan Drive' to detect games,\nor click '+ Add Game' to add manually."
        )
        self.empty_desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_desc.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 14px; line-height: 1.5;")
        empty_box.addWidget(self.empty_desc)

        self.empty_widget.setVisible(False)
        main_layout.addWidget(self.empty_widget, stretch=1)

        self.setCentralWidget(central_widget)

    def open_settings(self):
        dlg = SettingsDialog(self.db, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            for card in self.card_widgets.values():
                card.update_badges()
                card.refresh_cover()
            self.rearrange_grid()

    def on_card_size_changed(self, val: int):
        self.card_size = val
        self.db.set_setting("card_size", val)
        for card in self.card_widgets.values():
            card.set_card_size(val)
        self.rearrange_grid()

    def set_filter_category(self, cat: str):
        self.current_filter_category = cat
        self.update_tab_styles()
        self.rearrange_grid()

    def update_tab_styles(self):
        games = self.db.get_all_games()
        game_items = [g for g in games if not (g.get("is_software") or g.get("item_type") == "software")]
        software_items = [g for g in games if (g.get("is_software") or g.get("item_type") == "software")]
        total_game_count = len(game_items)
        software_count = len(software_items)
        fav_count = sum(1 for g in games if g.get("is_favorite"))

        counts = {
            "steam": 0,
            "epic": 0,
            "ubisoft": 0,
            "gog": 0,
            "ea": 0,
            "bluestacks": 0,
            "other": 0
        }
        for g in game_items:
            p = get_game_platform(g)
            if p == "local":
                counts["other"] += 1
            elif p in counts:
                counts[p] += 1
            else:
                counts["other"] += 1

        self.tab_all_btn.setText(f"🎮 All Games ({total_game_count})")
        self.tab_fav_btn.setText(f"⭐ Favorites ({fav_count})")
        self.tab_software_btn.setText(f"💻 Software ({software_count})")
        self.tab_steam_btn.setText(f"♨ Steam ({counts['steam']})")
        self.tab_epic_btn.setText(f"⚡ Epic ({counts['epic']})")
        self.tab_ubisoft_btn.setText(f"🌀 Ubisoft ({counts['ubisoft']})")
        self.tab_gog_btn.setText(f"👾 GOG ({counts['gog']})")
        self.tab_ea_btn.setText(f"🎯 EA ({counts['ea']})")
        self.tab_bluestacks_btn.setText(f"📱 Android ({counts['bluestacks']})")
        self.tab_other_btn.setText(f"📁 Local / Other ({counts['other']})")

        # Dynamically show launcher tabs if count > 0, or if currently active
        optional_tabs = ["epic", "ubisoft", "gog", "ea", "bluestacks"]
        for opt in optional_tabs:
            btn = self.tab_buttons[opt]
            btn.setVisible(counts[opt] > 0 or self.current_filter_category == opt)

        # Active / Inactive styles
        for cat, btn in self.tab_buttons.items():
            if cat == self.current_filter_category:
                if cat == "steam":
                    btn.setStyleSheet("background-color: #0c2738; color: #38bdf8; font-weight: bold; border-radius: 6px; padding: 6px 14px; border: 1px solid #1e608f;")
                elif cat == "favorite":
                    btn.setStyleSheet("background-color: #ca8a04; color: white; font-weight: bold; border-radius: 6px; padding: 6px 14px; border: 1px solid #facc15;")
                elif cat == "software":
                    btn.setStyleSheet("background-color: #312e81; color: #a5b4fc; font-weight: bold; border-radius: 6px; padding: 6px 14px; border: 1px solid #4f46e5;")
                elif cat == "epic":
                    btn.setStyleSheet("background-color: #18181b; color: #facc15; font-weight: bold; border-radius: 6px; padding: 6px 14px; border: 1px solid #ca8a04;")
                elif cat == "ubisoft":
                    btn.setStyleSheet("background-color: #0f172a; color: #60a5fa; font-weight: bold; border-radius: 6px; padding: 6px 14px; border: 1px solid #2563eb;")
                elif cat == "gog":
                    btn.setStyleSheet("background-color: #2e1065; color: #c084fc; font-weight: bold; border-radius: 6px; padding: 6px 14px; border: 1px solid #7c3aed;")
                elif cat == "ea":
                    btn.setStyleSheet("background-color: #2a0808; color: #f87171; font-weight: bold; border-radius: 6px; padding: 6px 14px; border: 1px solid #dc2626;")
                elif cat == "bluestacks":
                    btn.setStyleSheet("background-color: #064e3b; color: #34d399; font-weight: bold; border-radius: 6px; padding: 6px 14px; border: 1px solid #059669;")
                else:
                    btn.setStyleSheet(f"background-color: {ACCENT_BLUE}; color: #08111e; font-weight: bold; border-radius: 6px; padding: 6px 14px; border: 1px solid {ACCENT_BLUE};")
            else:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background-color: {BG_PANEL};
                        color: {TEXT_MUTED};
                        border: 1px solid {BORDER_DEFAULT};
                        border-radius: 6px;
                        padding: 6px 14px;
                        font-weight: 600;
                    }}
                    QPushButton:hover {{
                        background-color: {BG_CARD};
                        color: {TEXT_PRIMARY};
                        border-color: {BORDER_HOVER};
                    }}
                """)

    def get_filtered_games(self) -> List[Dict]:
        games = self.db.get_all_games()
        # Favorite sorting: Favorites first (at the top rows), then alphabetical by title
        games.sort(key=lambda x: (not bool(x.get("is_favorite", False)), x["name"].lower()))

        filtered = []
        for g in games:
            is_sw = bool(g.get("is_software") or g.get("item_type") == "software")
            p = get_game_platform(g)

            if self.current_filter_category == "software":
                if not is_sw:
                    continue
            else:
                if is_sw and self.current_filter_category != "favorite":
                    continue
                if self.current_filter_category == "favorite" and not g.get("is_favorite"):
                    continue
                elif self.current_filter_category == "steam" and p != "steam":
                    continue
                elif self.current_filter_category == "epic" and p != "epic":
                    continue
                elif self.current_filter_category == "ubisoft" and p != "ubisoft":
                    continue
                elif self.current_filter_category == "gog" and p != "gog":
                    continue
                elif self.current_filter_category == "ea" and p != "ea":
                    continue
                elif self.current_filter_category == "bluestacks" and p != "bluestacks":
                    continue
                elif self.current_filter_category == "other" and p != "local":
                    continue
            filtered.append(g)
        return filtered

    def scan_selected_drive(self):
        drive = self.drive_combo.currentText()
        if not drive:
            return
        self.db.add_monitored_folder(drive)
        self.start_scan(drive)

    def scan_custom_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Folder to Scan for Games")
        if folder:
            self.db.add_monitored_folder(folder)
            self.start_scan(folder)

    def start_scan(self, directory: str):
        if self.scanner_thread and self.scanner_thread.isRunning():
            return

        self.progress_frame.setVisible(True)
        self.progress_label.setText(f"Scanning {directory}...")
        self.progress_bar.setValue(0)
        self.scan_drive_btn.setEnabled(False)
        self.scan_folder_btn.setEnabled(False)
        self.sync_btn.setEnabled(False)

        self.scanner_thread = ScannerThread(
            target_dir=directory,
            existing_checker=self.db.is_game_known
        )
        self.scanner_thread.progress.connect(self.on_scan_progress)
        self.scanner_thread.finished_scan.connect(self.on_scan_finished)
        self.scanner_thread.start()

    def start_monitored_scan(self, silent: bool = False):
        if self.scanner_thread and self.scanner_thread.isRunning():
            return

        monitored = self.db.get_monitored_folders()
        if not monitored:
            if not silent:
                QMessageBox.information(
                    self, "No Monitored Folders",
                    "ยังไม่มีโฟลเดอร์เกมในระบบบันทึก\nกรุณาสแกนไดร์ฟ หรือเพิ่มโฟลเดอร์ใน Settings ก่อนครับ"
                )
            return

        self.progress_frame.setVisible(True)
        self.progress_label.setText("Checking for new games in monitored libraries...")
        self.progress_bar.setValue(0)
        self.scan_drive_btn.setEnabled(False)
        self.scan_folder_btn.setEnabled(False)
        self.sync_btn.setEnabled(False)

        self.scanner_thread = ScannerThread(
            monitored_dirs=monitored,
            existing_checker=self.db.is_game_known
        )
        self.scanner_thread.progress.connect(self.on_scan_progress)
        self.scanner_thread.finished_scan.connect(lambda res: self.on_monitored_scan_finished(res, silent=silent))
        self.scanner_thread.start()

    def on_monitored_scan_finished(self, results: List[Dict], silent: bool = False):
        self.progress_frame.setVisible(False)
        self.scan_drive_btn.setEnabled(True)
        self.scan_folder_btn.setEnabled(True)
        self.sync_btn.setEnabled(True)

        new_count = 0
        newly_added = []
        for item in results:
            if not self.db.is_game_known(exe_path=item["exe_path"], folder_path=item["folder_path"]):
                game = self.db.add_game(
                    name=item["name"],
                    exe_path=item["exe_path"],
                    folder_path=item["folder_path"]
                )
                newly_added.append(game)
                new_count += 1

        if new_count > 0:
            self.load_games_to_ui()
            if newly_added:
                if self.cover_thread and self.cover_thread.isRunning():
                    self.cover_thread.cancel()
                self.cover_thread = CoverFetchWorker(newly_added)
                self.cover_thread.cover_downloaded.connect(self.on_cover_downloaded)
                self.cover_thread.start()

            if not silent:
                QMessageBox.information(
                    self, "Scan Complete",
                    f"ตรวจพบและเพิ่มเกมใหม่ {new_count} เกมเรียบร้อยแล้ว!"
                )
        else:
            if not silent:
                QMessageBox.information(
                    self, "Up to Date",
                    "ไม่พบโฟลเดอร์เกมใหม่ ทุกเกมในโฟลเดอร์ที่บันทึกไว้เป็นปัจจุบันแล้ว!"
                )

    def on_scan_progress(self, folder_name: str, current: int, total: int):
        self.progress_label.setText(f"Scanning ({current}/{total}): {folder_name}")
        if total > 0:
            self.progress_bar.setValue(int((current / total) * 100))

    def cancel_scan(self):
        if self.scanner_thread and self.scanner_thread.isRunning():
            self.scanner_thread.cancel()
            self.progress_label.setText("Cancelling scan...")

    def on_scan_finished(self, results: List[Dict]):
        self.progress_frame.setVisible(False)
        self.scan_drive_btn.setEnabled(True)
        self.scan_folder_btn.setEnabled(True)
        self.sync_btn.setEnabled(True)

        new_count = 0
        newly_added = []
        for item in results:
            if not self.db.is_game_known(exe_path=item["exe_path"], folder_path=item["folder_path"]):
                game = self.db.add_game(
                    name=item["name"],
                    exe_path=item["exe_path"],
                    folder_path=item["folder_path"]
                )
                newly_added.append(game)
                new_count += 1

        self.load_games_to_ui()
        if newly_added:
            if self.cover_thread and self.cover_thread.isRunning():
                self.cover_thread.cancel()
            self.cover_thread = CoverFetchWorker(newly_added)
            self.cover_thread.cover_downloaded.connect(self.on_cover_downloaded)
            self.cover_thread.start()

        QMessageBox.information(
            self,
            "Scan Complete",
            f"Finished scanning!\nDetected {new_count} new game(s) ({len(results)} scanned)."
        )

    def add_single_item_manually(self, is_software: bool = False):
        title = "Select Software Executable or Shortcut" if is_software else "Select Game Executable or Shortcut"
        file_path, _ = QFileDialog.getOpenFileName(
            self, title, "", "Executables & Shortcuts (*.exe *.lnk);;Executables (*.exe);;Shortcuts (*.lnk);;All Files (*.*)"
        )
        if not file_path:
            return

        path_obj = Path(file_path)
        if path_obj.suffix.lower() == ".lnk":
            item_title = path_obj.stem
            target_exe, launch_args, work_dir = self.resolve_shortcut(file_path)
            folder_path = work_dir if work_dir and os.path.exists(work_dir) else os.path.dirname(target_exe)
            clean_title = item_title if is_software else (scanner.clean_game_name(item_title) or item_title)
            game = self.db.add_game(
                name=clean_title,
                exe_path=target_exe or file_path,
                folder_path=folder_path or os.path.dirname(file_path),
                is_software=is_software,
                item_type="software" if is_software else "game"
            )
            self.db.update_game(game["id"], lnk_path=file_path, launch_args=launch_args)
        else:
            folder_path = str(path_obj.parent)
            folder_name = path_obj.parent.name
            if is_software:
                clean_title = path_obj.stem
            else:
                if folder_name.lower() in ('bin', 'binaries', 'win64', 'x64', 'release', 'build', 'shipping', 'client'):
                    parent_name = path_obj.parent.parent.name
                    clean_title = scanner.clean_game_name(parent_name)
                else:
                    clean_title = scanner.clean_game_name(folder_name)
                if not clean_title or len(clean_title) < 2:
                    clean_title = scanner.clean_game_name(path_obj.stem) or path_obj.stem

            game = self.db.add_game(
                name=clean_title,
                exe_path=str(path_obj),
                folder_path=folder_path,
                is_software=is_software,
                item_type="software" if is_software else "game"
            )

        if not is_software and folder_path and os.path.exists(folder_path):
            self.db.add_monitored_folder(folder_path)

        self.load_games_to_ui()
        if not is_software:
            self.check_missing_covers()

    def dragEnterEvent(self, event: QtGui.QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QtGui.QDragMoveEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QtGui.QDropEvent):
        urls = event.mimeData().urls()
        if not urls:
            return
        event.acceptProposedAction()
        file_paths = [u.toLocalFile() for u in urls if u.isLocalFile()]
        self.handle_dropped_files(file_paths)

    def resolve_shortcut(self, lnk_path: str):
        """Resolves .lnk shortcut to target executable, arguments, and working directory."""
        try:
            import win32com.client
            shell = win32com.client.Dispatch("WScript.Shell")
            sc = shell.CreateShortcut(lnk_path)
            return sc.TargetPath, sc.Arguments, sc.WorkingDirectory
        except Exception as e:
            print(f"Error resolving shortcut {lnk_path}: {e}")
            return lnk_path, "", os.path.dirname(lnk_path)

    def handle_dropped_files(self, file_paths: List[str]):
        is_software_tab = (self.current_filter_category == "software")
        added_items = []
        for path in file_paths:
            if not os.path.exists(path):
                continue

            path_obj = Path(path)
            # Case 1: Windows Shortcut (.lnk)
            if path_obj.suffix.lower() == ".lnk":
                item_title = path_obj.stem
                target_exe, launch_args, work_dir = self.resolve_shortcut(path)
                folder_path = work_dir if work_dir and os.path.exists(work_dir) else os.path.dirname(target_exe)
                clean_title = item_title if is_software_tab else (scanner.clean_game_name(item_title) or item_title)

                item = self.db.add_game(
                    name=clean_title,
                    exe_path=target_exe or path,
                    folder_path=folder_path or os.path.dirname(path),
                    is_software=is_software_tab,
                    item_type="software" if is_software_tab else "game"
                )
                self.db.update_game(item["id"], lnk_path=path, launch_args=launch_args)
                if not is_software_tab and folder_path and os.path.exists(folder_path):
                    self.db.add_monitored_folder(folder_path)
                added_items.append(item)

            # Case 2: Direct .exe
            elif path_obj.suffix.lower() == ".exe":
                folder_path = str(path_obj.parent)
                folder_name = path_obj.parent.name
                if is_software_tab:
                    clean_title = path_obj.stem
                else:
                    if folder_name.lower() in ('bin', 'binaries', 'win64', 'x64', 'release', 'build', 'shipping', 'client'):
                        parent_name = path_obj.parent.parent.name
                        clean_title = scanner.clean_game_name(parent_name)
                    else:
                        clean_title = scanner.clean_game_name(folder_name)

                    if not clean_title or len(clean_title) < 2:
                        clean_title = scanner.clean_game_name(path_obj.stem) or path_obj.stem

                item = self.db.add_game(
                    name=clean_title,
                    exe_path=str(path_obj),
                    folder_path=folder_path,
                    is_software=is_software_tab,
                    item_type="software" if is_software_tab else "game"
                )
                if not is_software_tab:
                    self.db.add_monitored_folder(folder_path)
                added_items.append(item)

            # Case 3: Folder dropped
            elif os.path.isdir(path):
                res = scanner.find_game_executable_in_folder(path)
                if res:
                    exe_path, game_title = res
                    item = self.db.add_game(
                        name=game_title,
                        exe_path=exe_path,
                        folder_path=path,
                        is_software=is_software_tab,
                        item_type="software" if is_software_tab else "game"
                    )
                    if not is_software_tab:
                        self.db.add_monitored_folder(path)
                    added_items.append(item)

        if added_items:
            self.load_games_to_ui()
            # Background fetch covers for newly dropped non-software games only
            games_to_fetch = [g for g in added_items if not (g.get("is_software") or g.get("item_type") == "software")]
            if games_to_fetch:
                if self.cover_thread and self.cover_thread.isRunning():
                    self.cover_thread.cancel()
                self.cover_thread = CoverFetchWorker(games_to_fetch)
                self.cover_thread.cover_downloaded.connect(self.on_cover_downloaded)
                self.cover_thread.start()

            names = ", ".join(f"'{g['name']}'" for g in added_items[:3])
            if len(added_items) > 3:
                names += f" and {len(added_items) - 3} more"
            if is_software_tab:
                QMessageBox.information(
                    self, "Software Added",
                    f"เพิ่มโปรแกรม {names} เข้าสู่คลัง Software เรียบร้อยแล้ว!"
                )
            else:
                QMessageBox.information(
                    self, "Game Added",
                    f"เพิ่มเกม {names} เข้าสู่คลัง GameVault เรียบร้อยแล้ว!\n(ระบบกำลังค้นหาและดึงภาพปกในพื้นหลัง)"
                )

    def load_games_to_ui(self):
        all_games = self.db.get_all_games()
        current_ids = {g["id"] for g in all_games}

        # Remove deleted game cards
        for gid in list(self.card_widgets.keys()):
            if gid not in current_ids:
                card = self.card_widgets.pop(gid)
                card.setParent(None)
                card.deleteLater()

        # Create or update GameCard for every single game in library
        for game in all_games:
            gid = game["id"]
            if gid not in self.card_widgets:
                card = GameCard(game, db=self.db, card_width=self.card_size, parent=self.grid_container)
                card.clicked.connect(self.open_game_details)
                card.play_requested.connect(self.launch_game)
                card.action_requested.connect(self.handle_card_action)
                self.card_widgets[gid] = card
            else:
                self.card_widgets[gid].game = game
                self.card_widgets[gid].update_badges()

        self.rearrange_grid()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QtCore.QTimer.singleShot(60, self.rearrange_grid)

    def rearrange_grid(self, update_tabs: bool = True):
        all_games = self.db.get_all_games()
        if update_tabs:
            self.update_tab_styles()

        filtered_games = self.get_filtered_games()
        filter_text = self.search_input.text().strip().lower()

        # Disable container updates while altering layout to eliminate UI stutter and repaint lag
        self.grid_container.setUpdatesEnabled(False)
        try:
            # Remove all items currently in grid_layout (clean slate, widgets not destroyed)
            while self.grid_layout.count() > 0:
                item = self.grid_layout.takeAt(0)
                if item.widget():
                    item.widget().setVisible(False)

            # ---------------- Responsive Dynamic Grid Calculation ----------------
            viewport_w = self.scroll_area.viewport().width()
            spacing = 14
            base_size = max(120, self.card_size)

            # Usable width for cards and spacing (leaving margin for scrollbar)
            usable_w = max(280, viewport_w - 20)

            # Calculate standard columns that fit
            cols_floor = max(1, (usable_w + spacing) // (base_size + spacing))
            cols_ceil = cols_floor + 1

            # Check if an extra column can fit smoothly without cards getting too small (>= 82% of base_size)
            width_if_ceil = (usable_w - (cols_ceil - 1) * spacing) // cols_ceil
            if cols_ceil > 1 and width_if_ceil >= max(135, int(base_size * 0.82)):
                columns = cols_ceil
                effective_card_width = width_if_ceil
            else:
                columns = cols_floor
                effective_card_width = (usable_w - (cols_floor - 1) * spacing) // cols_floor

            # Keep effective_card_width within a sane range relative to base size
            effective_card_width = max(120, min(effective_card_width, int(base_size * 1.35)))

            # Center the grid perfectly: calculate symmetric left and right margins
            total_grid_w = columns * effective_card_width + (columns - 1) * spacing
            side_margin = max(4, (viewport_w - total_grid_w) // 2)
            self.grid_layout.setContentsMargins(side_margin, 6, side_margin, 16)

            visible_count = 0
            for game in filtered_games:
                if filter_text and filter_text not in game["name"].lower():
                    card = self.card_widgets.get(game["id"])
                    if card:
                        card.setVisible(False)
                    continue

                card = self.card_widgets.get(game["id"])
                if not card:
                    card = GameCard(game, db=self.db, card_width=effective_card_width, parent=self.grid_container)
                    card.clicked.connect(self.open_game_details)
                    card.play_requested.connect(self.launch_game)
                    card.action_requested.connect(self.handle_card_action)
                    self.card_widgets[game["id"]] = card
                else:
                    if abs(card.card_width - effective_card_width) >= 3:
                        card.set_card_size(effective_card_width)

                row = visible_count // columns
                col = visible_count % columns
                self.grid_layout.addWidget(card, row, col)
                card.setVisible(True)
                visible_count += 1

            if visible_count == 0:
                self.scroll_area.setVisible(False)
                self.empty_widget.setVisible(True)
                if filter_text:
                    self.empty_icon.setText("🔍")
                    self.empty_title.setText(f"No results for '{filter_text}'")
                    self.empty_desc.setText("Try searching with a different game/software title or keyword.")
                elif self.current_filter_category == "favorite":
                    self.empty_icon.setText("⭐")
                    self.empty_title.setText("No favorite items yet")
                    self.empty_desc.setText("Click the star ☆ on any card or right-click to pin your favorite items here!")
                elif self.current_filter_category == "software":
                    self.empty_icon.setText("💻")
                    self.empty_title.setText("ยังไม่มีโปรแกรมหรือ Software ในคลัง")
                    self.empty_desc.setText("ลากไฟล์ .exe หรือ Shortcut (.lnk) ของโปรแกรมมาวางที่นี่ได้ทันที\nหรือกดปุ่ม ➕ Add ด้านบนแล้วเลือก 'เพิ่มโปรแกรม' ได้เลยครับ")
                elif self.current_filter_category == "steam":
                    self.empty_icon.setText("♨")
                    self.empty_title.setText("No Steam games detected")
                    self.empty_desc.setText("Games inside SteamLibrary / steamapps folders will appear here.")
                elif self.current_filter_category == "other":
                    self.empty_icon.setText("📁")
                    self.empty_title.setText("No Non-Steam games detected")
                    self.empty_desc.setText("Games outside SteamLibrary folders will appear here.")
                else:
                    self.empty_icon.setText("🎮")
                    self.empty_title.setText("No games in your library yet")
                    self.empty_desc.setText("Select a drive or folder above and click 'Scan Drive' to detect games,\nor drag & drop any game executable / BlueStacks shortcut here!")
            else:
                self.scroll_area.setVisible(True)
                self.empty_widget.setVisible(False)

            if self.current_filter_category == "software":
                sw_total = sum(1 for g in all_games if g.get("is_software") or g.get("item_type") == "software")
                self.count_badge.setText(f"{visible_count} / {sw_total} Software")
            else:
                game_total = sum(1 for g in all_games if not (g.get("is_software") or g.get("item_type") == "software"))
                self.count_badge.setText(f"{visible_count} / {game_total} Games")
        finally:
            self.grid_container.setUpdatesEnabled(True)

    def filter_games(self, text: str):
        # Debounced search trigger for instant 60+ FPS smooth typing without stutter
        self.search_timer.start()

    def check_missing_covers(self):
        games = self.db.get_all_games()
        missing = []
        for g in games:
            cpath = g.get("cover_path")
            if not cpath or not os.path.exists(cpath):
                missing.append(g)

        if missing:
            if self.cover_thread and self.cover_thread.isRunning():
                self.cover_thread.cancel()
            self.cover_thread = CoverFetchWorker(missing)
            self.cover_thread.cover_downloaded.connect(self.on_cover_downloaded)
            self.cover_thread.start()

    def on_cover_downloaded(self, game_id: str, cover_path: str, details: dict):
        clear_cover_cache(cover_path)
        updates = {"cover_path": cover_path}
        if details:
            updates["appid"] = details.get("appid")
            updates["description"] = details.get("short_description", "")
            updates["genres"] = details.get("genres", "")
            updates["release_date"] = details.get("release_date", "")
            updates["developers"] = details.get("developers", "")
            updates["screenshots"] = details.get("screenshots", [])
            updates["screenshots_full"] = details.get("screenshots_full", [])
            updates["steam_url"] = details.get("steam_url", "")
            cover_fetcher.cache_game_screenshots(game_id, details.get("screenshots", []), self.db.covers_dir)

        self.db.update_game(game_id, **updates)
        card = self.card_widgets.get(game_id)
        if card:
            card.refresh_cover()

    def open_game_details(self, game: Dict):
        # Fresh read from db
        fresh_game = self.db.get_game(game["id"]) or game
        dlg = GameDetailDialog(
            game=fresh_game,
            db=self.db,
            on_update_callback=self.on_game_updated,
            on_play_callback=self.launch_game,
            parent=self
        )
        dlg.exec()

    def on_game_updated(self, game_id: str):
        fresh_game = self.db.get_game(game_id)
        if fresh_game and fresh_game.get("cover_path"):
            clear_cover_cache(fresh_game.get("cover_path"))
        card = self.card_widgets.get(game_id)
        if card and fresh_game:
            card.game = fresh_game
            card.refresh_cover()
            card.apply_border_style()
            card.update_badges()
            # Update title in card
            metrics = card.title_label.fontMetrics()
            elided = metrics.elidedText(fresh_game["name"], Qt.TextElideMode.ElideRight, card.card_width - 15)
            card.title_label.setText(elided)
        self.update_tab_styles()

    def launch_game(self, game: Dict):
        # 1. If game was added via shortcut (.lnk) e.g. BlueStacks, launch the shortcut directly
        lnk_path = game.get("lnk_path")
        if lnk_path and os.path.exists(lnk_path):
            try:
                os.startfile(lnk_path)
                self.db.record_play(game["id"])
                return
            except Exception:
                pass

        exe_path = game.get("exe_path")
        if not exe_path or not os.path.exists(exe_path):
            QMessageBox.critical(
                self, "Error", f"Executable not found:\n{exe_path}\nPlease re-assign executable path."
            )
            return

        folder = game.get("folder_path") or os.path.dirname(exe_path)
        launch_args = game.get("launch_args", "")
        try:
            cmd = [exe_path]
            if launch_args:
                import shlex
                try:
                    cmd.extend(shlex.split(launch_args))
                except Exception:
                    cmd.append(launch_args)
            subprocess.Popen(cmd, cwd=folder, shell=False)
            self.db.record_play(game["id"])
        except Exception as e:
            QMessageBox.warning(
                self,
                "Launch Error",
                f"Failed to launch game:\n{str(e)}\n\nTry running GameVault as Administrator if the game requires elevated permissions."
            )

    def handle_card_action(self, action: str, game: Dict):
        if action == "toggle_favorite":
            new_fav = self.db.toggle_favorite(game["id"])
            game["is_favorite"] = new_fav
            self.on_game_updated(game["id"])
            self.rearrange_grid()

        elif action == "toggle_type":
            is_sw = bool(game.get("is_software") or game.get("item_type") == "software")
            new_is_sw = not is_sw
            new_type = "software" if new_is_sw else "game"
            self.db.update_game(game["id"], is_software=new_is_sw, item_type=new_type)
            game["is_software"] = new_is_sw
            game["item_type"] = new_type
            self.on_game_updated(game["id"])
            self.rearrange_grid()

        elif action.startswith("set_border_color:"):
            color = action.split(":", 1)[1]
            if color == "None" or not color:
                color = None
            self.db.update_game(game["id"], border_color=color)
            game["border_color"] = color
            self.on_game_updated(game["id"])

        elif action.startswith("set_platform:"):
            target_plat = action.split(":", 1)[1]
            if target_plat == "auto":
                target_plat = None
            self.db.update_game(game["id"], platform=target_plat)
            game["platform"] = target_plat
            self.on_game_updated(game["id"])
            self.rearrange_grid()

        elif action == "choose_border_color":
            dlg = BorderColorDialog(game.get("border_color"), game_name=game["name"], db=self.db, parent=self)
            if dlg.exec() == QDialog.DialogCode.Accepted:
                self.db.update_game(game["id"], border_color=dlg.selected_color)
                game["border_color"] = dlg.selected_color
                self.on_game_updated(game["id"])

        elif action == "upload_cover":
            file_path, _ = QFileDialog.getOpenFileName(
                self, "Choose Cover Image", "", "Images (*.png *.jpg *.jpeg *.webp *.bmp)"
            )
            if file_path:
                dest = game.get("cover_path") or os.path.join(self.db.covers_dir, f"{game['id']}.jpg")
                game["cover_path"] = dest
                if cover_fetcher.save_custom_cover(file_path, dest):
                    self.db.update_game(game["id"], cover_path=dest)
                    self.on_game_updated(game["id"])

        elif action == "search_cover":
            try:
                dest = game.get("cover_path") or os.path.join(self.db.covers_dir, f"{game['id']}.jpg")
                game["cover_path"] = dest

                dlg = OnlineCoverDialog(game["name"], target_cover_path=dest, db=self.db, parent=self)
                if dlg.exec() == QDialog.DialogCode.Accepted:
                    if dlg.custom_image_applied:
                        self.db.update_game(game["id"], cover_path=dest)
                        self.on_game_updated(game["id"])
                        QMessageBox.information(self, "Success", "Custom web cover downloaded, resized to 600x900, and applied successfully!")
                    elif dlg.selected_appid:
                        cover_fetcher.download_steam_cover(dlg.selected_appid, dest)

                        updates = {"appid": dlg.selected_appid, "cover_path": dest}
                        details = dlg.selected_details
                        if details:
                            updates["description"] = details.get("short_description", "")
                            updates["genres"] = details.get("genres", "")
                            updates["release_date"] = details.get("release_date", "")
                            updates["developers"] = details.get("developers", "")
                            updates["screenshots"] = details.get("screenshots", [])
                            updates["screenshots_full"] = details.get("screenshots_full", [])
                            updates["steam_url"] = details.get("steam_url", "")
                            cover_fetcher.cache_game_screenshots(game["id"], details.get("screenshots", []), self.db.covers_dir)

                        self.db.update_game(game["id"], **updates)
                        self.on_game_updated(game["id"])
            except Exception as e:
                print(f"[handle_card_action:search_cover] Error: {e}")
                QMessageBox.critical(self, "Error", f"Failed to search/apply cover:\n{e}")

        elif action == "refresh_steam":
            try:
                dest = game.get("cover_path") or os.path.join(self.db.covers_dir, f"{game['id']}.jpg")
                details = cover_fetcher.fetch_cover_for_game(game["name"], dest)
                if details and isinstance(details, dict) and details.get("appid"):
                    updates = {
                        "appid": details["appid"],
                        "cover_path": dest,
                        "description": details.get("short_description", ""),
                        "genres": details.get("genres", ""),
                        "release_date": details.get("release_date", ""),
                        "developers": details.get("developers", ""),
                        "screenshots": details.get("screenshots", []),
                        "screenshots_full": details.get("screenshots_full", []),
                        "steam_url": details.get("steam_url", "")
                    }
                    cover_fetcher.cache_game_screenshots(game["id"], details.get("screenshots", []), self.db.covers_dir)
                    self.db.update_game(game["id"], **updates)
                    self.on_game_updated(game["id"])
                    QMessageBox.information(self, "Updated", f"Steam metadata updated for '{game['name']}'!")
                else:
                    QMessageBox.information(
                        self, "Notice", f"Could not find exact Steam match for '{game['name']}'. Please use Search Cover to pick manually."
                    )
            except Exception as e:
                print(f"[handle_card_action:refresh_steam] Error: {e}")
                QMessageBox.critical(self, "Error", f"Failed to refresh Steam metadata:\n{e}")

        elif action == "rename":
            is_sw = bool(game.get("is_software") or game.get("item_type") == "software")
            dialog_title = "Rename Software" if is_sw else "Rename Game"
            prompt_label = "Enter new software name:" if is_sw else "Enter new game title:"
            new_name, ok = QtWidgets.QInputDialog.getText(
                self, dialog_title, prompt_label, text=game["name"]
            )
            if ok and new_name.strip():
                clean_new = new_name.strip()
                self.db.update_game(game["id"], name=clean_new)
                game["name"] = clean_new
                self.on_game_updated(game["id"])

                if not is_sw:
                    prompt = QMessageBox.question(
                        self, "Search Cover",
                        f"Would you like to auto-fetch new cover & info from Steam for '{clean_new}'?",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                    )
                    if prompt == QMessageBox.StandardButton.Yes:
                        self.handle_card_action("refresh_steam", game)

        elif action == "change_exe":
            dlg = ChangeExeDialog(game, self)
            if dlg.exec() == QDialog.DialogCode.Accepted and dlg.selected_exe:
                new_exe = dlg.selected_exe
                self.db.update_game(game["id"], exe_path=new_exe)
                game["exe_path"] = new_exe
                self.on_game_updated(game["id"])
                QMessageBox.information(self, "Updated", f"Executable updated to:\n{new_exe}")

        elif action == "open_dir":
            folder = game.get("folder_path") or os.path.dirname(game["exe_path"])
            if os.path.exists(folder):
                os.startfile(folder)

        elif action == "remove":
            confirm = QMessageBox.question(
                self,
                "Remove Game",
                f"Remove '{game['name']}' from library?\n(This will not delete your game files).",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if confirm == QMessageBox.StandardButton.Yes:
                self.db.remove_game(game["id"])
                self.load_games_to_ui()

    def setup_system_tray(self):
        """Initializes Windows System Tray icon with Steam-style Jump List menu."""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return

        self.tray_icon = QSystemTrayIcon(self)
        icon_path = get_asset_path("icon.png")
        if os.path.exists(icon_path):
            self.tray_icon.setIcon(QIcon(icon_path))
        self.tray_icon.setToolTip("GameVault - Game & Software Library by MeN9CH")

        self.tray_menu = QMenu()
        self.tray_menu.setStyleSheet(f"""
            QMenu {{
                background-color: {BG_PANEL};
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_DEFAULT};
                border-radius: 6px;
                padding: 4px;
            }}
            QMenu::item {{
                padding: 7px 20px;
                border-radius: 4px;
                font-size: 12px;
            }}
            QMenu::item:selected {{
                background-color: {BG_CARD_HOVER};
                color: {ACCENT_BLUE};
            }}
            QMenu::separator {{
                height: 1px;
                background: {BORDER_DEFAULT};
                margin: 4px 6px;
            }}
        """)
        self.tray_menu.aboutToShow.connect(self.populate_tray_menu)
        self.tray_icon.setContextMenu(self.tray_menu)
        self.tray_icon.activated.connect(self.on_tray_activated)
        self.tray_icon.show()

    def populate_tray_menu(self):
        """Dynamically populates the System Tray context menu with recent games/software and controls."""
        self.tray_menu.clear()

        include_software = self.db.get_setting("tray_include_software", False) if self.db else False
        recent_items = self.db.get_recently_played_games(limit=5, include_software=include_software)
        if recent_items:
            hdr_text = "🎮 รายการล่าสุด (Recent Games & Software):" if include_software else "🎮 เกมล่าสุด (Recent Games):"
            hdr = self.tray_menu.addAction(hdr_text)
            hdr.setEnabled(False)
            for g in recent_items:
                name = g.get("name", "Unknown")
                disp_name = (name[:26] + "..") if len(name) > 28 else name
                prefix = "💻" if (g.get("is_software") or g.get("item_type") == "software") else "▶"
                act = self.tray_menu.addAction(f"   {prefix}  {disp_name}")
                act.triggered.connect(lambda _, game=g: self.launch_game(game))
            self.tray_menu.addSeparator()

        # Section 2: Window Controls
        act_library = self.tray_menu.addAction("📂 เปิดคลัง GameVault (Library)")
        act_library.triggered.connect(self.show_and_activate)

        act_scan = self.tray_menu.addAction("🔄 สแกนหาเกมใหม่ (Scan)")
        act_scan.triggered.connect(lambda: self.start_monitored_scan(silent=False))

        act_settings = self.tray_menu.addAction("⚙ การตั้งค่า (Settings)")
        act_settings.triggered.connect(self.open_settings)

        act_donate = self.tray_menu.addAction("💚 สนับสนุน (Supporters)")
        act_donate.triggered.connect(self.open_supporters_dialog)

        self.tray_menu.addSeparator()
        act_exit = self.tray_menu.addAction("❌ ออกจากโปรแกรม (Exit)")
        act_exit.triggered.connect(self.quit_application)

    def open_supporters_dialog(self):
        from supporter_dialog import SupportersDialog
        dlg = SupportersDialog(self)
        dlg.exec()

    def on_tray_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            if self.isVisible() and not self.isMinimized():
                self.hide()
            else:
                self.show_and_activate()

    def show_and_activate(self):
        self.showNormal()
        self.activateWindow()
        self.raise_()

    def quit_application(self):
        self._force_quit = True
        if hasattr(self, 'tray_icon'):
            self.tray_icon.hide()
        QApplication.quit()

    def closeEvent(self, event):
        min_to_tray = self.db.get_setting("minimize_to_tray_on_close", True)
        if not self._force_quit and min_to_tray and QSystemTrayIcon.isSystemTrayAvailable():
            event.ignore()
            self.hide()
            # Notify user on first minimize
            if not self.db.get_setting("tray_balloon_shown", False):
                self.tray_icon.showMessage(
                    "GameVault - Game & Software Library by MeN9CH",
                    "GameVault ยังคงทำงานอยู่ใน System Tray\nคลิกขวาที่ไอคอนเพื่อเลือก 5 รายการล่าสุด หรือเปิดคลังได้ตลอดเวลาครับ",
                    QSystemTrayIcon.MessageIcon.Information,
                    3000
                )
                self.db.set_setting("tray_balloon_shown", True)
        else:
            event.accept()


def main():
    try:
        import ctypes
        myappid = 'gamevault.launcher.app.1.0'
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
    except Exception:
        pass

    app = QApplication(sys.argv)
    app.setApplicationName("GameVault")
    app.setQuitOnLastWindowClosed(False)

    # Load and register Noto Sans Thai application font
    font_path = get_asset_path(os.path.join("assets", "fonts", "NotoSansThai.ttf"))
    if os.path.exists(font_path):
        font_id = QFontDatabase.addApplicationFont(font_path)
        if font_id >= 0:
            families = QFontDatabase.applicationFontFamilies(font_id)
            if families:
                app.setFont(QFont(families[0], 10))
            else:
                app.setFont(QFont("Noto Sans Thai", 10))
        else:
            app.setFont(QFont("Noto Sans Thai", 10))
    else:
        app.setFont(QFont("Noto Sans Thai", 10))

    icon_path = get_asset_path("icon.png")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    # Enable autostart by default if not set
    base_dir = get_app_dir()
    db_path = str(base_dir / "games.json")
    covers_dir = str(base_dir / "covers")
    tmp_db = LibraryDB(db_path=db_path, covers_dir=covers_dir)
    if tmp_db.get_setting("run_on_startup", None) is None:
        set_windows_autostart(True)
        tmp_db.set_setting("run_on_startup", True)

    window = MainWindow()

    start_minimized = "--minimized" in sys.argv or "--tray" in sys.argv
    if not start_minimized:
        window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()

    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")

    main()
