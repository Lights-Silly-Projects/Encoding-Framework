from typing import Literal

__all__: list[str] = [
    "TrimAuto"
]

TrimAuto = tuple[int | Literal["auto"] | None, int | Literal["auto"] | None]
