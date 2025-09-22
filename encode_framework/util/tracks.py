import re

from vsmuxtools import AudioFormat, ParsedFile, TrackInfo, TrackType
from vstools import CustomIndexError, SPath, SPathLike

from .logging import Log

__all__: list[str] = [
    "build_audio_track_name",
    "closest_common_bitrate",
    "COMMON_LOSSY_BITRATES",
]

COMMON_LOSSY_BITRATES: list[int] = [i for i in range(16, 1025, 16)]


def build_audio_track_name(audio_file: SPathLike, track_idx: int = 0) -> str:
    """
    Build the name of the audio track.

    This function tries to match the naming conventions listed here:
        - https://thewiki.moe/advanced/muxing/#correct-tagging

    Args:
        audio_file: The audio file to build the name for.
        track_idx: The index of the track to build the name for.

    Returns:
        The name of the audio track.
    """

    if not (sfile := SPath(audio_file)).exists():
        Log.error(
            f'The encoded audio file, "{sfile.as_posix()}", could not be found!',
            build_audio_track_name,
        )

        return ""

    afile = ParsedFile.from_file(sfile)

    if len(afile.tracks) < track_idx:
        raise CustomIndexError(
            f"Track index {track_idx} is out of bounds for file {sfile.as_posix()}",
            build_audio_track_name,
        )

    atrack = afile.find_tracks(
        type=TrackType.AUDIO, error_if_empty=True, caller=build_audio_track_name
    )[track_idx]

    if not (aformat := atrack.get_audio_format()):
        return ""

    base_str = _get_base_encoder_str(atrack, aformat)

    if aformat.is_lossy:
        base_str = _get_lossy_encoder_str(base_str, atrack)

    return _get_descriptive_str(base_str, atrack)


def _get_base_encoder_str(atrack: TrackInfo, aformat: AudioFormat) -> str:
    """Get the base encoder string for a track."""

    name_strs = []

    if aformat.value:
        name_strs.append(aformat.value)

    if (ch := atrack.raw_ffprobe.channels) and (
        cl := atrack.raw_ffprobe.channel_layout
    ):
        try:
            cl_clean = "".join(c for c in cl if c.isdigit() or c == ".")
            ch_float = float(cl_clean)
            ch = ch_float
        except (ValueError, TypeError):
            pass

        name_strs.append(f"{ch:.1f}")

    return " ".join(name_strs)


def _get_lossy_encoder_str(track_str: str, atrack: TrackInfo) -> str:
    """Get the encoder string for a lossy audio track."""

    if enc_params := atrack.other_tags.get(
        "ENCODER_OPTIONS", atrack.other_tags.get("ENCODER_SETTINGS")
    ):
        if match := re.search(r"bitrate\s+(\d+)", enc_params):
            return f"{track_str} @ {match.group(1)}kb/s"

    # Try to guess the bitrate.
    if bit_rate := getattr(atrack.raw_ffprobe, "bit_rate", None):
        return f"{track_str} @ {closest_common_bitrate(int(bit_rate))}kb/s"

    if bps := atrack.other_tags.get("BPS"):
        try:
            kbps = closest_common_bitrate(int(bps))

            return f"{track_str} @ {kbps}kb/s"
        except (ValueError, TypeError):
            pass

    if (nbytes := atrack.other_tags.get("NUMBER_OF_BYTES")) and (
        duration_str := atrack.other_tags.get("DURATION")
    ):
        try:
            h, m, s = duration_str.split(":")
            seconds = int(h) * 3600 + int(m) * 60 + float(s)

            kbps = closest_common_bitrate(int(int(nbytes) * 8 / seconds))

            return f"{track_str} @ {kbps}kb/s"
        except (ValueError, TypeError):
            pass

    return track_str


def _get_descriptive_str(track_str: str, atrack: TrackInfo) -> str:
    """Get the descriptive string for a track."""

    if not atrack.raw_mkvmerge:
        return track_str

    visual_impaired = atrack.raw_mkvmerge.properties.flag_visual_impaired
    hearing_impaired = atrack.raw_mkvmerge.properties.flag_hearing_impaired
    commentary = atrack.raw_mkvmerge.properties.flag_commentary
    text_descriptions = atrack.raw_mkvmerge.properties.flag_text_descriptions

    if not any([visual_impaired, hearing_impaired, commentary, text_descriptions]):
        return track_str

    descriptive_str = []

    if any([visual_impaired, hearing_impaired, text_descriptions]):
        descriptive_str.append("Descriptive")

    if commentary:
        descriptive_str.append("Commentary")

    return f"{track_str} - {', '.join(descriptive_str)}"


def closest_common_bitrate(mps: int) -> int:
    """Get the closest common bitrate that is equal to or above the given bitrate."""

    target = round(mps / 1000)

    for bitrate in COMMON_LOSSY_BITRATES:
        if bitrate >= target:
            return bitrate

    return COMMON_LOSSY_BITRATES[-1]
