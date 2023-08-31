import os
from typing import Literal

__all__: list[str] = [
    "Zones",
    "TrimAuto",
    "TextSubExt",
    "is_windows",
]


Zones = list[tuple[int, int, float]]
"""List of tuples containing zoning information (start, end, bitrate multiplier)."""

TrimAuto = tuple[int | Literal["auto"] | None, int | Literal["auto"] | None]
"""Trims with literal string \"auto\" added."""

TextSubExt = (".ass", ".srt", ".vtt")
"""Text-based subtitle extensions"""

is_windows = os.name == "nt"
"""Check whether we're on a Windows machine."""
