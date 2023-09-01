"""
    Misc functions that don't have a place in any other module.
"""
import linecache
import os
from typing import cast

from vssource import source
from vstools import SPath, SPathLike, core, get_prop, scale_value, vs

from ..util.logging import Log

__all__: list[str] = [
    "get_pre_trim",
    "get_post_trim",
]


def get_pre_trim(clip: vs.VideoNode | SPathLike, kf_file: SPathLike, lock_file: SPathLike) -> int | None:
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

    clip = clip.std.PlaneStats()

    if get_prop(clip[0], "PlaneStatsAverage", float) > scale_value(16.2, 8, 32):
        return None

    first_sc = int(linecache.getline(kf_file.to_str(), 5).replace(' I -1', ''))

    if first_sc > 24 \
            and get_prop(clip[23], "PlaneStatsAverage", float) < scale_value(16.2, 8, 32) \
            and get_prop(clip[24], "PlaneStatsAverage", float) > scale_value(16.2, 8, 32):
        Log.warn("Auto-guessed 24 frame trim at the start. Please verify this!", "get_pre_trim")

        first_sc = 24
    elif get_prop(clip[first_sc - 1], "PlaneStatsAverage", float) > scale_value(16.2, 8, 32):
        return None

    Log.debug(
        f"Black frames found at the start of the video. Trimming clip at the end (frame {first_sc}).",
        "get_pre_trim"
    )

    SPath(lock_file).touch(exist_ok=True)

    return first_sc


def get_post_trim(clip: vs.VideoNode | SPathLike, kf_file: SPathLike, lock_file: SPathLike) -> int | None:
    """
    Simple naive function that checks an existing keyframe file to trim the end of the clip.

    This has a check in place to make sure the start and end frame are fully black.

    You should probably only run this if you're sure your videos consistently end on black frames.

    :return: framenum or None.
    """
    clip = _get_clip(clip)
    kf_file = SPath(kf_file)

    if not kf_file.exists():
        return None

    clip = clip.std.PlaneStats()

    if get_prop(clip[-1], "PlaneStatsAverage", float) > scale_value(16.2, 8, 32):
        return None

    with open(kf_file, "rb") as f:
        try:
            f.seek(-3, os.SEEK_END)

            while f.read(1) != b'\n':
                f.seek(-3, os.SEEK_CUR)
        except OSError:
            f.seek(0)

        last_line = f.readline().decode()

    last_sc = int(last_line.replace(' I -1', ''))

    if get_prop(clip[last_sc], "PlaneStatsAverage", float) > scale_value(16.2, 8, 32):
        return None

    Log.debug(
        "Black frames found at the end of the video. "
        f"Trimming clip at the end (frame {last_sc}, relative trim: {last_sc - clip.num_frames}).",
        "get_post_trim"
    )

    SPath(lock_file).touch(exist_ok=True)

    return last_sc


def _get_clip(clip: vs.VideoNode | SPathLike) -> vs.VideoNode:
    if not isinstance(clip, vs.VideoNode):
        clip = SPath(clip)  # type:ignore[arg-type]

        if clip.suffix == ".dgi":
            clip = core.dgdecodenv.DGSource(clip)
        else:
            clip = source(SPath(clip))

    return cast(vs.VideoNode, clip)
