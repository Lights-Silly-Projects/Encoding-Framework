from .find import _FindSubtitles
from .process import _ProcessSubtitles

__all__: list[str] = [
    "_Subtitles"
]


class _Subtitles(_FindSubtitles, _ProcessSubtitles):
    """A subtitles class to consolidate all the individual subtitle class components."""
    ...
