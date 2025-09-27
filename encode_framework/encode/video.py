from typing import Any, cast

from muxtools import get_workdir
from vsmuxtools import VideoFile, VideoTrack, x265  # type:ignore[import]
from vsmuxtools.video.encoders import VideoEncoder  # type:ignore[import]
from vssource import BestSource
from vstools import (
    ColorRange,
    CustomNotImplementedError,
    CustomRuntimeError,
    CustomValueError,
    DitherType,
    FuncExceptT,
    SPath,
    SPathLike,
    depth,
    finalize_clip,
    get_depth,
    get_prop,
    vs,
)

from ..types import Zones
from ..util.logging import Log
from .base import _BaseEncoder

__all__: list[str] = ["_VideoEncoder"]


VideoEncoders = type[VideoEncoder]  # type:ignore[misc,valid-type]


class _VideoEncoder(_BaseEncoder):
    """Class containing methods pertaining to handling video encoding."""

    video_file: VideoFile  # type:ignore[assignment]
    """The encoded video file."""

    video_track: VideoTrack
    """The video track of the encoded video file."""

    premux_path: SPath
    """The path to the premux."""

    lossless_path: SPath
    """Path to a lossless intermediary encode."""

    encoder: VideoEncoders = x265
    """The encoder used for the encode."""

    video_container_args: list[str] = []
    """Additional arguments that must be passed to the container."""

    def encode_video(
        self,
        input_clip: vs.VideoNode | SPathLike | None = None,
        output_clip: vs.VideoNode | SPathLike | None = None,
        zones: Zones = [],
        out_bit_depth: int = 10,
        dither_type: DitherType = DitherType.AUTO,
        qpfile: SPathLike | bool = True,
        lang: str = "ja",
        settings: SPathLike = "_settings/{encoder}_settings",
        lossless: bool = False,
        encoder: VideoEncoders = x265,
        track_args: dict[str, Any] = {},
        delete_partial_encodes: bool = False,
        **encoder_kwargs: Any,
    ) -> VideoFile:
        """
        Encode the video node.

        :param input_clip:              Source clip. Used for certain metrics.
        :param output_clip:             Filtered clip to encode.
        :param zones:                   Zones for the encoder. If empty list or None, take from script_info.
        :param out_bit_depth:           Bitdepth to output to.
        :param dither_type:             Dither type when dithering down to `out_bit_depth`.
        :param qpfile:                  qpfile for the encoder. A path must be passed.
                                        If False, do not use a qpfile at all.
        :param lang:                    Language of the track.
        :param settings:                Settings file. By default, tries to find a settings file using the encoder's name.
        :param lossless:                Whether to run a lossless encode prior to the regular encode.
        :param encoder:                 The lossy encoder to use. Default: x265.
        :param track_args:              Additional arguments to pass to the track.
                                        For example, `{display-unit:3, display-width:267, display-height:200}`
                                        to force a true 9:10 aspect ratio.
        :param delete_partial_encodes:  Delete partial encodes after encoding.
        :param **encoder_kwargs:        Additional arguments to pass to the encoder.

        :return:                        VideoFile object.
        """

        in_clip = self._handle_path_clip(input_clip) or self.script_info.clip_cut

        self._remove_empty_parts()
        self._get_crop_args()

        if delete_partial_encodes:
            self._delete_partial_encodes()

        self._fix_finished_encode_extension()

        if track_args:
            self._video_track_args = []

            for k, v in track_args.items():
                self._video_track_args.extend(["--" + k.replace("_", "-"), f"0:{v}"])

        if finished_encode := list(SPath(get_workdir()).glob("encoded.*")):
            Log.debug(
                f'Found finished encode at "{finished_encode[0]}"', self.encode_video
            )

            self.video_file = VideoFile(finished_encode[0])

            self.video_track = self.video_file.to_track(
                default=True,
                timecode_file=self.script_info.tc_path,
                lang=lang.strip(),
                crop=self.crop,
            )

            return self.video_file

        if isinstance(in_clip, tuple):
            in_clip = in_clip[0]

        out_clip = self._handle_path_clip(output_clip) or self.out_clip or in_clip

        self.encoder = encoder

        settings_file = SPath(
            str(settings).format(
                encoder=self.encoder.__name__
                if hasattr(self.encoder, "__name__")
                else str(self.encoder)
            )
        )

        if not isinstance(out_clip, vs.VideoNode):
            raise Log.error(
                "Too many output nodes in filterchain function! Please only output one node!",
                self.encode_video,
                CustomRuntimeError,  # type:ignore[arg-type]
                reason=f"Output nodes: {len(out_clip)}",  # type:ignore[arg-type]
            )

        if lossless:
            lossless_clip = self._encode_lossless(out_clip)  # type:ignore[arg-type]
            in_clip, out_clip = lossless_clip, lossless_clip

        if qpfile is True and self.script_info.sc_path.exists():
            Log.debug(
                f'QP file found at "{self.script_info.sc_path}"', self.encode_video
            )

            qpfile = self.script_info.sc_path

        if not settings_file.exists():
            Log.warn(
                f'No settings file found at "{settings_file}"! Falling back to defaults...',
                self.encode_video,
            )
        else:
            self._set_container_args(encoder, settings_file)

        if self.video_container_args:
            Log.info(
                "Applying the following container settings:\n"
                f'"{" ".join(self.video_container_args)}"',
                self.encode_video,
            )

        zones += self.script_info.zones
        zones = self._normalize_zones(out_clip, zones)

        Log.info(f"Zones: {zones}", self.encode_video)

        # Args for finalizing the clip.
        if get_depth(out_clip) != out_bit_depth:
            out_clip = self._finalize_clip(
                out_clip, out_bit_depth, dither_type, self.encode_video
            )

        if isinstance(self.encoder, type):
            self.encoder = self.encoder(
                settings_file, zones, qpfile, in_clip, **encoder_kwargs
            )

        video_file = self.encoder.encode(out_clip)  # type:ignore[arg-type, call-arg]

        self.video_file = cast(VideoFile, video_file)

        self.video_track = self.video_file.to_track(
            default=True,
            timecode_file=self.script_info.tc_path,
            lang=lang.strip(),
            crop=self.crop,
        )

        return self.video_file

    def _finalize_clip(
        self,
        clip: vs.VideoNode,
        out_bit_depth: int = 10,
        dither_type: DitherType = DitherType.AUTO,
        func: Any | None = None,
    ) -> vs.VideoNode:
        clip = depth(clip, out_bit_depth, dither_type=dither_type)

        self.out_clip = finalize_clip(
            clip, out_bit_depth, ColorRange.from_video(clip).is_limited, func=func
        )

        return self.out_clip

    def _set_container_args(
        self, encoder: VideoEncoders, settings_file: SPath
    ) -> list[str]:
        """Set additional container arguments if relevant."""
        psets = str(encoder(settings_file).settings).split(" ")  # type:ignore[arg-type, attr-defined, call-arg]

        if all(x in psets for x in ("--overscan", "--display-window")):
            overscan_idx = psets.index("--overscan")
            display_window_idx = psets.index("--display-window")

            if psets[overscan_idx + 1] == "crop":
                self.video_container_args += [
                    "--cropping",
                    f"0:{psets[display_window_idx + 1]}",
                ]

        return self.video_container_args

    def _delete_partial_encodes(self) -> None:
        """Delete partial encodes from the workdir."""

        for part in SPath(get_workdir()).glob("encode*"):
            part.unlink()

    def _fix_finished_encode_extension(self) -> None:
        """Sometimes I extract the old encode and forget to rename it properly."""

        wdir = SPath(get_workdir())

        if spath := wdir.fglob("*.h265"):
            target = wdir / "encoded.265"

            Log.info(
                f"Renaming finished encode '{spath.name}' to '{target.name}'...",
                self._fix_finished_encode_extension,
            )

            target.unlink(missing_ok=True)
            spath.rename(target)

    def _remove_empty_parts(self) -> None:
        """Remove empty parts from the workdir."""

        for part in SPath(get_workdir()).glob("encoded_part_*"):
            if part.stat().st_size == 0:
                part.unlink()

    def _handle_path_clip(
        self, potential_path: vs.VideoNode | SPathLike | None
    ) -> vs.VideoNode | SPath | None:
        if isinstance(potential_path, vs.VideoNode):
            return potential_path

        if potential_path is None:
            return potential_path

        try:
            if (spath := SPath(potential_path)).exists():
                return BestSource.source(spath, cachepath=get_workdir() / "bscache")
        except CustomNotImplementedError:
            pass
        except Exception as e:
            Log.warn(e, self.encode_video)

        return potential_path

    def _get_crop_args(
        self, crop: int | tuple[int, int] | tuple[int, int, int, int] | None = None
    ) -> int | tuple[int, int] | tuple[int, int, int, int] | None:
        if crop is not None:
            return crop

        _l = get_prop(self.out_clip, "_SARLeft", int, None, 0, self.encode_video)
        _r = get_prop(self.out_clip, "_SARRight", int, None, 0, self.encode_video)
        _t = get_prop(self.out_clip, "_SARTop", int, None, 0, self.encode_video)
        _b = get_prop(self.out_clip, "_SARBottom", int, None, 0, self.encode_video)

        if any([_l, _r, _t, _b]):
            crop = (_l, _t, _r, _b)

        self.crop = crop

        return crop

    def _encode_lossless(
        self, clip_to_process: vs.VideoNode, caller: str | None = None
    ) -> vs.VideoNode:
        from vsmuxtools import FFV1, get_workdir
        from vssource import BestSource

        self.lossless_path = SPath(
            get_workdir()
            / f"{self.script_info.show_title}_{self.script_info.ep_num}_lossless.mkv"
        )

        if self.lossless_path.exists():
            Log.info(
                f"Lossless intermediary located at {self.lossless_path}! "
                "If this encode is outdated, please delete the lossless render!",
                caller or self._encode_lossless,
            )
        else:
            Log.info(
                "Creating a lossless intermediary...", caller or self._encode_lossless
            )

            FFV1().encode(clip_to_process, self.lossless_path)

        return BestSource.source(self.lossless_path)

    def _normalize_zones(self, clip: vs.VideoNode, zones: Zones) -> Zones:
        """Normalizes zones so they don't destroy the encoder with a \"Broken Pipe\" error."""

        if not isinstance(zones, list):
            zones = [zones]

        norm_zones: Zones = []

        for zone in zones:
            if len(zone) != 3:
                raise Log.error(
                    f'The zone "{zone}" must contain 3 values! '
                    "(start frame, end frame, bitrate modifier)",
                    self.encode_video,
                    CustomValueError,  # type:ignore
                )

            if any(map(lambda x: x is None, zone)):
                start, end, bitrate = zone

                if start is None:
                    start = 0
                elif start < 0:
                    start = clip.num_frames - abs(start)

                if end is None:
                    end = clip.num_frames
                elif end < 0:
                    end = clip.num_frames - abs(end)

                if bitrate is None:
                    raise Log.error(
                        f'The value of "bitrate modifier" can\'t be None ({zone})!',
                        self.encode_video,
                        CustomValueError,
                    )
                elif bitrate <= 0:
                    continue

                zone = (start, end, bitrate)

            norm_zones += [zone]

        return norm_zones

    def _warn_if_path_too_long(self, func_except: FuncExceptT | None = None) -> bool:
        """Logs a warning if the premux path is too long, but only once."""

        func = func_except or self._warn_if_path_too_long

        self._path_too_long = getattr(self, "_path_too_long", False)

        if self._path_too_long:
            return self._path_too_long

        if len(str(self.premux_path)) > 255:
            Log.warn("Output path is too long! Please move this file...", func)  # type:ignore

            self._path_too_long = True

        return self._path_too_long
