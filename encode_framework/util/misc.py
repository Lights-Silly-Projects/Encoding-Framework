import re
from fractions import Fraction

from jetpytools import SPathLike
from ..util import frame_to_timedelta

__all__: list[str] = ["markdownify", "get_opus_bitrate_from_channels"]


def frame_to_ms(
    f: int, fps: Fraction = Fraction(24000, 1001), compensate: bool = False
) -> float:
    """
    Converts a frame number to it's ms value.

    :param f:           The frame number
    :param fps:         A Fraction containing fps_num and fps_den. Also accepts a timecode (v2) file.
    :param compensate:  Whether to place the timestamp in the middle of said frame
                        Useful for subtitles, not so much for audio where you'd want to be accurate

    :return:            The resulting ms
    """

    td = frame_to_timedelta(f, fps, compensate)
    return td.total_seconds() * 1000


def markdownify(string: str) -> str:
    """Markdownify a given string."""
    string = re.sub(r"\[bold\]([a-zA-Z0-9\.!?:\-]+)?\[\/\]", r"**\1**", str(string))
    string = re.sub(r"\[italics\]([a-zA-Z0-9\.!?:\-]+)?\[\/\]", r"_\1_", str(string))

    return string


def get_opus_bitrate_from_channels(channel_count: float = 2.0) -> str:
    """Get the channel count from the name for Opus."""

    channel_count = float(channel_count)
    base_str = f"Opus {channel_count} @ "

    if channel_count <= 2.0:
        return base_str + "192kb/s"

    if channel_count > 6.0:
        return base_str + "420kb/s"

    return base_str + "320kb/s"
