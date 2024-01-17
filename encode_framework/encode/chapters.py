from typing import Any

from vsmuxtools import Chapters, src_file, timedelta_to_frame  # type:ignore[import]
from vstools import SPath, SPathLike, CustomNotImplementedError, FileNotExistsError, vs
from fractions import Fraction

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
        shift: int = 0, force: bool = False, **kwargs: Any
    ) -> Chapters | None:
        """
        Create chapter objects if chapter files exist.

        :param ref:     Reference src_file or ScriptInfo object to get chapters from.
                        Can also be a list of integers representing frame numbers with additional names.
                        Furthermore, it can also be an SPath pointing to a chapter-like file.
        :param shift:   Amount to globally shift chapters by in frames (relative to `src_file`'s fps).
        :param force:   Force chapter creation, even for videos such as NCs or MVs.
        """
        from vsmuxtools import frame_to_timedelta

        if isinstance(ref, ScriptInfo):
            ref = ref.src
        elif isinstance(ref, SPathLike):
            if not (ref := SPath(ref)).exists():
                raise Log.error(f"Could not find the file \"{ref}\"!", self.get_chapters)

            raise Log.error("Paths are not supported yet!", self.get_chapters, CustomNotImplementedError)

        if any(str(self.script_info.ep_num).startswith(x) for x in ["NC", "OP", "ED", "EP", "MV"]):
            if not force:
                Log.debug(
                    "Not grabbing chapters as this is not an episode! Set \"force=True\" to force chapters.",
                    self.get_chapters
                )

                return Chapters((frame_to_timedelta(0), None))
            else:
                Log.warn("Not an episode, but \"force=True\" was set!", self.get_chapters)

        chapters = Chapters(ref or self.script_info.src, **kwargs)

        if shift:
            for i, _ in enumerate(self.chapters.chapters):
                self.chapters = self.chapters.shift_chapter(i, shift)

            Log.info(f"After shift:", self.get_chapters)
            self.chapters.print()

        if chapters.chapters:
            self.chapters = chapters

        return self.chapters


def get_chapter_frames(
    script_info: ScriptInfo, index: int = 0,
    ref: vs.VideoNode | None = None, log: bool = False
) -> tuple[int, int]:
    """Get the start and end frame of a chapter obtained from a file."""
    if not (ch_src := SPath(script_info.file)).exists():
        raise FileNotExistsError(f"Could not find file, \"{ch_src}\"", get_chapter_frames)

    fps = ref.fps if ref is not None else Fraction(24000, 1001)

    chs = _Chapters(script_info).get_chapters(force=True)

    try:
        ch_s = timedelta_to_frame(chs.chapters[index][0], fps)
    except AttributeError:
        Log.warn("Could not find chapters.", get_chapter_frames)
        return

    try:
        ch_e = chs.chapters[index + 1]
        ch_e = timedelta_to_frame(ch_e[0], fps) - 1
    except IndexError:
        if ref is not None:
            ch_e = ref.num_frames
        else:
            ch_e = None

    ch_range = (ch_s, ch_e)

    if log:
        Log.info(f"Chapter range selected:\n{ch_range}", get_chapter_frames)

    return ch_range
