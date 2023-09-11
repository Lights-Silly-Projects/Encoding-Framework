from babelfish import Language  # type:ignore[import]
from magic import Magic
from muxtools import FontFile, SubTrack, frame_to_ms, make_output  # type:ignore[import]
from vsmuxtools import SubFile  # type:ignore[import]
from vstools import SPath, SPathLike, vs

from ..git import clone_git_repo
from ..types import IsWindows, TextSubExt
from ..util import Log, cargo_build, check_program_installed, run_cmd
from .base import _BaseEncoder

__all__: list[str] = [
    "_Subtitles"
]


class _Subtitles(_BaseEncoder):

    subtitle_files: list[SubFile] = []
    """A list of all the subtitle source files."""

    subtitle_tracks: list[SubTrack] = []
    """A list of all subtitle tracks."""

    font_files: list[FontFile] = []
    """A list of fonts collected from the file."""

    def find_sub_files(self, dgi_path: SPathLike | None = None) -> list[SPath]:
        """
        Find accompanying DGIndex(NV) demuxed pgs tracks.

        If input file is not a dgi file, it will throw an error.
        """
        dgi_file = SPath(dgi_path) if dgi_path is not None else self.script_info.src_file

        # TODO: Add logic to find and merge subs from multiple files, i.e. VOBs
        if isinstance(dgi_file, list):
            dgi_file = dgi_file[0]

        if not dgi_file.to_str().endswith(".dgi"):
            Log.error("Input file is not a dgi file, not returning any subs", self.find_sub_files)

            return []

        mg = Magic(mime=True)

        # TODO: make sure this checks the stem of the filename so it doesn't grab the wrong sup's.
        for f in dgi_file.parent.glob(f"{dgi_file.stem}*.*"):
            Log.debug(f"Checking the following file: \"{f.name}\"...", self.find_sub_files)

            get_mime = mg.from_file(f.to_str())

            if get_mime == "application/octet-stream" and f.to_str().endswith((".sup", ".pgs")):
                self.subtitle_files += [f]
            elif get_mime == "video/mpeg" and f.to_str().endswith(".sub"):
                self.subtitle_files += [f]
            elif f.to_str().endswith(TextSubExt):
                self.subtitle_files += [f]

        if not self.subtitle_files:
            Log.debug("No subtitle files found!", self.find_sub_files)

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
        ref: vs.VideoNode | None = None,
        langs: list[Language] = [Language("eng"), Language("jpn")],
        sub_delay: int | None = None, strict: bool = False
    ) -> list[SubTrack]:
        """
        OCR and process any files that are found.

        :param sub_delay:           Delay in frames. Will use the ref clip as a reference.
        """
        if subtitle_files is not None and not isinstance(subtitle_files, list):
            subtitle_files = [SPath(subtitle_files)]

        sub_files = subtitle_files or self.subtitle_files

        if not sub_files:
            return sub_files

        wclip = ref or self.out_clip

        sub_delay = frame_to_ms(sub_delay or 0, wclip.fps)

        Log.info("The following subtitle files were found!", self.process_subs)

        for sub in sub_files:
            try:
                Log.info(f"    - \"{SPath(sub).name}\"", self.process_subs)
            except (AttributeError, ValueError) as e:
                Log.warn(f"    - Could not determine track name!\n{e}", self.process_subs)

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
                Log.error(
                    f"Some kind of error occurred while cloning the \"tessdata_best\" repo!\n{e}", self.process_subs)

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

                    # Move to workdir
                    new_path = sub_spath.with_suffix(".srt").rename(make_output(sub_spath, "srt", "ocrd", False))

                    proc_files += [new_path]
                    ocrd += [new_path]
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
                                run_cmd([str(repo / "bootstrap-vcpkg.bat")])
                                run_cmd([str(repo / "vcpkg"), "integrate", "install"])
                            else:
                                run_cmd([str(repo / "bootstrap-vcpkg.sh")])

                        cargo_build("vobsubocr")

                    run_cmd(["vobsubocr", "-l", langs[0], "-o", out.to_str(), idx.to_str()])

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

        # Fixing a handful of very common OCR errors I encountered myself...
        for ocrd_file in ocrd:
            ocrd_file = SPath(ocrd_file)

            clean = ocrd_file.with_stem(ocrd_file.stem + "_clean")

            with open(ocrd_file, "rt") as fin:
                with open(clean, "wt") as fout:
                    for line in fin:
                        line = line.replace("|", "I")

                        fout.write(line)

            ocrd_file.unlink()
            clean.rename(ocrd_file)

        first_track_removed = False

        for i, sub in enumerate(proc_set):
            sub = SPath(sub)

            if sub.stat().st_size == 0:
                Log.warn(f"\"{SPath(sub).name}\" is an empty file! Ignoring...", self.process_subs)

                first_track_removed = True

                continue

            name = ""

            if sub in ocrd:
                name = "OCR'd"

            if sub.to_str().endswith(".srt"):
                sub = SubFile.from_srt(sub)
                sub.container_delay = int(sub_delay)
            else:
                sub = SubFile(sub, delay=int(sub_delay))

            sub = sub.shift(-self.script_info.trim[0])
            sub = sub.truncate_by_video(wclip)

            self.subtitle_tracks += [sub.to_track(name, default=first_track_removed or not bool(i))]
            self.font_files = sub.collect_fonts(search_current_dir=False)

        return self.subtitle_tracks
