from babelfish import Language
from vstools import SPath, SPathLike

from .base import _BaseSubtitles
from .enum import OcrProgram
from typing import Literal
from ...util import Log


__all__: list[str] = [
    "_SubtitlesProcess"
]


class _SubtitlesProcess(_BaseSubtitles):
    """A private class containing methods for OCRing and cleaning up subtitle files."""

    def ocr(self, file: SPathLike, langs: list[Language] = [Language("eng"), Language("jpn")]) -> SPath:
        """
        OCR the subtitles if possible. If not, throw a warning and return the original file's path.

        This method assumes the given file is a file that can be OCR'd.

        :param file:            File to process.
        :param langs:           Languages to process.

        :return:                SPath to the OCR'd file if succesful, else the original file.
        """
        sfile = SPath(file)

        if (x := sfile.exists()) is False:
            Log.error(f"The file {x} could not be found!", self.ocr)
            return x

        if (tool := self._pick_ocr()) is False:
            Log.error("Could not find or install any supported OCR packages!", self.ocr)
            return sfile



        # run_cmd(["vobsubocr", "-l", langs[0], "-o", out.to_str(), idx.to_str()])
        ...

    def _pick_ocr(self) -> OcrProgram | Literal[False]:
        """Try to pick an OCR program to use. Try to install one if none are currently installed"""
        for program in OcrProgram:
            if program.installed:
                return program

        for program in OcrProgram:
            if program.install():
                return program

        return False

