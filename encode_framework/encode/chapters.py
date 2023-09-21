from typing import Any

from vsmuxtools import Chapters, src_file  # type:ignore[import]

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
        self, ref: src_file | ScriptInfo | None = None,
        force: bool = False, **kwargs: Any
    ) -> Chapters | None:
        """Create chapter objects if chapter files exist."""
        from vsmuxtools import frame_to_timedelta

        if isinstance(ref, ScriptInfo):
            ref = ref.src

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

        return self.chapters
