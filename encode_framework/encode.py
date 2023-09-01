from typing import Any, cast

from vstools import CustomRuntimeError, SPath, SPathLike, vs

from .util.logging import Log
from .script import ScriptInfo
from .tracks import _EncodeDiagnostics

__all__: list[str] = [
    "Encoder"
]

# TODO: Rewrite this etnire thing + tracks/*.py

class Encoder(_EncodeDiagnostics):
    """Class containing core encoding methods."""

    def __init__(self, script_info: ScriptInfo, out_clip: vs.VideoNode | None = None, **kwargs: Any) -> None:
        self.script_info = script_info

        if out_clip is None:
            out_clip = self.script_info.clip_cut  # type:ignore[assignment]

        if not isinstance(out_clip, vs.VideoNode):
            raise CustomRuntimeError(
                "Multiple output nodes detected in filterchain! "
                "Please output just one node!", __file__, len(out_clip)  # type:ignore[arg-type]
            )

        assert isinstance(out_clip, vs.VideoNode)

        self.out_clip = cast(vs.VideoNode, out_clip)

        self.video_file = None  # type:ignore

    def pre_encode(self) -> None:
        """Tasks to perform prior to encoding."""

        ...

    def mux(self, out_path: SPathLike | None = None, move_once_done: bool = False, lang: str = "ja") -> SPath:
        """Mux the different tracks together."""
        from vsmuxtools import mux

        if self.script_info.tc_path.exists():
            Log.info(f"Timecode file found at \"{self.script_info.tc_path}\"!", self.mux)

            tc_path = self.script_info.tc_path
        else:
            tc_path = None

        video_track = self.video_file.to_track(default=True, timecode_file=tc_path, lang=lang)

        if Log.is_debug:
            Log.debug("Merging the following files:", self.mux)
            Log.debug(f"   - [VIDEO] {video_track.file}", self.mux)

            if self.audio_tracks:
                for track in self.audio_tracks:
                    Log.debug(f"   - [AUDIO] {track.file}", self.mux)

            if self.subtitle_tracks:
                for track in self.subtitle_tracks:
                    Log.debug(f"   - [SUBTITLES] {track.file}", self.mux)

            if self.chapters:
                Log.debug(f"   - [CHAPTERS] {[ch[1] for ch in self.chapters.chapters]}", self.mux)

        self.premux_path = SPath(mux(
            video_track, *self.audio_tracks, *self.subtitle_tracks,
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

        try:
            self.script_info.file.rename(target)
        except FileNotFoundError as e:
            Log.warn(str(e), self._move_once_done)

        return target

    # TODO:
    def _update_premux_filename(self) -> SPath:
        """Add versioning to premuxes."""
        # base_name = SPath(re.sub(r' \[[0-9A-F]{8}\]', "", self.premux_path.to_str()))
        # found = SPath(self.premux_path.parent).glob(f"{base_name.stem}*.mkv")
        # if len(found) > 1:
        #     ep_num =
        #     self.premux_path

        return SPath()

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
