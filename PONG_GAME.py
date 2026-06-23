# Pong Game — improved CodeSkulptor version

import simplegui
import random

# Canvas
WIDTH = 600
HEIGHT = 400

# Ball
BALL_RADIUS = 12
BALL_MAX_SPEED = 10

# Paddles
PAD_WIDTH = 8
PAD_HEIGHT = 80
HALF_PAD_WIDTH = PAD_WIDTH / 2
HALF_PAD_HEIGHT = PAD_HEIGHT / 2
PADDLE_SPEED = 6

# Directions
LEFT = -1
RIGHT = 1

# Game state
ball_pos = [WIDTH / 2, HEIGHT / 2]
ball_vel = [0, 0]

paddle1_pos = HEIGHT / 2
paddle2_pos = HEIGHT / 2
paddle1_vel = 0
paddle2_vel = 0

score1 = 0
score2 = 0
rally = 0
paused = False

# Keyboard state
KEY_W = simplegui.KEY_MAP["w"]
KEY_S = simplegui.KEY_MAP["s"]
KEY_UP = simplegui.KEY_MAP["up"]
KEY_DOWN = simplegui.KEY_MAP["down"]
KEY_P = simplegui.KEY_MAP["p"]
KEY_R = simplegui.KEY_MAP["r"]

keys_down = {
    KEY_W: False,
    KEY_S: False,
    KEY_UP: False,
    KEY_DOWN: False
}


def spawn_ball(direction):
    """Place the ball in the centre with a random starting velocity."""
    global ball_pos, ball_vel

    ball_pos = [WIDTH / 2, HEIGHT / 2]

    horizontal_speed = random.randrange(3, 5)
    vertical_speed = random.randrange(-3, 4)

    if vertical_speed == 0:
        vertical_speed = random.choice([-1, 1])

    ball_vel = [direction * horizontal_speed, vertical_speed]


def new_game():
    """Reset the full match."""
    global paddle1_pos, paddle2_pos
    global paddle1_vel, paddle2_vel
    global score1, score2, rally, paused

    score1 = 0
    score2 = 0
    rally = 0
    paused = False

    paddle1_pos = HEIGHT / 2
    paddle2_pos = HEIGHT / 2
    paddle1_vel = 0
    paddle2_vel = 0

    for key in keys_down:
        keys_down[key] = False

    spawn_ball(random.choice([LEFT, RIGHT]))


def update_paddle_velocity():
    """Allow smooth movement, including holding keys down."""
    global paddle1_vel, paddle2_vel

    paddle1_vel = PADDLE_SPEED * (
        int(keys_down[KEY_S]) - int(keys_down[KEY_W])
    )

    paddle2_vel = PADDLE_SPEED * (
        int(keys_down[KEY_DOWN]) - int(keys_down[KEY_UP])
    )


def clamp_paddles():
    """Keep paddles fully inside the game area."""
    global paddle1_pos, paddle2_pos

    paddle1_pos = max(HALF_PAD_HEIGHT,
                      min(HEIGHT - HALF_PAD_HEIGHT, paddle1_pos))

    paddle2_pos = max(HALF_PAD_HEIGHT,
                      min(HEIGHT - HALF_PAD_HEIGHT, paddle2_pos))


def ball_hits_paddle(paddle_y):
    """Return True when the ball overlaps a paddle vertically."""
    return (
        ball_pos[1] >= paddle_y - HALF_PAD_HEIGHT and
        ball_pos[1] <= paddle_y + HALF_PAD_HEIGHT
    )


def bounce_from_paddle(paddle_y, direction):
    """Bounce the ball, add speed, and alter angle from contact position."""
    global ball_vel, rally

    hit_position = (ball_pos[1] - paddle_y) / HALF_PAD_HEIGHT

    horizontal_speed = min(abs(ball_vel[0]) * 1.08, BALL_MAX_SPEED)

    ball_vel[0] = direction * horizontal_speed
    ball_vel[1] += hit_position * 2.2

    # Prevent nearly vertical or impossibly fast vertical travel
    ball_vel[1] = max(-BALL_MAX_SPEED, min(BALL_MAX_SPEED, ball_vel[1]))

    rally += 1


def update_ball():
    """Move ball, detect walls, paddles, scores, and respawns."""
    global ball_pos, ball_vel, score1, score2

    ball_pos[0] += ball_vel[0]
    ball_pos[1] += ball_vel[1]

    # Top and bottom wall collisions
    if ball_pos[1] <= BALL_RADIUS:
        ball_pos[1] = BALL_RADIUS
        ball_vel[1] = abs(ball_vel[1])

    elif ball_pos[1] >= HEIGHT - BALL_RADIUS:
        ball_pos[1] = HEIGHT - BALL_RADIUS
        ball_vel[1] = -abs(ball_vel[1])

    # Left paddle or left-side score
    if ball_vel[0] < 0 and ball_pos[0] - BALL_RADIUS <= PAD_WIDTH:
        if ball_hits_paddle(paddle1_pos):
            ball_pos[0] = PAD_WIDTH + BALL_RADIUS
            bounce_from_paddle(paddle1_pos, RIGHT)
        else:
            score2 += 1
            spawn_ball(RIGHT)

    # Right paddle or right-side score
    if ball_vel[0] > 0 and ball_pos[0] + BALL_RADIUS >= WIDTH - PAD_WIDTH:
        if ball_hits_paddle(paddle2_pos):
            ball_pos[0] = WIDTH - PAD_WIDTH - BALL_RADIUS
            bounce_from_paddle(paddle2_pos, LEFT)
        else:
            score1 += 1
            spawn_ball(LEFT)


def draw_background(canvas):
    """Draw pitch markings."""
    canvas.draw_line(
        [WIDTH / 2, 0],
        [WIDTH / 2, HEIGHT],
        2,
        "White"
    )

    canvas.draw_line(
        [PAD_WIDTH, 0],
        [PAD_WIDTH, HEIGHT],
        1,
        "White"
    )

    canvas.draw_line(
        [WIDTH - PAD_WIDTH, 0],
        [WIDTH - PAD_WIDTH, HEIGHT],
        1,
        "White"
    )


def draw_paddles(canvas):
    """Draw both paddles."""
    canvas.draw_line(
        [HALF_PAD_WIDTH, paddle1_pos - HALF_PAD_HEIGHT],
        [HALF_PAD_WIDTH, paddle1_pos + HALF_PAD_HEIGHT],
        PAD_WIDTH,
        "White"
    )

    canvas.draw_line(
        [WIDTH - HALF_PAD_WIDTH, paddle2_pos - HALF_PAD_HEIGHT],
        [WIDTH - HALF_PAD_WIDTH, paddle2_pos + HALF_PAD_HEIGHT],
        PAD_WIDTH,
        "White"
    )


def draw(canvas):
    global paddle1_pos, paddle2_pos

    draw_background(canvas)

    if not paused:
        paddle1_pos += paddle1_vel
        paddle2_pos += paddle2_vel

        clamp_paddles()
        update_ball()

    draw_paddles(canvas)

    canvas.draw_circle(
        ball_pos,
        BALL_RADIUS,
        1,
        "White",
        "White"
    )

    # Scores
    canvas.draw_text(str(score1), [245, 55], 46, "White")
    canvas.draw_text(str(score2), [325, 55], 46, "White")

    # Game details
    canvas.draw_text("Rally: " + str(rally), [250, HEIGHT - 18], 16, "White")

    if paused:
        canvas.draw_text("PAUSED", [220, 210], 34, "Yellow")


def keydown(key):
    global paused

    if key in keys_down:
        keys_down[key] = True
        update_paddle_velocity()

    elif key == KEY_P:
        paused = not paused

    elif key == KEY_R:
        new_game()


def keyup(key):
    if key in keys_down:
        keys_down[key] = False
        update_paddle_velocity()


# Create game frame
frame = simplegui.create_frame("Improved Pong", WIDTH, HEIGHT)

frame.set_draw_handler(draw)
frame.set_keydown_handler(keydown)
frame.set_keyup_handler(keyup)

frame.add_button("New Match", new_game, 120)
frame.add_label("Left Paddle: W / S")
frame.add_label("Right Paddle: Up / Down")
frame.add_label("P = Pause    R = Restart")

new_game()
frame.start()
