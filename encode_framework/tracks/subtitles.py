import os

from babelfish import Language  # type:ignore[import]
from magic import Magic
from vsmuxtools import SubFile, SubTrack, frame_to_ms
from vstools import SPath, SPathLike

from ..types import IsWindows, TextSubExt
from ..util import cargo_build, check_program_installed, run_cmd
from ..util.git import clone_git_repo
from ..util.logging import Log
from .base import _BaseEncoder

__all__: list[str] = [
    "_Subtitles"
]


class _Subtitles(_BaseEncoder):

    subtitle_files: list[SubFile] = []
    """A list of all the subtitle source files."""

    subtitle_tracks: list[SubTrack] = []
    """A list of all subtitle tracks."""

    def find_sub_files(self, dgi_path: SPathLike | None = None) -> list[SPath]:
        """
        Find accompanying DGIndex(NV) demuxed pgs tracks.

        If input file is not a dgi file, it will throw an error.
        """
        dgi_file = SPath(dgi_path) if dgi_path is not None else self.script_info.src_file

        if not dgi_file.to_str().endswith(".dgi"):
            Log.error("Input file is not a dgi file, not returning any subs", self.find_sub_files)
            return []

        mg = Magic(mime=True)

        # TODO: make sure this checks the stem of the filename so it doesn't grab the wrong sup's.
        for f in dgi_file.parent.glob(f"{dgi_file.stem}*.*"):
            Log.debug(f"Checking the following file: \"{f.name}\"...", self.find_sub_files)

            get_mime = mg.from_file(f.to_str())

            sub_file = SubFile(f, source=dgi_file)

            if get_mime == "application/octet-stream" and f.to_str().endswith((".sup", ".pgs")):
                self.subtitle_files += [sub_file]
            elif get_mime == "video/mpeg" and f.to_str().endswith(".sub"):
                self.subtitle_files += [sub_file]
            elif f.to_str().endswith(TextSubExt):
                self.subtitle_files += [sub_file]

        if not self.subtitle_files:
            return self.subtitle_files

        Log.info("The following subtitle files were found!", self.find_sub_files)

        for f in self.subtitle_files:
            try:
                Log.info(f"    - \"{SPath(f).name}\"", self.find_sub_files)
            except (AttributeError, ValueError) as e:
                Log.warn(f"    - Could not determine track name!\n{e}", self.find_sub_files)

        return self.subtitle_files

    def process_subs(
        self, subtitle_files: SPathLike | list[SPath] | None = None,
        langs: list[Language] = [Language("eng"), Language("jpn")],
        sub_delay: int | None = None, strict: bool = False
    ) -> list[SubTrack]:
        """
        OCR and process any files that are found.
        """
        if subtitle_files is not None and not isinstance(subtitle_files, list):
            subtitle_files = [SPath(subtitle_files)]

        sub_files = subtitle_files or self.subtitle_files

        if not sub_files:
            return sub_files

        Log.info("The following subtitle files were found!", self.process_subs)

        for sub in sub_files:
            try:
                Log.info(f"    - \"{SPath(sub).name}\"", self.process_subs)
            except (AttributeError, ValueError) as e:
                Log.warn(f"    - Could not determine track name!\n{e}", self.process_subs)

        if sub_delay is None:
            sub_delay = frame_to_ms(self.script_info.src.trim[0], self.out_clip.fps, compensate=True) * -1

        # TODO: Add trim logic from SubFile.

        try:
            check_program_installed("tesseract", "https://codetoprosper.com/tesseract-ocr-for-windows/", _raise=True)
        except FileNotFoundError as e:
            Log.error(str(e), self.process_subs)

            Log.warn("Will still convert the files to tracks...", self.process_subs)

            self.subtitle_tracks = list([
                SubTrack(sub, default=not bool(i), delay=int(sub_delay))
                for i, sub in enumerate(self.subtitle_files)
            ])

            return self.subtitle_tracks

        try:
            clone_git_repo("https://github.com/tesseract-ocr/tessdata_best.git")
        except Exception as e:
            if not "exit code(128)" in str(e):
                Log.error(f"Some kind of error occurred while cloning the \"tessdata_best\" repo!\n{e}", self.process_subs)

                return sub_files

            pass

        mg = Magic(mime=True)
        proc_files = []
        ocrd = []

        for i, sub in enumerate(sub_files):
            sub_spath = SPath(sub)

            Log.info(f"[{i + 1}/{len(sub_files)}] OCRing \"{sub_spath.name}\"...", self.process_subs)

            if sub_spath.to_str().endswith(TextSubExt):
                Log.info(
                    f"[{i + 1}/{len(sub_files)}] \"{sub_spath.name}\" is a text-based "
                    "subtitle format. Skipping OCR!", self.process_subs
                )

                proc_files += [sub_spath]

                continue

            get_mime = mg.from_file(SPath(sub).to_str())

            if get_mime == "application/octet-stream" and sub_spath.to_str().endswith((".sup", ".pgs")):
                from pgsrip import Options, Sup, pgsrip  # type:ignore

                if pgsrip.rip(Sup(sub), Options(languages=langs, overwrite=not strict, one_per_lang=False)):
                    Log.info(f"[{i + 1}/{len(sub_files)}] Done!", self.process_subs)

                    proc_files += [sub_spath.with_suffix(".srt")]
                    ocrd += [sub_spath.with_suffix(".srt")]
                else:
                    Log.warn(
                        f"An error occurred while OCRing \"{sub_spath.name}\"! Passing the original file instead...",
                        self.process_subs
                    )

                    proc_files += [sub_spath]
            elif get_mime == "video/mpeg" and sub_spath.to_str().endswith(".sub"):
                idx = SPath(sub).with_suffix(".idx")
                out = sub_spath.with_suffix(".srt")

                try:
                    if not check_program_installed("vobsubocr"):
                        Log.error("\"vobsubocr\" could not be found! Attempting to build...", self.process_subs)

                        if not check_program_installed("vcpkg"):
                            repo = clone_git_repo("https://github.com/microsoft/vcpkg")

                            if IsWindows:
                                run_cmd([repo / "bootstrap-vcpkg.bat"])
                                run_cmd([repo / "vcpkg", "integrate", "install"])
                            else:
                                run_cmd([repo / "bootstrap-vcpkg.sh"])

                        cargo_build("vobsubocr")

                    run_cmd(["vobsubocr", "-l", langs[0], "-o", out, idx])

                    proc_files += [out]
                    ocrd += [out]
                except Exception as e:
                    Log.error(str(e), self.process_subs)

                    proc_files += [sub_spath]
            else:
                Log.info(
                    f"[{i + 1}/{len(sub_files)}] \"{sub_spath.name}\" is not a text-based "
                    "subtitle format, but could not process. Not touching.", self.process_subs
                )

                proc_files += [sub_spath]

        proc_set = set(proc_files)

        if len(proc_files) != len(proc_set):
            Log.debug(f"Removed duplicate tracks ({len(proc_files)} -> {len(proc_set)})", self.process_subs)

        first_track_removed = False

        for i, sub in enumerate(proc_set):
            if os.stat(sub).st_size == 0:
                Log.warn(f"\"{SPath(sub).name}\" is an empty file! Ignoring...", self.process_subs)

                first_track_removed = True

                continue

            name = ""

            if sub in ocrd:
                name = "OCR'd"

            self.subtitle_tracks += [SubTrack(
                sub, name=name, default=first_track_removed or not bool(i), delay=int(sub_delay)
            )]

        return self.subtitle_tracks