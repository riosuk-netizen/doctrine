"""Jita prices for fit costs.

Prices come from Fuzzwork's market aggregates for Jita 4-4 (one request for many items),
using the sell side, which is what a pilot pays to buy the fit. If Fuzzwork can't be reached,
ESI's average market price is used instead. Prices are cached in the database for an hour.
"""
import json
import time
from datetime import datetime, timezone

from esi import ESI, PARAMS, session
from models import KV, db

FUZZWORK = "https://market.fuzzwork.co.uk/aggregates/"
JITA_44 = 60003760
TTL = 3600


def _load():
    row = db.session.get(KV, "jita_prices")
    try:
        return {int(k): v for k, v in json.loads(row.value).items()} if row else {}
    except ValueError:
        return {}


def _save(cache):
    db.session.merge(KV(key="jita_prices", value=json.dumps({str(k): v for k, v in cache.items()})))
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()


def _fuzzwork(type_ids):
    out = {}
    ids = sorted(type_ids)
    for i in range(0, len(ids), 200):
        chunk = ids[i:i + 200]
        r = session.get(FUZZWORK, params={"station": JITA_44, "types": ",".join(map(str, chunk))}, timeout=20)
        r.raise_for_status()
        for tid, data in r.json().items():
            sell = data.get("sell") or {}
            # the 5% percentile ignores one silly cheap order; fall back to the lowest sell order
            price = float(sell.get("percentile") or 0) or float(sell.get("min") or 0)
            if price > 0:
                out[int(tid)] = price
    return out


def _esi_average(type_ids):
    r = session.get(f"{ESI}/markets/prices/", params=PARAMS, timeout=20)
    r.raise_for_status()
    want = set(type_ids)
    return {p["type_id"]: float(p.get("average_price") or p.get("adjusted_price") or 0)
            for p in r.json() if p["type_id"] in want and (p.get("average_price") or p.get("adjusted_price"))}


def jita(type_ids):
    """({type_id: ISK each}, source, fetched_at). Missing items simply aren't in the dict."""
    ids = {int(t) for t in type_ids if t}
    cache = _load()
    now = time.time()
    stale = {t for t in ids if t not in cache or now - cache[t][1] > TTL}
    source = "Jita sell"
    if stale:
        got, answered = {}, False
        try:
            got, answered = _fuzzwork(stale), True
        except Exception:
            got = {}
        if not got:
            try:
                got, answered = _esi_average(stale), True
                source = "EVE average"
            except Exception:
                got = {}
        for t in (stale if answered else got):  # if nothing answered, try again next time  # items with no market (or a failed lookup) are remembered too, so we don't ask again every page load
            cache[t] = [got.get(t), now, source]
        if answered:
            _save(cache)
    prices = {t: cache[t][0] for t in ids if t in cache and cache[t][0]}
    stamps = [cache[t][1] for t in ids if t in cache and cache[t][0]]
    sources = {cache[t][2] if len(cache[t]) > 2 else "Jita sell" for t in ids if t in cache}
    at = datetime.fromtimestamp(min(stamps), timezone.utc) if stamps else None
    return prices, (sources.pop() if len(sources) == 1 else "Jita sell" if sources else source), at


# what counts towards a fit's cost: the hull, every fitted module, and drones / fighters / cargo by quantity.
# Ammo loaded in guns isn't counted (EFT doesn't say how much); ammo in the cargo is.
COUNT_GROUPS = ("high", "mid", "low", "rig", "subsystem", "drones", "fighters", "cargo")


def fit_items(layout):
    """[(type_id, quantity)] for one fit layout."""
    items = []
    if layout.get("ship_id"):
        items.append((layout["ship_id"], 1))
    for g in COUNT_GROUPS:
        for it in layout["groups"].get(g, []):
            if it.get("empty") or not it.get("type_id"):
                continue
            items.append((it["type_id"], max(1, it.get("qty") or 1)))
    return items


def fit_costs(layouts):
    """{fit_id: {"total", "hull", "fitting", "missing", "source", "at"}} plus {type_id: price} for the module list."""
    all_ids = {t for L in layouts.values() for t, _ in fit_items(L)}
    prices, source, at = jita(all_ids)
    out = {}
    for fid, L in layouts.items():
        total = hull = 0.0
        missing = 0
        for tid, qty in fit_items(L):
            p = prices.get(tid)
            if p is None:
                missing += 1
                continue
            total += p * qty
            if tid == L.get("ship_id"):
                hull = p
        out[fid] = {"total": total, "hull": hull, "fitting": total - hull, "missing": missing,
                    "source": source, "at": at}
    return out, prices


def isk(value):
    """1234567 -> '1.23m', 950000 -> '950k', 2.4e9 -> '2.40b'."""
    v = float(value or 0)
    for size, unit in ((1e12, "t"), (1e9, "b"), (1e6, "m"), (1e3, "k")):
        if v >= size:
            n = v / size
            return f"{n:.2f}{unit}" if n < 10 else f"{n:.1f}{unit}" if n < 100 else f"{n:.0f}{unit}"
    return f"{v:.0f}"
