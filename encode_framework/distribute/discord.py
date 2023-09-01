from configparser import ConfigParser
from typing import Any

from discord_webhook import DiscordWebhook

from ..util.logging import Log

__all__: list[str] = [
    "DiscordEmbedder"
]

class DiscordEmbedder(DiscordWebhook):
    """Class for handling sending discord embeds."""

    webhook_url: str
    """The webhook url to send images to."""

    def __init__(self) -> None:
        self._set_webhook_url()

        super().__init__(
            self.webhook_url,
            avatar_url="https://i.imgur.com/icZhOfv.png",
            username="Encode News Delivery Service",
            rate_limit_entry=True
        )

    def ok(self, msg: str) -> None:
        """Success message."""
        ...

    def fail(self, msg: str) -> None:
        """Fail message."""
        ...

    def init(self, msg: str) -> None:
        """Init message."""
        ...

    def ping(self) -> None:
        """Ping the webhook to see if it's alive."""
        self.set_content("Pong!")

        Log.info("Pinging webhook...", self.ping)  # type:ignore[arg-type]
        response = self.execute()

        if not response.ok:
            raise Log.error(f"Could not ping webhook! ({response.status_code})", self.ping)  # type:ignore[arg-type]

        Log.info(f"Webhook succesfully pinged! (Time: {response.elapsed})", self.ping)  # type:ignore[arg-type]

    def _set_webhook_url(self, auth: str = "auth.ini") -> str:
        config = ConfigParser()

        config.read(auth)

        if not config.has_section("DISCORD"):
            raise Log.error(f"No \"DISCORD\" section found in \"{auth}\"!", self._set_webhook_url)

        if not config.has_option("DISCORD", "webhook"):
            raise Log.error(f"No \"webhook\" option found in \"{auth}\"!", self._set_webhook_url)

        self.webhook_url = config.get("DISCORD", "webhook")

        if not self.webhook_url:
            raise Log.error(f"No webhook set in \"{auth}\"!", self._set_webhook_url)

        return self.webhook_url

    def _format_ok(self, diagnostics: Any) -> str:
        ...


