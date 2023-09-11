from typing import Any

from magic import Magic
from vstools import SPath, vs

from ...util import Log
from .base import _BaseSubtitles

__all__: list[str] = [
    "_SubtitleFormats"
]

class _SubtitleFormats(_BaseSubtitles):
    """A private class containing methods for determining subtitle formats and converting between them."""

    __hardsub_mimes: tuple[str, ...] = ("application/octet-stream", "video/mpeg")
    """Common mimes for hardsub streams."""

    __hardsub_exts: tuple[str, ...] = (".sup", ".pgs", ".sub")
    """Common extensions for hardsub streams."""

    def can_be_ocrd(self, file: SPath) -> bool:
        """
        Determine whether the given file is a subtitle file that can be ocr'd.

        :param file:        File to process.

        :return: A boolean representing whether a file can be OCR'd or not.
        """
        may_be_sub = self._get_mime(file) in self.__hardsub_mimes and file.to_str().endswith(self.__hardsub_exts)

        if not may_be_sub:
            return may_be_sub

        # Extra check to make sure necessary component files can be located.
        if file.to_str().endswith(".sub"):
            if not file.with_suffix(".idx").exists():
                Log.warn(f"\"{file}\" file found, but no accompanying \".idx\" file found!", self.can_be_ocrd)

                return False

        return may_be_sub

    def to_ass(self, file: SPath, ref: vs.VideoNode | None) -> SPath:
        """
        Try to convert the given file to an ASS subtitle file.

        :param file:        File to process.
        :param ref:         Ref VideoNode to use for trimming and the like.

        :return:            Path to new ASS file or the original file if it was unsuccesful.
        """

        # TODO:
        ...

    def _get_mime(self, file: SPath) -> Any:
        """Obtain the mime from a given file."""
        if not hasattr(self, "_magic"):
            self._magic = Magic(mime=True)

        return self._magic.from_file(file.to_str())
