"""Required skills for a fit, plus alpha clone limits.

Skill requirements come from ESI dogma attributes on each type (and on each
skill, for prerequisites). Alpha clone caps come from the game's clone grade
data, published at Hoboleaks. Everything is cached in the database.
"""
import json
import time
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache

import requests

from esi import ESI, PARAMS, session
import fitting
from models import KV, RefCache, SkillInfo, TypeReqs, db, now

# (requiredSkillN, requiredSkillNLevel) dogma attribute IDs
REQ_ATTRS = ((182, 277), (183, 278), (184, 279), (1285, 1286), (1289, 1287), (1290, 1288))
CLONE_URL = "https://sde.hoboleaks.space/tq/clonestates.json"
ALPHA_TTL = 24 * 3600

# slot groups whose items you need skills for (cargo and implants are optional extras)
SKILL_GROUPS = ("high", "mid", "low", "rig", "subsystem", "drones", "fighters")


def _int_keys(d):
    return {int(k): int(v) for k, v in d.items()}


def reqs_from_dogma(attrs):
    vals = {a["attribute_id"]: a["value"] for a in attrs or []}
    out = {}
    for s, l in REQ_ATTRS:
        sid, lvl = int(vals.get(s, 0) or 0), int(vals.get(l, 0) or 0)
        if sid > 0 and lvl > 0:
            out[sid] = max(out.get(sid, 0), lvl)
    return out


def _get_type(type_id):
    r = session.get(f"{ESI}/universe/types/{type_id}/", params=PARAMS, timeout=15)
    r.raise_for_status()
    return r.json()


@lru_cache(maxsize=512)
def _group_name(group_id):
    r = session.get(f"{ESI}/universe/groups/{group_id}/", params=PARAMS, timeout=15)
    r.raise_for_status()
    return r.json()["name"]


def _fetch_many(fn, keys):
    """Run fn over keys in parallel, dropping any that fail."""
    keys = list(keys)
    if not keys:
        return {}

    def safe(k):
        try:
            return k, fn(k)
        except (requests.RequestException, KeyError, ValueError):
            return k, None

    with ThreadPoolExecutor(max_workers=8) as ex:
        return {k: v for k, v in ex.map(safe, keys) if v is not None}


META_GROUP_ATTR = 1692  # metaGroupID dogma attribute


def meta_from_dogma(attrs):
    for a in attrs or []:
        if a.get("attribute_id") == META_GROUP_ATTR:
            return int(a.get("value") or 0)
    return 0


REF_DATA = "https://ref-data.everef.net/types"


def _meta_lookup(type_id):
    """Meta group for one type (0 = plain Tech I). EVE Ref first, CCP's ESI as a fallback.
    Raises if neither source answers, so nothing wrong gets cached."""
    try:
        r = session.get(f"{REF_DATA}/{type_id}", timeout=15)
        r.raise_for_status()
        data = r.json()
        if data.get("meta_group_id") is not None:
            return int(data["meta_group_id"])
        if int(data.get("tech_level") or 1) == 2:
            return 2
        meta = meta_from_dogma([{"attribute_id": int(k), "value": v.get("value") if isinstance(v, dict) else v}
                                for k, v in (data.get("dogma_attributes") or {}).items()])
        if meta:
            return meta
    except (requests.RequestException, ValueError, AttributeError, TypeError):
        pass
    # CCP's ESI on its own: the metaGroupID attribute isn't always there, so also use the
    # tech level (always there) and the market tree (faction hulls sit under a "... Faction ..." group)
    data = _get_type(type_id)  # raises on failure
    attrs = data.get("dogma_attributes") or []
    meta = meta_from_dogma(attrs)
    if meta:
        return meta
    tech = next((int(a["value"]) for a in attrs if a.get("attribute_id") == 422), 1)  # techLevel
    if tech == 2:
        return 2
    if tech == 3:
        return 14
    group_id = data.get("market_group_id")
    for _ in range(5):  # walk up the market tree
        if not group_id:
            break
        group = _market_group(group_id)  # raises on failure, so a half-checked answer isn't cached
        if "faction" in group.get("name", "").lower():
            return 4
        group_id = group.get("parent_group_id")
    return 0


@lru_cache(maxsize=512)
def _market_group(group_id):
    r = session.get(f"{ESI}/markets/groups/{group_id}/", params=PARAMS, timeout=15)
    r.raise_for_status()
    return r.json()


def meta_groups(type_ids):
    """{type_id: meta group} (0 = plain Tech I / none), cached alongside skill requirements."""
    ids = {t for t in type_ids if t}
    if not ids:
        return {}
    rows = {r.type_id: r for r in TypeReqs.query.filter(TypeReqs.type_id.in_(ids)).all()}
    out = {tid: r.meta_group for tid, r in rows.items() if r.meta_group is not None}
    fetched = _fetch_many(_meta_lookup, ids - out.keys())
    for tid, meta in fetched.items():
        row = rows.get(tid)
        if row:
            row.meta_group = meta
        else:
            db.session.add(TypeReqs(type_id=tid, reqs="{}", meta_group=meta, reqs_pending=True))
        out[tid] = meta
    if fetched:
        db.session.commit()
    return out


def type_reqs(type_ids):
    """{type_id: {skill_id: level}} for items, cached."""
    ids = {t for t in type_ids if t}
    have = {r.type_id: _int_keys(json.loads(r.reqs)) for r in TypeReqs.query.filter(TypeReqs.type_id.in_(ids)).all()
            if not r.reqs_pending} if ids else {}
    fetched = _fetch_many(_get_type, ids - have.keys())
    for tid, data in fetched.items():
        reqs = reqs_from_dogma(data.get("dogma_attributes"))
        row = db.session.get(TypeReqs, tid)
        if row:
            row.reqs, row.reqs_pending = json.dumps(reqs), False
        else:
            db.session.add(TypeReqs(type_id=tid, reqs=json.dumps(reqs)))
        have[tid] = reqs
    if fetched:
        db.session.commit()
    return have


def skill_infos(skill_ids):
    """Load skills and every prerequisite down the chain. {skill_id: {name, group, reqs}}."""
    out = {}
    frontier = set(skill_ids)
    while frontier:
        for r in SkillInfo.query.filter(SkillInfo.type_id.in_(frontier)).all():
            out[r.type_id] = {"name": r.name, "group": r.group_name, "reqs": _int_keys(json.loads(r.reqs))}
        missing = frontier - out.keys()
        fetched = _fetch_many(_get_type, missing)
        groups = _fetch_many(_group_name, {d["group_id"] for d in fetched.values() if "group_id" in d})
        for sid, d in fetched.items():
            info = {"name": d.get("name", f"Skill {sid}"), "group": groups.get(d.get("group_id"), "Other"),
                    "reqs": reqs_from_dogma(d.get("dogma_attributes"))}
            db.session.merge(SkillInfo(type_id=sid, name=info["name"], group_name=info["group"], reqs=json.dumps(info["reqs"])))
            out[sid] = info
        if fetched:
            db.session.commit()
        frontier = {p for sid in frontier if sid in out for p in out[sid]["reqs"]} - out.keys()
    return out


_alpha = {"caps": None, "at": 0.0}


def alpha_caps():
    """{skill_id: max level an alpha can train}. None if the data can't be loaded."""
    if _alpha["caps"] is not None and time.time() - _alpha["at"] < ALPHA_TTL:
        return _alpha["caps"]
    caps = None
    try:
        r = session.get(CLONE_URL, timeout=20)
        r.raise_for_status()
        caps = {}
        for grade in r.json().values():
            for sid, lvl in grade.get("skills", {}).items():
                caps[int(sid)] = max(caps.get(int(sid), 0), int(lvl))
        if caps:
            db.session.merge(KV(key="alpha_caps", value=json.dumps(caps)))
            db.session.commit()
        else:
            caps = None
    except (requests.RequestException, ValueError, AttributeError):
        caps = None
    if caps is None:  # fall back to the last good copy
        row = db.session.get(KV, "alpha_caps")
        if row:
            caps = _int_keys(json.loads(row.value))
    if caps is not None:
        _alpha.update(caps=caps, at=time.time())
    return caps


def _expand(direct, infos):
    """Add every prerequisite, keeping the highest level needed for each skill."""
    need = {}
    stack = list(direct.items())
    while stack:
        sid, lvl = stack.pop()
        if need.get(sid, 0) >= lvl:
            continue
        need[sid] = lvl
        for p, pl in infos.get(sid, {}).get("reqs", {}).items():
            stack.append((p, pl))
    return need


def _plan_lines(need, infos):
    """Skill plan text: one line per level, prerequisites first."""
    done, lines = {}, []

    def name(sid):
        return infos.get(sid, {}).get("name", f"Skill {sid}")

    def visit(sid, lvl, path=()):
        if done.get(sid, 0) >= lvl or sid in path:
            return
        for p, pl in sorted(infos.get(sid, {}).get("reqs", {}).items(), key=lambda kv: name(kv[0])):
            visit(p, pl, path + (sid,))
        for level in range(done.get(sid, 0) + 1, lvl + 1):
            lines.append(f"{name(sid)} {level}")
        done[sid] = lvl

    for sid in sorted(need, key=name):
        visit(sid, need[sid])
    return lines


# ---- game data for the fitting check (EVE Ref, cached in the database) ----
REF_MAX_AGE = timedelta(days=30)  # refresh now and then so CCP rebalances come through


def _ref_cached(kind, ids, url, shape):
    """{id: shaped data} for ids, from the cache or EVE Ref. Fetch failures are left out."""
    ids = {int(i) for i in ids if i}
    if not ids:
        return {}
    rows = {r.ref_id: r for r in RefCache.query.filter(RefCache.kind == kind, RefCache.ref_id.in_(ids)).all()}
    out, stale = {}, set()
    cutoff = now() - REF_MAX_AGE
    for rid, r in rows.items():
        out[rid] = json.loads(r.data)
        upd = r.updated_at.replace(tzinfo=cutoff.tzinfo) if r.updated_at and r.updated_at.tzinfo is None else r.updated_at
        if not upd or upd < cutoff:
            stale.add(rid)

    def fetch(i):
        r = session.get(f"{url}/{i}", timeout=20)
        r.raise_for_status()
        return shape(r.json())

    fetched = _fetch_many(fetch, (ids - out.keys()) | stale)
    for rid, data in fetched.items():
        row = rows.get(rid)
        if row:
            row.data, row.updated_at = json.dumps(data), now()
        else:
            db.session.add(RefCache(kind=kind, ref_id=rid, data=json.dumps(data)))
        out[rid] = data
    if fetched:
        try:
            db.session.commit()
        except Exception:  # another worker saved the same row first
            db.session.rollback()
    return {int(k): v for k, v in out.items()}


def _shape_type(d):
    return {"group_id": d.get("group_id"), "category_id": d.get("category_id"),
            "attrs": {str(int(k)): v.get("value") for k, v in (d.get("dogma_attributes") or {}).items()},
            "effects": [int(k) for k in (d.get("dogma_effects") or {})]}


def _shape_effect(d):
    return {"category": d.get("effect_category"), "modifiers": [
        {"func": m.get("func"), "domain": m.get("domain"), "modified": m.get("modified_attribute_id"),
         "modifying": m.get("modifying_attribute_id"), "op": m.get("operator"),
         "skill": m.get("skill_type_id"), "group": m.get("group_id")} for m in (d.get("modifiers") or [])]}


def _shape_attr(d):
    return {"default": d.get("default_value") or 0.0, "stackable": bool(d.get("stackable", True))}


def ref_types(ids):
    out = _ref_cached("type", ids, REF_DATA, _shape_type)
    for d in out.values():  # json turns int keys into strings
        d["attrs"] = {int(k): v for k, v in d["attrs"].items()}
    return out


def ref_effects(ids):
    return _ref_cached("effect", ids, "https://ref-data.everef.net/dogma_effects", _shape_effect)


def ref_attrs(ids):
    return _ref_cached("attr", ids, "https://ref-data.everef.net/dogma_attributes", _shape_attr)


def fit_skills(layouts):
    """Build the Required skills view for each fit. layouts: {fit_id: layout}."""
    per_fit_types = {}
    for fid, L in layouts.items():
        ids = {L["ship_id"]}
        for g in SKILL_GROUPS:
            for it in L["groups"][g]:
                ids.add(it.get("type_id"))
                ids.add(it.get("charge_id"))
        per_fit_types[fid] = {i for i in ids if i}

    reqs = type_reqs(set().union(*per_fit_types.values()) if per_fit_types else set())
    direct_all = {}
    per_fit_direct = {}
    for fid, ids in per_fit_types.items():
        direct = {}
        for tid in ids:
            for sid, lvl in reqs.get(tid, {}).items():
                direct[sid] = max(direct.get(sid, 0), lvl)
        per_fit_direct[fid] = direct
        direct_all.update(direct)

    infos = skill_infos(set(direct_all) | set(fitting.FITTING_SKILLS))
    caps = alpha_caps()

    def prereqs_ok(sid):
        if caps is None:
            return False
        chain = _expand({sid: 1}, infos)
        return all(lvl <= caps.get(p, 0) for p, lvl in chain.items() if p != sid)

    views = {}
    for fid, direct in per_fit_direct.items():
        need = _expand(direct, infos)
        L = layouts[fid]
        fit_check = None
        try:
            fit_check = fitting.check(L, need, reqs.get(L["ship_id"], {}).keys(), ref_types, ref_effects, ref_attrs,
                                      caps=caps, prereqs_ok=prereqs_ok)
        except Exception:  # never let the fitting maths break the page
            fit_check = None
        fitting_ids = set()
        if fit_check and fit_check["extra"]:
            for sid, lvl in fit_check["extra"].items():
                if lvl > direct.get(sid, 0):
                    fitting_ids.add(sid)
                    direct = {**direct, sid: max(direct.get(sid, 0), lvl)}
            need = _expand(direct, infos)
        groups = {}
        omega = False
        for sid, lvl in need.items():
            info = infos.get(sid, {"name": f"Skill {sid}", "group": "Other"})
            cap = caps.get(sid, 0) if caps is not None else None
            is_omega = cap is not None and lvl > cap
            omega = omega or is_omega
            groups.setdefault(info["group"], []).append(
                {"id": sid, "name": info["name"], "level": lvl, "cap": cap, "omega": is_omega,
                 "fitting": sid in fitting_ids})
        views[fid] = {
            "groups": [{"name": g, "skills": sorted(s, key=lambda x: x["name"])} for g, s in sorted(groups.items())],
            "count": len(need),
            "omega": omega,
            "caps_known": caps is not None,
            "complete": bool(need) or not per_fit_types[fid],
            "plan": "\n".join(_plan_lines(need, infos)),
            "fitting": fit_check,
        }
    return views
