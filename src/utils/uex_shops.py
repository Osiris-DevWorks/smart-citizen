"""Where items are sold in game, from UEX, for the SCO drawer's Item Finder (3.1.0).

The game files no longer hold shop stock: CIG serves it from its own
servers, so Data.p4k has nothing to read. UEX (uexcorp.space) collects it
from player reports and serves it through a free API that needs no key:

- ``items_prices_all``: every item at every shop terminal, with its last
  reported buy price (about 24,000 rows, 6 MB).
- ``terminals?type=item``: where each shop terminal is (shop, city or
  station, planet or moon, star system) and whether it is in the LIVE game.

Both are fetched at most once per ``MAX_AGE_S`` (UEX itself caches them for
12 hours) and only what the finder shows is kept, in one small JSON file
in the channel cache (``SHOP_CACHE_FILE``). A fetch that fails falls back to
that file, however old, so the finder still works offline. Nothing about
the player is sent: two plain GET requests with the app's name and version.

Stdlib only, no Qt: ``workers.UexShopDataWorker`` runs ``load_shop_data``
off the GUI thread, and the tests run it with a fake opener.
"""
from __future__ import annotations

import gzip
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional
from urllib.request import Request, urlopen

from src.utils.atomic_io import atomic_write_text, read_bytes_retrying

logger = logging.getLogger(__name__)

UEX_API = "https://api.uexcorp.uk/2.0"
PRICES_URL = f"{UEX_API}/items_prices_all"
TERMINALS_URL = f"{UEX_API}/terminals?type=item"
# Where the finder sends a player who wants more than it shows.
UEX_SITE = "uexcorp.space"
SHOP_CACHE_FILE = "uex_shops.json"
CACHE_VERSION = 1
# UEX refreshes these every 12 hours, so fetching more often gains nothing.
MAX_AGE_S = 12 * 60 * 60
# After a load, how long the app waits before it tries UEX again (offline,
# every overlay option change would otherwise ask).
UEX_RETRY_S = 10 * 60
REQUEST_TIMEOUT_S = 20
# How many items one search lists; typing more narrows it.
MATCH_LIMIT = 50

Opener = Callable[[str], bytes]


@dataclass(frozen=True)
class ShopLocation:
    """One shop that sells an item, and where it is."""
    shop: str        # "Casaba Outlet"
    place: str       # "Area 18": a city, station or outpost
    body: str        # "ArcCorp": the planet or moon, "" in open space
    system: str      # "Stanton"
    price: float     # last reported buy price, aUEC per unit
    reported: int    # when that price was reported, Unix time (0: unknown)


@dataclass(frozen=True)
class ItemMatch:
    """An item the search found, with every shop that sells it, cheapest first."""
    name: str
    locations: tuple[ShopLocation, ...]


@dataclass
class ShopData:
    """What the finder searches: item names and the shops selling each."""
    fetched_at: float = 0.0
    items: dict[int, str] = field(default_factory=dict)
    # id -> (shop, place, body, system)
    terminals: dict[int, tuple[str, str, str, str]] = field(default_factory=dict)
    # item id -> [(terminal id, price, reported)]
    prices: dict[int, list[tuple[int, float, int]]] = field(default_factory=dict)

    def is_empty(self) -> bool:
        return not self.prices

    def search(self, needle: str, limit: int = MATCH_LIMIT) -> tuple[list[ItemMatch], int]:
        """Items whose name holds *needle* (any case), by name, and how many
        matched in all (more than *limit* when the list was cut short)."""
        needle = needle.strip().casefold()
        if not needle:
            return [], 0
        found = sorted((name.casefold(), item_id) for item_id, name in self.items.items()
                       if item_id in self.prices and needle in name.casefold())
        matches = []
        for _, item_id in found[:limit]:
            locations = []
            for terminal_id, price, reported in self.prices[item_id]:
                terminal = self.terminals.get(terminal_id)
                if terminal is not None:
                    locations.append(ShopLocation(*terminal, price, reported))
            if locations:
                locations.sort(key=lambda loc: (loc.price, loc.system, loc.place, loc.shop))
                matches.append(ItemMatch(self.items[item_id], tuple(locations)))
        return matches, len(found)


def _shop_and_place(terminal: dict) -> tuple[str, str, str, str]:
    """A terminal's shop, place, body and system. UEX names a shop terminal
    "<shop> - <more> - <place>"; the place is taken from its own fields."""
    place = (terminal.get("city_name") or terminal.get("space_station_name")
             or terminal.get("outpost_name") or terminal.get("displayname") or "")
    name = terminal.get("name") or terminal.get("fullname") or ""
    shop = name.split(" - ")[0].strip() or place
    body = terminal.get("moon_name") or terminal.get("planet_name") or ""
    return shop, place.strip(), body, terminal.get("star_system_name") or ""


def build_shop_data(prices: list, terminals: list, fetched_at: float) -> ShopData:
    """Keep what the finder shows from UEX's two answers: shops in the LIVE
    game, and items with a buy price at one of them."""
    data = ShopData(fetched_at=fetched_at)
    for terminal in terminals:
        if terminal.get("is_available_live") and terminal.get("id"):
            data.terminals[int(terminal["id"])] = _shop_and_place(terminal)
    for row in prices:
        try:
            item_id, terminal_id = int(row["id_item"]), int(row["id_terminal"])
            price = float(row.get("price_buy") or 0)
        except (KeyError, TypeError, ValueError):
            continue
        name = (row.get("item_name") or "").strip()
        if price <= 0 or not name or terminal_id not in data.terminals:
            continue
        data.items.setdefault(item_id, name)
        reported = int(row.get("date_modified") or row.get("date_added") or 0)
        data.prices.setdefault(item_id, []).append((terminal_id, price, reported))
    # Only the shops something is sold at.
    used = {t for rows in data.prices.values() for t, _, _ in rows}
    data.terminals = {t: v for t, v in data.terminals.items() if t in used}
    return data


def _to_json(data: ShopData) -> str:
    return json.dumps({
        "version": CACHE_VERSION,
        "fetched_at": data.fetched_at,
        "items": {str(k): v for k, v in data.items.items()},
        "terminals": {str(k): list(v) for k, v in data.terminals.items()},
        "prices": {str(k): [list(r) for r in v] for k, v in data.prices.items()},
    }, ensure_ascii=False, separators=(",", ":"))


def read_cache(path: Path) -> Optional[ShopData]:
    """The cached shop data, or None when there is none or it can't be read."""
    try:
        raw = json.loads(read_bytes_retrying(path).decode("utf-8"))
        if raw.get("version") != CACHE_VERSION:
            return None
        return ShopData(
            fetched_at=float(raw["fetched_at"]),
            items={int(k): v for k, v in raw["items"].items()},
            terminals={int(k): tuple(v) for k, v in raw["terminals"].items()},
            prices={int(k): [(int(t), float(p), int(r)) for t, p, r in v]
                    for k, v in raw["prices"].items()},
        )
    except FileNotFoundError:
        return None
    except (OSError, ValueError, KeyError, TypeError) as e:
        logger.warning(f"UEX shop cache {path} could not be read ({e}), ignoring it")
        return None


def default_opener(user_agent: str) -> Opener:
    """GET a URL and return its body, gzip or not."""
    def open_url(url: str) -> bytes:
        request = Request(url, headers={"User-Agent": user_agent,
                                        "Accept": "application/json",
                                        "Accept-Encoding": "gzip"})
        with urlopen(request, timeout=REQUEST_TIMEOUT_S) as response:
            body = response.read()
            if response.headers.get("Content-Encoding", "").lower() == "gzip":
                body = gzip.decompress(body)
            return body
    return open_url


def _fetch_list(opener: Opener, url: str) -> list:
    answer = json.loads(opener(url).decode("utf-8"))
    if not isinstance(answer, dict) or answer.get("status") != "ok" \
            or not isinstance(answer.get("data"), list):
        status = answer.get("status") if isinstance(answer, dict) else type(answer).__name__
        raise ValueError(f"UEX answered {url} with status {status!r}")
    return answer["data"]


def fetch_shop_data(opener: Opener, now: Optional[float] = None) -> ShopData:
    """Ask UEX for the shops and their stock. Raises on any failure."""
    terminals = _fetch_list(opener, TERMINALS_URL)
    prices = _fetch_list(opener, PRICES_URL)
    return build_shop_data(prices, terminals, time.time() if now is None else now)


def load_shop_data(cache_path: Path, opener: Opener, *, force: bool = False,
                   now: Optional[float] = None) -> tuple[Optional[ShopData], str]:
    """The shop data to show, and why it is that one.

    A cache younger than ``MAX_AGE_S`` is used as it is, unless *force*.
    Otherwise UEX is asked and the answer saved over the cache; when that
    fails the old cache is used, however old, and the reason is the error.
    Returns ``(data or None, "")`` on success, ``(cache or None, error)`` on
    a failed fetch.
    """
    now = time.time() if now is None else now
    cached = read_cache(cache_path)
    if cached is not None and not force and 0 <= now - cached.fetched_at < MAX_AGE_S:
        return cached, ""
    try:
        data = fetch_shop_data(opener, now)
    except Exception as e:  # network, HTTP, JSON: all mean "use what we have"
        logger.warning(f"UEX shop data could not be fetched ({e}); "
                       f"{'using the cache from before' if cached else 'no cache to fall back on'}")
        return cached, str(e) or type(e).__name__
    if data.is_empty():
        logger.warning("UEX sent no shop prices; keeping the cache from before")
        return cached, "UEX sent no shop prices"
    try:
        atomic_write_text(cache_path, _to_json(data))
    except OSError as e:
        logger.warning(f"UEX shop cache {cache_path} could not be written ({e})")
    logger.info(f"UEX shop data: {len(data.items)} items at {len(data.terminals)} shops")
    return data, ""
