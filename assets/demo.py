"""Build the before/after demo GIF in this folder.

    python3 assets/demo.py

A dev-only script: it needs Pillow, ffmpeg and a monospace font. Holdback itself
is standard library only and never imports any of this.

The simulation is a Claude Code window given the same question twice. Without
Holdback the question is answered by editing two files. With Holdback the edit
is held, in Holdback's own words, and the question is answered instead.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile

from PIL import Image, ImageDraw, ImageFont

S = 2  # supersample factor
W, H = 960, 500
FPS = 20

FONTS = [
    ("/System/Library/Fonts/Menlo.ttc", 0, 1),
    ("/Library/Fonts/DejaVuSansMono.ttf", 0, 0),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 0, 0),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf", 0, 0),
    ("C:/Windows/Fonts/consola.ttf", 0, 0),
]
FS = 16
CW = FS * 0.6
LH = 25

BG = (26, 26, 28)
CHROME = (35, 35, 39)
CHROME_LINE = (48, 48, 53)
TEXT = (232, 230, 227)
DIM = (125, 122, 118)
FAINT = (86, 84, 81)
BORDER = (58, 58, 62)
AMBER = (217, 162, 78)
AMBER_DIM = (158, 121, 66)
GREY_CHIP = (138, 135, 130)

DOTS = [(255, 95, 86), (255, 189, 46), (39, 201, 63)]

PROMPT = "why does the login redirect loop?"

BEFORE = [
    ("say", "Looking at the auth guard now."),
    ("", ""),
    ("tool", "Update(src/auth.ts)"),
    ("res", "Updated src/auth.ts with 6 additions and 2 removals"),
    ("", ""),
    ("tool", "Update(src/middleware.ts)"),
    ("res", "Updated src/middleware.ts with 3 additions and 1 removal"),
    ("", ""),
    ("say", "Fixed it \u2014 the guard redirected before the session cookie was"),
    ("cont", "read. I changed the order and added a case for /callback."),
]

HELD = [
    ("tool", "Update(src/auth.ts)"),
]

AFTER = [
    ("held", "Holdback: held. This call would change src/auth.ts, and the"),
    ("held2", "person's message doesn't tell you to do any work (Holdback"),
    ("held2", "read it as: a question about why the login redirect loops)."),
    ("", ""),
    ("say", "The guard redirects before the session cookie is read, so"),
    ("cont", "/callback bounces back to /login and round it goes. Nothing"),
    ("cont", "changed."),
]

FOOT_BEFORE = "You asked a question. Two files changed."
FOOT_AFTER = "You asked a question. You got an answer."


def _face(bold):
    for path, regular, heavy in FONTS:
        if os.path.exists(path):
            return path, heavy if bold else regular
    raise SystemExit("no monospace font found; add one to FONTS at the top of this file")


def font(size=FS, bold=False):
    path, index = _face(bold)
    return ImageFont.truetype(path, size * S, index=index)


F = font()
FB = font(bold=True)
FSM = font(13)


def chars(lines):
    """Flat character count of a (kind, text) line list, newlines included."""
    return sum(len(t) + 1 for _, t in lines)


def reveal(lines, n):
    """The first n characters of the line list, as whole lines."""
    out, left = [], n
    for kind, text in lines:
        if left <= 0:
            break
        out.append((kind, text[:left]))
        left -= len(text) + 1
    return out


class Canvas:
    def __init__(self):
        self.im = Image.new("RGB", (W * S, H * S), BG)
        self.d = ImageDraw.Draw(self.im)

    def rect(self, box, fill=None, outline=None, radius=0, width=1):
        box = [v * S for v in box]
        if radius:
            self.d.rounded_rectangle(box, radius=radius * S, fill=fill,
                                     outline=outline, width=width * S)
        else:
            self.d.rectangle(box, fill=fill, outline=outline, width=width * S)

    def text(self, xy, s, f=F, fill=TEXT):
        self.d.text((xy[0] * S, xy[1] * S), s, font=f, fill=fill)

    def dot(self, x, y, r, fill):
        self.d.ellipse([x * S, y * S, (x + r) * S, (y + r) * S], fill=fill)

    def out(self):
        return self.im.resize((W, H), Image.LANCZOS)


def chrome(c):
    c.rect([0, 0, W, 36], fill=CHROME)
    c.rect([0, 36, W, 37], fill=CHROME_LINE)
    for i, col in enumerate(DOTS):
        c.dot(18 + i * 19, 13, 11, col)
    c.text((W / 2 - 46, 10), "claude code", f=FSM, fill=FAINT)


def chip(c, label, after):
    y = 60
    col = AMBER if after else GREY_CHIP
    c.dot(28, y + 4, 9, col)
    c.text((45, y), label, f=FB, fill=col)


def prompt_box(c, typed, caret):
    y = 92
    c.rect([28, y, W - 28, y + 40], outline=BORDER, radius=7)
    c.text((44, y + 11), ">", fill=FAINT)
    c.text((66, y + 11), typed, fill=TEXT)
    if caret:
        c.rect([67 + len(typed) * CW, y + 11, 75 + len(typed) * CW, y + 30], fill=(150, 148, 144))


def body(c, lines, y0=158):
    y = y0
    for kind, text in lines:
        if kind in ("say", "tool") and text:
            c.dot(29, y + 6, 8, TEXT)
            c.text((48, y), text, fill=TEXT)
        elif kind == "cont" and text:
            c.text((48, y), text, fill=TEXT)
        elif kind == "res" and text:
            c.text((48, y), "\u2514", fill=FAINT)
            c.text((68, y), text, fill=DIM)
        elif kind == "held" and text:
            c.text((48, y), "\u2514", fill=AMBER_DIM)
            c.text((68, y), text, fill=AMBER)
        elif kind == "held2" and text:
            c.text((68, y), text, fill=AMBER)
        y += LH
    return y


def foot(c, text, col=FAINT):
    c.rect([28, H - 56, W - 28, H - 55], fill=(40, 40, 44))
    c.text((28, H - 42), text, f=FSM, fill=col)


def frame(after, typed, caret, shown, show_foot):
    c = Canvas()
    chrome(c)
    chip(c, "With Holdback" if after else "Without Holdback", after)
    prompt_box(c, typed, caret)
    body(c, shown)
    if show_foot:
        foot(c, FOOT_AFTER if after else FOOT_BEFORE, col=AMBER_DIM if after else FAINT)
    return c.out()


def build():
    frames = []

    def add(im, n=1):
        for _ in range(n):
            frames.append(im)

    def fade(a, b, n=5):
        for i in range(1, n + 1):
            frames.append(Image.blend(a, b, i / (n + 1)))

    def typing(after):
        add(frame(after, "", True, [], False), 8 if after else 12)
        for i in range(1, len(PROMPT) + 1, 2):
            add(frame(after, PROMPT[:i], True, [], False))
        add(frame(after, PROMPT, True, [], False), 4)
        add(frame(after, PROMPT, False, [], False), 8)

    # --- Without Holdback ----------------------------------------------------
    typing(False)
    for n in range(6, chars(BEFORE) + 6, 7):
        add(frame(False, PROMPT, False, reveal(BEFORE, n), False))
    add(frame(False, PROMPT, False, BEFORE, False), 6)
    add(frame(False, PROMPT, False, BEFORE, True), 46)

    # --- With Holdback -------------------------------------------------------
    fade(frame(False, PROMPT, False, BEFORE, True), frame(True, "", True, [], False))
    typing(True)
    for n in range(6, chars(HELD) + 6, 7):
        add(frame(True, PROMPT, False, reveal(HELD, n), False))
    add(frame(True, PROMPT, False, HELD, False), 12)
    for n in range(6, chars(AFTER) + 6, 7):
        add(frame(True, PROMPT, False, HELD + reveal(AFTER, n), False))
    add(frame(True, PROMPT, False, HELD + AFTER, False), 6)
    last = frame(True, PROMPT, False, HELD + AFTER, True)
    add(last, 52)
    fade(last, frame(False, "", True, [], False))
    return frames


def run(args):
    if shutil.which("ffmpeg") is None:
        raise SystemExit("ffmpeg is not installed")
    subprocess.run(["ffmpeg", "-y", "-v", "error"] + args, check=True)


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    gif = sys.argv[1] if len(sys.argv) > 1 else os.path.join(here, "holdback-demo.gif")
    tmp = tempfile.mkdtemp(prefix="holdback-demo-")
    try:
        frames = build()
        for i, im in enumerate(frames):
            im.save(os.path.join(tmp, "f%04d.png" % i))
        palette = os.path.join(tmp, "palette.png")
        run(["-framerate", str(FPS), "-i", os.path.join(tmp, "f%04d.png"),
             "-vf", "palettegen=max_colors=96:stats_mode=diff", palette])
        run(["-framerate", str(FPS), "-i", os.path.join(tmp, "f%04d.png"), "-i", palette,
             "-lavfi", "paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle",
             "-loop", "0", gif])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("%s  %dx%d  %d frames  %.1fs  %.0fKB"
          % (gif, W, H, len(frames), len(frames) / FPS, os.path.getsize(gif) / 1024))


if __name__ == "__main__":
    main()
