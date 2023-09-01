import os

__all__: list[str] = [
    "SystemName",
    "IsWindows",

    "TrueOutputs",

    "TextSubExt",
]

SystemName = os.name
"""The name of the system."""

IsWindows = SystemName in ("nt")
"""Bool indicating whether we're on a Windows machine."""

TrueOutputs = ("yes", "y", "1")
"""Outputs that should be considered as \"True\" for user input."""

TextSubExt = (".ass", ".srt", ".vtt")
"""Text-based subtitle extensions"""
