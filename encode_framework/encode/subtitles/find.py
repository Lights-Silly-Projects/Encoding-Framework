from typing import Any, Callable

from vstools import SPath, SPathLike, to_arr

from ...types import BitmapSubExt, TextSubExt
from ...util import Log
from .base import _BaseSubtitles

__all__: list[str] = ["_FindSubtitles"]


class _FindSubtitles(_BaseSubtitles):
    """Class containing methods pertaining to finding subtitle files."""

    def find_sub_files(
        self, dgi_path: SPathLike | None = None, **kwargs: Any
    ) -> list[SPath]:
        """
        Find accompanying DGIndex(NV) demuxed pgs tracks.

        If input file is not a dgi file, it will throw an error.
        """

        if isinstance(dgi_path, list):
            dgi_path = dgi_path[0]

        if dgi_path is not None:
            dgi_file = SPath(dgi_path)
        else:
            dgi_file = self.script_info.src_file[0]

        if not dgi_file.to_str().endswith(".dgi"):
            Log.error(
                "Input file is not a dgi file, not returning any subs.",
                self.find_sub_files,
            )

            return []

        if not dgi_file.to_str().endswith(".dgi") and not kwargs.get("_is_loop", False):
            Log.warn(
                "Trying to pass a non-dgi file! "
                "Extracting tracks using DGIndexNV in %TEMP% (this may take some time)...",
                self.find_sub_files,
            )

            old_script_info_src = self.script_info.src_file
            old_script_info_trim = self.script_info.trim

            self.script_info.src_file = []
            self.script_info.index(dgi_file, force_dgi=True)

            sfiles = self.find_sub_files(self.script_info.src_file[0], _is_loop=True)

            # Delete files from tempdir
            (f.unlink(True) for f in to_arr(self.script_info.src_file))

            self.script_info.src_file = old_script_info_src
            self.script_info.update_trims(old_script_info_trim)

            return sfiles

        self._find(dgi_file.parent.glob(f"{dgi_file.stem}*.*"), self.find_sub_files)

        if not self.subtitle_files:
            return []

        self.subtitle_files = sorted(self.subtitle_files, key=self.extract_pid)

        self._announce(self.find_sub_files)

        return self.subtitle_files

    def _find(
        self, files: list[SPath], caller: str | Callable[[Any], Any] | None = None
    ) -> Any:
        for f in files:
            Log.debug(f'Checking the following file: "{f.name}"...', caller)

            f_no_undersc = SPath(f.to_str().split("_")[0])

            bitmap_exist = any(
                f.with_suffix(ext).exists() or f_no_undersc.with_suffix(ext).exists()
                for ext in BitmapSubExt
            )

            if f.suffix in TextSubExt and bitmap_exist:
                Log.debug(
                    f'"{f.name}" is an OCR\'d subtitle file from an existing '
                    "bitmap subtitle file. Skipping...",
                    caller,
                )
                f.unlink()

                continue

            if self._can_be_ocrd(f) or f.to_str().endswith(TextSubExt):
                self.subtitle_files += [f]

    def _announce(self, caller: str | Callable[[Any], Any] | None = None) -> None:
        Log.info("The following subtitle files were found!", caller)

        for f in self.subtitle_files:
            try:
                Log.info(f'    - "{SPath(f).name}"', caller)
            except (AttributeError, ValueError) as e:
                Log.warn(f"    - Could not determine track name!\n{e}", caller)
