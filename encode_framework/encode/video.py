from typing import Any, cast

from vsmuxtools import VideoFile, x265  # type:ignore[import]
from vsmuxtools.video.encoders import SupportsQP  # type:ignore[import]
from vstools import (ColorRange, CustomRuntimeError, CustomValueError, DitherType, FileNotExistsError, SPath, SPathLike,
                     depth, finalize_clip, get_depth, vs)

from ..types import Zones
from ..util.logging import Log
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

    encoder: SupportsQP = x265
    """The encoder used for the encode."""

    video_container_args: list[str] = []
    """Additional arguments that must be passed to the container."""

    def encode_video(
        self,
        input_clip: vs.VideoNode | None = None,
        output_clip: vs.VideoNode | None = None,
        zones: Zones = [],
        out_bit_depth: int = 10,
        dither_type: DitherType = DitherType.AUTO,
        qpfile: SPathLike | bool = True,
        settings: SPathLike = "_settings/{encoder}_settings",
        lossless: bool = False,
        encoder: SupportsQP = x265,
        **encoder_kwargs: Any
    ) -> VideoFile:
        """
        Encode the video node.

        :param input_clip:          Source clip. Used for certain metrics.
        :param output_clip:         Filtered clip to encode.
        :param zones:               Zones for the encoder.
        :param out_bit_depth:       Bitdepth to output to.
        :param dither_type:         Dither type when dithering down to `out_bit_depth`.
        :param qpfile:              qpfile for the encoder. A path must be passed.
                                    If False, do not use a qpfile at all.
        :param settings:            Settings file. By default, tries to find a settings file using the encoder's name.
        :param lossless:            Whether to run a lossless encode prior to the regular encode.
        :param encoder:             The lossy encoder to use. Default: x265.

        :return:                    VideoFile object.
        """
        in_clip = input_clip or self.script_info.clip_cut
        out_clip = output_clip or self.out_clip or in_clip

        self.encoder = encoder
        settings_file = SPath(str(settings).format(encoder=self.encoder.__name__))

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
        else:
            self._set_container_args(encoder, settings_file)

        if self.video_container_args:
            Log.info(
                "Applying the following container settings:\n"
                f"\"{' '.join(self.video_container_args)}\"",
                self.encode_video
            )

        zones = self._normalize_zones(out_clip, zones)

        # Args for finalizing the clip.
        if get_depth(out_clip) != out_bit_depth:
            out_clip = self._finalize_clip(out_clip, out_bit_depth, dither_type, self.encode_video)

        video_file = self.encoder(settings_file, zones, qpfile, in_clip, **encoder_kwargs) \
            .encode(out_clip)  # type:ignore[arg-type]

        self.video_file = cast(VideoFile, video_file)

        return self.video_file

    def _finalize_clip(
        self, clip: vs.VideoNode,
        out_bit_depth: int = 10,
        dither_type: DitherType = DitherType.AUTO,
        func: Any | None = None
    ) -> vs.VideoNode:
        clip = depth(clip, out_bit_depth, dither_type=dither_type)

        self.out_clip = finalize_clip(
            clip, out_bit_depth,ColorRange.from_video(clip).is_limited, func=func
        )

        return self.out_clip

    def _set_container_args(self, encoder: SupportsQP, settings_file: SPath) -> list[str]:
        """Set additional container arguments if relevant."""
        psets = str(encoder(settings_file).settings).split(" ")

        if all(x in psets for x in ("--overscan", "--display-window")):
            overscan_idx = psets.index("--overscan")
            display_window_idx = psets.index("--display-window")

            if psets[overscan_idx + 1] == "crop":
                self.video_container_args += ["--cropping", f"0:{psets[display_window_idx + 1]}"]

        return self.video_container_args


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

    def _normalize_zones(self, clip: vs.VideoNode, zones: Zones) -> Zones:
        """Normalizes zones so they don't destroy the encoder with a \"Broken Pipe\" error."""
        if not isinstance(zones, list):
            zones = [zones]

        norm_zones: list[Zones] = []

        for zone in zones:
            if not len(zone) == 3:
                raise Log.error(
                    f"The zone \"{zone}\" must contain 3 values! "
                    "(start frame, end frame, bitrate modifier)", self.encode_video, CustomValueError
                )

            if any(map(lambda x: x is None, zone)):
                start, end, bitrate = zone

                if start is None:
                    start = 0

                if end is None:
                    end = clip.num_frames

                if bitrate is None:
                    raise Log.error(
                        f"The value of \"bitrate modifier\" can't be None ({zone})!",
                        self.encode_video, CustomValueError
                    )
                elif bitrate == 0:
                    break

                zone = (start, end, bitrate)

            norm_zones += [zone]

        return norm_zones
