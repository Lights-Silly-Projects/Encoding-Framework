import re
import subprocess
from typing import Any, Literal, cast

from vsmuxtools import AudioFile, AudioTrack, Chapters
from vsmuxtools import Encoder as AudioEncoder  # type:ignore[import]
from vsmuxtools import FFMpeg, HasTrimmer, VideoFile, ensure_path, qAAC, x265
from vsmuxtools.video.encoders import SupportsQP  # type:ignore[import]
from vstools import (CustomError, CustomNotImplementedError, CustomRuntimeError, CustomValueError, FileNotExistsError,
                     FileType, SPath, SPathLike, vs)

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

        # Pre-clean acopy files because it's a pain if you ran this after updating...
        self.__clean_acopy(dgi_file)

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
                    Log.info(f"    - \"{f.name if isinstance(f, SPath) else f.file}\"")
                except (AttributeError, ValueError) as e:
                    Log.warn(f"    - Unknown track!\n{e}")
            self.audio_files += audio_files

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
        audio_file: SPath | list[SPath] | vs.AudioNode | None = None,
        trims: list[tuple[int, int]] | tuple[int, int] | None = None,
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

        :param audio_file:      Path to an audio file or an AudioNode. If none, checks object's audio files.
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

        from vsmuxtools import FLAC, Sox, do_audio, frames_to_samples, is_fancy_codec, make_output

        if all(not afile for afile in (audio_file, self.audio_files)):
            Log.warn("No audio tracks found to encode...", self.encode_audio)

            return []

        is_file = True

        if audio_file is not None and audio_file:
            if isinstance(audio_file, vs.AudioNode):
                audio_file = [audio_file]
            elif not isinstance(audio_file, list):
                audio_file = [SPath(audio_file)]

        if any([isinstance(audio_file, vs.AudioNode)]):
            is_file = False
            Log.warn("AudioNode passed! This may be a buggy experience...", self.encode_audio)

        process_files = audio_file or self.audio_files

        # Remove acopy files first so they don't mess with reorder and stuff.
        if is_file:
            self.__clean_acopy(process_files[0])

        wclip = ref or self.script_info.src.src

        # Normalising trims.
        if trims is None:
            if is_file:
                trims = [self.script_info.src.trim]
            else:
                trims = [(
                    frames_to_samples(self.script_info.src.trim[0]),
                    frames_to_samples(self.script_info.src.trim[1])
                )]
        elif isinstance(trims, tuple):
            trims = [trims]

        # Normalising reordering of tracks.
        if reorder and is_file:
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
            Log.debug(f"Processing audio file \"{audio_file}\"...", self.encode_audio)

            # This is mainly meant to support weird trims we don't typically support and should not be used otherwise!
            if isinstance(audio_file, vs.AudioNode):
                Log.warn("Not properly supported yet! This may fail!", self.encode_audio, CustomNotImplementedError)

                self.audio_tracks += [
                    do_audio(audio_file, encoder=encoder)
                    .to_track(default=not bool(i), **track_args)
                ]

                continue

            trimmed_file = make_output(str(audio_file), codec, f"trimmed_{codec}")
            trimmed_file = SPath("_workdir") / re.sub(r"\s\(\d+\)", "", trimmed_file.name)

            # Delete temp dir to minimise random errors.
            if SPath(trimmed_file.parent / ".temp").exists():
                shutil.rmtree(trimmed_file.parent / ".temp")

            # If a trimmed audio file already exists, this means it was likely already encoded.
            if trims and trimmed_file.exists():
                Log.debug(f"Trimmed file found at \"{trimmed_file}\"! Skipping encoding...", self.encode_audio)

                self.audio_tracks += [
                    AudioFile.from_file(trimmed_file, self.encode_audio)
                    .to_track(default=not bool(i), **track_args)
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

            # vsmuxtools, at the time of writing, deletes the original audio files if you pass an external file.
            if is_audio_file and not afile_copy.exists():
                Log.debug(
                    f"Copying audio file \"{afile.file.name}\" "
                    "(this is a temporary workaround)!", self.encode_audio
                )

                afile_copy = shutil.copy(afile.file, afile_copy)

            is_lossy = False if force else afile.is_lossy()

            # Trim the audio file if applicable.
            if trims and trimmer is not False:
                trimmer_obj = trimmer or (FFMpeg.Trimmer if is_lossy else Sox)
                trimmer_obj = trimmer_obj(**trimmer_kwargs)

                setattr(trimmer_obj, "trim", trim)

                if str(afile.file).endswith(".w64") or (force and afile.is_lossy()):
                    Log.debug("Audio file has w64 extension, creating an intermediary encode...", self.encode_audio)

                    afile = FLAC(compression_level=0, dither=False).encode_audio(afile)

                afile = trimmer_obj.trim_audio(afile)

            # Unset the encoder if force=False and it's a specific kind of audio track.
            if is_lossy and force:
                Log.warn("Input audio is lossy, but \"force=True\"...", self.encode_audio, 1)
            elif is_fancy_codec(afile.get_mediainfo()) and force:
                Log.warn("Audio contain Atmos or special DTS features, but \"force=True\"...", self.encode_audio, 1)
            elif is_lossy and not force:
                Log.warn("Input audio is lossy. Not re-encoding...", self.encode_audio, 1)
                encoder = None
            elif is_fancy_codec(afile.get_mediainfo()) and not force:
                Log.warn("Audio contain Atmos or special DTS features. Not re-encoding...", self.encode_audio, 1)
                encoder = None

            if encoder:
                setattr(encoder, "output", None)
                encoded = encoder.encode_audio(afile, verbose)
                ensure_path(afile.file, self.encode_audio).unlink(missing_ok=True)
                afile = encoded

            # Move the acopy to the original position if muxtools Thanos snapped it.
            if not SPath(afile_old).exists():
                afile_copy.replace(afile_old)
                afile_copy.unlink(missing_ok=True)

            self.audio_tracks += [afile.to_track(default=not bool(i), **track_args)]

        # Remove acopy files again so they don't mess up future encodes.
        self.__clean_acopy(afile.file)

        return self.audio_tracks

    def __clean_acopy(self, base_path: SPathLike | AudioFile) -> None:
        """Try to forcibly clean up acopy files so they no longer pollute other methods."""
        from vsmuxtools import GlobSearch

        if isinstance(base_path, AudioFile):
            file = base_path.file

            if isinstance(file, list):
                file = file[0]
            elif isinstance(file, GlobSearch):
                file = list(file)[0]
        else:
            file = base_path

        try:
            for acopy in SPath(file).parent.glob("*.acopy"):
                Log.debug(f"Unlinking file \"{acopy}\"...", self.encode_audio)
                SPath(acopy).unlink(missing_ok=True)
        except Exception as e:
            Log.error(str(e), self.__clean_acopy, CustomValueError)

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

    def diagnostics(
        self, premux_path: SPathLike | None = None,
        filesize_unit: str = "mb", plotbitrate: bool = True
    ) -> dict[str, Any]:
        """
        Print some diagnostic information about the encode.

        Returns an object containing all the diagnostics.
        """
        elapsed_time = self.script_info.elapsed_time(self.diagnostics)

        self.premux_path = premux_path or self.premux_path

        if not self.premux_path.to_str().endswith(".mkv"):
            Log.error(f"Premux \"{self.premux_path.name}\" is not an mkv file!", self.diagnostics)

            return {
                "description": "Given premux file was not an .mkv file... Skipping most diagnostics.",
                "elapsed_time": elapsed_time,
            }

        pmx_fs = self.get_filesize(self.premux_path)

        if pmx_fs == 0:
            raise Log.error(
                f"Premux is {self._prettystring_filesize(pmx_fs, filesize_unit)}! Please check the file!",
                self.diagnostics, CustomValueError
            )

        Log.info(
            f"The premux (\"{self.premux_path.name}\") has the following filesize: "
            f"{self._prettystring_filesize(pmx_fs, filesize_unit)}",
            self.diagnostics
        )

        Log.info("Generating a plot of the bitrate...", self.diagnostics)

        # Try to generate a bitrate plot for further information.
        plot_out_path = SPath(
            self.script_info.file.parent / "_assets" / "bitrate_plots"
            / self.premux_path.with_suffix(".png").name
        )

        if plotbitrate:
            try:
                if not plot_out_path.parent.exists():
                    plot_out_path.parent.mkdir(exist_ok=True, parents=True)

                self.__run_plotbitrate(plot_out_path)
            except BaseException as e:
                Log.error(str(e), self.diagnostics, CustomError)
            finally:
                if plot_out_path.exists():
                    Log.info(f"Plot image exported to \"{plot_out_path}\"!", self.diagnostics)
                else:
                    Log.error(f"Could not export a plot image!", self.diagnostics)

        return {
            "premux": {
                "location": self.premux_path,
                "filesize": {
                    "bytes": self.get_filesize(self.premux_path, "bytes"),
                    "kb": self.get_filesize(self.premux_path, "kb"),
                    "mb": self.get_filesize(self.premux_path, "mb"),
                    "gb": self.get_filesize(self.premux_path, "gb"),
                    "tb": self.get_filesize(self.premux_path, "tb"),
                },
            },
            "elapsed_time": elapsed_time,
            "bitrate_plot_file": plot_out_path if plot_out_path.exists() else None
        }

    def __run_plotbitrate(self, plot_out_path: SPathLike) -> None:
        subprocess.run([
            "plotbitrate", "-o", SPath(plot_out_path).to_str(),
            "-f", "png", "--show-frame-types", self.premux_path
        ])

    @classmethod
    def get_filesize(cls, file: SPathLike, unit: str = "mb") -> str | float:
        """
        Get the target filesize in the given unit.

        Valid units: ['bytes', 'kb', 'mb', 'gb', 'tb', 'pb'].
        """
        units = ['bytes', 'kb', 'mb', 'gb', 'tb', 'pb']

        if unit.lower() not in units:
            raise CustomValueError("An invalid unit was passed!", Encoder.get_filesize, f"{unit} not in {units}")

        sfile = SPath(file)

        if not sfile.exists():
            raise FileNotExistsError(f"The file \"{sfile}\" could not be found!", Encoder.get_filesize)

        return sfile.stat().st_size / (1024 ** units.index(unit))


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
