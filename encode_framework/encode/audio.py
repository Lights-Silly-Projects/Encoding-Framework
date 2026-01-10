from __future__ import annotations

import re
import threading
import time
from typing import Any, Literal

from vsmuxtools import (
    AudioFile,
    AudioTrack,
    Encoder,
    FFMpeg,
    FLAC,
    HasTrimmer,
    Opus,
    ParsedFile,
    TrackType,
    TimeScale,
    AutoEncoder,
)
from vstools import (
    CustomRuntimeError,
    CustomValueError,
    FileNotExistsError,
    FileType,
    SPath,
    SPathLike,
    to_arr,
    vs,
)

from ..util.convert import frame_to_ms
from ..util.logging import Log
from ..util.tracks import build_audio_track_name
from .base import _BaseEncoder
from .utils import normalize_track_type_args, split_track_args

__all__: list[str] = [
    "_AudioEncoder",
]


class _AudioEncoder(_BaseEncoder):
    """Class containing methods pertaining to handling audio encoding."""

    audio_files: list[SPath] = []
    """A list of all audio source files."""

    audio_tracks: list[AudioTrack] = []
    """A list of all audio tracks."""

    def find_audio_files(
        self,
        dgi_path: SPathLike | None = None,
        overwrite: bool = False,
        **kwargs: Any,
    ) -> list[SPath]:
        """
        Find accompanying DGIndex(NV) demuxed audio tracks.

        If no demuxed tracks can be found, it will instead check if the source video is an m2ts file.
        If it is, it will try to extract those audio tracks and return those.
        If input file is not a dgi file, it will throw an error.
        """
        if overwrite:
            self.audio_files = []

        dgi_file = self._resolve_dgi_path(dgi_path)

        # Pre-clean acopy files because it's a pain if you ran this after updating...
        try:
            self.__clean_acopy(dgi_file)
        except Exception as e:
            Log.error(str(e), self.find_audio_files)

        # Handle non-dgi files by converting them to dgi first
        if not dgi_file.to_str().endswith(".dgi"):
            return self._handle_non_dgi_file(dgi_file, overwrite)

        audio_files = self._search_audio_files(dgi_file)

        # Fallback to m2ts extraction if no demuxed tracks found
        if not audio_files:
            audio_files = self._find_m2ts_audio(dgi_file)

        if audio_files:
            audio_files = sorted(audio_files, key=self.extract_pid)
            self._log_found_audio_files(audio_files)
            self.audio_files += audio_files

        return audio_files

    def _resolve_dgi_path(self, dgi_path: SPathLike | None) -> SPath:
        """Resolve the dgi file path from the given parameter or script_info."""
        if isinstance(dgi_path, list):
            dgi_path = dgi_path[0]

        if dgi_path is not None:
            return SPath(dgi_path)

        return self.script_info.src_file[0]

    def _handle_non_dgi_file(
        self, file_path: SPath, overwrite: bool
    ) -> list[SPath]:
        """Handle non-dgi files by indexing them first, then finding audio files."""
        Log.warn("Trying to pass a non-dgi file!", self.find_audio_files)

        # Save current state
        old_script_info_src = self.script_info.src_file
        old_script_info_trim = self.script_info.trim

        # Index the file to create a dgi file
        self.script_info.src_file = []
        try:
            self.script_info.index(file_path, self.script_info.trim, force_dgi=True)
        except IndexError:
            self.script_info.index(
                file_path,
                self.script_info.trim,
                force_dgi=True,
                dgi_kwargs=dict(force_symlink=True),
            )

        # Find audio files using the newly created dgi file
        audio_files = self._search_audio_files(self.script_info.src_file[0])

        # Clean up temporary files
        self._temp_files += to_arr(self.script_info.src_file)
        self._cleanup_temp_files()

        # Restore original state
        self.script_info.src_file = old_script_info_src
        self.script_info.update_trims(old_script_info_trim)

        if audio_files:
            audio_files = sorted(audio_files, key=self.extract_pid)
            self._log_found_audio_files(audio_files)
            self.audio_files += audio_files

        return audio_files

    def _search_audio_files(self, dgi_file: SPath) -> list[SPath]:
        """Search for audio files in the directory containing the dgi file."""
        Log.debug(
            f'DGIndex(NV) input found! Trying to find audio tracks in "{dgi_file.get_folder()}"...',
            self.find_audio_files,
        )

        # [] and () characters mess up the glob, so replacing them
        search_string = f"*{dgi_file.stem}*".translate(
            str.maketrans("[]()", "????")
        ).replace("**", "*")

        audio_files: list[SPath] = []

        for file_path in dgi_file.get_folder().glob(search_string):
            if self._should_skip_file(file_path):
                continue

            Log.debug(
                f'Checking the following file: "{file_path.name}"...',
                self.find_audio_files,
            )

            if self._is_valid_audio_file(file_path):
                audio_files.append(file_path)

        return audio_files

    def _should_skip_file(self, file_path: SPath) -> bool:
        """Check if a file should be skipped based on its extension."""
        # Explicitly ignore certain files; audio.parse seems to count these for some reason?
        return file_path.suffix.lower() in (
            ".log",
            ".sup",
            ".ttf",
            ".otf",
            ".ttc",
            ".wob",
        )

    def _is_valid_audio_file(self, file_path: SPath) -> bool:
        """Check if a file is a valid audio file."""
        try:
            FileType.AUDIO.parse(file_path, func=self.find_audio_files)
            return True
        except (AssertionError, ValueError):
            return False

    def _log_found_audio_files(self, audio_files: list[SPath]) -> None:
        """Log the found audio files."""
        Log.info(f"The following audio sources were found ({len(audio_files)}):")

        for file_path in audio_files:
            try:
                name = file_path.name if isinstance(file_path, SPath) else file_path.file  # type:ignore[attr-defined]
                Log.info(f'    - "{name}"')
            except (AttributeError, ValueError) as e:
                Log.warn(f"    - Unknown track!\n{e}")

    def _cleanup_temp_files(self) -> None:
        """Clean up temporary files, handling permission errors gracefully."""
        for file_path in self._temp_files:
            try:
                file_path.unlink(missing_ok=True)
            except PermissionError:
                Log.warn(
                    f'Failed to unlink file, "{file_path}"! Skipping...',
                    self.find_audio_files,
                )

    def _find_m2ts_audio(self, dgi_file: SPath) -> list[SPath]:
        from vsmuxtools import parse_m2ts_path

        Log.debug(
            "No audio tracks could be found! Trying to find the source file...",
            self.find_audio_files,
        )

        m2ts = parse_m2ts_path(dgi_file)

        if str(m2ts).endswith(".dgi"):
            Log.debug(
                "No m2ts file found! Not encoding any audio...", self.find_audio_files
            )

            return []

        Log.debug(f'Source file found at "{str(m2ts)}"', self.find_audio_files)

        return self._extract_tracks(m2ts)

    def _extract_tracks(self, video_file: SPath) -> list[SPath]:
        """Extract tracks if a video file is passed."""
        from pymediainfo import MediaInfo, Track  # type:ignore[import]

        video_file = SPath(video_file)

        if not video_file.exists():
            Log.error(
                "The given file could not be found!",
                self._extract_tracks,
                FileNotExistsError,
                reason=video_file.to_str(),  # type:ignore[arg-type]
            )

        mi = MediaInfo.parse(video_file)

        atracks = list[AudioTrack]()
        _track = -1

        for track in mi.tracks:
            assert isinstance(track, Track)

            if track.track_type == "Audio":
                _track += 1

                atracks += [
                    FFMpeg.Extractor(
                        _track
                        if track is None
                        else int(track.to_data().get("stream_identifier", _track))
                    ).extract_audio(video_file)
                ]

        return atracks

    def encode_audio(
        self,
        audio_file: SPath | list[SPath] | vs.AudioNode | None = None,
        trims: list[tuple[int, int]] | tuple[int, int] | Literal[False] | None = None,
        reorder: list[int] | Literal[False] | int = False,
        ref: vs.VideoNode | list[vs.VideoNode] | Any | None = None,
        track_args: list[dict[str, Any]] = [dict(lang="ja", default=True)],
        encoder: Encoder = AutoEncoder,
        trimmer: HasTrimmer | None | Literal[False] = None,
        script_info: "ScriptInfo" | None = None,  # type:ignore # noqa
        full_analysis: bool = True,
        force: bool = False,
        verbose: bool = False,
    ) -> list[AudioTrack]:
        """
        Encode the audio tracks.

        :param audio_file:      Path to an audio file or an AudioNode. If none, checks object's audio files.
        :param trims:           Audio trims. If False or empty list, do not trim.
                                If None, use trims passed in ScriptInfo.
        :param reorder:         Reorder tracks. For example, if you know you have 3 audio tracks
                                ordered like [JP, EN, "Commentary"], you can pass [1, 0, 2]
                                to reorder them to [EN, JP, Commentary].
                                This can also be used to remove specific tracks.
        :param ref:             Reference VideoNode for framerate and max frame number information.
                                if None, gets them from the source clip pre-trimming.
        :param track_args:      Keyword arguments for the track. Accepts a list,
                                where one set of kwargs goes to every track.
        :param encoder:         Audio encoder to use.
        :param trimmer:         Trimmer to use for trimming. If False, don't trim at all.
                                If None, automatically determine the trimmer based on input file.
        :param script_info:     Optional ScriptInfo override.
        :param full_analysis:   Enable full audio analysis (default: True).
        :param force:           Force the audio files to be re-encoded, even if they're lossy.
        :param verbose:         Enable more verbose output.
        """
        from vsmuxtools import do_audio

        func = self.encode_audio

        # Resolve audio files to process
        process_files = self._resolve_audio_files(audio_file)

        if not process_files:
            Log.warn("No audio tracks found to encode...", func)
            return []

        # Get reference clip for frame information
        wclip = self._get_reference_clip(ref, script_info)

        # Debug: Log reference clip information
        Log.debug(
            f"Reference clip info - FPS: {wclip.fps} ({float(wclip.fps):.6f}), "
            f"num_frames: {wclip.num_frames}, "
            f"duration: {wclip.num_frames / float(wclip.fps):.3f}s",
            func,
        )

        # Normalize trims
        trims = self._normalize_trims(trims, wclip)
        Log.debug(f"Normalized trims: {trims}", func)

        # Reorder files if needed
        reorder_list = [reorder] if isinstance(reorder, int) else reorder
        process_files = self._reorder(process_files, reorder_list)

        if not process_files:
            return []

        # Normalize track args
        if not isinstance(track_args, list):
            track_args = [track_args]

        # Initialize encoder
        encoder = encoder() if callable(encoder) else encoder

        # Determine timescale
        src_file = (script_info or self.script_info).src_file[0]
        timescale = TimeScale.M2TS if src_file.suffix == ".m2ts" else TimeScale.MKV
        Log.debug(
            f"Source file: {src_file.name}, timescale: {timescale.name}",
            func,
        )

        # Process each audio file
        for i, audio_input in enumerate(process_files):
            Log.info(f"Processing audio file {i + 1}/{len(process_files)}...", func)

            # Convert AudioNode to file if needed
            audio_file_path = self._convert_audionode_to_file(
                audio_input, wclip, verbose
            )

            # Get trim for this track
            trim = self._get_track_trim(trims, i, script_info, wclip)

            # Debug: Log trim information
            if trim:
                trim_start_ms = frame_to_ms(trim[0], wclip.fps) if trim[0] is not None else 0
                trim_end_ms = frame_to_ms(trim[1], wclip.fps) if trim[1] is not None else 0
                # Calculate frame count: end - start (exclusive end, so frames are start to end-1)
                trim_frame_count = trim[1] - trim[0] if trim[1] is not None and trim[0] is not None else 0
                trim_duration_ms = trim_end_ms - trim_start_ms
                trim_duration_from_frames = trim_frame_count / float(wclip.fps)
                Log.debug(
                    f"Track {i+1} trim: {trim} (frames) = "
                    f"{trim_start_ms:.1f}ms - {trim_end_ms:.1f}ms "
                    f"(duration: {trim_duration_ms:.1f}ms / {trim_duration_ms/1000:.3f}s)\n"
                    f"  - Frame count: {trim_frame_count} frames (end - start, exclusive end)\n"
                    f"  - Duration from frame count: {trim_duration_from_frames:.3f}s\n"
                    f"  - Note: VapourSynth trims are [start, end) - exclusive end frame",
                    func,
                )
            else:
                Log.debug(f"Track {i+1}: No trim applied", func)

            # Get track args for this track
            track_arg = (
                track_args[i] if i < len(track_args) else (track_args[-1] if track_args else {})
            )
            track_arg = dict(track_arg) if track_arg else {}
            track_arg = normalize_track_type_args(track_arg)

            # Extract delay from track args
            delay = int(track_arg.pop("delay", 0))

            if delay:
                Log.info(f"Delay passed ({delay}ms), applying to source audio file...", func)
            else:
                Log.debug(f"Track {i+1}: No delay applied", func)

            # Clean up acopy files
            try:
                self.__clean_acopy(audio_file_path)
            except Exception:
                pass

            # If this is a demuxed DTS file from a DGI source, try extracting from m2ts instead
            # This ensures we get the full audio track with correct timing
            m2ts_extracted_file = self._try_extract_from_m2ts(
                audio_file_path, script_info, func
            )

            # TEMPORARY: Check if we should bypass encoding and use m2ts file directly
            # Set this to True to test if the issue is with encoding or extraction
            BYPASS_ENCODE_USE_M2TS = True  # TODO: Remove this temporary check

            if BYPASS_ENCODE_USE_M2TS and m2ts_extracted_file != audio_file_path:
                Log.warn(
                    f"TEMPORARY: Bypassing encoding and using m2ts-extracted file directly: {m2ts_extracted_file.name}",
                    func,
                )
                # Create a simple AudioTrack from the extracted file without encoding
                from vsmuxtools import ParsedFile
                from pymediainfo import MediaInfo

                try:
                    afile = ParsedFile.from_file(m2ts_extracted_file)
                    atrack = afile.find_tracks(type=TrackType.AUDIO, error_if_empty=True)[0]

                    # Set container delay
                    atrack.container_delay = delay

                    # Build track name if not provided
                    if not track_arg.get("name"):
                        track_arg["name"] = build_audio_track_name(m2ts_extracted_file)

                    # Apply track args
                    for key, value in track_arg.items():
                        setattr(atrack, key, value)

                    # Debug: Log the resulting audio track info
                    try:
                        mi = MediaInfo.parse(atrack.file)
                        for track in mi.tracks:
                            if track.track_type == "Audio":
                                duration_ms = float(track.duration or 0)
                                duration_s = duration_ms / 1000
                                Log.debug(
                                    f"TEMPORARY: Using m2ts-extracted audio track (no encoding):\n"
                                    f"  - File: {atrack.file.name}\n"
                                    f"  - Duration: {duration_ms:.1f}ms ({duration_s:.3f}s)\n"
                                    f"  - Sample rate: {track.sampling_rate}Hz\n"
                                    f"  - Channels: {track.channel_s}\n"
                                    f"  - Container delay: {atrack.container_delay}ms",
                                    func,
                                )
                                break
                    except Exception as e:
                        Log.debug(f"Could not parse m2ts-extracted audio file info: {e}", func)

                    self.audio_tracks.append(atrack)
                    continue  # Skip the encoding loop for this track
                except Exception as e:
                    Log.warn(
                        f"TEMPORARY: Failed to use m2ts-extracted file directly ({e}). Falling back to normal encoding.",
                        func,
                    )
                    audio_file_path = m2ts_extracted_file
            else:
                audio_file_path = m2ts_extracted_file

            # Handle force encoding for lossy formats
            audio_file_path = self._handle_force_encoding(
                audio_file_path, force, func
            )

            # Ensure audio_file_path is an SPath
            if not isinstance(audio_file_path, SPath):
                audio_file_path = SPath(audio_file_path)

            # Calculate trim to pass to do_audio
            # Only pass trim if it's not the full clip
            trim_to_pass = None
            if trim:
                # Check if trim covers the full clip (accounting for 0-indexed end frame)
                is_full_clip = (
                    trim[0] == 0
                    and (trim[1] == wclip.num_frames or trim[1] == wclip.num_frames - 1)
                )
                if not is_full_clip:
                    trim_to_pass = trim
                else:
                    Log.debug(
                        f"Trim covers full clip (trim={trim}, num_frames={wclip.num_frames}), "
                        "not passing to do_audio",
                        func,
                    )
            else:
                Log.debug("No trim provided, not passing to do_audio", func)

            # Debug: Get source audio file info before processing
            # Try to get actual duration from the file (MediaInfo can't always parse DTS files)
            source_duration_s = None
            source_duration_frames = None
            try:
                from pymediainfo import MediaInfo

                mi_source = MediaInfo.parse(audio_file_path)
                for track in mi_source.tracks:
                    if track.track_type == "Audio":
                        source_duration_ms = float(track.duration or 0)
                        source_duration_s = source_duration_ms / 1000
                        source_sr = track.sampling_rate

                        # Calculate how many frames this duration represents at the video FPS
                        if source_duration_s > 0:
                            source_duration_frames = int(source_duration_s * float(wclip.fps))

                        Log.debug(
                            f"Source audio file info (from MediaInfo):\n"
                            f"  - File: {audio_file_path.name}\n"
                            f"  - Duration: {source_duration_ms:.1f}ms ({source_duration_s:.3f}s)\n"
                            f"  - Duration in frames (at {wclip.fps}): {source_duration_frames} frames\n"
                            f"  - Sample rate: {source_sr}Hz",
                            func,
                        )
                        break
            except Exception as e:
                Log.debug(f"Could not parse source audio file info with MediaInfo: {e}", func)

            # If MediaInfo couldn't get duration, try to get it from ffprobe
            if not source_duration_s or source_duration_s == 0:
                try:
                    import subprocess
                    result = subprocess.run(
                        [
                            "ffprobe",
                            "-v", "error",
                            "-show_entries", "format=duration",
                            "-of", "default=noprint_wrappers=1:nokey=1",
                            str(audio_file_path),
                        ],
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    if result.returncode == 0 and result.stdout.strip():
                        duration_str = result.stdout.strip()
                        # Handle 'N/A' or empty strings
                        if duration_str and duration_str.upper() != "N/A":
                            try:
                                source_duration_s = float(duration_str)
                                source_duration_frames = int(source_duration_s * float(wclip.fps))
                                Log.debug(
                                    f"Source audio file info (from ffprobe):\n"
                                    f"  - Duration: {source_duration_s:.3f}s\n"
                                    f"  - Duration in frames (at {wclip.fps}): {source_duration_frames} frames",
                                    func,
                                )
                            except ValueError:
                                Log.debug(f"Could not parse duration from ffprobe output: {duration_str}", func)
                except Exception as e:
                    Log.debug(f"Could not get source audio duration from ffprobe: {e}", func)

            # Validate trim against source duration if we have it
            if trim_to_pass and source_duration_frames is not None:
                trim_start_frame = trim_to_pass[0]
                trim_end_frame = trim_to_pass[1]
                trim_frame_count = trim_end_frame - trim_start_frame

                if trim_end_frame > source_duration_frames:
                    Log.warn(
                        f"WARNING: Trim end frame ({trim_end_frame}) exceeds source audio duration "
                        f"({source_duration_frames} frames / {source_duration_s:.3f}s)!\n"
                        f"  - Trim: {trim_to_pass}\n"
                        f"  - Source duration: {source_duration_s:.3f}s ({source_duration_frames} frames)\n"
                        f"  - Trim expects: {trim_frame_count} frames ({trim_frame_count / float(wclip.fps):.3f}s)\n"
                        f"  - This will cause the audio to be shorter than expected and may cause sync issues!",
                        "encode_audio",
                    )

            # Debug: Log what we're passing to do_audio
            # Calculate expected duration correctly
            # Trims in VapourSynth are typically [start, end) - exclusive end
            # So frame count = end - start
            if trim_to_pass:
                trim_frame_count = trim_to_pass[1] - trim_to_pass[0]
                expected_duration_from_trim = trim_frame_count / float(wclip.fps)
            elif trim:
                trim_frame_count = trim[1] - trim[0] if trim[1] is not None and trim[0] is not None else wclip.num_frames
                expected_duration_from_trim = trim_frame_count / float(wclip.fps)
            else:
                expected_duration_from_trim = wclip.num_frames / float(wclip.fps)

            Log.debug(
                f"Calling do_audio with:\n"
                f"  - audio_file_path: {audio_file_path}\n"
                f"  - timesource (fps): {wclip.fps} ({float(wclip.fps):.6f})\n"
                f"  - timescale: {timescale.name}\n"
                f"  - trims: {trim_to_pass}\n"
                f"  - num_frames: {wclip.num_frames}\n"
                f"  - Expected duration from trim/num_frames: {expected_duration_from_trim:.3f}s\n"
                f"  - skip_analysis: {not full_analysis}\n"
                f"  - delay: {delay}ms",
                func,
            )

            # Use do_audio to handle extraction, trimming, and encoding
            # do_audio will automatically skip encoding for lossy formats unless we've
            # already created an intermediary file (when force=True)
            # Note: do_audio extracts the audio first, then trims it
            atrack = do_audio(
                audio_file_path,
                timesource=wclip.fps,
                timescale=timescale,
                extractor=FFMpeg.Extractor(skip_analysis=not full_analysis),
                encoder=encoder,
                trims=trim_to_pass,
                num_frames=wclip.num_frames,
                quiet=not verbose,
            )

            # After extraction, try to get the actual extracted file duration
            # This helps diagnose if the trim exceeded the source duration
            if trim_to_pass:
                try:
                    # The extracted file should be in the workdir with "_extracted_0" suffix
                    # We need to find it - it might be in the same dir as audio_file_path or in workdir
                    extracted_file_pattern = audio_file_path.stem + "_extracted_0"
                    extracted_file = None

                    # Try to find the extracted file
                    for ext in [".dts", ".ac3", ".flac", ".wav", ".mka"]:
                        potential_file = audio_file_path.parent / f"{extracted_file_pattern}{ext}"
                        if potential_file.exists():
                            extracted_file = potential_file
                            break

                    if extracted_file:
                        # Get duration from the extracted file
                        try:
                            import subprocess
                            result = subprocess.run(
                                [
                                    "ffprobe",
                                    "-v", "error",
                                    "-show_entries", "format=duration",
                                    "-of", "default=noprint_wrappers=1:nokey=1",
                                    str(extracted_file),
                                ],
                                capture_output=True,
                                text=True,
                                timeout=10,
                            )
                            if result.returncode == 0 and result.stdout.strip():
                                duration_str = result.stdout.strip()
                                if duration_str and duration_str.upper() != "N/A":
                                    extracted_duration_s = float(duration_str)
                                    extracted_duration_frames = int(extracted_duration_s * float(wclip.fps))

                                    if trim_to_pass[1] > extracted_duration_frames:
                                        Log.warn(
                                            f"WARNING: Trim end frame ({trim_to_pass[1]}) exceeds extracted audio duration "
                                            f"({extracted_duration_frames} frames / {extracted_duration_s:.3f}s)!\n"
                                            f"  - Trim: {trim_to_pass}\n"
                                            f"  - Extracted audio duration: {extracted_duration_s:.3f}s ({extracted_duration_frames} frames)\n"
                                            f"  - Trim expects: {trim_frame_count} frames ({expected_duration_from_trim:.3f}s)\n"
                                            f"  - This will cause the audio to be shorter than expected and may cause sync issues!",
                                            "encode_audio",
                                        )
                        except Exception:
                            pass  # Silently fail - this is just diagnostic
                except Exception:
                    pass  # Silently fail - this is just diagnostic

            # Set container delay BEFORE logging (so it shows in the log)
            atrack.container_delay = delay
            Log.debug(
                f"Set container delay to {atrack.container_delay}ms (from delay={delay}ms)",
                func,
            )

            # Debug: Log the resulting audio track info
            try:
                from pymediainfo import MediaInfo

                mi = MediaInfo.parse(atrack.file)
                for track in mi.tracks:
                    if track.track_type == "Audio":
                        duration_ms = float(track.duration or 0)
                        duration_s = duration_ms / 1000
                        # Calculate expected duration - trims are [start, end) exclusive
                        if trim_to_pass:
                            trim_frame_count = trim_to_pass[1] - trim_to_pass[0]
                            expected_duration = trim_frame_count / float(wclip.fps)
                        elif trim:
                            trim_frame_count = trim[1] - trim[0] if trim[1] is not None and trim[0] is not None else wclip.num_frames
                            expected_duration = trim_frame_count / float(wclip.fps)
                        else:
                            expected_duration = wclip.num_frames / float(wclip.fps)
                        duration_diff = abs(duration_s - expected_duration)
                        duration_diff_ms = duration_diff * 1000

                        # Calculate what the duration should be including delay
                        expected_duration_with_delay = expected_duration + (delay / 1000.0)

                        Log.debug(
                            f"Resulting audio track:\n"
                            f"  - File: {atrack.file.name}\n"
                            f"  - Duration: {duration_ms:.1f}ms ({duration_s:.3f}s)\n"
                            f"  - Expected duration (from trim): {expected_duration:.3f}s\n"
                            f"  - Expected duration (with delay): {expected_duration_with_delay:.3f}s\n"
                            f"  - Duration difference: {duration_diff_ms:.1f}ms ({duration_diff:.3f}s)\n"
                            f"  - Sample rate: {track.sampling_rate}Hz\n"
                            f"  - Channels: {track.channel_s}\n"
                            f"  - Container delay: {atrack.container_delay}ms",
                            func,
                        )

                        if duration_diff > 0.1:  # More than 100ms difference
                            # Calculate potential issues
                            missing_frames = duration_diff * float(wclip.fps)
                            missing_duration_s = duration_diff

                            Log.warn(
                                f"WARNING: Audio duration mismatch! "
                                f"Expected {expected_duration:.3f}s, got {duration_s:.3f}s "
                                f"(difference: {duration_diff_ms:.1f}ms / {duration_diff:.3f}s). "
                                f"This may indicate a sync issue!\n"
                                f"  - Trim: {trim_to_pass or trim}\n"
                                f"  - Frame count: {trim_frame_count if trim_to_pass or trim else wclip.num_frames}\n"
                                f"  - FPS: {wclip.fps} ({float(wclip.fps):.6f})\n"
                                f"  - Missing frames (approx): {missing_frames:.1f} frames\n"
                                f"  - Missing duration: {missing_duration_s:.3f}s\n"
                                f"  - Possible causes:\n"
                                f"    * Trim interpretation mismatch (inclusive vs exclusive end)\n"
                                f"    * Source audio duration different from expected\n"
                                f"    * FPS mismatch between video and audio\n"
                                f"    * Timescale issues (M2TS vs MKV)",
                                func,
                            )
                        break
            except Exception as e:
                Log.debug(f"Could not parse resulting audio file info: {e}", func)

            if abs(atrack.container_delay) > 1001:
                Log.warn(
                    f"Container delay is greater than 1001ms ({atrack.container_delay}ms)! "
                    "This is likely to cause syncing issues! Consider trimming the audio file further.",
                    func,
                )

            # Build track name if not provided
            if not track_arg.get("name"):
                track_arg["name"] = build_audio_track_name(atrack.file)

            # Convert to track with track args
            atrack = atrack.to_track(**(split_track_args(track_arg, i)))

            Log.debug(atrack.__dict__, func)

            self.audio_tracks.append(atrack)

        return self.audio_tracks

    def _resolve_audio_files(
        self, audio_file: SPath | list[SPath] | vs.AudioNode | None
    ) -> list[SPath | vs.AudioNode]:
        """Resolve audio files to process, handling AudioNode and file paths."""
        if audio_file is None:
            return self.audio_files

        if isinstance(audio_file, vs.AudioNode):
            return [audio_file]

        if isinstance(audio_file, list):
            return audio_file

        return [SPath(str(audio_file))]

    def _get_reference_clip(
        self,
        ref: vs.VideoNode | list[vs.VideoNode] | Any | None,
        script_info: Any | None,
    ) -> vs.VideoNode:
        """Get the reference clip for frame information."""
        from ..script import ScriptInfo

        if ref is not None:
            Log.debug(f"`ref` VideoNode passed: {ref}", self.encode_audio)
            if isinstance(ref, ScriptInfo):
                return ref.src.init()
            if isinstance(ref, vs.VideoNode):
                return ref

        return self.script_info.src.init()

    def _normalize_trims(
        self,
        trims: list[tuple[int, int]] | tuple[int, int] | Literal[False] | None,
        wclip: vs.VideoNode,
    ) -> list[tuple[int, int]] | tuple[int, int] | None:
        """Normalize trim values."""
        if trims is False:
            return None

        if trims is None:
            trims = self.script_info.trim

        # Convert single tuple to list for consistency
        if isinstance(trims, tuple):
            trims = [trims]

        # Normalize None values
        if isinstance(trims, list):
            normalized = []
            for trim in trims:
                if isinstance(trim, tuple):
                    start = trim[0] if trim[0] is not None else 0
                    end = trim[1] if trim[1] is not None else wclip.num_frames
                    normalized.append((start, end))
                else:
                    normalized.append(trim)
            return normalized if len(normalized) > 1 else normalized[0] if normalized else None

        return trims

    def _get_track_trim(
        self,
        trims: list[tuple[int, int]] | tuple[int, int] | None,
        track_index: int,
        script_info: Any | None,
        wclip: vs.VideoNode,
    ) -> tuple[int, int] | None:
        """Get the trim value for a specific track."""
        if trims is None:
            return None

        if isinstance(trims, tuple):
            return trims

        if isinstance(trims, list):
            # Handle multi-trim case
            if (
                script_info
                and isinstance(script_info.trim, list)
                and len(script_info.trim) == 1
            ):
                # Use track-specific trim if available, otherwise use last
                return trims[track_index] if track_index < len(trims) else trims[-1]
            # Use first trim for all tracks if not multi-trim
            return trims[0] if trims else None

        return None

    def _try_extract_from_m2ts(
        self,
        audio_file_path: SPath,
        script_info: Any | None,
        func: Any,
    ) -> SPath:
        """
        Try to extract audio directly from m2ts source if the audio file is a demuxed DTS file.

        This ensures we get the full audio track with correct timing instead of using
        potentially incomplete demuxed files.
        """
        # Check if this looks like a demuxed DTS file (has PID in the name)
        if "PID" not in audio_file_path.name or not audio_file_path.suffix.lower() in [".dts", ".ac3", ".thd"]:
            return audio_file_path

        try:
            from vsmuxtools import parse_m2ts_path

            # Try to get the m2ts source from script_info
            dgi_file = None
            if script_info and hasattr(script_info, "src_file"):
                src_file = script_info.src_file[0] if isinstance(script_info.src_file, list) else script_info.src_file
                if hasattr(src_file, "to_str"):
                    src_file_str = src_file.to_str()
                else:
                    src_file_str = str(src_file)

                if src_file_str.endswith(".dgi"):
                    dgi_file = SPath(src_file_str)
                else:
                    # Try to find a DGI file in the same directory
                    potential_dgi = SPath(src_file_str).with_suffix(".dgi")
                    if potential_dgi.exists():
                        dgi_file = potential_dgi

            if not dgi_file:
                # Try to find DGI file from the audio file's directory
                audio_dir = audio_file_path.parent
                dgi_files = list(audio_dir.glob("*.dgi"))
                if dgi_files:
                    dgi_file = dgi_files[0]

            if not dgi_file or not dgi_file.exists():
                Log.debug(
                    f"Could not find DGI file to determine m2ts source. Using demuxed file: {audio_file_path.name}",
                    func,
                )
                return audio_file_path

            # Parse m2ts path from DGI file
            m2ts = parse_m2ts_path(dgi_file)

            if str(m2ts).endswith(".dgi") or not SPath(m2ts).exists():
                Log.debug(
                    f"Could not find m2ts source file. Using demuxed file: {audio_file_path.name}",
                    func,
                )
                return audio_file_path

            # Extract PID from the demuxed file name
            pid_match = re.search(r"PID (\d+)", audio_file_path.name)
            if not pid_match:
                Log.debug(
                    f"Could not extract PID from filename. Using demuxed file: {audio_file_path.name}",
                    func,
                )
                return audio_file_path

            track_pid = int(pid_match.group(1))

            # Find the track index in the m2ts file
            from pymediainfo import MediaInfo, Track  # type:ignore[import]

            mi = MediaInfo.parse(m2ts)
            track_index = -1
            found_track = False

            for track in mi.tracks:
                assert isinstance(track, Track)
                if track.track_type == "Audio":
                    track_index += 1
                    # Check if this track matches the PID
                    stream_id = int(track.to_data().get("stream_identifier", track_index))
                    if stream_id == track_pid or track_index == track_pid:
                        found_track = True
                        break

            if not found_track:
                Log.debug(
                    f"Could not find matching track (PID {track_pid}) in m2ts file. Using demuxed file: {audio_file_path.name}",
                    func,
                )
                return audio_file_path

            # Extract the track from m2ts
            Log.info(
                f"Extracting audio track (PID {track_pid}) directly from m2ts source for better timing accuracy...",
                func,
            )

            extracted_file = FFMpeg.Extractor(track_index).extract_audio(m2ts)

            if extracted_file and SPath(extracted_file).exists():
                Log.debug(
                    f"Successfully extracted track from m2ts: {SPath(extracted_file).name}",
                    func,
                )
                return SPath(extracted_file)
            else:
                Log.debug(
                    f"Extraction from m2ts failed. Using demuxed file: {audio_file_path.name}",
                    func,
                )
                return audio_file_path

        except Exception as e:
            Log.debug(
                f"Error trying to extract from m2ts ({e}). Using demuxed file: {audio_file_path.name}",
                func,
            )
            return audio_file_path

    def _convert_audionode_to_file(
        self, audio_input: SPath | vs.AudioNode, wclip: vs.VideoNode, verbose: bool
    ) -> SPath:
        """Convert AudioNode to a WAV file using vsmuxtools."""
        from vsmuxtools import do_audio

        if isinstance(audio_input, vs.AudioNode):
            Log.debug("Converting AudioNode to WAV file...", self.encode_audio)
            audio_file = do_audio(
                audio_input,
                encoder=None,  # No encoding, just extract to WAV
                num_frames=wclip.num_frames,
                quiet=not verbose,
            )
            return audio_file.file

        return audio_input

    def _handle_force_encoding(
        self, audio_file_path: SPath, force: bool, caller: Any
    ) -> SPath:
        """
        Handle force encoding for lossy formats by creating an intermediary FLAC file.

        :param audio_file_path: Path to the audio file.
        :param force: Whether to force re-encoding of lossy formats.
        :param caller: Caller function for logging.
        :return: Path to the audio file (original or intermediary).
        """
        if not force:
            return audio_file_path

        # Check if the audio format is lossy or special
        try:
            afile = AudioFile.from_file(audio_file_path, caller)
            parsed = ParsedFile.from_file(audio_file_path)
            audio_tracks = parsed.find_tracks(
                type=TrackType.AUDIO, error_if_empty=True, caller=caller
            )

            if audio_tracks:
                aformat = audio_tracks[0].get_audio_format()
                if aformat and aformat.should_not_transcode():
                    # Create intermediary FLAC file for lossy formats when forcing
                    Log.debug(
                        '"force" is set to True and the file is marked as lossy or special! '
                        "Creating an intermediary file...",
                        caller,
                    )
                    afile = FLAC(compression_level=0).encode_audio(afile)
                    return afile.file

        except Exception as e:
            Log.debug(
                f"Could not determine audio format, proceeding with original file: {e}",
                caller,
            )

        return audio_file_path

    def _reorder(
        self,
        process_files: list[SPath] | None = None,
        reorder: list[int] | Literal[False] = False,
    ) -> list[SPath]:
        if process_files is None:
            return []

        if reorder is False:
            return process_files

        if isinstance(reorder, int):
            reorder = [reorder]

        process_files = process_files or self.audio_files

        if len(reorder) > len(process_files):  # type:ignore[arg-type]
            reorder = reorder[: len(process_files)]  # type:ignore[arg-type]

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
                Log.debug(f'Unlinking temporary file "{acopy}"...', self.encode_audio)
                SPath(acopy).unlink(missing_ok=True)
        except Exception as e:
            Log.error(str(e), self.__clean_acopy, CustomValueError)  # type:ignore[arg-type]

    def _get_audio_codec(self, encoder: Encoder) -> str:
        encoder_map = {"qaac": "qaac", "flac": "libflac", "opus": "libopus"}

        codec = encoder_map.get(str(encoder.__name__).lower())

        if not codec:
            Log.error(
                "Unknown codec. Please expand the if/else statement!",
                self.encode_audio,
                CustomRuntimeError,
                reason=encoder.__name__,  # type:ignore[arg-type]
            )

        return str(codec)

    # TODO:
    def _check_dupe_audio(self, atracks: list[AudioTrack]) -> list[AudioTrack]:
        """
        Compares the hashes of every audio track and removes duplicate tracks.
        Theoretically, if a track is an exact duplicate of another, the hashes should match.
        """

        return []

    def _schedule_unlink(path: SPathLike, timeout: int = 60, interval: float = 2.0):
        """
        Try to unlink the file at `path` in a background thread until it succeeds or timeout is reached.
        """
        spath = SPath(path)

        def _unlink_worker():
            end_time = time.time() + timeout

            while time.time() < end_time:
                try:
                    spath.unlink(missing_ok=True)
                    break
                except Exception:
                    time.sleep(interval)

        threading.Thread(target=_unlink_worker, daemon=True).start()
