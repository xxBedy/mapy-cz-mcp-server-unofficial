"""Účtování kreditů.

Každé volání API stojí kredity. Ceny podle ceníku na https://developer.mapy.com/cs/cena/.
Cena buňky matice je z ceníku odvozená (40 kreditů za matici 10x10 = 0,4 za buňku)
a je proto označená jako odhad.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .errors import CreditBudgetExceeded

COST_GEOCODE = 4.0
COST_ROUTING = 4.0
COST_ELEVATION = 4.0
COST_STATIC = 4.0
COST_TIMEZONE = 1.0
COST_TILE = 1.0
COST_MATRIX_CELL = 0.4  # odvozeno: 40 kreditů / 100 buněk


@dataclass
class CreditLedger:
    """Součet kreditů spotřebovaných v této session.

    Je to lokální odhad, ne stav účtu — API zůstatek nevystavuje.
    """

    budget: int | None = None
    spent: float = 0.0
    by_operation: dict[str, float] = field(default_factory=dict)
    calls: int = 0

    def check(self, amount: float) -> None:
        if self.budget is not None and self.spent + amount > self.budget:
            raise CreditBudgetExceeded(self.spent, self.budget, amount)

    def record(self, operation: str, amount: float) -> None:
        self.spent += amount
        self.calls += 1
        self.by_operation[operation] = self.by_operation.get(operation, 0.0) + amount

    def snapshot(self) -> dict[str, object]:
        return {
            "spentCredits": round(self.spent, 1),
            "calls": self.calls,
            "budget": self.budget,
            "remaining": (round(self.budget - self.spent, 1) if self.budget is not None else None),
            "byOperation": {k: round(v, 1) for k, v in sorted(self.by_operation.items())},
            "note": (
                "Lokální odhad podle ceníku, ne stav účtu — API zůstatek nevystavuje. "
                "Cena buňky matice (0,4) je z ceníku odvozená."
            ),
        }
