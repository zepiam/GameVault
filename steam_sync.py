"""
Steam Library Synchronization Module for GameVault.
Connects with local Steam client to discover installed games and owned games in the user's Steam library.
Works 100% locally with zero login or API keys required.
"""

import os
import re
import json
import winreg
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Set, Optional, Tuple

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

import sys

# Cache file for resolved Steam app names (supporting frozen PyInstaller exe)
def _get_names_cache_file() -> str:
    if getattr(sys, "frozen", False):
        base_dir = os.path.dirname(os.path.abspath(sys.executable))
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_dir, "steam_names_cache.json")


def _load_names_cache() -> Dict[str, str]:
    cache_path = _get_names_cache_file()
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save_names_cache(cache: Dict[str, str]):
    cache_path = _get_names_cache_file()
    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


def find_steam_path() -> Optional[str]:
    """Finds the root directory of the installed Steam client."""
    candidates = []
    try:
        for hive, sub, val in (
            (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath"),
        ):
            try:
                with winreg.OpenKey(hive, sub) as k:
                    v, _ = winreg.QueryValueEx(k, val)
                    if v and os.path.isdir(v):
                        candidates.append(os.path.normpath(v))
            except OSError:
                pass
    except Exception:
        pass

    candidates += [r"C:\Program Files (x86)\Steam", r"C:\Program Files\Steam"]
    for c in candidates:
        if os.path.isdir(os.path.join(c, "steamapps")) or os.path.isdir(os.path.join(c, "userdata")):
            return os.path.normpath(c)
    return None


def get_steam_libraries(steam_path: str) -> List[str]:
    """Discovers all Steam library drive directories from libraryfolders.vdf."""
    libs = [steam_path]
    vdf = os.path.join(steam_path, "steamapps", "libraryfolders.vdf")
    if os.path.exists(vdf):
        try:
            with open(vdf, "r", encoding="utf-8", errors="ignore") as f:
                txt = f.read()
            paths = re.findall(r'"path"\s+"([^"]+)"', txt)
            for p in paths:
                clean = os.path.normpath(p.replace("\\\\", "\\"))
                if os.path.isdir(clean) and clean not in libs:
                    libs.append(clean)
        except Exception:
            pass
    return libs


def get_installed_steam_games(steam_path: str) -> Dict[int, Dict]:
    """
    Finds all games currently installed in any Steam library folder.
    Returns {appid: {"name": ..., "folder_path": ..., "library": ...}}
    """
    libs = get_steam_libraries(steam_path)
    installed = {}
    for lib in libs:
        apps_dir = os.path.join(lib, "steamapps")
        if not os.path.isdir(apps_dir):
            continue
        try:
            for fn in os.listdir(apps_dir):
                if fn.startswith("appmanifest_") and fn.endswith(".acf"):
                    try:
                        with open(os.path.join(apps_dir, fn), "r", encoding="utf-8", errors="ignore") as f:
                            txt = f.read()
                        aid_m = re.search(r'"appid"\s+"(\d+)"', txt)
                        name_m = re.search(r'"name"\s+"([^"]+)"', txt)
                        dir_m = re.search(r'"installdir"\s+"([^"]+)"', txt)
                        if aid_m and name_m:
                            aid = int(aid_m.group(1))
                            name = name_m.group(1).strip()
                            idir = dir_m.group(1) if dir_m else ""
                            # Ignore non-game tools
                            if not re.match(r"^(Proton|Steam Linux Runtime|Steamworks|Steam Controller)", name, re.I):
                                installed[aid] = {
                                    "appid": aid,
                                    "name": name,
                                    "folder_path": os.path.join(apps_dir, "common", idir),
                                    "library": lib,
                                }
                    except Exception:
                        pass
        except Exception:
            pass
    return installed


def get_uninstalled_steam_games(steam_path: str, installed_ids: Set[int]) -> Set[int]:
    """
    Extracts all AppIDs owned in the user's Steam accounts from localconfig.vdf
    that are NOT currently installed.
    """
    userdata = os.path.join(steam_path, "userdata")
    if not os.path.isdir(userdata):
        return set()

    uninstalled = set()
    try:
        for uid in os.listdir(userdata):
            upath = os.path.join(userdata, uid, "config", "localconfig.vdf")
            if os.path.exists(upath):
                try:
                    with open(upath, "r", encoding="utf-8", errors="ignore") as f:
                        txt = f.read()
                    m = re.search(r'"apps"\s*\{', txt, re.I)
                    if m:
                        chunk = txt[m.start():m.start() + 1000000]
                        app_matches = re.findall(r'"([0-9]{2,10})"\s*\{', chunk)
                        for aid_str in app_matches:
                            aid = int(aid_str)
                            # Exclude tools / low IDs / already installed / steam packages
                            if aid > 200 and aid not in installed_ids:
                                uninstalled.add(aid)
                except Exception:
                    pass
    except Exception:
        pass
    return uninstalled


def fetch_steam_app_info(appid: int) -> Optional[Tuple[str, Optional[str]]]:
    """
    Queries Steam basic API for a single appid.
    Returns (app_name, header_image_url) or None if app not found/valid.
    """
    url = f"https://store.steampowered.com/api/appdetails?appids={appid}&filters=basic&l=english"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=5) as r:
            data = json.loads(r.read().decode("utf-8", errors="ignore"))
            entry = data.get(str(appid), {})
            if entry.get("success"):
                item_data = entry.get("data", {})
                name = item_data.get("name")
                if name:
                    # Clean up weird characters
                    name = name.replace("\ufffd", "").strip()
                    header_img = item_data.get("header_image")
                    return name, header_img
    except Exception:
        pass
    return None


def resolve_steam_cover(steam_path: str, appid: int, target_path: str, fallback_header_url: Optional[str] = None) -> bool:
    """
    Finds cover art for a Steam app:
    1. Checks local Steam client cache first (zero download!)
    2. Downloads from Steam CDN if not cached locally
    """
    if os.path.exists(target_path) and os.path.getsize(target_path) > 1000:
        return True

    # 1. Local Steam librarycache check
    cache_dir = os.path.join(steam_path, "appcache", "librarycache")
    local_candidates = [
        os.path.join(cache_dir, str(appid), "library_600x900.jpg"),
        os.path.join(cache_dir, f"{appid}_library_600x900.jpg"),
        os.path.join(cache_dir, str(appid), "header.jpg"),
        os.path.join(cache_dir, f"{appid}_header.jpg"),
    ]
    for cand in local_candidates:
        if os.path.exists(cand) and os.path.getsize(cand) > 1000:
            try:
                import shutil
                os.makedirs(os.path.dirname(target_path), exist_ok=True)
                shutil.copyfile(cand, target_path)
                return True
            except Exception:
                pass

    # 2. Download from official CDN
    cdn_urls = [
        f"https://shared.cloudflare.steamstatic.com/store_item_assets/steam/apps/{appid}/library_600x900.jpg",
        f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/library_600x900.jpg",
        f"https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/{appid}/library_600x900_2x.jpg",
        f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/header.jpg",
    ]
    if fallback_header_url:
        cdn_urls.append(fallback_header_url)

    for u in cdn_urls:
        try:
            req = urllib.request.Request(u, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    os.makedirs(os.path.dirname(target_path), exist_ok=True)
                    with open(target_path, "wb") as f:
                        f.write(resp.read())
                    return True
        except Exception:
            continue
    return False


def sync_steam_library_into_db(db, progress_callback=None, cancel_flag=None) -> Dict[str, int]:
    """
    Main sync function:
    - Finds installed Steam games and ensures they are in DB with is_installed = True
    - Finds uninstalled Steam games and adds them with is_installed = False
    - Returns summary stats
    """
    steam_path = find_steam_path()
    if not steam_path:
        return {"status": "error", "message": "Steam client not found on system."}

    installed = get_installed_steam_games(steam_path)
    installed_ids = set(installed.keys())
    uninstalled_ids = get_uninstalled_steam_games(steam_path, installed_ids)

    names_cache = _load_names_cache()
    # Pre-populate names_cache with installed names which we already have 100% locally
    for aid, item in installed.items():
        names_cache[str(aid)] = item["name"]

    existing_games = db.get_all_games()
    existing_by_appid = {g.get("appid"): g for g in existing_games if g.get("appid")}

    installed_added = 0
    uninstalled_added = 0

    total_tasks = len(installed) + len(uninstalled_ids)
    processed = 0

    # 1. Process Installed Steam Games (Local and fast)
    for aid, item in installed.items():
        if cancel_flag and cancel_flag():
            break
        processed += 1
        if progress_callback:
            progress_callback(item["name"], processed, total_tasks)

        g = existing_by_appid.get(aid)
        if not g and item.get("folder_path"):
            norm_target_folder = os.path.normpath(item["folder_path"]).lower()
            for eg in existing_games:
                if eg.get("folder_path") and os.path.normpath(eg.get("folder_path")).lower() == norm_target_folder:
                    g = eg
                    break
        if not g:
            # Check by name matching
            for eg in existing_games:
                if eg.get("name", "").strip().lower() == item["name"].strip().lower():
                    g = eg
                    break

        if g:
            updates = {}
            if not g.get("appid"):
                updates["appid"] = aid
            if not g.get("is_installed", True):
                updates["is_installed"] = True
            if not g.get("folder_path") and item.get("folder_path"):
                updates["folder_path"] = item["folder_path"]
            if not g.get("platform"):
                updates["platform"] = "steam"
            if updates:
                db.update_game(g["id"], **updates)
        else:
            exe_path = ""
            try:
                from scanner import find_game_executable_in_folder
                res = find_game_executable_in_folder(item["folder_path"])
                if res:
                    exe_path = res[0]
            except Exception:
                pass

            cover_dest = os.path.join(db.covers_dir, f"steam_{aid}.jpg")
            resolve_steam_cover(steam_path, aid, cover_dest)

            db.add_game(
                name=item["name"],
                exe_path=exe_path or item["folder_path"],
                folder_path=item["folder_path"],
                appid=aid,
                cover_path=cover_dest,
                is_software=False,
                item_type="game",
                is_installed=True,
                source="steam"
            )
            installed_added += 1

    # 2. Identify uninstalled games that need processing
    uninstalled_to_query = []
    for aid in uninstalled_ids:
        g = existing_by_appid.get(aid)
        if g:
            # Already in DB, make sure is_installed is False if exe does not exist
            exe = g.get("exe_path", "")
            if not exe or not os.path.exists(exe):
                if g.get("is_installed", True):
                    db.update_game(g["id"], is_installed=False)
            processed += 1
            continue

        uninstalled_to_query.append(aid)

    # 3. Resolve missing uninstalled games concurrently
    if uninstalled_to_query and not (cancel_flag and cancel_flag()):
        # Split into cached vs uncached
        needed_fetch = [aid for aid in uninstalled_to_query if str(aid) not in names_cache]

        # Fetch in parallel with 8 workers
        if needed_fetch:
            with ThreadPoolExecutor(max_workers=8) as executor:
                future_to_aid = {
                    executor.submit(fetch_steam_app_info, aid): aid
                    for aid in needed_fetch
                }
                for future in as_completed(future_to_aid):
                    if cancel_flag and cancel_flag():
                        break
                    aid = future_to_aid[future]
                    try:
                        res = future.result()
                        if res:
                            name, _ = res
                            names_cache[str(aid)] = name
                        else:
                            # Not a public game or invalid ID
                            names_cache[str(aid)] = ""
                    except Exception:
                        pass

        # Now add valid uninstalled games to DB
        for aid in uninstalled_to_query:
            if cancel_flag and cancel_flag():
                break
            processed += 1

            name = names_cache.get(str(aid), "")
            if not name:
                # Skip invalid or unlisted steam packages
                continue

            if progress_callback:
                progress_callback(name, processed, total_tasks)

            cover_dest = os.path.join(db.covers_dir, f"steam_{aid}.jpg")
            resolve_steam_cover(steam_path, aid, cover_dest)

            # Check if game already exists in library by name (merge instead of duplicate)
            name_match = None
            for eg in existing_games:
                if eg.get("name", "").strip().lower() == name.strip().lower():
                    name_match = eg
                    break
            if name_match:
                if not name_match.get("appid"):
                    db.update_game(name_match["id"], appid=aid)
                continue

            db.add_game(
                name=name,
                exe_path="",
                folder_path="",
                appid=aid,
                cover_path=cover_dest,
                is_software=False,
                item_type="game",
                is_installed=False,
                source="steam"
            )
            uninstalled_added += 1

    _save_names_cache(names_cache)

    # Recalculate true totals currently in DB
    all_g = db.get_all_games()
    inst_total = sum(1 for g in all_g if bool(g.get("is_installed", True)) and not g.get("is_software"))
    uninst_total = sum(1 for g in all_g if not bool(g.get("is_installed", True)) and not g.get("is_software"))

    return {
        "status": "success",
        "installed_total": inst_total,
        "uninstalled_total": uninst_total,
        "new_installed": installed_added,
        "new_uninstalled": uninstalled_added,
    }


def get_steam_last_played_map(steam_path: str) -> Dict[int, int]:
    """
    Extracts {appid: last_played_timestamp} from all appmanifest files and localconfig.vdf.
    Returns the latest last_played timestamp for each appid.
    """
    last_played_map = {}

    # 1. Check manifests in all library folders
    libs = get_steam_libraries(steam_path)
    for lib in libs:
        apps_dir = os.path.join(lib, "steamapps")
        if not os.path.isdir(apps_dir):
            continue
        try:
            for fn in os.listdir(apps_dir):
                if fn.startswith("appmanifest_") and fn.endswith(".acf"):
                    try:
                        with open(os.path.join(apps_dir, fn), "r", encoding="utf-8", errors="ignore") as f:
                            txt = f.read()
                        aid_m = re.search(r'"appid"\s+"(\d+)"', txt)
                        lp_m = re.search(r'"LastPlayed"\s+"(\d+)"', txt)
                        if aid_m and lp_m:
                            aid = int(aid_m.group(1))
                            lp = int(lp_m.group(1))
                            if lp > 0:
                                last_played_map[aid] = max(last_played_map.get(aid, 0), lp)
                    except Exception:
                        pass
        except Exception:
            pass

    # 2. Check localconfig.vdf across all user accounts
    userdata = os.path.join(steam_path, "userdata")
    if os.path.isdir(userdata):
        try:
            for uid in os.listdir(userdata):
                upath = os.path.join(userdata, uid, "config", "localconfig.vdf")
                if os.path.exists(upath):
                    try:
                        with open(upath, "r", encoding="utf-8", errors="ignore") as f:
                            txt = f.read()
                        matches = re.findall(r'"([0-9]{2,10})"\s*\{[^}]*?"LastPlayed"\s*"(\d+)"', txt, re.DOTALL)
                        for aid_str, lp_str in matches:
                            aid = int(aid_str)
                            lp = int(lp_str)
                            if lp > 0:
                                last_played_map[aid] = max(last_played_map.get(aid, 0), lp)
                    except Exception:
                        pass
        except Exception:
            pass

    return last_played_map


def check_and_update_installed_steam_games(db) -> int:
    """
    Super-fast lightweight check (takes 2-5ms) comparing Steam appmanifest files
    and localconfig.vdf with games in DB.
    If an uninstalled Steam game has now been installed, it updates:
      - is_installed = True
      - folder_path
      - exe_path
    Syncs Steam LastPlayed timestamps into GameVault's last_played.
    If an installed Steam game was uninstalled in Steam, it marks is_installed = False.
    """
    steam_path = find_steam_path()
    if not steam_path:
        return 0

    installed_map = get_installed_steam_games(steam_path)
    lp_map = get_steam_last_played_map(steam_path)
    all_games = db.get_all_games()
    changed = 0

    for g in all_games:
        aid = g.get("appid")
        if not aid:
            continue
        try:
            aid = int(aid)
        except (ValueError, TypeError):
            continue

        is_currently_installed = bool(g.get("is_installed", True))
        steam_lp = lp_map.get(aid, 0)
        curr_lp = g.get("last_played") or 0

        updates = {}
        if steam_lp > curr_lp:
            updates["last_played"] = steam_lp

        if aid in installed_map:
            # Game is installed according to Steam manifest!
            steam_info = installed_map[aid]
            folder = steam_info.get("folder_path", "")
            if not is_currently_installed:
                # Newly installed!
                exe_path = g.get("exe_path", "")
                if not exe_path or not os.path.exists(exe_path):
                    if folder and os.path.isdir(folder):
                        try:
                            from scanner import find_game_executable_in_folder
                            res = find_game_executable_in_folder(folder)
                            if res:
                                exe_path = res[0]
                        except Exception:
                            pass
                updates["is_installed"] = True
                updates["folder_path"] = folder or g.get("folder_path", "")
                updates["exe_path"] = exe_path or folder or g.get("exe_path", "")
                changed += 1
            else:
                # Already marked installed, but ensure folder_path is saved if empty
                if not g.get("folder_path") and folder:
                    updates["folder_path"] = folder
        else:
            # Not in Steam manifests
            # If it's a Steam source game and was marked installed, check if folder/exe still exists
            if g.get("source") == "steam" and is_currently_installed:
                folder = g.get("folder_path", "")
                exe = g.get("exe_path", "")
                folder_exists = bool(folder and os.path.isdir(folder))
                exe_exists = bool(exe and os.path.exists(exe))
                if not folder_exists and not exe_exists:
                    updates["is_installed"] = False
                    changed += 1

        if updates:
            db.update_game(g["id"], **updates)
            if "last_played" in updates and len(updates) == 1:
                changed += 1

    return changed
