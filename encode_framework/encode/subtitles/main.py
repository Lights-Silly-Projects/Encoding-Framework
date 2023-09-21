import shutil

from muxtools import FontFile, frame_to_ms, get_setup_attr, uniquify_path, get_workdir  # type:ignore[import]
from vsmuxtools import SubFile, SubTrack  # type:ignore[import]
from vstools import SPath, SPathLike, vs

from ...types import TextSubExt
from ...util import Log
from .base import _BaseEncoder
from .enum import OcrProgram

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

        if isinstance(dgi_file, list):
            dgi_file = dgi_file[0]

        if not dgi_file.to_str().endswith(".dgi"):
            Log.error("Input file is not a dgi file, not returning any subs.", self.find_sub_files)

            return []

        for f in dgi_file.parent.glob(f"{dgi_file.stem}*.*"):
            Log.debug(f"Checking the following file: \"{f.name}\"...", self.find_sub_files)

            if self._can_be_ocrd(f) or f.to_str().endswith(TextSubExt):
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
        ocr_program: OcrProgram = OcrProgram.SUBTITLEEDIT,
        sub_delay: int | None = None,
        save: bool = True,
    ) -> list[SubTrack]:
        """
        OCR and process any files that are found.

        :param subtitle_files:      A list of subtitle files. If None, gets it from previous subs found.
        :param ref:                 A reference video node to use for processing.
        :param ocr_program:         The OCR program to use. See `OcrProgram` for more information.
        :param sub_delay:           Delay in frames. Will use the ref clip as a reference.
        :param save:                Whether to save the subtitles in a different directory.
        """
        if subtitle_files is not None and not isinstance(subtitle_files, list):
            subtitle_files = [SPath(subtitle_files)]
        elif isinstance(subtitle_files, list):
            subtitle_files = [SPath(x) for x in subtitle_files]

        sub_files = subtitle_files or self.subtitle_files

        if not sub_files:
            return sub_files

        wclip = ref or self.out_clip

        proc_files, ocrd_files = self._process_files(sub_files, ocr_program, wclip)

        proc_set = set(proc_files)

        if len(proc_files) != len(proc_set):
            Log.debug(f"Removed duplicate tracks ({len(proc_files)} -> {len(proc_set)})", self.process_subs)

        # Fixing a handful of very common OCR errors I encountered myself and other minor adjustments...
        for ocrd_file in ocrd_files:
            self._process_ocr_file(SPath(ocrd_file))

        self._trackify(proc_set, ocrd_files, wclip, frame_to_ms(sub_delay or 0, wclip.fps))
        self._clean_ocr(sub_files, self.script_info.src_file[0])

        if save:
            for f in self._save(self.script_info.src_file[0]):
                Log.info(f"Saving subs at \"{f}\"!", self.process_subs)

        return self.subtitle_tracks

    def _save(self, og_name: SPathLike) -> list[SPath]:
        show_name = get_setup_attr("show_name", "Example")
        episode = get_setup_attr("episode", "01")

        (SPath.cwd() / "_subs").mkdir(exist_ok=True)

        new_files: list[SPath] = []

        for sub in list(get_workdir().glob(f"{SPath(og_name).stem}*_vof.[as][sr][st]")):
            new_files += [SPath(shutil.copy(sub, uniquify_path(SPath.cwd() / "_subs" / f"{show_name} {episode}.ass")))]

        return new_files

    def _can_be_ocrd(self, file: SPath) -> bool:
        return SPath(file).to_str().endswith((".pgs", ".sup", ".sub", ".idx"))

    def _process_ocr_file(self, file: SPath) -> None:
        clean = file.with_stem(file.stem + "_clean")

        with open(file, "rt") as fin:
            with open(clean, "wt") as fout:
                for line in fin:
                    line = line.replace("|", "I")
                    line = line.replace("{\i}", "{\i0}")

                    fout.write(line)

        file.unlink()
        clean.rename(file)

    def _check_filesize(self, file: SPath) -> bool:
        if (x := file.stat().st_size == 0):
            Log.warn(f"\"{SPath(file).name}\" is an empty file! Ignoring...", self.process_subs)

        return x

    def _prepare_subfile(self, file: SPath, ref: vs.VideoNode | None = None, sub_delay: int = 0) -> SubFile:
        if file.to_str().endswith(".srt"):
            sub_file = SubFile.from_srt(file)
            sub_file.container_delay = int(sub_delay)
        else:
            sub_file = SubFile(file, container_delay=int(sub_delay))

        sub_file = sub_file.shift(-self.script_info.trim[0])

        if ref:
            sub_file = sub_file.truncate_by_video(ref)

        return sub_file

    def _clean_ocr(self, files: list[SPath], og_name: SPathLike) -> None:
        if not isinstance(files, list):
            files = [files]

        for f in files:
            if not self._can_be_ocrd(f):
                continue

            for s in f.parent.glob(f"{SPath(og_name).stem}.[as][sr][st]"):
                Log.debug(f"Cleaning up \"{s}\"...", self.process_subs)
                s.unlink()

    def _trackify(
        self, processed_files: list[SPath], ocrd_files: list[SPath],
        ref: vs.VideoNode | None = None, sub_delay: int = 0
    ) -> None:
        first_track_removed = False

        for i, sub in enumerate(processed_files):
            sub = SPath(sub)

            if self._check_filesize(sub):
                first_track_removed = True
                continue

            name = "OCR'd" if sub in ocrd_files else ""

            sub_file = self._prepare_subfile(sub, ref, sub_delay)

            self.subtitle_tracks += [sub_file.to_track(name, default=first_track_removed or not bool(i))]
            self.font_files = sub_file.collect_fonts(search_current_dir=False)

    def _process_files(
        self, sub_files: list[SPath],
        ocr_program: OcrProgram,
        ref: vs.VideoNode | None = None
    ) -> tuple[list[SPath], list[SPath]]:
        proc_files: list[SPath] = []
        ocrd_files: list[SPath] = []

        for i, sub_file in enumerate(sub_files):
            sub_spath = SPath(sub_file)

            num = f"[{i + 1}/{len(sub_files)}]"

            if sub_spath.to_str().endswith(TextSubExt):
                Log.info(
                    f"{num} \"{sub_spath.name}\" is a text-based "
                    "subtitle format. Skipping OCR!", self.process_subs
                )

                proc_files += [sub_spath]

                continue

            if x := list(get_workdir().glob(f"{sub_spath.stem}*_vof.[as][sr][st]")):
                for y in x:
                    Log.info(f"{num} \"{SPath(y).name}\" found! Skipping processing...", self.process_subs)
                    proc_files = [y]

                continue

            if not (proc := ocr_program.ocr(sub_spath, ref=ref)):
                Log.warn(
                    f"{num} \"{sub_spath.name}\" is likely not a text-based subtitle format, "
                    "but could not process it. Leaving it untouched!", self.process_subs
                )

                proc_files += [sub_spath]

                continue

            proc_files += [proc]
            ocrd_files += [proc]

        return proc_files, ocrd_files
