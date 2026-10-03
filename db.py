"""
Database and Persistence Manager for GameVault.
Stores games in games.json and handles additions, edits, and deletions.
"""

import os
import json
import uuid
import time
from typing import List, Dict, Optional


class LibraryDB:
    def __init__(self, db_path: str = "games.json", covers_dir: str = "covers"):
        self.db_path = db_path
        self.covers_dir = covers_dir
        os.makedirs(self.covers_dir, exist_ok=True)
        self.games: List[Dict] = []
        self.settings: Dict = {"card_size": 185}
        self.load()

    def load(self):
        if os.path.exists(self.db_path):
            try:
                with open(self.db_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        self.games = data
                    elif isinstance(data, dict):
                        self.games = data.get("games", [])
                        self.settings = data.get("settings", {"card_size": 185})
            except Exception as e:
                print(f"[LibraryDB] Error loading {self.db_path}: {e}")
                self.games = []
        else:
            self.games = []

    def save(self):
        try:
            with open(self.db_path, "w", encoding="utf-8") as f:
                json.dump({"games": self.games, "settings": self.settings}, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[LibraryDB] Error saving {self.db_path}: {e}")

    def get_setting(self, key: str, default=None):
        return self.settings.get(key, default)

    def set_setting(self, key: str, val):
        self.settings[key] = val
        self.save()

    def get_all_games(self) -> List[Dict]:
        return list(self.games)

    def get_game(self, game_id: str) -> Optional[Dict]:
        for g in self.games:
            if g.get("id") == game_id:
                return g
        return None

    def get_monitored_folders(self) -> List[str]:
        """Returns list of directories monitored for games. Infers from existing games if empty."""
        folders = self.get_setting("monitored_folders", None)
        if folders is None:
            inferred = set()
            for g in self.games:
                fpath = g.get("folder_path")
                if fpath:
                    parent = os.path.dirname(fpath)
                    if parent and os.path.exists(parent):
                        inferred.add(os.path.normpath(parent))
            folders = sorted(list(inferred))
            self.set_setting("monitored_folders", folders)
        return list(folders)

    def add_monitored_folder(self, folder: str) -> bool:
        """Adds a directory to monitored folders list."""
        if not folder or not os.path.exists(folder):
            return False
        norm = os.path.normpath(folder)
        folders = self.get_monitored_folders()
        for f in folders:
            if os.path.normpath(f).lower() == norm.lower():
                return False
        folders.append(norm)
        self.set_setting("monitored_folders", folders)
        return True

    def remove_monitored_folder(self, folder: str):
        """Removes a directory from monitored folders list."""
        norm = os.path.normpath(folder).lower()
        folders = [f for f in self.get_monitored_folders() if os.path.normpath(f).lower() != norm]
        self.set_setting("monitored_folders", folders)

    def is_game_known(self, exe_path: Optional[str] = None, folder_path: Optional[str] = None) -> bool:
        """Quickly checks if an executable path or folder path already belongs to any game or was intentionally removed."""
        norm_exe = os.path.normpath(exe_path).lower() if exe_path else ""
        norm_folder = os.path.normpath(folder_path).lower() if folder_path else ""

        # Check ignored/removed list so removed games are never re-scanned
        ignored = [os.path.normpath(x).lower() for x in self.get_setting("ignored_paths", [])]
        if norm_exe and norm_exe in ignored:
            return True
        if norm_folder and norm_folder in ignored:
            return True

        for g in self.games:
            g_exe = os.path.normpath(g.get("exe_path", "")).lower()
            g_folder = os.path.normpath(g.get("folder_path", "")).lower()
            if norm_exe and g_exe == norm_exe:
                return True
            if norm_folder and g_folder == norm_folder:
                return True
        return False

    def add_game(self, name: str, exe_path: str, folder_path: str, appid: Optional[int] = None, cover_path: Optional[str] = None, is_software: bool = False, item_type: str = "game") -> Dict:
        # Check if game with exact exe_path or folder_path already exists (protect existing entries)
        norm_exe = os.path.normpath(exe_path).lower()
        norm_folder = os.path.normpath(folder_path).lower() if folder_path else ""
        for existing in self.games:
            if os.path.normpath(existing.get("exe_path", "")).lower() == norm_exe:
                return existing
            if norm_folder and os.path.normpath(existing.get("folder_path", "")).lower() == norm_folder:
                return existing

        # If path was in ignored_paths, remove it since user/action explicitly re-added it
        ignored = self.get_setting("ignored_paths", [])
        new_ignored = [x for x in ignored if os.path.normpath(x).lower() not in (norm_exe, norm_folder)]
        if len(new_ignored) != len(ignored):
            self.set_setting("ignored_paths", new_ignored)

        game_id = str(uuid.uuid4())
        default_cover = os.path.join(self.covers_dir, f"{game_id}.jpg")
        game = {
            "id": game_id,
            "name": name,
            "exe_path": exe_path,
            "folder_path": folder_path,
            "appid": appid,
            "cover_path": cover_path or default_cover,
            "play_count": 0,
            "last_played": None,
            "date_added": time.time(),
            "is_software": is_software,
            "item_type": item_type if is_software else "game"
        }
        self.games.append(game)
        self.save()
        return game

    def update_game(self, game_id: str, **updates):
        for g in self.games:
            if g.get("id") == game_id:
                g.update(updates)
                self.save()
                return g
        return None

    def remove_game(self, game_id: str):
        game = self.get_game(game_id)
        if game:
            cover_path = game.get("cover_path")
            if cover_path and os.path.exists(cover_path) and self.covers_dir in cover_path:
                try:
                    os.remove(cover_path)
                except OSError:
                    pass

            # Remember removed paths in ignored list so scanner never re-adds it
            ignored = self.get_setting("ignored_paths", [])
            for p in [game.get("exe_path"), game.get("folder_path")]:
                if p:
                    norm = os.path.normpath(p).lower()
                    if norm not in [os.path.normpath(x).lower() for x in ignored]:
                        ignored.append(norm)
            self.set_setting("ignored_paths", ignored)

            self.games = [g for g in self.games if g.get("id") != game_id]
            self.save()

    def get_recently_played_games(self, limit: int = 5, include_software: bool = False) -> List[Dict]:
        """Returns the top N most recently played items, sorted by last_played descending."""
        pool = self.games if include_software else [
            g for g in self.games if not (g.get("is_software") or g.get("item_type") == "software")
        ]
        played = [g for g in pool if g.get("last_played") and g.get("last_played", 0) > 0]
        played.sort(key=lambda x: x.get("last_played", 0), reverse=True)
        if len(played) >= limit:
            return played[:limit]

        # Supplement with favorites if fewer than limit
        res = list(played)
        seen_ids = {g["id"] for g in res}
        favorites = [g for g in pool if g.get("is_favorite") and g["id"] not in seen_ids]
        for f in favorites:
            res.append(f)
            seen_ids.add(f["id"])
            if len(res) >= limit:
                return res[:limit]

        # Supplement with remaining items in pool
        others = [g for g in pool if g["id"] not in seen_ids]
        for o in others:
            res.append(o)
            if len(res) >= limit:
                break
        return res

    def record_play(self, game_id: str):
        game = self.get_game(game_id)
        if game:
            game["play_count"] = game.get("play_count", 0) + 1
            game["last_played"] = time.time()
            self.save()

    def toggle_favorite(self, game_id: str) -> bool:
        game = self.get_game(game_id)
        if game:
            new_val = not bool(game.get("is_favorite", False))
            game["is_favorite"] = new_val
            self.save()
            return new_val
        return False

    def get_border_categories(self) -> List[Dict]:
        """
        Returns customizable border color categories:
        [{"color": "#ef4444", "name": "สีแดง"}, ...]
        """
        default_categories = [
            {"color": "#ef4444", "name": "สีแดง"},
            {"color": "#38bdf8", "name": "สีฟ้า"},
            {"color": "#a855f7", "name": "สีม่วง"},
            {"color": "#22c55e", "name": "สีเขียว"},
            {"color": "#eab308", "name": "สีเหลือง"},
            {"color": "#f97316", "name": "สีส้ม"},
            {"color": "#ec4899", "name": "สีชมพู"},
        ]
        return self.get_setting("border_categories", default_categories)

    def set_border_categories(self, categories: List[Dict]):
        self.set_setting("border_categories", categories)

