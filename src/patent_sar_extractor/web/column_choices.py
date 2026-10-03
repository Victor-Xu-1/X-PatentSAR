"""Bounded full-project raw value choices for Excel-style checklists."""

from collections import Counter


class ColumnChoices:
    def __init__(self) -> None:
        self.counts: Counter[str] = Counter()
        self.truncated = False

    def observe(self, value: object) -> None:
        if value is None:
            return
        token = str(value)
        if not token or len(token) > 1000:
            return
        if token not in self.counts and len(self.counts) >= 200:
            self.truncated = True
            largest = max(self.counts)
            if token >= largest:
                return
            del self.counts[largest]
        self.counts[token] += 1

    def values(self) -> list[dict[str, object]]:
        return [
            {"value": token, "count": count}
            for token, count in sorted(self.counts.items())
        ]
