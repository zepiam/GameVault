"""
Cover Art Fetcher and Steam Store Metadata Manager for GameVault.
Fetches official Steam portrait covers (600x900), game descriptions, and screenshots.
"""

import os
import re
import urllib.request
import urllib.parse
import json
import io
from typing import Optional, List, Dict, Tuple
from PIL import Image, ImageOps

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


def extract_steam_appid(text: str) -> Optional[int]:
    """
    Extracts Steam AppID from a URL or raw string.
    Examples:
    - 'https://store.steampowered.com/app/2243710/Rune_Factory_3_Special/' -> 2243710
    - 'https://steamcommunity.com/app/2243710' -> 2243710
    - '2243710' -> 2243710
    """
    if not text:
        return None
    text = text.strip()

    # If it's pure digits
    if text.isdigit():
        return int(text)

    # Match /app/12345
    match = re.search(r'/app/(\d+)', text)
    if match:
        return int(match.group(1))

    return None


def search_steam_games(query: str, max_results: int = 8) -> List[Dict]:
    """
    Searches the Steam Store API for games matching the query.
    Returns list of dicts with appid, name, tiny_image, poster_url, header_url.
    """
    clean_query = urllib.parse.quote(query.strip())
    url = f"https://store.steampowered.com/api/storesearch/?term={clean_query}&l=english&cc=US"

    results = []
    try:
        req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            items = data.get('items', [])
            for item in items[:max_results]:
                appid = item.get('id')
                name = item.get('name')
                tiny_img = item.get('tiny_image')
                poster_url = f"https://shared.cloudflare.steamstatic.com/store_item_assets/steam/apps/{appid}/library_600x900.jpg"
                header_url = f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/header.jpg"
                results.append({
                    'appid': appid,
                    'name': name,
                    'tiny_image': tiny_img or header_url,
                    'poster_url': poster_url,
                    'header_url': header_url,
                    'source': 'steam'
                })
    except Exception as e:
        print(f"[CoverFetcher] Error searching Steam for '{query}': {e}")

    return results


def search_steamgriddb_covers(query: str, api_key: str, max_results: int = 12) -> List[Dict]:
    """
    Searches SteamGridDB API v2 for 600x900 vertical covers.
    Requires free API key from https://www.steamgriddb.com/profile/preferences/api
    """
    if not api_key:
        return []

    clean_query = urllib.parse.quote(query.strip())
    headers = {
        'User-Agent': USER_AGENT,
        'Authorization': f'Bearer {api_key.strip()}'
    }

    results = []
    try:
        # Step 1: Search game autocomplete
        url_search = f"https://www.steamgriddb.com/api/v2/search/autocomplete/{clean_query}"
        req1 = urllib.request.Request(url_search, headers=headers)
        with urllib.request.urlopen(req1, timeout=6) as r1:
            data1 = json.loads(r1.read().decode('utf-8'))
            games = data1.get('data', [])

        if not games:
            return results

        # Step 2: For top matched game, fetch vertical grids (600x900)
        game_id = games[0].get('id')
        game_name = games[0].get('name', query)
        url_grids = f"https://www.steamgriddb.com/api/v2/grids/game/{game_id}?dimensions=600x900"
        req2 = urllib.request.Request(url_grids, headers=headers)
        with urllib.request.urlopen(req2, timeout=6) as r2:
            data2 = json.loads(r2.read().decode('utf-8'))
            grids = data2.get('data', [])
            for g in grids[:max_results]:
                author = g.get('author', {}).get('name', 'Community') if isinstance(g.get('author'), dict) else 'Community'
                results.append({
                    'appid': None,
                    'name': f"{game_name} ({author})",
                    'poster_url': g.get('url'),
                    'tiny_image': g.get('thumb') or g.get('url'),
                    'header_url': g.get('url'),
                    'source': 'steamgriddb'
                })
    except Exception as e:
        print(f"[CoverFetcher] SteamGridDB API error: {e}")

    return results


def test_steamgriddb_key(api_key: str) -> Tuple[bool, str]:
    """
    Validates a SteamGridDB API key against their API endpoint.
    """
    if not api_key or not api_key.strip():
        return False, "API Key is empty. Please enter your key."
    clean_key = api_key.strip()
    headers = {
        'User-Agent': USER_AGENT,
        'Authorization': f'Bearer {clean_key}'
    }
    try:
        url = "https://www.steamgriddb.com/api/v2/search/autocomplete/test"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=6) as resp:
            if resp.status == 200:
                return True, "API Key is valid and connected successfully!"
            return False, f"Server returned HTTP {resp.status}"
    except urllib.error.HTTPError as he:
        if he.code == 401:
            return False, "Invalid API Key (HTTP 401 Unauthorized). Please check your key."
        return False, f"HTTP Error: {he.code}"
    except Exception as e:
        return False, f"Connection failed: {e}"


def download_steam_cover(appid: int, save_path: str) -> bool:
    """
    Downloads the Steam vertical library cover (or fallback header) to save_path.
    """
    candidates = [
        f"https://shared.cloudflare.steamstatic.com/store_item_assets/steam/apps/{appid}/library_600x900.jpg",
        f"https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/{appid}/library_600x900_2x.jpg",
        f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/library_600x900_2x.jpg",
        f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/header.jpg"
    ]

    for img_url in candidates:
        try:
            req = urllib.request.Request(img_url, headers={'User-Agent': USER_AGENT})
            with urllib.request.urlopen(req, timeout=8) as resp:
                if resp.status == 200:
                    os.makedirs(os.path.dirname(save_path), exist_ok=True)
                    with open(save_path, 'wb') as f:
                        f.write(resp.read())
                    return True
        except Exception:
            continue
    return False


def get_steam_app_details(appid: int) -> Optional[Dict]:
    """
    Fetches game metadata from Steam store API:
    - description, screenshots, release date, genres, developers
    """
    url = f"https://store.steampowered.com/api/appdetails?appids={appid}&l=english"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            entry = data.get(str(appid), {})
            if not entry.get('success'):
                return None

            app_data = entry.get('data', {})
            genres = [g.get('description', '') for g in app_data.get('genres', [])]

            screenshots = []
            screenshots_full = []
            for sc in app_data.get('screenshots', [])[:4]:
                screenshots.append(sc.get('path_thumbnail', ''))
                screenshots_full.append(sc.get('path_full', ''))

            return {
                'appid': appid,
                'name': app_data.get('name', ''),
                'short_description': app_data.get('short_description', ''),
                'genres': ', '.join(genres),
                'release_date': app_data.get('release_date', {}).get('date', ''),
                'developers': ', '.join(app_data.get('developers', [])),
                'publishers': ', '.join(app_data.get('publishers', [])),
                'header_image': app_data.get('header_image', ''),
                'screenshots': screenshots,
                'screenshots_full': screenshots_full,
                'steam_url': f"https://store.steampowered.com/app/{appid}/"
            }
    except Exception as e:
        print(f"[CoverFetcher] Error fetching appdetails for appid {appid}: {e}")
        return None


def download_file_to(url: str, save_path: str) -> bool:
    """Downloads a remote file and saves it locally."""
    if not url:
        return False
    try:
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
        with urllib.request.urlopen(req, timeout=8) as resp:
            if resp.status == 200:
                with open(save_path, 'wb') as f:
                    f.write(resp.read())
                return True
    except Exception as e:
        print(f"[CoverFetcher] Failed to download {url}: {e}")
    return False


def cache_game_screenshots(game_id: str, screenshot_urls: List[str], covers_dir: str) -> List[str]:
    """Downloads screenshot thumbnails locally and returns their local file paths."""
    local_paths = []
    for idx, url in enumerate(screenshot_urls):
        local_path = os.path.join(covers_dir, f"{game_id}_ss_{idx}.jpg")
        if not os.path.exists(local_path):
            download_file_to(url, local_path)
        if os.path.exists(local_path):
            local_paths.append(local_path)
    return local_paths


def fetch_game_full_by_appid(appid: int, save_cover_path: str) -> Optional[Dict]:
    """
    Given an appid: downloads its cover and returns full metadata (description, screenshots, etc.).
    """
    download_steam_cover(appid, save_cover_path)
    details = get_steam_app_details(appid)
    return details


def fetch_cover_and_details_by_id_or_url(query_or_url: str, save_cover_path: str) -> Optional[Dict]:
    """
    Given a Steam store URL or raw AppID string, downloads cover and returns full metadata.
    """
    appid = extract_steam_appid(query_or_url)
    if appid:
        return fetch_game_full_by_appid(appid, save_cover_path)
    return None


def fetch_cover_for_game(game_name: str, save_path: str) -> Optional[Dict]:
    """
    Auto-searches Steam for the game, downloads cover, and returns full metadata if found.
    """
    matches = search_steam_games(game_name, max_results=3)
    if not matches:
        short_name = game_name.split(':')[0].split('-')[0].strip()
        if short_name != game_name:
            matches = search_steam_games(short_name, max_results=3)

    if matches:
        best_match = matches[0]
        appid = best_match['appid']
        download_steam_cover(appid, save_path)
        details = get_steam_app_details(appid)
        if details:
            return details
        return {'appid': appid, 'name': best_match['name']}

    return None


def download_and_process_image_url(image_url: str, save_path: str, target_width: int = 600, target_height: int = 900) -> bool:
    """
    Downloads an image from any HTTP/HTTPS URL, crops/resizes it to 2:3 ratio (default 600x900),
    and saves as a high-quality JPEG.
    """
    clean_url = image_url.strip()
    if not (clean_url.startswith('http://') or clean_url.startswith('https://')):
        return False

    try:
        req = urllib.request.Request(clean_url, headers={'User-Agent': USER_AGENT})
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = resp.read()

        img = Image.open(io.BytesIO(data))
        rgb_img = img.convert('RGB')
        # Center-crop & scale to exact 2:3 ratio (default 600x900)
        fitted = ImageOps.fit(rgb_img, (target_width, target_height), method=Image.Resampling.LANCZOS)
        dirname = os.path.dirname(save_path)
        if dirname:
            os.makedirs(dirname, exist_ok=True)
        fitted.save(save_path, 'JPEG', quality=95)
        return True
    except Exception as e:
        print(f"[CoverFetcher] Failed to download/process image URL '{image_url}': {e}")
        return False


def save_custom_cover(src_image_path: str, dest_cover_path: str, target_width: int = 600, target_height: int = 900) -> bool:
    """
    Imports and optimizes a user-uploaded image for the cover, resizing to 600x900.
    """
    try:
        with Image.open(src_image_path) as img:
            rgb_img = img.convert('RGB')
            fitted = ImageOps.fit(rgb_img, (target_width, target_height), method=Image.Resampling.LANCZOS)
            dirname = os.path.dirname(dest_cover_path)
            if dirname:
                os.makedirs(dirname, exist_ok=True)
            fitted.save(dest_cover_path, 'JPEG', quality=95)
        return True
    except Exception as e:
        print(f"[CoverFetcher] Failed to save custom cover: {e}")
        return False
