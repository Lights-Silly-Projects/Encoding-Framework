import re
from typing import Any, Literal, cast

from vsmuxtools import AudioTrack, Chapters
from vsmuxtools import Encoder as AudioEncoder  # type:ignore[import]
from vsmuxtools import FFMpeg, HasTrimmer, VideoFile, ensure_path, qAAC, x265
from vsmuxtools.video.encoders import SupportsQP  # type:ignore[import]
from vstools import CustomRuntimeError, FileNotExistsError, FileType, SPath, SPathLike, vs, CustomValueError

from .logging import Log
from .script import ScriptInfo

__all__: list[str] = [
    "Zones",
    "Encoder"
]


Zones = list[tuple[int, int, float]]
"""List of tuples containing zoning information (start, end, bitrate multiplier)."""


class Encoder:
    """Class containing core encoding methods."""

    script_info: ScriptInfo
    """Script info containing additional information necessary for encoding."""

    out_clip: vs.VideoNode
    """Clip to output."""

    video_file: VideoFile
    """The encoded video file."""

    audio_files: list[SPath] = []
    """A list of all audio source files."""

    audio_tracks: list[AudioTrack] = []
    """A list of all audio tracks."""

    chapters: Chapters | None = None
    """Chapters obtained from the m2ts playlist or elsewhere."""

    premux_path: SPath
    """The path to the premux."""

    lossless_path: SPath
    """Path to a lossless intermediary encode."""

    def __init__(self, script_info: ScriptInfo, out_clip: vs.VideoNode | None = None, **kwargs: Any) -> None:
        self.script_info = script_info

        if out_clip is None:
            out_clip = self.script_info.clip_cut  # type:ignore[assignment]

        assert isinstance(out_clip, vs.VideoNode)

        if not isinstance(out_clip, vs.VideoNode):
            raise CustomRuntimeError(
                "Multiple output nodes detected in filterchain! "
                "Please output just one node!", __file__, len(out_clip)  # type:ignore[arg-type]
            )

        self.out_clip = self._finalize_clip(out_clip, **kwargs)  # type:ignore[arg-type]

        self.video_file = None  # type:ignore

    def _finalize_clip(self, clip: vs.VideoNode, **kwargs: Any) -> vs.VideoNode:
        """Perform finalization on the out clip."""
        from vstools import finalize_clip

        return finalize_clip(clip, **kwargs)

    def pre_encode(self) -> None:
        """Tasks to perform prior to encoding."""

        ...

    def get_chapters(self, force: bool = False, **kwargs: Any) -> Chapters:
        """Create chapter objects if chapter files exist."""
        from vsmuxtools import frame_to_timedelta

        if any(str(self.script_info.ep_num).startswith(x) for x in ["NC", "OP", "ED", "EP", "MV"]):
            if not force:
                Log.debug(
                    "Not grabbing chapters as this is not an episode! Set \"force=True\" to force chapters.",
                    self.get_chapters
                )

                return Chapters((frame_to_timedelta(0), None))
            else:
                Log.warn("Not an episode, but \"force=True\" was set!", self.get_chapters)

        self.chapters = Chapters(self.script_info.src, **kwargs)

        return self.chapters

    def find_audio_files(self, dgi_path: SPathLike | None = None) -> list[SPath]:
        """
        Find accompanying DGIndex(NV) demuxed audio tracks.

        If no demuxed tracks can be found, it will instead check if the source video is an m2ts file.
        If it is, it will try to extract those audio tracks and return those.
        If input file is not a dgi file, it will throw an error.
        """
        if dgi_path is not None:
            dgi_file = SPath(dgi_path)
        else:
            dgi_file = self.script_info.src_file

        if not dgi_file.to_str().endswith(".dgi"):
            Log.debug("Trying to pass a non-dgi file! Figuring out an audio source...", self.find_audio_files)

            try:
                FileType.AUDIO.parse(dgi_file, func=self.find_audio_files)
                audio_files = [dgi_file]
            except (AssertionError, ValueError):
                pass

            try:
                FileType.VIDEO.parse(dgi_file, func=self.find_audio_files)

                audio_files = [FFMpeg().Extractor().extract_audio(dgi_file)]
            except (AssertionError, ValueError):
                pass
        else:
            Log.debug("DGIndex(NV) input found! Trying to find audio tracks...", self.find_audio_files)

            audio_files: list[SPath] = []

            for f in dgi_file.parent.glob(f"{dgi_file.stem}*.*"):
                try:
                    FileType.AUDIO.parse(f, func=self.find_audio_files)
                except (AssertionError, ValueError):
                    continue

                audio_files += [f]

        if audio_files:
            Log.info(f"The following audio sources were found ({len(audio_files)}):")

            for f in audio_files:
                try:
                    Log.info(f"    - \"{f.file}\"")
                except (AttributeError, ValueError) as e:
                    Log.warn(f"    - Unknown track!\n{e}")

            self.audio_files = audio_files

            return audio_files

        return []

    def _find_m2ts_audio(self, dgi_file: SPath) -> list[SPath]:
        from vsmuxtools import parse_m2ts_path

        Log.debug("No audio tracks could be found! Trying to find the source file...", self.find_audio_files)

        m2ts = parse_m2ts_path(dgi_file)

        if str(m2ts).endswith('.dgi'):
            Log.debug("No m2ts file found! Not encoding any audio...", self.find_audio_files)

            return []

        Log.debug(f"Source file found at \"{str(m2ts)}\"", self.find_audio_files)

        return self._extract_tracks(m2ts)

    def _extract_tracks(self, video_file: SPath) -> list[SPath]:
        """Extract tracks if a video file is passed."""
        from pymediainfo import MediaInfo, Track  # type:ignore[import]

        video_file = SPath(video_file)

        if not video_file.exists():
            Log.error(
                f"The given file could not be found!", self._extract_tracks,
                FileNotExistsError, reason=video_file.to_str()  # type:ignore[arg-type]
            )

        mi = MediaInfo.parse(video_file)

        atracks = list[AudioTrack]()
        _track = -1

        for track in mi.tracks:
            assert isinstance(track, Track)

            if track.track_type == 'Audio':
                _track += 1

                atracks += [
                    FFMpeg.Extractor(_track if track is None else int(track.to_data().get("stream_identifier", _track)))
                    .extract_audio(video_file)
                ]

        return atracks

    def encode_audio(
        self,
        audio_file: SPath | list[SPath] | None = None,
        trims: list[tuple[int, int]] | None = None,
        reorder: list[int] | Literal[False] = False,
        ref: vs.VideoNode | None = None,
        encoder: AudioEncoder = qAAC,
        trimmer: HasTrimmer | None | Literal[False] = None,
        force: bool = False,
        verbose: bool = False,
        **track_args: Any
    ) -> list[AudioTrack]:
        """
        Encode the audio tracks.

        :param audio_file:      ath to an audio file. If none, checks object's audio files.
        :param trims:           Audio trims. If None or empty list, do not trim.
                                If True, use trims passed in ScriptInfo.
        :param reorder:         Reorder tracks. For example, if you know you have 3 audio tracks
                                ordered like [JP, EN, "Commentary"], you can pass [1, 0, 2]
                                to reorder them to [EN, JP, Commentary].
                                This can also be used to remove specific tracks.
        :param ref:             Reference VideoNode for framerate and max frame number information.
                                if None, gets them from the source clip pre-trimming.
        :param encoder:         Audio encoder to use. If the audio file is lossy, it will NEVER re-encode it!
        :param trimmer:         Trimmer to use for trimming. If False, don't trim at all.
                                If None, automatically determine the trimmer based on input file.
        :param verbose:         Enable more verbose output.
        :param force:           Force the audio files to be re-encoded, even if they're lossy.
                                I'm aware I said it would never re-encode it.
        :param track_args:      Keyword arguments for the track.
        """
        import shutil
        from itertools import zip_longest

        from vsmuxtools import FLAC, AudioFile, Sox, is_fancy_codec, make_output

        if all(not afile for afile in (audio_file, self.audio_files)):
            Log.warn("No audio tracks found to encode...", self.encode_audio)

            return []

        if audio_file is not None and audio_file:
            if not isinstance(audio_file, list):
                audio_file = [SPath(audio_file)]

        process_files = audio_file or self.audio_files

        wclip = ref or self.script_info.src.src

        if trims is None:
            trims = [self.script_info.src.trim]

        if reorder:
            if len(reorder) > len(process_files):
                reorder = reorder[:len(process_files)]

            process_files = [process_files[i] for i in reorder]

        codec = self._get_audio_codec(encoder)
        encoder = encoder() if callable(encoder) else encoder

        trimmer_kwargs = dict(
            fps=wclip.fps,
            num_frames=wclip.num_frames
        )

        # TODO: Figure out how much I can move out of this for loop.
        for i, (audio_file, trim) in enumerate(zip_longest(process_files, trims, fillvalue=trims[-1])):
            Log.debug(f"Processing audio track {i + 1}/{len(process_files)}...", self.encode_audio)

            trimmed_file = make_output(str(audio_file), codec, f"trimmed_{codec}")
            trimmed_file = SPath("_workdir") / re.sub(r"\s\(\d+\)", "", trimmed_file.name)

            # Delete temp dir to minimise random errors.
            if SPath(trimmed_file.parent / ".temp").exists():
                shutil.rmtree(trimmed_file.parent / ".temp")

            if trims and trimmed_file.exists():
                Log.debug(f"Trimmed file found at \"{trimmed_file}\"! Skipping encoding...")

                self.audio_tracks += [
                    AudioFile.from_file(trimmed_file, self.encode_audio).to_track(default=not bool(i), **track_args)
                ]

                continue

            afile = AudioFile.from_file(audio_file, self.encode_audio)
            afile_copy = afile.file.with_suffix(".acopy")
            afile_old = afile.file

            try:
                FileType.AUDIO.parse(afile_old, func=self.encode_audio)
                is_audio_file = True
            except (AssertionError, ValueError):
                is_audio_file = False

            if is_audio_file and not afile_copy.exists():
                # vsmuxtools, at the time of writing, deletes the original audio files if you pass an external file.
                Log.debug(f"Copying audio file \"{afile.file.name}\" (this is a temporary workaround)!")

                afile_copy = shutil.copy(afile.file, afile_copy)

            is_lossy = False if force else afile.is_lossy()

            if trims and trimmer is not False:
                trimmer_obj = trimmer or (FFMpeg.Trimmer if is_lossy else Sox)
                trimmer_obj = trimmer_obj(**trimmer_kwargs)

                setattr(trimmer_obj, "trim", trim)

                if str(afile.file).endswith(".w64") or (force and afile.is_lossy()):
                    Log.debug("Audio files has w64 extension, creating an intermediary encode...", self.encode_audio)

                    afile = FLAC(compression_level=0, dither=False).encode_audio(afile)

                afile = trimmer_obj.trim_audio(afile)

            if is_lossy:
                Log.warn("Input audio is lossy. Not re-encoding...", self.encode_audio, 1)
                encoder = None
            elif is_fancy_codec(afile.get_mediainfo()):
                Log.warn("Audio contain Atmos or special DTS features. Not re-encoding...", self.encode_audio, 1)

            if encoder:
                setattr(encoder, "output", None)
                encoded = encoder.encode_audio(afile, verbose)
                ensure_path(afile.file, self.encode_audio).unlink(missing_ok=True)
                afile = encoded

            if not SPath(afile_old).exists():
                SPath(afile_copy).replace(afile_old)

            self.audio_tracks += [afile.to_track(default=not bool(i), **track_args)]

        return self.audio_tracks

    def encode_video(
        self,
        input_clip: vs.VideoNode | None = None,
        output_clip: vs.VideoNode | None = None,
        zones: Zones = [],
        qpfile: SPathLike | bool = True,
        settings: SPathLike = "_settings/{encoder}_settings",
        lossless: bool = False,
        encoder: SupportsQP = x265,
    ) -> VideoFile:
        """
        Encode the video node.

        :param zones:               Zones for the encoder.
        :param qpfile:              qpfile for the encoder. A path must be passed.
                                    If False, do not use a qpfile at all.
        :param settings:            Settings file. By default, tries to find a settings file using the encoder's name.
        :param lossless:            Whether to run a lossless encode prior to the regular encode.
        :param encoder:             The lossy encoder to use. Default: x265.
        :param lossless_encoder:    The lossless encoder to run.

        :return:                    VideoFile object.
        """
        from vsmuxtools import FFV1, LosslessPreset, get_workdir

        if input_clip is None:
            input_clip = self.script_info.clip_cut  # type:ignore[assignment]

        if output_clip is None:
            output_clip = self.out_clip or input_clip

        settings_file = SPath(str(settings).format(encoder=encoder.__name__))

        if not isinstance(output_clip, vs.VideoNode):
            Log.error(
                "Too many output nodes in filterchain function! Please only output one node!",
                self.encode_video, CustomRuntimeError,  # type:ignore[arg-type]
                reason=f"Output nodes: {len(output_clip)}"  # type:ignore[arg-type]
            )

        if lossless:
            from vssource import BestSource

            self.lossless_path = get_workdir() / f"{self.script_info.show_title}_{self.script_info.ep_num}_lossless.mkv"

            if self.lossless_path.exists():
                Log.info(
                    f"Lossless intermediary located at {self.lossless_path}! "
                    "If this encode is outdated, please delete the lossless render!",
                    self.encode_video
                )
            else:
                Log.info("Creating a lossless intermediary...", self.encode_video)

                FFV1(LosslessPreset.COMPRESSION).encode(output_clip, self.lossless_path)

            lossless_clip = BestSource.source(str(self.lossless_path))
            input_clip, output_clip = lossless_clip, lossless_clip

        if qpfile is True and self.script_info.sc_path.exists():
            Log.debug(f"QP file found at \"{self.script_info.sc_path}\"", self.encode_video)

            qpfile = self.script_info.sc_path

        if not settings_file.exists():
            Log.error(
                f"No settings file found at \"{settings_file}\"!",
                self.encode_video, FileNotExistsError  # type:ignore[arg-type]
            )

        self.video_file = encoder(settings_file, zones, qpfile, input_clip) \
            .encode(self._finalize_clip(output_clip))  # type:ignore[arg-type]

        return cast(VideoFile, self.video_file)

    def mux(self, out_path: SPathLike | None = None, move_once_done: bool = False) -> SPath:
        """Mux the different tracks together."""
        from vsmuxtools import mux

        video_track = self.video_file.to_track(default=True, timecode_file=self.script_info.tc_path, lang="")

        if Log.is_debug:
            Log.debug("Merging the following files:", self.mux)
            Log.debug(f"   - [VIDEO] {video_track.file}", self.mux)

            if self.audio_tracks:
                for track in self.audio_tracks:
                    Log.debug(f"   - [AUDIO] {track.file}", self.mux)

            if self.chapters:
                Log.debug(f"   - [CHAPTERS] {self.chapters}", self.mux)

        self.premux_path = SPath(mux(video_track, *self.audio_tracks, self.chapters, outfile=out_path))

        Log.info(f"Final file \"{self.premux_path.name}\" output to \"{self.premux_path}\"!", self.mux)

        if move_once_done:
            self.premux_path = self._move_once_done()

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

    def _get_audio_codec(self, encoder: AudioEncoder) -> str:
        encoder_map = {
            "qaac": "qaac",
            "flac": "libflac",
        }

        codec = encoder_map.get(str(encoder.__name__).lower())

        if not codec:
            Log.error(
                "Unknown codec. Please expand the if/else statement!", self.encode_audio,
                CustomRuntimeError, reason=encoder.__name__  # type:ignore[arg-type]
            )

        return str(codec)

    # TODO:
    def _check_dupe_audio(self, atracks: list[AudioTrack]) -> list[AudioTrack]:
        """
        Compares the hashes of every audio track and removes duplicate tracks.
        Theoretically, if a track is an exact duplicate of another, the hashes should match.
        """

        return []
        ...

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
        from vstools import set_output

        final_clip = out_clip or self.out_clip

        if not isinstance(final_clip, vs.VideoNode):
            Log.error(
                f"Input script has multiple output nodes ({len(final_clip)})! Please output a single node!",
                self.prepare_vspipe, tb_limit=1
            )

        self._finalize_clip(final_clip)

        set_output(final_clip)

    def diagnostics(self, filesize_unit: str = "mb") -> float:
        """
        Print some diagnostic information about the encode.
        """
        pmx_fs = self.get_filesize(self.premux_path)

        if pmx_fs == 0:
            raise Log.error(
                f"Premux is {self._prettystring_filesize(pmx_fs, filesize_unit)}! Please check the file!",
                self.diagnostics, CustomValueError
            )

        Log.info(
            f"The premux has the following filesize: {self._prettystring_filesize(pmx_fs, filesize_unit)}",
            self.diagnostics
        )

        pmx_dir = self.get_dir_filesize(self.premux_path)

        print(pmx_dir > pmx_fs)
        if pmx_dir > pmx_fs:
            Log.info(
                f"The premux directory's filesize is {self._prettystring_filesize(pmx_dir, filesize_unit)}",
                self.diagnostics
            )

        return self.script_info.elapsed_time(self.diagnostics)

    @classmethod
    def get_filesize(cls, file: SPathLike, unit: str = "mb") -> str | float:
        """
        Get the target filesize in the given unit.

        Valid units: ['bytes', 'kb', 'mb', 'gb'].
        """
        exponents = {
            'bytes': 0,
            'kb': 1,
            'mb': 2,
            'gb': 3,
        }

        if unit.lower() not in ['bytes', 'kb', 'mb', 'gb']:
            raise CustomValueError(
                "An invalid unit was passed!", Encoder.get_filesize,
                f"{unit} not in {exponents.keys()}"
            )

        sfile = SPath(file)

        if not sfile.exists():
            raise FileNotExistsError(f"The file \"{sfile}\" could not be found!", Encoder.get_filesize)

        filesize = sfile.stat().st_size / 1024 ** exponents.get(unit, 0)

        return filesize

    @classmethod
    def get_dir_filesize(cls, dir: SPathLike, unit: str = "mb") -> float:
        """
        Get the target directory filesize in the given unit.

        Valid units: ['bytes', 'kb', 'mb', 'gb'].
        """
        sdir = SPath(dir)

        if sdir.is_file():
            sdir = sdir.parent

        filesize = 0

        for f in sdir.glob("*"):
            filesize += Encoder.get_filesize(f, unit)

        return filesize

    @classmethod
    def _prettystring_filesize(cls, filesize: float, unit: str = "mb", rnd: int = 3) -> str:
        """Create a pretty string out of the components for a filesize."""
        return f"{round(filesize, rnd)}{unit}"
