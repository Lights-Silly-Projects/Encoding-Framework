from typing import Literal

__all__: list[str] = [
    "Zones",

    "TrimAuto",
]

Zones = list[tuple[int | None, int | None, float]]
"""List of tuples containing zoning information (start, end, bitrate multiplier)."""

TrimAuto = tuple[int | Literal["auto"] | None, int | Literal["auto"] | None]
"""Trims with literal string \"auto\" added."""
