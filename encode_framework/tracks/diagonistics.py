
import subprocess
from typing import Any

from vstools import CustomError, CustomValueError, FileNotExistsError, SPath, SPathLike

from ..util.logging import Log
from .audio import _AudioEncoder
from .chapters import _Chapters
from .subtitles import _Subtitles
from .video import _VideoEncoder

__all__: list[str] = [
    "_EncodeDiagnostics"
]


class _EncodeDiagnostics(_AudioEncoder, _Chapters, _Subtitles, _VideoEncoder):
    def diagnostics(
        self, premux_path: SPathLike | None = None,
        filesize_unit: str = "mb", plotbitrate: bool = True
    ) -> dict[str, Any]:
        """
        Print some diagnostic information about the encode.

        Returns an object containing all the diagnostics.
        """
        elapsed_time = self.script_info.elapsed_time(self.diagnostics)

        self.premux_path = SPath(premux_path or self.premux_path)

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
            self.script_info.file.parents[1] / "_assets" / "bitrate_plots"
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
                "tracks": {
                    "video": self.video_file,
                    "audio": self.audio_tracks,
                    "subtitles": self.subtitle_tracks,
                    "chapters": self.chapters
                }
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
            raise CustomValueError("An invalid unit was passed!", _Diagnostics.get_filesize, f"{unit} not in {units}")

        sfile = SPath(file)

        if not sfile.exists():
            raise FileNotExistsError(f"The file \"{sfile}\" could not be found!", _Diagnostics.get_filesize)

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
            filesize += float(_Diagnostics.get_filesize(f, unit))

        return filesize

    @classmethod
    def _prettystring_filesize(cls, filesize: float, unit: str = "mb", rnd: int = 2) -> str:
        """Create a pretty string out of the components for a filesize."""
        return f"{round(filesize, rnd)}{unit}"
