"""Minimal hardcoded opening book for book-move detection."""

# Space-joined SAN move sequences from common opening theory.
# A move is "book" if (history + new_move) matches exactly or is a
# strict prefix (followed by a space) of any line below.
BOOK_LINES: frozenset[str] = frozenset({
    # Single first moves
    "e4",
    "d4",
    "c4",
    "Nf3",
    # Common replies to 1.e4
    "e4 e5",
    "e4 c5",
    "e4 e6",
    "e4 c6",
    "e4 d5",
    # Common replies to 1.d4
    "d4 d5",
    "d4 Nf6",
    # 2nd moves
    "e4 e5 Nf3",
    "d4 d5 c4",
    "d4 Nf6 c4",
    "e4 c5 Nf3",
    # 3rd moves
    "e4 e5 Nf3 Nc6",
    "d4 d5 c4 e6",
    "d4 Nf6 c4 g6",
    "e4 c5 Nf3 d6 d4",
    "e4 e6 d4 d5",
    # 4th moves — Italian / Spanish / Giuoco
    "e4 e5 Nf3 Nc6 Bc4",
    "e4 e5 Nf3 Nc6 Bb5",
    # 5th moves
    "e4 e5 Nf3 Nc6 Bc4 Nf6",
    "e4 e5 Nf3 Nc6 Bc4 Bc5",
    "e4 e5 Nf3 Nc6 Bb5 a6",
    # Ruy Lopez continuation
    "e4 e5 Nf3 Nc6 Bb5 a6 Ba4",
    "e4 e5 Nf3 Nc6 Bb5 a6 Ba4 Nf6",
    "e4 e5 Nf3 Nc6 Bb5 a6 Ba4 Nf6 O-O",
    # Italian continuation
    "e4 e5 Nf3 Nc6 Bc4 Bc5 c3",
    "e4 e5 Nf3 Nc6 Bc4 Nf6 d3",
    # Sicilian continuation
    "e4 c5 Nf3 d6 d4 cxd4",
    "e4 c5 Nf3 Nc6 d4 cxd4",
    # QGD
    "d4 d5 c4 e6 Nc3",
    "d4 d5 c4 e6 Nc3 Nf6",
    # King's Indian
    "d4 Nf6 c4 g6 Nc3",
    "d4 Nf6 c4 g6 Nc3 Bg7",
})


def is_book_move(history: list[str], move_san: str) -> bool:
    """Return True if history + move_san matches or is a strict prefix of any book line."""
    full_seq = " ".join(history + [move_san])
    for line in BOOK_LINES:
        if line == full_seq or line.startswith(full_seq + " "):
            return True
    return False
