from typing import Any

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

    def _check_filesize(self, file: SPath, warn: bool = True, caller: Any | None = None) -> bool:
        if (x := file.stat().st_size == 0) and warn:
            Log.warn(f"\"{SPath(file).name}\" is an empty file! Ignoring...", caller)

        return x
