"""
Game Scanner Module for GameVault
Scans drives or specific directories to detect installed games, their executables, and game names.
"""

import os
import re
import psutil
from pathlib import Path
from typing import List, Dict, Optional, Tuple

# Try importing pefile for Windows PE header metadata inspection
try:
    import pefile
    PEFILE_AVAILABLE = True
except ImportError:
    PEFILE_AVAILABLE = False


# Common folder names to ignore when scanning entire drives
IGNORED_DIRS = {
    'windows', '$recycle.bin', 'system volume information', 'recovery',
    'appdata', 'programdata', 'msocache', 'intel', 'perflogs',
    'drivers', 'node_modules', '.git', '.gemini', '.vscode',
    'common files', 'microsoft', 'package cache', 'temp', 'tmp',
    'windowsdefender', 'nvidia', 'amd', 'corsair', 'razer'
}

# Substrings or names of executables that are NOT the game itself
IGNORED_EXE_PATTERNS = [
    r'unins(tall)?(\d+)?',
    r'setup',
    r'install(er)?',
    r'patch(er)?',
    r'update(r)?',
    r'crash(handler|pad|report)?.*',
    r'unitycrashhandler(32|64)?',
    r'vcredist.*',
    r'dxsetup',
    r'dxwebsetup',
    r'redist.*',
    r'dotnet.*',
    r'eac_.*',
    r'easyanticheat.*',
    r'battleye.*',
    r'epicgameslauncher',
    r'steam(errorreporter)?',
    r'origin(webhelperservice)?',
    r'uplay.*',
    r'ubisoftconnect.*',
    r'galaxyclient.*',
    r'cefprocess',
    r'ffmpeg',
    r'python.*',
    r'node',
    r'cmd',
    r'powershell',
    r'vulkaninfo.*',
    r'7z.*',
    r'winrar',
    r'helper',
    r'service',
    r'diag.*',
    r'benchmark.*',
    r'config(urator|tool)?',
    r'launcher_helper'
]

# Engine and generic names to ignore when extracting game title from PE metadata
IGNORED_PRODUCT_NAMES = {
    'unity', 'unity player', 'unityplayer', 'unreal', 'unreal engine',
    'epic games', 'godot', 'godot engine', 'gamemaker', 'cryengine',
    'fmod', 'wwise', 'directx', 'microsoft', 'windows', 'game',
    'launcher', 'bootstrap', 'shipping', 'client', 'app', 'application',
    'chromium', 'electron', 'python', 'nwjs', 'nw.js'
}

# Release group / metadata tags to strip from folder names
RELEASE_TAGS = [
    r'\[.*?\]',                      # [FLT], [FitGirl Repack], etc.
    r'\(.*?\)',                      # (2020), (v1.0), etc.
    r'\b(fitgirl|dodi|codex|skidrow|cpi|plaza|repack|flt|steampunks|reloaded|razor1911|prophet|elamigos|goldberg|gog|rg mechanics|empress|cset)\b',
    r'\bv\d+(\.\d+)*\b',            # v1.0, v1.0.4.2
    r'\bbuild\s*\d+\b',             # build 12345
    r'\b(x64|x86|64bit|32bit)\b',
    r'\b(multi\d+|multilingual)\b',
    r'\b(deluxe|ultimate|complete|goty|remastered|enhanced|definitive)\s+edition\b',
]

# Common game library subdirectories across Steam, Epic Games, Ubisoft Connect, GOG Galaxy, and EA/Origin
COMMON_LAUNCHER_SUBDIRS = [
    'SteamLibrary/steamapps/common',
    'steamapps/common',
    'Steam/steamapps/common',
    'common',
    'Program Files (x86)/Steam/steamapps/common',
    'Program Files/Steam/steamapps/common',
    'Epic Games',
    'Program Files/Epic Games',
    'Program Files (x86)/Epic Games',
    'Ubisoft/games',
    'Ubisoft Game Launcher/games',
    'Ubisoft Games',
    'Program Files (x86)/Ubisoft/Ubisoft Game Launcher/games',
    'Program Files/Ubisoft/Ubisoft Game Launcher/games',
    'GOG Games',
    'GOG Galaxy/Games',
    'Program Files (x86)/GOG Galaxy/Games',
    'Program Files/GOG Galaxy/Games',
    'EA Games',
    'Origin Games',
    'Program Files/EA Games',
    'Program Files (x86)/Origin Games',
    'Games',
    'XboxGames',
]


def get_available_drives() -> List[str]:
    """Return a list of available drive paths like ['C:\\', 'D:\\', ...]."""
    drives = []
    try:
        for partition in psutil.disk_partitions(all=False):
            if partition.device:
                drives.append(partition.device)
    except Exception:
        # Fallback for Windows
        for letter in 'CDEFGHIJKLMNOPQRSTUVWXYZ':
            path = f"{letter}:\\"
            if os.path.exists(path):
                drives.append(path)
    return sorted(drives)


def clean_game_name(raw_name: str) -> str:
    """Cleans up a folder or executable name into a polished game title."""
    name = raw_name

    # Remove tags using regex
    for pattern in RELEASE_TAGS:
        name = re.sub(pattern, ' ', name, flags=re.IGNORECASE)

    # Replace separators with spaces
    name = re.sub(r'[_.\-+]+', ' ', name)

    # Clean double spaces
    name = re.sub(r'\s+', ' ', name).strip()

    # Title case if all lowercase or weirdly formatted
    if name.islower() or name.isupper():
        name = name.title()

    return name or raw_name


def get_pe_metadata(exe_path: str) -> Dict[str, str]:
    """Extract FileDescription and ProductName from Windows PE executable."""
    if not PEFILE_AVAILABLE:
        return {}

    try:
        pe = pefile.PE(exe_path, fast_load=True)
        pe.parse_data_directories(directories=[
            pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_RESOURCE']
        ])
        info = {}
        if hasattr(pe, 'FileInfo'):
            for finfo in pe.FileInfo[0]:
                if hasattr(finfo, 'Key') and finfo.Key.decode('utf-8', errors='ignore') == 'StringFileInfo':
                    for st in finfo.StringTable:
                        for k, v in st.entries.items():
                            key = k.decode('utf-8', errors='ignore')
                            val = v.decode('utf-8', errors='ignore')
                            info[key] = val
        return info
    except Exception:
        return {}


def is_ignored_exe(exe_name: str) -> bool:
    """Check if executable is an uninstaller, installer, crash reporter, etc."""
    name_lower = os.path.splitext(exe_name)[0].lower()
    for pattern in IGNORED_EXE_PATTERNS:
        if re.search(pattern, name_lower, re.IGNORECASE):
            return True
    return False


def find_game_executable_in_folder(folder_path: str) -> Optional[Tuple[str, str]]:
    """
    Finds the most likely game executable inside a game folder.
    Returns (exe_path, detected_game_name) or None.
    """
    candidates = []
    folder_name = os.path.basename(folder_path.rstrip('\\/'))

    # Search folder up to depth 3
    for root, dirs, files in os.walk(folder_path):
        rel_depth = os.path.relpath(root, folder_path).count(os.sep)
        if rel_depth > 3:
            dirs.clear()
            continue

        # Skip ignored subdirs
        dirs[:] = [d for d in dirs if d.lower() not in IGNORED_DIRS]

        for file in files:
            if not file.lower().endswith('.exe'):
                continue
            if is_ignored_exe(file):
                continue

            full_path = os.path.join(root, file)
            try:
                size_mb = os.path.getsize(full_path) / (1024 * 1024)
            except OSError:
                continue

            # Games are rarely under 1MB unless simple indie games
            candidates.append((full_path, file, size_mb, rel_depth))

    if not candidates:
        return None

    # Score candidates
    scored = []
    cleaned_folder = clean_game_name(folder_name).lower()

    for full_path, file_name, size_mb, depth in candidates:
        score = 0.0
        exe_base = os.path.splitext(file_name)[0].lower()

        # Metadata inspection
        pe_meta = get_pe_metadata(full_path)
        prod_name = pe_meta.get('ProductName', '').strip()
        file_desc = pe_meta.get('FileDescription', '').strip()

        # Check metadata validity
        prod_valid = (
            prod_name and len(prod_name) > 3
            and prod_name.lower() not in IGNORED_PRODUCT_NAMES
            and not any(ign in prod_name.lower() for ign in ['setup', 'installer', 'crash'])
        )
        file_desc_valid = (
            file_desc and len(file_desc) > 3
            and file_desc.lower() not in IGNORED_PRODUCT_NAMES
            and not any(ign in file_desc.lower() for ign in ['setup', 'installer', 'crash', 'application'])
        )

        if prod_valid:
            score += 30.0
            if cleaned_folder in prod_name.lower() or prod_name.lower() in cleaned_folder:
                score += 40.0

        # Name match with folder
        if exe_base == cleaned_folder.replace(' ', ''):
            score += 50.0
        elif exe_base in cleaned_folder or cleaned_folder in exe_base:
            score += 30.0

        # Subfolders named bin, x64, Shipping are common for primary game exes
        path_lower = full_path.lower()
        if 'bin\\x64' in path_lower or 'bin/x64' in path_lower:
            score += 25.0
        elif 'shipping.exe' in path_lower:
            score += 20.0
        elif depth == 0:
            score += 15.0  # Root executable

        # Size weighting (games tend to be bigger binaries)
        if size_mb > 20:
            score += 20.0
        elif size_mb > 5:
            score += 10.0
        elif size_mb < 1:
            score -= 15.0

        # Determine best game name (prefer clean folder name over engine/generic metadata)
        candidate_name = None
        if prod_valid and not prod_name.lower().endswith('.exe'):
            candidate_name = clean_game_name(prod_name)
        elif file_desc_valid and not file_desc.lower().endswith('.exe'):
            candidate_name = clean_game_name(file_desc)
        else:
            candidate_name = clean_game_name(folder_name)

        scored.append((score, full_path, candidate_name))

    # Pick highest score
    scored.sort(key=lambda x: x[0], reverse=True)
    best_score, best_path, best_name = scored[0]

    return best_path, best_name


def scan_games_directory(root_dir: str, existing_checker=None, progress_callback=None, cancel_flag=None) -> List[Dict]:
    """
    Scans a directory (or drive) for game folders.
    Returns list of dicts: {'name': str, 'exe_path': str, 'folder_path': str}
    """
    detected_games = []
    seen_exes = set()

    if not os.path.exists(root_dir):
        return detected_games

    root_path = Path(root_dir)

    # Strategy: Look for common game root directories first, or direct children
    potential_game_dirs = []
    common_subdirs = COMMON_LAUNCHER_SUBDIRS

    has_known_lib = False
    for sub in common_subdirs:
        target = root_path / sub
        if target.exists() and target.is_dir():
            has_known_lib = True
            try:
                for child in target.iterdir():
                    if child.is_dir() and child.name.lower() not in IGNORED_DIRS and not child.name.startswith('$'):
                        potential_game_dirs.append(child)
            except PermissionError:
                pass

    # If root_dir itself is a direct games folder (e.g. D:\Games or D:\SteamLibrary\steamapps\common)
    # or if we are scanning a whole drive without special subdirs:
    try:
        for child in root_path.iterdir():
            if cancel_flag and cancel_flag():
                break
            if not child.is_dir():
                continue
            name_lower = child.name.lower()
            if name_lower in IGNORED_DIRS or name_lower.startswith('$'):
                continue
            # If child is one of the known library roots, we already handled its kids
            if any(child == (root_path / sub.split('/')[0]) for sub in common_subdirs if (root_path / sub.split('/')[0]).exists()):
                continue
            potential_game_dirs.append(child)
    except PermissionError:
        pass

    # Deduplicate
    unique_folders = []
    seen_norm = set()
    for f in potential_game_dirs:
        norm = os.path.normpath(str(f)).lower()
        if norm not in seen_norm:
            seen_norm.add(norm)
            unique_folders.append(f)

    total = len(unique_folders)
    for idx, folder in enumerate(unique_folders):
        if cancel_flag and cancel_flag():
            break

        folder_str = str(folder)
        if progress_callback:
            progress_callback(folder.name, idx + 1, total)

        if existing_checker and existing_checker(folder_path=folder_str):
            continue

        res = find_game_executable_in_folder(folder_str)
        if res:
            exe_path, game_name = res
            if exe_path not in seen_exes:
                if existing_checker and existing_checker(exe_path=exe_path):
                    continue
                seen_exes.add(exe_path)
                detected_games.append({
                    'name': game_name,
                    'exe_path': exe_path,
                    'folder_path': folder_str
                })

    return detected_games


def scan_monitored_directories(directories: List[str], existing_checker=None, progress_callback=None, cancel_flag=None) -> List[Dict]:
    """
    Scans multiple monitored directories/drives for NEW games only.
    Skips any game folder or executable that already exists in the database.
    """
    new_games = []
    seen_exes = set()
    all_target_folders = []
    common_subdirs = COMMON_LAUNCHER_SUBDIRS

    for root_dir in directories:
        if cancel_flag and cancel_flag():
            break
        if not root_dir or not os.path.exists(root_dir):
            continue

        root_path = Path(root_dir)
        has_sub = False
        for sub in common_subdirs:
            target = root_path / sub
            if target.exists() and target.is_dir():
                has_sub = True
                try:
                    for child in target.iterdir():
                        if child.is_dir() and child.name.lower() not in IGNORED_DIRS and not child.name.startswith('$'):
                            all_target_folders.append(child)
                except PermissionError:
                    pass

        try:
            for child in root_path.iterdir():
                if cancel_flag and cancel_flag():
                    break
                if not child.is_dir():
                    continue
                name_lower = child.name.lower()
                if name_lower in IGNORED_DIRS or name_lower.startswith('$'):
                    continue
                if has_sub and any(child == (root_path / sub.split('/')[0]) for sub in common_subdirs if (root_path / sub.split('/')[0]).exists()):
                    continue
                all_target_folders.append(child)
        except PermissionError:
            pass

        # Also check root_path itself if it is directly a game folder
        all_target_folders.append(root_path)

    # Deduplicate
    unique_folders = []
    seen_norm = set()
    for f in all_target_folders:
        norm = os.path.normpath(str(f)).lower()
        if norm not in seen_norm:
            seen_norm.add(norm)
            unique_folders.append(f)

    total = len(unique_folders)
    for idx, folder in enumerate(unique_folders):
        if cancel_flag and cancel_flag():
            break

        folder_str = str(folder)
        if progress_callback:
            progress_callback(folder.name, idx + 1, total)

        if existing_checker and existing_checker(folder_path=folder_str):
            continue

        res = find_game_executable_in_folder(folder_str)
        if res:
            exe_path, game_name = res
            if exe_path in seen_exes:
                continue
            if existing_checker and existing_checker(exe_path=exe_path):
                continue

            seen_exes.add(exe_path)
            new_games.append({
                'name': game_name,
                'exe_path': exe_path,
                'folder_path': folder_str
            })

    return new_games
