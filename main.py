import asyncio
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from game.data import (CLASSES, ENHANCE_MAX, OBJECTS, PCT_STATS, POTION_MAX, RARITIES, SETS,
                       SKILL_MAX, SLOT_NAMES, SLOTS, STAT_NAMES, UNIQUES)
from game.engine import TICK, Game, GameError

STATIC = Path(__file__).parent / "static"
MAX_ROOMS = 100
ROOM_IDLE_SEC = 30 * 60
CODE_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


class Room:
    def __init__(self, code):
        self.game = Game(code)
        self.lock = asyncio.Lock()
        self.sockets = {}   # pid -> WebSocket
        self.tokens = {}    # 비밀 토큰 -> pid (재접속용)
        self.last_active = time.time()
        self.task = None

    async def send(self, ws, msg):
        try:
            await ws.send_json(msg)
        except Exception:
            pass

    async def broadcast(self, msg):
        await asyncio.gather(*(self.send(ws, msg) for ws in list(self.sockets.values())))

    async def flush(self):
        """개인 정보와 개인 알림 전송."""
        g = self.game
        dirty, g.pdirty = g.pdirty, set()
        for pid in dirty:
            ws = self.sockets.get(pid)
            if ws and pid in g.players:
                await self.send(ws, {"t": "me", "me": g.private(pid)})
        msgs, g.messages = g.messages, []
        for pid, text in msgs:
            ws = self.sockets.get(pid)
            if ws:
                await self.send(ws, {"t": "error", "msg": text})

    async def push(self, full=False):
        g = self.game
        if full or g.dirty:
            await self.broadcast({"t": "state", "state": g.state()})
        elif g.ev or g.changed:
            await self.broadcast({"t": "tk", **g.take_tick()})
        await self.flush()

    async def run(self):
        """게임 진행 루프. 접속자가 없으면 쉰다."""
        loop = asyncio.get_running_loop()
        next_t = loop.time()
        while True:
            next_t += TICK
            await asyncio.sleep(max(0, next_t - loop.time()))
            if not self.sockets:
                next_t = loop.time()
                continue
            async with self.lock:
                kind = self.game.tick()
                if kind == "state":
                    await self.broadcast({"t": "state", "state": self.game.state()})
                elif kind == "tk":
                    await self.broadcast({"t": "tk", **self.game.take_tick()})
                await self.flush()


rooms: dict[str, Room] = {}


async def cleanup_rooms():
    while True:
        await asyncio.sleep(300)
        now = time.time()
        for code in [c for c, r in rooms.items()
                     if not r.sockets and now - r.last_active > ROOM_IDLE_SEC]:
            rooms.pop(code).task.cancel()


@asynccontextmanager
async def lifespan(app):
    task = asyncio.create_task(cleanup_rooms())
    yield
    task.cancel()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html")


@app.get("/healthz")
async def healthz():
    return {"ok": True, "rooms": len(rooms)}


@app.get("/api/meta")
async def meta():
    return {"classes": CLASSES, "rarities": RARITIES, "stat_names": STAT_NAMES,
            "pct_stats": sorted(PCT_STATS), "objects": OBJECTS, "slots": SLOTS,
            "slot_names": SLOT_NAMES, "sets": SETS, "uniques": UNIQUES, "skill_max": SKILL_MAX,
            "potion_max": POTION_MAX, "enhance_max": ENHANCE_MAX}


@app.post("/api/rooms")
async def create_room():
    if len(rooms) >= MAX_ROOMS:
        raise HTTPException(503, "방이 너무 많습니다. 잠시 후 다시 시도하세요.")
    while True:
        code = "".join(secrets.choice(CODE_CHARS) for _ in range(4))
        if code not in rooms:
            break
    room = rooms[code] = Room(code)
    room.task = asyncio.create_task(room.run())
    return {"code": code}


@app.get("/api/rooms/{code}/map")
async def room_map(code: str):
    room = rooms.get(code.upper())
    if not room or not room.game.dg:
        raise HTTPException(404, "맵이 없습니다.")
    return room.game.map_data()


@app.websocket("/ws/{code}")
async def ws_endpoint(ws: WebSocket, code: str):
    await ws.accept()
    room = rooms.get(code.upper())
    if not room:
        await ws.send_json({"t": "fatal", "msg": "없는 방입니다."})
        await ws.close()
        return

    # 첫 메시지: {"t": "hello", "name": ..., "token": ...}
    try:
        hello = await asyncio.wait_for(ws.receive_json(), timeout=10)
    except Exception:
        await ws.close()
        return

    g = room.game
    async with room.lock:
        pid = room.tokens.get(hello.get("token") or "")
        if pid and pid in g.players:
            old = room.sockets.get(pid)
            if old:  # 다른 탭에서 접속 중이면 이전 연결을 끊는다
                await room.send(old, {"t": "fatal", "msg": "다른 창에서 접속했습니다."})
                try:
                    await old.close()
                except Exception:
                    pass
            token = hello["token"]
        else:
            try:
                pid = g.join(str(hello.get("name", "")).strip())
            except GameError as e:
                await ws.send_json({"t": "fatal", "msg": str(e)})
                await ws.close()
                return
            token = secrets.token_urlsafe(16)
            room.tokens[token] = pid
        room.sockets[pid] = ws
        g.set_connected(pid, True)
        await ws.send_json({"t": "welcome", "you": pid, "token": token, "chat": g.chat})
        await room.push(full=True)

    try:
        while True:
            msg = await ws.receive_json()
            room.last_active = time.time()
            async with room.lock:
                if room.sockets.get(pid) is not ws:
                    break
                try:
                    result = handle(g, pid, msg)
                except GameError as e:
                    await room.send(ws, {"t": "error", "msg": str(e)})
                    continue
                except (KeyError, TypeError, ValueError):
                    await room.send(ws, {"t": "error", "msg": "잘못된 요청입니다."})
                    continue
                t = msg.get("t")
                if t == "chat":
                    await room.broadcast({"t": "chat", "line": result})
                elif t in ("move", "attack", "talk"):
                    await room.flush()  # 실제 이동은 틱 루프가 방송
                else:
                    await room.push(full=t in ("class", "ready", "start", "lobby"))
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        async with room.lock:
            if room.sockets.get(pid) is ws:
                del room.sockets[pid]
                if g.phase == "lobby":
                    g.leave(pid)
                    room.tokens = {t: p for t, p in room.tokens.items() if p != pid}
                else:
                    g.set_connected(pid, False)
                room.last_active = time.time()
                await room.push(full=True)


def handle(g: Game, pid: str, msg: dict):
    t = msg.get("t")
    if t == "move":
        return g.move(pid, float(msg["x"]), float(msg["y"]))
    if t == "attack":
        return g.attack(pid, str(msg["id"]))
    if t == "talk":
        return g.talk(pid, str(msg["id"]))
    if t == "skill":
        return g.cast(pid, str(msg["id"]), float(msg["x"]), float(msg["y"]), msg.get("target"))
    if t == "class":
        return g.choose_class(pid, msg["cls"])
    if t == "ready":
        return g.toggle_ready(pid)
    if t == "start":
        return g.start(pid)
    if t == "lobby":
        return g.to_lobby(pid)
    if t == "learn":
        return g.learn(pid, str(msg["id"]))
    if t == "equip":
        return g.equip(pid, str(msg["id"]), msg.get("slot"))
    if t == "unequip":
        return g.unequip(pid, str(msg["slot"]))
    if t == "drop":
        return g.drop_item(pid, str(msg["id"]))
    if t == "sort":
        return g.sort_inv(pid)
    if t == "buy":
        return g.shop_buy(pid, int(msg["idx"]))
    if t == "buy_potion":
        return g.buy_potion(pid)
    if t == "sell":
        return g.sell(pid, str(msg["id"]))
    if t == "enhance":
        return g.enhance(pid, str(msg["id"]))
    if t == "close_npc":
        return g.close_npc(pid)
    if t == "prompt":
        return g.answer_prompt(pid, bool(msg.get("yes")))
    if t == "chat":
        text = str(msg.get("text", "")).strip()[:120]
        if not text:
            raise GameError("빈 메시지")
        line = {"name": g.players[pid]["name"], "text": text}
        g.chat.append(line)
        del g.chat[:-30]
        return line
    raise GameError("알 수 없는 요청")
