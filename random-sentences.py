#!/usr/bin/env python3
"""
Advanced Random Sentence & Procedural Story Generator
======================================================

A modernised and expanded version of a simple random sentence generator.

Features
--------
- Multiple grammatical sentence templates
- Weighted vocabulary selection
- Random adjectives and adverbs
- Singular/plural noun handling
- Basic verb agreement
- Character generation
- Story continuity
- Paragraph generation
- Configurable sentence/story length
- Reproducible random generation using seeds
- Command-line interface
- Optional JSON output
- Clean object-oriented design
- Standard-library only

Examples
--------
Generate 20 random sentences:

    python random_story.py

Generate a 40-sentence story:

    python random_story.py --sentences 40

Use a deterministic seed:

    python random_story.py --seed 12345

Create three paragraphs:

    python random_story.py --paragraphs 3

Return machine-readable JSON:

    python random_story.py --json
"""

from __future__ import annotations

import argparse
import json
import random
import textwrap
from dataclasses import asdict, dataclass
from typing import Callable, Sequence, TypeVar


T = TypeVar("T")


# ---------------------------------------------------------------------------
# DATA MODELS
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Noun:
    singular: str
    plural: str


@dataclass(frozen=True)
class Character:
    name: str
    description: str
    home: str


@dataclass
class GeneratedStory:
    title: str
    seed: int | None
    characters: list[Character]
    paragraphs: list[str]


# ---------------------------------------------------------------------------
# LANGUAGE DATA
# ---------------------------------------------------------------------------

ARTICLES = [
    "the",
    "a",
    "one",
    "some",
    "any",
]

DEFINITE_ARTICLES = [
    "the",
]

INDEFINITE_ARTICLES = [
    "a",
    "one",
]

NOUNS = [
    Noun("boy", "boys"),
    Noun("girl", "girls"),
    Noun("dog", "dogs"),
    Noun("cat", "cats"),
    Noun("robot", "robots"),
    Noun("scientist", "scientists"),
    Noun("engineer", "engineers"),
    Noun("traveller", "travellers"),
    Noun("car", "cars"),
    Noun("drone", "drones"),
    Noun("machine", "machines"),
    Noun("computer", "computers"),
    Noun("spaceship", "spaceships"),
    Noun("train", "trains"),
    Noun("creature", "creatures"),
]

PLACES = [
    "town",
    "city",
    "forest",
    "laboratory",
    "workshop",
    "station",
    "castle",
    "village",
    "factory",
    "harbour",
    "mountain",
    "valley",
    "island",
    "underground tunnel",
    "abandoned facility",
    "space station",
]

ADJECTIVES = [
    "ancient",
    "bright",
    "broken",
    "curious",
    "enormous",
    "forgotten",
    "friendly",
    "futuristic",
    "glowing",
    "hidden",
    "mysterious",
    "noisy",
    "peculiar",
    "powerful",
    "rusty",
    "silent",
    "strange",
    "tiny",
    "unstable",
    "unusual",
]

ADVERBS = [
    "carefully",
    "cautiously",
    "cheerfully",
    "dramatically",
    "eagerly",
    "frantically",
    "gracefully",
    "loudly",
    "mysteriously",
    "quickly",
    "quietly",
    "reluctantly",
    "slowly",
    "suddenly",
    "unexpectedly",
]

PAST_VERBS = [
    "approached",
    "built",
    "carried",
    "chased",
    "discovered",
    "drove",
    "examined",
    "followed",
    "found",
    "jumped",
    "left",
    "opened",
    "ran",
    "repaired",
    "searched",
    "skipped",
    "walked",
    "watched",
]

TRANSITIVE_VERBS = [
    "approached",
    "built",
    "carried",
    "chased",
    "discovered",
    "examined",
    "followed",
    "found",
    "opened",
    "repaired",
    "searched for",
    "watched",
]

PREPOSITIONS = [
    "above",
    "across",
    "around",
    "behind",
    "beside",
    "from",
    "inside",
    "near",
    "on",
    "over",
    "through",
    "to",
    "towards",
    "under",
]

CONJUNCTIONS = [
    "and",
    "but",
    "because",
    "although",
    "while",
    "until",
]

REACTIONS = [
    "nobody understood why",
    "something seemed terribly wrong",
    "the situation became stranger",
    "everything suddenly became quiet",
    "a distant alarm began to sound",
    "the lights flickered",
    "the ground shook beneath them",
    "an unexpected signal appeared",
    "nobody wanted to turn back",
    "the mystery only deepened",
]

DISCOVERIES = [
    "a glowing metal sphere",
    "an abandoned machine",
    "a mysterious control panel",
    "a hidden doorway",
    "a strange map",
    "an encrypted message",
    "a tiny mechanical creature",
    "an enormous underground chamber",
    "a damaged robot",
    "a forgotten laboratory",
    "an unfamiliar vehicle",
    "a blinking computer terminal",
]

CHARACTER_NAMES = [
    "Alex",
    "Amelia",
    "Charlie",
    "Elliot",
    "Eva",
    "Finn",
    "Isaac",
    "Leo",
    "Maya",
    "Noah",
    "Olivia",
    "Ruby",
    "Sam",
    "Theo",
    "Zara",
]

CHARACTER_DESCRIPTIONS = [
    "curious engineer",
    "young inventor",
    "fearless explorer",
    "quiet scientist",
    "clever mechanic",
    "enthusiastic programmer",
    "experimental roboticist",
    "adventurous traveller",
]

TITLE_ADJECTIVES = [
    "Hidden",
    "Forgotten",
    "Impossible",
    "Mechanical",
    "Mysterious",
    "Silent",
    "Strange",
    "Unexpected",
]

TITLE_NOUNS = [
    "Machine",
    "Signal",
    "Journey",
    "Experiment",
    "Discovery",
    "Station",
    "World",
    "Device",
    "Secret",
    "Adventure",
]


# ---------------------------------------------------------------------------
# RANDOM ENGINE
# ---------------------------------------------------------------------------

class RandomEngine:
    """Wrapper around random.Random for deterministic generation."""

    def __init__(self, seed: int | None = None) -> None:
        self.seed = seed
        self.random = random.Random(seed)

    def choice(self, values: Sequence[T]) -> T:
        return self.random.choice(values)

    def chance(self, probability: float = 0.5) -> bool:
        return self.random.random() < probability

    def randint(self, minimum: int, maximum: int) -> int:
        return self.random.randint(minimum, maximum)

    def weighted_choice(
        self,
        values: Sequence[T],
        weights: Sequence[float],
    ) -> T:
        return self.random.choices(values, weights=weights, k=1)[0]


# ---------------------------------------------------------------------------
# TEXT UTILITIES
# ---------------------------------------------------------------------------

def sentence_case(text: str) -> str:
    text = text.strip()

    if not text:
        return text

    return text[0].upper() + text[1:]


def ensure_terminal_punctuation(text: str) -> str:
    text = text.rstrip()

    if not text:
        return text

    if text[-1] not in ".!?":
        text += "."

    return text


def normalize_sentence(text: str) -> str:
    return ensure_terminal_punctuation(sentence_case(" ".join(text.split())))


def use_correct_indefinite_article(word: str) -> str:
    """
    Basic a/an selection.

    English contains exceptions, but this heuristic works well for
    the vocabulary used by this generator.
    """

    first_letter = word.strip().lower()[:1]

    if first_letter in {"a", "e", "i", "o", "u"}:
        return "an"

    return "a"


# ---------------------------------------------------------------------------
# GENERATOR
# ---------------------------------------------------------------------------

class StoryGenerator:
    def __init__(self, seed: int | None = None) -> None:
        self.engine = RandomEngine(seed)
        self.seed = seed
        self.characters: list[Character] = []

    # ------------------------------------------------------------------
    # Basic lexical generation
    # ------------------------------------------------------------------

    def noun(self, plural: bool = False) -> str:
        noun = self.engine.choice(NOUNS)
        return noun.plural if plural else noun.singular

    def adjective(self) -> str:
        return self.engine.choice(ADJECTIVES)

    def adverb(self) -> str:
        return self.engine.choice(ADVERBS)

    def place(self) -> str:
        return self.engine.choice(PLACES)

    def verb(self) -> str:
        return self.engine.choice(PAST_VERBS)

    def preposition(self) -> str:
        return self.engine.choice(PREPOSITIONS)

    # ------------------------------------------------------------------
    # Phrase generation
    # ------------------------------------------------------------------

    def noun_phrase(
        self,
        *,
        allow_adjective: bool = True,
        allow_plural: bool = True,
    ) -> str:

        plural = allow_plural and self.engine.chance(0.20)

        noun = self.engine.choice(NOUNS)
        noun_word = noun.plural if plural else noun.singular

        adjective = (
            self.adjective()
            if allow_adjective and self.engine.chance(0.65)
            else None
        )

        if plural:
            determiner = self.engine.weighted_choice(
                ["the", "some", "several"],
                [0.55, 0.30, 0.15],
            )

            if adjective:
                return f"{determiner} {adjective} {noun_word}"

            return f"{determiner} {noun_word}"

        if adjective:
            phrase_head = f"{adjective} {noun_word}"

            if self.engine.chance(0.50):
                article = use_correct_indefinite_article(adjective)
            else:
                article = "the"

            return f"{article} {phrase_head}"

        article = self.engine.weighted_choice(
            ["the", "a"],
            [0.60, 0.40],
        )

        if article == "a":
            article = use_correct_indefinite_article(noun_word)

        return f"{article} {noun_word}"

    def place_phrase(self) -> str:
        adjective = self.adjective() if self.engine.chance(0.45) else None
        place = self.place()

        if adjective:
            return f"the {adjective} {place}"

        return f"the {place}"

    # ------------------------------------------------------------------
    # Sentence templates
    # ------------------------------------------------------------------

    def classic_sentence(self) -> str:
        """
        Enhanced version of the original:

        article + noun + verb + preposition + article + noun
        """

        subject = self.noun_phrase()
        verb = self.verb()
        preposition = self.preposition()
        destination = self.noun_phrase()

        return normalize_sentence(
            f"{subject} {verb} {preposition} {destination}"
        )

    def adjective_sentence(self) -> str:
        subject = self.noun_phrase()
        verb = self.engine.choice(TRANSITIVE_VERBS)
        obj = self.noun_phrase()

        if self.engine.chance(0.65):
            adverb = self.adverb()
            result = f"{subject} {adverb} {verb} {obj}"
        else:
            result = f"{subject} {verb} {obj}"

        return normalize_sentence(result)

    def location_sentence(self) -> str:
        subject = self.noun_phrase()
        verb = self.verb()
        prep = self.preposition()
        place = self.place_phrase()

        return normalize_sentence(
            f"{subject} {verb} {prep} {place}"
        )

    def discovery_sentence(self) -> str:
        subject = self.noun_phrase()
        discovery = self.engine.choice(DISCOVERIES)
        place = self.place_phrase()

        patterns = [
            f"{subject} discovered {discovery} inside {place}",
            f"inside {place}, {subject} found {discovery}",
            f"{subject} unexpectedly noticed {discovery} near {place}",
            f"while exploring {place}, {subject} encountered {discovery}",
        ]

        return normalize_sentence(self.engine.choice(patterns))

    def compound_sentence(self) -> str:
        subject = self.noun_phrase()
        verb1 = self.verb()
        place = self.place_phrase()
        conjunction = self.engine.choice(CONJUNCTIONS)
        reaction = self.engine.choice(REACTIONS)

        return normalize_sentence(
            f"{subject} {verb1} towards {place}, "
            f"{conjunction} {reaction}"
        )

    def dramatic_sentence(self) -> str:
        reaction = self.engine.choice(REACTIONS)

        beginnings = [
            "Without warning",
            "Moments later",
            "For reasons nobody could explain",
            "Almost immediately",
            "At exactly that moment",
            "Before anyone could react",
        ]

        beginning = self.engine.choice(beginnings)

        return normalize_sentence(
            f"{beginning}, {reaction}"
        )

    # ------------------------------------------------------------------
    # Character-aware sentences
    # ------------------------------------------------------------------

    def generate_character(self) -> Character:
        existing_names = {character.name for character in self.characters}

        available_names = [
            name
            for name in CHARACTER_NAMES
            if name not in existing_names
        ]

        if not available_names:
            available_names = CHARACTER_NAMES

        character = Character(
            name=self.engine.choice(available_names),
            description=self.engine.choice(CHARACTER_DESCRIPTIONS),
            home=self.place(),
        )

        self.characters.append(character)
        return character

    def character_sentence(self) -> str:
        if not self.characters:
            self.generate_character()

        character = self.engine.choice(self.characters)

        discovery = self.engine.choice(DISCOVERIES)
        place = self.place_phrase()

        patterns = [
            (
                f"{character.name}, the {character.description}, "
                f"discovered {discovery} inside {place}"
            ),
            (
                f"{character.name} cautiously entered {place} "
                f"and examined {discovery}"
            ),
            (
                f"{character.name} had never seen anything like "
                f"{discovery} before"
            ),
            (
                f"although {character.name} wanted to leave, "
                f"the mystery of {discovery} was impossible to ignore"
            ),
        ]

        return normalize_sentence(self.engine.choice(patterns))

    # ------------------------------------------------------------------
    # General sentence dispatcher
    # ------------------------------------------------------------------

    def random_sentence(self) -> str:
        generators: list[Callable[[], str]] = [
            self.classic_sentence,
            self.adjective_sentence,
            self.location_sentence,
            self.discovery_sentence,
            self.compound_sentence,
            self.dramatic_sentence,
            self.character_sentence,
        ]

        weights = [
            1.0,   # classic
            1.5,   # adjective
            1.4,   # location
            1.8,   # discovery
            1.2,   # compound
            0.8,   # dramatic
            1.8,   # character continuity
        ]

        generator = self.engine.weighted_choice(
            generators,
            weights,
        )

        return generator()

    # ------------------------------------------------------------------
    # Story structure
    # ------------------------------------------------------------------

    def generate_title(self) -> str:
        return (
            f"The {self.engine.choice(TITLE_ADJECTIVES)} "
            f"{self.engine.choice(TITLE_NOUNS)}"
        )

    def opening_sentence(self) -> str:
        character = self.generate_character()

        openings = [
            (
                f"{character.name} was a {character.description} "
                f"who lived near a {character.home}"
            ),
            (
                f"on an otherwise ordinary morning, "
                f"{character.name}, a {character.description}, "
                f"left the {character.home} searching for something unusual"
            ),
            (
                f"few people in the {character.home} understood "
                f"{character.name}'s fascination with strange machines"
            ),
        ]

        return normalize_sentence(self.engine.choice(openings))

    def conflict_sentence(self) -> str:
        if not self.characters:
            character = self.generate_character()
        else:
            character = self.characters[0]

        event = self.engine.choice(
            [
                "a warning signal appeared on a nearby screen",
                "the entire building suddenly lost power",
                "an unfamiliar machine activated itself",
                "a locked doorway opened without explanation",
                "a strange transmission began repeating their name",
                "a mechanical creature emerged from the darkness",
            ]
        )

        return normalize_sentence(
            f"then, without warning, {event}, "
            f"and {character.name} realised the situation had changed"
        )

    def ending_sentence(self) -> str:
        if not self.characters:
            name = "the traveller"
        else:
            name = self.characters[0].name

        endings = [
            (
                f"{name} finally returned home, "
                "although the mystery was far from solved"
            ),
            (
                f"by sunrise, {name} understood that "
                "the discovery would change everything"
            ),
            (
                f"{name} switched off the machine and walked away, "
                "but one tiny light continued blinking"
            ),
            (
                f"for now the danger had passed, "
                f"but {name} knew another adventure was already beginning"
            ),
        ]

        return normalize_sentence(self.engine.choice(endings))

    def generate_paragraph(
        self,
        sentence_count: int = 5,
        *,
        include_opening: bool = False,
        include_conflict: bool = False,
        include_ending: bool = False,
    ) -> str:

        sentence_count = max(1, sentence_count)
        sentences: list[str] = []

        if include_opening:
            sentences.append(self.opening_sentence())

        remaining = sentence_count - len(sentences)

        if include_conflict and remaining > 1:
            normal_before_conflict = max(1, remaining // 2)

            for _ in range(normal_before_conflict):
                sentences.append(self.random_sentence())

            sentences.append(self.conflict_sentence())

        while len(sentences) < sentence_count:
            if include_ending and len(sentences) == sentence_count - 1:
                sentences.append(self.ending_sentence())
            else:
                sentences.append(self.random_sentence())

        return " ".join(sentences[:sentence_count])

    def generate_story(
        self,
        *,
        paragraphs: int = 4,
        sentences_per_paragraph: int = 5,
    ) -> GeneratedStory:

        paragraphs = max(1, paragraphs)
        sentences_per_paragraph = max(1, sentences_per_paragraph)

        self.characters.clear()

        story_paragraphs: list[str] = []

        for index in range(paragraphs):
            first = index == 0
            middle = index == max(1, paragraphs // 2)
            last = index == paragraphs - 1

            paragraph = self.generate_paragraph(
                sentence_count=sentences_per_paragraph,
                include_opening=first,
                include_conflict=middle,
                include_ending=last,
            )

            story_paragraphs.append(paragraph)

        return GeneratedStory(
            title=self.generate_title(),
            seed=self.seed,
            characters=list(self.characters),
            paragraphs=story_paragraphs,
        )


# ---------------------------------------------------------------------------
# OUTPUT
# ---------------------------------------------------------------------------

def print_random_sentences(
    generator: StoryGenerator,
    count: int,
) -> None:
    print("=" * 72)
    print("RANDOM SENTENCES")
    print("=" * 72)

    for number in range(1, count + 1):
        sentence = generator.random_sentence()

        print(
            textwrap.fill(
                f"{number:02d}. {sentence}",
                width=88,
                subsequent_indent="    ",
            )
        )


def print_story(story: GeneratedStory) -> None:
    print()
    print("=" * 72)
    print(story.title.upper())
    print("=" * 72)

    for paragraph in story.paragraphs:
        print()
        print(
            textwrap.fill(
                paragraph,
                width=88,
            )
        )

    if story.seed is not None:
        print()
        print(f"Generation seed: {story.seed}")


def output_json(
    sentences: list[str],
    story: GeneratedStory,
) -> None:

    payload = {
        "sentences": sentences,
        "story": asdict(story),
    }

    print(
        json.dumps(
            payload,
            indent=2,
            ensure_ascii=False,
        )
    )


# ---------------------------------------------------------------------------
# COMMAND-LINE INTERFACE
# ---------------------------------------------------------------------------

def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate random English sentences and procedural short stories."
        )
    )

    parser.add_argument(
        "--sentences",
        type=int,
        default=20,
        help="Number of independent random sentences to generate.",
    )

    parser.add_argument(
        "--paragraphs",
        type=int,
        default=4,
        help="Number of paragraphs in the generated story.",
    )

    parser.add_argument(
        "--sentences-per-paragraph",
        type=int,
        default=5,
        help="Number of sentences in each story paragraph.",
    )

    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help=(
            "Optional random seed. "
            "Using the same seed reproduces the same output."
        ),
    )

    parser.add_argument(
        "--json",
        action="store_true",
        help="Output generated data as JSON.",
    )

    return parser.parse_args()


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main() -> None:
    args = parse_arguments()

    if args.sentences < 0:
        raise SystemExit("--sentences must be zero or greater.")

    if args.paragraphs < 1:
        raise SystemExit("--paragraphs must be at least 1.")

    if args.sentences_per_paragraph < 1:
        raise SystemExit(
            "--sentences-per-paragraph must be at least 1."
        )

    generator = StoryGenerator(seed=args.seed)

    independent_sentences = [
        generator.random_sentence()
        for _ in range(args.sentences)
    ]

    story = generator.generate_story(
        paragraphs=args.paragraphs,
        sentences_per_paragraph=args.sentences_per_paragraph,
    )

    if args.json:
        output_json(
            independent_sentences,
            story,
        )
        return

    print("=" * 72)
    print("ADVANCED RANDOM SENTENCE GENERATOR")
    print("=" * 72)

    if args.seed is not None:
        print(f"Seed: {args.seed}")

    print()

    for index, sentence in enumerate(
        independent_sentences,
        start=1,
    ):
        print(
            textwrap.fill(
                f"{index:02d}. {sentence}",
                width=88,
                subsequent_indent="    ",
            )
        )

    print_story(story)


if __name__ == "__main__":
    main()
