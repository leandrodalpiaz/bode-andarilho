from __future__ import annotations

from collections import Counter
from threading import Lock
from typing import Any


class PwaMetrics:
    """Contadores mínimos do processo para o piloto de uma instância.

    Os rótulos são controlados pelo backend (operação/status), evitando que
    tokens, e-mails ou URLs criem cardinalidade não controlada. Antes de
    escalar horizontalmente, o armazenamento deve ser trocado por um coletor
    externo.
    """

    def __init__(self) -> None:
        self._counters: Counter[tuple[str, tuple[tuple[str, str], ...]]] = Counter()
        self._lock = Lock()

    def increment(self, name: str, **labels: Any) -> None:
        key = (
            name,
            tuple(sorted((str(label), str(value)) for label, value in labels.items())),
        )
        with self._lock:
            self._counters[key] += 1

    def snapshot(self) -> dict[str, list[dict[str, Any]]]:
        with self._lock:
            values = list(self._counters.items())
        counters = []
        for (name, labels), value in sorted(values, key=lambda item: item[0]):
            counters.append(
                {
                    "name": name,
                    "labels": dict(labels),
                    "value": value,
                }
            )
        return {"counters": counters}
