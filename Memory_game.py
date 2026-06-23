import simplegui
import random

# Game settings
CARD_COUNT = 16
PAIR_COUNT = 8
CARD_WIDTH = 50
CARD_HEIGHT = 100
WIDTH = CARD_COUNT * CARD_WIDTH
HEIGHT = CARD_HEIGHT

cards = []
exposed = []
selected = []
turns = 0
game_complete = False


def update_label(message=None):
    """Refresh the score/status label."""
    if message:
        label.set_text(message)
    else:
        label.set_text("Turns = " + str(turns))


def new_game():
    """Create, shuffle, and hide a fresh deck."""
    global cards, exposed, selected, turns, game_complete

    cards = list(range(PAIR_COUNT)) * 2
    random.shuffle(cards)

    exposed = [False] * CARD_COUNT
    selected = []
    turns = 0
    game_complete = False

    update_label()


def hide_previous_pair():
    """Hide the previous two cards when they are not a match."""
    global selected

    if len(selected) == 2:
        first = selected[0]
        second = selected[1]

        if cards[first] != cards[second]:
            exposed[first] = False
            exposed[second] = False

    selected = []


def check_win():
    """Check whether every card has been revealed."""
    global game_complete

    if all(exposed):
        game_complete = True
        update_label("You won in " + str(turns) + " turns!")


def mouseclick(pos):
    """Reveal a card and evaluate pairs."""
    global selected, turns

    index = pos[0] // CARD_WIDTH

    # Ignore clicks outside the card area
    if index < 0 or index >= CARD_COUNT:
        return

    # Ignore already revealed cards or clicks after finishing
    if exposed[index] or game_complete:
        return

    # Before picking a new card, resolve the previous pair
    if len(selected) == 2:
        hide_previous_pair()

    # Reveal selected card
    exposed[index] = True
    selected.append(index)

    # A turn is completed after revealing two cards
    if len(selected) == 2:
        turns += 1

        if cards[selected[0]] == cards[selected[1]]:
            update_label("Match! Turns = " + str(turns))
            selected = []
            check_win()
        else:
            update_label("Try again... Turns = " + str(turns))


def draw(canvas):
    """Draw the deck."""
    for index in range(CARD_COUNT):
        left = index * CARD_WIDTH
        right = left + CARD_WIDTH

        # Card border/background
        canvas.draw_polygon(
            [[left, 0], [left, CARD_HEIGHT], [right, CARD_HEIGHT], [right, 0]],
            2,
            "White",
            "Green"
        )

        if exposed[index]:
            canvas.draw_polygon(
                [[left, 0], [left, CARD_HEIGHT], [right, CARD_HEIGHT], [right, 0]],
                2,
                "White",
                "Navy"
            )
            canvas.draw_text(
                str(cards[index]),
                [left + 16, 67],
                45,
                "White"
            )


frame = simplegui.create_frame("Memory Game", WIDTH, HEIGHT)
frame.add_button("New Game", new_game, 140)
label = frame.add_label("Turns = 0")

frame.set_mouseclick_handler(mouseclick)
frame.set_draw_handler(draw)

new_game()
frame.start()
