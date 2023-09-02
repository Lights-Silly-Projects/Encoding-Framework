import json
from configparser import ConfigParser
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import requests  # type:ignore[import]
from requests.exceptions import ConnectionError  # type:ignore[import]

from ..config import add_section, get_option
from ..util import Log

__all__: list[str] = [
    "AniList",
    "AniListAnime",
    "AiringSchedule",

    "create_anilist_section"
]


class AiringSchedule:
    """A class representing an airing schedule for a single episodes"""

    next_air_date: datetime
    """The datetime when the next episode airs"""

    time_until_air: timedelta
    """Time until the next episode airs"""

    episode: int
    """The next episode's episode number"""

    def __init__(self, next_air_date: int, time_until_air: int, episode: int) -> None:
        self.next_air_date = self.epoch_to_datetime(next_air_date)
        self.time_until_air = timedelta(seconds=time_until_air)
        self.episode = episode

    @classmethod
    def epoch_to_datetime(cls, epoch_time: int) -> datetime:
        """Convert from epoch time to a datetime object."""
        return datetime.fromtimestamp(epoch_time)


class AniListAnime:
    """A class containing basic information about an anime queried from AniList."""

    id: int
    """The AniList id. -1 means \"Unknown Id\"."""

    name: dict[str, str]
    """The dominant title of the anime."""

    tv_season: str
    """Which TV season and year the anime came out in."""

    status: str
    """The airing status of the anime."""

    url = str
    """Url to the AniList page."""

    img: str
    """Url to the banner image for embeds."""

    next_airing_episode: AiringSchedule | None = None
    """Information about the next scheduled episode to air, if any."""

    etc = dict[str, Any]
    """Any remainning unprocessed results."""

    def __init__(self, **kwargs: dict[str, Any]) -> None:
        self.id = int(kwargs.pop("id", -1))  # type:ignore[assignment, arg-type]
        self.name = kwargs.pop("title", {'english': '???'})

        self.format = str(kwargs.pop("format", "TV"))
        self.status = str(kwargs.pop("status", "Unknown")).replace("_", "-").capitalize()

        self.tv_season = " ".join([
            str(kwargs.pop("season", "")).capitalize(), str(kwargs.pop("seasonYear", ""))
        ]).strip()

        self.url = str(kwargs.pop("siteUrl", "https://anilist.co/"))  # type:ignore[assignment]
        self.img = self._handle_img(kwargs.pop("bannerImage", ""), kwargs.pop("coverImage", {}))

        if (airing_schedule := kwargs.pop("nextAiringEpisode", None)) is None:
            self.next_airing_episode = airing_schedule

        if isinstance(airing_schedule, dict):
            self.next_airing_episode = AiringSchedule(
                airing_schedule.pop("airingAt"),
                airing_schedule.pop("timeUntilAiring"),
                airing_schedule.pop("episode")
            )

        self.etc = kwargs  # type:ignore[assignment]

    def _handle_img(self, banner: str, cover: dict[str, str]) -> str:
        return banner or cover.get("large", "https://i.imgur.com/BvjeQwv.gif")


class AniList:
    """A class for basic AniList API calls."""

    _url = "https://graphql.anilist.co"

    history: list[tuple[datetime, AniListAnime]] = []
    """A list of results obtained from this instantiated class."""

    def get_anime_by_id(self, anime_id: int | None = None) -> AniListAnime | None:
        """Retrieve an Anime object containing all the information that may be used in this package."""
        anime_id = anime_id or self._get_config_anime_id()

        if not anime_id:
            Log.error(
                "Can't query without a valid AniList id! "
                "Please set one in your project config file!",
                self.get_anime_by_id
            )

            return None

        query = """
            query ($id: Int) {
                Media (id: $id, type: ANIME) {
                    id
                    title {
                        romaji
                        english
                        native
                    }
                    format
                    status
                    season
                    seasonYear
                    coverImage {
                        large
                    }
                    bannerImage
                    nextAiringEpisode {
                        airingAt
                        timeUntilAiring
                        episode
                    }
                    siteUrl
                }
            }
        """

        results = AniListAnime(**self._send_payload(query, {'id': anime_id}))

        self.history += [(datetime.now(), results)]

        return results

    def _send_payload(self, query: str, variables: dict[str, Any] = {}) -> dict[str, Any]:
        r = requests.post(self._url, json={'query': query, 'variables': variables})

        if not r.ok:
            errs = []

            for err in dict(json.loads(r.content)).get('errors', list()):
                errs += [f"{r.status_code} ({r.reason}): {err or 'No error message given...'}"]

            msg = "An error was thrown while getting the anime details:"

            if len(errs) > 1:
                msg = f"{len(errs)} errors were thrown while getting the anime details:"

            Log.error(
                "\n".join([msg] + (errs or [f"{r.status_code} ({r.reason}): No error message given..."])),
                self.get_anime_by_id
            )

            return {}

        return dict(json.loads(r.content)).get('data', dict()).get('Media', dict())

    def ping(self) -> None:
        """Ping the AniList API point to check whether it's currently alive."""
        try:
            r = requests.post(self._url)
            Log.info(f"Pong! (Time: {r.elapsed})", self.ping)  # type:ignore[arg-type]
        except (ConnectionError) as e:
            Log.error(str(e), self.ping)  # type:ignore[arg-type]

    def _get_config_anime_id(self, filename: str | Path = "config.ini") -> int:
        """Get the anime id from the project config file. If it can't, return 0."""
        try:
            return int(get_option(filename, "ANILIST", "anime_id"))
        except (TypeError, ValueError):
            return 0


def create_anilist_section(filename: str | Path = "config.ini") -> ConfigParser:
    """Create the anilist section in the config file."""
    return add_section(filename, "ANILIST", [{"anime_id": "", "title_language": "romaji"}])
