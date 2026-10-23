"""던전 맵 생성과 길찾기."""
from collections import deque

WALL, FLOOR = "#", "."
MAP_W, MAP_H = 64, 48
DIRS8 = [(1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)]


RADIUS = 0.3  # 캐릭터 충돌 반경(타일)

# 마을 지도: #=벽 .=바닥  S=상인 B=대장장이 P=포탈 @=시작
TOWN = [
    "############################",
    "#..........................#",
    "#...S..............B.......#",
    "#..........................#",
    "#....##............##......#",
    "#....##............##......#",
    "#..........................#",
    "#..@...................P...#",
    "#..........................#",
    "#....##............##......#",
    "#....##............##......#",
    "#..........................#",
    "#..........................#",
    "############################",
]


class Dungeon:
    def __init__(self, rng, w=MAP_W, h=MAP_H, room_target=14, town=False):
        self.rng = rng
        self.rooms = []  # (x, y, w, h)
        self.marks = {}
        if town:
            self.w, self.h = len(TOWN[0]), len(TOWN)
            self.grid = []
            for y, row in enumerate(TOWN):
                line = []
                for x, ch in enumerate(row):
                    if ch not in "#.":
                        self.marks[ch] = (x, y)
                    line.append(WALL if ch == "#" else FLOOR)
                self.grid.append(line)
            self.rooms = [(1, 1, self.w - 2, self.h - 2)]
        else:
            self.w, self.h = w, h
            self.grid = [[WALL] * w for _ in range(h)]
            self._place_rooms(room_target)
            self._connect()
        self.adj = {}
        for y in range(self.h):
            for x in range(self.w):
                if self.grid[y][x] == FLOOR:
                    self.adj[(x, y)] = list(self._neighbors(x, y))
        self.start_room = self.rooms[0]
        if town:
            self.start = self.marks["@"]
            self.far_room = self.start_room
            self.stairs = self.marks["P"]
            return
        self.start = self.center(self.start_room)
        dist = self.distances(self.start)
        self.far_room = max(self.rooms[1:], key=lambda r: dist.get(self.center(r), 0))
        self.stairs = self.center(self.far_room)

    # ---------- 생성 ----------
    def _place_rooms(self, target):
        for _ in range(400):
            if len(self.rooms) >= target:
                break
            rw, rh = self.rng.randint(6, 11), self.rng.randint(5, 8)
            x, y = self.rng.randint(1, self.w - rw - 2), self.rng.randint(1, self.h - rh - 2)
            if any(x < ox + ow + 2 and ox < x + rw + 2 and y < oy + oh + 2 and oy < y + rh + 2
                   for ox, oy, ow, oh in self.rooms):
                continue
            self.rooms.append((x, y, rw, rh))
            for yy in range(y, y + rh):
                for xx in range(x, x + rw):
                    self.grid[yy][xx] = FLOOR

    def _connect(self):
        # 프림 알고리즘으로 가까운 방끼리 연결 + 순환로 몇 개
        centers = [self.center(r) for r in self.rooms]
        done = {0}
        while len(done) < len(centers):
            best = None
            for i in done:
                for j in range(len(centers)):
                    if j in done:
                        continue
                    d = abs(centers[i][0] - centers[j][0]) + abs(centers[i][1] - centers[j][1])
                    if best is None or d < best[0]:
                        best = (d, i, j)
            _, i, j = best
            self._corridor(centers[i], centers[j])
            done.add(j)
        for _ in range(3):
            a, b = self.rng.sample(centers, 2)
            self._corridor(a, b)

    def _corridor(self, a, b):
        (x1, y1), (x2, y2) = a, b
        if self.rng.random() < 0.5:
            self._hline(x1, x2, y1)
            self._vline(y1, y2, x2)
        else:
            self._vline(y1, y2, x1)
            self._hline(x1, x2, y2)

    def _hline(self, x1, x2, y):
        for x in range(min(x1, x2), max(x1, x2) + 1):
            self.grid[y][x] = FLOOR

    def _vline(self, y1, y2, x):
        for y in range(min(y1, y2), max(y1, y2) + 1):
            self.grid[y][x] = FLOOR

    # ---------- 조회 ----------
    @staticmethod
    def center(room):
        x, y, w, h = room
        return (x + w // 2, y + h // 2)

    def walkable(self, x, y):
        return 0 <= x < self.w and 0 <= y < self.h and self.grid[y][x] == FLOOR

    def room_tiles(self, room, margin=1):
        x, y, w, h = room
        return [(xx, yy) for yy in range(y + margin, y + h - margin)
                for xx in range(x + margin, x + w - margin)]

    def neighbors(self, x, y):
        return self.adj.get((x, y), ())

    def _neighbors(self, x, y):
        for dx, dy in DIRS8:
            nx, ny = x + dx, y + dy
            if not self.walkable(nx, ny):
                continue
            # 대각선 이동 시 모서리 뚫고 지나가기 금지
            if dx and dy and not (self.walkable(x + dx, y) and self.walkable(x, y + dy)):
                continue
            yield nx, ny

    def distances(self, src, limit=None):
        dist = {src: 0}
        q = deque([src])
        while q:
            cur = q.popleft()
            if limit is not None and dist[cur] >= limit:
                continue
            for n in self.neighbors(*cur):
                if n not in dist:
                    dist[n] = dist[cur] + 1
                    q.append(n)
        return dist

    def path(self, src, dst, limit=200):
        """src → dst 최단 경로 (src 제외). 못 가면 None."""
        if src == dst:
            return []
        if not self.walkable(*dst):
            return None
        prev = {src: None}
        q = deque([src])
        adj = self.adj
        while q:
            cur = q.popleft()
            if cur == dst:
                break
            for n in adj.get(cur, ()):
                if n not in prev:
                    prev[n] = cur
                    q.append(n)
        if dst not in prev:
            return None
        out = []
        cur = dst
        while cur != src:
            out.append(cur)
            cur = prev[cur]
        out.reverse()
        return out if len(out) <= limit else None

    def los(self, a, b):
        """a에서 b가 벽에 막히지 않고 보이는지 (브레즌햄 직선)."""
        (x0, y0), (x1, y1) = a, b
        dx, dy = abs(x1 - x0), -abs(y1 - y0)
        sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
        err = dx + dy
        while (x0, y0) != (x1, y1):
            if not self.walkable(x0, y0):
                return False
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy
        return True

    # ---------- 연속 좌표 이동 ----------
    def free(self, x, y, r=RADIUS):
        """반경 r인 원(사각형 근사)이 벽과 겹치지 않는지."""
        w = self.walkable
        return (w(int(x - r), int(y - r)) and w(int(x + r), int(y - r))
                and w(int(x - r), int(y + r)) and w(int(x + r), int(y + r)))

    def slide(self, x, y, dx, dy, r=RADIUS):
        """축별로 나눠 이동해서 벽에 비비며 미끄러지게."""
        if self.free(x + dx, y, r):
            x += dx
        if self.free(x, y + dy, r):
            y += dy
        return x, y

    def clear_line(self, x0, y0, x1, y1, r=RADIUS):
        d = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
        n = int(d / 0.25) + 1
        for i in range(1, n + 1):
            t = i / n
            if not self.free(x0 + (x1 - x0) * t, y0 + (y1 - y0) * t, r):
                return False
        return True

    def tiles_str(self):
        return ["".join(row) for row in self.grid]
