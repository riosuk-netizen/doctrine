"""Fitting check: does a fit actually fit (CPU, power grid, calibration), and with which skills?

A cut-down version of EVE's dogma rules that only works out the fitting numbers.
It reads CCP's own effect definitions (skills, hull bonuses, modules, rigs) so new
ships and rebalances are picked up without code changes.

Data comes in through three lookup functions so the same maths runs on the live
site (EVE Ref, cached in the database) and in tests (a local copy of the game data):
    get_types(ids)   -> {type_id: {"group_id", "category_id", "attrs": {attr_id: value}, "effects": [effect_id]}}
    get_effects(ids) -> {effect_id: {"category": int, "modifiers": [{"func", "domain", "modified", "modifying", "op", "skill", "group"}]}}
    get_attrs(ids)   -> {attr_id: {"default": float, "stackable": bool}}
"""
import math

# dogma attribute ids
CPU_OUTPUT, POWER_OUTPUT, CALIBRATION = 48, 11, 1132
CPU, POWER, RIG_COST = 50, 30, 1153
SKILL_LEVEL, SKILL_RANK = 280, 275
REQ_SKILL_ATTRS = (182, 183, 184, 1285, 1289, 1290)

# every skill that changes CPU, grid or calibration (found by scanning the game data)
FITTING_SKILLS = {
    3426: "CPU Management",
    3413: "Power Grid Management",
    3318: "Weapon Upgrades",
    11207: "Advanced Weapon Upgrades",
    3425: "Shield Upgrades",
    3424: "Energy Grid Upgrades",
    3432: "Electronics Upgrades",
}

# effect categories that apply while a ship sits fitted and online
PASSIVE, ONLINE = 0, 4
# categories exempt from stacking penalties: ship, charge, skill, implant, subsystem
PENALTY_EXEMPT = {6, 8, 16, 20, 32}
OP_ORDER = (-1, 0, 1, 2, 3, 4, 5, 6, 7)
FIT_GROUPS = ("high", "mid", "low", "rig", "subsystem")


class Item:
    __slots__ = ("uid", "type_id", "kind", "location", "attrs", "effects", "group_id", "category_id", "online")

    def __init__(self, uid, type_id, kind, location, data, online=True):
        self.uid, self.type_id, self.kind, self.location, self.online = uid, type_id, kind, location, online
        self.attrs = dict(data.get("attrs", {}))
        self.effects = list(data.get("effects", []))
        self.group_id = data.get("group_id")
        self.category_id = data.get("category_id")

    def requires(self, skill_id):
        return any(int(self.attrs.get(a, 0) or 0) == skill_id for a in REQ_SKILL_ATTRS)


class FitModel:
    """Builds the modifier graph once; then levels can be changed and totals re-read cheaply."""

    def __init__(self, ship, modules, skill_ids, get_types, get_effects, get_attrs):
        type_ids = {ship} | {m["type_id"] for m in modules} | set(skill_ids)
        types = get_types(type_ids)
        if ship not in types:
            raise LookupError("ship data unavailable")
        self.items = []
        self.ship = Item(0, ship, "ship", None, types[ship])
        self.items.append(self.ship)
        self.char = Item(-1, 0, "char", None, {})
        uid = 1
        self.fitted = []
        for m in modules:
            if m["type_id"] not in types:
                raise LookupError(f"type {m['type_id']} unavailable")
            it = Item(uid, m["type_id"], m["kind"], "ship", types[m["type_id"]], online=m.get("online", True))
            self.items.append(it)
            self.fitted.append(it)
            uid += 1
        self.skills = {}
        for sid in skill_ids:
            if sid in types:
                it = Item(uid, sid, "skill", "char", types[sid])
                it.attrs[SKILL_LEVEL] = 0
                self.items.append(it)
                self.skills[sid] = it
                uid += 1

        effect_ids = set()
        for it in self.items:
            effect_ids.update(it.effects)
        self.effects = get_effects(effect_ids)
        missing = effect_ids - set(self.effects)
        if missing:
            raise LookupError(f"{len(missing)} effects unavailable")

        self.mods = {}  # (target uid, attr) -> [(op, source item, modifying attr)]
        attr_ids = {CPU_OUTPUT, POWER_OUTPUT, CALIBRATION, CPU, POWER, RIG_COST, SKILL_LEVEL}
        for src in self.items:
            for eid in src.effects:
                eff = self.effects[eid]
                cat = eff.get("category")
                if src.kind == "skill" or src.kind == "ship":
                    if cat != PASSIVE:
                        continue
                elif cat not in (PASSIVE, ONLINE) or (cat == ONLINE and not src.online):
                    continue
                seen = set()
                for m in eff.get("modifiers", []):
                    if m.get("modified") == SKILL_LEVEL:
                        continue  # we set skill levels directly
                    key = (m.get("func"), m.get("domain"), m.get("modified"), m.get("modifying"), m.get("op"),
                           m.get("skill"), m.get("group"))
                    if key in seen:
                        continue
                    seen.add(key)
                    for tgt in self._targets(src, m):
                        self.mods.setdefault((tgt.uid, m["modified"]), []).append((m["op"], src, m["modifying"]))
                        attr_ids.update((m["modified"], m["modifying"]))
        self.attr_meta = get_attrs(attr_ids)
        self._memo = {}

    def _domain(self, src, domain):
        if domain == "itemID":
            return src
        if domain == "shipID":
            return self.ship
        if domain == "charID":
            return self.char
        return None

    def _located(self, where):
        if where is self.ship:
            return self.fitted
        if where is self.char:
            return list(self.skills.values())
        return []

    def _targets(self, src, m):
        func, dom = m.get("func"), self._domain(src, m.get("domain"))
        if dom is None or m.get("modified") is None or m.get("modifying") is None:
            return []
        if func == "ItemModifier":
            return [dom]
        if func == "LocationModifier":
            return self._located(dom)
        if func == "LocationGroupModifier":
            g = m.get("group")
            return [t for t in self._located(dom) if g is not None and t.group_id == g]
        if func == "LocationRequiredSkillModifier":
            sk = m.get("skill")
            if sk is None:
                return []  # malformed duplicate without a skill: would wrongly hit everything
            if sk == -1:
                sk = src.type_id
            return [t for t in self._located(dom) if t.requires(sk)]
        return []  # owner (drones / charges), target, etc. don't affect fitting

    # ---- attribute maths ----
    def _default(self, attr):
        return float(self.attr_meta.get(attr, {}).get("default", 0.0) or 0.0)

    def _stackable(self, attr):
        return self.attr_meta.get(attr, {}).get("stackable", True)

    def value(self, item, attr, _stack=()):
        key = (item.uid, attr)
        if key in self._memo:
            return self._memo[key]
        if key in _stack:  # circular reference: fall back to the base value
            return float(item.attrs.get(attr, self._default(attr)))
        val = float(item.attrs.get(attr, self._default(attr)))
        mods = self.mods.get(key, [])
        if mods:
            stack = _stack + (key,)
            by_op = {}
            for op, src, mattr in mods:
                by_op.setdefault(op, []).append((self.value(src, mattr, stack), src))
            penalise = not self._stackable(attr)
            for op in OP_ORDER:
                vals = by_op.get(op)
                if not vals:
                    continue
                if op == -1:
                    val = vals[-1][0]
                elif op == 7:
                    val = vals[-1][0]
                elif op == 2:
                    val += sum(v for v, _ in vals)
                elif op == 3:
                    val -= sum(v for v, _ in vals)
                else:
                    factors = []
                    for v, src in vals:
                        if op in (0, 4):
                            f = v
                        elif op in (1, 5):
                            f = 1.0 / v if v else 1.0
                        else:  # 6: post percent
                            f = 1.0 + v / 100.0
                        factors.append((f, src))
                    val *= self._combine(factors, penalise)
        self._memo[key] = val
        return val

    @staticmethod
    def _combine(factors, penalise):
        if not penalise:
            return math.prod(f for f, _ in factors)
        total = 1.0
        free = [f for f, s in factors if s.category_id in PENALTY_EXEMPT or s.kind in ("skill", "ship")]
        total *= math.prod(free)
        rest = [f for f, s in factors if not (s.category_id in PENALTY_EXEMPT or s.kind in ("skill", "ship"))]
        for group in ([f for f in rest if f >= 1], [f for f in rest if f < 1]):
            group.sort(key=lambda f: abs(f - 1), reverse=True)
            for i, f in enumerate(group):
                total *= 1 + (f - 1) * math.exp(-((i / 2.67) ** 2))
        return total

    def totals(self, levels):
        for sid, it in self.skills.items():
            it.attrs[SKILL_LEVEL] = levels.get(sid, 0)
        self._memo = {}
        online = [m for m in self.fitted if m.online and m.kind in ("high", "mid", "low", "subsystem")]
        rigs = [m for m in self.fitted if m.kind == "rig"]
        return {
            "cpu": (sum(self.value(m, CPU) for m in online), self.value(self.ship, CPU_OUTPUT)),
            "power": (sum(self.value(m, POWER) for m in online), self.value(self.ship, POWER_OUTPUT)),
            "calibration": (sum(self.value(r, RIG_COST) for r in rigs), self.value(self.ship, CALIBRATION)),
        }


def fits(t, eps=1e-6):
    return all(used <= total + eps for used, total in t.values())


def shortfall(t):
    return sum(max(0.0, used - total) / max(total, 1.0) for used, total in t.values())


def sp_for_level(rank, level):
    return 0 if level <= 0 else 250 * rank * (32 ** ((level - 1) / 2))


def layout_modules(layout):
    mods = []
    for kind in FIT_GROUPS:
        for it in layout["groups"].get(kind, []):
            if it.get("empty") or not it.get("type_id"):
                continue
            mods.append({"type_id": it["type_id"], "kind": kind, "online": not it.get("offline")})
    return mods


def check(layout, base_levels, ship_skill_ids, get_types, get_effects, get_attrs, caps=None, prereqs_ok=None):
    """Work out whether a fit fits, and the cheapest fitting skills that make it fit.

    base_levels: {skill_id: level} the fit already needs (to use the modules).
    ship_skill_ids: skills the hull needs (their level can carry fitting bonuses).
    caps: {skill_id: max alpha level}, or None if unknown.
    prereqs_ok(skill_id): True if that skill's prerequisites are alpha-trainable.
    Returns a dict for the page, or None if the data isn't available.
    """
    ship = layout.get("ship_id")
    mods = layout_modules(layout)
    if not ship:
        return None
    candidates = set(FITTING_SKILLS) | set(ship_skill_ids)
    skill_ids = set(base_levels) | candidates
    try:
        model = FitModel(ship, mods, skill_ids, get_types, get_effects, get_attrs)
    except (LookupError, KeyError, TypeError, ValueError, ZeroDivisionError):
        return None

    base = {sid: lvl for sid, lvl in base_levels.items()}
    t_min = model.totals(base)

    # only skills that change one of this fit's numbers are worth suggesting
    relevant = []
    for sid in candidates:
        if sid not in model.skills or base.get(sid, 0) >= 5:
            continue
        t5 = model.totals({**base, sid: 5})
        if any(abs(t5[k][0] - t_min[k][0]) > 1e-9 or abs(t5[k][1] - t_min[k][1]) > 1e-9 for k in t5):
            relevant.append(sid)
    all_v = {**base, **{sid: 5 for sid in relevant}}
    t_max = model.totals(all_v)

    def rank(sid):
        return float(model.skills[sid].attrs.get(SKILL_RANK, 1) or 1)

    def search(alpha):
        cur = dict(base)
        allowed = []
        for sid in relevant:
            if alpha:
                if caps is None or (prereqs_ok and not prereqs_ok(sid)):
                    continue
                if caps.get(sid, 0) <= cur.get(sid, 0):
                    continue
            allowed.append(sid)
        t = model.totals(cur)
        for _ in range(60):
            if fits(t):
                break
            short = shortfall(t)
            best = None
            for sid in allowed:
                lvl = cur.get(sid, 0)
                top = min(5, caps.get(sid, 0)) if alpha else 5
                if lvl >= top:
                    continue
                trial = model.totals({**cur, sid: lvl + 1})
                gain = short - shortfall(trial)
                if gain <= 1e-12:
                    continue
                cost = sp_for_level(rank(sid), lvl + 1) - sp_for_level(rank(sid), lvl)
                score = gain / max(cost, 1)
                if best is None or score > best[0]:
                    best = (score, sid)
            if best is None:
                # nothing helps on its own one step at a time: try the biggest single jump
                for sid in allowed:
                    top = min(5, caps.get(sid, 0)) if alpha else 5
                    if cur.get(sid, 0) < top:
                        best = (0, sid)
                        break
                if best is None:
                    return None
            cur[best[1]] = cur.get(best[1], 0) + 1
            t = model.totals(cur)
        if not fits(t):
            return None
        # trim anything the later picks made unnecessary
        for sid in sorted(cur, key=lambda s: -(sp_for_level(rank(s), cur[s]) if s in model.skills else 0)):
            while cur.get(sid, 0) > base.get(sid, 0):
                trial = {**cur, sid: cur[sid] - 1}
                if fits(model.totals(trial)):
                    cur = trial
                else:
                    break
        return cur

    plan, alpha_plan = None, None
    if fits(t_max):
        alpha_plan = search(alpha=True) if caps is not None else None
        plan = alpha_plan or search(alpha=False)
    t_plan = model.totals(plan) if plan else None
    extra = {sid: lvl for sid, lvl in (plan or {}).items() if lvl > base.get(sid, 0)}

    def fmt(t):
        return {k: {"used": round(u, 2), "total": round(tot, 2), "ok": u <= tot + 1e-6} for k, (u, tot) in t.items()}

    return {
        "fits_min": fits(t_min),
        "fits_max": fits(t_max),
        "alpha_fit": alpha_plan is not None,
        "minimum": fmt(t_min),
        "recommended": fmt(t_plan) if t_plan else None,
        "all_v": fmt(t_max),
        "extra": extra,                         # {skill_id: level} fitting skills to add
        "relevant": sorted(relevant),
        "has_rigs": any(m["kind"] == "rig" for m in mods),
    }
