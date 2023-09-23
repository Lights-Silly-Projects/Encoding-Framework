import filecmp
import shutil

from vsmuxtools import GJM_GANDHI_PRESET, SubFile, SubTrack, frame_to_ms, get_setup_attr, get_workdir, uniquify_path
from vstools import SPath, SPathLike, vs

from ...types import BitmapSubExt, TextSubExt
from ...util import Log
from .base import _BaseSubtitles
from .enum import OcrProgram

__all__: list[str] = [
    "_ProcessSubtitles"
]

class _ProcessSubtitles(_BaseSubtitles):
    """Class containing methods pertaining to processing subtitle( file)s."""

    def process_subs(
        self, subtitle_files: SPathLike | list[SPath] | None = None,
        ref: vs.VideoNode | None = None,
        ocr_program: OcrProgram | None = OcrProgram.SUBTITLEEDIT,
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
        if ocr_program is None:
            ocr_program = OcrProgram.PASSTHROUGH

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
            if not self._can_be_ocrd(ocrd_file):
                self._process_ocr_file(SPath(ocrd_file))

        self._trackify(proc_set, ocrd_files, wclip, frame_to_ms(sub_delay or 0, wclip.fps))
        self._clean_ocr(ocrd_files)

        if save:
            for f in self._save(self.script_info.src_file[0]):
                Log.info(f"Copying subs to \"{f}\"!", self.process_subs)

        return self.subtitle_tracks

    def _save(self, name: SPathLike) -> list[SPath]:
        show_name = get_setup_attr("show_name", "Example")
        episode = get_setup_attr("episode", "01")

        new_files: list[SPath] = []

        for sub in list(get_workdir().glob(f"{SPath(name).stem}*_vof.[as][sr][st]")):
            if self._check_filesize(sub, caller=self._save):
                continue

            out = SPath.cwd() / "_subs" / f"{show_name} - {episode}.ass"

            if out.exists() and filecmp.cmp(sub, out, shallow=False):
                Log.debug(f"\"{sub.name}\" already exists in the out dir. Skipping...", self._save)
                new_files += [out]
                continue

            (SPath.cwd() / "_subs").mkdir(exist_ok=True)

            new_files += [SPath(shutil.copy(sub, uniquify_path(out)))]

        return new_files

    def _process_ocr_file(self, file: SPath) -> None:
        clean = file.with_stem(file.stem + "_clean")

        if clean.exists():
            clean.unlink()

        try:
            with open(file, "rt") as fin:
                with open(clean, "wt") as fout:
                    for line in fin:
                        line = line.replace("|", "I")
                        line = line.replace("{\i}", "{\i0}")

                        fout.write(line)
        except Exception as e:
            Log.debug(f"An error occurred while trying to clean \"{file}\"!\n{e}", self._process_ocr_file)

        if self._check_filesize(clean, warn=False, caller=self._process_ocr_file):
            clean.unlink()
            return

        file.unlink()
        clean.rename(file)

    def _prepare_subfile(self, file: SPath, ref: vs.VideoNode | None = None, sub_delay: int = 0) -> SubFile:
        if file.to_str().endswith(".srt"):
            sub_file = SubFile.from_srt(file)
            sub_file.container_delay = int(sub_delay)
            sub_file = sub_file.restyle(GJM_GANDHI_PRESET)
        else:
            sub_file = SubFile(file, container_delay=int(sub_delay))

        sub_file = sub_file.shift(-self.script_info.trim[0], self.script_info.clip_cut.fps)

        if ref:
            sub_file = sub_file.truncate_by_video(ref)

        return sub_file

    def _clean_ocr(self, files: list[SPath]) -> None:
        if not isinstance(files, list):
            files = [files]

        for f in files:
            for s in f.parent.glob(f.stem):
                if s.to_str().endswith(BitmapSubExt):
                    Log.debug(f"Cleaning up \"{s}\"...", self.process_subs)
                    s.unlink()

    def _trackify(
        self, processed_files: list[SPath], ocrd_files: list[SPath],
        ref: vs.VideoNode | None = None, sub_delay: int = 0
    ) -> None:
        first_track_removed = False

        for i, sub in enumerate(processed_files):
            sub = SPath(sub)

            if self._check_filesize(sub, caller=self._trackify):
                first_track_removed = True
                continue

            name = "OCR'd" if sub in ocrd_files else ""
            default = default=first_track_removed or not bool(i)

            if sub.to_str().endswith(".sup"):
                self.subtitle_tracks += [SubTrack(sub, name, default, delay=sub_delay)]
            else:
                sub_file = self._prepare_subfile(sub, ref, sub_delay)
                self.subtitle_tracks += [sub_file.to_track(name, default=first_track_removed or not bool(i))]
                self.font_files = sub_file.collect_fonts(search_current_dir=False)

    def _process_files(
        self, sub_files: list[SPath],
        ocr_program: OcrProgram | None = OcrProgram.SUBTITLEEDIT,
        ref: vs.VideoNode | None = None
    ) -> tuple[list[SPath], list[SPath]]:
        if ocr_program is None:
            ocr_program = OcrProgram.PASSTHROUGH

        proc_files: list[SPath] = []
        ocrd_files: list[SPath] = []

        for i, sub_file in enumerate(sub_files):
            sub_spath = SPath(sub_file)

            num = f"[{i + 1}/{len(sub_files)}]"

            # Existing processed subs already exist
            if x := list(get_workdir().glob(f"{sub_spath.stem}*_vof.[as][sr][st]")):
                found: list[SPath] = []

                for y in x:
                    if self._check_filesize(y, caller=self._process_files):
                        y.unlink()
                        continue

                    Log.info(f"{num} \"{SPath(y).name}\" found! Skipping processing...", self.process_subs)
                    proc_files = [y]
                    found += [y]

                if found:
                    continue

            # Softsubs found, do not do anything special.
            if sub_spath.to_str().endswith(TextSubExt):
                Log.info(
                    f"{num} \"{sub_spath.name}\" is a text-based subtitle format. "
                    "Skipping OCR!", self.process_subs
                )

                proc_files += [sub_spath]

                continue

            # Try to run the OCR tool
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
