import subprocess as sp
import time
from datetime import datetime, timedelta, timezone
from enum import Enum, auto
from typing import Any, cast

from discord_webhook import DiscordEmbed, DiscordWebhook
from pymediainfo import MediaInfo  # type:ignore[import]
from pyupload.uploader import CatboxUploader  # type:ignore
from requests import Response  # type:ignore[import]
from vstools import SPath, SPathLike, vs

from ..config import get_items, get_option
from ..encode import Encoder
from ..script import ScriptInfo
from ..util import Log, markdownify
from .anilist import AniList, AniListAnime

__all__: list[str] = [
    "DiscordEmbedder",
    "DiscordEmbedOpts", "DisOpt"
]


class DiscordEmbedOpts(str, Enum):
    """
    User-passed Discord options for the webhook embed.

    Any of these failing should NEVER cause the embed itself to fail.
    """

    ANIME_INFO = auto()
    """Display basic anime information. Requires the anilist id to be set in [ANILIST] in config.ini."""

    EXCEPTION = auto()
    """Display the exception if an error is thrown."""

    PLOTBITRATE = auto()
    """Embed an image with the plotted bitrate of the output file if possible."""

    SHOW_FPS = auto()
    """Convert elapsed time to frames-per-second. Requires TIME_ELAPSED."""

    TIME_ELAPSED = auto()
    """Amount of time that has elapsed since the last embed."""

    TRACKS_INFO = auto()
    """Display the number of tracks and basic information about each track."""


DisOpt = DiscordEmbedOpts


class DiscordEmbedder(DiscordWebhook):
    """Class for handling sending discord embeds."""

    webhook_url: str
    """The webhook url to send images to."""

    last_embed: Response | None = None
    """The last embed that was passed."""

    _encode_embed_opts: set[DiscordEmbedOpts] = []
    """Enum options for embeds."""

    _history: list[Response] = []
    """A history of responses."""

    def __init__(
        self,
        script_info: ScriptInfo,
        encoder: Encoder,
        options: set[DiscordEmbedOpts] = {
            DiscordEmbedOpts.ANIME_INFO,
            DiscordEmbedOpts.EXCEPTION,
            DiscordEmbedOpts.PLOTBITRATE,
            DiscordEmbedOpts.SHOW_FPS,
            DiscordEmbedOpts.TIME_ELAPSED,
            DiscordEmbedOpts.TRACKS_INFO,
        },
        **webhook_kwargs: Any
    ) -> None:
        self._set_webhook_url()

        if not self.webhook_url:
            return

        self._start = False

        self.script_info = script_info
        self.encoder = encoder
        self.project_options = self._get_project_options()

        webhook_kwargs.pop("webhook_url", False)

        init_kwargs = {
            "avatar_url": "https://i.imgur.com/icZhOfv.png",
            "username": "BB Encode News Delivery Service",
            "rate_limit_entry": True
        }

        init_kwargs |= webhook_kwargs

        super().__init__(self.webhook_url, **init_kwargs)

        if not isinstance(options, set):
            options = {options}
        elif isinstance(options, list):
            options = set(options)

        self._encode_embed_opts = options

        if DiscordEmbedOpts.ANIME_INFO in self._encode_embed_opts:
            self._set_anilist()

    def start(self, msg: str = "") -> None:
        """Encode start embed This must ALWAYS be run first!."""
        if not self.webhook_url:
            return

        self._start = True

        embed = DiscordEmbed(title=self._get_base_title(), description=msg, color=33023)

        if DiscordEmbedOpts.ANIME_INFO in self._encode_embed_opts:
            embed = self._start_anime_info(embed)

        self._safe_add_embed(embed)
        self._safe_execute(self.start)

    def success(self, msg: str = "", pmx: SPathLike = "") -> None:
        """Encode success embed."""
        if not self.webhook_url:
            return

        if not self._start:
            Log.error(f"You must run \"{self.__class__.__name__}.start\" first!", self.success)

        if pmx:
            self.encoder.premux_path = SPath(pmx)

        embed = DiscordEmbed(title=self._get_base_title("has finished encoding!"), description=msg, color=32768)

        if DiscordEmbedOpts.ANIME_INFO in self._encode_embed_opts:
            embed = self._set_anilist_title(embed, "has finished encoding!")

        if DiscordEmbedOpts.TRACKS_INFO in self._encode_embed_opts:
            embed = self._track_sizes(embed)

        if DiscordEmbedOpts.PLOTBITRATE in self._encode_embed_opts:
            embed = self._set_plotbitrate(embed)

        if DiscordEmbedOpts.TIME_ELAPSED in self._encode_embed_opts:
            embed = self._success_add_elapsed(embed)

        if DiscordEmbedOpts.ANIME_INFO in self._encode_embed_opts:
            embed = self._success_add_next_airing(embed)

        self._safe_add_embed(embed)
        self._safe_execute(self.start)

    def fail(self, msg: str = "", exception: BaseException | str | None = None) -> None:
        """Encode fail embed."""
        if not self.webhook_url:
            return

        if not self._start:
            Log.error(f"You must run \"{self.__class__.__name__}.start\" first!", self.fail)

        embed = DiscordEmbed(title=self._get_base_title("has failed while encoding!"), description=msg, color=12582912)

        if DiscordEmbedOpts.ANIME_INFO in self._encode_embed_opts:
            embed = self._set_anilist_title(embed, "has failed while encoding!")

        if DiscordEmbedOpts.EXCEPTION in self._encode_embed_opts:
            embed = self._prettify_exception(embed, exception)

        self._safe_add_embed(embed)
        self._safe_execute(self.start)

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

    # !This is the start of all private functions ---------------------------------------------------------------------
    def _set_webhook_url(self, auth: str = "auth.ini") -> str:
        self.webhook_url = get_option("auth.ini", "DISCORD", "webhook_url")

        if not self.webhook_url:
            Log.error(f"You MUST set a webhook url to use Discord embeds!", self._set_webhook_url)

        return self.webhook_url

    def _get_project_options(self, config: str = "config.ini") -> dict[str, str]:
        """Get all the options from the config file's project section."""
        return get_items("config.ini", "SETUP")

    def _get_response_datetime(self, response: Response) -> datetime:
        return datetime.fromisoformat(dict(response.json()).get("timestamp", ""))

    def _get_base_title(self, suffix: str = "has started encoding") -> str:
        title = f"{self.project_options.get('out_name'), '&show& - &ep&'} {suffix}"

        show_name = self.project_options.get("show_name", "An unnamed series")

        if show_name.lower() == "nice series":
            show_name = "An unnamed series"

        title = title.replace("&show&", show_name)
        title = title.replace("&ep&", str(self.script_info.ep_num))
        title = title.replace("$crc32$", "").replace("[]", "")

        return title.strip()

    def _get_footer(self, embed: DiscordEmbed) -> DiscordEmbed:
        system = get_option("auth.ini", "DISCORD", "system_name")

        embed.set_footer((f"Running on {system}" if system else ""))

        return embed

    def _success_add_next_airing(self, embed: DiscordEmbed) -> DiscordEmbed:
        desc = ""

        if self._anime.next_airing_episode is not None:  # type:ignore[union-attr]
            desc += "\nTime until next episode airs: " \
                f"{self._anime.next_airing_episode.time_until_air}"  # type:ignore[union-attr]

        embed = self._append_to_embed_description(embed, desc)

        return embed

    def _set_anilist(self) -> AniListAnime | None:
        self._anilist = AniList()
        self._anime = self._anilist.get_anime_by_id()

        return self._anime

    def _set_anilist_title(self, embed: DiscordEmbed, suffix: str = "has started encoding!") -> DiscordEmbed:
        if self._anime is None:
            return embed

        title = self._anime.name.get(get_option("config.ini", "ANILIST", "title_language").lower(), None)

        # No title found, get the first fallback title it can find.
        if title is None:
            for lang in ("romaji", "english", "native"):
                if title := self._anime.name.get(lang, ""):
                    break

                title = "???"

        embed.set_title(f"{title} - {str(self.script_info.ep_num)} {suffix}")

        return embed

    def _start_anime_info(self, embed: DiscordEmbed) -> DiscordEmbed:
        """Make the embed fancy if you pass anime info"""
        if self._anime is None:
            return embed

        self._anime = cast(AniListAnime, self._anime)

        # OVAs, movies, etc. are typically not considered part of a "TV" season.
        if self._anime.format not in ("TV"):
            self._anime.tv_season = self._anime.tv_season.split(" ")[-1]

        desc = f"Aired: {self._anime.tv_season} ({self._anime.status})"

        if embed.description:
            desc += f"\n{embed.description}"

        embed = self._set_anilist_title(embed, "has started encoding!")
        embed.set_description(desc)
        embed.set_image(self._anime.img)

        return embed

    def _track_sizes(self, embed: DiscordEmbed) -> DiscordEmbed:
        tracks = self._get_track_sizes()

        desc = f"* Total filesize: {tracks[0][1]}"

        for track_type, file_size in tracks[1:]:
            desc += f"\n * {track_type}: {file_size}"

        embed = self._append_to_embed_description(embed, desc)

        return embed

    def _get_track_sizes(self, premux_path: SPathLike | None = None) -> list[tuple[str, str]]:
        if premux_path is None:
            premux_path = self.encoder.premux_path

        premux_path = SPath(premux_path)

        tracks: list[tuple[str, str]] = []

        for track in MediaInfo.parse(premux_path, full=False).tracks:
            if track.track_type == "General":
                tracks += [(track.track_type, track.file_size)]
            elif track.track_type in ("Video", "Audio"):
                tracks += [
                    (f"{track.track_type} ({track.track_id}) [{str(track.format).split(' ')[0].upper()}]",
                     track.stream_size)
                ]
            elif track.track_type == "Text":
                tracks += [(f"Subtitles ({track.track_id})", track.stream_size)]

        return tracks

    def _set_plotbitrate(self, embed: DiscordEmbed) -> DiscordEmbed:
        embed.set_image(self._make_plotbitrate())

        return embed

    def _make_plotbitrate(self, premux_path: SPathLike | None = None) -> str:
        if premux_path is None:
            premux_path = self.encoder.premux_path

        premux_path = SPath(premux_path)

        out_path = premux_path.with_suffix(".png")

        sp.run(["plotbitrate", "-o", out_path.to_str(), "-f", "png", "--show-frame-types", premux_path.to_str()])

        url = CatboxUploader(out_path.to_str()).execute()

        out_path.unlink(missing_ok=True)

        return url

    def _success_add_elapsed(self, embed: DiscordEmbed) -> DiscordEmbed:
        # !For some reason this is about 5s off. Not a big deal, but still, wtf?
        elapsed = datetime.now(timezone(timedelta(seconds=0), name=time.tzname[time.daylight])) - \
            self._get_response_datetime(self._history[0])

        desc = f"\nTime elapsed: {str(elapsed)[:-3]}"

        if DiscordEmbedOpts.SHOW_FPS in self._encode_embed_opts:
            desc += f" ({self._calc_fps(self.encoder.out_clip, elapsed.seconds):.2f} fps)"

        embed = self._append_to_embed_description(embed, desc)

        return embed

    def _calc_fps(self, clip: vs.VideoNode, elapsed_time: float) -> float:
        """Calculate the framerate. We can't get it from the encoder directly it seems, so gotta do it ourselves."""
        return clip.num_frames / elapsed_time

    def _prettify_exception(self, embed: DiscordEmbed, exception: BaseException | str | None = None) -> DiscordEmbed:
        if isinstance(exception, KeyboardInterrupt):
            exception = "The encode was manually interrupted!"

        if exception:
            exception = markdownify(str(exception))

        exception = exception or "Please consult the stacktrace!"

        embed = self._append_to_embed_description(embed, str(exception))

        return embed

    def _append_to_embed_title(self, embed: DiscordEmbed, title: str) -> DiscordEmbed:
        embed.set_title(str(embed.title) + title)

        return embed

    def _append_to_embed_description(self, embed: DiscordEmbed, description: str) -> DiscordEmbed:
        embed.set_description(str(embed.description) + description)

        return embed

    def _safe_add_embed(self, embed: DiscordEmbed) -> None:
        """Strip specific types of content in the passed embed."""
        embed.title = str(embed.title).strip()
        embed.description = str(embed.description).strip()

        self.add_embed(embed)

    def _safe_execute(self, caller: str | Any | None = None) -> Response:
        """Remove and re-add properties that break `execute()` safely."""
        saved_props: dict[str, Any] = {}

        annoying_props = (
            "_anilist", "_anime", "_encode_embed_opts", "_history", "_start",
            "encoder", "project_options", "script_info", "start_time"
        )

        for prop in annoying_props:
            if hasattr(self, prop):
                saved_props |= {prop: getattr(self, prop)}

                try:
                    delattr(self, prop)
                except AttributeError as e:
                    Log.debug(str(e), self._safe_execute)

        Log.info("Pinging Discord webhook.", caller)
        r = self.execute()

        for k, v in saved_props.items():
            setattr(self, k, v)

        del saved_props

        self._history += [r]

        if not r.ok:
            Log.error(str(self.get_embeds()), caller)

        self.remove_embeds()

        return r
