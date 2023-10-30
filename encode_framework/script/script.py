from __future__ import annotations

import inspect
import sys
from time import time
from typing import Any, cast

from vskernels import Hermite
from vsmuxtools import src_file  # type:ignore[import]
from vstools import CustomValueError, Keyframes, SceneChangeMode, SPath, SPathLike, set_output, vs, normalize_ranges

from ..types import TrimAuto, is_iterable
from ..util import Log, assert_truthy

__all__: list[str] = [
    "ScriptInfo",
    "Preview"
]


class ScriptInfo:
    """Class containing core information necessary for the encode script."""

    file: SPath
    """Path to the current working script file."""

    src_file: list[SPath]
    """A list of paths to the source video file to work from."""

    src: src_file
    """The source video file object."""

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

        self.sc_path = SPath(f"_scenechanges/{self.file.stem}_scening.txt")
        self.sc_lock_file = SPath(f"_scenechanges/{self.file.stem}_scening.lock")

        self.tc_path = SPath(f"_assets/{self.file.stem}_timecodes.txt")

    def index(
        self, path: SPathLike | list[SPathLike], trim: TrimAuto | int | None = None,
        name: str | None = None, force_dgi: bool = True
    ) -> vs.VideoNode:
        """Index the given file. Returns a tuple containing the `src_file` object and the `init_cut` node."""
        from .trim import get_post_trim, get_pre_trim

        if trim and isinstance(trim, list) and all(isinstance(x, tuple) for x in trim):
            if len(trim) > 1:
                Log.warn(f"Multiple trims found! Only grabbing the first ({trim[0][0]} => {trim[0][1]})...")

            trim = trim[0]

        path_is_iterable = is_iterable(path)

        if path_is_iterable and not force_dgi:
            raise CustomValueError("You may only pass a list of files if you set \"force_dgi=True\"!", self.index)
        elif force_dgi:
            path = list(path) if path_is_iterable else [path]
        elif not path_is_iterable:
            path = [path]

        self.src_file = [SPath(p).resolve() for p in path]

        if force_dgi and not self.src_file[0].to_str().endswith(".dgi"):
            from vssource import DGIndexNV

            try:
                self.src_file = DGIndexNV().index(self.src_file, False, False, None, "-a")
            except (Exception, vs.Error) as e:
                raise Log.error(e, self.index)

        if not trim:
            trim = (None, None)
        elif isinstance(trim, int):
            trim = (trim, -trim)
        elif any(isinstance(x, str) for x in trim):
            trim_pre, trim_post = trim

            if str(trim_pre).lower() == "auto":
                trim_pre = get_pre_trim(self.src_file, self.sc_path, self.sc_lock_file)

                self.sc_lock_file.touch(exist_ok=True)
            if str(trim_post).lower() == "auto":
                trim_post = get_post_trim(self.src_file, self.sc_path, self.sc_lock_file)

                self.sc_lock_file.touch(exist_ok=True)

            trim = (trim_pre, trim_post)

            Log.debug(f"New trim: {trim}", self.index)

        if all(isinstance(x, type(None)) for x in trim):
            trim = None


        assert_truthy(is_iterable(self.src_file))

        self.src = src_file(self.src_file[0].to_str(), trim=trim)
        self.clip_cut = cast(vs.VideoNode, self.src.init_cut()).std.SetFrameProps(Name="src")

        self.update_trims(trim)

        if name is not None:
            self.clip_cut = self.clip_cut.std.SetFrameProps(Name=name)

        return self.clip_cut

    def update_trims(self, trim: int | tuple[int, int] | list[int] | None = None) -> tuple[int, int]:
        """Update trims if necessary. Useful for if you adjust the trims during prefiltering."""
        if isinstance(trim, list):
            if any(isinstance(x, tuple) for x in trim):
                trim = trim[0]
            elif len(trim) > 1:
                trim = (trim[0], trim[1])
            # TODO: this one is a bug in wobblyparser. Gotta fix this.
            elif isinstance(trim[0], list):
                trim = (trim[0][0], trim[0][1])
            else:
                trim = tuple(trim)
        elif not isinstance(trim, tuple):
            trim = (trim, trim)

        if any(x is None for x in trim):
            trim = list(trim)

            if trim[0] is None:
                trim[0] = 0  # type:ignore[assignment, index]

            if trim[1] is None:
                trim[1] = self.clip_cut.num_frames + 1  # type:ignore[index]

            trim = tuple(trim)

        if inspect.stack()[1][3] in ("trim"):
            return trim

        trim = normalize_ranges(self.src.src, trim)[0]

        self._trim = trim
        self.src.trim = trim

    @property
    def trim(self) -> tuple[int, int]:
        """The clip trim. Exclusive trim."""
        tr = self._trim

        if tr is None:
            tr = (None, None)
        elif isinstance(tr, list):
            tr = self.update_trims(tr)

        if any(t is None for t in tr):
            if tr[0] is None:
                tr[0] = 0  # type:ignore[assignment, index]

            if tr[1] is None:
                tr[1] = self.clip_cut.num_frames + 1  # type:ignore[index]

        return tuple(tr)

    def update_tc(self, tc_path: SPathLike) -> SPath:
        """Update the timecode properties."""
        tc_loc = SPath(tc_path)

        if not tc_loc.exists():
            raise Log.error(f"The file \"{tc_loc}\" could not be found!", self.update_tc, FileNotFoundError)

        self.tc_path = tc_loc

        return self.tc_path

    def setup_muxtools(self, **setup_kwargs: Any) -> None:
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
        wclip = Hermite.scale(wclip, get_w(height, wclip), height)
        wclip = prefilter_to_full_range(wclip, range_conversion)

        kf = Keyframes.from_clip(wclip, mode)
        kf.append(wclip.num_frames - 1)

        self.sc_path.parent.mkdir(exist_ok=True, parents=True)

        kf.to_file(self.sc_path, force=True, func=self.generate_keyframes)

        return kf

    def replace_prefilter(
        self, prefilter: vs.VideoNode | tuple[vs.VideoNode],
        sc: bool = True, force: bool = False
    ) -> vs.VideoNode:
        """Replace the clip_cut attribute with a prefiltered clip. Useful for telecined clips."""
        if isinstance(prefilter, (tuple, list)):
            prefilter = tuple([self.clip_cut] + list(prefilter))  # type:ignore[assignment]

        self.clip_cut = prefilter

        if force:
            self.sc_force = force

        # Check whether sc_path exists, and remove if the last keyframe exceeds the prefiltered clip's total frames.
        if sc and self.sc_path.exists() and isinstance(self.clip_cut, vs.VideoNode) and not self.sc_lock_file.exists():
            assert isinstance(self.clip_cut, vs.VideoNode)  # typing

            if Keyframes.from_file(self.sc_path)[-1] > prefilter.num_frames:  # type:ignore[union-attr]
                Log.warn("Prefilter passed but keyframes don't match! Regenerating...", self.replace_prefilter)
                self.sc_path.unlink(missing_ok=True)

            self.generate_keyframes(prefilter)
            self._make_sf_lock()
        elif sc and not self.sc_path.exists():
            self.generate_keyframes(prefilter)
            self._make_sf_lock()

        return prefilter  # type:ignore[return-value]

    def _make_sf_lock(self) -> SPath:
        self.sc_lock_file.touch(exist_ok=True)

        with open(self.sc_lock_file, "w") as f:
            f.write(
                f"This is a lock file for \"{self.sc_path.name}\".\n"
                "To regenerate the scenechange file, delete this lock file!\n"
            )

        return self.sc_lock_file

    def unsupported_call(self, caller: str | None = None) -> None:
        """Called when the user is trying to run a script through unsupported methods."""
        from vstools import CustomRuntimeError

        if not self.render:
            return

        if caller is None:
            caller = inspect.stack()[1].filename

        if caller in ("__main__", "__vapoursynth__"):
            return

        sys.tracebacklimit = 0

        Log.error(
            "You are trying to run this script in a way that is currently not supported! Aborting...",
            SPath(__name__).name, CustomRuntimeError  # type:ignore[arg-type]
        )

        exit()


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

            name = get_prop(clip, "Name", bytes, default=False, func=self.set_video_outputs)  # type:ignore[arg-type, assignment]

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
            from ..encode import Encoder

            dgi_audio = Encoder(self.script_info).find_audio_files()

            audios = [core.bs.AudioSource(f) for f in dgi_audio]
        else:
            audios = [core.bs.AudioSource(self.script_info.file)]

        set_output(audios)
