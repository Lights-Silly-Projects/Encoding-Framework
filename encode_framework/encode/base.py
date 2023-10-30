import filecmp
from typing import Any, Callable

from vstools import CustomRuntimeError, SPath, finalize_clip, vs

from ..script import ScriptInfo
from ..util import Log

__all__: list[str] = [
    "_BaseEncoder"
]


class _BaseEncoder:
    """Class containing the base components of all the encoder child frameworks."""

    script_info: ScriptInfo
    """Script info containing additional information necessary for encoding."""

    out_clip: vs.VideoNode
    """Clip to output."""

    def __init__(self, script_info: ScriptInfo, out_clip: vs.VideoNode | None = None, **kwargs: Any) -> None:
        self.script_info = script_info

        if out_clip is None:
            out_clip = self.script_info.clip_cut  # type:ignore[assignment]

        assert isinstance(out_clip, vs.VideoNode)

        if not isinstance(out_clip, vs.VideoNode):
            raise CustomRuntimeError(
                "Multiple output nodes detected in filterchain! "
                "Please output just one node!", __file__, len(out_clip)  # type:ignore[arg-type]
            )

        self.out_clip = finalize_clip(out_clip, **kwargs)  # type:ignore[arg-type]

        self.video_file = None  # type:ignore

    def check_is_empty(self, file: SPath) -> bool:
        """Check whether a file is empty (0 bits big)."""
        return file.stat().st_size == 0

    def check_identical(
        self, *files: SPath, shallow: bool = False,
        caller: str | Callable[[Any], Any] | None = None
    ) -> bool:
        """Check whether an arbitrary amount of files are bit-identical. Must pass at least 2 files."""
        if len(files) < 2:
            raise Log.error("You must compare at least two files!", caller)
        elif len(files) == 2:
            return filecmp.cmp(*files, shallow=bool(shallow))

        # TODO: Add support for multiple files
        return False
