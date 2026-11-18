"""The SCO drawer's Order tab: a crafting order and what it needs.

Qt-free and settings-free. The blueprints come from ``crafting_index.json``
(:class:`src.utils.mining_catalog.CraftingIndex`, version 2), written by the
generator from the DataForge crafting blueprints.

Every craftable item has crafting slots ("Frame", "Cabling", ...). Each slot
takes an amount of one material (SCU for ores, a count of pieces for gems
and other items), accepts material from a lowest quality up, and the quality
of that material (0 to 1000) moves one or more of the item's stats along a
curve: a multiplier for most stats (0.9x at 0, 1.0x at 500, 1.1x at 1000)
and whole units added for a power plant's pips. Some blueprints have a pick:
"any 2 of these 3" slots. Ported from the RK site's Crafting Central
(citizen-bot ``web/frontend/src/lib/crafting.ts``), whose model this keeps.

An order has one line per item: adding an item already on it raises that
line's count, so each item has one set of slot qualities.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional

from src.utils.i18n import tr

QUALITY_MIN = 0
QUALITY_MAX = 1000
# The neutral point of every curve in the game data: 1.0x, +0 pips.
QUALITY_DEFAULT = 500
COUNT_MAX = 999
UNIT_SCU = "scu"
UNIT_PIECES = "unit"
VOLUME_SCU = "scu"
VOLUME_CSCU = "cscu"


@dataclass
class OrderLine:
    """One item on the order: its blueprint key, how many, and per slot the
    material quality and whether the slot is used (only a pick's slots can
    be off)."""

    key: str
    count: int = 1
    q: list[int] = field(default_factory=list)
    on: list[bool] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"key": self.key, "count": self.count, "q": list(self.q), "on": list(self.on)}


@dataclass
class StatModifier:
    """A stat's combined change: ``mul`` multiplies it, ``add`` adds pips."""

    mul: float = 1.0
    add: int = 0
    slots: int = 0
    pips: bool = False


@dataclass
class MaterialTotal:
    """One material on the order: the total, and how much at each quality
    (highest first), with the items that use it."""

    material: str
    unit: str
    amount: float
    by_quality: list[tuple[int, float]]
    items: list[str]


def clamp_quality(q, low: int = QUALITY_MIN) -> int:
    try:
        value = round(float(q))
    except (TypeError, ValueError):
        value = QUALITY_DEFAULT
    return max(max(QUALITY_MIN, int(low)), min(QUALITY_MAX, value))


def blueprints_by_key(blueprints: Iterable[dict]) -> dict[str, dict]:
    return {bp["k"]: bp for bp in blueprints if isinstance(bp, dict) and bp.get("k")}


def _picks(bp: dict) -> list[dict]:
    return bp.get("p") or []


def new_line(bp: dict) -> OrderLine:
    """A line at neutral quality, with each pick's first slots chosen."""
    taken: dict[int, int] = {}
    on = []
    for slot in bp["s"]:
        g = slot.get("g")
        if g is None:
            on.append(True)
            continue
        taken[g] = taken.get(g, 0) + 1
        need = _picks(bp)[g]["k"] if g < len(_picks(bp)) else 0
        on.append(taken[g] <= need)
    return OrderLine(
        key=bp["k"],
        count=1,
        q=[clamp_quality(QUALITY_DEFAULT, slot.get("min", 0)) for slot in bp["s"]],
        on=on,
    )


def picks_valid(bp: dict, on: list[bool]) -> bool:
    """Each pick has exactly the number of slots it needs switched on."""
    return all(
        sum(1 for i, slot in enumerate(bp["s"]) if slot.get("g") == g and on[i]) == pick["k"]
        for g, pick in enumerate(_picks(bp))
    )


def fit_line(raw, bp: Optional[dict]) -> Optional[OrderLine]:
    """A stored line made to fit its blueprint again, or None when the
    blueprint is gone (a patch can drop one). Lengths and ranges are repaired."""
    if bp is None or not isinstance(raw, dict):
        return None
    fresh = new_line(bp)
    try:
        count = int(round(float(raw.get("count", 1))))
    except (TypeError, ValueError):
        count = 1
    stored_q = raw.get("q") if isinstance(raw.get("q"), list) else []
    q = [
        clamp_quality(stored_q[i], slot.get("min", 0)) if i < len(stored_q) else fresh.q[i]
        for i, slot in enumerate(bp["s"])
    ]
    stored_on = raw.get("on")
    on = (
        [bool(v) for v in stored_on]
        if isinstance(stored_on, list)
        and len(stored_on) == len(bp["s"])
        and picks_valid(bp, [bool(v) for v in stored_on])
        else fresh.on
    )
    return OrderLine(key=bp["k"], count=max(1, min(COUNT_MAX, count)), q=q, on=on)


def load_order(raw_lines, by_key: dict[str, dict]) -> list[OrderLine]:
    """The saved order fitted to the blueprints there are now. Lines whose
    blueprint is gone are dropped; two lines for one item become one."""
    lines: list[OrderLine] = []
    seen: dict[str, OrderLine] = {}
    for raw in raw_lines if isinstance(raw_lines, list) else []:
        line = fit_line(raw, by_key.get(raw.get("key")) if isinstance(raw, dict) else None)
        if line is None:
            continue
        if line.key in seen:
            seen[line.key].count = min(COUNT_MAX, seen[line.key].count + line.count)
            continue
        seen[line.key] = line
        lines.append(line)
    return lines


def add_to_order(lines: list[OrderLine], bp: dict, count: int = 1) -> OrderLine:
    """Add *count* of *bp*: the item's line goes up when it is already on the
    order, otherwise a new line is added at the end. Returns the line."""
    for line in lines:
        if line.key == bp["k"]:
            line.count = min(COUNT_MAX, line.count + count)
            return line
    line = new_line(bp)
    line.count = max(1, min(COUNT_MAX, count))
    lines.append(line)
    return line


def toggle_pick_slot(bp: dict, on: list[bool], index: int) -> list[bool]:
    """Switch a pick slot on or off. Turning one on beyond what the pick
    needs turns off the pick's earliest other chosen slot; turning one off
    turns on another, so the craft stays valid."""
    if not 0 <= index < len(bp["s"]):
        return on
    g = bp["s"][index].get("g")
    if g is None:
        return on
    need = _picks(bp)[g]["k"] if g < len(_picks(bp)) else 0
    nxt = list(on)
    if nxt[index]:
        other = next(
            (
                i
                for i, slot in enumerate(bp["s"])
                if slot.get("g") == g and not nxt[i] and i != index
            ),
            None,
        )
        if other is None:
            return on
        nxt[index] = False
        nxt[other] = True
        return nxt
    nxt[index] = True
    chosen = [i for i, slot in enumerate(bp["s"]) if slot.get("g") == g and nxt[i] and i != index]
    if len(chosen) >= need and chosen:
        nxt[chosen[0]] = False
    return nxt


def curve_value(curve: dict, quality: float) -> float:
    """A curve's value at a quality: linear within the segment that holds
    it, clamped outside the covered range."""
    segments = curve.get("s") or []
    if not segments:
        return 0.0 if curve.get("add") else 1.0
    best = segments[0]
    for seg in segments:
        if quality >= seg[0]:
            best = seg
    q_min, q_max, v_min, v_max = best
    if q_max <= q_min:
        return v_min
    t = max(0.0, min(1.0, (quality - q_min) / (q_max - q_min)))
    return v_min + (v_max - v_min) * t


def stat_modifiers(
    bp: dict,
    curves: list[dict],
    qualities: list[int],
    on: Optional[list[bool]] = None,
    only: Optional[int] = None,
) -> dict[str, StatModifier]:
    """The combined change per stat for one slot (*only*) or the whole item.
    Where two slots move one stat, multipliers multiply and pips add: the
    game files don't say how the game combines them, so that is assumed."""
    out: dict[str, StatModifier] = {}
    for i, slot in enumerate(bp["s"]):
        if only is not None and i != only:
            continue
        if on is not None and not on[i]:
            continue
        q = qualities[i] if i < len(qualities) else QUALITY_DEFAULT
        for stat, ci in slot.get("m") or []:
            if not 0 <= ci < len(curves):
                continue
            curve = curves[ci]
            mod = out.setdefault(stat, StatModifier())
            value = curve_value(curve, q)
            if curve.get("add"):
                mod.add += round(value)
                mod.pips = True
            else:
                mod.mul *= value
            mod.slots += 1
    return out


def modifier_sign(mod: StatModifier) -> int:
    value = mod.add if mod.pips else round((mod.mul - 1) * 1000)
    return (value > 0) - (value < 0)


def format_modifier(mod: StatModifier) -> str:
    """Like "+12%" or "-5%" for a multiplier, "+2 pips" for pips."""
    if mod.pips:
        return tr("sco.order_pips", value=f"{mod.add:+d}" if mod.add else "0")
    pct = round((mod.mul - 1) * 1000) / 10
    return f"{pct:+g}%" if pct else "0%"


def material_totals(
    lines: Iterable[OrderLine], by_key: dict[str, dict], only: Optional[str] = None
) -> list[MaterialTotal]:
    """What the order (or the one line for *only*) needs, one row per
    material, split by the quality each slot calls for. Rows are ordered by
    unit (SCU first), then most needed."""
    rows: dict[tuple[str, str], dict] = {}
    for line in lines:
        if only is not None and line.key != only:
            continue
        bp = by_key.get(line.key)
        if bp is None:
            continue
        for i, slot in enumerate(bp["s"]):
            if i < len(line.on) and not line.on[i]:
                continue
            row = rows.setdefault(
                (slot["mat"], slot["u"]), {"amount": 0.0, "bands": {}, "items": set()}
            )
            amount = float(slot["q"]) * line.count
            quality = line.q[i] if i < len(line.q) else QUALITY_DEFAULT
            row["amount"] += amount
            row["bands"][quality] = row["bands"].get(quality, 0.0) + amount
            row["items"].add(bp["n"])
    totals = [
        MaterialTotal(
            material=mat,
            unit=unit,
            amount=_round(row["amount"]),
            by_quality=[(q, _round(a)) for q, a in sorted(row["bands"].items(), reverse=True)],
            items=sorted(row["items"], key=str.casefold),
        )
        for (mat, unit), row in rows.items()
    ]
    totals.sort(key=lambda t: (t.unit != UNIT_SCU, -t.amount, t.material))
    return totals


def _round(value: float) -> float:
    return round(value, 4)


def format_amount(amount: float, unit: str, volume: str = VOLUME_CSCU) -> str:
    """Like "0.36 SCU", "36 cSCU" or "7 pcs"."""
    if unit == UNIT_PIECES:
        n = _round(amount)
        return tr("sco.order_pieces", count=f"{n:g}")
    if volume == VOLUME_CSCU:
        centi = amount * 100
        return tr("sco.order_cscu", amount=f"{round(centi, 0 if centi >= 100 else 2):g}")
    digits = 1 if amount >= 100 else 2 if amount >= 1 else 3
    return tr("sco.order_scu", amount=f"{round(amount, digits):g}")


def search_blueprints(
    blueprints: Iterable[dict],
    query: str,
    material_names: Optional[dict[str, str]] = None,
    limit: int = 40,
) -> list[dict]:
    """Blueprints whose name, category or materials hold every word of the
    query, names starting with the first word first."""
    words = query.strip().lower().split()
    if not words:
        return []
    names = material_names or {}
    scored = []
    for bp in blueprints:
        name = bp["n"].lower()
        hay = " ".join(
            [name, bp.get("c", "").lower()]
            + [names.get(s["mat"], s["mat"]).lower() for s in bp["s"]]
        )
        if not all(w in hay for w in words):
            continue
        score = 0 if name.startswith(words[0]) else 1 if words[0] in name else 2
        scored.append((score, bp["n"].casefold(), bp["k"], bp))
    scored.sort(key=lambda s: s[:3])
    return [bp for *_rest, bp in scored[:limit]]


def order_text(
    totals: list[MaterialTotal],
    lines: list[OrderLine],
    by_key: dict[str, dict],
    material_names: dict[str, str],
    volume: str = VOLUME_CSCU,
) -> str:
    """The order as plain text, for pasting into Discord: the items, then
    every material with its amount at each quality."""
    out = [tr("sco.order_text_title", count=sum(line.count for line in lines))]
    for line in lines:
        bp = by_key.get(line.key)
        if bp is not None:
            out.append(f"- {line.count} x {bp['n']}")
    out.append(tr("sco.order_text_materials"))
    for row in totals:
        bands = ", ".join(
            tr("sco.order_text_band", amount=format_amount(a, row.unit, volume), quality=q)
            for q, a in row.by_quality
        )
        out.append(
            f"- {material_names.get(row.material, row.material)}: "
            f"{format_amount(row.amount, row.unit, volume)} ({bands})"
        )
    return "\n".join(out)
