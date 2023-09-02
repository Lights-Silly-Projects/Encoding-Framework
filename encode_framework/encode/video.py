from typing import cast

from vsmuxtools import VideoFile, x265  # type:ignore[import]
from vsmuxtools.video.encoders import SupportsQP  # type:ignore[import]
from vstools import CustomRuntimeError, FileNotExistsError, SPath, SPathLike, finalize_clip, vs

from ..util.logging import Log
from ..types import Zones
from .base import _BaseEncoder

__all__: list[str] = [
    "_VideoEncoder"
]


class _VideoEncoder(_BaseEncoder):
    """Class containing methods pertaining to handling video encoding."""

    video_file: VideoFile
    """The encoded video file."""

    premux_path: SPath
    """The path to the premux."""

    lossless_path: SPath
    """Path to a lossless intermediary encode."""

    def encode_video(
        self,
        input_clip: vs.VideoNode | None = None,
        output_clip: vs.VideoNode | None = None,
        zones: Zones = [],
        qpfile: SPathLike | bool = True,
        settings: SPathLike = "_settings/{encoder}_settings",
        lossless: bool = False,
        encoder: SupportsQP = x265,
    ) -> VideoFile:
        """
        Encode the video node.

        :param zones:               Zones for the encoder.
        :param qpfile:              qpfile for the encoder. A path must be passed.
                                    If False, do not use a qpfile at all.
        :param settings:            Settings file. By default, tries to find a settings file using the encoder's name.
        :param lossless:            Whether to run a lossless encode prior to the regular encode.
        :param encoder:             The lossy encoder to use. Default: x265.
        :param lossless_encoder:    The lossless encoder to run.

        :return:                    VideoFile object.
        """
        in_clip = input_clip or self.script_info.clip_cut
        out_clip = output_clip or self.out_clip or in_clip

        assert isinstance(encoder, SupportsQP)

        settings_file = SPath(str(settings).format(encoder=encoder.__name__))

        if not isinstance(out_clip, vs.VideoNode):
            raise Log.error(
                "Too many output nodes in filterchain function! Please only output one node!",
                self.encode_video, CustomRuntimeError,  # type:ignore[arg-type]
                reason=f"Output nodes: {len(out_clip)}"  # type:ignore[arg-type]
            )

        if lossless:
            lossless_clip = self._encode_lossless(out_clip)  # type:ignore[arg-type]
            in_clip, out_clip = lossless_clip, lossless_clip

        if qpfile is True and self.script_info.sc_path.exists():
            Log.debug(f"QP file found at \"{self.script_info.sc_path}\"", self.encode_video)

            qpfile = self.script_info.sc_path

        if not settings_file.exists():
            Log.error(
                f"No settings file found at \"{settings_file}\"! Falling back to defaults...",
                self.encode_video, FileNotExistsError  # type:ignore[arg-type]
            )

        video_file = encoder(settings_file, zones, qpfile, in_clip) \
            .encode(finalize_clip(out_clip))  # type:ignore[arg-type]

        self.video_file = cast(VideoFile, video_file)

        return self.video_file

    def _encode_lossless(self, clip_to_process: vs.VideoNode, caller: str | None = None) -> vs.VideoNode:
        from vsmuxtools import FFV1, LosslessPreset, get_workdir
        from vssource import BestSource

        self.lossless_path = get_workdir() / f"{self.script_info.show_title}_{self.script_info.ep_num}_lossless.mkv"

        if self.lossless_path.exists():
            Log.info(
                f"Lossless intermediary located at {self.lossless_path}! "
                "If this encode is outdated, please delete the lossless render!",
                caller or self._encode_lossless
            )
        else:
            Log.info("Creating a lossless intermediary...", caller or self._encode_lossless)

            FFV1(LosslessPreset.COMPRESSION).encode(clip_to_process, self.lossless_path)

        return BestSource.source(self.lossless_path)
