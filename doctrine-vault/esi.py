"""Resolve item names to type IDs using public ESI endpoints (no login needed)."""
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache

import requests

from models import TypeInfo, db

ESI = "https://esi.evetech.net/latest"
PARAMS = {"datasource": "tranquility"}
session = requests.Session()
session.headers["User-Agent"] = "DoctrineVault/1.0 (corp doctrine library)"


def _chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


@lru_cache(maxsize=4096)
def _type_group(type_id):
    r = session.get(f"{ESI}/universe/types/{type_id}/", params=PARAMS, timeout=15)
    r.raise_for_status()
    return r.json()["group_id"]


@lru_cache(maxsize=2048)
def _group_category(group_id):
    r = session.get(f"{ESI}/universe/groups/{group_id}/", params=PARAMS, timeout=15)
    r.raise_for_status()
    return r.json()["category_id"]


def fetch_types(names):
    """Ask ESI for the given names. Returns a list of unsaved TypeInfo rows."""
    ids = {}
    for chunk in _chunks(sorted(names), 500):
        r = session.post(f"{ESI}/universe/ids/", params={**PARAMS, "language": "en"}, json=chunk, timeout=20)
        r.raise_for_status()
        for it in r.json().get("inventory_types", []):
            ids[it["id"]] = it["name"]
    if not ids:
        return []
    with ThreadPoolExecutor(max_workers=8) as ex:
        type_groups = dict(zip(ids, ex.map(_type_group, ids)))
        gids = list(set(type_groups.values()))
        group_cats = dict(zip(gids, ex.map(_group_category, gids)))
    return [
        TypeInfo(name_lower=name.lower(), name=name, type_id=tid, category_id=group_cats.get(type_groups[tid]))
        for tid, name in ids.items()
    ]


def resolve(names):
    """Return {lower name: TypeInfo} for every name we can resolve (DB cache first, then ESI)."""
    lowers = {n.strip().lower(): n.strip() for n in names if n and n.strip()}
    if not lowers:
        return {}
    found = {t.name_lower: t for t in TypeInfo.query.filter(TypeInfo.name_lower.in_(list(lowers))).all()}
    missing = [orig for low, orig in lowers.items() if low not in found]
    if missing:
        try:
            new = fetch_types(missing)
        except requests.RequestException:
            new = []  # ESI down: show placeholders, try again next view
        for t in new:
            found[t.name_lower] = db.session.merge(t)
        if new:
            db.session.commit()
    return found


def character_id(name):
    """EVE character ID for an exact character name, or None."""
    name = (name or "").strip()
    if not name:
        return None
    try:
        r = session.post(f"{ESI}/universe/ids/", params={**PARAMS, "language": "en"}, json=[name], timeout=15)
        r.raise_for_status()
        for c in r.json().get("characters", []):
            if c["name"].lower() == name.lower():
                return c["id"]
    except requests.RequestException:
        pass
    return None


def character(name):
    """{"id", "name"} for an exact character name (name with EVE's own capitals), or None."""
    name = (name or "").strip()
    if not name:
        return None
    try:
        r = session.post(f"{ESI}/universe/ids/", params={**PARAMS, "language": "en"}, json=[name], timeout=15)
        r.raise_for_status()
        for c in r.json().get("characters", []):
            if c["name"].lower() == name.lower():
                return {"id": c["id"], "name": c["name"]}
    except requests.RequestException:
        pass
    return None


def groups(names):
    """{lower-case name: id} for alliance and corporation names (exact names)."""
    names = [n for n in names if n]
    if not names:
        return {}
    try:
        r = session.post(f"{ESI}/universe/ids/", params={**PARAMS, "language": "en"}, json=names, timeout=15)
        r.raise_for_status()
        data = r.json()
    except requests.RequestException:
        return {}
    return {g["name"].lower(): g["id"] for key in ("alliances", "corporations") for g in data.get(key, [])}
