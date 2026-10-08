import logging
import re
import urllib.parse

import requests

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = "GdG-Event-Bot/1.0 (+https://github.com/destard/GdG-Event-Bot)"
BGG_SEARCH_URL = "https://api.geekdo.com/api/geekitems?objecttype=thing&search="
BGG_DETAIL_URL = "https://api.geekdo.com/api/geekitems?objecttype=thing&objectid="

ACCESSORY_RE = re.compile(
    r"\b(\d+\s*x\s*\d+\s*mm|sleeves?|enamel|coins?|tokens?|insert|organizer|playmat|dice bag|promo pack|promo card|upgrade kit|goodie|neoprene|custom dice)\b",
    re.I,
)


def pick_best_bgg_item(items, query):
    """Exact name match, else the first non-accessory containing the query, else any non-accessory, else the first item."""
    q_norm = query.lower()
    named = [(item, item.get("name", "").strip()) for item in items]

    for item, name in named:
        if name.lower() == q_norm:
            return item
    for item, name in named:
        if not ACCESSORY_RE.search(name) and q_norm in name.lower():
            return item
    for item, name in named:
        if not ACCESSORY_RE.search(name):
            return item
    return items[0]


def bgg_image_url(item_data):
    """Prefers the high-resolution 'original' image over 'imageurl'."""
    images = item_data.get("images")
    url = images.get("original") if isinstance(images, dict) else None
    url = url or item_data.get("imageurl")
    if url and url.startswith("//"):
        url = "https:" + url
    return url


def fetch_bgg_game_image(game_name: str, timeout: int = 10) -> bytes | None:
    if not game_name or not game_name.strip():
        return None
    q = game_name.strip()
    headers = {"User-Agent": DEFAULT_USER_AGENT, "Accept": "application/json"}

    try:
        resp = requests.get(f"{BGG_SEARCH_URL}{urllib.parse.quote(q)}", headers=headers, timeout=timeout)
        if resp.status_code != 200:
            logger.warning(f"BGG search for '{q}' returned status {resp.status_code}")
            return None

        items = resp.json().get("items", [])
        if not items:
            logger.info(f"No BGG search items found for '{q}'")
            return None

        object_id = pick_best_bgg_item(items, q).get("objectid")
        if not object_id:
            return None

        det_resp = requests.get(f"{BGG_DETAIL_URL}{object_id}", headers=headers, timeout=timeout)
        if det_resp.status_code != 200:
            logger.warning(f"BGG item detail fetch for ID {object_id} returned {det_resp.status_code}")
            return None

        image_url = bgg_image_url(det_resp.json().get("item", {}))
        if not image_url:
            logger.info(f"No image URL found in BGG item for '{q}' (ID: {object_id})")
            return None

        img_resp = requests.get(image_url, headers=headers, timeout=timeout + 5)
        if img_resp.status_code == 200:
            return img_resp.content
        logger.warning(f"Failed to download image from {image_url}: status {img_resp.status_code}")
        return None

    except Exception as e:
        logger.error(f"Error fetching BGG image for '{q}': {e}")
        return None
