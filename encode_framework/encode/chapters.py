from typing import Any

from vsmuxtools import Chapters, src_file  # type:ignore[import]
from vstools import SPath, SPathLike, CustomNotImplementedError

from ..script import ScriptInfo
from ..util.logging import Log
from .base import _BaseEncoder

__all__: list[str] = [
    "_Chapters"
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

        if chapters.chapters:
            self.chapters = chapters

        if shift:
            for i, _ in enumerate(self.chapters.chapters):
                self.chapters = self.chapters.shift_chapter(i, shift)

            Log.info(f"After shift:", self.get_chapters)
            self.chapters.print()

        return self.chapters
