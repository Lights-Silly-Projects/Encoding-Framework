from muxtools import FontFile, SubFile, SubTrack

from ..base import _BaseEncoder


__all__: list[str] = [
    "_BaseSubtitles"
]

class _BaseSubtitles(_BaseEncoder):
    """The base class for subtitles."""

    subtitle_files: list[SubFile] = []
    """A list of all the subtitle source files."""

    subtitle_tracks: list[SubTrack] = []
    """A list of all subtitle tracks."""

    font_files: list[FontFile] = []
    """A list of fonts collected from the file."""