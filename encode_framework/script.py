"""
    Common boilerplate in most of my scripts.
"""
from __future__ import annotations

import inspect
import os
import sys
from datetime import timedelta
from random import choice
from time import time
from typing import Any, Callable, cast

from vsmuxtools import src_file
from vstools import Keyframes, SceneChangeMode, SPath, SPathLike, set_output, vs

from .discord import notify_webhook
from .kernels import ZewiaCubicNew
from .logging import Log
from .types import TrimAuto
from .updater import self_update

__all__: list[str] = [
    "ScriptInfo",
    "Preview"
]


class ScriptInfo:
    """Class containing core information necessary for the encode script."""

    file: SPath
    """Path to the current work file."""

    src: src_file
    """The working source file object."""

    clip_cut: vs.VideoNode | tuple[vs.VideoNode]
    """The work clip with trimming applied. Can also be a list in case of prefilter shenanigans."""

    render: bool = False
    """Whether the script is currently being rendered."""

    show_title: str = "Unknown Title"
    """Title of the show, based off of the filename by default."""

    ep_num: str | int = 1
    """Number of the current episode. Can also be a string (for OVAs and the like)."""

    sc_path: SPath
    """Path to the scenechange file. This gets used for previewing and passed as a qp file later on."""

    sc_lock_file: SPath
    """A lock file for scenechange generation."""

    sc_force: bool = False
    """Whether to force scenechange generation."""

    tc_path: SPath | None = None
    """Path to an optional timecode file."""

    dryrun: bool = False
    """Whether this is a dryrun, only meant for testing."""

    def __init__(
        self, caller: str | None = None,
        show_title: str | None = None,
        ep_num: str | int | None = None,
        dryrun: bool = False
    ) -> None:
        from vspreview import is_preview

        if caller is None:
            caller = inspect.stack()[1].filename

        self.dryrun = dryrun

        self.render = not is_preview()

        # if self.render:
        if True:
            self.start_time = time()

        self.file = SPath(caller)

        split = SPath(self.file).stem.split('_') if '_' in caller else (SPath(caller).stem, '')

        self.show_title = show_title or split[0]
        self.ep_num = ep_num or split[1]

        self.sc_path = SPath(f".vspreview/scenechanges/{self.file.stem}_scening.txt")
        self.sc_lock_file = SPath(f".vspreview/scenechanges/{self.file.stem}_scening.lock")

        tc_path = SPath(f"_assets/{self.file.stem}_timecodes.txt")

        if tc_path.exists():
            self.tc_path = tc_path

    def index(
        self, path: SPathLike, trim: TrimAuto | int | None = None,
        name: str | None = None, force_dgi: bool = True
    ) -> vs.VideoNode:
        """Index the given file. Returns a tuple containing the `src_file` object and the `init_cut` node."""
        from vssource import DGIndexNV

        from .misc import get_post_trim, get_pre_trim

        self.src_file = SPath(path)

        if trim is None:
            trim = (None, None)
        elif any(isinstance(x, str) for x in trim):
            trim_pre, trim_post = trim

            if trim_pre == "auto":
                trim_pre = get_pre_trim(self.src_file, self.sc_path, self.sc_lock_file)

                self.sc_lock_file.touch(exist_ok=True)
            if trim_post == "auto":
                trim_post = get_post_trim(self.src_file, self.sc_path, self.sc_lock_file)

            self.sc_lock_file

            trim = (trim_pre, trim_post)
        elif isinstance(trim, int):
            trim = (trim, -trim)

        if force_dgi and not self.src_file.to_str().endswith(".dgi"):
            try:
                dgi = DGIndexNV().index([self.src_file.absolute()], False, False, None, "-a")[0]
            except (Exception, vs.Error) as e:
                Log.warn(f"Some kind of error ocurred!", self.index)  # type:ignore[arg-type]

                raise e

            self.src_file = dgi

        self.src = src_file(self.src_file.to_str(), trim=trim)
        self.clip_cut = cast(vs.VideoNode, self.src.init_cut()).std.SetFrameProps(Name="src")

        if name is not None:
            self.clip_cut = self.clip_cut.std.SetFrameProps(Name=name)

        return self.clip_cut

    def setup_muxtools(self, ftp: bool = True, discord: bool = True, **setup_kwargs: Any) -> None:
        """Create the config file for muxtools."""
        from vsmuxtools import Setup

        # TODO: Fix all this
        adjustable_kwargs = dict(
            mkv_title_naming="",  # The mkv title metadata property.
            out_name=f"$show$ - $ep$ (Premux) [$crc32$]"  # Output filename
        )
        adjustable_kwargs |= setup_kwargs

        ini = Setup(
            self.ep_num,  # The episode value.
            show_name=self.show_title,  # The name of the show.
            **adjustable_kwargs  # Optional kwargs.
        )

        ini.edit("show", self.show_title)  # Don't remember why I did this ngl.

        if ftp:
            from .config import Config
            Config.create_ftp_config()

        if discord:
            from .config import Config
            Config.create_discord_config()

    def generate_keyframes(
        self, clip: vs.VideoNode | None = None,
        mode: SceneChangeMode = SceneChangeMode.WWXD,
        force: bool = False,
        height: int = 288, range_conversion: float = 4.0
    ) -> Keyframes:
        """Generate keyframes for the trimmed clip. Returns a Keyframes object."""
        from vsdenoise import prefilter_to_full_range
        from vstools import get_w

        wclip = cast(vs.VideoNode, clip or self.clip_cut)

        if force or self.sc_force:
            self.sc_lock_file.unlink(missing_ok=True)

        if self.sc_path.exists():
            kf = Keyframes.from_file(self.sc_path)

            if self.sc_lock_file.exists() or kf[-1] == wclip.num_frames - 1:
                return kf

            Log.warn(
                f"Scenechanges don't match up with the input clip "
                f"(scenechange file last frame ({kf[-1]}) != work clip last frame ({wclip.num_frames - 1}))! "
                "Regenerating...",
                self.generate_keyframes
            )

        # Prefiltering.
        wclip = ZewiaCubicNew.scale(wclip, get_w(height, wclip), height)
        wclip = prefilter_to_full_range(wclip, range_conversion)

        kf = Keyframes.from_clip(wclip, mode)
        kf.append(wclip.num_frames - 1)

        self.sc_path.parents[0].mkdir(exist_ok=True, parents=True)

        kf.to_file(self.sc_path, force=True, func=self.generate_keyframes)

        return kf

    def replace_prefilter(
        self, prefilter: vs.VideoNode | tuple[vs.VideoNode],
        force: bool = False
    ) -> vs.VideoNode:
        """Replace the clip_cut attribute with a prefiltered clip. Useful for telecined clips."""
        if isinstance(prefilter, (tuple, list)):
            prefilter = tuple([self.clip_cut] + list(prefilter))  # type:ignore[assignment]

        self.clip_cut = prefilter

        if force:
            self.sc_force = force

        # Check whether sc_path exists, and remove if the last keyframe exceeds the prefiltered clip's total frames.
        if self.sc_path.exists() and isinstance(self.clip_cut, vs.VideoNode) and not self.sc_lock_file.exists():
            assert isinstance(self.clip_cut, vs.VideoNode)  # typing

            if Keyframes.from_file(self.sc_path)[-1] > prefilter.num_frames:  # type:ignore[union-attr]
                Log.warn("Prefilter passed but keyframes don't match! Regenerating...", self.replace_prefilter)
                self.sc_path.unlink(missing_ok=True)

            self.generate_keyframes(prefilter)  # type:ignore[arg-type]

            self.sc_lock_file.touch(exist_ok=True)

            with open(self.sc_lock_file, "w") as f:
                f.write(
                    f"This is a lock file for \"{self.sc_path.name}\".\n"
                    "To regenerate the scenechange file, delete this lock file!\n"
                )

        return prefilter  # type:ignore[return-value]

    def unsupported_call(self, caller: str) -> None:
        """Called when the user is trying to run a script through unsupported methods."""
        from vstools import CustomRuntimeError

        if not self.render:
            return

        if caller in ("__main__", "__vapoursynth__"):
            return

        sys.tracebacklimit = 0

        Log.error(
            "You are trying to run this script in a way that is not supported! Aborting...",
            SPath(__name__).name, CustomRuntimeError  # type:ignore[arg-type]
        )

        exit()

    def elapsed_time(self, func: str | Callable[[Any], Any] | None = None) -> timedelta:
        """Get the elapsed time in seconds."""
        from vstools import CustomValueError

        if not hasattr(self, "start_time"):
            raise CustomValueError("Missing attribute!", self.elapsed_time, "start_time")

        elapsed = time() - self.start_time
        delta = timedelta(seconds=elapsed)

        if elapsed > 60:
            prt_elapsed = str(delta)  # type:ignore
        else:
            prt_elapsed = str(elapsed)

        Log.info(f"Elapsed time: {prt_elapsed}", func or self.elapsed_time)  # type:ignore[arg-type]

        self.end_time = elapsed

        return delta

    def discord_start(self, **kwargs: Any) -> None:
        """Run this when the script is starting."""
        from .config import Config

        auth = Config.auth_config

        if not auth.has_section("DISCORD"):
            return

        if not auth.has_option("DISCORD", "webhook"):
            return

        wh_args = dict(
            show_name=self.show_title, ep_num=self.ep_num,
            username=auth.get("DISCORD", "name", fallback="EncodeRunner"),
            author="System: " + auth.get("DISCORD", "user", fallback=os.getlogin() or os.getenv("username")),
            avatar=auth.get("DISCORD", "avatar", fallback="https://avatars.githubusercontent.com/u/88586140"),
            webhook_url=auth.get("DISCORD", "webhook"),
            title="{show_name} {ep_num} has started encoding!",
        )

        wh_args |= kwargs

        if not self.dryrun:
            notify_webhook(**wh_args)

    def discord_failed(
        self, exception: Exception | str | None = None,
        footer: int | dict[str, str] | None = None,
        **kwargs: Any
    ) -> None:
        """Run this when the script has failed."""
        from .config import Config

        auth = Config.auth_config

        if not auth.has_section("DISCORD"):
            return

        if not auth.has_option("DISCORD", "webhook"):
            return

        if isinstance(exception, KeyboardInterrupt):
            exception = "The encode was manually interrupted!"

        # TODO: Add more
        footers = [
            {
                "text": "Aww, shucks...",
                "icon_url": "https://archives.bulbagarden.net/media/upload/7/73/MDP_E_213.png"
            },
            {
                "text": "EVERYTHING IS ON FIIIREEEEEE!!!",
                "icon_url": "https://i.imgur.com/wwZn1UR.png"
            },
        ]

        if isinstance(footer, int):
            footers = footers[footer]
        elif isinstance(footer, (list, dict)):
            footers = footer

        wh_args = dict(
            show_name=self.show_title, ep_num=self.ep_num,
            username=auth.get("DISCORD", "name", fallback="EncodeRunner"),
            author="System: " + auth.get("DISCORD", "user", fallback=os.getlogin() or os.getenv("username")),
            avatar=auth.get("DISCORD", "avatar", fallback="https://avatars.githubusercontent.com/u/88586140"),
            webhook_url=auth.get("DISCORD", "webhook"),
            title="{show_name} {ep_num} has failed during encoding!",
            description="{exception}",
            exception=exception or "Please consult the stacktrace on the system your encode ran on",
            color="12582912",
            footer=footers
        )

        wh_args |= kwargs

        if not self.dryrun:
            notify_webhook(**wh_args)
        elif exception:
            raise Log.error(exception)

    def discord_ok(self, **kwargs: Any) -> None:
        """Run this when the script has finished without error."""
        from .config import Config

        auth = Config.auth_config

        if not auth.has_section("DISCORD"):
            return

        if not auth.has_option("DISCORD", "webhook"):
            return

        if not kwargs.get("description", False):
            kwargs["description"] = ""

        # if kwargs.get("premux", {}).get("filesize", False):
        #     filesize_dict = dict(kwargs["premux"]["filesize"])
        #     byte_size = filesize_dict.get("bytes", 0)

        #     if byte_size > 2.56e+11:
        #         unit, filesize = ("tb", filesize_dict["tb"])
        #     elif byte_size > 1e+9:
        #         unit, filesize = ("gb", filesize_dict["gb"])
        #     else:
        #         unit, filesize = ("mb", filesize_dict["mb"])

        #     kwargs["description"] += f"\nFilesize: {filesize}{unit}"

        if kwargs.get("elapsed_time", False):
            elapsed_time = self.strfdelta(self.elapsed_time())

            kwargs["description"] += f"\nEncoding time: {elapsed_time}"

            if hasattr(self, "end_time"):
                kwargs["description"] += f" ({self._calc_fps(self.clip_cut, self.end_time):.2f} fps)"

        wh_args = dict(
            show_name=self.show_title, ep_num=self.ep_num,
            username=auth.get("DISCORD", "name", fallback="EncodeRunner"),
            author="System: " + auth.get("DISCORD", "user", fallback=os.getlogin() or os.getenv("username")),
            avatar=auth.get("DISCORD", "avatar", fallback="https://avatars.githubusercontent.com/u/88586140"),
            webhook_url=auth.get("DISCORD", "webhook"),
            title="{show_name} {ep_num} has finished encoding!",
            color="32768"
        )

        wh_args |= kwargs

        if not self.dryrun:
            notify_webhook(**wh_args)

    def upload_to_ftp(self) -> None:
        raise NotImplementedError

    @classmethod
    def strfdelta(cls, tdelta: timedelta, fmt: str = "%H:%M:%S") -> str:
        """Convert a timedelta to a pretty string."""
        return str(tdelta)[:-3]
        # TODO: fix this
        d = {"%D": tdelta.days}
        d["%H"], rem = divmod(tdelta.seconds, 3600)
        d["%M"], d["%S"] = divmod(rem, 60)

        return fmt.format(**d)

    def _calc_fps(self, clip: vs.VideoNode, elapsed_time: float) -> float:
        """Calculate the framerate. We can't get it from the encoder directly it seems, so gotta do it ourselves."""
        return clip.num_frames / elapsed_time


class Preview:
    """Class containing core previewing methods."""

    script_info: ScriptInfo
    """Script info containing the information necessary for previewing."""

    num_outputs = 0
    """Number of output clips"""

    def __init__(self, script_info: ScriptInfo) -> None:
        self.script_info = script_info

    def set_video_outputs(self, clips: vs.VideoNode | tuple[vs.VideoNode, ...]) -> None:
        """Set VideoNode outputs."""
        from vstools import get_prop

        if isinstance(clips, vs.VideoNode):
            clips = [clips]  # type:ignore[assignment]

        for i, clip in enumerate(list(clips), self.num_outputs):  # type:ignore[arg-type]
            try:
                assert isinstance(clip, vs.VideoNode)
            except AssertionError:
                Log.warn(f"Clip {i} was not a VideoNode! Skipping...", self.set_video_outputs)

                continue

            name = get_prop(clip, "Name", bytes, default=False)  # type:ignore[arg-type, assignment]

            if isinstance(name, bytes):
                name = name.decode('utf-8')  # type:ignore[assignment]

            assert isinstance(name, (str, bool))

            Log.debug(
                f"Clip {i} - Name: " + (f'\"{name}\"' if name else "no name set"),
                self.set_video_outputs
            )  # type:ignore[arg-type]

            set_output(clip.std.PlaneStats(), name=name)  # type:ignore[arg-type]

            self.num_outputs += 1

    def set_audio_outputs(self, path: SPathLike | None = None) -> None:
        """Set AudioNode outputs."""
        from vstools import core

        if path is not None:
            audios = [core.bs.AudioSource(SPath(path).to_str())]
        elif self.script_info.file.suffix == ".dgi":
            from .encode import Encoder

            dgi_audio = Encoder(self.script_info).find_audio_files()

            audios = [core.bs.AudioSource(f) for f in dgi_audio]
        else:
            audios = [core.bs.AudioSource(self.script_info.file)]

        set_output(audios)
