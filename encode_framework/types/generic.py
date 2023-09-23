import os
from typing import Any

try:
    from typing import Iterable
except AttributeError:
    from collections import Iterable

__all__: list[str] = [
    "SystemName",
    "IsWindows",

    "TruthyInput",

    "TextSubExt",
    "BitmapSubExt",

    "is_iterable",
]

SystemName = os.name
"""The name of the system."""

IsWindows = SystemName in ("nt")
"""Bool indicating whether we're on a Windows machine."""

TruthyInput = ("yes", "y", "1")
"""Outputs that should be considered as \"True\" for user input."""

TextSubExt = (".ass", ".srt", ".vtt")
"""Text-based subtitle extensions"""

BitmapSubExt = (".idx", ".pgs", ".sub", ".sup")
"""Bitmap-based subtitle extensions"""


def is_iterable(obj: Any, count_str: bool = False) -> bool:
    """Check whether the given object is iterable (but not a string unless accepted)."""
    is_iter = isinstance(obj, Iterable)

    if count_str:
        return is_iter

    return is_iter and not isinstance(obj, str)
