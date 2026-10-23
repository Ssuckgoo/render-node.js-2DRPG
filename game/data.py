"""게임 밸런스 데이터. 숫자 조정은 여기서만 하면 된다.

거리 단위는 타일, 시간 단위는 초.
스킬 target 종류:
  enemy  - 커서 아래(또는 커서에 가장 가까운) 적 하나
  area   - 커서 위치에 범위 공격
  around - 내 주변 범위 공격
  dash   - 커서 쪽으로 돌진 후 착지 지점 범위 공격
  blink  - 커서 위치로 순간이동
  field  - 커서 위치(또는 나를 따라다니는)에 일정 시간 지속되는 장판
  ally   - 커서 아래(또는 체력 가장 낮은) 아군
  allies - 내 주변 아군 전체
  self   - 자신
  dead   - 쓰러진 아군
스킬 "lv"에는 레벨당 증가량을 적는다.
"""

# ---------- 직업 / 스킬 ----------
CLASSES = {
    "warrior": {
        "name": "전사", "hp": 140, "atk": 11, "df": 4, "spd": 3,
        "desc": "튼튼한 근접 탱커. 적을 끌어모으고 버틴다.",
        "basic": {"name": "베기", "range": 1.5, "mult": 1.0},
        "skills": [
            {"id": "cleave", "name": "회전베기", "target": "around", "radius": 1.8, "mult": 1.1,
             "cd": 4, "lv": {"mult": 0.15}, "desc": "주변 적 모두에게 {mult}배 피해"},
            {"id": "charge", "name": "돌진", "target": "dash", "range": 5, "radius": 1.4, "mult": 0.8,
             "stun": 1.0, "cd": 7, "lv": {"mult": 0.15, "cd": -0.4},
             "desc": "커서 쪽으로 돌진, 착지 지점 {mult}배 피해 + {stun}초 기절"},
            {"id": "taunt", "name": "도발", "target": "self", "radius": 6, "taunt": 5, "shield": 25,
             "cd": 12, "lv": {"shield": 12}, "desc": "주변 적을 끌어오고 보호막 {shield}"},
            {"id": "quake", "name": "대지 분쇄", "target": "around", "radius": 3.2, "mult": 2.2,
             "stun": 2.0, "cd": 25, "req": 6, "lv": {"mult": 0.4},
             "desc": "[궁극기] 넓은 범위 {mult}배 피해 + {stun}초 기절"},
        ],
        "passives": [
            {"id": "iron_skin", "name": "강철 피부", "stats": {"df": 2, "max_hp_pct": 0.03},
             "desc": "레벨당 방어력 +2, 최대 체력 +3%"},
            {"id": "bloodlust", "name": "피의 갈증", "stats": {"lifesteal": 0.03},
             "desc": "레벨당 흡혈 +3%"},
            {"id": "frenzy", "name": "전투 광란", "stats": {"as": 0.06},
             "desc": "레벨당 공격 속도 +6%"},
        ],
    },
    "mage": {
        "name": "마법사", "hp": 80, "atk": 14, "df": 1, "spd": 4,
        "desc": "원거리 광역 딜러. 몸이 약하니 거리를 유지하자.",
        "basic": {"name": "화염구", "range": 6, "mult": 1.0},
        "skills": [
            {"id": "meteor", "name": "메테오", "target": "area", "range": 8, "radius": 2, "mult": 1.3,
             "burn": 4, "cd": 8, "lv": {"mult": 0.2}, "desc": "커서 위치 반경 2에 {mult}배 피해 + 화상"},
            {"id": "freeze", "name": "빙결", "target": "enemy", "range": 7, "mult": 0.8, "stun": 2.0,
             "cd": 7, "lv": {"mult": 0.15, "stun": 0.25}, "desc": "적 하나 {mult}배 피해 + {stun}초 빙결"},
            {"id": "blink", "name": "순간이동", "target": "blink", "range": 6, "cd": 8,
             "lv": {"cd": -0.6}, "desc": "커서 위치로 순간이동 (재사용 {cd}초)"},
            {"id": "blizzard", "name": "눈보라", "target": "field", "range": 8, "radius": 3, "duration": 4,
             "mult": 0.45, "slow": 0.5, "cd": 24, "req": 6, "lv": {"mult": 0.1},
             "desc": "[궁극기] 4초간 0.5초마다 {mult}배 피해 + 둔화"},
        ],
        "passives": [
            {"id": "arcane", "name": "마력 증폭", "stats": {"atk": 2}, "desc": "레벨당 공격력 +2"},
            {"id": "focus", "name": "집중", "stats": {"cdr": 0.05}, "desc": "레벨당 재사용 대기시간 -5%"},
            {"id": "pyro", "name": "화염 숙련", "stats": {"burn_pct": 0.25}, "desc": "레벨당 화상 피해 +25%"},
        ],
    },
    "rogue": {
        "name": "도적", "hp": 95, "atk": 13, "df": 2, "spd": 7,
        "desc": "빠른 근접 딜러. 치명타로 순식간에 적을 녹인다.",
        "crit": 0.2,
        "basic": {"name": "찌르기", "range": 1.5, "mult": 1.0},
        "skills": [
            {"id": "backstab", "name": "암습", "target": "enemy", "range": 1.8, "mult": 2.4, "cd": 5,
             "lv": {"mult": 0.35}, "desc": "가까운 적에게 {mult}배 피해"},
            {"id": "poison", "name": "독칼", "target": "enemy", "range": 4, "mult": 0.6, "poison": 6,
             "cd": 6, "lv": {"mult": 0.1}, "desc": "적 하나 {mult}배 피해 + 6초 맹독"},
            {"id": "shadow", "name": "그림자 걸음", "target": "blink", "range": 5, "crit_buff": 0.6,
             "buff_time": 3, "cd": 9, "lv": {"buff_time": 0.5},
             "desc": "커서 위치로 이동 + {buff_time}초간 치명타 +60%"},
            {"id": "bladestorm", "name": "칼날 폭풍", "target": "field", "follow": True, "radius": 2,
             "duration": 1.5, "interval": 0.25, "mult": 0.55, "cd": 22, "req": 6, "lv": {"mult": 0.1},
             "desc": "[궁극기] 1.5초간 주변을 0.25초마다 {mult}배로 베어낸다"},
        ],
        "passives": [
            {"id": "precision", "name": "급소 노리기", "stats": {"crit": 0.04}, "desc": "레벨당 치명타 +4%"},
            {"id": "agility", "name": "날렵함", "stats": {"ms": 0.06, "as": 0.04},
             "desc": "레벨당 이동 속도 +6%, 공격 속도 +4%"},
            {"id": "venom", "name": "맹독 숙련", "stats": {"poison_pct": 0.25}, "desc": "레벨당 독 피해 +25%"},
        ],
    },
    "priest": {
        "name": "사제", "hp": 90, "atk": 9, "df": 2, "spd": 4,
        "desc": "치유와 부활. 파티의 생명줄.",
        "basic": {"name": "징벌", "range": 5, "mult": 0.9},
        "skills": [
            {"id": "heal", "name": "치유", "target": "ally", "range": 7, "heal": 3.0, "cd": 3,
             "lv": {"heal": 0.6}, "desc": "커서 아래(없으면 체력 낮은) 아군을 공격력 {heal}배 회복"},
            {"id": "bless", "name": "축복", "target": "allies", "radius": 7, "heal": 1.5, "shield": 12,
             "cd": 12, "lv": {"heal": 0.3, "shield": 6}, "desc": "주변 아군 {heal}배 회복 + 보호막 {shield}"},
            {"id": "revive", "name": "부활", "target": "dead", "range": 4, "ratio": 0.4, "cd": 20,
             "lv": {"ratio": 0.1, "cd": -2}, "desc": "가까이 쓰러진 아군을 체력 {ratio}로 즉시 부활"},
            {"id": "holylight", "name": "신성한 빛", "target": "field", "range": 8, "radius": 3,
             "duration": 5, "mult": 0.4, "heal": 0.5, "cd": 25, "req": 6, "lv": {"mult": 0.1, "heal": 0.1},
             "desc": "[궁극기] 5초간 아군 회복 + 적에게 {mult}배 피해"},
        ],
        "passives": [
            {"id": "faith", "name": "신앙", "stats": {"heal_pct": 0.1}, "desc": "레벨당 치유량 +10%"},
            {"id": "guardian", "name": "수호", "stats": {"df": 2, "max_hp": 6}, "desc": "레벨당 방어력 +2, 최대 체력 +6"},
            {"id": "wrath", "name": "신의 분노", "stats": {"atk": 2}, "desc": "레벨당 공격력 +2"},
        ],
    },
}
SKILL_MAX = 5
SKILL_KEYS = ["Q", "W", "E", "R"]

POTION_HEAL = 0.4
POTION_CD = 2
POTION_MAX = 10

PLAYER_ATTACK_BASE = 1.1   # 기본 공격 간격(초) = BASE / (1 + spd*0.05) / (1 + 공격속도)
ENEMY_ATTACK_BASE = 1.15
PLAYER_SPEED = 4.2         # 초당 타일
RESPAWN_SEC = 15

# ---------- 몬스터 ----------
# speed: 초당 타일, range: 공격 사거리
# abilities: 특수 능력 (engine.Game.use_ability 참고)
#   below: 체력 비율이 이 값 아래일 때만 사용
ENEMIES = {
    "slime":    {"name": "슬라임", "hp": 32, "atk": 6, "df": 0, "spd": 2, "speed": 1.6,
                 "on_death": "split"},
    "slimelet": {"name": "꼬마 슬라임", "hp": 12, "atk": 4, "df": 0, "spd": 4, "speed": 2.4, "scale": 0.7,
                 "sprite": "slime", "no_loot": True},
    "bat":      {"name": "박쥐", "hp": 20, "atk": 6, "df": 0, "spd": 8, "speed": 4.0},
    "goblin":   {"name": "고블린", "hp": 36, "atk": 8, "df": 1, "spd": 5, "speed": 3.0},
    "archer":   {"name": "고블린 궁수", "hp": 26, "atk": 7, "df": 0, "spd": 4, "speed": 2.6, "range": 5,
                 "projectile": "#d6b36a"},
    "skeleton": {"name": "해골병사", "hp": 42, "atk": 9, "df": 3, "spd": 3, "speed": 2.3,
                 "on_death": "reassemble"},
    "cultist":  {"name": "광신도", "hp": 34, "atk": 8, "df": 1, "spd": 4, "speed": 2.4, "range": 4.5,
                 "projectile": "#c56bff",
                 "abilities": [{"type": "heal", "cd": 6, "amount": 18}]},
    "imp":      {"name": "폭탄 임프", "hp": 22, "atk": 15, "df": 0, "spd": 6, "speed": 3.6,
                 "abilities": [{"type": "explode", "cd": 0, "radius": 1.6, "delay": 0.8, "mult": 1.6}]},
    "orc":      {"name": "오크", "hp": 70, "atk": 12, "df": 2, "spd": 2, "speed": 2.3,
                 "abilities": [{"type": "charge", "cd": 7, "min": 3, "max": 7, "mult": 1.6}]},
    # 엘리트 (체력은 1인 기준, 인원수에 비례해 증가)
    "golem":    {"name": "골렘", "hp": 120, "atk": 13, "df": 5, "spd": 1, "speed": 1.6, "elite": True,
                 "abilities": [{"type": "slam", "cd": 6, "radius": 2, "delay": 1.1, "mult": 1.4}]},
    "vampire":  {"name": "뱀파이어", "hp": 95, "atk": 12, "df": 3, "spd": 6, "speed": 3.2, "elite": True,
                 "lifesteal": 0.4,
                 "abilities": [{"type": "summon", "cd": 12, "kinds": ["bat", "bat"], "max": 4}]},
    "necro":    {"name": "강령술사", "hp": 80, "atk": 10, "df": 2, "spd": 4, "speed": 2.2, "elite": True,
                 "range": 5, "projectile": "#7fffd4",
                 "abilities": [{"type": "summon", "cd": 10, "kinds": ["skeleton", "skeleton"], "max": 4}]},
    "mimic":    {"name": "미믹", "hp": 85, "atk": 12, "df": 2, "spd": 5, "speed": 3.0, "elite": True,
                 "abilities": [{"type": "slam", "cd": 7, "radius": 1.6, "delay": 0.9, "mult": 1.3}]},
    # 보스
    "goblin_king": {"name": "고블린 왕", "hp": 240, "atk": 12, "df": 3, "spd": 4, "speed": 2.4, "boss": True,
                    "abilities": [
                        {"type": "slam", "cd": 7, "radius": 2.4, "delay": 1.2, "mult": 1.6},
                        {"type": "summon", "cd": 14, "kinds": ["goblin", "archer"], "max": 4},
                        {"type": "enrage", "below": 0.5},
                        {"type": "charge", "cd": 9, "min": 3, "max": 8, "mult": 1.5, "below": 0.5},
                    ]},
    "lich":     {"name": "리치", "hp": 300, "atk": 14, "df": 4, "spd": 5, "speed": 2.2, "boss": True,
                 "range": 5.5, "projectile": "#7fffd4",
                 "abilities": [
                     {"type": "zones_players", "cd": 6, "radius": 1.4, "delay": 1.2, "mult": 1.3},
                     {"type": "summon", "cd": 15, "kinds": ["skeleton", "skeleton", "skeleton"], "max": 5},
                     {"type": "enrage", "below": 0.5},
                     {"type": "teleport", "cd": 8, "below": 0.5},
                     {"type": "slam", "cd": 9, "radius": 3, "delay": 1.4, "mult": 1.5, "below": 0.5},
                 ]},
    "dragon":   {"name": "드래곤", "hp": 380, "atk": 17, "df": 6, "spd": 3, "speed": 2.0, "boss": True,
                 "range": 2, "scale": 2.5,
                 "abilities": [
                     {"type": "breath", "cd": 6, "length": 6, "radius": 1.1, "delay": 1.0, "mult": 1.4},
                     {"type": "slam", "cd": 8, "radius": 2.6, "delay": 1.2, "mult": 1.5},
                     {"type": "enrage", "below": 0.5},
                     {"type": "rain", "cd": 10, "count": 7, "radius": 1.3, "delay": 1.3, "mult": 1.2,
                      "below": 0.5},
                 ]},
}

ENEMY_POOLS = [
    (1, ["slime", "bat", "goblin", "goblin"]),
    (2, ["goblin", "archer", "skeleton", "bat", "slime"]),
    (4, ["skeleton", "cultist", "archer", "imp", "goblin"]),
    (6, ["orc", "cultist", "skeleton", "imp", "archer"]),
    (9, ["orc", "cultist", "imp", "archer", "skeleton"]),
]
ELITES = ["golem", "vampire", "necro"]
BOSSES = ["goblin_king", "lich", "dragon"]  # 3, 6, 9층. 이후 반복하며 강해짐
BOSS_EVERY = 3

XP = {"normal": 6, "elite": 25, "boss": 70}
GOLD = {"normal": 3, "elite": 15, "boss": 60}
LEVEL_UP = {"max_hp": 8, "atk": 1}


def xp_to_next(level):
    return 20 + 15 * (level - 1)


# ---------- 장비 ----------
SLOTS = ["weapon", "helmet", "armor", "gloves", "boots", "amulet", "ring1", "ring2"]
SLOT_NAMES = {"weapon": "무기", "helmet": "투구", "armor": "갑옷", "gloves": "장갑", "boots": "신발",
              "amulet": "목걸이", "ring": "반지", "ring1": "반지", "ring2": "반지"}
INVENTORY_SIZE = 40

RARITIES = [
    {"name": "일반", "color": "#d6d0e0", "mult": 1.0, "affix": 0, "w": 60},
    {"name": "희귀", "color": "#5b9cff", "mult": 1.35, "affix": 1, "w": 28},
    {"name": "영웅", "color": "#c06bff", "mult": 1.75, "affix": 2, "w": 9},
    {"name": "전설", "color": "#ff9f1c", "mult": 2.2, "affix": 2, "w": 1.5},
    {"name": "세트", "color": "#4fe07a", "mult": 1.8, "affix": 1, "w": 1.5},
]

WEAPON_BASES = {
    "warrior": ["대검", "도끼", "철퇴"],
    "mage": ["지팡이", "마법봉"],
    "rogue": ["단검", "쌍검"],
    "priest": ["홀", "성서"],
}
ITEM_BASES = {
    "helmet": ["가죽 모자", "철 투구", "두건", "왕관"],
    "armor": ["가죽 갑옷", "사슬 갑옷", "판금 갑옷", "로브"],
    "gloves": ["가죽 장갑", "건틀릿", "손목 보호대"],
    "boots": ["가죽 장화", "철 장화", "여행자 신발"],
    "amulet": ["목걸이", "펜던트", "부적"],
    "ring": ["반지", "인장 반지"],
}
ITEM_PREFIX = [
    ["낡은", "평범한", "투박한"],
    ["단단한", "예리한", "빛나는"],
    ["용사의", "저주받은", "달빛"],
]

STAT_NAMES = {
    "atk": "공격력", "df": "방어력", "max_hp": "최대 체력", "spd": "민첩",
    "crit": "치명타 확률", "crit_dmg": "치명타 피해", "lifesteal": "흡혈", "thorns": "가시",
    "as": "공격 속도", "ms": "이동 속도", "cdr": "재사용 감소", "dr": "받는 피해 감소",
    "max_hp_pct": "최대 체력", "heal_pct": "치유량", "burn_pct": "화상 피해", "poison_pct": "독 피해",
}
PCT_STATS = {"crit", "crit_dmg", "lifesteal", "as", "ms", "cdr", "dr", "max_hp_pct", "heal_pct",
             "burn_pct", "poison_pct"}

# 부위별 주능력: (스탯, 1층 값, 층당 증가)
MAIN_STATS = {
    "weapon": [("atk", 3, 1.0)],
    "helmet": [("df", 0.6, 0.2), ("max_hp", 5, 1.5)],
    "armor": [("df", 1.2, 0.35), ("max_hp", 8, 2.5)],
    "gloves": [("atk", 1, 0.35)],
    "boots": [("ms", 0.05, 0.002), ("df", 0.4, 0.15)],
    "amulet": [("max_hp", 6, 2)],
    "ring": [],
}
# 추가 옵션 후보: (스탯, 1층 값, 층당 증가)
AFFIXES = [
    ("atk", 1, 0.35), ("df", 1, 0.2), ("max_hp", 8, 2), ("crit", 0.03, 0.002),
    ("crit_dmg", 0.12, 0.01), ("lifesteal", 0.03, 0.002), ("thorns", 2, 0.6),
    ("as", 0.05, 0.003), ("ms", 0.04, 0.002), ("cdr", 0.04, 0.002),
]

# 전설 고유 장비: 고정 이름 + 특수 효과. stats 값은 같은 부위 주능력 대비 배율(퍼센트 스탯은 고정값)
UNIQUES = [
    {"id": "thunder", "name": "천둥의 망치", "slot": "weapon", "cls": "warrior",
     "stats": {"atk": 1.3}, "effect": "공격 시 20% 확률로 주변 적 3명에게 연쇄 번개 (80% 피해)"},
    {"id": "inferno", "name": "지옥불 지팡이", "slot": "weapon", "cls": "mage",
     "stats": {"atk": 1.3}, "effect": "기본 공격이 폭발해 주변에 50% 피해"},
    {"id": "fang", "name": "그림자 송곳니", "slot": "weapon", "cls": "rogue",
     "stats": {"atk": 1.2, "crit": 0.08}, "effect": "치명타 시 최대 체력 3% 회복, 치명타 피해 +25%"},
    {"id": "dawn", "name": "새벽의 홀", "slot": "weapon", "cls": "priest",
     "stats": {"atk": 1.2}, "effect": "치유한 양의 30%만큼 보호막 부여"},
    {"id": "windwalk", "name": "바람걸음 장화", "slot": "boots", "stats": {"ms": 0.25},
     "effect": "이동 속도 +25%"},
    {"id": "thorncrown", "name": "가시 왕관", "slot": "helmet", "stats": {"df": 1.0},
     "effect": "받은 피해의 25%를 공격자에게 반사"},
    {"id": "berserk", "name": "광전사의 손아귀", "slot": "gloves", "stats": {"atk": 1.0},
     "effect": "체력 50% 이하일 때 공격 속도 +40%"},
    {"id": "phoenix", "name": "불사조 깃털", "slot": "amulet", "stats": {"max_hp": 1.0},
     "effect": "층마다 1회, 쓰러질 피해를 받으면 체력 50%로 되살아남"},
    {"id": "arcring", "name": "마력의 고리", "slot": "ring", "stats": {"cdr": 0.2},
     "effect": "재사용 대기시간 -20%"},
    {"id": "frostheart", "name": "얼음 심장", "slot": "armor", "stats": {"df": 1.0, "max_hp": 1.0},
     "effect": "피격 시 20% 확률로 공격자를 1.5초 빙결"},
]

# 세트 장비 (투구/갑옷/장갑/신발)
SETS = {
    "guardian": {"name": "수호자의", "pieces": ["helmet", "armor", "gloves", "boots"],
                 "bonus": {2: {"max_hp_pct": 0.15}, 4: {"dr": 0.15}},
                 "desc": {2: "최대 체력 +15%", 4: "받는 피해 -15%"}},
    "hunter": {"name": "그림자 사냥꾼의", "pieces": ["helmet", "armor", "gloves", "boots"],
               "bonus": {2: {"crit": 0.1}, 4: {"crit_dmg": 0.5, "ms": 0.1}},
               "desc": {2: "치명타 확률 +10%", 4: "치명타 피해 +50%, 이동 속도 +10%"}},
}

# ---------- 마을 ----------
POTION_PRICE = 20
ENHANCE_MAX = 10
SHOP_SIZE = 10

# 맵 오브젝트 설명 (클라이언트 툴팁용)
OBJECTS = {
    "chest": "상자 — 밟으면 열린다",
    "fountain": "회복의 샘 — 파티 전원 체력 50% 회복 (1회)",
    "altar": "피의 제단 — 최대 체력을 바치고 공격력을 얻는다",
    "shop": "상인 — 장비와 물약을 사고판다",
    "smith": "대장장이 — 장비를 강화한다",
    "portal": "포탈 — 파티 전원이 모이면 다음 층으로",
}
