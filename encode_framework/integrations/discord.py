from configparser import ConfigParser
from enum import Enum, auto
from typing import Any

from discord_webhook import DiscordWebhook
from requests import Response  # type:ignore[import]

from ..util.logging import Log

__all__: list[str] = [
    "DiscordEmbedder",
    "DiscordEmbedOpts", "DisOpt"
]


class DiscordEmbedOpts(str, Enum):
    """
    User-passed Discord options for the webhook embed.

    Any of these failing should NEVER cause the embed itself to fail.
    """

    TRACKS = auto()
    """Display the number of tracks and basic information about each track."""

    PLOTBITRATE = auto()
    """Embed an image with the plotted bitrate of the output file if possible."""

    TIME_ELAPSED = auto()
    """Amount of time that has elapsed since the last embed."""

    FPS = auto()
    """Use TIME_ELAPSED to calculate a global FPS. Requires TIME_ELAPSED."""

    ANIME_INFO = auto()
    """Display basic anime information. Requires the anilist id to be set in [ANILIST] in config.ini."""

    EXCEPTION = auto()
    """Display the exception if an error is thrown."""


DisOpt = DiscordEmbedOpts


class DiscordEmbedder(DiscordWebhook):
    """Class for handling sending discord embeds."""

    webhook_url: str
    """The webhook url to send images to."""

    last_embed: Response | None = None
    """The last embed that was passed."""

    _encode_embed_opts: list[DiscordEmbedOpts] = []
    """Enum options for embeds."""

    def __init__(
        self, options: list[DiscordEmbedOpts] = [
            DiscordEmbedOpts.ANIME_INFO,
            DiscordEmbedOpts.TRACKS,
            DiscordEmbedOpts.TIME_ELAPSED,
            DiscordEmbedOpts.FPS,
            DiscordEmbedOpts.PLOTBITRATE,
            DiscordEmbedOpts.EXCEPTION,
        ],
        **webhook_kwargs: Any
    ) -> None:
        self._set_webhook_url()
        self._encode_embed_opts = options

        del options

        webhook_kwargs.pop("webhook_url", False)

        init_kwargs = {
            "avatar_url": "https://i.imgur.com/icZhOfv.png",
            "username": "Encode News Delivery Service",
            "rate_limit_entry": True
        }

        init_kwargs |= webhook_kwargs

        super().__init__(self.webhook_url, **init_kwargs)

        self.set_content("")
        self.remove_embeds()
        self.remove_files()

    def start(self, msg: str) -> None:
        """Encode start embed."""
        ...

    def success(self, msg: str) -> None:
        """Encode success embed."""
        ...

    def fail(self, msg: str) -> None:
        """Encode fail embed."""
        ...

    def ping(self) -> None:
        """Ping the webhook to see if it's alive."""
        self.set_content("Pong!")

        Log.info("Pinging webhook...", self.ping)  # type:ignore[arg-type]
        try:
            response = self.execute(True)
        except TypeError as e:
            raise Log.error(f"Could not ping webhook! ({e})", self.ping)  # type:ignore[arg-type]

        if not response.ok:
            raise Log.error(f"Could not ping webhook! ({response.status_code})", self.ping)  # type:ignore[arg-type]

        Log.info(f"Webhook succesfully pinged! (Time: {response.elapsed})", self.ping)  # type:ignore[arg-type]

    def _set_webhook_url(self, auth: str = "auth.ini") -> str:
        config = ConfigParser()

        config.read(auth)

        if not config.has_section("DISCORD"):
            raise Log.error(f"No \"DISCORD\" section found in \"{auth}\"!", self._set_webhook_url)

        if not config.has_option("DISCORD", "webhook_url"):
            raise Log.error(f"No \"webhook_url\" option found in \"{auth}\"!", self._set_webhook_url)

        self.webhook_url = config.get("DISCORD", "webhook_url")

        if not self.webhook_url:
            raise Log.error(f"No webhook_url set in \"{auth}\"!", self._set_webhook_url)

        return self.webhook_url

    def _format_ok(self, diagnostics: Any) -> str:
        return ""
