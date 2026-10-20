"""EFT fit parsing and slot layout.

EFT export order (EVE client and Pyfa): low, mid, high, rigs, subsystems,
then bay sections (drones, fighters, cargo) whose lines end in " xN".
Implants and boosters may follow as plain lines.
"""
import re
import xml.etree.ElementTree as ET

HEADER_RE = re.compile(r"^\[([^,\]]+),\s*(.*)\]$")
EMPTY_RE = re.compile(r"^\[Empty .* slot\]$", re.I)
TAG_LINE_RE = re.compile(r"^(\([^()]{1,40}\)|\[[^\[\],]{1,40}\])$")  # a lone "(Tackle)" or "[Tackle]" line
QTY_RE = re.compile(r"^(.*?)\s+x(\d+)$")
SUBSYSTEM_RE = re.compile(r"^(Legion|Loki|Proteus|Tengu) (Core|Defensive|Offensive|Propulsion) - ")

CAT_SHIP = 6
CAT_DRONE = 18
CAT_IMPLANT = 20
CAT_SUBSYSTEM = 32
CAT_FIGHTER = 87

SLOT_SEQUENCE = ["low", "mid", "high", "rig"]
DISPLAY_ORDER = ["high", "mid", "low", "rig", "subsystem", "drones", "fighters", "cargo", "implants"]
LABELS = {
    "high": "High", "mid": "Mid", "low": "Low", "rig": "Rigs",
    "subsystem": "Subsystems", "drones": "Drones", "fighters": "Fighters",
    "cargo": "Cargo", "implants": "Implants",
}
XML_SLOT = {"high": "hi slot", "mid": "med slot", "low": "low slot", "rig": "rig slot", "subsystem": "subsystem slot"}


class EFTError(ValueError):
    pass


def split_fits(text):
    """Split pasted text containing one or more EFT fits into blocks."""
    blocks, cur = [], []
    for line in text.replace("\r\n", "\n").split("\n"):
        s = line.strip()
        if HEADER_RE.match(s) and not EMPTY_RE.match(s):
            if cur:
                blocks.append("\n".join(cur).strip())
            cur = [s]
        elif cur:
            cur.append(line.rstrip())
    if cur:
        blocks.append("\n".join(cur).strip())
    return blocks


def _parse_line(s):
    if EMPTY_RE.match(s):
        return {"empty": True, "label": s.strip("[]"), "name": None, "charge": None, "qty": 1, "has_qty": False, "offline": False}
    offline = s.upper().endswith("/OFFLINE")
    if offline:
        s = s[: -len("/OFFLINE")].rstrip()
    qty, has_qty = 1, False
    m = QTY_RE.match(s)
    if m:
        s, qty, has_qty = m.group(1).strip(), int(m.group(2)), True
    name, charge = s, None
    if "," in s:
        name, charge = (p.strip() for p in s.split(",", 1))
    return {"empty": False, "label": name, "name": name, "charge": charge or None, "qty": qty, "has_qty": has_qty, "offline": offline}


def parse_fit(text):
    lines = [l.rstrip() for l in text.strip().split("\n")]
    if not lines:
        raise EFTError("Empty fit")
    m = HEADER_RE.match(lines[0].strip())
    if not m:
        raise EFTError(f"First line should look like [Ship, Fit name], got: {lines[0][:60]}")
    ship, name = m.group(1).strip(), (m.group(2).strip() or m.group(1).strip())

    raw_sections, cur = [], []
    for line in lines[1:]:
        s = line.strip()
        if not s:
            if cur:
                raw_sections.append(cur)
                cur = []
            continue
        if TAG_LINE_RE.match(s) and not EMPTY_RE.match(s):
            continue  # someone typed a role tag on its own line; it isn't a module
        cur.append(_parse_line(s))
    if cur:
        raw_sections.append(cur)

    sections = []
    for items in raw_sections:
        real = [i for i in items if not i["empty"]]
        is_bay = bool(real) and all(i["has_qty"] for i in real)
        sections.append({"kind": "bay" if is_bay else "modules", "items": items})
    return {"ship": ship, "name": name, "sections": sections}


def all_names(fit):
    names = {fit["ship"]}
    for sec in fit["sections"]:
        for it in sec["items"]:
            if it["name"]:
                names.add(it["name"])
            if it["charge"]:
                names.add(it["charge"])
    return names


def build_layout(fit, info):
    """Assign parsed items to slot groups. `info` maps lower-case name -> TypeInfo."""

    def lookup(n):
        return info.get(n.lower()) if n else None

    def cat(it):
        t = lookup(it["name"])
        return t.category_id if t else None

    groups = {k: [] for k in DISPLAY_ORDER}
    unknown = set()
    module_idx = 0
    for sec in fit["sections"]:
        if sec["kind"] == "modules":
            if module_idx < len(SLOT_SEQUENCE):
                kind = SLOT_SEQUENCE[module_idx]
            else:
                real = [i for i in sec["items"] if not i["empty"]]
                is_sub = real and all(cat(i) == CAT_SUBSYSTEM or SUBSYSTEM_RE.match(i["name"]) for i in real)
                kind = "subsystem" if (is_sub and not groups["subsystem"]) else "implants"
            module_idx += 1
            targets = [(kind, it) for it in sec["items"]]
        else:
            targets = []
            for it in sec["items"]:
                c = cat(it)
                targets.append(("drones" if c == CAT_DRONE else "fighters" if c == CAT_FIGHTER else "cargo", it))

        for kind, it in targets:
            item = dict(it)
            t, ct = lookup(it["name"]), lookup(it["charge"])
            item["type_id"] = t.type_id if t else None
            item["charge_id"] = ct.type_id if ct else None
            if it["name"] and not t:
                unknown.add(it["name"])
            if it["charge"] and not ct:
                unknown.add(it["charge"])
            groups[kind].append(item)

    ship = lookup(fit["ship"])
    if not ship:
        unknown.add(fit["ship"])
    return {
        "ship_id": ship.type_id if ship else None,
        "groups": groups,
        "unknown": sorted(unknown),
    }


def doctrine_xml(fits_with_layouts, description=""):
    """EVE fittings XML (Fitting window > Import > from file) for a whole doctrine."""
    root = ET.Element("fittings")
    for fit, layout in fits_with_layouts:
        f = ET.SubElement(root, "fitting", name=fit.name[:50])
        ET.SubElement(f, "description", value=(fit.notes or description or "")[:500])
        ET.SubElement(f, "shipType", value=fit.ship)
        for kind, prefix in XML_SLOT.items():
            for i, it in enumerate(layout["groups"][kind]):
                if not it["empty"]:
                    ET.SubElement(f, "hardware", slot=f"{prefix} {i}", type=it["name"])
        for kind, slot in (("drones", "drone bay"), ("fighters", "fighter bay"), ("cargo", "cargo")):
            for it in layout["groups"][kind]:
                ET.SubElement(f, "hardware", qty=str(it["qty"]), slot=slot, type=it["name"])
    ET.indent(root)
    return '<?xml version="1.0" ?>\n' + ET.tostring(root, encoding="unicode")
