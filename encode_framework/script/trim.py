"""
Misc functions that don't have a place in any other module.
"""

import linecache
import os
from typing import cast

from jetpytools import SPath, SPathLike
from vsrgtools import gauss_blur
from vssource import BestSource
from vstools import core, get_prop, scale_value, vs, Keyframes

from ..util.logging import Log

__all__: list[str] = [
    "get_pre_trim",
    "get_post_trim",
]


def get_pre_trim(
    clip: vs.VideoNode | SPathLike, kf_file: SPathLike, lock_file: SPathLike
) -> int | None:
    """
    Simple naive function that checks an existing keyframe file to trim the start of the clip.

    This has a check in place to make sure the start and end frame are fully black.

    You should probably only run this if you're sure your videos consistently start on black frames.

    :return: framenum or None.
    """
    clip = _get_clip(clip)
    kf_file = SPath(kf_file)

    if not kf_file.exists():
        return None

    clip = gauss_blur(clip, 1.5).std.PlaneStats()

    if get_prop(clip[0], "PlaneStatsAverage", float) > scale_value(16.2, 8, 32):
        return None

    first_sc = int(linecache.getline(kf_file.to_str(), 5).replace(" I -1", ""))

    if (
        first_sc > 24
        and get_prop(clip[23], "PlaneStatsAverage", float) < scale_value(16.2, 8, 32)
        and get_prop(clip[24], "PlaneStatsAverage", float) > scale_value(16.2, 8, 32)
    ):
        Log.warn(
            "Auto-guessed 24 frame trim at the start. Please verify this!",
            "get_pre_trim",
        )

        first_sc = 24
    elif get_prop(clip[first_sc - 1], "PlaneStatsAverage", float) < scale_value(
        16.2, 8, 32
    ):
        return None

    Log.debug(
        f"Black frames found at the start of the video. Trimming clip at the end (frame {first_sc}).",
        "get_pre_trim",
    )

    SPath(lock_file).touch(exist_ok=True)

    return first_sc


def get_post_trim(
    clip: vs.VideoNode | SPathLike, kf_file: SPathLike, lock_file: SPathLike
) -> int | None:
    """
    Simple naive function that checks an existing keyframe file to trim the end of the clip.

    This has a check in place to make sure the start and end frame are fully black.

    You should probably only run this if you're sure your videos consistently end on black frames.

    :return: framenum or None.
    """
    clip = _get_clip(clip)
    kf_file = SPath(kf_file)

    if not kf_file.exists():
        Log.debug("Could not find keyframe file", "get_post_trim")
        return None

    clip = gauss_blur(clip, 1.5).std.PlaneStats()

    if get_prop(clip[-1], "PlaneStatsAverage", float) > scale_value(32, 8, 32):
        Log.debug(
            "Last frame has non-exact black values! "
            f"{get_prop(clip[-1], 'PlaneStatsAverage', float)} > {scale_value(21, 8, 32)}",
            "get_post_trim",
        )

        return None

    kf = Keyframes.from_file(kf_file)

    if (last_sc := int(kf[-1])) == (clip.num_frames - 1):
        last_sc = kf[-2]

    if get_prop(clip[last_sc], "PlaneStatsAverage", float) > scale_value(32, 8, 32):
        Log.debug(
            f"Frame {last_sc}: {get_prop(clip[last_sc], 'PlaneStatsAverage', float)} > {scale_value(21, 8, 32)}",
            "get_post_trim",
        )

        return None

    Log.debug(
        "Black frames found at the end of the video. "
        f"Trimming clip at the end (frame {last_sc}, relative trim: {last_sc - clip.num_frames}).",
        "get_post_trim",
    )

    SPath(lock_file).touch(exist_ok=True)

    return last_sc


def _get_clip(clip: vs.VideoNode | SPathLike) -> vs.VideoNode:
    if not isinstance(clip, vs.VideoNode):
        if isinstance(clip, list):
            clip = clip[0]

        clip = SPath(clip)  # type:ignore[arg-type]

        if clip.suffix == ".dgi":
            clip = core.dgdecodenv.DGSource(clip)
        else:
            clip = BestSource.source(SPath(clip))

    return cast(vs.VideoNode, clip)
