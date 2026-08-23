"""
Parses EVE Online EFT-format fit strings into structured data.

EFT format example:

[Merlin, PVP Merlin]
Damage Control II
Small Shield Extender II

1MN Afterburner II
Warp Disruptor II

Light Neutron Blaster II, Null L
Light Neutron Blaster II, Null L

Small Auxiliary Thrusters II


Hobgoblin II x2

Nanite Repair Paste x10

Sections are separated by blank lines and appear in a conventional order:
high slots, mid slots, low slots, rigs/subsystems, drones, cargo.
Since EFT text doesn't explicitly label sections, we infer them by
position (blocks in order) which matches how the EVE client exports fits.
"""
import re

HEADER_RE = re.compile(r"^\[(?P<ship>[^,]+),\s*(?P<name>.+)\]$")
QTY_RE = re.compile(r"^(?P<item>.+?)\s+x(?P<qty>\d+)$")
CHARGE_RE = re.compile(r"^(?P<module>.+?),\s*(?P<charge>.+)$")

# Conventional block order after the header, when the EVE client exports a fit.
SECTION_ORDER = ["low", "mid", "high", "rig", "drone", "cargo"]


class EftParseError(ValueError):
    pass


def parse_eft(raw_text: str) -> dict:
    """
    Returns:
        {
            "ship_name": str,
            "fit_name": str,
            "sections": {
                "low": [ {item, charge, qty}, ... ],
                "mid": [...],
                "high": [...],
                "rig": [...],
                "drone": [...],
                "cargo": [...],
            }
        }
    """
    if not raw_text or not raw_text.strip():
        raise EftParseError("Empty fit text.")

    lines = raw_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    lines = [l.rstrip() for l in lines]

    if not lines or not lines[0].strip().startswith("["):
        raise EftParseError("Fit must start with a [Ship, Fit Name] header line.")

    header_match = HEADER_RE.match(lines[0].strip())
    if not header_match:
        raise EftParseError("Could not parse header line — expected format: [Ship Name, Fit Name]")

    ship_name = header_match.group("ship").strip()
    fit_name = header_match.group("name").strip()

    body = lines[1:]

    # Split into blocks on blank lines, preserving empty blocks (EFT uses them
    # as section separators — e.g. two blank lines in a row means an empty slot section).
    blocks = []
    current = []
    for line in body:
        if line.strip() == "":
            blocks.append(current)
            current = []
        else:
            current.append(line.strip())
    blocks.append(current)

    # Drop fully-empty trailing blocks (trailing whitespace in file)
    while blocks and not blocks[-1]:
        blocks.pop()

    # Blocks are usually [low, mid, high, rig(s), drones, cargo] in that order,
    # but not every fit has every section (e.g. no drones). We assign
    # non-empty blocks to section names in order, skipping ahead intelligently
    # isn't reliable without slot data from ESI, so we assign positionally
    # among the non-empty blocks using the conventional order.
    non_empty_blocks = [b for b in blocks if b]

    sections = {s: [] for s in SECTION_ORDER}
    for idx, block in enumerate(non_empty_blocks):
        section_name = SECTION_ORDER[idx] if idx < len(SECTION_ORDER) else "cargo"
        for line in block:
            sections[section_name].append(_parse_line(line))

    return {
        "ship_name": ship_name,
        "fit_name": fit_name,
        "sections": sections,
    }


def _parse_line(line: str) -> dict:
    qty_match = QTY_RE.match(line)
    if qty_match:
        return {
            "item": qty_match.group("item").strip(),
            "charge": None,
            "qty": int(qty_match.group("qty")),
        }

    charge_match = CHARGE_RE.match(line)
    if charge_match:
        return {
            "item": charge_match.group("module").strip(),
            "charge": charge_match.group("charge").strip(),
            "qty": None,
        }

    return {"item": line.strip(), "charge": None, "qty": None}


def to_eft_string(fit) -> str:
    """Rebuild an EFT text block from a Fit model instance, for export/copy."""
    lines = [f"[{fit.ship_name}, {fit.name}]", ""]

    by_section = {}
    for m in fit.modules:
        by_section.setdefault(m.slot_section, []).append(m)

    for section in SECTION_ORDER:
        mods = by_section.get(section, [])
        if not mods:
            continue
        for m in mods:
            if m.charge_name:
                lines.append(f"{m.item_name}, {m.charge_name}")
            elif m.quantity:
                lines.append(f"{m.item_name} x{m.quantity}")
            else:
                lines.append(m.item_name)
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"
