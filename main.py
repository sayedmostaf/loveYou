# #!/usr/bin/env python3
# # -*- coding: utf-8 -*-
# """
# Love in 20 Languages ♥
# ======================

# A big, glowing heart made ENTIRELY of the words "I love you" in 20 languages.
# No title, no footer, no frame: just the words, shaped like a heart.

# The heart outline is the classic parametric curve

#         x = 16 sin^3(t)
#         y = 13 cos t - 5 cos 2t - 2 cos 3t - cos 4t

# and the phrases are packed inside it row by row using their real pixel widths,
# so every phrase stays complete (smaller type fills the narrow tip). The heart
# is revealed from the outer edge toward the centre; each phrase fades in,
# flashes, and settles into a coral -> pink -> violet gradient. A heartbeat pulse
# and drifting sparkles keep it alive. Hover a phrase to see its language.

# Requirements : Python 3.8+ with tkinter (included in the Windows/macOS
#                installers; on Debian/Ubuntu: sudo apt install python3-tk).
#                No other packages.
# Run          : python love_heart.py
# Keys         : R replay   F11 / F fullscreen   Esc / Q quit   (Ctrl+C also works)
# """

import argparse
import math
import random
import signal
import sys
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

try:
    import tkinter as tk
    import tkinter.font as tkfont
except ImportError:
    sys.exit("tkinter is not installed. Windows/macOS: reinstall Python from python.org "
             "(keep 'tcl/tk' ticked). Ubuntu/Debian: sudo apt install python3-tk")

RGB = Tuple[int, int, int]
Point = Tuple[float, float]

# --------------------------------------------------------------------------- #
# Content & look
# --------------------------------------------------------------------------- #

# (language, phrase, is_right_to_left)
LANGUAGES: List[Tuple[str, str, bool]] = [
    ("English",    "I love you",                       False),
    ("Arabic",     "أحبك",                              True),
    ("Spanish",    "Te amo",                           False),
    ("French",     "Je t'aime",                        False),
    ("German",     "Ich liebe dich",                   False),
    ("Italian",    "Ti amo",                           False),
    ("Portuguese", "Eu te amo",                        False),
    ("Dutch",      "Ik hou van jou",                   False),
    ("Russian",    "Я тебя люблю",                     False),
    ("Greek",      "Σ' αγαπώ",                         False),
    ("Turkish",    "Seni seviyorum",                   False),
    ("Hindi",      "मैं तुमसे प्यार करता/करती हूँ",      False),
    ("Chinese",    "我爱你",                            False),
    ("Japanese",   "愛してる",                          False),
    ("Korean",     "사랑해",                            False),
    ("Bengali",    "আমি তোমাকে ভালোবাসি",               False),
    ("Urdu",       "میں تم سے محبت کرتا/کرتی ہوں",       True),
    ("Indonesian", "Aku cinta kamu",                   False),
    ("Swahili",    "Nakupenda",                        False),
    ("Persian",    "دوستت دارم",                        True),
]

BG: RGB = (7, 3, 13)                       # near-black with a hint of purple
AMBIENT: RGB = (120, 16, 74)               # colour of the very soft ambient light
FLASH: RGB = (255, 240, 248)               # the white-pink flash when a phrase appears
TIP_BG: RGB = (34, 18, 58)
TIP_EDGE: RGB = (255, 128, 190)
# Gradient stops, outer edge -> centre of the heart.
GRADIENT: List[RGB] = [(255, 80, 96), (255, 70, 140), (255, 100, 190),
                       (226, 105, 244), (160, 118, 255)]
GLOW = 0.22                                # strength of the glow behind words

# Timeline (animation seconds; --speed scales real time into this)
REVEAL_START = 0.6
REVEAL_DURATION = 8.5
FADE_IN, SETTLE = 0.45, 0.60               # per phrase
BEAT_PERIOD = 1.7
BEAT_SCALE = 0.026                         # heart grows by ~2.6 % on each beat
# Type tiers (fraction of the big size). Smaller tiers are used only where bigger ones cannot fit.
TIERS = [("big", 1.0), ("small", 0.72), ("tiny", 0.52)]

HEART_UNITS_W, HEART_UNITS_H = 32.0, 29.0  # approx. extent of the curve in its own units
GLOW_OFFSETS = [(-1, 0), (1, 0), (0, -1), (0, 1)]


# --------------------------------------------------------------------------- #
# Small colour / maths helpers
# --------------------------------------------------------------------------- #

def clamp01(v: float) -> float:
    return 0.0 if v < 0 else 1.0 if v > 1 else v


def smooth(v: float) -> float:
    v = clamp01(v)
    return v * v * (3 - 2 * v)


def lerp(a: RGB, b: RGB, t: float) -> RGB:
    t = clamp01(t)
    return (int(a[0] + (b[0] - a[0]) * t), int(a[1] + (b[1] - a[1]) * t),
            int(a[2] + (b[2] - a[2]) * t))


def gradient(stops: Sequence[RGB], t: float) -> RGB:
    t = clamp01(t) * (len(stops) - 1)
    i = min(int(t), len(stops) - 2)
    return lerp(stops[i], stops[i + 1], t - i)


def hexc(c: RGB) -> str:
    return "#%02x%02x%02x" % c


def rounded_rect(x1: float, y1: float, x2: float, y2: float, r: float) -> List[float]:
    """Point list for a smooth rounded rectangle (use with smooth=True)."""
    return [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
            x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]


# --------------------------------------------------------------------------- #
# Backdrop: very soft ambient light (pure Tk, no Pillow) - no visible edges
# --------------------------------------------------------------------------- #

def make_backdrop(w: int, h: int, seed: int) -> tk.PhotoImage:
    cell = 6
    gw, gh = w // cell + 2, h // cell + 2
    diag = math.hypot(w, h)
    rng = random.Random(seed)
    rows = []
    for j in range(gh):
        y = j * cell
        row = []
        for i in range(gw):
            x = i * cell
            d = math.hypot(x - w / 2, y - h * 0.48) / (0.42 * diag)
            a = 0.20 * math.exp(-2.4 * d * d)
            noise = rng.random() - 0.5                      # dithering hides banding
            row.append("#%02x%02x%02x" % tuple(
                max(0, min(255, int(BG[k] + AMBIENT[k] * a + noise))) for k in range(3)))
        rows.append(row)
    small = tk.PhotoImage(width=gw, height=gh)
    small.put(rows)
    return small.zoom(cell, cell)


# --------------------------------------------------------------------------- #
# Heart geometry
# --------------------------------------------------------------------------- #

def heart_curve(samples: int = 480) -> List[Point]:
    """Parametric heart in its own units (y pointing up)."""
    pts = []
    for i in range(samples):
        t = 2 * math.pi * i / samples
        x = 16 * math.sin(t) ** 3
        y = (13 * math.cos(t) - 5 * math.cos(2 * t)
             - 2 * math.cos(3 * t) - math.cos(4 * t))
        pts.append((x, y))
    return pts


def fit_heart(width: int, top: float, bottom: float) -> List[Point]:
    """Heart polygon in canvas pixels, centred in the band between top and bottom."""
    unit = heart_curve()
    ys = [p[1] for p in unit]
    y_mid = (max(ys) + min(ys)) / 2
    scale = min(0.94 * width / HEART_UNITS_W, (bottom - top) / HEART_UNITS_H)
    cx, cy = width / 2, (top + bottom) / 2
    return [(cx + x * scale, cy - (y - y_mid) * scale) for x, y in unit]


def scan_intervals(poly: List[Point], y: float) -> List[Tuple[float, float]]:
    """Inside intervals of the polygon along the horizontal line at y."""
    xs = []
    n = len(poly)
    for i in range(n):
        (x1, y1), (x2, y2) = poly[i], poly[(i + 1) % n]
        if (y1 <= y < y2) or (y2 <= y < y1):
            xs.append(x1 + (y - y1) * (x2 - x1) / (y2 - y1))
    xs.sort()
    return [(xs[i], xs[i + 1]) for i in range(0, len(xs) - 1, 2)]


def intersect(a: List[Tuple[float, float]], b: List[Tuple[float, float]]):
    out = []
    for a0, a1 in a:
        for b0, b1 in b:
            lo, hi = max(a0, b0), min(a1, b1)
            if hi - lo > 0:
                out.append((lo, hi))
    return out


def distance_to_edge(poly: List[Point], px: float, py: float) -> float:
    """Shortest distance from a point to the heart's outline."""
    best = float("inf")
    n = len(poly)
    for i in range(n):
        (x1, y1), (x2, y2) = poly[i], poly[(i + 1) % n]
        dx, dy = x2 - x1, y2 - y1
        seg = dx * dx + dy * dy
        t = 0.0 if seg == 0 else clamp01(((px - x1) * dx + (py - y1) * dy) / seg)
        d = math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))
        if d < best:
            best = d
    return best


# --------------------------------------------------------------------------- #
# Phrase layout
# --------------------------------------------------------------------------- #

@dataclass
class Entry:
    language: str
    text: str
    width: float            # measured pixel width


@dataclass
class Phrase:
    language: str
    text: str
    font: str               # "big" or "small"
    x: float                # left edge
    y: float                # vertical centre
    width: float
    color: RGB
    ring: int
    angle: float
    start: float = 0.0      # reveal time (animation seconds, relative to REVEAL_START)
    core: int = 0           # canvas item ids
    glows: List[int] = field(default_factory=list)
    settled: bool = False
    shown: bool = False     # items stay hidden until the phrase's reveal begins


class PhraseQueue:
    """Endless shuffled supply of phrases; keeps all 20 languages balanced."""

    def __init__(self, entries: List[Entry], seed: int) -> None:
        self.entries = entries
        self.rng = random.Random(seed)
        self.items: List[Entry] = []
        self.min_width = min(e.width for e in entries)
        self.refill()

    def refill(self) -> None:
        batch = list(self.entries)
        self.rng.shuffle(batch)
        self.items.extend(batch)

    def _find(self, limit: float, exclude: set) -> Optional[Entry]:
        for i, e in enumerate(self.items):
            if e.width <= limit and e.language not in exclude:
                return self.items.pop(i)
        return None

    def take(self, limit: float, exclude: set) -> Optional[Entry]:
        entry = self._find(limit, exclude)
        if entry is None and limit >= self.min_width and len(self.items) < 2 * len(self.entries):
            self.refill()
            entry = self._find(limit, exclude)
        return entry


def make_entries(font: tkfont.Font, rtl_visual: bool) -> List[Entry]:
    entries = []
    for lang, text, rtl in LANGUAGES:
        shown = text[::-1] if (rtl and rtl_visual) else text
        entries.append(Entry(lang, shown, font.measure(shown)))
    return entries


def build_layout(poly: List[Point], fonts: Dict[str, tkfont.Font], big_px: int,
                 rtl_visual: bool, seed: int) -> List[Phrase]:
    """Pack complete phrases into the heart, row by row, using measured widths.

    Big type is used wherever it fits; rows where no big phrase fits (lobe tops
    and the narrow tip) fall back to smaller tiers so the whole heart stays
    filled with words. Rows are justified edge to edge for a crisp silhouette.
    """
    queues = {key: PhraseQueue(make_entries(fonts[key], rtl_visual), seed + i)
              for i, (key, _) in enumerate(TIERS)}
    px = {key: max(8, int(big_px * f)) for key, f in TIERS}

    ys = [p[1] for p in poly]
    heart_top, heart_bottom = min(ys), max(ys)
    rows = max(3, int((heart_bottom - heart_top) / (big_px * 1.45)))
    row_h = (heart_bottom - heart_top) / rows
    centre_x = sum(p[0] for p in poly) / len(poly)
    centre_y = (heart_top + heart_bottom) / 2

    placed: List[Phrase] = []
    depths: List[float] = []

    def pack_row(yc: float, key: str) -> int:
        """Fill one row with `key` sized type; returns how many phrases were placed."""
        size, queue = px[key], queues[key]
        half_box = size * 0.62
        margin, min_gap, max_gap = size * 0.30, size * 0.95, size * 3.5
        # A text box must be inside the heart at its top, middle and bottom edges.
        runs = scan_intervals(poly, yc)
        runs = intersect(runs, scan_intervals(poly, yc - half_box))
        runs = intersect(runs, scan_intervals(poly, yc + half_box))
        count = 0
        for x0, x1 in runs:
            x0, x1 = x0 + margin, x1 - margin
            length = x1 - x0
            if length < queue.min_width:
                continue
            chosen: List[Entry] = []
            used = 0.0
            while True:
                remaining = length - used - (min_gap if chosen else 0)
                entry = queue.take(remaining, {e.language for e in chosen})
                if entry is None:
                    break
                chosen.append(entry)
                used += entry.width + (min_gap if len(chosen) > 1 else 0)
            if not chosen:
                continue
            total = sum(e.width for e in chosen)
            if len(chosen) > 1:
                gap = min(max_gap, (length - total) / (len(chosen) - 1))
                span = total + gap * (len(chosen) - 1)
            else:
                gap, span = 0.0, total
            x = x0 + (length - span) / 2
            for e in chosen:
                mid_x = x + e.width / 2
                depth = min(distance_to_edge(poly, x, yc), distance_to_edge(poly, mid_x, yc),
                            distance_to_edge(poly, x + e.width, yc))
                depths.append(depth)
                angle = math.atan2(mid_x - centre_x, -(yc - centre_y)) % (2 * math.pi)
                placed.append(Phrase(e.language, e.text, key, x, yc, e.width, (0, 0, 0),
                                     int(depth / (row_h * 1.1)), angle))
                x += e.width + gap
                count += 1
        return count

    for k in range(rows):
        yc = heart_top + (k + 0.5) * row_h
        for key, _ in TIERS:
            if pack_row(yc, key):
                break

    # Colour = mostly depth (coral rim -> violet core) with a little top-to-bottom drift.
    max_depth = max(depths) or 1.0
    for p, d in zip(placed, depths):
        vertical = (p.y - heart_top) / (heart_bottom - heart_top)
        p.color = gradient(GRADIENT, 0.72 * (d / max_depth) ** 0.75 + 0.28 * vertical)
    # Outer ring first; within a ring sweep clockwise starting at the top notch.
    placed.sort(key=lambda p: (p.ring, p.angle))
    return placed


# --------------------------------------------------------------------------- #
# The application
# --------------------------------------------------------------------------- #

def pick_family(root: tk.Tk, candidates: Sequence[str], fallback: str) -> str:
    available = set(tkfont.families(root))
    return next((c for c in candidates if c in available), fallback)


class LoveHeartApp:
    def __init__(self, root: tk.Tk, args: argparse.Namespace) -> None:
        self.root = root
        self.args = args
        self.stop = False
        self.canvas = tk.Canvas(root, bg=hexc(BG), highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.family = pick_family(root, ["Segoe UI", "Noto Sans", "Arial Unicode MS",
                                         "Nirmala UI", "DejaVu Sans", "Helvetica"], "TkDefaultFont")
        self.built_size = (0, 0)
        self.resize_job = None
        self.fullscreen = args.fullscreen
        self.hover: Optional[Phrase] = None
        self.pulse_now = 0.0
        self.by_item: Dict[int, Phrase] = {}

        root.bind("<Escape>", lambda e: self.request_stop())
        root.bind("<q>", lambda e: self.request_stop())
        root.bind("<r>", lambda e: self.replay())
        root.bind("<F11>", lambda e: self.toggle_fullscreen())
        root.bind("<f>", lambda e: self.toggle_fullscreen())
        root.protocol("WM_DELETE_WINDOW", self.request_stop)
        self.canvas.bind("<Configure>", self.on_configure)
        self.canvas.bind("<Motion>", self.on_motion)
        self.canvas.bind("<Leave>", lambda e: self.set_hover(None))

    # ----- window events ---------------------------------------------------- #
    def request_stop(self) -> None:
        self.stop = True

    def toggle_fullscreen(self) -> None:
        self.fullscreen = not self.fullscreen
        self.root.attributes("-fullscreen", self.fullscreen)

    def replay(self) -> None:
        self.build_scene(instant=False)

    def on_configure(self, event: tk.Event) -> None:
        if (event.width, event.height) == self.built_size:
            return
        if self.resize_job is not None:
            self.root.after_cancel(self.resize_job)
        self.resize_job = self.root.after(250, self.rebuild_after_resize)

    def rebuild_after_resize(self) -> None:
        self.resize_job = None
        w, h = self.canvas.winfo_width(), self.canvas.winfo_height()
        if (w, h) != self.built_size and w > 300 and h > 300:
            self.build_scene(instant=True)          # show the finished heart at the new size

    # ----- hover: highlight + language chip --------------------------------- #
    def on_motion(self, event: tk.Event) -> None:
        hit = None
        for item in self.canvas.find_overlapping(event.x - 1, event.y - 1, event.x + 1, event.y + 1):
            p = self.by_item.get(item)
            if p is not None and p.settled:
                hit = p
        if hit is not self.hover:
            self.set_hover(hit)
        if hit is not None:
            self.place_tip(event.x, event.y)

    def settled_color(self, p: Phrase) -> RGB:
        mix = 0.5 * self.pulse_now
        if p is self.hover:
            mix = max(mix, 0.8)
        return lerp(p.color, FLASH, mix)

    def set_hover(self, p: Optional[Phrase]) -> None:
        c = self.canvas
        old, self.hover = self.hover, p
        for ph, glow in ((old, GLOW), (p, 0.5)):
            if ph is not None:
                c.itemconfigure(ph.core, fill=hexc(self.settled_color(ph)))
                g = hexc(lerp(BG, ph.color, glow))
                for item in ph.glows:
                    c.itemconfigure(item, fill=g)
        if p is None:
            for item in self.tip_items:
                c.itemconfigure(item, state="hidden")
            return
        c.itemconfigure(self.tip_text, text=p.language)
        font = self.fonts["tip"]
        self.tip_size = (font.measure(p.language) + 24, font.metrics("linespace") + 12)
        for item in self.tip_items:
            c.itemconfigure(item, state="normal")

    def place_tip(self, mx: float, my: float) -> None:
        w, h = self.built_size
        tw, th = self.tip_size
        x = min(max(8, mx + 16), w - tw - 8)
        y = min(max(8, my + 20), h - th - 8)
        self.canvas.coords(self.tip_bg, *rounded_rect(x, y, x + tw, y + th, 12))
        self.canvas.coords(self.tip_text, x + tw / 2, y + th / 2)
        self.canvas.tag_raise("tip")

    # ----- scene ------------------------------------------------------------ #
    def build_scene(self, instant: bool) -> None:
        c = self.canvas
        c.delete("all")
        w, h = c.winfo_width(), c.winfo_height()
        self.built_size = (w, h)
        self.cur_scale = 1.0
        self.hover = None
        self.pulse_now = 0.0

        # Very soft ambient light behind everything (kept referenced for Tk).
        self.backdrop = make_backdrop(w, h, self.args.seed)
        c.create_image(0, 0, image=self.backdrop, anchor="nw")

        # No title or footer: the heart gets almost the whole window.
        top, bottom = h * 0.035, h * 0.965
        self.poly = fit_heart(w, top, bottom)
        heart_h = max(p[1] for p in self.poly) - min(p[1] for p in self.poly)
        big_px = int(max(14, min(48, heart_h / 29 * 0.86)))
        spread = max(1.0, big_px / 24)
        self.fonts = {key: tkfont.Font(family=self.family, size=-max(8, int(big_px * f)), weight="bold")
                      for key, f in TIERS}
        self.fonts["tip"] = tkfont.Font(family=self.family, size=-int(max(12, min(17, h * 0.016))),
                                        weight="bold")

        # Floating sparkles (background layer).
        rng = random.Random(self.args.seed)
        self.sparkles = []
        for _ in range(70):
            r = rng.uniform(0.8, 2.6)
            x, y = rng.uniform(0, w), rng.uniform(0, h)
            item = c.create_oval(x - r, y - r, x + r, y + r, fill=hexc(BG), outline="", state="hidden")
            self.sparkles.append([item, rng.uniform(8, 26), rng.uniform(0, 6.28),
                                  rng.uniform(0.5, 1.6), rng.choice(GRADIENT)])

        # Phrases: glow items first, cores after, so glows never cover text.
        self.phrases = build_layout(self.poly, self.fonts, big_px,
                                    self.args.rtl == "visual", self.args.seed)
        self.by_item = {}
        for p in self.phrases:
            p.glows = [c.create_text(p.x + dx * spread, p.y + dy * spread, text=p.text,
                                     font=self.fonts[p.font], anchor="w", fill=hexc(BG),
                                     state="hidden", tags=("heart", "glow")) for dx, dy in GLOW_OFFSETS]
        for p in self.phrases:
            p.core = c.create_text(p.x, p.y, text=p.text, font=self.fonts[p.font],
                                   anchor="w", fill=hexc(BG), state="hidden", tags=("heart", "core"))
            p.settled = False
            p.shown = False
            for item in p.glows + [p.core]:
                self.by_item[item] = p
        c.tag_raise("core")

        # Tooltip chip (hidden until hovering a phrase).
        self.tip_size = (10.0, 10.0)
        self.tip_bg = c.create_polygon(rounded_rect(0, 0, 10, 10, 6), smooth=True, fill=hexc(TIP_BG),
                                       outline=hexc(TIP_EDGE), width=1, state="hidden", tags=("tip",))
        self.tip_text = c.create_text(0, 0, text="", font=self.fonts["tip"], fill=hexc(FLASH),
                                      state="hidden", tags=("tip",))
        self.tip_items = [self.tip_bg, self.tip_text]

        # Timeline is kept in "animation seconds"; --speed scales real time into it.
        n = len(self.phrases)
        for i, p in enumerate(self.phrases):
            p.start = i * REVEAL_DURATION / n
        self.reveal_end = REVEAL_START + REVEAL_DURATION + FADE_IN + SETTLE
        self.first_open = 0
        self.last_pulse_level = -1
        head_start = (self.reveal_end + 5) / self.args.speed if instant else 0.0
        self.t0 = time.perf_counter() - head_start

    # ----- animation -------------------------------------------------------- #0
    @staticmethod
    def phrase_color(age: float, final: RGB) -> Optional[RGB]:
        if age < 0:
            return None
        if age < FADE_IN:
            return lerp(BG, FLASH, smooth(age / FADE_IN))
        if age < FADE_IN + SETTLE:
            return lerp(FLASH, final, smooth((age - FADE_IN) / SETTLE))
        return final

    def set_phrase(self, p: Phrase, color: RGB) -> None:
        c = self.canvas
        if not p.shown:
            p.shown = True
            for item in p.glows + [p.core]:
                c.itemconfigure(item, state="normal")
        c.itemconfigure(p.core, fill=hexc(color))
        g = hexc(lerp(BG, color, GLOW))
        for item in p.glows:
            c.itemconfigure(item, fill=g)

    @staticmethod
    def pulse(t: float) -> float:
        """Double 'lub-dub' heartbeat envelope in [0, 1]."""
        t %= BEAT_PERIOD
        return max(math.exp(-((t - 0.12) / 0.06) ** 2), 0.65 * math.exp(-((t - 0.40) / 0.07) ** 2))

    def tick(self) -> None:
        if self.stop:
            self.root.destroy()
            return
        started = time.perf_counter()
        now = (started - self.t0) * self.args.speed      # animation seconds
        c = self.canvas

        # Phrases fade in outside-in.
        rel = now - REVEAL_START
        phrases = self.phrases
        n = len(phrases)
        i = self.first_open
        while i < n:
            p = phrases[i]
            age = rel - p.start
            if age < 0:
                break                                   # later phrases start even later
            color = self.phrase_color(age, p.color)
            if color is not None and not p.settled:
                self.set_phrase(p, color)
                if age >= FADE_IN + SETTLE:
                    p.settled = True
            i += 1
        while self.first_open < n and phrases[self.first_open].settled:
            self.first_open += 1

        # Heartbeat once the heart is complete.
        beat_t = now - self.reveal_end - 0.4
        pulse = self.pulse(beat_t) if beat_t > 0 else 0.0
        self.pulse_now = pulse
        level = int(pulse * 12)
        if level != self.last_pulse_level:
            self.last_pulse_level = level
            for p in phrases:
                if p.settled:
                    c.itemconfigure(p.core, fill=hexc(self.settled_color(p)))
        target = 1 + BEAT_SCALE * pulse
        if abs(target - self.cur_scale) > 1e-4:
            ratio = target / self.cur_scale
            c.scale("heart", self.built_size[0] / 2, self.built_size[1] / 2, ratio, ratio)
            self.cur_scale = target

        # Sparkles drift upward and twinkle.
        h = self.built_size[1]
        fade_in = clamp01(now / 3.0)
        for item, vy, phase, twinkle, col in self.sparkles:
            c.move(item, math.sin(now * 0.6 + phase) * 0.25, -vy / 60.0)
            if c.coords(item)[1] < -6:
                c.move(item, 0, h + 12)
            tw = 0.25 + 0.35 * (0.5 + 0.5 * math.sin(now * twinkle * 2 + phase))
            c.itemconfigure(item, fill=hexc(lerp(BG, col, tw * fade_in)),
                            state="normal" if fade_in > 0.05 else "hidden")

        elapsed_ms = (time.perf_counter() - started) * 1000
        self.root.after(max(1, int(16 - elapsed_ms)), self.tick)


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Love in 20 Languages - a heart made of 'I love you'.")
    parser.add_argument("--speed", type=float, default=1.0, help="animation speed multiplier (default 1.0)")
    parser.add_argument("--seed", type=int, default=7, help="phrase arrangement seed (default 7)")
    parser.add_argument("--fullscreen", action="store_true", help="start fullscreen (F11 toggles)")
    parser.add_argument("--rtl", choices=("logical", "visual"), default="logical",
                        help="Arabic/Persian/Urdu: 'logical' = as stored (default); "
                             "'visual' = reversed, for Tk builds without bidi support")
    args = parser.parse_args(argv)
    if args.speed <= 0:
        parser.error("--speed must be positive")
    return args


def enable_hidpi() -> None:
    """Crisp text on Windows high-DPI screens."""
    if sys.platform == "win32":
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass                                    # very old Windows: nothing to enable


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    enable_hidpi()
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        print(f"Could not open a window ({exc}). Run this on a desktop session.", file=sys.stderr)
        return 2

    root.title("Love in 20 Languages ♥")
    root.configure(bg=hexc(BG))
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    height = int(sh * 0.92)
    width = min(int(sw * 0.95), int(height * 1.15))
    root.geometry(f"{width}x{height}+{(sw - width) // 2}+{max(0, (sh - height) // 6)}")
    if args.fullscreen:
        root.attributes("-fullscreen", True)

    app = LoveHeartApp(root, args)
    # Ctrl+C in the launching terminal: just flag it; the animation loop closes the window.
    signal.signal(signal.SIGINT, lambda *_: app.request_stop())

    root.update()                                   # make sure the canvas has its real size
    app.build_scene(instant=False)
    root.after(16, app.tick)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())