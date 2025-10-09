import subprocess as sp
import time
from datetime import datetime, timedelta, timezone
from enum import Enum, auto
from shutil import which
from typing import Any, Literal, cast

from discord_webhook import DiscordEmbed, DiscordWebhook
from pymediainfo import MediaInfo, Track  # type:ignore[import]
from pyupload.uploader import CatboxUploader  # type:ignore
from requests import Response  # type:ignore[import]
from vsmuxtools.video import fill_props
from vsmuxtools.video.settings import file_or_default, settings_builder_x265
from vstools import CustomValueError, SPath, SPathLike, vs

from ..config import get_items, get_option
from ..encode import Encoder
from ..script import ScriptInfo
from ..util import Log, markdownify
from .anilist import AniList, AniListAnime
from .ftp import Ftp

__all__: list[str] = ["DiscordEmbedder", "DiscordEmbedOpts", "DisOpt"]


class DiscordEmbedOpts(str, Enum):
    """
    User-passed Discord options for the webhook embed.

    Any of these failing should NEVER cause the embed itself to fail.
    """

    ANIME_INFO = auto()
    """Display basic anime information. Requires the anilist id to be set in [ANILIST] in config.ini."""

    EXCEPTION = auto()
    """Display the exception if an error is thrown."""

    GENERAL_FILE_INFO = auto()
    """Display basic information about the file. Ignored if TRACKS_INFO is enabled."""

    PLOTBITRATE = auto()
    """Embed an image with the plotted bitrate of the output file if possible."""

    SETTINGS_VIDEO_ENCODE = auto()
    """Show the settings used for the encode, if a settings file is found."""

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

    _encode_embed_opts: set[DiscordEmbedOpts] = set()
    """Enum options for embeds."""

    _history: list[Response] = []
    """A history of responses."""

    def __init__(
        self,
        script_info: ScriptInfo,
        encoder: Encoder | tuple[Encoder, Encoder],
        options: set[DiscordEmbedOpts] = {
            DiscordEmbedOpts.ANIME_INFO,
            DiscordEmbedOpts.EXCEPTION,
            DiscordEmbedOpts.PLOTBITRATE,
            DiscordEmbedOpts.SETTINGS_VIDEO_ENCODE,
            DiscordEmbedOpts.SHOW_FPS,
            DiscordEmbedOpts.TIME_ELAPSED,
            DiscordEmbedOpts.TRACKS_INFO,
        },
        **webhook_kwargs: Any,
    ) -> None:
        """
        :param script_info:         The ScriptInfo object containing information about the script.
        :param encoder:             The encoder(s) used to encode the video and/or audio.
                                    Can accept a tuple of (VideoEncoder, AudioEncoder).
        :param options:             Options for what to include in the embeds.
                                    See the DiscordEmbedOpts class for more information.
        :param webhook_kwargs:      Keyword arguments to pass on to the webhook API.
        """
        self._set_webhook_url()

        if not self.webhook_url:
            return

        self._start = False

        self.script_info = script_info
        self.encoder = encoder
        self.project_options = self._get_project_options()
        self._history = []

        webhook_kwargs.pop("webhook_url", False)

        init_kwargs = {
            "avatar_url": "https://i.imgur.com/icZhOfv.png",
            "username": "BB Encode News Delivery Service",
            "rate_limit_entry": True,
        }

        init_kwargs |= webhook_kwargs

        super().__init__(self.webhook_url, **init_kwargs)

        if not isinstance(options, set):
            options = {options}
        elif isinstance(options, list):
            options = set(options)

        self._encode_embed_opts = options

        if all(
            x in self._encode_embed_opts
            for x in (DiscordEmbedOpts.TRACKS_INFO, DiscordEmbedOpts.GENERAL_FILE_INFO)
        ):
            self._encode_embed_opts -= set(DiscordEmbedOpts.GENERAL_FILE_INFO)

        if DiscordEmbedOpts.ANIME_INFO in self._encode_embed_opts:
            self._set_anilist()

    def start(self, msg: str = "") -> None:
        """Encode start embed This must ALWAYS be run first!"""
        if not self.webhook_url:
            return

        if self._start:
            return

        self._start = True

        embed = DiscordEmbed(title=self._get_base_title(), description=msg, color=33023)

        if DiscordEmbedOpts.ANIME_INFO in self._encode_embed_opts:
            embed = self._start_anime_info(embed)

        if DiscordEmbedOpts.SETTINGS_VIDEO_ENCODE in self._encode_embed_opts:
            embed = self._video_enc_settings(embed)

        self._safe_add_embed(embed)
        self._safe_execute(self.start)

    def success(self, msg: str = "", pmx: SPathLike = "") -> None:
        """Encode success embed."""

        if not self.webhook_url:
            return

        # if not self._start:
        #     Log.error(f"You must run \"{self.__class__.__name__}.start\" first!", self.success)

        if pmx:
            if isinstance(self.encoder, tuple):
                self.encoder[0].premux_path = SPath(pmx)
            else:
                self.encoder.premux_path = SPath(pmx)

        embed = DiscordEmbed(
            title=self._get_base_title("has finished encoding!"),
            description=msg,
            color=32768,
        )

        if DiscordEmbedOpts.ANIME_INFO in self._encode_embed_opts:
            embed = self._set_anilist_title(embed, "has finished encoding!")

        if any(
            x in self._encode_embed_opts
            for x in (DiscordEmbedOpts.TRACKS_INFO, DiscordEmbedOpts.GENERAL_FILE_INFO)
        ):
            embed = self._track_info(embed)

        if DiscordEmbedOpts.TIME_ELAPSED in self._encode_embed_opts:
            embed = self._success_add_elapsed(embed)

        if DiscordEmbedOpts.ANIME_INFO in self._encode_embed_opts:
            embed = self._success_add_next_airing(embed)

        if DiscordEmbedOpts.PLOTBITRATE in self._encode_embed_opts:
            embed = self._set_plotbitrate(embed)

        self._safe_add_embed(embed)
        self._safe_execute(self.success)

    def fail(
        self, msg: str = "", exception: BaseException | str | None = None
    ) -> Exception:
        """Encode fail embed."""
        if not self.webhook_url:
            return

        if not self._start:
            return Log.error(
                f'You must run "{self.__class__.__name__}.start" first!\n'
                f"Original exception: {exception}",
                self.fail,
            )

        embed = DiscordEmbed(
            title=self._get_base_title("has failed while encoding!"),
            description=msg,
            color=12582912,
        )

        if DiscordEmbedOpts.ANIME_INFO in self._encode_embed_opts:
            embed = self._set_anilist_title(embed, "has failed while encoding!")

        if DiscordEmbedOpts.EXCEPTION in self._encode_embed_opts:
            embed = self._prettify_exception(embed, markdownify(exception))

        embed = self._append_to_embed_description(embed, f"```{embed.description}```")

        self._safe_add_embed(embed)
        self._safe_execute(self.fail)

        return Exception(exception)

    def ftp_upload(self, ftp: Ftp) -> None:
        """FTP upload success."""
        if not self.webhook_url:
            return

        if not self._start:
            return Log.error(
                f'You must run "{self.__class__.__name__}.start" first!',
                self.ftp_upload,
            )

        if not ftp._history:
            raise CustomValueError(
                "You cannot call this embedded if you haven't uploaded anything!",
                self.ftp_upload,
            )

        msg = "The following files were uploaded to the FTP:"

        for transfer in ftp._history:
            msg += f"\n - {transfer.human_readable(DiscordEmbedOpts.TIME_ELAPSED in self._encode_embed_opts)}"

        embed = DiscordEmbed(title="FTP Uploads", description=msg, color=32768)

        self._safe_add_embed(embed)
        self._safe_execute(self.ftp_upload)

    def ping(self) -> None:
        """Ping the webhook to see if it's alive."""
        self.set_content("Pong!")

        Log.info("Pinging webhook...", self.ping)  # type:ignore[arg-type]

        try:
            response = self.execute(True)
        except TypeError as e:
            raise Log.error(f"Could not ping webhook! ({e})", self.ping)  # type:ignore[arg-type]

        if not response.ok:
            raise Log.error(
                f"Could not ping webhook! ({response.status_code})", self.ping
            )  # type:ignore[arg-type]

        Log.info(f"Webhook succesfully pinged! (Time: {response.elapsed})", self.ping)  # type:ignore[arg-type]

    # !This is the start of all private functions ---------------------------------------------------------------------
    def _set_webhook_url(self, auth: str = "auth.ini") -> str:
        self.webhook_url = get_option(auth, "DISCORD", "webhook_url")

        if "support.discord.com" in str(self.webhook_url):
            self.webhook_url = None

        if not self.webhook_url:
            Log.error(
                "You MUST set a webhook url to use Discord embeds!",
                self._set_webhook_url,
            )

        return self.webhook_url

    def _get_project_options(self, config: str = "config.ini") -> dict[str, str]:
        """Get all the options from the config file's project section."""
        return get_items(config, "SETUP")

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
            desc += (
                "\nTime until next episode airs: "
                f"{self._anime.next_airing_episode.time_until_air}"
            )  # type:ignore[union-attr]

        embed = self._append_to_embed_description(embed, desc)

        return embed

    def _set_anilist(self) -> AniListAnime | None:
        self._anilist = AniList()
        self._anime = self._anilist.get_anime_by_id()

        return self._anime

    def _set_anilist_title(
        self, embed: DiscordEmbed, suffix: str = "has started encoding!"
    ) -> DiscordEmbed:
        if self._anime is None:
            return embed

        title = self._anime.name.get(
            get_option("config.ini", "ANILIST", "title_language").lower(), None
        )

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

        desc = f"Aired: {self._anime.tv_season} (Airing Status: {self._anime.status})"

        if self._anime.next_airing_episode is not None:
            # TODO: this
            # desc += "\nTODO: add airing info :D (remind @lightarrowsexe if you see this)"
            pass

        embed = self._append_to_embed_description(embed, desc)

        embed = self._set_anilist_title(embed, "has started encoding!")
        embed.set_description(desc)

        if self._anime.img:
            Log.info(self._anime.img, self._start_anime_info)
            embed.set_image(self._anime.img)
        else:
            Log.warn("No image could be found to attach!", self._start_anime_info)

        return embed

    def _video_enc_settings(self, embed: DiscordEmbed) -> DiscordEmbed:
        from vsmuxtools import x265

        audio_encoder = None

        if isinstance(self.encoder, tuple):
            self.encoder, audio_encoder = self.encoder

        if not (sfile := SPath(f"_settings/{self.encoder.encoder.__name__}_settings")):
            return embed

        enc_is_x265 = isinstance(self.encoder.encoder, x265)

        out_clip = self.encoder._finalize_clip(
            self.encoder.out_clip, func=self._video_enc_settings
        )

        settings = file_or_default(
            sfile.to_str(),
            settings_builder_x265() if enc_is_x265 else settings_builder_x265(),
        )
        settings = fill_props(settings[0], out_clip, enc_is_x265)

        desc = f"\nTotal number of frames: {out_clip.num_frames}\n"
        desc += f"Video Encoder: {self.encoder.encoder.__name__}\n"

        if audio_encoder:
            desc += f"Audio Encoder: {audio_encoder.__name__}\n"

        desc += "```bash\nEncoder settings:\n\n"

        settings = [x.replace("--", "").strip() for x in settings.split(" --")]
        settings.sort()

        for setting in settings:
            if not setting.startswith("--"):
                setting = "--" + setting

            if (len(desc.split("\n")[-1] + setting)) > 42:
                desc += "\n"

            if " " in setting:
                desc += "=".join(setting.split(" ", maxsplit=1)) + " "
            else:
                desc += f"{setting} "

        desc += "\n```"

        return self._append_to_embed_description(embed, desc)

    def _track_info(self, embed: DiscordEmbed) -> DiscordEmbed:
        encoder = self.encoder[0] if isinstance(self.encoder, tuple) else self.encoder
        tracks = self._get_tracks(encoder.premux_path)

        desc = f"```markdown\n{encoder.premux_path.name}\n * Total Filesize: {tracks[0][1]}```\n"

        if DiscordEmbedOpts.GENERAL_FILE_INFO not in self._encode_embed_opts:
            desc += "```markdown\n"

            for track_title, track_info in tracks[1:]:
                desc += f"{track_title}:"

                if track_info:
                    desc += "\n    - " + "\n    - ".join(track_info)

                desc += "\n\n"

            desc += "```"

        Log.debug(f"Discord embed for tracks:\n{desc.strip()}", self._track_info)

        embed = self._append_to_embed_description(embed, desc.strip())

        return embed

    def _get_tracks(
        self, premux_path: SPathLike | None = None
    ) -> list[tuple[str, list[str]]]:
        if not premux_path:
            if isinstance(self.encoder, tuple):
                encoder = self.encoder[0]
            else:
                encoder = self.encoder

            premux_path = encoder.premux_path

        premux_path = SPath(premux_path)

        tracks: list[tuple[str, str]] = []

        try:
            for track in MediaInfo.parse(premux_path).tracks:
                assert isinstance(track, Track), f"Track {track} is not a track!"

                if track.track_type == "General":
                    tracks += [(track.track_type, track.other_file_size[0])]
                elif track.track_type == "Video":
                    tracks += [self._get_video_track_info(track)]
                elif track.track_type == "Audio":
                    tracks += [self._get_audio_track_info(track)]
                elif track.track_type == "Text":
                    tracks += [self._get_subtitle_track_info(track)]
                elif track.track_type == "Menu":
                    ch = self._get_menu_track_info(track)

                    if ch:
                        tracks += [ch]
                else:
                    Log.debug(f"Unprocessed track: {vars(track)}", self._track_info)
        except Exception as e:
            Log.error((str(vars(track)), e), self._track_info)

            raise Log.error(
                f'An error occured while retrieving the "{track.track_type}" track!',
                self._get_tracks,
            )

        return tracks

    def _get_basic_track_title(self, track: Track) -> str:
        return (
            " ".join(
                [
                    f"[{track.track_id}] {track.track_type}",
                    f"({track.commercial_name})",
                    f"{track.other_stream_size[0]}",
                ]
            )
            .replace("] Text ", "] Subtitles ")
            .strip()
        )

    def _get_video_track_info(self, track: Track) -> tuple[str, list[str]]:
        t_data = track.to_data()

        Log.debug(t_data, self._get_video_track_info)

        res = f"{track.width}x{track.height}"

        # TODO: Add a check for progressive/interlaced video
        res += "p"

        encoder = self.encoder[0] if isinstance(self.encoder, tuple) else self.encoder

        info = [
            # Language
            f"Language: {t_data.get('language', 'Not set')}",
            # Framerate check (can help you figure out whether the encode truly finished)
            f"{track.frame_count}/{encoder.out_clip.num_frames} frames",
            # Base resolution + Bit depth
            f"{res} ({track.other_display_aspect_ratio[0]}) {track.other_bit_depth[0][:-1]}",
            # Frame rate
            f"{str(track.other_frame_rate[0]).lower()} ({track.frame_rate_mode})",
        ]

        # True resolution PAR =/= 1  TODO: Figure out how to calc this!
        # if not float(eval(track.pixel_aspect_ratio)).is_integer():
        #     info.insert(1, f"Sampled resolution: {track.sampled_width}x{track.sampled_height}")

        # Colorimetry, but only if set by the user.
        if t_data.get("matrix_coefficients_source", "") == "Stream":
            info += [
                " / ".join(
                    [
                        f"{track.matrix_coefficients} (M)",
                        f"{track.transfer_characteristics} (T)",
                        f"{track.color_primaries} (P)",
                    ]
                )
            ]

        return (self._get_basic_track_title(track), info)

    def _get_audio_track_info(self, track: Track) -> tuple[str, list[str]]:
        t_data = track.to_data()

        Log.debug(t_data, self._get_audio_track_info)

        info = [
            # Number of channels
            str(t_data.get("other_channel_s", ["Unknown number of channels"])[0]),
            # Language
            f"Language: {t_data.get('language', 'Not set')}",
            # Track selection
            f"Default: {t_data.get('default', 'Unknown')}",
            f"Forced: {t_data.get('forced', 'Unknown')}",
        ]

        info += self._get_track_flags(t_data)

        if t_data.get("commercial_name", "") == "FLAC":
            info += [
                # Bit depth
                str(t_data.get("other_bit_depth", ["?"])[0]),
            ]

        if delay := t_data.get("delay_relative_to_video", 0):
            info += [
                # Delay
                f"Delay relative to video: {str(delay)}ms"
            ]

        return (self._get_basic_track_title(track), info)

    def _get_subtitle_track_info(self, track: Track) -> tuple[str, list[str]]:
        t_data = track.to_data()

        info = [
            f"Language: {t_data.get('language', 'Not set')}",
            f"Default: {t_data.get('default', 'Unknown')}",
            f"Forced: {t_data.get('forced', 'Unknown')}",
        ]

        if delay := t_data.get("delay_relative_to_video", 0):
            info += [
                # Delay
                f"Delay relative to video: {str(delay)}ms"
            ]

        info += self._get_track_flags(t_data)

        return (self._get_basic_track_title(track), info)

    def _get_track_flags(self, track_data: dict[str, Any] = {}) -> list[str]:
        flags_to_check: list[tuple[str, str]] = [
            ("hearing_impaired", "Hearing Impaired"),
            ("visual_impaired", "Visual Impaired"),
            ("text_description", "Text Description"),
            ("original", "Original"),
            ("commentary", "Commentary"),
        ]

        flags = []

        for flag_name, flag_label in flags_to_check:
            if flag := track_data.get(flag_name, False):
                flags.append(f"{flag_label}: {flag}")

        return flags

    def _get_menu_track_info(self, track: Track) -> tuple[str, list[str]]:
        chapters = []

        for k, v in dict(sorted(vars(track).items())).items():
            try:
                _ = int(str(k).replace("_", ""))
                chapters += [f"{k.replace('_', ':')} - {v.split(':', 1)[1]}"]
            except (TypeError, ValueError) as e:
                Log.debug(e, self._get_menu_track_info)
                break

        if not chapters:
            return ()

        return (f"[+] Chapters ({len(chapters)})", chapters)

    def _set_plotbitrate(self, embed: DiscordEmbed) -> DiscordEmbed:
        url = self._make_plotbitrate()

        if url:
            embed.set_image(url)
        else:
            Log.error("Could not upload image!", self._set_plotbitrate)
            embed = self._append_to_embed_description(
                embed, "< Could not upload bitrate plot >"
            )

        return embed

    def _make_plotbitrate(
        self, premux_path: SPathLike | None = None
    ) -> str | Literal[False]:
        if not which("plotbitrate"):
            from vstools import DependencyNotFoundError

            Log.error(
                'The executable for "plotbitrate" could not be found! Install it with `pip install plotbitrate`!',
                self._make_plotbitrate,
                DependencyNotFoundError,
            )
            return False

        if premux_path is None:
            encoder = (
                self.encoder[0] if isinstance(self.encoder, tuple) else self.encoder
            )
            premux_path = encoder.premux_path

        premux_path = SPath(premux_path)

        out_path = premux_path.with_suffix(".png")

        url = ""

        try:
            args = [
                "python",
                "-m",
                "plotbitrate",
                "-o",
                out_path.to_str(),
                "-f",
                "png",
                "--show-frame-types",
                premux_path.to_str(),
            ]

            sp.run(args)
        except sp.CalledProcessError:
            Log.error(
                f"An error occurred while trying to create a bitrate plot! Params:\n{args}",
                self._make_plotbitrate,
            )

        err = 0

        try:
            url = CatboxUploader(out_path.to_str()).execute()
        except FileNotFoundError as e:
            Log.error(str(e), "CatboxUploader.execute")
            err = 1
        except Exception as e:
            Log.error(str(e), "CatboxUploader.execute")
            err = 1

        if not err:
            out_path.unlink(missing_ok=True)

        return url

    def _success_add_elapsed(self, embed: DiscordEmbed) -> DiscordEmbed:
        # !For some reason this is about 5s off. Not a big deal, but still, wtf?
        elapsed = datetime.now(
            timezone(timedelta(seconds=0), name=time.tzname[time.daylight])
        ) - self._get_response_datetime(self._history[-1])

        desc = f"\nTime elapsed: {str(elapsed)[:-3]}"

        if DiscordEmbedOpts.SHOW_FPS in self._encode_embed_opts:
            encoder = (
                self.encoder[0] if isinstance(self.encoder, tuple) else self.encoder
            )

            desc += (
                f" (≈{self._calc_fps(encoder.out_clip, elapsed.seconds):.2f} fps total)"
            )

        embed = self._append_to_embed_description(embed, desc)

        return embed

    def _calc_fps(self, clip: vs.VideoNode, elapsed_time: float) -> float:
        """Calculate the framerate. We can't get it from the encoder directly it seems, so gotta do it ourselves."""
        return clip.num_frames / elapsed_time

    def _prettify_exception(
        self, embed: DiscordEmbed, exception: BaseException | str | None = None
    ) -> DiscordEmbed:
        if isinstance(exception, KeyboardInterrupt):
            exception = "The encode was manually interrupted! "

        if exception:
            exception = markdownify(str(exception))

        exception = exception or "Please consult the stacktrace!"

        embed = self._append_to_embed_description(embed, str(exception))

        return embed

    def _append_to_embed_title(self, embed: DiscordEmbed, title: str) -> DiscordEmbed:
        embed.set_title(str(embed.title) + title)

        return embed

    def _append_to_embed_description(
        self, embed: DiscordEmbed, description: str
    ) -> DiscordEmbed:
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
            "_anilist",
            "_anime",
            "_encode_embed_opts",
            "_history",
            "_start",
            "encoder",
            "project_options",
            "script_info",
            "start_time",
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

        if not hasattr(self, "_history"):
            self._history = []

        self._history += [r]

        if not r.ok:
            Log.error(str(self.get_embeds()), caller)

        self.remove_embeds()

        return r
