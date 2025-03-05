import shutil
from typing import Any, Literal, cast

from vsmuxtools import (AudioFile, AudioTrack, AutoEncoder, Encoder, FFMpeg,
                        HasTrimmer, frame_to_ms, get_workdir)
from vstools import (CustomIndexError, CustomNotImplementedError,
                     CustomRuntimeError, CustomValueError, FileNotExistsError,
                     FileType, SPath, SPathLike, vs)

from ..util.logging import Log
from .base import _BaseEncoder

__all__: list[str] = [
    "_AudioEncoder"
]


class _AudioEncoder(_BaseEncoder):
    """Class containing methods pertaining to handling audio encoding."""

    audio_files: list[SPath] = []
    """A list of all audio source files."""

    audio_tracks: list[AudioTrack] = []
    """A list of all audio tracks."""

    def find_audio_files(
        self, dgi_path: SPathLike | None = None,
        reorder: list[int] | Literal[False] = False,
    ) -> list[SPath]:
        """
        Find accompanying DGIndex(NV) demuxed audio tracks.

        If no demuxed tracks can be found, it will instead check if the source video is an m2ts file.
        If it is, it will try to extract those audio tracks and return those.
        If input file is not a dgi file, it will throw an error.
        """

        if isinstance(dgi_path, list):
            dgi_path = dgi_path[0]

        if dgi_path is not None:
            dgi_file = SPath(dgi_path)
        else:
            dgi_file = self.script_info.src_file[0]

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

                audio_files = [SPath(FFMpeg().Extractor().extract_audio(dgi_file).file)]  # type;ignore
            except (AssertionError, ValueError):
                pass
        else:
            Log.debug("DGIndex(NV) input found! Trying to find audio tracks...", self.find_audio_files)

            audio_files: list[SPath] = []  # type:ignore[no-redef]

            # [] and () characters mess up the glob, so replacing them
            search_string = f'*{dgi_file.stem}*.*'.translate(str.maketrans('[]()', '????')).replace('**', '*')

            for f in dgi_file.get_folder().glob(search_string):
                # explicitly ignore certain files; audio.parse seems to count these for some reason?
                if f.suffix.lower() in (".log", ".sup", ".ttf", ".otf", ".ttc", ".wob"):
                    continue

                Log.debug(f"Checking the following file: \"{f.name}\"...", self.find_audio_files)

                try:
                    FileType.AUDIO.parse(f, func=self.find_audio_files)
                except (AssertionError, ValueError) as e:
                    print(e)
                    continue

                audio_files += [f]

        if not audio_files:
            return []

        Log.info(f"The following audio sources were found ({len(audio_files)}):")

        audio_files = sorted(audio_files, key=self.extract_pid)

        if reorder:
            old, new = audio_files, self._reorder(audio_files, reorder)
            Log.info(f"Reordering files! {old=}, {new=}", self.find_audio_files)
            audio_files = new

        for f in audio_files:
            try:
                Log.info(f"    - \"{f.name if isinstance(f, SPath) else f.file}\"")  # type:ignore[attr-defined]
            except (AttributeError, ValueError) as e:
                Log.warn(f"    - Unknown track!\n{e}")

        self.audio_files += audio_files

        return audio_files

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
                "The given file could not be found!", self._extract_tracks,
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
        ref: vs.VideoNode | Any | None = None,
        track_args: list[dict[str, Any]] = [dict(lang="ja", default=True)],
        encoder: Encoder = AutoEncoder,
        trimmer: HasTrimmer | None | Literal[False] = None,
        force: bool = False,
        verbose: bool = False,
    ) -> list[AudioTrack]:
        """
        Encode the audio tracks.

        :param audio_file:      Path to an audio file or an AudioNode. If none, checks object's audio files.
        :param trims:           Audio trims. If False or empty list, do not trim.
                                If True, use trims passed in ScriptInfo.
        :param reorder:         Reorder tracks. For example, if you know you have 3 audio tracks
                                ordered like [JP, EN, "Commentary"], you can pass [1, 0, 2]
                                to reorder them to [EN, JP, Commentary].
                                This can also be used to remove specific tracks.
        :param ref:             Reference VideoNode for framerate and max frame number information.
                                if None, gets them from the source clip pre-trimming.
        :param track_args:      Keyword arguments for the track. Accepts a list,
                                where one set of kwargs goes to every track.
        :param encoder:         Audio encoder to use. If the audio file is lossy, it will NEVER re-encode it!
                                Default: AutoEncoder (default arguments).
        :param trimmer:         Trimmer to use for trimming. If False, don't trim at all.
                                If None, automatically determine the trimmer based on input file.
        :param verbose:         Enable more verbose output.
        :param force:           Force the audio files to be re-encoded, even if they're lossy.
                                I'm aware I said it would never re-encode it.
        """
        from itertools import zip_longest

        from vsmuxtools import (FLAC, Sox, do_audio, frames_to_samples,
                                is_fancy_codec)

        from ..script import ScriptInfo

        func = self.encode_audio

        if all(not afile for afile in (audio_file, self.audio_files)):
            Log.warn("No audio tracks found to encode...", func)

            return []

        is_file = True

        if audio_file is not None and audio_file:
            if isinstance(audio_file, vs.AudioNode):
                audio_file = [audio_file]  # type:ignore[list-item]
            elif not isinstance(audio_file, list):
                audio_file = [SPath(str(audio_file))]

        if any([isinstance(audio_file, vs.AudioNode)]):
            is_file = False
            Log.warn("AudioNode passed! This may be a buggy experience...", func)

        process_files = audio_file or self.audio_files

        # Remove acopy files first so they don't mess with reorder and stuff.
        if is_file:
            self.__clean_acopy(process_files[0])  # type:ignore[index]

        if ref is not None:
            Log.debug(f"`ref` VideoNode passed: {ref}", func)

        wclip = ref.src.init() if isinstance(ref, ScriptInfo) else ref or self.script_info.src.init()

        trims = self.script_info.trim if trims is None else trims

        # Normalising trims.
        if not trims:
            pass
        elif isinstance(trims, tuple) and not isinstance(trims, list):
            trims = [trims]
        elif is_file:
            trims = [trims] if not isinstance(trims[0], tuple) else trims
        else:
            trims_list = trims if isinstance(trims[0], tuple) else [trims]
            trims = [frames_to_samples(x, 48000, wclip.fps) for x in trims_list]

        if trims:
            Log.debug(f"{trims=}", func)

        process_files = self._reorder(process_files, reorder)

        if not process_files:
            return process_files

        # Normalising track args
        if track_args and not isinstance(track_args, list):
            track_args = [track_args]

        # codec = self._get_audio_codec(encoder)
        encoder = encoder() if callable(encoder) else encoder

        trimmer_kwargs = dict(
            fps=wclip.fps,
            num_frames=wclip.num_frames
        )

        # TODO: Figure out how much I can move out of this for loop.
        for i, (audio_file, trim, track_arg) in enumerate(  # type:ignore[arg-type, assignment]
            zip_longest(process_files, trims, track_args, fillvalue=trims[-1])  # type:ignore[arg-type]
        ):
            if not isinstance(trim, tuple):
                Log.warn(f"Trim is not a tuple: {trim} ({type(trim)})", self.encode_audio)
                trim = tuple(trim)

            # I guess this is something to worry about now?
            if trim == track_arg:
                track_arg = track_args[-1]

            if any(x < 0 for x in trim):
                old_trim, trim = trim, (
                    max(0, trim[0]),
                    wclip.num_frames - abs(trim[1]) if trim[1] < 0 else trim[1]
                )

                Log.warn(
                    f"Invalid trim values fixed: {trim}. Original trim: {old_trim}",
                    self.encode_audio
                )

            if any(x > wclip.num_frames for x in trim):
                old_trim, trim = trim, tuple(min(wclip.num_frames, x) for x in trim)
                Log.warn(
                    f"Trim values greater than the number of frames set to the number of frames: {trim}. "
                    f"Original trim: {old_trim}", self.encode_audio
                )

            if track_arg:
                track_arg = dict(track_arg)

            delay = track_arg.pop("delay", 0)

            Log.debug(
                f"Processing audio track {i + 1}/{len(process_files)}...",  self.encode_audio  # type:ignore[arg-type]
            )
            Log.debug(f"Processing audio file \"{audio_file}\"...", func)
            Log.info(f"{trim=}, {track_arg=}", func)

            if delay:
                Log.info(f"Delay passed ({delay}ms), applying to source audio file...", func)

            src = cast(vs.VideoNode, self.script_info.src.init())

            # This is mainly meant to support weird trims we don't typically support and should not be used otherwise!
            if isinstance(audio_file, vs.AudioNode):
                Log.warn(
                    "Not properly supported yet! This may fail!", self.encode_audio,
                    CustomNotImplementedError
                )  # type:ignore[arg-type]

                atrack = do_audio(
                    audio_file, encoder=encoder, fps=src.fps, num_frames=src.num_frames
                )

                atrack.container_delay = delay

                self.audio_tracks += [atrack.to_track(**track_arg)]

                continue

            trimmed_files = list(SPath(get_workdir()).glob(f"{audio_file.stem}_*_trimmed_*.*"))

            if trimmed_files:
                # Delete temp dir to minimise random errors.
                if trimmed_files[0].exists():
                    shutil.rmtree(trimmed_files[0].parent / ".temp", True)

                # If a trimmed audio file already exists, this means it was likely already encoded.
                if trim:
                    Log.debug(f"Trimmed file found at \"{trimmed_files[0]}\"! Skipping encoding...", func)

                    afile = AudioFile.from_file(trimmed_files[0], func)
                    afile.container_delay = delay

                    self.audio_tracks += [afile.to_track(**(track_arg | dict(default=not bool(i))))]

                    continue

            afile = AudioFile.from_file(audio_file, func)
            afile.container_delay = delay

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

            try:
                is_lossy = force or afile.is_lossy()
            except IndexError:
                raise Log.error(f"Could not get the mediainfo for \"{afile.file}\"!", CustomIndexError)

            # Trim the audio file if applicable.
            if trim and trimmer is not False:
                trimmer_obj = trimmer or (FFMpeg.Trimmer if is_lossy else Sox)
                trimmer_obj = trimmer_obj(**trimmer_kwargs)

                if any(x is None for x in trim):
                    trim = (trim[0] or 0, trim[1] or wclip.num_frames)

                if trim[0] < 0:
                    new_delay = frame_to_ms(abs(trim[0]), wclip.fps)

                    Log.warn(
                        f"Start trim value is negative ({trim[0]})! Calculating additional delay of {new_delay}ms!",
                        self.encode_audio
                    )

                    delay -= new_delay
                    trim = (0, trim[1])

                if trim[1] > wclip.num_frames:
                    trim = (trim[0], wclip.num_frames)
                elif trim[1] < 0:
                    trim_into_ep = wclip.num_frames - abs(trim[1])
                    if trim_into_ep < 0:
                        Log.warn(
                            f"End trim is before the start trim ({trim[1]} < {trim[0]} ({trim_into_ep} frames))!",
                            self.encode_audio
                        )

                        trim = (0, 0)
                    else:
                        trim = (trim[0], trim_into_ep)

                setattr(trimmer_obj, "trim", trim)
                setattr(trimmer_obj, "fps", wclip.fps)
                setattr(trimmer_obj, "num_frames", wclip.num_frames)

                if force and is_lossy:
                    Log.debug(
                        "\"force\" is set to True and the file is lossy! Creating an intermediary file...",
                        self.encode_audio
                    )

                    afile = FLAC(compression_level=0).encode_audio(afile)

                Log.info(f"Trimming audio file \"{afile.file}\" with trims {trim}...", self.encode_audio)
                # afile = trimmer_obj.trim_audio(afile)

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
                # encoded = do_audio(afile, i, trim, wclip.fps, wclip.num_frames, None, None, encoder, not verbose)
                # ensure_path(afile.file, func).unlink(missing_ok=True)
                # afile = encoded

            # Move the acopy to the original position if muxtools Thanos snapped it.
            if not SPath(afile_old).exists():
                afile_copy.replace(afile_old)
                afile_copy.unlink(missing_ok=True)

            atrack = do_audio(
                audio_file, encoder=encoder, trims=trim, fps=src.fps, num_frames=src.num_frames, quiet=not verbose
            )

            atrack.container_delay = delay

            if abs(atrack.container_delay) > 1001:
                Log.warn(
                    f"Container delay is greater than 1001ms ({atrack.container_delay}ms)! "
                    "This is likely to cause syncing issues! Consider trimming the audio file further.",
                    self.encode_audio
                )

            atrack = atrack.to_track(**track_arg)

            # atrack.delay = delay

            Log.debug(atrack.__dict__, func)

            self.audio_tracks += [atrack]

        # Remove acopy files again so they don't mess up future encodes.
        self.__clean_acopy(afile.file)

        return self.audio_tracks

    def _reorder(
        self, process_files: list[SPath] | None = None,
        reorder: list[int] | Literal[False] = False
    ) -> list[SPath]:
        if not reorder:
            return

        process_files = process_files or self.audio_files

        if len(reorder) > len(process_files):  # type:ignore[arg-type]
            reorder = reorder[:len(process_files)]  # type:ignore[arg-type]

        return [process_files[i] for i in reorder]

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
            Log.error(str(e), self.__clean_acopy, CustomValueError)  # type:ignore[arg-type]

    def _get_audio_codec(self, encoder: Encoder) -> str:
        encoder_map = {
            "qaac": "qaac",
            "flac": "libflac",
            "opus": "libopus"
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
