import shutil
from itertools import zip_longest
from typing import Any, Literal

from vsmuxtools import (GJM_GANDHI_PRESET, SubFile, SubTrack, frame_to_ms,
                        get_setup_attr, get_workdir, uniquify_path)
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
        reorder: list[int] | Literal[False] = False,
        sub_delay: int | None = None,
        trim: bool | None = None,
        restyle: bool = False,
        save: bool = True,
    ) -> list[SubTrack]:
        """
        OCR and process any files that are found.

        :param subtitle_files:      A list of subtitle files. If None, gets it from previous subs found.
        :param ref:                 A reference video node to use for processing.
        :param ocr_program:         The OCR program to use. See `OcrProgram` for more information.
        :param reorder:             Reorder tracks. For example, if you know you have 3 subtitle tracks
                                    ordered like [JP, EN, "Commentary"], you can pass [1, 0, 2]
                                    to reorder them to [EN, JP, Commentary].
                                    This can also be used to remove specific tracks.
        :param sub_delay:           Delay in frames. Will use the ref clip as a reference.
        :param trim:                Whether to truncate lines that extend past the video.
                                    If None, tries to automatically determine whether it should
                                    based on the existence of `ref` and the difference in frames.
        :param restyle:             Whether to restyle the subs to GJM Gandhi Sans.
        :param save:                Whether to save the subtitles in a different directory.
        """
        if ocr_program is None:
            ocr_program = OcrProgram.PASSTHROUGH

        if subtitle_files is not None and not isinstance(subtitle_files, list):
            subtitle_files = [SPath(subtitle_files)]
        elif isinstance(subtitle_files, list):
            subtitle_files = [SPath(x) for x in subtitle_files]

        sub_files = subtitle_files or self.subtitle_files

        # Normalising reordering of tracks.
        if reorder:
            if len(reorder) > len(sub_files):  # type:ignore[arg-type]
                reorder = reorder[:len(sub_files)]  # type:ignore[arg-type]

            sub_files = [sub_files[i] for i in reorder]  # type:ignore[index, misc]

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

        if trim is None and ref:
            trim = (ref.num_frames * 1.333) > self.out_clip.num_frames

        self._trackify(proc_set, ocrd_files, wclip, frame_to_ms(sub_delay or 0, wclip.fps), trim, restyle)
        self._clean_ocr(ocrd_files)

        if save:
            self._save()

        return self.subtitle_tracks

    def passthrough(
        self, subtitle_files: SPathLike | list[SPath] | None = None,
        track_args: dict[str, Any] = {"lang": "en"},
        reorder: list[int] | Literal[False] = False,
        sub_delay: int | None = None,
    ) -> list[SubTrack]:
        """
        Passthrough the subs as found.

        :param subtitle_files:      A list of subtitle files. If None, gets it from previous subs found.
        :param reorder:             Reorder tracks. For example, if you know you have 3 subtitle tracks
                                    ordered like [JP, EN, "Commentary"], you can pass [1, 0, 2]
                                    to reorder them to [EN, JP, Commentary].
                                    This can also be used to remove specific tracks.
        :param sub_delay:           Delay in frames. Will use the ref clip as a reference.
        :param save:                Whether to save the subtitles in a different directory.
        """

        if subtitle_files is not None and not isinstance(subtitle_files, list):
            subtitle_files = [SPath(subtitle_files)]
        elif isinstance(subtitle_files, list):
            subtitle_files = [SPath(x) for x in subtitle_files]

        sub_files = subtitle_files or self.subtitle_files

        # Normalising reordering of tracks.
        if reorder:
            if len(reorder) > len(sub_files):  # type:ignore[arg-type]
                reorder = reorder[:len(sub_files)]  # type:ignore[arg-type]

            sub_files = [sub_files[i] for i in reorder]  # type:ignore[index, misc]

        if not sub_files:
            return sub_files

        for i, (sub, track_arg) in enumerate(zip_longest(sub_files, track_args)):
            sub = SPath(sub)

            if self.check_is_empty(sub):
                Log.debug(f"\"{sub.name}\" is an empty file! Ignoring...", self.passthrough)
                continue

            Log.info(f"[{i + 1}/{len(sub_files)}] {track_arg=}", self.passthrough)

            self.subtitle_tracks += [SubTrack(sub, **track_arg, delay=sub_delay)]

        return self.subtitle_tracks

    def _save(self) -> list[SPath]:
        show_name = get_setup_attr("show_name", "Example")
        episode = get_setup_attr("episode", "01")

        new_files: list[SPath] = []

        for file in self.subtitle_tracks:
            sub = file.file

            if self.check_is_empty(sub):
                Log.debug(f"\"{SPath(sub).name}\" is an empty file! Ignoring...", self._save)
                continue

            out = SPath.cwd() / "_subs" / f"{show_name} - {episode}.ass"

            if out.exists() and self.check_identical(sub, out, caller=self._save):
                Log.debug(f"\"{sub.name}\" already exists in the out dir. Skipping...", self._save)
                new_files += [out]
                continue

            (SPath.cwd() / "_subs").mkdir(exist_ok=True)

            Log.info(f"Saving subtitle file to \"{out}\"!", self.process_subs)

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
                        line = line.replace(" L ", " I ")
                        line = line.replace(" ll ", " I ")
                        line = line.replace("{\i}", "{\i0}")

                        fout.write(line)
        except Exception as e:
            Log.debug(f"An error occurred while trying to clean \"{file}\"!\n{e}", self._process_ocr_file)

        if self.check_is_empty(clean):
            clean.unlink()
            return

        file.unlink()
        clean.rename(file)

    def _prepare_subfile(
        self, file: SPath, ref: vs.VideoNode | None = None,
        sub_delay: int = 0, trim: bool = True, restyle: bool = False
    ) -> SubFile:
        if file.to_str().endswith(".srt"):
            sub_file = SubFile.from_srt(file)
            sub_file.container_delay = int(sub_delay)

            if restyle:
                sub_file = sub_file.restyle(GJM_GANDHI_PRESET)
        else:
            sub_file = SubFile(file, container_delay=int(sub_delay))

        sub_file = sub_file.shift(-self.script_info.trim[0], self.script_info.clip_cut.fps)

        if ref and trim:
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
        ref: vs.VideoNode | None = None, sub_delay: int = 0,
        trim: bool = True, restyle: bool = False
    ) -> None:
        first_track_removed = False

        for i, sub in enumerate(processed_files):
            sub = SPath(sub)

            if self.check_is_empty(sub):
                Log.debug(f"\"{SPath(sub).name}\" is an empty file! Ignoring...", self._trackify)
                first_track_removed = True
                continue

            name = "OCR'd" if sub in ocrd_files else ""
            default = default=first_track_removed or not bool(i)

            if sub.to_str().endswith(".sup"):
                self.subtitle_tracks += [SubTrack(sub, name, default, delay=sub_delay)]
            else:
                sub_file = self._prepare_subfile(sub, ref, sub_delay, trim, restyle)
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
                    if self.check_is_empty(y):
                        Log.debug(f"\"{y.name}\" is an empty file! Ignoring...", self.process_subs)
                        y.unlink()
                        continue

                    Log.info(f"{num} \"{y.name}\" found! Skipping processing...", self.process_subs)
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
