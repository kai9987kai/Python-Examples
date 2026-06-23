# Interactive Polyline Drawer - CodeSkulptor / SimpleGUI

import simplegui

# Canvas settings
WIDTH = 700
HEIGHT = 450

# Drawing state
polyline = []
mouse_pos = None
closed_shape = False
line_width = 3

# Colours
BACKGROUND = "Black"
LINE_COLOUR = "Aqua"
POINT_COLOUR = "Yellow"
PREVIEW_COLOUR = "Gray"
TEXT_COLOUR = "White"


def update_status():
    """Refresh the on-screen status label."""
    shape_state = "Closed" if closed_shape else "Open"
    status.set_text(
        "Points: " + str(len(polyline)) +
        " | Shape: " + shape_state +
        " | Width: " + str(line_width)
    )


def click(pos):
    """Add a new point where the user clicks."""
    global polyline

    # Re-open the shape when a new point is added
    if closed_shape:
        toggle_closed()

    polyline.append(pos)
    update_status()


def mouse_move(pos):
    """Track cursor position for the live preview line."""
    global mouse_pos
    mouse_pos = pos


def clear():
    """Remove every point."""
    global polyline
    polyline = []
    update_status()


def undo():
    """Remove the newest point."""
    if polyline:
        polyline.pop()
    update_status()


def toggle_closed():
    """Switch between an open line and a closed polygon."""
    global closed_shape

    if len(polyline) >= 3:
        closed_shape = not closed_shape

    update_status()


def increase_width():
    """Make the line thicker."""
    global line_width
    line_width = min(12, line_width + 1)
    update_status()


def decrease_width():
    """Make the line thinner."""
    global line_width
    line_width = max(1, line_width - 1)
    update_status()


def keydown(key):
    """Keyboard shortcuts."""
    if key == simplegui.KEY_MAP["z"]:
        undo()

    elif key == simplegui.KEY_MAP["c"]:
        clear()

    elif key == simplegui.KEY_MAP["space"]:
        toggle_closed()

    elif key == simplegui.KEY_MAP["up"]:
        increase_width()

    elif key == simplegui.KEY_MAP["down"]:
        decrease_width()


def draw(canvas):
    """Draw the polyline, points, preview, and instructions."""

    # Draw faint grid
    for x_pos in range(0, WIDTH, 50):
        canvas.draw_line((x_pos, 0), (x_pos, HEIGHT), 1, "DimGray")

    for y_pos in range(0, HEIGHT, 50):
        canvas.draw_line((0, y_pos), (WIDTH, y_pos), 1, "DimGray")

    # Draw connected line segments
    for index in range(1, len(polyline)):
        canvas.draw_line(
            polyline[index - 1],
            polyline[index],
            line_width,
            LINE_COLOUR
        )

    # Close the shape when enabled
    if closed_shape and len(polyline) >= 3:
        canvas.draw_line(
            polyline[-1],
            polyline[0],
            line_width,
            LINE_COLOUR
        )

    # Live preview from last point to mouse cursor
    if polyline and mouse_pos and not closed_shape:
        canvas.draw_line(
            polyline[-1],
            mouse_pos,
            1,
            PREVIEW_COLOUR
        )

    # Draw point markers and point numbers
    for index in range(len(polyline)):
        point = polyline[index]

        canvas.draw_circle(
            point,
            5,
            1,
            POINT_COLOUR,
            POINT_COLOUR
        )

        canvas.draw_text(
            str(index + 1),
            (point[0] + 8, point[1] - 8),
            13,
            TEXT_COLOUR
        )

    # Empty-canvas hint
    if not polyline:
        canvas.draw_text(
            "Click anywhere to start drawing",
            (210, 220),
            22,
            "LightGray"
        )

    # Instructions
    canvas.draw_text(
        "Click: add point | Z: undo | C: clear | Space: open/close | Up/Down: line width",
        (15, HEIGHT - 15),
        14,
        TEXT_COLOUR
    )


# Create interface
frame = simplegui.create_frame("Advanced Polyline Drawer", WIDTH, HEIGHT)

frame.set_mouseclick_handler(click)
frame.set_mousemove_handler(mouse_move)
frame.set_keydown_handler(keydown)
frame.set_draw_handler(draw)

frame.add_button("Undo Last Point", undo, 160)
frame.add_button("Clear All", clear, 160)
frame.add_button("Open / Close Shape", toggle_closed, 160)
frame.add_button("Increase Width", increase_width, 160)
frame.add_button("Decrease Width", decrease_width, 160)

status = frame.add_label("")
update_status()

frame.start()
