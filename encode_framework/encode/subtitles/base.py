from vsmuxtools import FontFile, SubFile, SubTrack
from vstools import SPath

from ...types import BitmapSubExt
from ..base import _BaseEncoder

__all__: list[str] = [
    "_BaseSubtitles"
]

class _BaseSubtitles(_BaseEncoder):

    subtitle_files: list[SubFile] = []
    """A list of all the subtitle source files."""

    subtitle_tracks: list[SubTrack] = []
    """A list of all subtitle tracks."""

    font_files: list[FontFile] = []
    """A list of fonts collected from the file."""

    def _can_be_ocrd(self, file: SPath) -> bool:
        """Verify whether a subtitle file can be OCR'd."""
        return SPath(file).to_str().endswith(BitmapSubExt)
