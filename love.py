import argparse
import math
import random
import signal
import sys
import time
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

try:
    import tkinter as tk
    import tkinter.font as tkfont
except ImportError:
    sys.exit("tkinter is not installed. Windows/macOS: reinstall Python from python.org "
             "(keep 'tcl/tk' ticked). Ubuntu/Debian: sudo apt install python3-tk")

RGB = Tuple[int, int, int]

# --------------------------------------------------------------------------- #
# Content & look
# --------------------------------------------------------------------------- #

# (language, phrase, is_right_to_left)
LANGUAGES: List[Tuple[str, str, bool]] = [
    ("English",    "I love you",                       False),
    ("Arabic",     "ﻚﺒﺣﺃ",                              True),
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
    ("Urdu",       "ﮞﻮﮨ ﯽﺗﺮﮐ/ﺎﺗﺮﮐ ﺖﺒﺤﻣ ﮯﺳ ﻢﺗ ﮟﯿﻣ",       True),
    ("Indonesian", "Aku cinta kamu",                   False),
    ("Swahili",    "Nakupenda",                        False),
    ("Persian",    "ﻡﺭﺍﺩ ﺖﺘﺳﻭﺩ",                        True),
]

TITLE = "Love in 20 Languages"
FINAL_MESSAGE = "One feeling, 20 languages. ♥"

BG: RGB = (7, 3, 13)                       # near-black with a hint of purple
FLASH: RGB = (255, 236, 246)               # the white-pink flash when a phrase appears
HALO: RGB = (110, 14, 66)                  # colour of the soft glow behind the heart
# Gradient stops, outer edge -> centre of the heart.
GRADIENT: List[RGB] = [(255, 38, 72), (255, 70, 120), (255, 100, 180),
                       (236, 105, 238), (170, 110, 255)]

# Timeline (seconds at --speed 1)
TITLE_CHAR_DELAY = 0.05
REVEAL_START = 2.3
REVEAL_DURATION = 8.0
FADE_IN, SETTLE = 0.45, 0.60               # per phrase
MESSAGE_FADE = 1.3
BEAT_PERIOD = 1.7
BEAT_SCALE = 0.028                         # heart grows by ~3 % on each beat

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


# --------------------------------------------------------------------------- #
# Heart geometry
# --------------------------------------------------------------------------- #

Point = Tuple[float, float]


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


def fit_heart(width: int, height: int, top: float, bottom: float) -> List[Point]:
    """Heart polygon in canvas pixels, centred in the band between top and bottom."""
    unit = heart_curve()
    ys = [p[1] for p in unit]
    y_mid = (max(ys) + min(ys)) / 2
    scale = min(0.90 * width / HEART_UNITS_W, (bottom - top) / HEART_UNITS_H)
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
    rtl: bool
    width: float            # measured pixel width


@dataclass
class Phrase:
    text: str
    x: float                # left edge
    y: float                # vertical centre
    width: float
    color: RGB
    ring: int
    angle: float
    start: float = 0.0      # reveal time (seconds, relative to REVEAL_START)
    core: int = 0           # canvas item ids
    glows: List[int] = field(default_factory=list)
    settled: bool = False


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


def build_layout(poly: List[Point], top: float, bottom: float, font: tkfont.Font,
                 font_px: int, rtl_visual: bool, seed: int) -> List[Phrase]:
    """Pack complete phrases into the heart, row by row, using measured widths."""
    entries = []
    for lang, text, rtl in LANGUAGES:
        shown = text[::-1] if (rtl and rtl_visual) else text
        entries.append(Entry(lang, shown, rtl, font.measure(shown)))
    queue = PhraseQueue(entries, seed)

    ys = [p[1] for p in poly]
    heart_top, heart_bottom = min(ys), max(ys)
    rows = max(3, int((heart_bottom - heart_top) / (font_px * 1.5)))
    row_h = (heart_bottom - heart_top) / rows
    half_box = font_px * 0.62
    margin = font_px * 0.45
    min_gap, max_gap = font_px * 1.0, font_px * 2.4
    centre_x = sum(p[0] for p in poly) / len(poly)
    centre_y = (heart_top + heart_bottom) / 2

    placed: List[Phrase] = []
    depths: List[float] = []

    for k in range(rows):
        yc = heart_top + (k + 0.5) * row_h
        # A text box must be inside the heart at its top, middle and bottom edges.
        runs = scan_intervals(poly, yc)
        runs = intersect(runs, scan_intervals(poly, yc - half_box))
        runs = intersect(runs, scan_intervals(poly, yc + half_box))
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
                placed.append(Phrase(e.text, x, yc, e.width, (0, 0, 0), int(depth / (row_h * 1.1)), angle))
                x += e.width + gap

    # Colour = mostly depth (red rim -> purple core) with a little top-to-bottom drift.
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


class NeonText:
    """Canvas text with a soft glow made of four dim offset copies."""

    def __init__(self, canvas: tk.Canvas, x: float, y: float, text: str, font: tkfont.Font,
                 anchor: str, spread: float) -> None:
        self.canvas = canvas
        self.glows = [canvas.create_text(x + dx * spread, y + dy * spread, text=text, font=font,
                                         anchor=anchor, fill=hexc(BG), tags=("glow",))
                      for dx, dy in GLOW_OFFSETS]
        self.core = canvas.create_text(x, y, text=text, font=font, anchor=anchor,
                                       fill=hexc(BG), tags=("core",))

    def set_text(self, text: str) -> None:
        for item in self.glows + [self.core]:
            self.canvas.itemconfigure(item, text=text)

    def set_color(self, color: RGB, glow: float = 0.30) -> None:
        self.canvas.itemconfigure(self.core, fill=hexc(color))
        g = hexc(lerp(BG, color, glow))
        for item in self.glows:
            self.canvas.itemconfigure(item, fill=g)


class LoveHeartApp:
    def __init__(self, root: tk.Tk, args: argparse.Namespace) -> None:
        self.root = root
        self.args = args
        self.stop = False
        self.canvas = tk.Canvas(root, bg=hexc(BG), highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.family = pick_family(root, ["Segoe UI", "Noto Sans", "Arial Unicode MS",
                                         "Nirmala UI", "DejaVu Sans", "Helvetica"], "TkDefaultFont")
        self.title_family = pick_family(root, ["Segoe UI Light", "Georgia", "Palatino Linotype",
                                               "DejaVu Serif", "Times New Roman"], self.family)
        self.built_size = (0, 0)
        self.resize_job = None
        self.fullscreen = args.fullscreen

        root.bind("<Escape>", lambda e: self.request_stop())
        root.bind("<q>", lambda e: self.request_stop())
        root.bind("<r>", lambda e: self.replay())
        root.bind("<F11>", lambda e: self.toggle_fullscreen())
        root.bind("<f>", lambda e: self.toggle_fullscreen())
        root.protocol("WM_DELETE_WINDOW", self.request_stop)
        self.canvas.bind("<Configure>", self.on_configure)

    # ----- lifecycle -------------------------------------------------------- #
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
        if (w, h) != self.built_size and w > 200 and h > 200:
            self.build_scene(instant=True)          # show the finished heart at the new size

    # ----- scene ------------------------------------------------------------ #
    def build_scene(self, instant: bool) -> None:
        c = self.canvas
        c.delete("all")
        w, h = c.winfo_width(), c.winfo_height()
        self.built_size = (w, h)
        self.cur_scale = 1.0

        top, bottom = h * 0.14, h * 0.90
        self.poly = fit_heart(w, h, top, bottom)
        heart_h = max(p[1] for p in self.poly) - min(p[1] for p in self.poly)
        font_px = int(max(13, min(44, heart_h / 29 * 1.02)))
        self.font_px = font_px
        spread = max(1.0, font_px / 20)
        self.fonts = {
            "phrase": tkfont.Font(family=self.family, size=-font_px, weight="bold"),
            "title": tkfont.Font(family=self.title_family, size=-int(max(24, min(64, h * 0.05)))),
            "message": tkfont.Font(family=self.title_family, size=-int(max(18, min(40, h * 0.034))),
                                   slant="italic"),
        }

        # Floating sparkles (background layer).
        rng = random.Random(self.args.seed)
        self.sparkles = []
        for _ in range(70):
            r = rng.uniform(0.8, 2.6)
            x, y = rng.uniform(0, w), rng.uniform(0, h)
            item = c.create_oval(x - r, y - r, x + r, y + r, fill=hexc(BG), outline="")
            self.sparkles.append([item, rng.uniform(8, 26), rng.uniform(0, 6.28),
                                  rng.uniform(0.5, 1.6), rng.choice(GRADIENT)])

        # Soft halo behind the text (revealed together with the phrases).
        self.halo = []
        for factor in (1.10, 1.06, 1.03, 1.0):
            cx, cy = w / 2, (top + bottom) / 2
            flat = [v for x, y in self.poly for v in (cx + (x - cx) * factor, cy + (y - cy) * factor)]
            self.halo.append(c.create_polygon(flat, fill=hexc(BG), outline="", tags=("heart", "halo")))

        # Title & final message.
        self.title = NeonText(c, w / 2, h * 0.07, "", self.fonts["title"], "center", 2)
        self.message = NeonText(c, w / 2, h * 0.955, FINAL_MESSAGE, self.fonts["message"], "center", 1.5)

        # Phrases: glow items first, cores after, so glows never cover text.
        self.phrases = build_layout(self.poly, top, bottom, self.fonts["phrase"], font_px,
                                    self.args.rtl == "visual", self.args.seed)
        for p in self.phrases:
            p.glows = [c.create_text(p.x + dx * spread, p.y + dy * spread, text=p.text,
                                     font=self.fonts["phrase"], anchor="w", fill=hexc(BG),
                                     tags=("heart", "glow")) for dx, dy in GLOW_OFFSETS]
        for p in self.phrases:
            p.core = c.create_text(p.x, p.y, text=p.text, font=self.fonts["phrase"],
                                   anchor="w", fill=hexc(BG), tags=("heart",))
            p.settled = False
        c.tag_raise("glow", "halo")
        c.tag_raise("core")

        # Timeline is kept in "animation seconds"; --speed scales real time into it.
        n = len(self.phrases)
        for i, p in enumerate(self.phrases):
            p.start = i * REVEAL_DURATION / n
        self.reveal_end = REVEAL_START + REVEAL_DURATION + FADE_IN + SETTLE
        self.first_open = 0
        self.last_pulse_level = -1
        self.title_shown = -1
        head_start = (self.reveal_end + MESSAGE_FADE + 5) / self.args.speed if instant else 0.0
        self.t0 = time.perf_counter() - head_start

    # ----- animation -------------------------------------------------------- #
    def phrase_color(self, age: float, final: RGB) -> Optional[RGB]:
        if age < 0:
            return None
        if age < FADE_IN:
            return lerp(BG, FLASH, smooth(age / FADE_IN))
        if age < FADE_IN + SETTLE:
            return lerp(FLASH, final, smooth((age - FADE_IN) / SETTLE))
        return final

    def set_phrase(self, p: Phrase, color: RGB) -> None:
        self.canvas.itemconfigure(p.core, fill=hexc(color))
        g = hexc(lerp(BG, color, 0.30))
        for item in p.glows:
            self.canvas.itemconfigure(item, fill=g)

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

        # Title typewriter.
        shown = min(len(TITLE), int(now / TITLE_CHAR_DELAY))
        if shown != self.title_shown:
            self.title_shown = shown
            self.title.set_text(TITLE[:shown])
            self.title.set_color((255, 150, 205), 0.28)

        # Phrases fade in outside-in.
        rel = now - REVEAL_START
        progress = clamp01(rel / REVEAL_DURATION)
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

        # Final message, then heartbeat.
        end = self.reveal_end
        msg_k = smooth((now - end - 0.2) / MESSAGE_FADE)
        self.message.set_color(lerp(BG, (255, 170, 215), msg_k), 0.28)
        beat_t = now - end - 0.2 - MESSAGE_FADE
        pulse = self.pulse(beat_t) if beat_t > 0 else 0.0

        # Halo grows with the reveal and flares with each beat.
        for item, base in zip(self.halo, (0.10, 0.18, 0.30, 0.46)):
            c.itemconfigure(item, fill=hexc(lerp(BG, HALO, base * progress * (1 + 0.7 * pulse))))

        level = int(pulse * 12)
        if level != self.last_pulse_level:
            self.last_pulse_level = level
            for p in phrases:
                if p.settled:
                    c.itemconfigure(p.core, fill=hexc(lerp(p.color, FLASH, 0.5 * pulse)))
        target = 1 + BEAT_SCALE * pulse
        if abs(target - self.cur_scale) > 1e-4:
            cx, cy = self.canvas.winfo_width() / 2, self.canvas.winfo_height() / 2
            ratio = target / self.cur_scale
            c.scale("heart", cx, cy, ratio, ratio)
            self.cur_scale = target

        # Sparkles drift upward and twinkle.
        h = self.canvas.winfo_height()
        fade_in = clamp01(now / 3.0)
        for item, vy, phase, twinkle, col in self.sparkles:
            c.move(item, math.sin(now * 0.6 + phase) * 0.25, -vy / 60.0)
            if c.coords(item)[1] < -6:
                c.move(item, 0, h + 12)
            tw = 0.25 + 0.35 * (0.5 + 0.5 * math.sin(now * twinkle * 2 + phase))
            c.itemconfigure(item, fill=hexc(lerp(BG, col, tw * fade_in)))

        elapsed_ms = (time.perf_counter() - started) * 1000
        self.root.after(max(1, int(16 - elapsed_ms)), self.tick)


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Love in 20 Languages - a neon heart made of 'I love you'.")
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
    height = int(sh * 0.90)
    width = min(int(sw * 0.95), int(height * 1.22))
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
