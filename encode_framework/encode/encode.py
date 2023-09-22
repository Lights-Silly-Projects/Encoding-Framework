import re
from typing import Any, cast

from vstools import CustomRuntimeError, SPath, SPathLike, finalize_clip, vs, DitherType, depth, get_prop

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

    def mux(self, out_path: SPathLike | None = None, move_once_done: bool = False, lang: str = "ja") -> SPath:
        """Mux the different tracks together."""
        from vsmuxtools import mux  # type:ignore[import]

        if SPath(self.script_info.tc_path).exists():  # type:ignore[arg-type]
            Log.info(f"Timecode file found at \"{self.script_info.tc_path}\"!", self.mux)

        if self.video_container_args:
            mkvmerge_args = " ".join(self.video_container_args)
            lang += f" {mkvmerge_args}"

        video_track = self.video_file.to_track(
            default=True, timecode_file=self.script_info.tc_path, lang=lang.strip()
        )

        Log.info("Merging the following files:", self.mux)
        Log.info(f"   - [VIDEO] {video_track.file}", self.mux)

        if SPath(self.script_info.tc_path).exists():
            Log.info(f"       - [+] Timecodes: {self.script_info.tc_path}", self.mux)

        if self.video_container_args:
            Log.info(f"       - [+] Additional args: \"{mkvmerge_args}\"", self.mux)

        if self.audio_tracks:
            for track in self.audio_tracks:
                Log.info(f"   - [AUDIO] {track.file}", self.mux)

        if self.subtitle_tracks:
            for track in self.subtitle_tracks:
                Log.info(f"   - [SUBTITLES] {track.file}", self.mux)

        if self.chapters:
            Log.info(f"   - [CHAPTERS] {[ch for ch in self.chapters.chapters]}", self.mux)

        self.premux_path = SPath(mux(
            video_track, *self.audio_tracks,
            *self.subtitle_tracks, *self.font_files,
            self.chapters, outfile=out_path
        ))

        Log.info(
            f"Final file \"{self.premux_path.name}\" output to "
            f"\"{self.premux_path.parent / self.premux_path.name}\"!", self.mux
        )

        if move_once_done:
            self.script_info.file = self._move_once_done()

        return self.premux_path

    def _move_once_done(self, dir_name: str = "_done") -> SPath:
        """Move files to a "done" directory once done encoding."""
        out_dir = self.script_info.file.parent / dir_name
        target = out_dir / self.script_info.file.name

        out_dir.mkdir(exist_ok=True)

        if target.exists():
            Log.warn("Target file already exists! Please move this manually...", self._move_once_done)

            return self.script_info.file.parent

        try:
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

            Log.debug(f"Moving old premux \"{pmx.name}\" -> \"{target}\"...", self._move_old_premuxes_once_done)

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

    @property
    def __name__(self) -> str:
        """Hopefully this will shut up Log..."""
        return "Encoder"
