import re

__all__: list[str] = [
    "markdownify",
    "get_opus_bitrate_from_channels"
]


def markdownify(string: str) -> str:
    """Markdownify a given string."""
    string = re.sub(r"\[bold\]([a-zA-Z0-9\.!?:\-]+)?\[\/\]", r"**\1**", str(string))
    string = re.sub(r"\[italics\]([a-zA-Z0-9\.!?:\-]+)?\[\/\]", r"_\1_", str(string))

    return string


def get_opus_bitrate_from_channels(channel_count: float = 2.0) -> str:
    """Get the channel count from the name for Opus."""

    channel_count = float(channel_count)
    base_str = f'Opus {channel_count} @ '

    if channel_count <= 2.0:
        return base_str + '192kb/s'

    if channel_count > 6.0:
        return base_str + '420kb/s'

    return base_str + '320kb/s'
