"""장비 생성, 능력치 계산, 가격."""
from .data import (AFFIXES, ITEM_BASES, ITEM_PREFIX, MAIN_STATS, PCT_STATS, RARITIES, SETS,
                   UNIQUES, WEAPON_BASES)

ITEM_TYPES = ["weapon", "weapon", "helmet", "armor", "gloves", "boots", "amulet", "ring"]


def slot_type(slot):
    return "ring" if slot in ("ring1", "ring2") else slot


def _round(stat, v):
    return round(v, 3) if stat in PCT_STATS else max(1, round(v))


def _main_value(slot, stat, f):
    for s, base, per in MAIN_STATS.get(slot, []):
        if s == stat:
            return base + per * f
    for s, base, per in AFFIXES:
        if s == stat:
            return base + per * f
    return 1


def _add_affixes(rng, stats, n, f, mult=1.0):
    pool = AFFIXES[:]
    rng.shuffle(pool)
    for stat, base, per in pool[:n]:
        v = (base + per * f) * rng.uniform(0.8, 1.2) * mult
        stats[stat] = stats.get(stat, 0) + v


def make_item(rng, floor, classes, new_id, min_rarity=0, rarity=None, slot=None):
    """floor: 아이템 레벨, classes: 무기 직업을 고를 때 쓸 파티 직업 목록."""
    f = max(1, floor)
    if rarity is None:
        weights = [r["w"] * (1 + 0.12 * f * min(i, 3)) if i >= min_rarity else 0
                   for i, r in enumerate(RARITIES)]
        rarity = rng.choices(range(len(RARITIES)), weights=weights)[0]
    rar = RARITIES[rarity]
    item = {"id": new_id(), "rarity": rarity, "plus": 0, "ilvl": f,
            "req": max(1, round(f * 1.15) - 1)}
    stats = {}

    if rarity == 3:  # 전설 고유
        cands = [u for u in UNIQUES if (u.get("cls") in classes or not u.get("cls"))
                 and (slot is None or u["slot"] == slot)]
        u = rng.choice(cands or UNIQUES)
        item.update({"slot": u["slot"], "name": u["name"], "unique": u["id"], "effect": u["effect"]})
        if u.get("cls"):
            item["cls"] = u["cls"]
        for stat, v in u["stats"].items():
            stats[stat] = v if stat in PCT_STATS else _main_value(u["slot"], stat, f) * rar["mult"] * v
        for stat, base, per in MAIN_STATS[u["slot"]]:
            stats.setdefault(stat, (base + per * f) * rar["mult"])
        _add_affixes(rng, stats, rar["affix"], f)
    else:
        if rarity == 4:  # 세트
            sid = rng.choice(list(SETS))
            st = SETS[sid]
            slot = slot if slot in st["pieces"] else rng.choice(st["pieces"])
            item.update({"slot": slot, "set": sid,
                         "name": f"{st['name']} {rng.choice(ITEM_BASES[slot])}"})
        else:
            slot = slot or rng.choice(ITEM_TYPES)
            if slot == "weapon":
                cls = rng.choice(classes)
                item["cls"] = cls
                base = rng.choice(WEAPON_BASES[cls])
            else:
                base = rng.choice(ITEM_BASES[slot])
            item.update({"slot": slot, "name": f"{rng.choice(ITEM_PREFIX[rarity])} {base}"})
        m = rar["mult"] * rng.uniform(0.85, 1.15)
        for stat, base, per in MAIN_STATS[slot]:
            stats[stat] = (base + per * f) * m
        n_aff = rar["affix"] + (1 if slot in ("ring", "amulet") else 0)
        _add_affixes(rng, stats, n_aff, f, 1.3 if slot in ("ring", "amulet") else 1.0)

    item["stats"] = {k: _round(k, v) for k, v in stats.items()}
    return item


def item_stats(item):
    """강화 수치를 반영한 실제 능력치."""
    plus = item.get("plus", 0)
    out = {}
    for k, v in item["stats"].items():
        out[k] = round(v * (1 + 0.05 * plus), 3) if k in PCT_STATS else round(v * (1 + 0.1 * plus))
    return out


def item_value(item):
    return int((10 + 4 * item["ilvl"]) * (1 + item["rarity"] * 1.5) * (1 + 0.25 * item.get("plus", 0)))


def enhance_cost(item):
    return int(item_value(item) * (0.4 + 0.2 * item.get("plus", 0)))


def enhance_chance(item):
    return max(0.3, 1 - 0.08 * item.get("plus", 0))
