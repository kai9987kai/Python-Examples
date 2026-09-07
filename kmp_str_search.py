"""
Advanced Knuth-Morris-Pratt (KMP) Pattern Matching
=================================================

Original concept:
    Anurag Kumar
    anuragkumarak95@gmail.com

Modernised / extended implementation.

Features
--------
- Correct O(m) LPS/prefix table construction
- O(n + m) KMP searching
- Boolean containment tests
- First-match searching
- All-match searching
- Overlapping/non-overlapping matches
- Generic sequence support
- Compiled/reusable patterns
- Incremental streaming matching
- Command-line interface
- Built-in correctness tests

Terminology
-----------
n = length of text
m = length of pattern

Preprocessing:
    O(m)

Searching:
    O(n)

Complete first search:
    O(n + m)

Extra memory:
    O(m)
"""

from __future__ import annotations

from dataclasses import dataclass, field
import argparse
from collections.abc import Iterable, Iterator, Sequence
from typing import Generic, TypeVar


T = TypeVar("T")


# ---------------------------------------------------------------------------
# LPS / PREFIX TABLE
# ---------------------------------------------------------------------------

def build_lps(pattern: Sequence[T]) -> list[int]:
    """
    Construct the KMP Longest Proper Prefix which is also a Suffix table.

    For each position i:

        lps[i]

    stores the length of the longest proper prefix of:

        pattern[0:i+1]

    that is also a suffix of that same substring.

    Example
    -------
    Pattern:

        ABABCABAB

    LPS:

        [0, 0, 1, 2, 0, 1, 2, 3, 4]

    Complexity
    ----------
    Time:
        O(m)

    Space:
        O(m)

    where m = len(pattern).
    """

    m = len(pattern)

    lps = [0] * m

    # Length of the currently known prefix/suffix.
    prefix_len = 0

    # lps[0] is always 0.
    i = 1

    while i < m:

        # Characters continue the current prefix/suffix.
        if pattern[i] == pattern[prefix_len]:

            prefix_len += 1

            lps[i] = prefix_len

            i += 1

        # Mismatch after some prefix had already matched.
        #
        # Do NOT simply reset to zero.
        # There may be a smaller valid prefix/suffix available.
        elif prefix_len:

            prefix_len = lps[prefix_len - 1]

        # No smaller prefix is available.
        else:

            lps[i] = 0

            i += 1

    return lps


# ---------------------------------------------------------------------------
# BOUND NORMALISATION
# ---------------------------------------------------------------------------

def _normalise_bounds(
    length: int,
    start: int = 0,
    end: int | None = None,
) -> tuple[int, int]:
    """
    Convert start/end into valid sequence boundaries.

    This follows normal Python slice-bound normalisation while avoiding
    creation of an actual sliced copy of the input data.
    """

    start_i, stop_i, step = slice(start, end).indices(length)

    # This function currently constructs a slice without a custom step,
    # therefore the value should always be one.
    if step != 1:

        raise ValueError(
            "KMP bounds require a slice step of 1."
        )

    return start_i, stop_i


# ---------------------------------------------------------------------------
# FIRST MATCH
# ---------------------------------------------------------------------------

def kmp_find(
    pattern: Sequence[T],
    text: Sequence[T],
    start: int = 0,
    end: int | None = None,
    *,
    lps: Sequence[int] | None = None,
) -> int:
    """
    Find the first occurrence of `pattern` inside `text`.

    Parameters
    ----------
    pattern:
        Pattern sequence.

    text:
        Sequence being searched.

    start:
        Starting search position.

    end:
        Exclusive ending search position.

    lps:
        Optional precomputed LPS table.

        This is useful when the same pattern is reused repeatedly.

    Returns
    -------
    int
        Index of the first match.

        Returns -1 when no match exists.

    Examples
    --------
    >>> kmp_find("ABABX", "ABABZABABYABABX")
    10

    >>> kmp_find("xyz", "abcdef")
    -1

    Complexity
    ----------
    Without precomputed LPS:

        O(n + m)

    With precomputed LPS:

        O(n)
    """

    n = len(text)
    m = len(pattern)

    start_i, stop_i = _normalise_bounds(
        n,
        start,
        end,
    )

    # Empty patterns match at the current boundary.
    if m == 0:

        return start_i

    # Early exit when there is not enough searchable text.
    if stop_i - start_i < m:

        return -1

    # Use the supplied preprocessed table if available.
    table = (
        lps
        if lps is not None
        else build_lps(pattern)
    )

    if len(table) != m:

        raise ValueError(
            "The supplied LPS table must have exactly "
            "the same length as the pattern."
        )

    # i = text position
    # j = pattern position
    i = start_i
    j = 0

    while i < stop_i:

        # ---------------------------------------------------------------
        # MATCH
        # ---------------------------------------------------------------

        if text[i] == pattern[j]:

            i += 1
            j += 1

            # Complete pattern matched.
            if j == m:

                return i - m

        # ---------------------------------------------------------------
        # MISMATCH AFTER PARTIAL MATCH
        # ---------------------------------------------------------------

        elif j:

            # The key KMP operation:
            #
            # Rather than restarting from the beginning of the pattern,
            # reuse knowledge encoded in the LPS table.
            j = table[j - 1]

        # ---------------------------------------------------------------
        # MISMATCH AT PATTERN START
        # ---------------------------------------------------------------

        else:

            i += 1

    return -1


# ---------------------------------------------------------------------------
# BOOLEAN COMPATIBILITY API
# ---------------------------------------------------------------------------

def kmp_contains(
    pattern: Sequence[T],
    text: Sequence[T],
) -> bool:
    """
    Return True when pattern occurs anywhere inside text.
    """

    return kmp_find(
        pattern,
        text,
    ) != -1


def kmp(
    pattern: Sequence[T],
    text: Sequence[T],
    len_p: int | None = None,
    len_t: int | None = None,
) -> bool:
    """
    Backward-compatible version of the original `kmp()` API.

    The original implementation accepted `len_p` and `len_t` but did not
    actually use them.

    This version keeps those parameters so existing code does not break,
    but validates them when supplied.

    Examples
    --------
    >>> kmp("abc", "xyzabcdef")
    True

    >>> kmp("abc", "xyzdef")
    False
    """

    if (
        len_p is not None
        and len_p != len(pattern)
    ):

        raise ValueError(
            f"len_p={len_p} does not match "
            f"len(pattern)={len(pattern)}"
        )

    if (
        len_t is not None
        and len_t != len(text)
    ):

        raise ValueError(
            f"len_t={len_t} does not match "
            f"len(text)={len(text)}"
        )

    return kmp_contains(
        pattern,
        text,
    )


# ---------------------------------------------------------------------------
# ALL MATCHES
# ---------------------------------------------------------------------------

def kmp_finditer(
    pattern: Sequence[T],
    text: Sequence[T],
    start: int = 0,
    end: int | None = None,
    *,
    overlapping: bool = True,
) -> Iterator[int]:
    """
    Lazily yield every occurrence of `pattern`.

    Parameters
    ----------
    overlapping:
        True:
            Include overlapping matches.

        False:
            Only return non-overlapping matches.

    Example
    -------
    >>> list(kmp_finditer("ana", "bananana"))
    [1, 3, 5]

    >>> list(
    ...     kmp_finditer(
    ...         "ana",
    ...         "bananana",
    ...         overlapping=False
    ...     )
    ... )
    [1, 5]
    """

    n = len(text)
    m = len(pattern)

    start_i, stop_i = _normalise_bounds(
        n,
        start,
        end,
    )

    # There is an empty pattern at every boundary.
    if m == 0:

        yield from range(
            start_i,
            stop_i + 1,
        )

        return

    if stop_i - start_i < m:

        return

    lps = build_lps(pattern)

    i = start_i
    j = 0

    while i < stop_i:

        if text[i] == pattern[j]:

            i += 1
            j += 1

            if j == m:

                yield i - m

                # For overlapping matching, retain the largest
                # valid suffix/prefix state.
                if overlapping:

                    j = lps[j - 1]

                # For non-overlapping matching, begin the next
                # match from the start of the pattern.
                else:

                    j = 0

        elif j:

            j = lps[j - 1]

        else:

            i += 1


def kmp_findall(
    pattern: Sequence[T],
    text: Sequence[T],
    start: int = 0,
    end: int | None = None,
    *,
    overlapping: bool = True,
) -> list[int]:
    """
    Return all match indices as a list.
    """

    return list(
        kmp_finditer(
            pattern,
            text,
            start,
            end,
            overlapping=overlapping,
        )
    )


def kmp_count(
    pattern: Sequence[T],
    text: Sequence[T],
    start: int = 0,
    end: int | None = None,
    *,
    overlapping: bool = True,
) -> int:
    """
    Count the number of pattern occurrences.
    """

    return sum(
        1
        for _ in kmp_finditer(
            pattern,
            text,
            start,
            end,
            overlapping=overlapping,
        )
    )


# ---------------------------------------------------------------------------
# PRECOMPILED PATTERN
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class KMPPattern(Generic[T]):
    """
    Precompiled KMP pattern.

    This is useful when searching many pieces of text using the same pattern.

    Instead of rebuilding the LPS table for every search:

        O(m) + O(n1)
        O(m) + O(n2)
        O(m) + O(n3)

    preprocessing happens only once:

        O(m) + O(n1) + O(n2) + O(n3)

    Example
    -------
    matcher = KMPPattern("ERROR")

    matcher.find(log1)
    matcher.find(log2)
    matcher.find(log3)
    """

    pattern: Sequence[T]

    _pattern: tuple[T, ...] = field(
        init=False,
        repr=False,
    )

    _lps: tuple[int, ...] = field(
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:

        # Freeze/copy the pattern so external mutation of a list does not
        # invalidate our preprocessed LPS table.
        self._pattern = tuple(
            self.pattern
        )

        self._lps = tuple(
            build_lps(
                self._pattern
            )
        )

    @property
    def lps(self) -> tuple[int, ...]:
        """
        Return the immutable LPS table.
        """

        return self._lps

    @property
    def length(self) -> int:
        """
        Pattern length.
        """

        return len(
            self._pattern
        )

    def find(
        self,
        text: Sequence[T],
        start: int = 0,
        end: int | None = None,
    ) -> int:
        """
        Return first match position or -1.
        """

        return kmp_find(
            self._pattern,
            text,
            start,
            end,
            lps=self._lps,
        )

    def contains(
        self,
        text: Sequence[T],
    ) -> bool:
        """
        Test whether the compiled pattern occurs inside text.
        """

        return (
            self.find(text)
            != -1
        )

    def finditer(
        self,
        text: Sequence[T],
        start: int = 0,
        end: int | None = None,
        *,
        overlapping: bool = True,
    ) -> Iterator[int]:
        """
        Yield all matches using the already-preprocessed pattern.
        """

        n = len(text)
        m = len(self._pattern)

        start_i, stop_i = _normalise_bounds(
            n,
            start,
            end,
        )

        if m == 0:

            yield from range(
                start_i,
                stop_i + 1,
            )

            return

        if stop_i - start_i < m:

            return

        i = start_i
        j = 0

        while i < stop_i:

            if text[i] == self._pattern[j]:

                i += 1
                j += 1

                if j == m:

                    yield i - m

                    if overlapping:

                        j = self._lps[j - 1]

                    else:

                        j = 0

            elif j:

                j = self._lps[j - 1]

            else:

                i += 1

    def findall(
        self,
        text: Sequence[T],
        start: int = 0,
        end: int | None = None,
        *,
        overlapping: bool = True,
    ) -> list[int]:
        """
        Return all matches as a list.
        """

        return list(
            self.finditer(
                text,
                start,
                end,
                overlapping=overlapping,
            )
        )

    def count(
        self,
        text: Sequence[T],
        start: int = 0,
        end: int | None = None,
        *,
        overlapping: bool = True,
    ) -> int:
        """
        Count occurrences.
        """

        return sum(
            1
            for _ in self.finditer(
                text,
                start,
                end,
                overlapping=overlapping,
            )
        )


# ---------------------------------------------------------------------------
# STREAMING / INCREMENTAL KMP
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class KMPStreamMatcher(Generic[T]):
    """
    Incremental KMP matcher.

    Unlike normal searching, this class does not need the complete text to
    exist in memory simultaneously.

    It can process:

        - network packets
        - serial-port input
        - log streams
        - very large files
        - sensor streams
        - socket data
        - chunked HTTP responses
        - generated sequences

    A pattern can begin in one chunk and finish in another.

    Example
    -------

    stream = KMPStreamMatcher("abcab")

    print(stream.feed("xxab"))
    # []

    print(stream.feed("cabyy"))
    # [2]

    Pattern:

        abcab

    spans the chunk boundary:

        "xxab" + "cabyy"
           ^^     ^^^
    """

    pattern: Sequence[T]

    overlapping: bool = True

    _pattern: tuple[T, ...] = field(
        init=False,
        repr=False,
    )

    _lps: tuple[int, ...] = field(
        init=False,
        repr=False,
    )

    _matched: int = field(
        init=False,
        default=0,
        repr=False,
    )

    _offset: int = field(
        init=False,
        default=0,
        repr=False,
    )

    def __post_init__(self) -> None:

        self._pattern = tuple(
            self.pattern
        )

        if not self._pattern:

            raise ValueError(
                "Streaming KMP requires a non-empty pattern."
            )

        self._lps = tuple(
            build_lps(
                self._pattern
            )
        )

    @property
    def offset(self) -> int:
        """
        Number of stream elements consumed so far.
        """

        return self._offset

    @property
    def partial_match_length(self) -> int:
        """
        Number of pattern elements currently matched at the stream tail.
        """

        return self._matched

    def reset(self) -> None:
        """
        Reset the matcher so it can process a new stream.
        """

        self._matched = 0
        self._offset = 0

    def feed(
        self,
        chunk: Iterable[T],
    ) -> list[int]:
        """
        Process one chunk of stream data.

        Returns
        -------
        list[int]
            Absolute positions of any matches completed while consuming
            this chunk.

        Important
        ---------
        Returned positions refer to the complete stream, not positions
        relative to this individual chunk.
        """

        matches: list[int] = []

        m = len(
            self._pattern
        )

        for item in chunk:

            # -----------------------------------------------------------
            # FALL BACK UNTIL THE CURRENT ITEM CAN EXTEND A VALID PREFIX
            # -----------------------------------------------------------

            while (
                self._matched
                and item
                != self._pattern[
                    self._matched
                ]
            ):

                self._matched = self._lps[
                    self._matched - 1
                ]

            # -----------------------------------------------------------
            # EXTEND CURRENT MATCH
            # -----------------------------------------------------------

            if (
                item
                == self._pattern[
                    self._matched
                ]
            ):

                self._matched += 1

                # -------------------------------------------------------
                # COMPLETE PATTERN
                # -------------------------------------------------------

                if self._matched == m:

                    start_position = (
                        self._offset
                        - m
                        + 1
                    )

                    matches.append(
                        start_position
                    )

                    if self.overlapping:

                        self._matched = self._lps[
                            self._matched - 1
                        ]

                    else:

                        self._matched = 0

            # Absolute stream position advances once per element.
            self._offset += 1

        return matches


# ---------------------------------------------------------------------------
# SELF TESTS
# ---------------------------------------------------------------------------

def _run_self_tests() -> None:
    """
    Execute correctness and regression tests.
    """

    # ------------------------------------------------------------------
    # ORIGINAL TEST 1
    # ------------------------------------------------------------------

    pattern = "abc1abc12"

    text1 = (
        "alskfjaldsabc1abc1abc12k23adsfabcabc"
    )

    text2 = (
        "alskfjaldsk23adsfabcabc"
    )

    assert kmp(
        pattern,
        text1,
    )

    assert not kmp(
        pattern,
        text2,
    )

    # ------------------------------------------------------------------
    # ORIGINAL TEST 2
    # ------------------------------------------------------------------

    pattern = "ABABX"

    text = "ABABZABABYABABX"

    assert kmp(
        pattern,
        text,
    )

    assert (
        kmp_find(
            pattern,
            text,
        )
        == 10
    )

    # ------------------------------------------------------------------
    # REGRESSION TEST FOR ORIGINAL IMPLEMENTATION
    # ------------------------------------------------------------------
    #
    # The old implementation can incorrectly claim this is a match.
    #
    # Pattern:
    #
    #     abb
    #
    # Text:
    #
    #     abab
    #
    # There is clearly no contiguous "abb" substring.

    assert not kmp(
        "abb",
        "abab",
    )

    # ------------------------------------------------------------------
    # LPS TABLE TESTS
    # ------------------------------------------------------------------

    assert (
        build_lps(
            "ABABCABAB"
        )
        == [
            0,
            0,
            1,
            2,
            0,
            1,
            2,
            3,
            4,
        ]
    )

    assert (
        build_lps(
            "AAAA"
        )
        == [
            0,
            1,
            2,
            3,
        ]
    )

    assert (
        build_lps(
            "AAACAAAAAC"
        )
        == [
            0,
            1,
            2,
            0,
            1,
            2,
            3,
            3,
            3,
            4,
        ]
    )

    # ------------------------------------------------------------------
    # OVERLAPPING MATCHES
    # ------------------------------------------------------------------

    assert (
        kmp_findall(
            "ana",
            "bananana",
        )
        == [
            1,
            3,
            5,
        ]
    )

    # ------------------------------------------------------------------
    # NON-OVERLAPPING MATCHES
    # ------------------------------------------------------------------

    assert (
        kmp_findall(
            "ana",
            "bananana",
            overlapping=False,
        )
        == [
            1,
            5,
        ]
    )

    assert (
        kmp_findall(
            "aaa",
            "aaaaa",
        )
        == [
            0,
            1,
            2,
        ]
    )

    assert (
        kmp_findall(
            "aaa",
            "aaaaa",
            overlapping=False,
        )
        == [
            0,
        ]
    )

    # ------------------------------------------------------------------
    # EMPTY PATTERN
    # ------------------------------------------------------------------

    assert (
        kmp_find(
            "",
            "abc",
        )
        == 0
    )

    assert (
        kmp_findall(
            "",
            "abc",
        )
        == [
            0,
            1,
            2,
            3,
        ]
    )

    # ------------------------------------------------------------------
    # GENERIC SEQUENCE SUPPORT
    # ------------------------------------------------------------------

    assert (
        kmp_find(
            [2, 3],
            [0, 1, 2, 3, 4],
        )
        == 2
    )

    # ------------------------------------------------------------------
    # COMPILED PATTERN
    # ------------------------------------------------------------------

    compiled = KMPPattern(
        "ABABX"
    )

    assert (
        compiled.lps
        == (
            0,
            0,
            1,
            2,
            0,
        )
    )

    assert (
        compiled.find(
            "ABABZABABYABABX"
        )
        == 10
    )

    # ------------------------------------------------------------------
    # STREAMING MATCH
    # ------------------------------------------------------------------

    stream = KMPStreamMatcher(
        "abcab"
    )

    found: list[int] = []

    found += stream.feed(
        "xxab"
    )

    found += stream.feed(
        "cabyyabc"
    )

    found += stream.feed(
        "ab"
    )

    assert (
        found
        == [
            2,
            9,
        ]
    )

    print(
        "All KMP self-tests passed."
    )


# ---------------------------------------------------------------------------
# COMMAND LINE
# ---------------------------------------------------------------------------

def _build_cli() -> argparse.ArgumentParser:
    """
    Construct command-line parser.
    """

    parser = argparse.ArgumentParser(
        description=(
            "Search text using the "
            "Knuth-Morris-Pratt algorithm."
        )
    )

    parser.add_argument(
        "pattern",
        nargs="?",
        help=(
            "Pattern to search for."
        ),
    )

    parser.add_argument(
        "text",
        nargs="?",
        help=(
            "Text to search."
        ),
    )

    parser.add_argument(
        "--all",
        action="store_true",
        help=(
            "Print every match index instead "
            "of only the first."
        ),
    )

    parser.add_argument(
        "--non-overlapping",
        action="store_true",
        help=(
            "When used with --all, "
            "suppress overlapping matches."
        ),
    )

    parser.add_argument(
        "--show-lps",
        action="store_true",
        help=(
            "Print the calculated LPS table."
        ),
    )

    parser.add_argument(
        "--self-test",
        action="store_true",
        help=(
            "Run the built-in correctness tests."
        ),
    )

    return parser


def main() -> int:
    """
    Command-line entry point.
    """

    parser = _build_cli()

    args = parser.parse_args()

    # ------------------------------------------------------------------
    # SELF TEST MODE
    # ------------------------------------------------------------------

    if args.self_test:

        _run_self_tests()

        return 0

    # ------------------------------------------------------------------
    # VALIDATION
    # ------------------------------------------------------------------

    if (
        args.pattern is None
        or args.text is None
    ):

        parser.error(
            "pattern and text are required "
            "unless --self-test is used"
        )

    # ------------------------------------------------------------------
    # PRECOMPILE PATTERN
    # ------------------------------------------------------------------

    matcher = KMPPattern(
        args.pattern
    )

    # ------------------------------------------------------------------
    # LPS INFORMATION
    # ------------------------------------------------------------------

    if args.show_lps:

        print(
            "LPS:",
            list(
                matcher.lps
            ),
        )

    # ------------------------------------------------------------------
    # ALL MATCHES
    # ------------------------------------------------------------------

    if args.all:

        matches = matcher.findall(
            args.text,
            overlapping=(
                not args.non_overlapping
            ),
        )

        print(
            matches
        )

    # ------------------------------------------------------------------
    # FIRST MATCH
    # ------------------------------------------------------------------

    else:

        index = matcher.find(
            args.text
        )

        print(
            index
        )

        # Useful shell exit status:
        #
        # 0 = match
        # 1 = no match
        return (
            0
            if index >= 0
            else 1
        )

    return 0


# ---------------------------------------------------------------------------
# ENTRY POINT
# ---------------------------------------------------------------------------

if __name__ == "__main__":

    raise SystemExit(
        main()
    )
