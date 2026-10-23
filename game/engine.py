"""게임 규칙. 네트워크와 무관한 순수 로직이라 단독으로 테스트할 수 있다.

실시간 진행: 서버가 TICK초마다 tick()을 호출한다.
좌표는 실수(타일 단위), 타일 (i, j)의 중심은 (i + 0.5, j + 0.5).
"""
import math
import random
import secrets

from .data import (BOSS_EVERY, BOSSES, CLASSES, ELITES, ENEMIES, ENEMY_ATTACK_BASE, ENEMY_POOLS,
                   ENHANCE_MAX, GOLD, INVENTORY_SIZE, LEVEL_UP, PLAYER_ATTACK_BASE, PLAYER_SPEED,
                   POTION_CD, POTION_HEAL, POTION_MAX, POTION_PRICE, RESPAWN_SEC, SETS, SHOP_SIZE,
                   SKILL_MAX, SLOTS, XP, xp_to_next)
from .dungeon import Dungeon
from .items import enhance_chance, enhance_cost, item_stats, item_value, make_item

TICK = 0.1
MAX_PLAYERS = 4
LOG_SIZE = 50
AGGRO_RANGE = 6.5
PACK_RANGE = 4
LEASH = 16
REGEN_DELAY = 5
REGEN_RATE = 0.015
PICKUP_RANGE = 0.8
NPC_RANGE = 1.8

BASE_STATS = ("max_hp", "atk", "df", "spd", "crit", "crit_dmg", "lifesteal", "thorns", "as", "ms",
              "cdr", "dr", "max_hp_pct", "heal_pct", "burn_pct", "poison_pct")


class GameError(Exception):
    pass


def dist(a, b):
    return math.hypot(a["x"] - b["x"], a["y"] - b["y"])


def dist_xy(a, x, y):
    return math.hypot(a["x"] - x, a["y"] - y)


def tile(e):
    return int(e["x"]), int(e["y"])


# ---------- 플레이어 ----------
def new_player(pid, name, cls="warrior"):
    p = {"id": pid, "name": name, "connected": True, "ready": False}
    reset_player(p, cls)
    return p


def reset_player(p, cls):
    first = CLASSES[cls]["skills"][0]["id"]
    p.update({
        "cls": cls, "level": 1, "xp": 0, "sp": 0, "skills": {first: 1}, "bonus": {},
        "eq": {s: None for s in SLOTS}, "inv": [], "potions": 3, "gold": 0,
        "shield": 0, "status": {}, "cds": {}, "x": 0.5, "y": 0.5, "wps": [], "target": None,
        "atk_cd": 0.0, "downed": False, "respawn_at": 0.0, "last_hit": -99.0, "regen": 0.0,
        "prompt": None, "npc": None, "want_npc": None, "phoenix_used": False, "stuck": 0, "hp": 1,
    })
    recalc(p)
    p["hp"] = p["max_hp"]


def class_skill(cls, sid):
    c = CLASSES[cls]
    for s in c["skills"] + c["passives"]:
        if s["id"] == sid:
            return s
    return None


def sv(s, key, lvl):
    """스킬 레벨을 반영한 값."""
    return s.get(key, 0) + s.get("lv", {}).get(key, 0) * (lvl - 1)


def recalc(p):
    c = CLASSES[p["cls"]]
    lv = p["level"] - 1
    st = {k: 0 for k in BASE_STATS}
    st.update({"max_hp": c["hp"] + lv * LEVEL_UP["max_hp"], "atk": c["atk"] + lv * LEVEL_UP["atk"],
               "df": c["df"], "spd": c["spd"], "crit": c.get("crit", 0.05), "crit_dmg": 0.6})
    for ps in c["passives"]:
        lvl = p["skills"].get(ps["id"], 0)
        for k, v in ps["stats"].items():
            st[k] += v * lvl
    for k, v in p["bonus"].items():
        st[k] += v
    fx, sets = set(), {}
    for it in p["eq"].values():
        if not it:
            continue
        for k, v in item_stats(it).items():
            st[k] += v
        if it.get("unique"):
            fx.add(it["unique"])
        if it.get("set"):
            sets[it["set"]] = sets.get(it["set"], 0) + 1
    for sid, n in sets.items():
        for need, bonus in SETS[sid]["bonus"].items():
            if n >= need:
                for k, v in bonus.items():
                    st[k] += v
    st["max_hp"] = max(10, round(st["max_hp"] * (1 + st["max_hp_pct"])))
    st["crit"] = min(st["crit"], 0.8)
    st["cdr"] = min(st["cdr"], 0.5)
    st["dr"] = min(st["dr"], 0.6)
    st["atk"], st["df"] = round(st["atk"]), round(st["df"])
    for k in ("crit", "crit_dmg", "lifesteal", "as", "ms", "cdr", "dr", "heal_pct", "burn_pct", "poison_pct"):
        st[k] = round(st[k], 3)
    p.update(st)
    p["fx"] = sorted(fx)
    p["sets"] = sets
    p["hp"] = min(p["hp"], p["max_hp"])


class Game:
    def __init__(self, code):
        self.code = code
        self.players = {}
        self.host = None
        self.phase = "lobby"    # lobby / explore / gameover
        self.town = False
        self.floor = 0
        self.time = 0.0
        self.ticks = 0
        self.dg = None
        self.map_id = 0
        self.monsters = []
        self.items = []
        self.objects = []
        self.zones = []         # 몬스터 광역기 예고
        self.fields = []        # 플레이어 지속 장판
        self.pending = []       # 일정 시간 뒤 다시 나타날 몬스터 (해골 재조립)
        self.stairs = None
        self.shop = []
        self.notice = ""
        self.log = []
        self.chat = []
        self.messages = []      # (pid, text) 개인 알림
        self.ev = []
        self.changed = set()
        self.dirty = False
        self.pdirty = set()     # 개인 정보(가방 등)를 다시 보내야 할 플레이어
        self.best_floor = 0
        self.uid = 0
        self.rng = random.Random()

    # ---------- 공통 ----------
    def new_id(self, prefix="i"):
        self.uid += 1
        return f"{prefix}{self.uid}"

    def add_log(self, text):
        self.log.append(text)
        del self.log[:-LOG_SIZE]
        self.dirty = True

    def tell(self, pid, text):
        self.messages.append((pid, text))

    def active_players(self):
        return [p for p in self.players.values() if not p["downed"]]

    def connected(self):
        return [p for p in self.players.values() if p["connected"]]

    def monster(self, mid):
        for m in self.monsters:
            if m["id"] == mid:
                return m
        return None

    def classes(self):
        return [p["cls"] for p in self.players.values()] or ["warrior"]

    def los(self, a, b):
        return self.dg.los(tile(a), tile(b))

    def in_range(self, a, b, rng):
        return dist(a, b) <= rng and self.los(a, b)

    def touch(self, p):
        self.pdirty.add(p["id"])

    # ---------- 로비 ----------
    def join(self, name):
        if self.phase != "lobby":
            raise GameError("이미 게임이 진행 중입니다.")
        if len(self.players) >= MAX_PLAYERS:
            raise GameError("방이 가득 찼습니다. (최대 4명)")
        pid = secrets.token_hex(3)
        taken = {p["cls"] for p in self.players.values()}
        cls = next((c for c in CLASSES if c not in taken), "warrior")
        self.players[pid] = new_player(pid, name[:10] or "모험가", cls)
        if self.host is None:
            self.host = pid
        return pid

    def set_connected(self, pid, on):
        p = self.players[pid]
        p["connected"] = on
        p["wps"], p["target"] = [], None
        if not on and self.host == pid:
            others = [q["id"] for q in self.connected()]
            if others:
                self.host = others[0]
        if on and (self.host is None or not self.players[self.host]["connected"]):
            self.host = pid
        self.touch(p)

    def leave(self, pid):
        if self.phase == "lobby" and pid in self.players:
            del self.players[pid]
            if self.host == pid:
                self.host = next(iter(self.players), None)

    def choose_class(self, pid, cls):
        if self.phase != "lobby":
            raise GameError("로비에서만 직업을 바꿀 수 있습니다.")
        if cls not in CLASSES:
            raise GameError("없는 직업입니다.")
        reset_player(self.players[pid], cls)

    def toggle_ready(self, pid):
        self.players[pid]["ready"] = not self.players[pid]["ready"]

    def start(self, pid):
        if pid != self.host:
            raise GameError("방장만 시작할 수 있습니다.")
        if self.phase not in ("lobby", "gameover"):
            raise GameError("이미 시작했습니다.")
        for p in self.players.values():
            reset_player(p, p["cls"])
            p["ready"] = False
            self.touch(p)
        self.floor = 1
        self.log = []
        self.new_floor()

    def to_lobby(self, pid):
        if pid != self.host:
            raise GameError("방장만 할 수 있습니다.")
        if self.phase != "gameover":
            raise GameError("게임이 끝난 뒤에만 가능합니다.")
        self.phase = "lobby"
        for pid_ in [p["id"] for p in self.players.values() if not p["connected"]]:
            self.leave(pid_)

    # ---------- 층 생성 ----------
    def is_boss_floor(self):
        return self.floor % BOSS_EVERY == 0

    def reset_level_state(self, dg):
        self.dg = dg
        self.map_id += 1
        self.monsters, self.items, self.objects = [], [], []
        self.zones, self.fields, self.pending = [], [], []
        self.best_floor = max(self.best_floor, self.floor)
        sx, sy = dg.start
        spots = sorted(dg.room_tiles(dg.start_room, 0), key=lambda t: abs(t[0] - sx) + abs(t[1] - sy))
        for p, (x, y) in zip(self.players.values(), spots):
            p.update({"x": x + 0.5, "y": y + 0.5, "wps": [], "prompt": None, "target": None,
                      "npc": None, "want_npc": None, "status": {}, "shield": 0, "phoenix_used": False})
            if p["downed"]:
                p["downed"] = False
                p["hp"] = math.ceil(p["max_hp"] * 0.3)
            self.touch(p)
        self.phase = "explore"
        self.dirty = True

    def new_floor(self):
        self.town = False
        dg = Dungeon(self.rng)
        self.reset_level_state(dg)
        used = {dg.stairs} | set(dg.room_tiles(dg.start_room, 0))

        def free_tiles(room, n):
            tiles = [t for t in dg.room_tiles(room, 1) if t not in used] or \
                    [t for t in dg.room_tiles(room, 0) if t not in used]
            cx, cy = self.rng.choice(tiles)
            tiles.sort(key=lambda t: (abs(t[0] - cx) + abs(t[1] - cy), self.rng.random()))
            out = tiles[:n]
            used.update(out)
            return out

        boss = self.is_boss_floor()
        self.stairs = {"x": dg.stairs[0], "y": dg.stairs[1], "locked": boss, "portal": False}
        others = [r for r in dg.rooms if r is not dg.start_room]
        for r in others:
            if r is dg.far_room and boss:
                x, y = dg.stairs
                bx = x - 2 if dg.walkable(x - 2, y) else x + 2 if dg.walkable(x + 2, y) else x
                kind = BOSSES[((self.floor // BOSS_EVERY) - 1) % len(BOSSES)]
                self.spawn(kind, bx + 0.5, y + 0.5)
                continue
            if self.rng.random() < 0.8:
                kinds = self.roll_group()
                for k, (x, y) in zip(kinds, free_tiles(r, len(kinds))):
                    self.spawn(k, x + 0.5, y + 0.5)
        rooms = others[:]
        self.rng.shuffle(rooms)
        for i, r in enumerate(rooms):
            kind = "chest" if i < 4 else "fountain" if i == 4 else \
                   "altar" if i == 5 and self.rng.random() < 0.6 else None
            if not kind:
                break
            (x, y), = free_tiles(r, 1)
            self.objects.append({"id": self.new_id("o"), "x": x, "y": y, "kind": kind, "used": False})
        self.add_log(f"── {self.floor}층 ──")
        self.notice = (f"{self.floor}층. 보스가 계단을 지키고 있다!" if boss
                       else f"{self.floor}층. 계단을 찾아 내려가자.")

    def new_town(self):
        self.town = True
        dg = Dungeon(self.rng, town=True)
        self.reset_level_state(dg)
        for p in self.players.values():
            p["hp"] = p["max_hp"]
        self.stairs = {"x": dg.stairs[0], "y": dg.stairs[1], "locked": False, "portal": True}
        for mark, kind in (("S", "shop"), ("B", "smith")):
            x, y = dg.marks[mark]
            self.objects.append({"id": self.new_id("o"), "x": x, "y": y, "kind": kind, "used": False})
        f = self.floor + 1
        self.shop = [make_item(self.rng, f, self.classes(), self.new_id, rarity=r)
                     for r in [0, 0, 0, 1, 1, 1, 1, 2, 2, 2][:SHOP_SIZE]]
        self.add_log("── 마을 ──")
        self.notice = "마을에 도착했다. 상인과 대장장이를 이용하고 포탈로 다음 층에 가자."

    def roll_group(self):
        n = len(self.players)
        pool = [p for lv, p in ENEMY_POOLS if self.floor >= lv][-1]
        if self.floor >= 2 and self.rng.random() < 0.15:
            kinds = [self.rng.choice(ELITES)]
            if n >= 3:
                kinds.append(self.rng.choice(pool))
            return kinds
        count = max(1, min(5, n + self.rng.choice([0, 0, 1, 1, 2])))
        return [self.rng.choice(pool) for _ in range(count)]

    def spawn(self, kind, x, y, aggro=False, owner=None, hp_ratio=1.0):
        d = ENEMIES[kind]
        f, n = self.floor, len(self.players)
        loop = (f - 1) // (BOSS_EVERY * len(BOSSES))
        atk_mult = 1.3 * (1 + 0.2 * (f - 1)) * (1 + 0.3 * loop)
        tier = "boss" if d.get("boss") else "elite" if d.get("elite") else "normal"
        if tier == "normal":
            hp_mult = (1 + 0.3 * (f - 1)) * (1 + 0.5 * loop) * (1 + 0.12 * (n - 1))
        else:
            hp_mult = (0.7 + 0.75 * (n - 1)) * (1 + 0.2 * (f - 1)) * (1 + 0.5 * loop)
        hp = max(1, round(d["hp"] * hp_mult))
        m = {
            "id": self.new_id("m"), "kind": kind, "name": d["name"], "tier": tier,
            "sprite": d.get("sprite", kind), "scale": d.get("scale", 1.0),
            "x": x, "y": y, "home": (x, y), "hp": max(1, round(hp * hp_ratio)), "max_hp": hp,
            "atk": max(1, round(d["atk"] * atk_mult)), "df": d["df"], "spd": d["spd"],
            "speed": d["speed"], "range": d.get("range", 1.2), "crit": 0.05, "crit_dmg": 0.5,
            "lifesteal": d.get("lifesteal", 0), "thorns": 0, "dr": 0, "shield": 0, "status": {},
            "heal_mult": hp_mult, "aggro": aggro, "returning": False,
            "atk_cd": self.rng.uniform(0.3, 1.0), "wps": [], "repath": 0,
            "taunt_by": None, "taunt_until": 0, "owner": owner, "enraged": False,
            "ab_cd": [self.time + self.rng.uniform(1, 3) for _ in d.get("abilities", [])],
            "charge": None, "fuse": None, "reassembled": False,
        }
        self.monsters.append(m)
        self.changed.add(m["id"])
        self.dirty = True
        return m

    def free_spot_near(self, x, y, radius=2):
        cands = [(tx, ty) for (tx, ty), d in self.dg.distances((int(x), int(y)), limit=radius).items() if d >= 1]
        if not cands:
            return x, y
        tx, ty = self.rng.choice(cands)
        return tx + 0.5, ty + 0.5

    # ---------- 아이템 ----------
    def make_item(self, **kw):
        return make_item(self.rng, self.floor, self.classes(), self.new_id, **kw)

    def drop_near(self, x, y, loot):
        """loot: 아이템 dict 또는 "potion"."""
        if not loot:
            return
        d = self.dg.distances((int(x), int(y)), limit=2)
        spots = sorted(d, key=lambda t: (d[t], self.rng.random()))
        for i, it in enumerate(loot):
            tx, ty = spots[i % len(spots)]
            gx, gy = tx + 0.5 + self.rng.uniform(-0.2, 0.2), ty + 0.5 + self.rng.uniform(-0.2, 0.2)
            if it == "potion":
                self.items.append({"id": self.new_id("g"), "x": gx, "y": gy, "potion": True})
            else:
                self.items.append({"id": it["id"], "x": gx, "y": gy, "item": it})
        self.dirty = True

    def find_inv(self, p, iid):
        for it in p["inv"]:
            if it["id"] == iid:
                return it
        raise GameError("가방에 없는 아이템입니다.")

    def can_wear(self, p, it):
        if it.get("cls") and it["cls"] != p["cls"]:
            raise GameError(f"{CLASSES[it['cls']]['name']} 전용 장비입니다.")
        if it["req"] > p["level"]:
            raise GameError(f"레벨 {it['req']} 이상 착용 가능합니다.")

    def equip(self, pid, iid, slot=None):
        p = self.players[pid]
        it = self.find_inv(p, iid)
        self.can_wear(p, it)
        t = it["slot"]
        if t == "ring":
            if slot not in ("ring1", "ring2"):
                slot = "ring1" if not p["eq"]["ring1"] else "ring2" if not p["eq"]["ring2"] else "ring1"
        else:
            slot = t
        old = p["eq"][slot]
        p["inv"].remove(it)
        p["eq"][slot] = it
        if old:
            p["inv"].append(old)
        recalc(p)
        self.touch(p)

    def unequip(self, pid, slot):
        p = self.players[pid]
        it = p["eq"].get(slot)
        if not it:
            return
        if len(p["inv"]) >= INVENTORY_SIZE:
            raise GameError("가방이 가득 찼습니다.")
        p["eq"][slot] = None
        p["inv"].append(it)
        recalc(p)
        self.touch(p)

    def drop_item(self, pid, iid):
        if self.phase != "explore":
            raise GameError("지금은 버릴 수 없습니다.")
        p = self.players[pid]
        it = self.find_inv(p, iid)
        p["inv"].remove(it)
        self.items.append({"id": it["id"], "x": p["x"], "y": p["y"], "item": it, "dropped_by": pid})
        self.touch(p)
        self.dirty = True

    def sort_inv(self, pid):
        p = self.players[pid]
        p["inv"].sort(key=lambda i: (-i["rarity"], i["slot"], -i["ilvl"]))
        self.touch(p)

    # ---------- 마을 ----------
    def need_npc(self, p, kind):
        if p["npc"] != kind:
            raise GameError("가까이 가서 대화하세요.")

    def shop_buy(self, pid, idx):
        p = self.players[pid]
        self.need_npc(p, "shop")
        if not (0 <= idx < len(self.shop)):
            raise GameError("없는 상품입니다.")
        it = self.shop[idx]
        price = item_value(it)
        if p["gold"] < price:
            raise GameError("골드가 부족합니다.")
        if len(p["inv"]) >= INVENTORY_SIZE:
            raise GameError("가방이 가득 찼습니다.")
        p["gold"] -= price
        p["inv"].append(self.shop.pop(idx))
        self.add_log(f"{p['name']}이(가) [{it['name']}] 구매 (-{price}G)")
        for q in self.players.values():
            if q["npc"] == "shop":
                self.touch(q)

    def buy_potion(self, pid):
        p = self.players[pid]
        self.need_npc(p, "shop")
        price = POTION_PRICE + 2 * self.floor
        if p["gold"] < price:
            raise GameError("골드가 부족합니다.")
        if p["potions"] >= POTION_MAX:
            raise GameError(f"물약은 {POTION_MAX}개까지 들 수 있습니다.")
        p["gold"] -= price
        p["potions"] += 1
        self.touch(p)

    def sell(self, pid, iid):
        p = self.players[pid]
        self.need_npc(p, "shop")
        it = self.find_inv(p, iid)
        price = item_value(it) // 4
        p["inv"].remove(it)
        p["gold"] += price
        self.touch(p)

    def enhance(self, pid, iid):
        p = self.players[pid]
        self.need_npc(p, "smith")
        it = next((i for i in p["inv"] if i["id"] == iid), None) or \
            next((i for i in p["eq"].values() if i and i["id"] == iid), None)
        if not it:
            raise GameError("없는 아이템입니다.")
        if it.get("plus", 0) >= ENHANCE_MAX:
            raise GameError("최대 강화입니다.")
        cost = enhance_cost(it)
        if p["gold"] < cost:
            raise GameError("골드가 부족합니다.")
        p["gold"] -= cost
        if self.rng.random() < enhance_chance(it):
            it["plus"] = it.get("plus", 0) + 1
            self.add_log(f"{p['name']}: [{it['name']}] +{it['plus']} 강화 성공!")
            self.tell(pid, f"강화 성공! +{it['plus']}")
        else:
            self.tell(pid, "강화 실패... (장비는 무사합니다)")
        recalc(p)
        self.touch(p)

    # ---------- 스킬 트리 ----------
    def learn(self, pid, sid):
        p = self.players[pid]
        s = class_skill(p["cls"], sid)
        if not s:
            raise GameError("없는 스킬입니다.")
        if p["sp"] <= 0:
            raise GameError("스킬 포인트가 없습니다.")
        lvl = p["skills"].get(sid, 0)
        if lvl >= SKILL_MAX:
            raise GameError("최대 레벨입니다.")
        need = s.get("req", 1) + 2 * lvl
        if p["level"] < need:
            raise GameError(f"캐릭터 레벨 {need} 이상 필요합니다.")
        p["sp"] -= 1
        p["skills"][sid] = lvl + 1
        recalc(p)
        self.touch(p)

    # ---------- 입력 ----------
    def set_path(self, e, gx, gy):
        """e를 (gx, gy)로 보낼 웨이포인트 계산. 실패하면 False."""
        st, gt = tile(e), (int(gx), int(gy))
        if not self.dg.walkable(*gt):
            return False
        if st == gt or self.dg.clear_line(e["x"], e["y"], gx, gy):
            e["wps"] = [(gx, gy)]
            return True
        path = self.dg.path(st, gt, limit=120)
        if path is None:
            return False
        wps = [(x + 0.5, y + 0.5) for x, y in path]
        if self.dg.free(gx, gy):
            wps[-1] = (gx, gy)
        e["wps"] = wps
        return True

    def move(self, pid, x, y):
        if self.phase != "explore":
            return
        p = self.players[pid]
        if p["downed"]:
            return
        x = min(max(float(x), 0), self.dg.w - 0.01)
        y = min(max(float(y), 0), self.dg.h - 0.01)
        p["target"], p["want_npc"] = None, None
        if p["wps"] and (int(p["wps"][-1][0]), int(p["wps"][-1][1])) == (int(x), int(y)) and len(p["wps"]) > 1:
            p["wps"][-1] = (x, y) if self.dg.free(x, y) else p["wps"][-1]
            return
        self.set_path(p, x, y)

    def attack(self, pid, mid):
        p = self.players[pid]
        if self.phase != "explore" or p["downed"] or not self.monster(mid):
            return
        p["target"], p["want_npc"] = mid, None
        p["repath"] = 0

    def talk(self, pid, oid):
        p = self.players[pid]
        o = next((o for o in self.objects if o["id"] == oid and o["kind"] in ("shop", "smith")), None)
        if not o or p["downed"]:
            return
        p["want_npc"], p["target"] = oid, None
        self.set_path(p, o["x"] + 0.5, o["y"] + 1.5)

    def close_npc(self, pid):
        p = self.players[pid]
        p["npc"], p["want_npc"] = None, None
        self.touch(p)

    def answer_prompt(self, pid, yes):
        p = self.players[pid]
        obj = next((o for o in self.objects if o["id"] == p["prompt"]), None)
        p["prompt"] = None
        self.touch(p)
        if not obj or obj["used"] or not yes:
            return
        obj["used"] = True
        b = p["bonus"]
        b["max_hp"] = b.get("max_hp", 0) - 15
        b["atk"] = b.get("atk", 0) + 3
        recalc(p)
        p["hp"] = max(1, p["hp"])
        self.add_log(f"{p['name']}이(가) 피를 바쳤다. 최대 체력 -15, 공격력 +3")

    # ---------- 스킬 사용 ----------
    def cast(self, pid, sid, x, y, target):
        if self.phase != "explore":
            raise GameError("지금은 스킬을 쓸 수 없습니다.")
        p = self.players[pid]
        if p["downed"]:
            raise GameError("쓰러진 상태입니다.")
        x, y = float(x), float(y)

        if sid == "potion":
            if self.time < p["cds"].get("potion", 0):
                return
            if p["potions"] <= 0:
                raise GameError("물약이 없습니다.")
            if p["hp"] >= p["max_hp"]:
                raise GameError("체력이 이미 가득합니다.")
            p["potions"] -= 1
            self.heal(p, math.ceil(p["max_hp"] * POTION_HEAL))
            p["cds"]["potion"] = self.time + POTION_CD
            self.ev.append({"k": "cast", "src": pid, "name": "물약", "id": "potion", "until": p["cds"]["potion"]})
            self.touch(p)
            return

        s = class_skill(p["cls"], sid)
        lvl = p["skills"].get(sid, 0)
        if not s or "target" not in s:
            raise GameError("없는 스킬입니다.")
        if lvl <= 0:
            raise GameError(f"{s['name']}: 아직 배우지 않았습니다. (K: 스킬 창)")
        left = p["cds"].get(sid, 0) - self.time
        if left > 0.05:
            raise GameError(f"{s['name']}: {left:.1f}초 후 사용 가능")
        t = s["target"]
        V = lambda k: sv(s, k, lvl)  # noqa: E731

        if t == "enemy":
            m = self.monster(target) if target else None
            if not (m and self.in_range(p, m, s["range"])):
                cands = [m for m in self.monsters if self.in_range(p, m, s["range"])]
                if not cands:
                    raise GameError(f"{s['name']}: 사거리({s['range']}칸) 안에 적이 없습니다.")
                m = min(cands, key=lambda m: dist_xy(m, x, y))
            self.ev.append({"k": "shot", "src": pid, "tgt": m["id"], "skill": sid})
            self.hit(p, m, V("mult"))
            if m["hp"] > 0:
                self.apply_status(m, s, lvl, p)
            if m["hp"] > 0:
                p["target"] = m["id"]
        elif t == "area":
            if dist_xy(p, x, y) > s["range"] + 0.5:
                raise GameError(f"{s['name']}: 너무 멉니다. ({s['range']}칸 이내)")
            self.ev.append({"k": "aoe", "x": x, "y": y, "r": s["radius"], "c": "#ff7a2f", "s": sid})
            for m in [m for m in self.monsters if dist_xy(m, x, y) <= s["radius"] + 0.4]:
                self.hit(p, m, V("mult"))
                if m["hp"] > 0:
                    self.apply_status(m, s, lvl, p)
        elif t == "around":
            self.ev.append({"k": "aoe", "x": p["x"], "y": p["y"], "r": s["radius"], "c": "#f1efe9", "s": sid})
            for m in [m for m in self.monsters if dist(m, p) <= s["radius"] + 0.4]:
                self.hit(p, m, V("mult"))
                if m["hp"] > 0:
                    self.apply_status(m, s, lvl, p)
        elif t in ("dash", "blink"):
            ox, oy = p["x"], p["y"]
            self.dash_to(p, x, y, s["range"])
            p["wps"] = []
            self.ev.append({"k": "dash", "src": pid, "x0": ox, "y0": oy, "x": p["x"], "y": p["y"], "s": sid})
            if t == "dash":
                self.ev.append({"k": "aoe", "x": p["x"], "y": p["y"], "r": s["radius"], "c": "#ffd27a", "s": sid})
                for m in [m for m in self.monsters if dist(m, p) <= s["radius"] + 0.4]:
                    self.hit(p, m, V("mult"))
                    if m["hp"] > 0:
                        self.apply_status(m, s, lvl, p)
            if s.get("crit_buff"):
                p["status"]["crit_buff"] = [s["crit_buff"], self.time + V("buff_time")]
        elif t == "field":
            if s.get("follow"):
                fx, fy = p["x"], p["y"]
            else:
                if dist_xy(p, x, y) > s["range"] + 0.5:
                    raise GameError(f"{s['name']}: 너무 멉니다. ({s['range']}칸 이내)")
                fx, fy = x, y
            self.fields.append({"id": self.new_id("f"), "owner": pid, "s": sid, "x": fx, "y": fy,
                                "r": s["radius"], "until": self.time + s["duration"],
                                "next": self.time, "interval": s.get("interval", 0.5),
                                "mult": V("mult"), "heal": V("heal"), "slow": s.get("slow", 0),
                                "follow": s.get("follow", False)})
        elif t == "self":
            if s.get("taunt"):
                for m in self.monsters:
                    if dist(m, p) <= s["radius"]:
                        m["taunt_by"], m["taunt_until"] = pid, self.time + s["taunt"]
                        self.aggro(m)
                p["status"]["taunt"] = self.time + s["taunt"]
                self.ev.append({"k": "aoe", "x": p["x"], "y": p["y"], "r": s["radius"], "c": "#ff5a4f", "s": sid})
            if s.get("shield"):
                p["shield"] += round(V("shield"))
        elif t == "ally":
            cands = [q for q in self.active_players() if self.in_range(p, q, s["range"])]
            q = next((c for c in cands if c["id"] == target), None) or \
                min(cands, key=lambda c: c["hp"] / c["max_hp"])
            self.ev.append({"k": "shot", "src": pid, "tgt": q["id"], "skill": sid})
            self.heal(q, round(p["atk"] * V("heal")), p)
        elif t == "allies":
            self.ev.append({"k": "aoe", "x": p["x"], "y": p["y"], "r": s["radius"], "c": "#7dffa0", "s": sid})
            for q in self.active_players():
                if dist(q, p) <= s["radius"]:
                    self.heal(q, round(p["atk"] * V("heal")), p)
                    q["shield"] += round(V("shield"))
        elif t == "dead":
            cands = [q for q in self.players.values() if q["downed"] and dist(q, p) <= s["range"]]
            if not cands:
                raise GameError(f"{s['name']}: {s['range']}칸 안에 쓰러진 아군이 없습니다.")
            q = min(cands, key=lambda c: dist(c, p))
            self.revive(q, V("ratio"))
            self.add_log(f"{p['name']}이(가) {q['name']}을(를) 부활시켰다!")

        p["cds"][sid] = self.time + V("cd") * (1 - p["cdr"])
        self.ev.append({"k": "cast", "src": pid, "name": s["name"], "id": sid, "until": p["cds"][sid]})

    def dash_to(self, e, x, y, max_d):
        dx, dy = x - e["x"], y - e["y"]
        d = math.hypot(dx, dy)
        if d < 0.01:
            return
        if d > max_d:
            dx, dy, d = dx / d * max_d, dy / d * max_d, max_d
        steps = int(d / 0.2) + 1
        for _ in range(steps):
            nx, ny = e["x"] + dx / steps, e["y"] + dy / steps
            if not self.dg.free(nx, ny):
                break
            e["x"], e["y"] = nx, ny

    def apply_status(self, m, s, lvl, src):
        st = m["status"]
        if s.get("stun"):
            dur = sv(s, "stun", lvl)
            st["stun"] = self.time + dur * (0.5 if m["tier"] == "boss" else 1)
            m["charge"] = None
        if s.get("poison"):
            st["poison"] = [max(2, round(src["atk"] * 0.35 * (1 + src.get("poison_pct", 0)))),
                            self.time + s["poison"]]
        if s.get("burn"):
            st["burn"] = [max(2, round(src["atk"] * 0.3 * (1 + src.get("burn_pct", 0)))), self.time + s["burn"]]
        self.changed.add(m["id"])

    # ---------- 피해/회복 ----------
    def crit_chance(self, u):
        c = u["crit"]
        b = u["status"].get("crit_buff")
        if b and b[1] > self.time:
            c += b[0]
        return c

    def hit(self, src, tgt, mult, kind="hit"):
        if tgt["hp"] <= 0 or tgt.get("downed"):
            return 0
        base = src["atk"] * mult * self.rng.uniform(0.9, 1.1)
        crit = self.rng.random() < self.crit_chance(src)
        fx = src.get("fx", ())
        if crit:
            base *= 1 + src.get("crit_dmg", 0.5) + (0.25 if "fang" in fx else 0)
        dmg = max(1, round((base - tgt["df"]) * (1 - tgt.get("dr", 0))))
        dealt = self.damage(tgt, dmg, kind, crit, src)
        if dealt and src.get("lifesteal") and src["hp"] > 0:
            self.heal(src, max(1, round(dealt * src["lifesteal"])), quiet=True)
        if crit and "fang" in fx:
            self.heal(src, max(1, round(src["max_hp"] * 0.03)), quiet=True)
        tfx = tgt.get("fx", ())
        # 반사 효과는 실제 유닛에게만 (몬스터 광역기는 가짜 공격자로 처리됨)
        real = src["id"] in self.players or src in self.monsters
        if real and src["hp"] > 0 and not src.get("downed") and tgt.get("thorns"):
            self.damage(src, tgt["thorns"], "thorns", False, tgt)
        if real and src["id"] not in self.players and src["hp"] > 0:
            if "thorncrown" in tfx:
                self.damage(src, max(1, round(dealt * 0.25)), "thorns", False, tgt)
            if "frostheart" in tfx and src["hp"] > 0 and self.rng.random() < 0.2:
                src["status"]["stun"] = self.time + 1.5
                self.ev.append({"k": "cast", "src": src["id"], "name": "빙결!"})
        if "thunder" in fx and src["id"] in self.players and self.rng.random() < 0.2:
            chain = [m for m in self.monsters if m is not tgt and dist(m, tgt) <= 4][:3]
            for m in chain:
                self.ev.append({"k": "chain", "x0": tgt["x"], "y0": tgt["y"], "x": m["x"], "y": m["y"]})
                self.damage(m, max(1, round(src["atk"] * 0.8 - m["df"])), "hit", False, src)
        return dealt

    def damage(self, tgt, dmg, kind, crit=False, src=None):
        if tgt["hp"] <= 0:
            return 0
        absorbed = min(tgt["shield"], dmg)
        tgt["shield"] -= absorbed
        dealt = dmg - absorbed
        tgt["hp"] = max(0, tgt["hp"] - dealt)
        self.ev.append({"k": "dmg", "tgt": tgt["id"], "v": dmg, "crit": crit, "kind": kind})
        if tgt["id"] in self.players:
            tgt["last_hit"] = self.time
            if tgt["hp"] <= 0 and "phoenix" in tgt.get("fx", ()) and not tgt["phoenix_used"]:
                tgt["phoenix_used"] = True
                tgt["hp"] = math.ceil(tgt["max_hp"] * 0.5)
                self.ev.append({"k": "cast", "src": tgt["id"], "name": "불사조의 가호!"})
            if tgt["hp"] <= 0:
                self.down(tgt)
        else:
            self.changed.add(tgt["id"])
            if not tgt["aggro"] and src is not None:
                self.aggro(tgt)
            if tgt["hp"] <= 0:
                self.kill(tgt)
        return dealt

    def heal(self, tgt, amt, src=None, quiet=False):
        if src is not None and src["id"] in self.players:
            amt = round(amt * (1 + src.get("heal_pct", 0)))
            if "dawn" in src.get("fx", ()):
                tgt["shield"] += round(amt * 0.3)
        tgt["hp"] = min(tgt["max_hp"], tgt["hp"] + amt)
        if not quiet:
            self.ev.append({"k": "heal", "tgt": tgt["id"], "v": amt})
        if tgt["id"] not in self.players:
            self.changed.add(tgt["id"])

    def down(self, p):
        p["downed"] = True
        p["respawn_at"] = self.time + RESPAWN_SEC
        p["wps"], p["target"] = [], None
        p["status"], p["shield"] = {}, 0
        self.ev.append({"k": "die", "tgt": p["id"]})
        self.add_log(f"{p['name']}이(가) 쓰러졌다! ({RESPAWN_SEC}초 후 부활)")
        if not self.active_players():
            self.phase = "gameover"
            self.notice = f"파티가 전멸했다... {self.floor}층에서 모험이 끝났다."
            self.add_log(self.notice)

    def revive(self, p, ratio):
        p["downed"] = False
        p["hp"] = math.ceil(p["max_hp"] * ratio)
        p["last_hit"] = self.time
        self.ev.append({"k": "revive", "tgt": p["id"]})
        self.dirty = True

    def kill(self, m, silent=False):
        if m not in self.monsters:
            return
        self.monsters.remove(m)
        self.ev.append({"k": "die", "tgt": m["id"]})
        self.dirty = True
        for p in self.players.values():
            if p["target"] == m["id"]:
                p["target"] = None
        d = ENEMIES[m["kind"]]
        if d.get("on_death") == "split":
            for _ in range(2):
                x, y = self.free_spot_near(m["x"], m["y"], 1)
                self.spawn("slimelet", x, y, aggro=True)
        if d.get("on_death") == "reassemble" and not m["reassembled"]:
            self.pending.append({"at": self.time + 4, "kind": m["kind"], "x": m["x"], "y": m["y"],
                                 "owner": m["owner"]})
            self.ev.append({"k": "cast", "src": m["id"], "name": "뼈가 흩어졌다..."})
            return
        if silent:
            return
        f, n = self.floor, len(self.players)
        summon = m["owner"] is not None or d.get("no_loot")
        xp = XP[m["tier"]] * (1 + 0.15 * (f - 1)) / n * (1 + 0.15 * (n - 1)) * (0.3 if summon else 1)
        gold = 0 if summon else round(GOLD[m["tier"]] * (1 + 0.2 * (f - 1)) * self.rng.uniform(0.7, 1.3))
        for p in self.players.values():
            self.give_xp(p, max(1, round(xp)))
            p["gold"] += gold
            self.touch(p)
        if summon:
            return
        loot = []
        if m["tier"] == "boss":
            for _ in self.players:
                loot += [self.make_item(min_rarity=2), "potion"]
            self.stairs["locked"] = False
            for p in self.players.values():
                if p["downed"]:
                    self.revive(p, 1.0)
                p["hp"] = p["max_hp"]
            for o in list(self.monsters):
                if o["owner"] == m["id"]:
                    self.kill(o, silent=True)
            self.notice = f"{m['name']}을(를) 쓰러뜨렸다! 계단이 열렸다. (다음은 마을)"
            self.add_log(self.notice)
        elif m["tier"] == "elite":
            loot.append(self.make_item(min_rarity=1))
            if self.rng.random() < 0.5:
                loot.append("potion")
            self.add_log(f"{m['name']} 처치!")
        else:
            if self.rng.random() < 0.22:
                loot.append(self.make_item())
            if self.rng.random() < 0.1:
                loot.append("potion")
        self.drop_near(m["x"], m["y"], loot)

    def give_xp(self, p, xp):
        p["xp"] += xp
        while p["xp"] >= xp_to_next(p["level"]):
            p["xp"] -= xp_to_next(p["level"])
            p["level"] += 1
            p["sp"] += 1
            recalc(p)
            if not p["downed"]:
                p["hp"] = min(p["max_hp"], p["hp"] + math.ceil(p["max_hp"] * 0.3))
            self.add_log(f"{p['name']} 레벨 업! Lv.{p['level']} (스킬 포인트 +1)")
            self.ev.append({"k": "lvl", "tgt": p["id"]})

    def aggro(self, m):
        m["aggro"], m["returning"] = True, False
        for o in self.monsters:
            if not o["aggro"] and abs(o["x"] - m["x"]) <= PACK_RANGE and abs(o["y"] - m["y"]) <= PACK_RANGE:
                o["aggro"], o["returning"] = True, False
                self.changed.add(o["id"])
        self.changed.add(m["id"])

    # ---------- 틱 ----------
    def tick(self):
        """TICK초마다 호출. 전체 상태가 필요하면 'state', 변화만 보내면 'tk', 없으면 None."""
        self.ticks += 1
        self.time += TICK
        if self.phase != "explore":
            return None
        moved = False
        for p in list(self.players.values()):
            moved |= self.player_tick(p)
        for m in list(self.monsters):
            if self.phase != "explore":
                break
            self.monster_tick(m)
        if self.phase == "explore":
            self.separate()
            self.field_tick()
            self.zone_tick()
            for s in [s for s in self.pending if s["at"] <= self.time]:
                self.pending.remove(s)
                m = self.spawn(s["kind"], s["x"], s["y"], aggro=True, owner=s["owner"], hp_ratio=0.5)
                m["reassembled"] = True
                self.ev.append({"k": "cast", "src": m["id"], "name": "재조립!"})
        if self.phase != "explore" or self.check_stairs() or self.dirty:
            return "state"
        if moved or self.ev or self.changed or self.zones or self.fields:
            return "tk"
        return None

    def follow_path(self, e, speed):
        """웨이포인트를 따라 speed(이번 틱 이동거리)만큼 이동. 움직였으면 True."""
        budget = speed
        ox, oy = e["x"], e["y"]
        while budget > 1e-6 and e["wps"]:
            # 다음 웨이포인트가 직선으로 보이면 건너뛰어 부드럽게
            while len(e["wps"]) > 1 and self.dg.clear_line(e["x"], e["y"], *e["wps"][1]):
                e["wps"].pop(0)
            wx, wy = e["wps"][0]
            dx, dy = wx - e["x"], wy - e["y"]
            d = math.hypot(dx, dy)
            if d <= budget:
                e["x"], e["y"] = self.dg.slide(e["x"], e["y"], dx, dy)
                e["wps"].pop(0)
                budget -= d
            else:
                e["x"], e["y"] = self.dg.slide(e["x"], e["y"], dx / d * budget, dy / d * budget)
                budget = 0
        moved = abs(e["x"] - ox) + abs(e["y"] - oy)
        if e["wps"] and moved < speed * 0.2:
            e["stuck"] = e.get("stuck", 0) + 1
            if e["stuck"] > 4:  # 벽에 걸렸으면 경로 재계산
                goal = e["wps"][-1]
                e["stuck"] = 0
                if not self.set_path(e, *goal):
                    e["wps"] = []
        else:
            e["stuck"] = 0
        return moved > 1e-6

    def player_tick(self, p):
        if p["downed"]:
            if self.time >= p["respawn_at"]:
                buddies = [q for q in self.active_players() if q is not p]
                if buddies:
                    q = self.rng.choice(buddies)
                    p["x"], p["y"] = q["x"], q["y"]
                self.revive(p, 0.3)
                self.add_log(f"{p['name']}이(가) 다시 일어났다.")
            return False
        if self.time - p["last_hit"] > REGEN_DELAY and p["hp"] < p["max_hp"]:
            p["regen"] += p["max_hp"] * REGEN_RATE * TICK * (3 if self.town else 1)
            if p["regen"] >= 1:
                p["hp"] = min(p["max_hp"], p["hp"] + int(p["regen"]))
                p["regen"] -= int(p["regen"])
        p["atk_cd"] -= TICK
        st = p["status"]
        for k in [k for k, v in st.items() if (v[1] if isinstance(v, list) else v) <= self.time]:
            del st[k]

        basic = CLASSES[p["cls"]]["basic"]
        tgt = self.monster(p["target"]) if p["target"] else None
        if p["target"] and not tgt:
            p["target"] = None
        if not tgt and not p["wps"]:
            near = [m for m in self.monsters if m["aggro"] and self.in_range(p, m, basic["range"])]
            if near:
                tgt = min(near, key=lambda m: dist(m, p))
                p["target"] = tgt["id"]
        if tgt:
            if self.in_range(p, tgt, basic["range"]):
                p["wps"] = []
                if p["atk_cd"] <= 0:
                    a_s = p["as"] + (0.4 if "berserk" in p["fx"] and p["hp"] < p["max_hp"] / 2 else 0)
                    p["atk_cd"] = PLAYER_ATTACK_BASE / (1 + p["spd"] * 0.05) / (1 + a_s)
                    self.ev.append({"k": "shot", "src": p["id"], "tgt": tgt["id"], "skill": "basic"})
                    self.hit(p, tgt, basic["mult"])
                    if "inferno" in p["fx"]:
                        self.ev.append({"k": "aoe", "x": tgt["x"], "y": tgt["y"], "r": 1.2, "c": "#ff7a2f"})
                        for m in [m for m in self.monsters if m is not tgt and dist(m, tgt) <= 1.4]:
                            self.hit(p, m, basic["mult"] * 0.5)
            elif self.ticks >= p.get("repath", 0):
                p["repath"] = self.ticks + 4
                if not self.set_path(p, tgt["x"], tgt["y"]):
                    p["target"], p["wps"] = None, []
        moved = False
        if p["wps"]:
            moved = self.follow_path(p, PLAYER_SPEED * (1 + p["ms"]) * TICK)
            if moved:
                self.on_move(p)
        # 상점/대장장이
        if p["want_npc"]:
            o = next((o for o in self.objects if o["id"] == p["want_npc"]), None)
            if o and dist_xy(p, o["x"] + 0.5, o["y"] + 0.5) <= NPC_RANGE:
                p["npc"], p["want_npc"], p["wps"] = o["kind"], None, []
                self.touch(p)
        elif p["npc"]:
            o = next((o for o in self.objects if o["kind"] == p["npc"]), None)
            if not o or dist_xy(p, o["x"] + 0.5, o["y"] + 0.5) > NPC_RANGE + 1:
                p["npc"] = None
                self.touch(p)
        return moved

    def on_move(self, p):
        tx, ty = tile(p)
        if p["prompt"]:
            o = next((o for o in self.objects if o["id"] == p["prompt"]), None)
            if not o or (o["x"], o["y"]) != (tx, ty):
                p["prompt"] = None
                self.touch(p)
        for g in [g for g in self.items if dist(g, p) <= PICKUP_RANGE and g.get("dropped_by") != p["id"]]:
            if g.get("potion"):
                if p["potions"] >= POTION_MAX:
                    continue
                p["potions"] += 1
            else:
                if len(p["inv"]) >= INVENTORY_SIZE:
                    self.tell(p["id"], "가방이 가득 찼습니다.")
                    continue
                p["inv"].append(g["item"])
                self.add_log(f"{p['name']}: [{g['item']['name']}] 획득")
            self.items.remove(g)
            self.touch(p)
            self.dirty = True
        for g in self.items:
            if g.get("dropped_by") == p["id"] and dist(g, p) > 1.2:
                g.pop("dropped_by")
        for o in self.objects:
            if o["used"] or (o["x"], o["y"]) != (tx, ty):
                continue
            if o["kind"] == "chest":
                o["used"] = True
                self.dirty = True
                gold = round(10 * (1 + 0.2 * self.floor) * self.rng.uniform(0.6, 1.4))
                for q in self.players.values():
                    q["gold"] += gold
                    self.touch(q)
                if self.floor >= 2 and self.rng.random() < 0.15:
                    self.add_log("상자가 이빨을 드러냈다! 미믹이다!")
                    x, y = self.free_spot_near(p["x"], p["y"], 1)
                    self.aggro(self.spawn("mimic", x, y, aggro=True))
                    continue
                loot = [self.make_item()] + (["potion"] if self.rng.random() < 0.4 else [])
                self.drop_near(o["x"], o["y"], loot)
                self.add_log(f"{p['name']}이(가) 상자를 열었다. (+{gold}G)")
            elif o["kind"] == "fountain":
                o["used"] = True
                self.dirty = True
                for q in self.active_players():
                    q["hp"] = min(q["max_hp"], q["hp"] + math.ceil(q["max_hp"] * 0.5))
                self.add_log(f"{p['name']}이(가) 샘물을 떴다. 파티 전원 체력 회복!")
            elif o["kind"] == "altar" and p["prompt"] != o["id"]:
                p["prompt"] = o["id"]
                self.touch(p)
        if self.stairs and (tx, ty) == (self.stairs["x"], self.stairs["y"]) and self.stairs["locked"]:
            if self.ticks % 20 == 0:
                self.tell(p["id"], "보스를 쓰러뜨려야 계단이 열립니다.")

    # ---------- 몬스터 ----------
    def monster_tick(self, m):
        st = m["status"]
        if self.ticks % 10 == 0:
            for dot in ("poison", "burn"):
                if dot in st:
                    dmg, until = st[dot]
                    if until <= self.time:
                        del st[dot]
                        self.changed.add(m["id"])
                    else:
                        self.damage(m, dmg, dot)
                        if m["hp"] <= 0:
                            return
        m["atk_cd"] -= TICK
        if m["fuse"] is not None:
            if self.time >= m["fuse"]:
                self.kill(m)
            return
        if st.get("stun", 0) > self.time:
            return
        if "stun" in st:
            del st["stun"]
            self.changed.add(m["id"])
        slow = st.get("slow")
        speed_mult = slow[0] if slow and slow[1] > self.time else 1.0
        if slow and slow[1] <= self.time:
            del st["slow"]
        if m["charge"]:
            self.charge_tick(m)
            return
        players = self.active_players()

        if not m["aggro"]:
            if m["returning"]:
                if self.ticks >= m["repath"] or not m["wps"]:
                    m["repath"] = self.ticks + 10
                    self.set_path(m, *m["home"])
                if self.follow_path(m, m["speed"] * 1.5 * TICK):
                    self.changed.add(m["id"])
                if dist_xy(m, *m["home"]) < 0.5 or not m["wps"]:
                    m["returning"] = False
                return
            if self.ticks % 3 == 0:
                for p in players:
                    if abs(p["x"] - m["x"]) <= AGGRO_RANGE and abs(p["y"] - m["y"]) <= AGGRO_RANGE \
                            and dist(p, m) <= AGGRO_RANGE and self.los(m, p):
                        self.aggro(m)
                        break
            return

        if dist_xy(m, *m["home"]) > LEASH and m["tier"] != "boss" or not players:
            m.update({"aggro": False, "returning": True, "hp": m["max_hp"], "status": {}, "wps": []})
            self.changed.add(m["id"])
            return

        tgt = None
        if m["taunt_until"] > self.time:
            tgt = self.players.get(m["taunt_by"])
            if tgt and tgt["downed"]:
                tgt = None
        if not tgt:
            tgt = min(players, key=lambda p: (dist(p, m), p["hp"]))
        d = dist(m, tgt)

        if self.use_ability(m, tgt, d):
            return
        if d <= m["range"] and (m["range"] < 2 or self.los(m, tgt)):
            m["wps"] = []
            if m["atk_cd"] <= 0:
                m["atk_cd"] = ENEMY_ATTACK_BASE / (1 + m["spd"] * 0.04) * (0.65 if m["enraged"] else 1)
                self.ev.append({"k": "shot", "src": m["id"], "tgt": tgt["id"], "skill": "enemy"})
                self.hit(m, tgt, 1.0)
        else:
            if self.ticks >= m["repath"] or not m["wps"]:
                m["repath"] = self.ticks + 5
                self.set_path(m, tgt["x"], tgt["y"])
            if self.follow_path(m, m["speed"] * speed_mult * TICK):
                self.changed.add(m["id"])

    def separate(self):
        """뭉친 몬스터끼리 살짝 밀어내기."""
        act = [m for m in self.monsters if m["aggro"]]
        for i, a in enumerate(act):
            for b in act[i + 1:]:
                dx, dy = b["x"] - a["x"], b["y"] - a["y"]
                d = math.hypot(dx, dy)
                lim = 0.35 * (a["scale"] + b["scale"])
                if 1e-4 < d < lim:
                    push = (lim - d) * 0.25
                    ux, uy = dx / d * push, dy / d * push
                    a["x"], a["y"] = self.dg.slide(a["x"], a["y"], -ux, -uy)
                    b["x"], b["y"] = self.dg.slide(b["x"], b["y"], ux, uy)
                    self.changed.update((a["id"], b["id"]))

    def use_ability(self, m, tgt, d):
        abilities = ENEMIES[m["kind"]].get("abilities", [])
        ratio = m["hp"] / m["max_hp"]
        for i, ab in enumerate(abilities):
            if ab.get("below") and ratio >= ab["below"]:
                continue
            t = ab["type"]
            if t == "enrage":
                if not m["enraged"]:
                    m["enraged"] = True
                    self.ev.append({"k": "cast", "src": m["id"], "name": "광폭화!"})
                    self.add_log(f"{m['name']}이(가) 광폭해졌다!")
                    self.changed.add(m["id"])
                continue
            if m["ab_cd"][i] > self.time:
                continue
            used = self.ability(m, ab, tgt, d)
            if used:
                m["ab_cd"][i] = self.time + ab["cd"] * (0.7 if m["enraged"] else 1)
                return True
        return False

    def zone(self, m, x, y, r, delay, mult):
        self.zones.append({"x": x, "y": y, "r": r, "at": self.time + delay, "total": delay,
                           "atk": m["atk"], "crit": m["crit"], "mult": mult, "src": m["id"]})

    def ability(self, m, ab, tgt, d):
        t = ab["type"]
        if t == "heal":
            hurt = [o for o in self.monsters if o["hp"] < o["max_hp"] * 0.8 and dist(o, m) <= 6]
            if not hurt:
                return False
            o = min(hurt, key=lambda o: o["hp"] / o["max_hp"])
            self.ev.append({"k": "shot", "src": m["id"], "tgt": o["id"], "skill": "heal"})
            self.heal(o, round(ab["amount"] * m["heal_mult"]))
            return True
        if t == "explode":
            if d > 1.4:
                return False
            self.zone(m, m["x"], m["y"], ab["radius"], ab["delay"], ab["mult"])
            m["fuse"] = self.time + ab["delay"]
            self.ev.append({"k": "cast", "src": m["id"], "name": "치익...!"})
            return True
        if t == "charge":
            if not (ab["min"] <= d <= ab["max"]) or not self.los(m, tgt):
                return False
            m["charge"] = {"phase": "wind", "t": self.time + 0.5, "tx": tgt["x"], "ty": tgt["y"],
                           "mult": ab["mult"], "hit": False}
            m["wps"] = []
            self.ev.append({"k": "cast", "src": m["id"], "name": "돌진!"})
            self.ev.append({"k": "line", "x0": m["x"], "y0": m["y"], "x": tgt["x"], "y": tgt["y"], "t": 0.5})
            return True
        if t == "slam":
            if d > ab["radius"] + 0.5:
                return False
            self.zone(m, m["x"], m["y"], ab["radius"], ab["delay"], ab["mult"])
            return True
        if t == "zones_players":
            for p in self.active_players():
                if dist(p, m) <= 10:
                    self.zone(m, p["x"], p["y"], ab["radius"], ab["delay"], ab["mult"])
            self.ev.append({"k": "cast", "src": m["id"], "name": "저주의 낙인"})
            return True
        if t == "breath":
            if d > ab["length"]:
                return False
            ux, uy = (tgt["x"] - m["x"]) / max(d, 0.01), (tgt["y"] - m["y"]) / max(d, 0.01)
            for i in range(1, ab["length"] + 1):
                self.zone(m, m["x"] + ux * i * 1.1, m["y"] + uy * i * 1.1, ab["radius"],
                          ab["delay"] + i * 0.05, ab["mult"])
            self.ev.append({"k": "cast", "src": m["id"], "name": "화염 숨결!"})
            return True
        if t == "rain":
            ps = self.active_players()
            for i in range(ab["count"]):
                p = self.rng.choice(ps)
                x, y = p["x"] + self.rng.uniform(-2.5, 2.5), p["y"] + self.rng.uniform(-2.5, 2.5)
                self.zone(m, x, y, ab["radius"], ab["delay"] + i * 0.2, ab["mult"])
            self.ev.append({"k": "cast", "src": m["id"], "name": "불의 비!"})
            return True
        if t == "summon":
            alive = sum(1 for o in self.monsters if o["owner"] == m["id"]) + \
                sum(1 for s in self.pending if s["owner"] == m["id"])
            if alive >= ab["max"]:
                return False
            for k in ab["kinds"][:ab["max"] - alive]:
                x, y = self.free_spot_near(m["x"], m["y"], 2)
                self.spawn(k, x, y, aggro=True, owner=m["id"])
            self.ev.append({"k": "cast", "src": m["id"], "name": "소환!"})
            self.ev.append({"k": "aoe", "x": m["x"], "y": m["y"], "r": 1.5, "c": "#a46bff"})
            return True
        if t == "teleport":
            spots = [t_ for t_, dd in self.dg.distances(tile(m), limit=7).items() if dd >= 4]
            if not spots:
                return False
            tx, ty = self.rng.choice(spots)
            self.ev.append({"k": "dash", "src": m["id"], "x0": m["x"], "y0": m["y"], "x": tx + 0.5, "y": ty + 0.5, "s": "tp"})
            m["x"], m["y"], m["wps"] = tx + 0.5, ty + 0.5, []
            self.changed.add(m["id"])
            return True
        return False

    def charge_tick(self, m):
        c = m["charge"]
        if c["phase"] == "wind":
            if self.time >= c["t"]:
                c["phase"], c["t"] = "dash", self.time + 1.0
            return
        dx, dy = c["tx"] - m["x"], c["ty"] - m["y"]
        d = math.hypot(dx, dy)
        step = 12 * TICK
        if d > 0.05:
            nx, ny = self.dg.slide(m["x"], m["y"], dx / d * min(step, d), dy / d * min(step, d))
            blocked = abs(nx - m["x"]) + abs(ny - m["y"]) < 0.05
            m["x"], m["y"] = nx, ny
        else:
            blocked = True
        self.changed.add(m["id"])
        for p in self.active_players():
            if not c["hit"] and dist(p, m) <= 1.0:
                c["hit"] = True
                self.hit(m, p, c["mult"])
        if c["hit"] or blocked or d <= step or self.time >= c["t"]:
            m["charge"] = None
            m["atk_cd"] = max(m["atk_cd"], 0.8)

    def zone_tick(self):
        for z in [z for z in self.zones if z["at"] <= self.time]:
            self.zones.remove(z)
            self.ev.append({"k": "aoe", "x": z["x"], "y": z["y"], "r": z["r"], "c": "#ff3b2f"})
            src = {"id": z["src"], "atk": z["atk"], "crit": z["crit"], "crit_dmg": 0.5, "hp": 1,
                   "status": {}, "lifesteal": 0}
            for p in self.active_players():
                if dist_xy(p, z["x"], z["y"]) <= z["r"] + 0.25:
                    self.hit(src, p, z["mult"], "zone")
                    if self.phase != "explore":
                        return

    def field_tick(self):
        for f in list(self.fields):
            owner = self.players.get(f["owner"])
            if self.time >= f["until"] or not owner:
                self.fields.remove(f)
                continue
            if f["follow"]:
                if owner["downed"]:
                    self.fields.remove(f)
                    continue
                f["x"], f["y"] = owner["x"], owner["y"]
            if self.time + 1e-6 < f["next"]:
                continue
            f["next"] += f["interval"]
            for m in [m for m in self.monsters if dist_xy(m, f["x"], f["y"]) <= f["r"] + 0.4]:
                if f["mult"]:
                    self.hit(owner, m, f["mult"])
                if f["slow"] and m["hp"] > 0:
                    m["status"]["slow"] = [f["slow"], self.time + 1.0]
            if f["heal"]:
                for q in self.active_players():
                    if dist_xy(q, f["x"], f["y"]) <= f["r"] + 0.4 and q["hp"] < q["max_hp"]:
                        self.heal(q, max(1, round(owner["atk"] * f["heal"])), owner)

    # ---------- 계단 / 포탈 ----------
    def stairs_gather(self):
        if not self.stairs or self.stairs["locked"]:
            return 0, 0
        ps = [p for p in self.connected() if not p["downed"]]
        sx, sy = self.stairs["x"] + 0.5, self.stairs["y"] + 0.5
        near = [p for p in ps if dist_xy(p, sx, sy) <= 1.6]
        return len(near), len(ps)

    def check_stairs(self):
        near, total = self.stairs_gather()
        if not total or near < total:
            return False
        if self.town:
            self.floor += 1
            self.new_floor()
        elif self.is_boss_floor():
            self.new_town()
        else:
            self.floor += 1
            self.new_floor()
        return True

    # ---------- 직렬화 ----------
    def map_data(self):
        return {"map_id": self.map_id, "w": self.dg.w, "h": self.dg.h, "tiles": self.dg.tiles_str(),
                "town": self.town}

    def flags(self, u):
        st, f, now = u["status"], "", self.time
        if st.get("stun", 0) > now:
            f += "S"
        if "slow" in st:
            f += "W"
        if "poison" in st:
            f += "P"
        if "burn" in st:
            f += "B"
        if st.get("taunt", 0) > now:
            f += "T"
        if "crit_buff" in st:
            f += "X"
        if u.get("aggro"):
            f += "A"
        if u.get("enraged"):
            f += "E"
        if u.get("charge") and u["charge"]["phase"] == "wind":
            f += "C"
        if u.get("fuse") is not None:
            f += "F"
        return f

    def player_row(self, p):
        down = round(max(0.0, p["respawn_at"] - self.time), 1) if p["downed"] else -1
        return [p["id"], round(p["x"], 2), round(p["y"], 2), p["hp"], p["max_hp"], p["shield"], down, self.flags(p)]

    def monster_row(self, m):
        return [m["id"], round(m["x"], 2), round(m["y"], 2), m["hp"], m["max_hp"], self.flags(m)]

    def zone_rows(self):
        return [[round(z["x"], 2), round(z["y"], 2), z["r"], round(1 - (z["at"] - self.time) / z["total"], 2)]
                for z in self.zones]

    def field_rows(self):
        return [[round(f["x"], 2), round(f["y"], 2), f["r"], f["s"]] for f in self.fields]

    def take_tick(self):
        msg = {"now": round(self.time, 2), "p": [self.player_row(p) for p in self.players.values()],
               "m": [self.monster_row(m) for m in self.monsters if m["id"] in self.changed],
               "z": self.zone_rows(), "f": self.field_rows(), "ev": self.ev}
        self.ev, self.changed = [], set()
        return msg

    def state(self):
        near, total = self.stairs_gather()
        self.dirty = False
        msg = {
            "code": self.code, "phase": self.phase, "floor": self.floor, "town": self.town,
            "now": round(self.time, 2), "host": self.host, "best_floor": self.best_floor,
            "notice": self.notice, "map_id": self.map_id,
            "players": [{"id": p["id"], "name": p["name"], "cls": p["cls"], "level": p["level"],
                         "connected": p["connected"], "ready": p["ready"], "row": self.player_row(p)}
                        for p in self.players.values()],
            "monsters": [{"id": m["id"], "kind": m["kind"], "sprite": m["sprite"], "name": m["name"],
                          "tier": m["tier"], "scale": m["scale"], "row": self.monster_row(m)}
                         for m in self.monsters],
            "items": [{"id": g["id"], "x": round(g["x"], 2), "y": round(g["y"], 2), "potion": True}
                      if g.get("potion") else
                      {"id": g["id"], "x": round(g["x"], 2), "y": round(g["y"], 2), "slot": g["item"]["slot"],
                       "rarity": g["item"]["rarity"], "name": g["item"]["name"]} for g in self.items],
            "objects": self.objects,
            "stairs": self.stairs,
            "gather": [near, total],
            "zones": self.zone_rows(),
            "fields": self.field_rows(),
            "ev": self.ev,
            "log": self.log,
        }
        self.ev, self.changed = [], set()
        return msg

    def private(self, pid):
        """해당 플레이어에게만 보내는 정보 (가방, 장비, 스킬 등)."""
        p = self.players[pid]
        data = {k: p[k] for k in ("level", "xp", "sp", "skills", "eq", "inv", "potions", "gold", "cds",
                                  "npc", "prompt", "fx", "sets") + tuple(BASE_STATS)}
        data["xp_next"] = xp_to_next(p["level"])
        if p["npc"] == "shop":
            data["shop"] = [dict(it, price=item_value(it)) for it in self.shop]
            data["potion_price"] = POTION_PRICE + 2 * self.floor
        data["values"] = {it["id"]: item_value(it) // 4 for it in p["inv"]}
        if p["npc"] == "smith":
            data["enhance"] = {it["id"]: [enhance_cost(it), round(enhance_chance(it), 2)]
                               for it in p["inv"] + [i for i in p["eq"].values() if i]}
        return data
