import re
from typing import Any, cast

from vstools import FuncExceptT, FuncExceptT, CustomRuntimeError, SPath, SPathLike, get_prop, vs
from muxtools import VideoTrack, get_setup_attr

from ..script import ScriptInfo
from ..util import Log
from .audio import _AudioEncoder
from .chapters import _Chapters
from .subtitles import _Subtitles
from .video import _VideoEncoder

__all__: list[str] = [
    "Encoder"
]

# TODO: Rewrite this entire thing + tracks/*.py


class Encoder(_AudioEncoder, _Chapters, _Subtitles, _VideoEncoder):
    """Class containing core encoding methods."""

    def __init__(self, script_info: ScriptInfo, out_clip: vs.VideoNode | None = None, **kwargs: Any) -> None:
        self.script_info = script_info

        oclip = out_clip or self.script_info.clip_cut

        if not isinstance(oclip, vs.VideoNode):
            raise CustomRuntimeError(
                "Multiple output nodes detected in filterchain! "
                "Please output just one node!", __file__, len(oclip)  # type:ignore[arg-type]
            )

        assert isinstance(oclip, vs.VideoNode)

        self.out_clip = cast(vs.VideoNode, oclip)

        self.video_file = None  # type:ignore

    def pre_encode(self) -> None:
        """Tasks to perform prior to encoding."""

        ...

    def mux(
        self, out_path: SPathLike | None = None,
        move_once_done: bool = False, lang: str = "ja",
        crop: int | tuple[int, int] | tuple[int, int, int, int] | None = None,
        *args: Any
    ) -> SPath:
        """
        Mux the different tracks together.

        :param out_path:            Path to output the muxed file to.
        :param move_once_done:      Move the python script once muxing is done.
        :param lang:                Language of the video track.
        :param crop:                Container cropping. Useful for anamorphic resolutions
                                    and consistency in the event you may want to regularly crop a video.
                                    If None, checks the output clip for "_SARLeft", "_SARRight", etc. props.
        :param args:                Additional arguments to pass on to mkvmerge.
        """
        from vsmuxtools import mux  # type:ignore[import]

        if self.script_info.tc_path.exists():  # type:ignore[arg-type]
            Log.info(f"Timecode file found at \"{self.script_info.tc_path}\"!", self.mux)

        tc_file = self.script_info.tc_path if self.script_info.tc_path.exists() else None

        crop = self._get_crop_args(crop)

        self.video_track = self.video_file.to_track(
            default=True, timecode_file=tc_file, lang=lang.strip(), crop=crop, *args
        )

        self._mux_logs(crop)

        self.premux_path = SPath(mux(
            self.video_track, *self.audio_tracks,
            *self.subtitle_tracks, *self.font_files,
            self.chapters, outfile=out_path,
            print_cli=True
        ))

        # self.fix_filename()

        Log.info(
            f"Final file \"{self.premux_path.name}\" output to "
            f"\"{self.premux_path.parent / self.premux_path.name}\"!", self.mux
        )

        if move_once_done:
            self.script_info.file = self._move_once_done()

        self._warn_if_path_too_long(self.mux)

        return self.premux_path

    def _get_crop_args(
        self, crop: tuple[int, int] | tuple[int, int, int, int] | None = None
    ) -> tuple[int, int] | tuple[int, int, int, int] | None:
        if crop is not None:
            return crop

        _l = get_prop(self.out_clip, "_SARLeft", int, None, 0, self.mux)
        _r = get_prop(self.out_clip, "_SARRight", int, None, 0, self.mux)
        _t = get_prop(self.out_clip, "_SARTop", int, None, 0, self.mux)
        _b = get_prop(self.out_clip, "_SARBottom", int, None, 0, self.mux)

        if any([_l, _r, _t, _b]):
            crop = (_l, _t, _r, _b)

        return crop

    def _mux_logs(
        self,
        crop: tuple[int, int] | tuple[int, int, int, int] | None,
    ) -> None:
        track_args = f"{self.video_track.default=}, {self.video_track.forced=}, {self.video_track.name=}, "
        track_args += f"{self.video_track.lang=}, {self.video_track.delay=}"

        Log.info("Merging the following files:", self.mux)
        Log.info(f"   - [VIDEO] \"{self.video_track.file}\" ({track_args})", self.mux)

        if self.script_info.tc_path.exists():
            Log.info(f"       - [+] Timecodes: \"{self.script_info.tc_path}\"", self.mux)

        if crop is not None:
            Log.info(f"       - [+] Container cropping: \"{crop}\"", self.mux)

        if self.video_container_args:
            Log.info(f"       - [+] Additional args: \"{" ".join(self.video_container_args)}\"", self.mux)

        if self.audio_tracks:
            for track in self.audio_tracks:
                track_args = f"{track.default=}, {track.forced=}, {track.name=}, {track.lang=}, {track.delay=}"
                Log.info(f"   - [AUDIO] \"{track.file}\" ({track_args})", self.mux)

        if self.subtitle_tracks:
            for track in self.subtitle_tracks:
                track_args = f"{track.default=}, {track.forced=}, {track.name=}, {track.lang=}, {track.delay=}"
                Log.info(f"   - [SUBTITLES] \"{track.file}\" ({track_args})", self.mux)

        if self.chapters:
            Log.info(f"   - [CHAPTERS] {[f'{ch[1]} ({ch[0]})' for ch in self.chapters.chapters]}", self.mux)

    def _move_once_done(self, dir_name: str = "_done") -> SPath:
        """Move files to a "done" directory once done encoding."""
        out_dir = self.script_info.file.parent / dir_name
        target = out_dir / self.script_info.file.name

        out_dir.mkdir(exist_ok=True)

        if target.exists():
            Log.warn("Target file already exists! Please move this manually...", self._move_once_done)

            return self.script_info.file.parent

        try:
            Log.debug(f"\"{self.script_info.file}\" --> \"{target}\"", self._move_once_done)
            return self.script_info.file.rename(target)
        except Exception as e:
            Log.error(str(e), self._move_once_done)

        return self.script_info.file

    def _move_old_premuxes_once_done(self, dir_name: str = "_old") -> list[SPath]:
        out_dir = self.premux_path / dir_name
        targets: list[SPath] = []

        premux_path_no_crc = re.sub(r"\s?\[[0-f]{8}\]*", r"", self.premux_path.name)

        for pmx in self.premux_path.parent.glob(f"{premux_path_no_crc}*.mkv"):
            if pmx == self.premux_path:
                continue

            target = out_dir / pmx.name

            Log.debug(f"\"{pmx.name}\" --> \"{target}\"", self._move_old_premuxes_once_done)

            pmx.rename(target)

            if target.exists():
                targets += [target]

        return targets

    # TODO: Read show title from config, check ep num matches, auto-add version numbers.
    # def _update_premux_filename(self) -> SPath:
    #     """Add versioning to premuxes."""
    #     encodes = SPath(self.premux_path.parent) \
    #         .glob(f"{self.script_info}*.mkv")

    #     if len(encodes):
    #         self.premux_path

    #     return SPath()

    def clean_workdir(self) -> None:
        from vsmuxtools import clean_temp_files

        clean_temp_files()

        if self.lossless_path and self.lossless_path.exists():
            self.lossless_path.unlink(missing_ok=True)

    def prepare_vspipe(self, out_clip: vs.VideoNode | None = None) -> None:
        from vstools import finalize_clip, set_output

        final_clip = out_clip or self.out_clip

        if not isinstance(final_clip, vs.VideoNode):
            Log.error(
                f"Input script has multiple output nodes ({len(final_clip)})! Please output a single node!",
                self.prepare_vspipe, tb_limit=1
            )

        final_clip = finalize_clip(final_clip)

        set_output(final_clip)

    def move_nc_to_extras_dir(self, dir_out: str = "Extras") -> SPath:
        """For moving NCs to an extras directory."""
        if "NC" not in str(self.script_info.ep_num):
            return self.premux_path

        if not (nc_dir := self.premux_path.parent / dir_out).exists():
            nc_dir.mkdir(exist_ok=True)

        nc_out = nc_dir / self.premux_path.name

        Log.info(f"Moving NC file: \"{self.premux_path}\" --> \"{nc_out}\"", self.mux)

        self.premux_path = self.premux_path.rename(nc_out)

        self._warn_if_path_too_long(self.move_nc_to_extras_dir)

        return self.premux_path

    def move_specials_to_specials_dir(self, dir_out: str = "Specials") -> SPath:
        """For moving NCs to an extras directory."""
        if not any(x in str(self.script_info.ep_num) for x in ("Movie", "MV", "ONA", "OVA", "S00", "SP")):
            return self.premux_path

        if not (sp_dir := self.premux_path.parent / dir_out).exists():
            sp_dir.mkdir(exist_ok=True)

        sp_out = sp_dir / self.premux_path.name

        Log.info(f"Moving Special: \"{self.premux_path}\" --> \"{sp_out}", self.mux)

        self.premux_path = self.premux_path.rename(sp_out)

        self._warn_if_path_too_long(self.move_specials_to_specials_dir)

        return self.premux_path

    def fix_filename(self, fallback: Any = None) -> SPath:
        """For some reason my output filenames are fucked, but only for $show_name$. idk why. This fixes that."""

        if "$show_name$" not in self.premux_path.to_str():
            return self.premux_path

        show_name = get_setup_attr("show_name", fallback)
        eng_show_name = get_setup_attr("show_name_eng", show_name)
        group = get_setup_attr("group", "")

        for key, val in {"show_name": show_name, "eng_show_name": eng_show_name, "group": group}:
            self.premux_path.name.replace(f"${key}$", val)

        new_name = self.premux_path.parent / SPath()

        Log.info(f"Renaming \"{self.premux_path.name}\" --> \"{new_name}\"", self.fix_filename)
        self.premux_path = SPath(self.premux_path).replace(new_name)

        self._warn_if_path_too_long(self.fix_filename)

        return self.premux_path

    def _warn_if_path_too_long(self, func_except: FuncExceptT | None = None) -> bool:
        """Logs a warning if the premux path is too long, but only once."""

        func = func_except or self._warn_if_path_too_long

        if not getattr(self, "_path_too_long"):
            self._path_too_long = False

        if self._path_too_long:
            return self._path_too_long

        if len(str(self.premux_path)) > 255:
            Log.warn("Output path is too long! Please move this file...", func)

            self._path_too_long = True

        return self._path_too_long

    @property
    def __name__(self) -> str:
        """Hopefully this will shut up Log..."""
        return "Encoder"
