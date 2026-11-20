"""The SCO Item Finder's shop data (``src/utils/uex_shops.py``), Qt-free.

UEX's two answers are faked with rows shaped like the real API's (read
from api.uexcorp.uk on 2026-11-20), so nothing goes over the network.
"""
from __future__ import annotations

import gzip
import json

import pytest

from src.utils import uex_shops
from src.utils.uex_shops import (
    MAX_AGE_S, PRICES_URL, TERMINALS_URL, build_shop_data, default_opener, load_shop_data,
    read_cache,
)

NOW = 1_800_000_000.0


def _terminal(id_, name, *, city=None, station=None, planet="ArcCorp", moon=None,
              system="Stanton", live=1):
    return {"id": id_, "name": name, "fullname": name, "displayname": city or station,
            "city_name": city, "space_station_name": station, "outpost_name": None,
            "planet_name": planet, "moon_name": moon, "star_system_name": system,
            "is_available_live": live, "type": "item"}


TERMINALS = [
    _terminal(1, "CenterMass - IO North Tower - Area 18", city="Area 18"),
    _terminal(2, "Casaba Outlet - Port Tressler", station="Port Tressler", planet="MicroTech"),
    _terminal(3, "Conscientious Objects - Levski", city="Levski", planet=None,
              moon="Delamar", system="Nyx"),
    _terminal(4, "Cordry's - Levski", city="Levski", planet=None, system="Nyx", live=0),
]


def _price(item, terminal, name, buy, modified=1_790_000_000):
    return {"id_item": item, "id_terminal": terminal, "item_name": name,
            "price_buy": buy, "price_sell": 0, "date_modified": modified,
            "date_added": 1_700_000_000}


PRICES = [
    _price(10, 1, 'P4-AR "Warhawk" Rifle', 4757),
    _price(10, 3, 'P4-AR "Warhawk" Rifle', 4600),
    _price(11, 2, "P4-AR Magazine (40 Cap)", 198),
    _price(11, 4, "P4-AR Magazine (40 Cap)", 150),   # shop not in LIVE
    _price(12, 1, "Sell-only thing", 0),             # no buy price
    _price(13, 99, "Unknown shop item", 50),         # terminal UEX did not list
]


def _data():
    return build_shop_data(PRICES, TERMINALS, NOW)


def test_only_live_shops_and_buy_prices_are_kept():
    data = _data()
    assert set(data.items) == {10, 11}
    assert set(data.terminals) == {1, 2, 3}
    assert [t for t, _, _ in data.prices[11]] == [2]


def test_a_shop_is_named_by_its_shop_and_place():
    data = _data()
    assert data.terminals[1] == ("CenterMass", "Area 18", "ArcCorp", "Stanton")
    assert data.terminals[2] == ("Casaba Outlet", "Port Tressler", "MicroTech", "Stanton")
    # A moon wins over its planet as the body.
    assert data.terminals[3] == ("Conscientious Objects", "Levski", "Delamar", "Nyx")


def test_search_finds_items_any_case_and_lists_cheapest_first():
    matches, total = _data().search("p4-ar")
    assert total == 2
    assert [m.name for m in matches] == ["P4-AR \"Warhawk\" Rifle", "P4-AR Magazine (40 Cap)"]
    rifle = matches[0]
    assert [(loc.place, loc.price) for loc in rifle.locations] == [
        ("Levski", 4600),
        ("Area 18", 4757),
    ]
    assert rifle.locations[0].reported == 1_790_000_000


def test_search_is_capped_but_counts_every_match():
    matches, total = _data().search("p4", limit=1)
    assert len(matches) == 1 and total == 2


def test_an_empty_search_finds_nothing():
    assert _data().search("  ") == ([], 0)


def _opener(calls, *, fail=False):
    def open_url(url):
        calls.append(url)
        if fail:
            raise OSError("no network")
        rows = TERMINALS if url == TERMINALS_URL else PRICES
        return json.dumps({"status": "ok", "data": rows}).encode()
    return open_url


def test_a_fetch_is_saved_and_a_fresh_cache_is_used_without_asking(tmp_path):
    cache = tmp_path / "uex_shops.json"
    calls = []
    data, error = load_shop_data(cache, _opener(calls), now=NOW)
    assert error == "" and calls == [TERMINALS_URL, PRICES_URL]
    assert read_cache(cache).prices == data.prices
    calls.clear()
    again, error = load_shop_data(cache, _opener(calls), now=NOW + MAX_AGE_S - 1)
    assert calls == [] and error == ""
    assert again.search("magazine")[0][0].locations == data.search("magazine")[0][0].locations


def test_an_old_cache_is_fetched_again(tmp_path):
    cache = tmp_path / "uex_shops.json"
    load_shop_data(cache, _opener([]), now=NOW)
    calls = []
    data, _ = load_shop_data(cache, _opener(calls), now=NOW + MAX_AGE_S + 1)
    assert calls and data.fetched_at == NOW + MAX_AGE_S + 1


def test_force_asks_even_with_a_fresh_cache(tmp_path):
    cache = tmp_path / "uex_shops.json"
    load_shop_data(cache, _opener([]), now=NOW)
    calls = []
    load_shop_data(cache, _opener(calls), force=True, now=NOW + 1)
    assert calls


def test_offline_falls_back_to_the_old_cache(tmp_path):
    cache = tmp_path / "uex_shops.json"
    load_shop_data(cache, _opener([]), now=NOW)
    data, error = load_shop_data(cache, _opener([], fail=True), now=NOW + 2 * MAX_AGE_S)
    assert data is not None and data.fetched_at == NOW
    assert "no network" in error


def test_offline_with_no_cache_gives_nothing(tmp_path):
    data, error = load_shop_data(tmp_path / "none.json", _opener([], fail=True), now=NOW)
    assert data is None and error


@pytest.mark.parametrize("answer", [
    {"status": "requests_limit_reached", "data": None},
    {"status": "ok", "data": {"not": "a list"}},
    ["not", "a", "dict"],
])
def test_an_answer_that_is_not_ok_keeps_the_cache(tmp_path, answer):
    cache = tmp_path / "uex_shops.json"
    load_shop_data(cache, _opener([]), now=NOW)
    data, error = load_shop_data(cache, lambda url: json.dumps(answer).encode(),
                                 force=True, now=NOW + 1)
    assert data.fetched_at == NOW and error


def test_an_answer_with_no_prices_keeps_the_cache(tmp_path):
    cache = tmp_path / "uex_shops.json"
    load_shop_data(cache, _opener([]), now=NOW)
    empty = json.dumps({"status": "ok", "data": []}).encode()
    data, error = load_shop_data(cache, lambda url: empty, force=True, now=NOW + 1)
    assert data.fetched_at == NOW and error
    assert read_cache(cache).fetched_at == NOW


def test_a_broken_or_old_format_cache_reads_as_none(tmp_path):
    cache = tmp_path / "uex_shops.json"
    cache.write_text("{not json", encoding="utf-8")
    assert read_cache(cache) is None
    cache.write_text(json.dumps({"version": 0}), encoding="utf-8")
    assert read_cache(cache) is None


def test_the_opener_sends_the_app_name_and_unpacks_gzip(monkeypatch):
    seen = {}

    class Response:
        headers = {"Content-Encoding": "gzip"}

        def read(self):
            return gzip.compress(b'{"status": "ok", "data": []}')

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(request, timeout):
        seen["agent"] = request.get_header("User-agent")
        seen["timeout"] = timeout
        return Response()

    monkeypatch.setattr(uex_shops, "urlopen", fake_urlopen)
    body = default_opener("SmartCitizen/3.1.0")(PRICES_URL)
    assert json.loads(body) == {"status": "ok", "data": []}
    assert seen == {"agent": "SmartCitizen/3.1.0", "timeout": uex_shops.REQUEST_TIMEOUT_S}
