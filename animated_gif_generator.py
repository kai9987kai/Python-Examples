#!/usr/bin/env python3
"""Generate randomized, looping animated GIF artwork using Pillow.

Install:  python -m pip install pillow
Example:  python random_animated_gifs.py --count 5 --size 400 --frames 60 --fps 20
"""

import argparse
import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

TAU = 2 * math.pi
PALETTES = [
    [(255, 68, 170), (105, 80, 255), (50, 235, 250), (255, 220, 90)],
    [(255, 117, 75), (255, 207, 89), (255, 83, 122), (142, 75, 255)],
    [(91, 255, 187), (65, 165, 255), (182, 103, 255), (255, 255, 156)],
    [(255, 168, 241), (133, 211, 255), (175, 255, 209), (255, 241, 181)],
]
MOTIONS = ("orbit", "spiral", "rain", "bounce", "burst", "mandala")
SHAPES = ("circle", "ring", "triangle", "square", "diamond", "pentagon", "star")


def draw_shape(draw, kind, x, y, radius, angle, colour):
    """Draw one geometric shape on an RGBA canvas."""
    r = max(2, radius)
    if kind == "circle":
        draw.ellipse((x-r, y-r, x+r, y+r), fill=colour)
    elif kind == "ring":
        draw.ellipse((x-r, y-r, x+r, y+r), outline=colour,
                     width=max(2, int(r / 3)))
    else:
        sides = {"triangle": 3, "square": 4, "diamond": 4,
                 "pentagon": 5, "star": 10}[kind]
        offset = math.pi / 4 if kind == "diamond" else -math.pi / 2
        points = []
        for j in range(sides):
            rr = r * (0.43 if kind == "star" and j % 2 else 1)
            a = angle + offset + TAU * j / sides
            points.append((x + rr * math.cos(a), y + rr * math.sin(a)))
        draw.polygon(points, fill=colour)


def make_background(size, colour):
    """A dark colour-tinted gradient, constructed only once per GIF."""
    bg = Image.new("RGBA", (size, size))
    d = ImageDraw.Draw(bg)
    for y in range(size):
        k = y / max(1, size - 1)
        rgb = tuple(int(3 + channel * (0.025 + 0.045 * k)) for channel in colour)
        d.line((0, y, size, y), fill=(*rgb, 255))
    return bg


def position(obj, motion, frame, total, size):
    """Calculate a shape's position at a given frame."""
    t = TAU * frame / total
    cx = cy = size / 2
    r = obj["orbit"]
    phase = obj["phase"]
    speed = obj["speed"]

    if motion == "orbit":
        a = phase + t * speed
        return cx + r * math.cos(a), cy + 0.72 * r * math.sin(a)
    if motion == "spiral":
        a = phase + t * speed
        rr = (r + frame * speed * size / total * 0.21) % (size * 0.53)
        return cx + rr * math.cos(a), cy + rr * math.sin(a)
    if motion == "rain":
        return (obj["x"] + 12 * math.sin(t + phase)) % size, \
               (obj["y"] + frame * speed * size / total) % size
    if motion == "bounce":
        return obj["x"] + 0.17 * size * math.sin(t * speed + phase), \
               obj["y"] + 0.17 * size * math.cos(t * obj["frequency"] + phase)
    if motion == "burst":
        rr = (r + frame * speed * size / total * 0.4) % (size * 0.63)
        return cx + rr * math.cos(phase), cy + rr * math.sin(phase)
    # A symmetric, rotating mandala.
    a = phase + t * speed
    return cx + r * math.cos(a), cy + r * math.sin(a)


def render_gif(destination, rng, size, frames, fps):
    """Render and save one independently randomized artwork."""
    motion = rng.choice(MOTIONS)
    palette = rng.choice(PALETTES)
    background = make_background(size, rng.choice(palette))
    glow = rng.choice((True, True, False))
    trails = rng.choice((True, True, False))
    waves = rng.choice((True, False))
    symmetry = rng.choice((5, 6, 7, 8)) if motion == "mandala" else 1
    count = rng.randint(12, 22) if motion == "mandala" else rng.randint(24, 45)

    objects = []
    for _ in range(count):
        objects.append({
            "x": rng.uniform(0, size),
            "y": rng.uniform(0, size),
            "orbit": rng.uniform(size * 0.05, size * 0.49),
            "phase": rng.uniform(0, TAU),
            "speed": rng.choice((1, 2, 3)) * rng.choice((-1, 1)),
            "frequency": rng.randint(1, 3),
            "radius": rng.uniform(size * 0.012, size * 0.045),
            "shape": rng.choice(SHAPES),
            "colour": rng.choice(palette),
        })
    stars = [(rng.randrange(size), rng.randrange(size), rng.uniform(0, TAU))
             for _ in range(40)]
    output = []

    for frame in range(frames):
        t = TAU * frame / frames
        picture = background.copy()
        d = ImageDraw.Draw(picture, "RGBA")

        # Twinkling stars and occasional animated sine-wave ribbons.
        for sx, sy, p in stars:
            brightness = int(35 + 110 * (0.5 + 0.5 * math.sin(t * 2 + p)))
            d.point((sx, sy), fill=(210, 225, 255, brightness))
        if waves:
            for j in range(3):
                y0 = size * (0.27 + 0.22 * j)
                points = [(x, y0 + size * 0.065 * math.sin(
                    (x / size) * TAU * (2 + j) + t * (j + 1)))
                    for x in range(0, size + 4, 4)]
                d.line(points, fill=(*palette[j % len(palette)], 65), width=2)

        artwork = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        ad = ImageDraw.Draw(artwork, "RGBA")
        for obj in objects:
            for sector in range(symmetry):
                # Each sector rotates the entire point around the centre.
                sector_angle = TAU * sector / symmetry
                trail_steps = range(5, -1, -1) if trails else (0,)
                for lag in trail_steps:
                    px, py = position(obj, motion, frame - lag * 0.65, frames, size)
                    if symmetry > 1:
                        dx, dy = px - size / 2, py - size / 2
                        px = size / 2 + dx * math.cos(sector_angle) - dy * math.sin(sector_angle)
                        py = size / 2 + dx * math.sin(sector_angle) + dy * math.cos(sector_angle)
                    alpha = 232 if lag == 0 else int(25 + 64 * (1 - lag / 6))
                    radius = obj["radius"] * (1 if lag == 0 else 0.78)
                    rotation = obj["phase"] + t * obj["speed"] + sector_angle
                    draw_shape(ad, obj["shape"], px, py, radius, rotation,
                               (*obj["colour"], alpha))

        if glow:
            blurred = artwork.filter(ImageFilter.GaussianBlur(max(4, size // 45)))
            picture = Image.alpha_composite(picture, blurred)
        picture = Image.alpha_composite(picture, artwork)
        # GIF uses indexed colours: quantize each frame to a compact palette.
        output.append(picture.convert("RGB").quantize(colors=128))

    output[0].save(destination, save_all=True, append_images=output[1:],
                   duration=round(1000 / fps), loop=0, disposal=2,
                   optimize=False)
    return motion, glow, trails, waves


def main():
    parser = argparse.ArgumentParser(description="Generate random animated GIF art")
    parser.add_argument("--count", type=int, default=4, help="GIFs to generate")
    parser.add_argument("--size", type=int, default=360, help="Square image size in pixels")
    parser.add_argument("--frames", type=int, default=48, help="Frames per GIF")
    parser.add_argument("--fps", type=int, default=20, help="Frames per second")
    parser.add_argument("--seed", type=int, default=None, help="Reproduce the same artwork")
    parser.add_argument("--output", type=Path, default=Path("random_gifs"))
    args = parser.parse_args()
    if args.count < 1 or args.size < 64 or args.frames < 2 or not 1 <= args.fps <= 100:
        parser.error("Requires count >= 1, size >= 64, frames >= 2, 1 <= fps <= 100")
    args.output.mkdir(parents=True, exist_ok=True)
    rng = random.Random(args.seed)

    for index in range(1, args.count + 1):
        path = args.output / f"random_animation_{index:02d}.gif"
        motion, glow, trails, waves = render_gif(
            path, rng, args.size, args.frames, args.fps)
        print(f"Created {path} | motion={motion} glow={glow} "
              f"trails={trails} waves={waves}")


if __name__ == "__main__":
    main()
