"""The single path by which tokens enter the engine.

Real vision and virtual table mode both report what they see here, as a full
snapshot per source. The rest of the engine only reads `TokenTracker.tokens`,
so it can't tell (and doesn't care) whether a token is physical or clicked.
"""

from protocol import Token, TokenSource


class TokenTracker:
    def __init__(self) -> None:
        self._by_source: dict[TokenSource, dict[str, Token]] = {s: {} for s in TokenSource}
        self.version = 0  # bumps on every change, so the server knows when to broadcast

    def update(self, source: TokenSource, tokens: list[Token]) -> None:
        """Replace everything `source` currently sees with `tokens`."""
        snapshot = {t.id: t for t in tokens}
        if snapshot != self._by_source[source]:
            self._by_source[source] = snapshot
            self.version += 1

    @property
    def tokens(self) -> list[Token]:
        return [t for by_id in self._by_source.values() for t in by_id.values()]
