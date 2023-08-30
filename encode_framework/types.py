from typing import Literal
import os

__all__: list[str] = [
    "TrimAuto",
    "TextSubExt",
    "is_windows",
]

TrimAuto = tuple[int | Literal["auto"] | None, int | Literal["auto"] | None]

TextSubExt = (".ass", ".srt", ".vtt")

is_windows = os.name == "nt"
