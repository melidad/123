"""巨鹿之战 30 秒地图动画样片（彩色疆域 + 真实地形 + 进军箭头 + 地名浮现）。

运行：
    pip install -r requirements.txt
    python render.py              # 渲染完整视频到 output/julu.mp4
    python render.py --preview    # 只渲染几张关键帧到 output/preview_*.png，用来快速调画面

依赖：ffmpeg、Noto Sans CJK 字体（Ubuntu: apt install fonts-noto-cjk；
macOS/Windows 可改 FONT_* 路径为思源黑体）。
地形数据来自 AWS Terrain Tiles（Terrarium 编码，公开免费），首次运行会下载到 cache/。
疆域边界、秦代河道为示意，行军路线采用辛德勇《巨鹿之战地理新解》的说法。
"""

import argparse
import math
import os
import subprocess
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "cache")
OUT = os.path.join(HERE, "output")

W, H = 1920, 1080
SS = 2  # 矢量图层超采样倍数，用来抗锯齿
FPS = 30
DURATION = 30.0

ZOOM = 9
EXTENT = (105.0, 123.0, 32.0, 41.0)  # lon0, lon1, lat0, lat1
TILE_URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"

FONT_BLACK = "/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc"
FONT_BOLD = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
FONT_INDEX = 2  # ttc 里的简体中文（SC）

QIN = (214, 38, 43)
CHU = (40, 170, 70)
ZHAO = (242, 205, 40)
QI = (60, 165, 225)
YAN = (205, 70, 200)
WEI = (240, 140, 40)
YELLOW = (255, 214, 0)
WHITE = (255, 255, 255)
INK = (20, 20, 20)
RIVER = (70, 140, 215)

# ---------------------------------------------------------------- 地理数据（经度, 纬度）

PLACES = {
    "咸阳": (108.71, 34.33),
    "彭城": (117.18, 34.26),
    "邯郸": (114.49, 36.61),
    "巨鹿": (115.03, 37.06),
    "棘原": (114.92, 36.80),
    "安阳": (116.30, 35.92),
    "平原津": (116.42, 37.17),
}

TERRITORIES = [
    ("秦", QIN, [(104, 31.5), (113.6, 31.5), (113.9, 33.6), (114.3, 34.5), (114.6, 35.3),
                 (114.95, 36.1), (115.05, 36.75), (114.4, 37.25), (113.6, 38.6), (112.6, 41.5), (104, 41.5)],
     (110.2, 36.4)),
    ("赵", ZHAO, [(114.4, 37.25), (115.05, 36.75), (115.7, 37.05), (116.3, 38.2), (116.0, 39.3),
                  (114.6, 39.6), (113.6, 38.6)], (115.0, 38.3)),
    ("燕", YAN, [(113.6, 38.6), (114.6, 39.6), (116.0, 39.3), (117.6, 39.05), (119.4, 39.5),
                 (123.5, 40.4), (123.5, 41.5), (112.6, 41.5)], (116.0, 39.62)),
    ("齐", QI, [(116.3, 38.2), (115.7, 37.05), (116.1, 36.55), (116.6, 35.9), (117.1, 35.25),
                (118.6, 35.25), (119.6, 35.6), (123.5, 36.4), (123.5, 38.3), (119.3, 38.1),
                (118.6, 38.0), (117.4, 38.6)], (118.3, 36.6)),
    ("魏", WEI, [(115.05, 36.75), (114.95, 36.1), (114.6, 35.3), (115.3, 34.95), (116.6, 35.9),
                 (116.1, 36.55), (115.7, 37.05)], (115.55, 35.75)),
    ("楚", CHU, [(113.6, 31.5), (123.5, 31.5), (123.5, 33.0), (120.4, 34.4), (119.6, 35.6),
                 (118.6, 35.25), (117.1, 35.25), (116.6, 35.9), (115.3, 34.95), (114.6, 35.3),
                 (114.3, 34.5), (113.9, 33.6)], (118.7, 34.55)),
]

# 秦代大河（西汉故道）与漳水，示意走向
YELLOW_RIVER = [(111.5, 34.8), (112.6, 34.85), (113.4, 34.95), (114.0, 35.3), (114.55, 35.65),
                (115.0, 35.85), (115.15, 36.3), (115.4, 36.6), (115.7, 36.9), (116.35, 37.15),
                (116.42, 37.45), (116.55, 37.9), (116.85, 38.3), (117.35, 38.42), (117.8, 38.5)]
ZHANG_RIVER = [(113.6, 36.45), (114.2, 36.35), (114.45, 36.38), (114.7, 36.55), (115.0, 36.75),
               (115.35, 36.9), (115.6, 37.1), (115.85, 37.45), (116.2, 37.75), (116.55, 37.9)]

ARROW_ZHANGHAN = [(113.6, 34.9), (114.0, 35.6), (114.3, 36.2), (114.45, 36.55)]
ARROW_WANGLI = [(112.4, 38.5), (113.4, 38.25), (114.2, 37.75), (114.8, 37.25), (114.97, 37.1)]
ARROW_CHU = [(116.3, 35.98), (116.52, 36.55), (116.42, 37.17), (116.0, 37.2), (115.6, 37.0),
             (115.34, 36.74)]
ARROW_YINGBU = [(115.42, 36.70), (115.25, 36.84), (115.02, 36.89)]
ARROW_XIANGYU = [(115.36, 36.70), (115.22, 36.9), (115.06, 37.02)]
ARROW_RETREAT = [(114.9, 36.78), (114.65, 36.5), (114.38, 36.22)]
SUPPLY_ROAD = [(114.92, 36.80), (114.97, 36.88), (115.0, 36.97)]
CAMPS = [(114.86, 37.25), (114.98, 37.28), (115.1, 37.26), (115.22, 37.23)]

# ---------------------------------------------------------------- 投影与地形


def world_px(lon, lat, z=ZOOM):
    n = 256 * 2 ** z
    s = math.sin(math.radians(lat))
    return (lon + 180) / 360 * n, (0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)) * n


def tile_range():
    lon0, lon1, lat0, lat1 = EXTENT
    x0, y0 = world_px(lon0, lat1)
    x1, y1 = world_px(lon1, lat0)
    return int(x0 // 256), int(x1 // 256), int(y0 // 256), int(y1 // 256)


def fetch_tile(xy):
    x, y = xy
    path = os.path.join(CACHE, f"{ZOOM}_{x}_{y}.png")
    if not os.path.exists(path):
        with urllib.request.urlopen(TILE_URL.format(z=ZOOM, x=x, y=y), timeout=60) as r:
            data = r.read()
        with open(path, "wb") as f:
            f.write(data)
    return xy, np.asarray(Image.open(path).convert("RGB"), dtype=np.float32)


def load_elevation():
    os.makedirs(CACHE, exist_ok=True)
    tx0, tx1, ty0, ty1 = tile_range()
    elev = np.zeros(((ty1 - ty0 + 1) * 256, (tx1 - tx0 + 1) * 256), dtype=np.float32)
    jobs = [(x, y) for x in range(tx0, tx1 + 1) for y in range(ty0, ty1 + 1)]
    with ThreadPoolExecutor(16) as pool:
        for (x, y), rgb in pool.map(fetch_tile, jobs):
            e = rgb[..., 0] * 256 + rgb[..., 1] + rgb[..., 2] / 256 - 32768
            elev[(y - ty0) * 256:(y - ty0 + 1) * 256, (x - tx0) * 256:(x - tx0 + 1) * 256] = e
    return elev, (tx0 * 256, ty0 * 256)


def shade_terrain(elev):
    cell = 156543.03 * math.cos(math.radians(36.5)) / 2 ** ZOOM
    gy, gx = np.gradient(elev * 2.5, cell)
    dzdx, dzdy = gx, -gy
    az, alt = math.radians(315), math.radians(42)
    lx, ly, lz = math.sin(az) * math.cos(alt), math.cos(az) * math.cos(alt), math.sin(alt)
    norm = np.sqrt(dzdx ** 2 + dzdy ** 2 + 1)
    shade = np.clip((-dzdx * lx - dzdy * ly + lz) / norm, 0, 1)

    stops = [0, 80, 250, 600, 1000, 1500, 2200, 3200]
    cols = np.array([(188, 206, 150), (176, 198, 138), (192, 192, 146), (198, 178, 132),
                     (176, 148, 110), (150, 122, 92), (132, 108, 88), (230, 226, 216)], dtype=np.float32)
    land = np.stack([np.interp(elev, stops, cols[:, i]) for i in range(3)], axis=-1)
    factor = (0.3 + 0.7 * shade) / (0.3 + 0.7 * math.sin(alt))
    land = land * factor[..., None]

    depth = np.clip(-elev / 60, 0, 1)[..., None]
    sea = (1 - depth) * np.array([140, 185, 215]) + depth * np.array([95, 150, 195])
    rgb = np.where((elev <= 0)[..., None], sea, land)
    return Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8))


# ---------------------------------------------------------------- 动画工具


def clamp(v, a=0.0, b=1.0):
    return max(a, min(b, v))


def seg(t, a, b):
    return clamp((t - a) / (b - a))


def ease_out(p):
    return 1 - (1 - p) ** 3


def ease_in_out(p):
    return 4 * p ** 3 if p < 0.5 else 1 - (-2 * p + 2) ** 3 / 2


def ease_back(p):
    c = 1.9
    return 1 + (c + 1) * (p - 1) ** 3 + c * (p - 1) ** 2


_fonts = {}


def font(size, heavy=True):
    key = (int(size), heavy)
    if key not in _fonts:
        _fonts[key] = ImageFont.truetype(FONT_BLACK if heavy else FONT_BOLD, max(4, int(size)), index=FONT_INDEX)
    return _fonts[key]


def smooth(points, samples=24):
    """Catmull-Rom 平滑，让箭头路径更圆润。"""
    if len(points) < 3:
        return points
    pts = [points[0]] + list(points) + [points[-1]]
    out = []
    for i in range(1, len(pts) - 2):
        p0, p1, p2, p3 = pts[i - 1], pts[i], pts[i + 1], pts[i + 2]
        for k in range(samples):
            t = k / samples
            t2, t3 = t * t, t * t * t
            out.append(tuple(0.5 * (2 * p1[j] + (-p0[j] + p2[j]) * t + (2 * p0[j] - 5 * p1[j] + 4 * p2[j] - p3[j]) * t2
                                    + (-p0[j] + 3 * p1[j] - 3 * p2[j] + p3[j]) * t3) for j in range(2)))
    out.append(points[-1])
    return out


def partial(path, p):
    if p <= 0:
        return []
    lens = [0.0]
    for a, b in zip(path, path[1:]):
        lens.append(lens[-1] + math.dist(a, b))
    target = lens[-1] * p
    out = [path[0]]
    for i in range(1, len(path)):
        if lens[i] >= target:
            a, b = path[i - 1], path[i]
            f = (target - lens[i - 1]) / max(1e-9, lens[i] - lens[i - 1])
            out.append((a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f))
            break
        out.append(path[i])
    return out


class Camera:
    KEYS = [  # 时间, 中心经度, 中心纬度, 画面宽度（经度）
        (0.0, 114.0, 36.85, 16.4),
        (7.5, 114.0, 36.75, 15.4),
        (10.8, 115.6, 36.52, 5.0),
        (22.0, 115.5, 36.58, 4.7),
        (25.0, 115.15, 36.9, 3.2),
        (27.0, 115.15, 36.9, 3.2),
        (30.0, 115.3, 36.72, 4.4),
    ]

    def __init__(self, t, origin):
        k = self.KEYS
        i = max(j for j in range(len(k)) if k[j][0] <= t) if t < k[-1][0] else len(k) - 2
        a, b = k[i], k[i + 1]
        p = ease_in_out(seg(t, a[0], b[0]))
        self.lon = a[1] + (b[1] - a[1]) * p
        self.lat = a[2] + (b[2] - a[2]) * p
        self.width = math.exp(math.log(a[3]) + (math.log(b[3]) - math.log(a[3])) * p)
        cx, cy = world_px(self.lon, self.lat)
        self.view_w = self.width * 256 * 2 ** ZOOM / 360
        self.view_h = self.view_w * H / W
        self.cx, self.cy = cx, cy
        self.scale = W / self.view_w
        self.origin = origin

    def crop_box(self):
        ox, oy = self.origin
        return (self.cx - self.view_w / 2 - ox, self.cy - self.view_h / 2 - oy,
                self.cx + self.view_w / 2 - ox, self.cy + self.view_h / 2 - oy)

    def px(self, lon, lat):
        x, y = world_px(lon, lat)
        return ((x - self.cx) * self.scale + W / 2) * SS, ((y - self.cy) * self.scale + H / 2) * SS

    def pts(self, coords):
        return [self.px(*c) for c in coords]

    def deg_px(self):
        return self.scale * 256 * 2 ** ZOOM / 360 * SS


# ---------------------------------------------------------------- 绘制元素


def with_alpha(color, a):
    return (*color[:3], int(255 * clamp(a)))


def text_center(d, xy, s, size, fill, stroke=0, stroke_fill=INK, heavy=True, alpha=1.0, anchor="mm"):
    if alpha <= 0 or size < 2:
        return
    d.text(xy, s, font=font(size * SS, heavy), fill=with_alpha(fill, alpha), anchor=anchor,
           stroke_width=int(stroke * SS), stroke_fill=with_alpha(stroke_fill, alpha))


def draw_arrow(d, path, p, color, width, alpha=1.0):
    pts = partial(path, p)
    if len(pts) < 2:
        return
    w = width * SS
    head_len, head_w = w * 2.4, w * 2.3
    total = sum(math.dist(a, b) for a, b in zip(pts, pts[1:]))
    if total < head_len * 0.6:
        return
    body, acc = [], 0.0
    for i, a in enumerate(pts):
        if i:
            acc += math.dist(pts[i - 1], a)
        if acc > total - head_len * 0.85:
            break
        body.append((a, acc / total))
    tip = pts[-1]
    back = partial(pts[::-1], head_len / total)[-1] if total > head_len else pts[0]
    dx, dy = tip[0] - back[0], tip[1] - back[1]
    ln = math.hypot(dx, dy) or 1
    nx, ny = -dy / ln, dx / ln
    left, right = [], []
    for i, (a, f) in enumerate(body):
        b = body[min(i + 1, len(body) - 1)][0] if i < len(body) - 1 else back
        c = body[max(i - 1, 0)][0]
        tx, ty = b[0] - c[0], b[1] - c[1]
        tl = math.hypot(tx, ty) or 1
        hw = w * (0.35 + 0.65 * f) / 2
        left.append((a[0] - ty / tl * hw, a[1] + tx / tl * hw))
        right.append((a[0] + ty / tl * hw, a[1] - tx / tl * hw))
    hw = w / 2
    poly = left + [(back[0] + nx * hw, back[1] + ny * hw), (back[0] + nx * head_w / 2, back[1] + ny * head_w / 2), tip,
                   (back[0] - nx * head_w / 2, back[1] - ny * head_w / 2), (back[0] - nx * hw, back[1] - ny * hw)] + right[::-1]
    shadow = [(x + 5 * SS, y + 6 * SS) for x, y in poly]
    d.polygon(shadow, fill=(0, 0, 0, int(70 * alpha)))
    d.polygon(poly, fill=with_alpha(color, 0.92 * alpha), outline=with_alpha(WHITE, alpha), width=int(3 * SS))


def draw_line(d, coords_px, color, width, alpha=1.0, dash=None, offset=0.0):
    if alpha <= 0 or len(coords_px) < 2:
        return
    if not dash:
        d.line(coords_px, fill=with_alpha(color, alpha), width=int(width * SS), joint="curve")
        return
    on, off = dash[0] * SS, dash[1] * SS
    period = on + off
    pos = -offset * SS % period - period
    for a, b in zip(coords_px, coords_px[1:]):
        L = math.dist(a, b)
        s = pos
        while s < L:
            s0, s1 = max(0, s), min(L, s + on)
            if s1 > s0:
                p0 = (a[0] + (b[0] - a[0]) * s0 / L, a[1] + (b[1] - a[1]) * s0 / L)
                p1 = (a[0] + (b[0] - a[0]) * s1 / L, a[1] + (b[1] - a[1]) * s1 / L)
                d.line([p0, p1], fill=with_alpha(color, alpha), width=int(width * SS))
            s += period
        pos = s - L - period


def city(d, cam, name, t_in, t, big=False, color=WHITE, label_dx=0, label_dy=-34, t_out=None):
    p = ease_back(seg(t, t_in, t_in + 0.5))
    a = seg(t, t_in, t_in + 0.25)
    if t_out is not None:
        a *= 1 - seg(t, t_out, t_out + 0.4)
    if a <= 0:
        return
    x, y = cam.px(*PLACES[name])
    r = (13 if big else 9) * SS * p
    d.ellipse([x - r, y - r, x + r, y + r], fill=with_alpha(color, a), outline=with_alpha(INK, a), width=int(3 * SS))
    if big:
        r2 = r * 0.45
        d.ellipse([x - r2, y - r2, x + r2, y + r2], fill=with_alpha(QIN if color == WHITE else INK, a))
    size = (40 if big else 32) * (0.6 + 0.4 * p)
    text_center(d, (x + label_dx * SS, y + label_dy * SS), name, size, YELLOW if big else WHITE, stroke=4, alpha=a)


def badge(d, xy, text, color, size, alpha, anchor_left=False):
    if alpha <= 0:
        return
    f = font(size * SS, heavy=True)
    x, y = xy
    l, t_, r, b = d.textbbox((0, 0), text, font=f, anchor="lt")
    tw, th = r - l, b - t_
    pad_x, pad_y = 14 * SS, 9 * SS
    x0 = x if anchor_left else x - tw / 2 - pad_x
    box = [x0, y - th / 2 - pad_y, x0 + tw + pad_x * 2, y + th / 2 + pad_y]
    d.rounded_rectangle([box[0] + 4 * SS, box[1] + 5 * SS, box[2] + 4 * SS, box[3] + 5 * SS], radius=8 * SS,
                        fill=(0, 0, 0, int(90 * alpha)))
    d.rounded_rectangle(box, radius=8 * SS, fill=with_alpha(color, 0.95 * alpha), outline=with_alpha(WHITE, alpha),
                        width=int(3 * SS))
    d.text(((box[0] + box[2]) / 2, (box[1] + box[3]) / 2), text, font=f, fill=with_alpha(WHITE, alpha), anchor="mm")


def caption(d, t, items):
    """底部字幕条：items = [(开始, 结束, [(文字, 颜色), ...]), ...]"""
    for t0, t1, parts in items:
        a = seg(t, t0, t0 + 0.3) * (1 - seg(t, t1 - 0.3, t1))
        if a <= 0:
            continue
        f = font(46 * SS, heavy=False)
        widths = [d.textlength(s, font=f) for s, _ in parts]
        total = sum(widths)
        y = (H - 92) * SS
        d.rounded_rectangle([(W * SS - total) / 2 - 36 * SS, y - 44 * SS, (W * SS + total) / 2 + 36 * SS, y + 44 * SS],
                            radius=14 * SS, fill=(10, 10, 10, int(175 * a)))
        x = (W * SS - total) / 2
        for (s, c), w in zip(parts, widths):
            d.text((x, y), s, font=f, fill=with_alpha(c, a), anchor="lm")
            x += w


# ---------------------------------------------------------------- 逐帧合成


class Renderer:
    def __init__(self):
        elev, self.origin = load_elevation()
        self.base = shade_terrain(elev)
        self.land = Image.fromarray(((elev > 0) * 255).astype(np.uint8))
        yy, xx = np.mgrid[0:H, 0:W]
        v = 1 - 0.38 * (((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2) ** 1.4
        self.vignette = np.clip(v, 0.55, 1)[..., None].astype(np.float32)
        band = np.exp(-(((np.arange(H) - H * 0.45) / (H * 0.17)) ** 4))
        self.band = band[:, None, None].astype(np.float32)

    def frame(self, t):
        cam = Camera(t, self.origin)
        img = self.base.resize((W, H), Image.BICUBIC, box=cam.crop_box()).convert("RGBA")

        terr = Image.new("RGBA", (W * SS, H * SS), (0, 0, 0, 0))
        dt = ImageDraw.Draw(terr)
        fade = ease_out(seg(t, 0.2, 1.6))
        close = seg(cam.width, 9, 4.2)
        fill_a = (0.52 - 0.22 * close) * fade
        for name, color, poly, _ in TERRITORIES:
            dt.polygon(cam.pts(poly), fill=with_alpha(color, fill_a))
        for name, color, poly, _ in TERRITORIES:
            pts = cam.pts(poly)
            dt.line(pts + [pts[0]], fill=with_alpha((255, 255, 255), 0.75 * fade), width=int(3 * SS), joint="curve")
        terr = terr.resize((W, H), Image.LANCZOS)
        land = self.land.resize((W, H), Image.BILINEAR, box=cam.crop_box())
        terr.putalpha(ImageChops.multiply(terr.getchannel("A"), land))
        img.alpha_composite(terr)

        ov = Image.new("RGBA", (W * SS, H * SS), (0, 0, 0, 0))
        d = ImageDraw.Draw(ov)
        self.draw_scene(d, cam, t)
        img.alpha_composite(ov.resize((W, H), Image.LANCZOS))

        rgb = np.asarray(img.convert("RGB"), dtype=np.float32) * self.vignette
        card = seg(t, 27.6, 28.2)
        if card > 0:
            rgb *= 1 - 0.5 * card * self.band
            top = Image.new("RGBA", (W * SS, H * SS), (0, 0, 0, 0))
            dd = ImageDraw.Draw(top)
            s = ease_back(card)
            text_center(dd, (W / 2 * SS, H * 0.42 * SS), "秦军主力覆灭", 112 * s, QIN, stroke=9, stroke_fill=WHITE, alpha=card)
            text_center(dd, (W / 2 * SS, H * 0.42 * SS + 108 * SS), "项羽 一战封神", 56 * s, YELLOW, stroke=5, alpha=card)
            base = Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8)).convert("RGBA")
            base.alpha_composite(top.resize((W, H), Image.LANCZOS))
            rgb = np.asarray(base.convert("RGB"), dtype=np.float32)
        fade_out = seg(t, 29.3, 30.0)
        if fade_out > 0:
            rgb *= 1 - 0.85 * fade_out
        return np.clip(rgb, 0, 255).astype(np.uint8)

    def draw_scene(self, d, cam, t):
        river_w = 3 + 4 * seg(cam.width, 9, 4.2)
        for river in (YELLOW_RIVER, ZHANG_RIVER):
            pts = cam.pts(smooth(river, 12))
            draw_line(d, pts, (235, 245, 255), river_w + 3, alpha=0.8 * seg(t, 0.4, 1.4))
            draw_line(d, pts, RIVER, river_w, alpha=seg(t, 0.4, 1.4))
        text_center(d, cam.px(112.9, 34.55), "大河（秦代故道·示意）", 26, (220, 238, 255), stroke=3,
                    stroke_fill=(30, 70, 120), alpha=seg(t, 1.2, 1.8) * (1 - seg(t, 8.5, 9.2)), heavy=False)
        text_center(d, cam.px(115.95, 37.02), "大河", 30, (220, 238, 255), stroke=3, stroke_fill=(30, 70, 120),
                    alpha=seg(t, 10.5, 11.0), heavy=False)
        text_center(d, cam.px(114.55, 36.38), "漳水", 30, (220, 238, 255), stroke=3, stroke_fill=(30, 70, 120),
                    alpha=seg(t, 10.5, 11.0), heavy=False)

        wide = 1 - seg(t, 7.6, 8.6)
        for i, (name, color, _, c) in enumerate(TERRITORIES):
            p = ease_back(seg(t, 1.0 + i * 0.12, 1.5 + i * 0.12))
            text_center(d, cam.px(*c), name, 92 * (0.5 + 0.5 * p), INK, stroke=0,
                        alpha=0.82 * seg(t, 1.0 + i * 0.12, 1.3 + i * 0.12) * wide)

        city(d, cam, "咸阳", 3.6, t, t_out=8.0)
        city(d, cam, "彭城", 3.8, t, t_out=8.0)
        city(d, cam, "邯郸", 4.0, t, label_dx=-46, label_dy=0)

        p = ease_in_out(seg(t, 4.4, 6.2))
        draw_arrow(d, cam.pts(smooth(ARROW_ZHANGHAN)), p, QIN, 22, alpha=1 - seg(t, 9.5, 10.3))
        p = ease_in_out(seg(t, 5.0, 7.0))
        draw_arrow(d, cam.pts(smooth(ARROW_WANGLI)), p, QIN, 22, alpha=1 - seg(t, 9.5, 10.3))
        a = seg(t, 5.4, 5.8) * (1 - seg(t, 9.5, 10.0))
        badge(d, cam.px(113.9, 35.25), "章邯", QIN, 30, a)
        a = seg(t, 6.0, 6.4) * (1 - seg(t, 9.5, 10.0))
        badge(d, cam.px(112.75, 37.95), "王离 · 长城军团", QIN, 30, a)

        a = seg(t, 2.2, 2.6) * (1 - seg(t, 14.5, 15.0))
        if a > 0:
            x0, y0 = (W - 470) * SS, 70 * SS
            d.rounded_rectangle([x0, y0, x0 + 420 * SS, y0 + 200 * SS], radius=16 * SS, fill=(15, 15, 15, int(175 * a)))
            text_center(d, (x0 + 110 * SS, y0 + 62 * SS), "秦军", 40, WHITE, alpha=a)
            text_center(d, (x0 + 300 * SS, y0 + 62 * SS), "约40万", 52, QIN, stroke=3, stroke_fill=WHITE, alpha=a)
            text_center(d, (x0 + 110 * SS, y0 + 128 * SS), "楚军", 40, WHITE, alpha=a)
            text_center(d, (x0 + 300 * SS, y0 + 128 * SS), "约5万", 52, CHU, stroke=3, stroke_fill=WHITE, alpha=a)
            text_center(d, (x0 + 210 * SS, y0 + 178 * SS), "兵力为通说，学界有争议", 22, (200, 200, 200), alpha=a, heavy=False)

        jl = cam.px(*PLACES["巨鹿"])
        radius = 0.085 * cam.deg_px()
        ring_in = seg(t, 9.6, 10.6)
        broken = seg(t, 24.4, 25.6)
        if ring_in > 0 and broken < 1:
            n = 18
            for i in range(n):
                ang0 = 2 * math.pi * i / n + t * 0.25
                if i / n > ease_out(ring_in):
                    continue
                push = 1 + 0.9 * ease_out(broken) * (0.6 + 0.4 * math.sin(i * 7.3))
                r = radius * push
                box = [jl[0] - r, jl[1] - r, jl[0] + r, jl[1] + r]
                d.arc(box, math.degrees(ang0), math.degrees(ang0 + 2 * math.pi / n * 0.62),
                      fill=with_alpha(QIN, 1 - broken), width=int(9 * SS))
        badge(d, cam.px(114.62, 37.18), "王离 围城", QIN, 28, seg(t, 10.4, 10.8) * (1 - seg(t, 24.6, 25.2)))
        city(d, cam, "巨鹿", 4.3, t, big=True, label_dx=96, label_dy=-4)

        city(d, cam, "棘原", 11.0, t, label_dx=-58, label_dy=6)
        road = cam.pts(SUPPLY_ROAD)
        cut = seg(t, 20.6, 21.2)
        draw_line(d, road, (120, 30, 30), 7, alpha=seg(t, 11.3, 12.0) * (1 - 0.7 * cut), dash=(14, 9), offset=t * 40)
        text_center(d, cam.px(114.78, 36.92), "甬道（运粮）", 26, WHITE, stroke=3, alpha=seg(t, 11.6, 12.2) * (1 - seg(t, 24.0, 24.5)))
        badge(d, cam.px(114.6, 36.72), "章邯", QIN, 28, seg(t, 11.2, 11.6) * (1 - seg(t, 26.6, 27.0)))
        if cut > 0:
            mx, my = cam.px(114.965, 36.88)
            s = 26 * SS * ease_back(cut)
            for sx in (1, -1):
                d.line([(mx - s, my - s * sx), (mx + s, my + s * sx)], fill=with_alpha(INK, 1), width=int(15 * SS))
                d.line([(mx - s, my - s * sx), (mx + s, my + s * sx)], fill=with_alpha(YELLOW, 1), width=int(9 * SS))

        city(d, cam, "安阳", 11.8, t, label_dx=0, label_dy=36)
        a = seg(t, 12.2, 12.6) * (1 - seg(t, 14.6, 15.0))
        badge(d, cam.px(116.62, 36.12), "宋义 逗留46天", CHU, 28, a, anchor_left=True)
        a = seg(t, 14.8, 15.2) * (1 - seg(t, 18.6, 19.0))
        badge(d, cam.px(116.62, 36.12), "项羽 斩宋义 夺兵权", CHU, 28, a, anchor_left=True)
        city(d, cam, "平原津", 15.6, t, label_dx=64, label_dy=0)

        p = ease_in_out(seg(t, 15.4, 18.6))
        draw_arrow(d, cam.pts(smooth(ARROW_CHU)), p, CHU, 26, alpha=1 - 0.55 * seg(t, 22.0, 23.0))
        p = ease_in_out(seg(t, 19.4, 20.6))
        draw_arrow(d, cam.pts(smooth(ARROW_YINGBU)), p, (110, 210, 120), 17, alpha=1 - seg(t, 24.0, 24.6))
        badge(d, cam.px(115.62, 36.6), "英布、蒲将军 2万", CHU, 26, seg(t, 19.2, 19.6) * (1 - seg(t, 22.0, 22.4)))

        p = ease_in_out(seg(t, 22.6, 24.4))
        draw_arrow(d, cam.pts(smooth(ARROW_XIANGYU)), p, CHU, 34)
        badge(d, cam.px(115.55, 36.62), "项羽 全军渡河", CHU, 30, seg(t, 22.4, 22.8) * (1 - seg(t, 26.4, 26.8)))

        for i, c in enumerate(CAMPS):
            a = seg(t, 24.8 + i * 0.1, 25.1 + i * 0.1) * (1 - seg(t, 28.6, 29.0))
            if a <= 0:
                continue
            x, y = cam.px(*c)
            s = 13 * SS
            d.rectangle([x - s, y - s, x + s, y + s], fill=with_alpha((120, 120, 120), a), outline=with_alpha(WHITE, a), width=int(3 * SS))
        text_center(d, cam.px(115.04, 37.36), "诸侯军 作壁上观", 28, WHITE, stroke=4, alpha=seg(t, 25.2, 25.6) * (1 - seg(t, 28.6, 29.0)))

        p = ease_in_out(seg(t, 26.6, 28.0))
        draw_arrow(d, cam.pts(smooth(ARROW_RETREAT)), p, QIN, 18, alpha=0.9)
        text_center(d, cam.px(114.28, 36.08), "章邯败退", 28, WHITE, stroke=4, alpha=seg(t, 27.4, 27.8))

        pop = seg(t, 23.2, 23.7)
        a = pop * (1 - seg(t, 26.0, 26.5))
        if a > 0:
            s = ease_back(pop)
            shake = math.sin(t * 90) * 6 * (1 - seg(t, 23.7, 24.2)) * SS
            cx, cy = W * 0.70 * SS + shake, H * 0.30 * SS
            text_center(d, (cx, cy), "破釜沉舟", 120 * s, WHITE, stroke=9, alpha=a)
            text_center(d, (cx, cy + 105 * SS), "持三日粮 · 九战九捷 · 虏王离", 44 * s, YELLOW, stroke=5, alpha=a)

        a = seg(t, 0.5, 1.0) * (1 - seg(t, 4.0, 4.5))
        if a > 0:
            x, y = 80 * SS, 140 * SS
            text_center(d, (x, y), "巨鹿之战", 128, WHITE, stroke=9, alpha=a, anchor="lm")
            d.line([(x, y + 92 * SS), (x + 560 * SS, y + 92 * SS)], fill=with_alpha(YELLOW, a), width=int(4 * SS))
            text_center(d, (x, y + 150 * SS), "公元前207年 · 秦军主力的最后一战", 46, YELLOW, stroke=4, alpha=a, anchor="lm")

        caption(d, t, [
            (2.0, 4.4, [("秦二世三年，六国复起，", WHITE), ("反秦之火", YELLOW), ("遍地燃烧", WHITE)]),
            (4.4, 7.8, [("章邯", QIN), ("攻破邯郸，", WHITE), ("王离", QIN), ("率长城军团南下，围赵王于", WHITE), ("巨鹿", YELLOW)]),
            (7.8, 11.8, [("王离围城，", WHITE), ("章邯", QIN), ("驻棘原，筑", WHITE), ("甬道", YELLOW), ("为王离输粮", WHITE)]),
            (11.8, 15.2, [("楚军北上救赵，宋义在安阳", WHITE), ("逗留46天", YELLOW), ("，被", WHITE), ("项羽", CHU), ("斩杀", WHITE)]),
            (15.2, 19.2, [("项羽", CHU), ("自", WHITE), ("平原津", YELLOW), ("渡过大河，西进至漳水南岸", WHITE)]),
            (19.2, 22.4, [("英布、蒲将军", CHU), ("率两万人先渡河，", WHITE), ("截断甬道", YELLOW)]),
            (22.4, 26.4, [("项羽", CHU), ("全军渡河，", WHITE), ("破釜沉舟", YELLOW), ("，九战大破秦军", WHITE)]),
        ])
        text_center(d, ((W - 24) * SS, (H - 22) * SS), "地形：AWS Terrain Tiles ｜ 疆域、河道为示意 ｜ 路线采用辛德勇说",
                    18, (235, 235, 235), stroke=2, alpha=0.85, heavy=False, anchor="rs")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", action="store_true", help="只渲染关键帧 PNG")
    ap.add_argument("--times", default="1.8,5.8,9,13,17.5,20.8,23.8,25.8,28.6")
    args = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    r = Renderer()

    if args.preview:
        for t in [float(x) for x in args.times.split(",")]:
            Image.fromarray(r.frame(t)).save(os.path.join(OUT, f"preview_{t:05.1f}.png"))
            print("preview", t)
        return

    out = os.path.join(OUT, "julu.mp4")
    ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                           "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "slow",
                           "-crf", "18", "-pix_fmt", "yuv420p", "-movflags", "+faststart", out], stdin=subprocess.PIPE)
    n = int(DURATION * FPS)
    for i in range(n):
        ff.stdin.write(r.frame(i / FPS).tobytes())
        if i % 60 == 0:
            print(f"frame {i}/{n}", flush=True)
    ff.stdin.close()
    ff.wait()
    print("done:", out)


if __name__ == "__main__":
    main()
