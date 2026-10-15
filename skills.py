"""Required skills for a fit, plus alpha clone limits.

Skill requirements come from ESI dogma attributes on each type (and on each
skill, for prerequisites). Alpha clone caps come from the game's clone grade
data, published at Hoboleaks. Everything is cached in the database.
"""
import json
import time
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache

import requests

from esi import ESI, PARAMS, session
from models import KV, SkillInfo, TypeReqs, db

# (requiredSkillN, requiredSkillNLevel) dogma attribute IDs
REQ_ATTRS = ((182, 277), (183, 278), (184, 279), (1285, 1286), (1289, 1287), (1290, 1288))
CLONE_URL = "https://sde.hoboleaks.space/tq/clonestates.json"
ALPHA_TTL = 24 * 3600

# the skills that change CPU, power grid or calibration, in the order editors see them
FITTING_SKILLS = [
    (3426, "CPU Management"),
    (3413, "Power Grid Management"),
    (3318, "Weapon Upgrades"),
    (11207, "Advanced Weapon Upgrades"),
    (3425, "Shield Upgrades"),
    (3424, "Energy Grid Upgrades"),
    (3432, "Electronics Upgrades"),
]

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


# training time: skill points per level (times the skill's rank) and EVE's attribute IDs
LEVEL_SP = (0, 250, 1415, 8000, 45255, 256000)
ATTR_IDS = {164: "charisma", 165: "intelligence", 166: "memory", 167: "perception", 168: "willpower"}
AVERAGE_SP_MIN = 30  # attributes of about 20 / 20 with no implants, used when nobody is logged in


def train_infos(skill_ids):
    """{skill_id: (rank, primary attribute, secondary attribute)}, cached in the database."""
    ids = {int(s) for s in skill_ids if s}
    row = db.session.get(KV, "skill_train")
    known = {int(k): tuple(v) for k, v in json.loads(row.value).items()} if row else {}
    missing = ids - known.keys()
    if missing:
        added = {}
        for sid, d in _fetch_many(_get_type, missing).items():
            attrs = {a["attribute_id"]: a["value"] for a in d.get("dogma_attributes") or []}
            if 275 in attrs:
                added[sid] = (int(attrs[275]), ATTR_IDS.get(int(attrs.get(180, 0)), ""), ATTR_IDS.get(int(attrs.get(181, 0)), ""))
        if added:
            known.update(added)
            db.session.merge(KV(key="skill_train", value=json.dumps({str(k): list(v) for k, v in known.items()})))
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
    return {s: known[s] for s in ids if s in known}


def training_minutes(targets, tinfo, have=None, attrs=None, alpha=False):
    """Minutes to train every skill in targets {skill_id: level} from where the pilot is now.
    have: {skill_id: (trained, active, sp)}; attrs: pilot attributes. Returns None if data is missing."""
    total = 0.0
    for sid, lvl in targets.items():
        if sid not in tinfo:
            return None
        rank, prim, sec = tinfo[sid]
        current = have.get(sid, (0, 0, 0)) if have else (0, 0, 0)
        sp_needed = LEVEL_SP[lvl] * rank - max(current[2], LEVEL_SP[current[0]] * rank)
        if sp_needed <= 0:
            continue
        rate = (attrs.get(prim, 0) + attrs.get(sec, 0) / 2) if attrs else AVERAGE_SP_MIN
        rate = rate or AVERAGE_SP_MIN
        total += sp_needed / (rate / 2 if alpha else rate)
    return total


def nice_time(minutes):
    """'3d 4h', '5h 20m', '12m'."""
    if minutes is None:
        return ""
    m = int(round(minutes))
    d, rem = divmod(m, 1440)
    h, mins = divmod(rem, 60)
    if d:
        return f"{d}d {h}h" if h else f"{d}d"
    if h:
        return f"{h}h {mins}m" if mins else f"{h}h"
    return f"{max(mins, 1)}m"


def _plan_lines(need, infos, start=None):
    """Skill plan text: one line per level, prerequisites first.
    start: levels already trained, which are left out of the plan."""
    done, lines = dict(start or {}), []

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


def fit_skills(layouts, fitting=None, have=None, attrs=None):
    """Build the Required skills view for each fit.
    layouts: {fit_id: layout}; fitting: {fit_id: {skill_id: level}} fitting skills set by editors;
    have: the logged-in pilot's skills {skill_id: (trained, active)}, to check whether they can fly each fit."""
    fitting = fitting or {}
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

    infos = skill_infos(set(direct_all) | {sid for lv in fitting.values() for sid in lv})
    caps = alpha_caps()
    tinfo = train_infos(set(infos))
    alpha = bool(have) and any(v[1] < v[0] for v in have.values())

    views = {}
    for fid, direct in per_fit_direct.items():
        need = _expand(direct, infos)
        groups = {}
        omega = False
        for sid, lvl in need.items():
            info = infos.get(sid, {"name": f"Skill {sid}", "group": "Other"})
            cap = caps.get(sid, 0) if caps is not None else None
            is_omega = cap is not None and lvl > cap
            omega = omega or is_omega
            groups.setdefault(info["group"], []).append(
                {"id": sid, "name": info["name"], "level": lvl, "cap": cap, "omega": is_omega})
        views[fid] = {
            "groups": [{"name": g, "skills": sorted(s, key=lambda x: x["name"])} for g, s in sorted(groups.items())],
            "count": len(need),
            "omega": omega,
            "caps_known": caps is not None,
            "complete": bool(need) or not per_fit_types[fid],
            "plan": "\n".join(_plan_lines(need, infos)),
        }
        # fitting skills the editor added: shown separately, but part of the plan and the alpha check
        chosen = {sid: lvl for sid, lvl in fitting.get(fid, {}).items() if lvl > 0}
        if chosen:
            full = _expand({**direct, **{s: max(direct.get(s, 0), l) for s, l in chosen.items()}}, infos)
            fit_rows = []
            for sid, _ in FITTING_SKILLS:
                if sid not in chosen:
                    continue
                cap = caps.get(sid, 0) if caps is not None else None
                lvl = full[sid]
                fit_rows.append({"id": sid, "name": infos.get(sid, {}).get("name", dict(FITTING_SKILLS)[sid]),
                                 "level": lvl, "cap": cap, "omega": cap is not None and lvl > cap})
            extra = {s: l for s, l in full.items() if l > need.get(s, 0)}
            full_omega = any(caps is not None and l > caps.get(s, 0) for s, l in full.items())
            views[fid].update({
                "fitting": fit_rows,
                "fitting_extra": len(extra),
                "omega": full_omega,
                "plan": "\n".join(_plan_lines(full, infos)),
            })
        else:
            views[fid]["fitting"] = []
            full = need
        views[fid]["train_all"] = nice_time(training_minutes(full, tinfo))
        if have is not None:
            _check_pilot(views[fid], full, have, infos)
            short = {s: l for s, l in full.items() if have.get(s, (0, 0, 0))[0] < l}
            if short:
                views[fid]["me"]["train"] = nice_time(training_minutes(short, tinfo, have, attrs, alpha))
                views[fid]["me"]["alpha"] = alpha
                views[fid]["me"]["own_attrs"] = attrs is not None
    return views


def _check_pilot(view, full, have, infos):
    """Mark each skill row with the pilot's level, and sum up whether they can fly the fit."""
    rows = [sk for g in view["groups"] for sk in g["skills"]] + view.get("fitting", [])
    for sk in rows:
        trained, active = have.get(sk["id"], (0, 0, 0))[:2]
        sk["have"], sk["active"] = trained, active
        need = sk["level"]
        sk["state"] = "ok" if active >= need else "clone" if trained >= need else "short"
    states = {}
    for sid, lvl in full.items():
        trained, active = have.get(sid, (0, 0, 0))[:2]
        st = "ok" if active >= lvl else "clone" if trained >= lvl else "short"
        states[sid] = st
    short = {sid: lvl for sid, lvl in full.items() if states[sid] == "short"}
    trained = {sid: v[0] for sid, v in have.items()}
    view["me"] = {
        "ready": not short and "clone" not in states.values(),
        "short": len(short),
        "clone": sum(1 for v in states.values() if v == "clone"),
        "plan": "\n".join(_plan_lines(short, infos, start=trained)),
    }


def ship_classes(type_ids):
    """{type_id: ship class name, e.g. 'Logistics Frigate'}, cached in the database."""
    ids = {int(t) for t in type_ids if t}
    row = db.session.get(KV, "ship_classes")
    known = {int(k): v for k, v in json.loads(row.value).items()} if row else {}
    missing = ids - known.keys()
    if missing:
        types = _fetch_many(_get_type, missing)
        groups = _fetch_many(_group_name, {d["group_id"] for d in types.values() if "group_id" in d})
        added = {tid: groups[d["group_id"]] for tid, d in types.items() if d.get("group_id") in groups}
        if added:
            known.update(added)
            db.session.merge(KV(key="ship_classes", value=json.dumps({str(k): v for k, v in known.items()})))
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
    return {t: known[t] for t in ids if t in known}
