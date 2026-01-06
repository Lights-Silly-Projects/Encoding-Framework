from fractions import Fraction
from pathlib import Path
from typing import Any

from vsmuxtools import Chapters, src_file
from vstools import FileNotExistsError, FuncExceptT, SPath, SPathLike, vs

from ..script import ScriptInfo
from ..util import Log, frame_to_timedelta, timedelta_to_frame
from .base import _BaseEncoder

__all__: list[str] = [
    "_Chapters",
    "get_chapter_frames",
]


class _Chapters(_BaseEncoder):
    """Class containing methods pertaining to handling chapters."""

    chapters: Chapters | None = None
    """Chapters obtained from the m2ts playlist or elsewhere."""

    def get_chapters(
        self,
        ref: src_file
        | ScriptInfo
        | list[int | tuple[int, str]]
        | SPathLike
        | None = None,
        shift: int | None = None,
        force: bool = False,
        func: FuncExceptT | None = None,
        **kwargs: Any,
    ) -> Chapters | None:
        """
        Create chapter objects if chapter files exist.

        :param ref:     Reference src_file or ScriptInfo object to get chapters from.
                        Can also be a list of integers representing frame numbers with additional names.
                        Furthermore, it can also be an SPath pointing to a chapter-like file.
        :param shift:   Amount to globally shift chapters by in frames (relative to `src_file`'s fps).
        :param func:    Function to log messages to.
        :param force:   Force chapter creation, even for videos such as NCs or MVs.
        """

        func = func or self.get_chapters

        if isinstance(ref, ScriptInfo):
            ref = ref.src
        elif isinstance(ref, (Path, SPath, str)) and not (ref := SPath(ref)).exists():
            raise Log.error(f'Could not find the file "{ref}"!', func)

        if any(
            str(self.script_info.ep_num).startswith(x)
            for x in ["NC", "OP", "ED", "EP", "MV"]
        ):
            if not force:
                Log.debug(
                    'Not grabbing chapters as this is not an episode! Set "force=True" to force chapters.',
                    func,
                )

                return Chapters((frame_to_timedelta(0), None))
            else:
                Log.warn('Not an episode, but "force=True" was set!', func)

        if isinstance(ref, SPath) and ref.suffix in ("mkv",):
            ref = src_file(ref)

        wclip = ref or self.script_info.src

        if isinstance(wclip, src_file) and (
            suffix := SPath(wclip.file).suffix.lower()
        ) not in (".m2ts", ".vob", ".iso", ".mkv"):
            Log.debug(
                'work clip is not a BD/DVD file, checking for "*.chapters.txt"...', func
            )

            file = SPath(wclip.file)
            files = list(SPath(file.parent).glob(f"*{file.stem}*.chapters.txt"))

            if files:
                Log.debug(
                    "The following files were found:"
                    + "\n    - ".join([f.to_str() for f in files]),
                    func,
                )

                wclip = files[0]
            else:
                Log.warn("No chapter files could be found.", func)

        try:
            if suffix == ".mkv":
                mkv_file = wclip.file if isinstance(wclip, src_file) else wclip

                if isinstance(mkv_file, list):
                    mkv_file = mkv_file[0]

                chapters = Chapters.from_mkv(mkv_file)
            else:
                chapters = Chapters(wclip, **kwargs)
        except PermissionError as e:
            Log.warn(e, self.get_chapters, sleep=0.1)

        if shift is None:
            if isinstance((shift := getattr(self, "script_info", 0)), ScriptInfo):
                shift = -shift.trim[0]

        chapters_found = (
            chapters and hasattr(chapters, "chapters") and chapters.chapters
        )

        if shift and chapters_found:
            for i, _ in enumerate(chapters.chapters):
                chapters = chapters.shift_chapter(i, shift)

        self.chapters = chapters if chapters else None

        return self.chapters


def get_chapter_frames(
    script_info: ScriptInfo | SPathLike,
    ref: vs.VideoNode | None = None,
    log: bool = False,
    _print: bool = True,
    func: FuncExceptT | None = None,
) -> list[tuple[int, int | None]] | None:
    """Get the start and end frame of a chapter obtained from a file."""
    func = func or get_chapter_frames

    if isinstance(script_info, ScriptInfo):
        ch_src = script_info.src.file

        if isinstance(src_file, list):
            ch_src = ch_src[0]
    else:
        ch_src = SPath(script_info)

        if ref is None:
            Log.error("Reference clip is required when passing a SPath.", func)
            exit(1)

    if not ch_src.exists():
        raise FileNotExistsError(f'Could not find file, "{ch_src}"', func)

    Log.info(f'Checking chapters for file, "{ch_src}"', func)

    wclip = script_info.src

    try:
        src_suffix = SPath(
            wclip.file[0] if isinstance(wclip.file, list) else wclip.file
        ).suffix.lower()
    except AttributeError:
        src_suffix = script_info.src_file[0].suffix.lower()

    if isinstance(wclip, src_file) and src_suffix not in (
        ".m2ts",
        ".vob",
        ".iso",
        ".mkv",
    ):
        Log.debug(
            'work clip is not a BD/DVD file, checking for "*.chapters.txt"...', func
        )

        file = SPath(wclip.file)
        files = list(SPath(file.parent).glob(f"*{file.stem}*.chapters.txt"))

        if files:
            Log.debug(
                "The following files were found: "
                + "\n    - ".join([f.to_str() for f in files]),
                func,
            )

            wclip = files[0]
        else:
            Log.warn("No chapter files could be found.", func)

    try:
        if src_suffix == ".mkv":
            chs = Chapters.from_mkv(wclip.file, wclip.src.fps, _print=_print)
        else:
            chs = Chapters(wclip, _print=_print)
    except Exception as e:
        Log.error(e, func)

        return []

    if chs.chapters is None:
        Log.warn("No chapters could be found.", func)
        return

    fps = ref.fps if ref is not None else Fraction(24000, 1001)

    try:
        timedelta_to_frame(chs.chapters[0][0], fps)
    except (AttributeError, TypeError):
        Log.warn("Could not find chapters.", func)
        return

    ch_ranges = []

    for i, (start_time, _) in enumerate(chs.chapters):
        end_time = chs.chapters[i + 1][0] if i + 1 < len(chs.chapters) else None
        start_frame = timedelta_to_frame(start_time, fps)

        if ref and start_frame >= ref.num_frames:
            if ch_ranges:
                ch_ranges[-1] = (ch_ranges[-1][0], None)

            break

        if end_time is None:
            end_frame = None
        else:
            end_frame = timedelta_to_frame(end_time, fps) - 1

        ch_ranges.append((start_frame, end_frame))

        if ref and end_time is not None and end_frame >= ref.num_frames:
            ch_ranges[-1] = (ch_ranges[-1][0], None)
            break

    return ch_ranges
