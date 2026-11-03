#!/usr/bin/env python3
"""PRISM BREAKER: REFORGED - a complete, asset-free arcade brick breaker.

Requires Python 3.10+ and pygame 2.5+ (pip install pygame).
Play: python PRISM_BREAKER_REFORGED.py

Original gameplay concept: Brickout by Christian Bender, provided by the user.
This implementation is a substantially new program with independent physics,
levels, effects, sound synthesis, controls, and progression.
"""

from __future__ import annotations

import json
import math
import os
import random
import sys
import tempfile
from array import array
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

try:
    import pygame
except ImportError:
    raise SystemExit(
        "Pygame is not installed. Install it with: python -m pip install pygame"
    ) from None

V = pygame.Vector2
W, H = 1280, 720
LEFT, RIGHT, TOP, BOTTOM = 54, 1226, 106, 704
PADDLE_Y = 632
SHIELD_Y = 680
STEP = 1.0 / 120.0
FPS_LIMIT = 120
TAU = math.tau

BG = (6, 10, 27)
TEXT = (226, 241, 255)
MUTED = (123, 149, 179)
CYAN = (68, 241, 255)
MAGENTA = (247, 80, 219)
GOLD = (255, 209, 94)
GREEN = (98, 255, 166)
RED = (255, 91, 126)
BLUE = (104, 133, 255)
PALETTE = [CYAN, BLUE, MAGENTA, (255, 125, 110), GOLD, GREEN, (175, 121, 255)]

DIFFICULTIES = {
    "ZEN": {"speed": 400, "lives": 5, "paddle": 166, "drop": 0.26, "bonus": 0.8},
    "ARCADE": {"speed": 500, "lives": 3, "paddle": 138, "drop": 0.19, "bonus": 1.0},
    "OVERDRIVE": {"speed": 605, "lives": 2, "paddle": 118, "drop": 0.14, "bonus": 1.4},
}
POWERUPS = {
    "expand": ("WIDE", CYAN, 16.0),
    "multi": ("MULTIBALL", MAGENTA, 0.0),
    "laser": ("LASER", RED, 14.0),
    "magnet": ("MAGNET", BLUE, 15.0),
    "slow": ("SLOW", GREEN, 12.0),
    "pierce": ("PIERCE", GOLD, 10.0),
    "shield": ("SHIELD +2", (167, 250, 211), 0.0),
    "life": ("EXTRA LIFE", (255, 152, 186), 0.0),
}
LEVEL_NAMES = [
    "FIRST LIGHT", "SPLIT SIGNAL", "DOUBLE HELIX", "PULSE ENGINE",
    "FRACTAL CORE", "QUANTUM ARRAY", "PRISM STORM", "EVENT HORIZON",
]
SAVE_FILE = Path.home() / ".prism_breaker_reforged.json"


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def mix(a: tuple[int, int, int], b: tuple[int, int, int], strength: float) -> tuple[int, int, int]:
    t = clamp(strength, 0, 1)
    return tuple(int(x + (y - x) * t) for x, y in zip(a, b))


def collide_swept_circle_rect(
    pos: V, velocity: V, radius: float, rect: pygame.Rect, dt: float
) -> Optional[tuple[float, V]]:
    """Continuous circle-vs-AABB intersection with genuine rounded corners.

    Returns earliest time-of-impact and outward collision normal, or None.
    Face hits are tested on their finite segments; corner hits solve the
    ray/circle quadratic. This avoids axis and corner tunnelling.
    """
    px, py, vx, vy = pos.x, pos.y, velocity.x, velocity.y
    candidates: list[tuple[float, V]] = []
    epsilon = 1e-8

    if vx > epsilon:
        t = (rect.left - radius - px) / vx
        if 0 <= t <= dt and rect.top - epsilon <= py + vy * t <= rect.bottom + epsilon:
            candidates.append((t, V(-1, 0)))
    elif vx < -epsilon:
        t = (rect.right + radius - px) / vx
        if 0 <= t <= dt and rect.top - epsilon <= py + vy * t <= rect.bottom + epsilon:
            candidates.append((t, V(1, 0)))

    if vy > epsilon:
        t = (rect.top - radius - py) / vy
        if 0 <= t <= dt and rect.left - epsilon <= px + vx * t <= rect.right + epsilon:
            candidates.append((t, V(0, -1)))
    elif vy < -epsilon:
        t = (rect.bottom + radius - py) / vy
        if 0 <= t <= dt and rect.left - epsilon <= px + vx * t <= rect.right + epsilon:
            candidates.append((t, V(0, 1)))

    a = vx * vx + vy * vy
    if a > epsilon:
        for cx, cy, sx, sy in (
            (rect.left, rect.top, -1, -1),
            (rect.right, rect.top, 1, -1),
            (rect.left, rect.bottom, -1, 1),
            (rect.right, rect.bottom, 1, 1),
        ):
            dx, dy = px - cx, py - cy
            b = 2 * (dx * vx + dy * vy)
            c = dx * dx + dy * dy - radius * radius
            disc = b * b - 4 * a * c
            if disc < 0:
                continue
            t = (-b - math.sqrt(disc)) / (2 * a)
            if not (0 <= t <= dt):
                continue
            hx, hy = px + vx * t, py + vy * t
            if (hx - cx) * sx < -epsilon or (hy - cy) * sy < -epsilon:
                continue
            normal = V(hx - cx, hy - cy)
            if normal.length_squared() > epsilon:
                normal.normalize_ip()
                if velocity.dot(normal) < 0:
                    candidates.append((t, normal))

    return min(candidates, key=lambda item: item[0]) if candidates else None


def load_records() -> dict:
    try:
        data = json.loads(SAVE_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {
                "best": int(clamp(int(data.get("best", 0)), 0, 10**12)),
                "total_bricks": int(clamp(int(data.get("total_bricks", 0)), 0, 10**12)),
                "games": int(clamp(int(data.get("games", 0)), 0, 10**9)),
                "sound": bool(data.get("sound", True)),
                "difficulty": data.get("difficulty", "ARCADE") if data.get("difficulty") in DIFFICULTIES else "ARCADE",
            }
    except (OSError, ValueError, TypeError):
        pass
    return {"best": 0, "total_bricks": 0, "games": 0, "sound": True, "difficulty": "ARCADE"}


def save_records(records: dict) -> None:
    """Atomic save: don't corrupt an existing record if writing is interrupted."""
    tmp_name = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=SAVE_FILE.parent,
            prefix=".prism_breaker_", suffix=".tmp", delete=False
        ) as handle:
            json.dump(records, handle, separators=(",", ":"))
            tmp_name = handle.name
        os.replace(tmp_name, SAVE_FILE)
    except OSError:
        if tmp_name:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass


@dataclass
class Ball:
    pos: V
    vel: V
    radius: float = 9.0
    attached: bool = False
    trail: list[V] = field(default_factory=list)
    immunity: dict[int, float] = field(default_factory=dict)


@dataclass
class Paddle:
    x: float = W / 2
    width: float = 138
    height: float = 18
    vx: float = 0

    @property
    def rect(self) -> pygame.Rect:
        return pygame.Rect(round(self.x - self.width / 2), PADDLE_Y,
                           round(self.width), round(self.height))


@dataclass
class Brick:
    home_x: float
    y: float
    width: float
    height: float
    hp: int
    max_hp: int
    color: tuple[int, int, int]
    kind: str = "normal"
    phase: float = 0.0
    x: float = 0.0

    def __post_init__(self) -> None:
        self.x = self.home_x

    @property
    def rect(self) -> pygame.Rect:
        return pygame.Rect(round(self.x), round(self.y), round(self.width), round(self.height))


@dataclass
class Powerup:
    pos: V
    kind: str
    time: float = 0.0


@dataclass
class Particle:
    pos: V
    vel: V
    color: tuple[int, int, int]
    life: float
    max_life: float
    radius: float
    gravity: float = 0.0


@dataclass
class Bolt:
    pos: V


@dataclass
class Floater:
    pos: V
    caption: str
    color: tuple[int, int, int]
    time: float = 1.0


class Audio:
    """Synthesizes PCM sound effects; no music files, downloads, or assets."""

    def __init__(self) -> None:
        self.sounds: dict[str, pygame.mixer.Sound] = {}
        self.ready = pygame.mixer.get_init() is not None
        if not self.ready:
            return
        for name, f0, f1, duration, shape in (
            ("wall", 390, 250, .065, "sine"),
            ("paddle", 220, 520, .095, "sine"),
            ("brick", 560, 880, .080, "triangle"),
            ("explode", 210, 55, .27, "noise"),
            ("power", 430, 980, .22, "sine"),
            ("shot", 870, 260, .10, "triangle"),
            ("lost", 360, 90, .38, "triangle"),
            ("clear", 430, 1020, .53, "sine"),
            ("start", 260, 710, .26, "sine"),
        ):
            try:
                self.sounds[name] = self.make_sound(f0, f1, duration, shape)
            except pygame.error:
                self.ready = False
                break

    @staticmethod
    def make_sound(f0: float, f1: float, duration: float, shape: str) -> pygame.mixer.Sound:
        sample_rate, fmt, channels = pygame.mixer.get_init()
        # Stereo and mono are supported, with correct signed-16-bit samples.
        if fmt != -16:
            raise pygame.error("Audio backend must support signed 16-bit PCM")
        samples = array("h")
        phase = 0.0
        count = max(1, int(sample_rate * duration))
        for i in range(count):
            t = i / count
            frequency = f0 + (f1 - f0) * t
            phase += TAU * frequency / sample_rate
            if shape == "noise":
                wave = random.uniform(-1, 1)
            elif shape == "triangle":
                wave = 2 / math.pi * math.asin(math.sin(phase))
            else:
                wave = math.sin(phase) + 0.18 * math.sin(2 * phase)
            envelope = min(1.0, t * 45) * (1.0 - t) ** 2
            sample = int(clamp(wave * envelope * 10500, -32767, 32767))
            samples.extend((sample,) * channels)
        return pygame.mixer.Sound(buffer=samples.tobytes())

    def play(self, name: str, enabled: bool = True) -> None:
        if enabled and self.ready and name in self.sounds:
            self.sounds[name].play()


class Game:
    def __init__(self, *, headless: bool = False) -> None:
        pygame.mixer.pre_init(22050, -16, 2, 512)
        pygame.init()
        pygame.display.set_caption("PRISM BREAKER // REFORGED")
        self.headless = headless
        self.window_size = (1280, 720)
        self.flags = pygame.RESIZABLE
        self.screen = pygame.display.set_mode(self.window_size, self.flags)
        self.canvas = pygame.Surface((W, H)).convert()
        self.scene = pygame.Surface((W, H)).convert()
        self.background = self.create_background()
        self.clock = pygame.time.Clock()
        self.font_xl = pygame.font.SysFont("consolas", 69, bold=True)
        self.font_big = pygame.font.SysFont("consolas", 38, bold=True)
        self.font_h2 = pygame.font.SysFont("consolas", 24, bold=True)
        self.font_body = pygame.font.SysFont("consolas", 19, bold=True)
        self.font_small = pygame.font.SysFont("consolas", 14)
        self.font_tiny = pygame.font.SysFont("consolas", 12)
        self.records = load_records()
        self.difficulty = self.records["difficulty"]
        self.mode = "CAMPAIGN"
        self.sound_on = self.records["sound"]
        self.audio = Audio()
        self.state = "menu"
        self.buttons: list[tuple[pygame.Rect, str]] = []
        self.mouse_target = W / 2
        self.mouse_timer = 0.0
        self.firing = False
        self.fullscreen = False
        self.time = 0.0
        self.run_time = 0.0
        self.accumulator = 0.0
        self.elapsed = 0.0
        self.shake = 0.0
        self.score = 0
        self.lives = 3
        self.level = 1
        self.combo = 0
        self.best_combo = 0
        self.destroyed = 0
        self.total_bricks = 0
        self.powerups_collected = 0
        self.paddle = Paddle()
        self.balls: list[Ball] = []
        self.bricks: list[Brick] = []
        self.drops: list[Powerup] = []
        self.particles: list[Particle] = []
        self.bolts: list[Bolt] = []
        self.floaters: list[Floater] = []
        self.timers: dict[str, float] = {}
        self.shield_charges = 0
        self.shot_cooldown = 0.0
        self.transition_time = 0.0
        self.stars = [
            (random.randrange(W), random.randrange(H), random.uniform(.4, 2.0), random.uniform(0, TAU))
            for _ in range(95)
        ]

    def create_background(self) -> pygame.Surface:
        surface = pygame.Surface((W, H)).convert()
        for y in range(H):
            t = y / H
            color = (int(7 + 6 * t), int(11 + 5 * t), int(28 + 13 * t))
            pygame.draw.line(surface, color, (0, y), (W, y))
        for x in range(0, W, 50):
            pygame.draw.line(surface, (18, 30, 55), (x, TOP), (x, H), 1)
        for y in range(TOP, H, 50):
            pygame.draw.line(surface, (18, 30, 55), (0, y), (W, y), 1)
        pygame.draw.line(surface, (26, 62, 85), (LEFT, TOP), (LEFT, BOTTOM))
        pygame.draw.line(surface, (26, 62, 85), (RIGHT, TOP), (RIGHT, BOTTOM))
        return surface

    def text(self, dst: pygame.Surface, words: str, x: float, y: float,
             *, font: Optional[pygame.font.Font] = None, color=TEXT,
             anchor: str = "topleft") -> pygame.Rect:
        image = (font or self.font_body).render(str(words), True, color)
        rect = image.get_rect()
        setattr(rect, anchor, (round(x), round(y)))
        dst.blit(image, rect)
        return rect

    def sound(self, name: str) -> None:
        self.audio.play(name, self.sound_on)

    def new_game(self) -> None:
        options = DIFFICULTIES[self.difficulty]
        self.state = "playing"
        self.score = 0
        self.lives = int(options["lives"])
        self.level = 1
        self.elapsed = 0.0
        self.destroyed = 0
        self.best_combo = 0
        self.powerups_collected = 0
        self.paddle = Paddle(W / 2, float(options["paddle"]))
        self.mouse_timer = 0.0
        self.mouse_target = self.paddle.x
        self.records["games"] += 1
        self.write_records()
        self.load_level()
        self.sound("start")

    def write_records(self) -> None:
        self.records["difficulty"] = self.difficulty
        self.records["sound"] = self.sound_on
        save_records(self.records)

    def load_level(self) -> None:
        self.balls = []
        self.bricks = []
        self.drops = []
        self.bolts = []
        self.floaters = []
        self.particles = []
        self.timers = {}
        self.shield_charges = 0
        self.combo = 0
        self.shot_cooldown = 0.0
        self.shake = 0.0
        self.paddle.width = float(DIFFICULTIES[self.difficulty]["paddle"])
        self.paddle.x = W / 2
        level = self.level
        rows = min(8, 4 + (level + 1) // 2)
        cols = 12
        brick_w, brick_h = 82, 27
        step_x, step_y = 90, 35
        start_x = (W - (cols - 1) * step_x - brick_w) / 2
        start_y = 161
        rng = random.Random(level * 16547 + 71)
        for row in range(rows):
            for col in range(cols):
                if not self.brick_enabled(row, col, level, rng):
                    continue
                difficulty_hp = int(level >= 4 and (row + col) % 5 == 0)
                difficulty_hp += int(level >= 7 and (row * 3 + col) % 9 == 0)
                hp = min(3, 1 + difficulty_hp)
                kind = "normal"
                if level >= 3 and (row * 11 + col * 7 + level) % 19 == 0:
                    kind = "explosive"
                    hp = 1
                elif level >= 5 and row % 2 == 0 and col % 4 == 0:
                    kind = "moving"
                color = PALETTE[(row + level // 2) % len(PALETTE)]
                self.bricks.append(Brick(start_x + col * step_x, start_y + row * step_y,
                                         brick_w, brick_h, hp, hp, color, kind,
                                         (col + row) * 0.64))
        self.total_bricks = len(self.bricks)
        self.attach_new_ball()

    @staticmethod
    def brick_enabled(row: int, col: int, level: int, rng: random.Random) -> bool:
        kind = (level - 1) % 8
        if kind == 0:  # classic band
            return True
        if kind == 1:  # chevrons
            return not ((row + col) % 5 == 0 and row > 0)
        if kind == 2:  # double helix
            return abs(col - (5.5 + 3.5 * math.sin(row * 1.7))) < 2.9 or abs(col - (5.5 - 3.5 * math.sin(row * 1.7))) < 2.9
        if kind == 3:  # glitch checker
            return (row + col) % 4 != 0
        if kind == 4:  # diamond and rim
            return abs(col - 5.5) + abs(row - 3) * 1.5 < 8.0
        if kind == 5:  # lanes
            return col % 4 != 1 or row % 3 == 0
        if kind == 6:  # wave
            return row < 2 or (col + row * row) % 5 != 1
        if level <= 8:
            return True
        return rng.random() < clamp(.78 + level * .005, .78, .94)

    def attach_new_ball(self) -> None:
        self.balls = [Ball(V(self.paddle.x, PADDLE_Y - 11), V(0, 0), attached=True)]

    def launch(self) -> None:
        speed = self.ball_speed()
        released = 0
        for ball in self.balls:
            if ball.attached:
                angle = random.choice((-1, 1)) * random.uniform(.24, .55)
                ball.vel = V(math.sin(angle), -math.cos(angle)) * speed
                ball.attached = False
                released += 1
        if released:
            self.sound("paddle")

    def ball_speed(self) -> float:
        base = float(DIFFICULTIES[self.difficulty]["speed"])
        level_scale = 1 + min(.38, (self.level - 1) * .045)
        slow_scale = .67 if self.timers.get("slow", 0) > 0 else 1.0
        return base * level_scale * slow_scale

    def spawn_particles(self, where: V, color: tuple[int, int, int],
                        amount: int = 10, spread: float = 220) -> None:
        for _ in range(amount):
            if len(self.particles) >= 310:
                break
            angle = random.uniform(0, TAU)
            speed = random.uniform(35, spread)
            lifetime = random.uniform(.22, .72)
            self.particles.append(Particle(where.copy(), V(math.cos(angle), math.sin(angle)) * speed,
                                           color, lifetime, lifetime, random.uniform(1.5, 4.2), 80))

    def show_floater(self, label: str, position: V, color=CYAN) -> None:
        if len(self.floaters) < 30:
            self.floaters.append(Floater(position.copy(), label, color))

    def damage_brick(self, brick: Brick, *, by_explosion: bool = False, depth: int = 0) -> None:
        if brick not in self.bricks:
            return
        brick.hp -= 1
        center = V(brick.rect.center)
        self.spawn_particles(center, brick.color, 7 if brick.hp else 16)
        self.shake = max(self.shake, 1.8)
        self.combo += 1
        self.best_combo = max(self.combo, self.best_combo)
        multiplier = min(8, 1 + self.combo // 5)
        bonus = float(DIFFICULTIES[self.difficulty]["bonus"])
        gain = int((35 if brick.hp > 0 else 100 + 50 * (brick.max_hp - 1)) * multiplier * bonus)
        self.score += gain
        if brick.hp > 0:
            self.sound("brick")
            return

        self.bricks.remove(brick)
        self.destroyed += 1
        self.records["total_bricks"] += 1
        if self.score > self.records["best"]:
            self.records["best"] = self.score
        self.sound("explode" if brick.kind == "explosive" else "brick")
        if self.combo % 8 == 0:
            self.show_floater(f"{multiplier}X COMBO", center, GOLD)
        if (not by_explosion or random.random() < .2) and random.random() < DIFFICULTIES[self.difficulty]["drop"]:
            kind = random.choices(list(POWERUPS), weights=[17, 17, 15, 12, 12, 10, 11, 6])[0]
            self.drops.append(Powerup(center.copy(), kind))
        if brick.kind == "explosive" and depth < 3:
            self.shake = max(self.shake, 10)
            self.spawn_particles(center, GOLD, 30, 380)
            for other in list(self.bricks):
                if V(other.rect.center).distance_squared_to(center) < 120**2:
                    self.damage_brick(other, by_explosion=True, depth=depth + 1)

    def use_powerup(self, kind: str) -> None:
        label, color, duration = POWERUPS[kind]
        self.powerups_collected += 1
        self.show_floater(label, V(self.paddle.x, PADDLE_Y - 32), color)
        self.spawn_particles(V(self.paddle.x, PADDLE_Y), color, 20)
        self.sound("power")
        if kind == "multi":
            moving = [ball for ball in self.balls if not ball.attached]
            if not moving:
                self.launch()
                moving = [ball for ball in self.balls if not ball.attached]
            for source in moving[:3]:
                for angle in (-.31, .31):
                    if len(self.balls) >= 8:
                        break
                    self.balls.append(Ball(source.pos.copy(), source.vel.rotate_rad(angle)))
        elif kind == "shield":
            self.shield_charges = min(5, self.shield_charges + 2)
        elif kind == "life":
            self.lives = min(9, self.lives + 1)
        else:
            existing = self.timers.get(kind, 0) > 0
            self.timers[kind] = max(self.timers.get(kind, 0), duration)
            if kind == "slow" and not existing:
                for ball in self.balls:
                    ball.vel *= .67

    def finish_game(self, victory: bool = False) -> None:
        self.state = "victory" if victory else "game_over"
        self.records["best"] = max(self.records["best"], self.score)
        self.write_records()
        self.sound("clear" if victory else "lost")

    def next_level(self) -> None:
        self.level += 1
        self.load_level()
        self.state = "playing"
        self.sound("start")

    def move_paddle(self, dt: float) -> None:
        old_x = self.paddle.x
        keys = pygame.key.get_pressed()
        direction = int(keys[pygame.K_RIGHT] or keys[pygame.K_d]) - int(keys[pygame.K_LEFT] or keys[pygame.K_a])
        if direction:
            self.paddle.x += direction * 900 * dt
            self.mouse_timer = 0
        elif self.mouse_timer > 0:
            # Smooth but sufficiently fast to preserve precise mouse control.
            self.paddle.x += (self.mouse_target - self.paddle.x) * min(1, 25 * dt)
        self.paddle.x = clamp(self.paddle.x, LEFT + self.paddle.width / 2,
                              RIGHT - self.paddle.width / 2)
        self.paddle.vx = clamp((self.paddle.x - old_x) / max(dt, .0001), -1000, 1000)

    def paddle_hit(self, ball: Ball) -> None:
        if self.timers.get("magnet", 0) > 0:
            ball.attached = True
            ball.vel = V(0, 0)
            ball.pos = V(clamp(ball.pos.x, self.paddle.rect.left + 10,
                               self.paddle.rect.right - 10), PADDLE_Y - ball.radius - .5)
        else:
            hit_pos = clamp((ball.pos.x - self.paddle.x) / (self.paddle.width / 2), -.98, .98)
            angle = hit_pos * math.radians(66)
            speed = max(ball.vel.length(), self.ball_speed())
            ball.vel = V(math.sin(angle) * speed + self.paddle.vx * .12,
                         -abs(math.cos(angle) * speed))
            if abs(ball.vel.x) < speed * .065:
                ball.vel.x = speed * .065 * random.choice((-1, 1))
            ball.vel.scale_to_length(speed)
            ball.pos.y = PADDLE_Y - ball.radius - .5
        self.combo = 0
        self.sound("paddle")
        self.shake = max(self.shake, 2.5)
        self.spawn_particles(V(ball.pos.x, PADDLE_Y), CYAN, 5, 115)

    def advance_ball(self, ball: Ball, dt: float) -> None:
        if ball.attached:
            ball.pos = V(clamp(ball.pos.x + self.paddle.vx * dt,
                               self.paddle.rect.left + ball.radius,
                               self.paddle.rect.right - ball.radius),
                         PADDLE_Y - ball.radius - 1)
            return

        for identifier in list(ball.immunity):
            ball.immunity[identifier] -= dt
            if ball.immunity[identifier] <= 0:
                del ball.immunity[identifier]

        remaining = dt
        for _ in range(8):
            if remaining <= 0.000001 or ball.attached:
                break
            best_t = remaining + 0.01
            hit_type: Optional[str] = None
            normal = V()
            hit_brick: Optional[Brick] = None
            vx, vy = ball.vel.x, ball.vel.y
            if vx < -1e-8:
                t = (LEFT + ball.radius - ball.pos.x) / vx
                if 0 <= t <= remaining and t < best_t:
                    best_t, hit_type, normal = t, "wall", V(1, 0)
            if vx > 1e-8:
                t = (RIGHT - ball.radius - ball.pos.x) / vx
                if 0 <= t <= remaining and t < best_t:
                    best_t, hit_type, normal = t, "wall", V(-1, 0)
            if vy < -1e-8:
                t = (TOP + ball.radius - ball.pos.y) / vy
                if 0 <= t <= remaining and t < best_t:
                    best_t, hit_type, normal = t, "wall", V(0, 1)

            if vy > 0:
                hit = collide_swept_circle_rect(ball.pos, ball.vel, ball.radius,
                                                 self.paddle.rect, remaining)
                if hit and hit[0] < best_t and hit[1].y < -.25:
                    best_t, normal = hit
                    hit_type = "paddle"
                if self.shield_charges > 0 and ball.pos.y <= SHIELD_Y - ball.radius:
                    t = (SHIELD_Y - ball.radius - ball.pos.y) / vy
                    if 0 <= t <= remaining and t < best_t:
                        best_t, hit_type, normal = t, "shield", V(0, -1)

            for brick in self.bricks:
                if id(brick) in ball.immunity:
                    continue
                hit = collide_swept_circle_rect(ball.pos, ball.vel, ball.radius,
                                                 brick.rect, remaining)
                if hit and hit[0] < best_t:
                    best_t, normal = hit
                    hit_type, hit_brick = "brick", brick

            if hit_type is None:
                ball.pos += ball.vel * remaining
                break

            ball.pos += ball.vel * max(0, best_t)
            remaining -= max(0, best_t)
            if hit_type == "brick" and hit_brick is not None:
                self.damage_brick(hit_brick)
                if self.timers.get("pierce", 0) > 0:
                    ball.immunity[id(hit_brick)] = .19
                    # No bounce: forward progress prevents repeated t=0 contacts.
                    step_forward = min(remaining, .0004)
                    ball.pos += ball.vel * step_forward
                    remaining -= step_forward
                    continue
            if hit_type == "paddle":
                self.paddle_hit(ball)
                continue
            if hit_type == "shield":
                self.shield_charges -= 1
                self.spawn_particles(V(ball.pos.x, SHIELD_Y), GREEN, 23)
                self.sound("paddle")
            elif hit_type == "wall":
                self.sound("wall")

            if ball.vel.dot(normal) < 0:
                ball.vel = ball.vel.reflect(normal)
            ball.pos += normal * .075
            # Small temporal advance prevents repeated numerical zero-time collisions.
            nudge = min(remaining, .00003)
            ball.pos += ball.vel * nudge
            remaining -= nudge

    def advance_bolts(self, dt: float) -> None:
        for bolt in self.bolts[:]:
            # Sweep bullets over their full vertical travel to prevent tunnelling.
            travel = 1150 * dt
            x, y = bolt.pos.x, bolt.pos.y
            target = None
            nearest = float("-inf")
            for brick in self.bricks:
                rect = brick.rect
                if rect.left - 3 <= x <= rect.right + 3 and y >= rect.top and y - travel <= rect.bottom:
                    hit_y = min(y, rect.bottom)
                    if target is None or hit_y > nearest:
                        target, nearest = brick, hit_y
            bolt.pos.y -= travel
            if target is not None:
                if bolt in self.bolts:
                    self.bolts.remove(bolt)
                self.damage_brick(target)
                self.spawn_particles(V(x, nearest), RED, 7)
            elif bolt.pos.y < TOP:
                self.bolts.remove(bolt)

    def fire_lasers(self) -> None:
        if self.timers.get("laser", 0) <= 0 or self.shot_cooldown > 0:
            return
        half = self.paddle.width * .36
        for offset in (-half, half):
            self.bolts.append(Bolt(V(self.paddle.x + offset, PADDLE_Y - 4)))
        self.shot_cooldown = .26
        self.sound("shot")

    def update_play(self, dt: float) -> None:
        self.elapsed += dt
        self.mouse_timer = max(0, self.mouse_timer - dt)
        self.move_paddle(dt)
        self.shot_cooldown = max(0, self.shot_cooldown - dt)
        self.shake = max(0, self.shake - dt * 30)
        for name in list(self.timers):
            before = self.timers[name]
            self.timers[name] = max(0, before - dt)
            if before > 0 and self.timers[name] <= 0:
                if name == "slow":
                    for ball in self.balls:
                        ball.vel /= .67
                del self.timers[name]
        target_width = float(DIFFICULTIES[self.difficulty]["paddle"])
        if self.timers.get("expand", 0) > 0:
            target_width *= 1.54
        self.paddle.width += (target_width - self.paddle.width) * min(1, dt * 12)
        self.paddle.x = clamp(self.paddle.x, LEFT + self.paddle.width / 2, RIGHT - self.paddle.width / 2)
        for brick in self.bricks:
            if brick.kind == "moving":
                brick.x = brick.home_x + math.sin(self.elapsed * 1.3 + brick.phase) * 11
        if self.firing or pygame.key.get_pressed()[pygame.K_f]:
            self.fire_lasers()

        self.advance_bolts(dt)
        for ball in self.balls[:]:
            self.advance_ball(ball, dt)
            if not ball.attached:
                ball.trail.append(ball.pos.copy())
                if len(ball.trail) > 16:
                    ball.trail.pop(0)
            if ball.pos.y - ball.radius > BOTTOM:
                if ball in self.balls:
                    self.balls.remove(ball)
                self.spawn_particles(ball.pos, RED, 19, 260)

        if not self.balls:
            self.lives -= 1
            self.combo = 0
            self.sound("lost")
            self.shake = max(self.shake, 14)
            if self.lives <= 0:
                self.finish_game()
            else:
                self.attach_new_ball()
                self.timers.pop("magnet", None)

        for drop in self.drops[:]:
            drop.time += dt
            drop.pos.y += 172 * dt
            hitbox = pygame.Rect(round(drop.pos.x - 13), round(drop.pos.y - 13), 26, 26)
            if hitbox.colliderect(self.paddle.rect):
                self.drops.remove(drop)
                self.use_powerup(drop.kind)
            elif drop.pos.y > BOTTOM + 25:
                self.drops.remove(drop)

        for particle in self.particles[:]:
            particle.life -= dt
            if particle.life <= 0:
                self.particles.remove(particle)
                continue
            particle.vel.y += particle.gravity * dt
            particle.pos += particle.vel * dt
        for floater in self.floaters[:]:
            floater.time -= dt
            floater.pos.y -= 41 * dt
            if floater.time <= 0:
                self.floaters.remove(floater)

        if self.state == "playing" and not self.bricks:
            self.state = "level_clear"
            self.transition_time = 2.1
            self.score += self.lives * 200 + max(0, int((100 - self.elapsed) * 3))
            self.records["best"] = max(self.records["best"], self.score)
            self.write_records()
            self.sound("clear")

    def update(self, dt: float) -> None:
        self.time += dt
        if self.state == "playing":
            self.update_play(dt)
        elif self.state == "level_clear":
            self.transition_time -= dt
            if self.transition_time <= 0:
                if self.mode == "CAMPAIGN" and self.level >= len(LEVEL_NAMES):
                    self.finish_game(victory=True)
                else:
                    self.next_level()

    def draw_glow(self, dest: pygame.Surface, center: V | tuple,
                  color: tuple[int, int, int], radius: float) -> None:
        px, py = int(center[0]), int(center[1])
        r = max(2, int(radius))
        for factor, weight in ((2.5, .15), (1.75, .22), (1.2, .4)):
            c = mix(BG, color, weight)
            pygame.draw.circle(dest, c, (px, py), int(r * factor))

    def draw_background(self, dest: pygame.Surface) -> None:
        dest.blit(self.background, (0, 0))
        for x, y, size, phase in self.stars:
            twinkle = .4 + .6 * (1 + math.sin(self.time * (1 + size * .35) + phase)) / 2
            color = mix((28, 43, 76), (80, 130, 181), twinkle)
            pygame.draw.circle(dest, color, (int(x), int((y + self.time * size * 2.5) % H)),
                               max(1, round(size)))
        # Horizon and soft accent lines.
        pygame.draw.line(dest, (35, 84, 102), (LEFT, TOP), (RIGHT, TOP), 2)
        pygame.draw.line(dest, (18, 53, 76), (LEFT, BOTTOM), (RIGHT, BOTTOM), 1)

    def draw_bricks(self, dest: pygame.Surface) -> None:
        for brick in self.bricks:
            rect = brick.rect
            color = brick.color
            shadow = rect.move(0, 3)
            pygame.draw.rect(dest, mix(BG, color, .22), shadow, border_radius=6)
            pygame.draw.rect(dest, mix(BG, color, .43), rect, border_radius=6)
            inner = rect.inflate(-4, -6)
            pygame.draw.rect(dest, mix((34, 43, 64), color, .82 if brick.hp == 1 else .63),
                             inner, border_radius=4)
            pygame.draw.line(dest, mix(color, TEXT, .45),
                             (rect.left + 6, rect.top + 4), (rect.right - 6, rect.top + 4), 2)
            if brick.hp > 1:
                for i in range(brick.hp):
                    pygame.draw.rect(dest, (9, 16, 33),
                                     (rect.centerx - brick.hp * 7 + i * 14, rect.centery + 4, 9, 4),
                                     border_radius=2)
            if brick.kind == "explosive":
                self.text(dest, "*", rect.centerx, rect.centery - 2,
                          font=self.font_h2, color=GOLD, anchor="center")
            elif brick.kind == "moving":
                pygame.draw.circle(dest, TEXT, rect.center, 3)

    def draw_paddle(self, dest: pygame.Surface) -> None:
        rect = self.paddle.rect
        tint = RED if self.timers.get("laser", 0) > 0 else CYAN
        self.draw_glow(dest, rect.center, tint, 16)
        pygame.draw.rect(dest, mix(BG, tint, .35), rect.inflate(10, 7), border_radius=12)
        pygame.draw.rect(dest, tint, rect, border_radius=9)
        pygame.draw.rect(dest, mix(tint, TEXT, .58), rect.inflate(-12, -10), border_radius=5)
        pygame.draw.line(dest, TEXT, (rect.left + 14, rect.top + 3),
                         (rect.right - 14, rect.top + 3), 2)
        if self.timers.get("laser", 0) > 0:
            for xx in (rect.left + 10, rect.right - 10):
                pygame.draw.rect(dest, RED, (xx - 4, rect.top - 12, 8, 16), border_radius=3)
        if self.timers.get("magnet", 0) > 0:
            pygame.draw.arc(dest, BLUE, rect.inflate(24, 20), math.pi, TAU, 2)
        if self.shield_charges:
            pygame.draw.line(dest, GREEN, (LEFT + 7, SHIELD_Y), (RIGHT - 7, SHIELD_Y), 3)
            for xx in range(LEFT + 10, RIGHT - 10, 40):
                pygame.draw.line(dest, mix(BG, GREEN, .37),
                                 (xx, SHIELD_Y - 3), (xx + 17, SHIELD_Y - 3), 2)

    def draw_balls(self, dest: pygame.Surface) -> None:
        piercing = self.timers.get("pierce", 0) > 0
        color = GOLD if piercing else CYAN
        for ball in self.balls:
            for i, trailpos in enumerate(ball.trail):
                f = (i + 1) / max(1, len(ball.trail))
                pygame.draw.circle(dest, mix(BG, color, .12 + .38 * f),
                                   (round(trailpos.x), round(trailpos.y)), max(1, round(ball.radius * f)))
            self.draw_glow(dest, ball.pos, color, ball.radius)
            pygame.draw.circle(dest, color, (round(ball.pos.x), round(ball.pos.y)), round(ball.radius))
            pygame.draw.circle(dest, (255, 255, 255),
                               (round(ball.pos.x - 2), round(ball.pos.y - 3)), 3)
            if piercing:
                pygame.draw.circle(dest, GOLD, (round(ball.pos.x), round(ball.pos.y)),
                                   round(ball.radius) + 6, 1)

    def draw_drops(self, dest: pygame.Surface) -> None:
        for drop in self.drops:
            label, color, _ = POWERUPS[drop.kind]
            center = (round(drop.pos.x), round(drop.pos.y))
            self.draw_glow(dest, center, color, 13)
            shape = [
                (center[0], center[1] - 13), (center[0] + 13, center[1]),
                (center[0], center[1] + 13), (center[0] - 13, center[1]),
            ]
            pygame.draw.polygon(dest, color, shape, 2)
            self.text(dest, label[0], *center, font=self.font_small, color=TEXT, anchor="center")

    def draw_effects(self, dest: pygame.Surface) -> None:
        for bolt in self.bolts:
            x, y = round(bolt.pos.x), round(bolt.pos.y)
            pygame.draw.line(dest, mix(BG, RED, .4), (x, y + 14), (x, y - 22), 10)
            pygame.draw.line(dest, RED, (x, y + 11), (x, y - 20), 3)
        for particle in self.particles:
            fade = particle.life / particle.max_life
            color = mix(BG, particle.color, fade)
            pygame.draw.circle(dest, color, (round(particle.pos.x), round(particle.pos.y)),
                               max(1, round(particle.radius * fade)))
        for floater in self.floaters:
            self.text(dest, floater.caption, floater.pos.x, floater.pos.y,
                      font=self.font_body, color=mix(BG, floater.color, floater.time), anchor="center")

    def draw_hud(self, dest: pygame.Surface) -> None:
        pygame.draw.rect(dest, (9, 18, 39), (0, 0, W, 94))
        pygame.draw.line(dest, (30, 83, 98), (0, 93), (W, 93), 2)
        self.text(dest, "PRISM / BREAKER", 28, 13, font=self.font_h2, color=CYAN)
        self.text(dest, "REFORGED EDITION", 30, 46, font=self.font_small, color=MUTED)
        self.text(dest, f"SCORE  {self.score:07,d}", 323, 21, font=self.font_h2)
        self.text(dest, f"BEST  {max(self.records['best'], self.score):07,d}", 324, 55,
                  font=self.font_small, color=MUTED)
        self.text(dest, f"LEVEL {self.level:02d}", 639, 20, font=self.font_h2, color=GOLD)
        self.text(dest, f"{self.mode} / {self.difficulty}", 641, 55,
                  font=self.font_small, color=MUTED)
        self.text(dest, f"LIVES {self.lives}", 878, 20, font=self.font_h2, color=GREEN)
        self.text(dest, f"COMBO {self.combo:02d}", 879, 55, font=self.font_small, color=MUTED)
        remaining = len(self.bricks)
        ratio = 1 - remaining / max(1, self.total_bricks)
        pygame.draw.rect(dest, (29, 45, 66), (1070, 29, 170, 9), border_radius=5)
        pygame.draw.rect(dest, CYAN, (1070, 29, round(170 * ratio), 9), border_radius=5)
        self.text(dest, f"{remaining} BRICKS LEFT", 1070, 50, font=self.font_small, color=MUTED)
        x = 33
        for name, duration in self.timers.items():
            if duration <= 0:
                continue
            label, color, total = POWERUPS[name]
            width = max(95, len(label) * 10 + 18)
            box = pygame.Rect(x, 111, width, 27)
            pygame.draw.rect(dest, mix(BG, color, .21), box, border_radius=6)
            pygame.draw.rect(dest, color, box, 1, border_radius=6)
            self.text(dest, f"{label} {duration:.0f}s", x + 7, 116,
                      font=self.font_small, color=color)
            x += width + 8
        if self.shield_charges:
            self.text(dest, f"SHIELD x{self.shield_charges}", 1020, 111,
                      font=self.font_small, color=GREEN)
        self.text(dest, "MOUSE / A-D / ARROWS: MOVE    SPACE / CLICK: LAUNCH    F / HOLD CLICK: LASER    P / ESC: PAUSE    M: MUTE    F11: FULLSCREEN",
                  W / 2, 707, font=self.font_tiny, color=MUTED, anchor="midbottom")
        if any(ball.attached for ball in self.balls) and self.state == "playing":
            self.text(dest, "PRESS SPACE OR CLICK TO LAUNCH", W / 2, 562,
                      font=self.font_body, color=CYAN, anchor="center")

    def panel(self, dest: pygame.Surface, rect: pygame.Rect) -> None:
        tint = pygame.Surface(rect.size, pygame.SRCALPHA)
        tint.fill((8, 17, 38, 246))
        dest.blit(tint, rect.topleft)
        pygame.draw.rect(dest, (52, 103, 128), rect, 2, border_radius=10)
        pygame.draw.line(dest, CYAN, (rect.left + 22, rect.top),
                         (rect.left + 150, rect.top), 3)

    def add_button(self, dest: pygame.Surface, caption: str, rect: pygame.Rect,
                   action: str, *, primary: bool = False) -> None:
        self.buttons.append((rect, action))
        mx, my = self.to_world(pygame.mouse.get_pos())
        hover = rect.collidepoint(mx, my)
        color = CYAN if primary else BLUE
        fill = mix(BG, color, .37 if hover else (.24 if primary else .12))
        pygame.draw.rect(dest, fill, rect, border_radius=8)
        pygame.draw.rect(dest, color if hover or primary else mix(BG, color, .56),
                         rect, 2, border_radius=8)
        self.text(dest, caption, rect.centerx, rect.centery, font=self.font_body,
                  color=TEXT if hover else mix(TEXT, color, .1), anchor="center")

    def dim(self, dest: pygame.Surface, opacity: int = 194) -> None:
        film = pygame.Surface((W, H), pygame.SRCALPHA)
        film.fill((4, 10, 24, opacity))
        dest.blit(film, (0, 0))

    def draw_menu(self, dest: pygame.Surface) -> None:
        self.buttons.clear()
        self.dim(dest, 105)
        self.panel(dest, pygame.Rect(156, 102, 968, 518))
        self.text(dest, "PRISM BREAKER", W / 2, 151, font=self.font_xl, color=TEXT, anchor="center")
        self.text(dest, "R E F O R G E D    /    N E O N   A R C A D E", W / 2, 201,
                  font=self.font_body, color=CYAN, anchor="center")
        self.text(dest, "Rebuild the signal. Shatter the core. Master the chaos.", W / 2, 249,
                  font=self.font_body, color=MUTED, anchor="center")
        self.add_button(dest, "START GAME", pygame.Rect(465, 288, 350, 53), "start", primary=True)
        self.add_button(dest, f"MODE  < {self.mode} >", pygame.Rect(465, 351, 350, 43), "mode")
        self.add_button(dest, f"DIFFICULTY  < {self.difficulty} >", pygame.Rect(465, 404, 350, 43), "difficulty")
        self.add_button(dest, "HOW TO PLAY", pygame.Rect(465, 457, 350, 43), "help")
        self.add_button(dest, f"SOUND: {'ON' if self.sound_on else 'OFF'}", pygame.Rect(465, 510, 350, 43), "sound")
        self.text(dest, f"PERSONAL BEST: {self.records['best']:,}", 183, 584,
                  font=self.font_small, color=GOLD)
        self.text(dest, f"BRICKS DESTROYED: {self.records['total_bricks']:,}", 1090, 584,
                  font=self.font_small, color=MUTED, anchor="topright")

    def draw_help(self, dest: pygame.Surface) -> None:
        self.buttons.clear()
        self.dim(dest, 210)
        self.panel(dest, pygame.Rect(160, 77, 960, 568))
        self.text(dest, "HOW TO PLAY", W / 2, 124, font=self.font_big, color=CYAN, anchor="center")
        lines = [
            "BOUNCE the ball off the paddle and destroy every brick to advance.",
            "MOUSE, A/D or LEFT/RIGHT moves the paddle. SPACE/CLICK launches.",
            "F or HOLD LEFT CLICK fires when LASER is active.",
            "P or ESC pauses. M mutes. F11 toggles fullscreen.",
            "BRICK TYPES: standard, reinforced (multiple hits), explosive (*)",
            "and moving (white indicator). Chain explosions for huge combos.",
            "POWER-UPS: WIDE / MULTIBALL / LASER / MAGNET / SLOW /",
            "PIERCE / SHIELD / EXTRA LIFE. Collect the falling diamonds.",
            "A MAGNET catches balls: press SPACE or CLICK to release.",
            "Each fifth brick hit increases your score multiplier (max x8).",
            "CAMPAIGN: eight stages. ENDLESS: procedural difficulty growth.",
            "ZEN = forgiving / ARCADE = standard / OVERDRIVE = intense.",
        ]
        for i, line in enumerate(lines):
            self.text(dest, line, 207, 178 + i * 31, font=self.font_body if i in (0, 4, 6) else self.font_small,
                      color=TEXT if i in (0, 4, 6) else MUTED)
        self.add_button(dest, "BACK TO MENU", pygame.Rect(464, 571, 352, 49), "menu", primary=True)

    def draw_pause(self, dest: pygame.Surface) -> None:
        self.buttons.clear()
        self.dim(dest, 208)
        self.panel(dest, pygame.Rect(397, 185, 486, 346))
        self.text(dest, "PAUSED", W / 2, 246, font=self.font_xl, color=CYAN, anchor="center")
        self.text(dest, "The signal is suspended", W / 2, 297,
                  font=self.font_body, color=MUTED, anchor="center")
        self.add_button(dest, "RESUME", pygame.Rect(462, 348, 357, 53), "resume", primary=True)
        self.add_button(dest, "RESTART", pygame.Rect(462, 414, 357, 43), "restart")
        self.add_button(dest, "MAIN MENU", pygame.Rect(462, 467, 357, 43), "menu")

    def draw_level_clear(self, dest: pygame.Surface) -> None:
        self.dim(dest, 153)
        self.text(dest, "SECTOR CLEARED", W / 2, 275, font=self.font_xl, color=GREEN, anchor="center")
        self.text(dest, f"STAGE {self.level} COMPLETE  /  SCORE {self.score:,}", W / 2, 340,
                  font=self.font_h2, color=TEXT, anchor="center")
        self.text(dest, "Synchronising next sector...", W / 2, 396,
                  font=self.font_body, color=MUTED, anchor="center")

    def draw_end(self, dest: pygame.Surface) -> None:
        self.buttons.clear()
        self.dim(dest, 202)
        self.panel(dest, pygame.Rect(289, 145, 702, 431))
        won = self.state == "victory"
        self.text(dest, "CORE RESTORED" if won else "SIGNAL LOST", W / 2, 209,
                  font=self.font_big, color=GREEN if won else RED, anchor="center")
        self.text(dest, f"FINAL SCORE     {self.score:,}", W / 2, 281,
                  font=self.font_h2, anchor="center")
        self.text(dest, f"PERSONAL BEST  {self.records['best']:,}", W / 2, 321,
                  font=self.font_body, color=GOLD, anchor="center")
        self.text(dest, f"LEVEL {self.level}    BRICKS {self.destroyed}    BEST COMBO {self.best_combo}",
                  W / 2, 363, font=self.font_small, color=MUTED, anchor="center")
        self.add_button(dest, "PLAY AGAIN", pygame.Rect(453, 413, 375, 52), "restart", primary=True)
        self.add_button(dest, "MAIN MENU", pygame.Rect(453, 475, 375, 44), "menu")

    def draw(self) -> None:
        self.draw_background(self.scene)
        if self.state != "menu" and self.state != "help":
            self.draw_bricks(self.scene)
            self.draw_paddle(self.scene)
            self.draw_drops(self.scene)
            self.draw_balls(self.scene)
            self.draw_effects(self.scene)
        self.canvas.fill(BG)
        offset = (round(random.uniform(-self.shake, self.shake)),
                  round(random.uniform(-self.shake, self.shake))) if self.shake > .5 and self.state == "playing" else (0, 0)
        self.canvas.blit(self.scene, offset)
        if self.state in ("playing", "paused", "level_clear", "game_over", "victory"):
            self.draw_hud(self.canvas)
        if self.state == "menu":
            self.draw_menu(self.canvas)
        elif self.state == "help":
            self.draw_help(self.canvas)
        elif self.state == "paused":
            self.draw_pause(self.canvas)
        elif self.state == "level_clear":
            self.draw_level_clear(self.canvas)
        elif self.state in ("game_over", "victory"):
            self.draw_end(self.canvas)
        window_width, window_height = self.screen.get_size()
        scale = min(window_width / W, window_height / H)
        render_w, render_h = max(1, round(W * scale)), max(1, round(H * scale))
        x, y = (window_width - render_w) // 2, (window_height - render_h) // 2
        self.screen.fill((2, 5, 14))
        if (render_w, render_h) == (W, H):
            self.screen.blit(self.canvas, (x, y))
        else:
            self.screen.blit(pygame.transform.smoothscale(self.canvas, (render_w, render_h)), (x, y))
        pygame.display.flip()

    def to_world(self, coords: tuple[int, int]) -> tuple[float, float]:
        ww, wh = self.screen.get_size()
        scale = min(ww / W, wh / H)
        off_x = (ww - W * scale) / 2
        off_y = (wh - H * scale) / 2
        return ((coords[0] - off_x) / scale, (coords[1] - off_y) / scale)

    def perform_action(self, action: str) -> None:
        if action == "start" or action == "restart":
            self.new_game()
        elif action == "resume":
            self.state = "playing"
        elif action == "menu":
            self.state = "menu"
            self.firing = False
        elif action == "help":
            self.state = "help"
        elif action == "mode":
            self.mode = "ENDLESS" if self.mode == "CAMPAIGN" else "CAMPAIGN"
        elif action == "difficulty":
            order = list(DIFFICULTIES)
            self.difficulty = order[(order.index(self.difficulty) + 1) % len(order)]
            self.write_records()
        elif action == "sound":
            self.sound_on = not self.sound_on
            self.write_records()
        self.buttons.clear()

    def fullscreen_toggle(self) -> None:
        self.fullscreen = not self.fullscreen
        if self.fullscreen:
            self.screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        else:
            self.screen = pygame.display.set_mode(self.window_size, pygame.RESIZABLE)

    def events(self) -> bool:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.write_records()
                return False
            if event.type == pygame.VIDEORESIZE and not self.fullscreen:
                self.window_size = (max(640, event.w), max(360, event.h))
                self.screen = pygame.display.set_mode(self.window_size, pygame.RESIZABLE)
            elif event.type == pygame.MOUSEMOTION:
                self.mouse_target, _ = self.to_world(event.pos)
                self.mouse_timer = 1.25
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if self.state == "playing":
                    if any(ball.attached for ball in self.balls):
                        self.launch()
                    else:
                        self.firing = True
                        self.fire_lasers()
                else:
                    mouse = self.to_world(event.pos)
                    for rect, action in self.buttons:
                        if rect.collidepoint(mouse):
                            self.perform_action(action)
                            break
            elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                self.firing = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_F11:
                    self.fullscreen_toggle()
                elif event.key == pygame.K_m:
                    self.sound_on = not self.sound_on
                    self.write_records()
                elif event.key == pygame.K_ESCAPE:
                    if self.state == "playing":
                        self.state = "paused"
                        self.firing = False
                    elif self.state == "paused":
                        self.state = "playing"
                    else:
                        self.state = "menu"
                elif event.key == pygame.K_p:
                    if self.state == "playing":
                        self.state = "paused"
                        self.firing = False
                    elif self.state == "paused":
                        self.state = "playing"
                elif self.state == "playing":
                    if event.key == pygame.K_SPACE:
                        self.launch()
                    elif event.key == pygame.K_r:
                        self.new_game()
                elif self.state in ("menu", "help", "paused", "game_over", "victory"):
                    if event.key == pygame.K_RETURN:
                        if self.state == "paused":
                            self.state = "playing"
                        elif self.state == "help":
                            self.state = "menu"
                        else:
                            self.new_game()
                    elif self.state == "menu":
                        if event.key in (pygame.K_1, pygame.K_2, pygame.K_3):
                            self.difficulty = list(DIFFICULTIES)[event.key - pygame.K_1]
                            self.write_records()
                        elif event.key == pygame.K_TAB:
                            self.perform_action("mode")
        return True

    def run(self, *, max_frames: Optional[int] = None) -> None:
        running = True
        frames = 0
        while running:
            elapsed = min(self.clock.tick(FPS_LIMIT) / 1000.0, 1 / 20)
            running = self.events()
            if not running:
                break
            self.accumulator += elapsed
            steps = 0
            while self.accumulator >= STEP and steps < 7:
                self.update(STEP)
                self.accumulator -= STEP
                steps += 1
            if steps >= 7:
                self.accumulator = 0.0
            self.draw()
            frames += 1
            if max_frames is not None and frames >= max_frames:
                break
        self.write_records()
        pygame.quit()


def smoke_test() -> None:
    """Optional graphical/physics self-test, using SDL's headless driver."""
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    game = Game(headless=True)
    game.write_records = lambda: None  # Do not alter real achievements during tests.
    game.new_game()
    assert len(game.bricks) > 0
    game.launch()
    game.damage_brick(game.bricks[0])
    for power in POWERUPS:
        game.use_powerup(power)
    for frame in range(1500):
        game.update(STEP)
        if frame % 150 == 0:
            game.draw()
        for ball in game.balls:
            assert math.isfinite(ball.pos.x) and math.isfinite(ball.pos.y)
            assert math.isfinite(ball.vel.x) and math.isfinite(ball.vel.y)
        assert 0 <= game.lives <= 9
        if game.state in ("game_over", "victory"):
            break
    print("SMOKE TEST PASSED: scene rendering, input-independent logic, power-ups, physics")
    pygame.quit()


def main() -> None:
    try:
        if "--smoke-test" in sys.argv:
            smoke_test()
        else:
            Game().run()
    except pygame.error as error:
        print(f"Pygame could not initialize or run: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
