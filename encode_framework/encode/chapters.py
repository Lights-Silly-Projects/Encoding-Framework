from fractions import Fraction
from typing import Any, cast

# type:ignore[import]
from vsmuxtools import Chapters, src_file, timedelta_to_frame
from vstools import FileNotExistsError, FuncExceptT, SPath, SPathLike, vs

from ..script import ScriptInfo
from ..util.logging import Log
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
        self, ref: src_file | ScriptInfo | list[int | tuple[int, str]] | SPathLike | None = None,
        shift: int | None = None, force: bool = False, func: FuncExceptT | None = None, **kwargs: Any
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
        from vsmuxtools import frame_to_timedelta

        func = func or self.get_chapters

        if isinstance(ref, ScriptInfo):
            ref = ref.src
        elif isinstance(ref, SPathLike) and not (ref := SPath(ref)).exists():
            raise Log.error(f"Could not find the file \"{ref}\"!", func)

        if any(str(self.script_info.ep_num).startswith(x) for x in ["NC", "OP", "ED", "EP", "MV"]):
            if not force:
                Log.debug(
                    "Not grabbing chapters as this is not an episode! Set \"force=True\" to force chapters.",
                    func
                )

                return Chapters((frame_to_timedelta(0), None))
            else:
                Log.warn("Not an episode, but \"force=True\" was set!", func)

        if isinstance(ref, SPath) and ref.suffix in ('mkv',):
            ref = src_file(ref)

        wclip = ref or self.script_info.src

        if isinstance(wclip, src_file) and SPath(wclip.file).suffix not in (".m2ts", ".vob", ".iso"):
            Log.debug("work clip is not a BD/DVD file, checking for \"*.chapters.txt\"...", func)

            file = SPath(wclip.file)
            files = list(SPath(file.parent).glob(
                f"*{file.stem}*.chapters.txt"))

            if files:
                Log.debug("The following files were found:" +
                          '\n    - '.join([f.to_str() for f in files]), func)

                wclip = files[0]
            else:
                Log.warn("No chapter files could be found.", func)

        chapters = Chapters(wclip, **kwargs)

        if shift is None:
            if isinstance((shift := getattr(self, "script_info", 0)), ScriptInfo):
                shift = shift.trim[0]

        chapters_found = chapters and hasattr(chapters, 'chapters')

        if shift and chapters_found:
            for i, _ in enumerate(chapters.chapters):
                chapters = chapters.shift_chapter(i, shift)

        self.chapters = chapters

        return self.chapters


def get_chapter_frames(
    script_info: ScriptInfo,
    ref: vs.VideoNode | None = None, log: bool = False,
    func: FuncExceptT | None = None,
) -> tuple[int, int] | None:
    """Get the start and end frame of a chapter obtained from a file."""
    func = func or get_chapter_frames

    if not (ch_src := SPath(script_info.src.file)).exists():
        raise FileNotExistsError(f"Could not find file, \"{ch_src}\"", func)

    Log.info(f"Checking chapters for file, \"{ch_src}\"", func)

    if isinstance(ref, ScriptInfo):
        ref = ref.src
    elif isinstance(ref, SPathLike):
        if not (ref := SPath(ref)).exists():
            raise Log.error(f"Could not find the file \"{ref}\"!", func)
    elif isinstance(ref, vs.VideoNode):
        ref = cast(vs.VideoNode, ref)

    wclip = ref or script_info.src

    if isinstance(wclip, src_file) and SPath(wclip.file).suffix not in (".m2ts", ".vob", ".iso"):
        Log.debug("work clip is not a BD/DVD file, checking for \"*.chapters.txt\"...", func)

        file = SPath(wclip.file)
        files = list(SPath(file.parent).glob(f"*{file.stem}*.chapters.txt"))

        if files:
            Log.debug("The following files were found: " + '\n    - '.join([f.to_str() for f in files]), func)

            wclip = files[0]
        else:
            Log.warn("No chapter files could be found.", func)

    chs = Chapters(wclip)

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
        ch_ranges += [(timedelta_to_frame(start_time), end_time if end_time is None else timedelta_to_frame(end_time))]

    return ch_ranges
