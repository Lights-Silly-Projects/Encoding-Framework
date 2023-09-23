import os
from enum import Enum, auto
from typing import Any, Literal

from vstools import SPath, SPathLike, vs

from ...git import clone_git_repo
from ...types import IsWindows
from ...util import (Log, cargo_build, check_package_installed, check_program_installed, install_package, run_cmd,
                     temp_download, unpack_zip)

__all__: list[str] = [
    "OcrProgram"
]


class OcrProgram(str, Enum):
    """The OCR program to use."""

    VOBSUBOCR = auto()
    """https://lib.rs/crates/vobsubocr"""

    PGSRIP = auto()
    """https://github.com/ratoaq2/pgsrip"""

    SUBEXTRACTOR = auto()
    """https://www.videohelp.com/software/SubExtractor"""

    SUBTITLEEDIT = auto()
    """https://github.com/SubtitleEdit/subtitleedit"""

    def __str__(self) -> str:
        return self.name.lower()

    def ocr(self, file: SPathLike, *args: Any, **kwargs: Any) -> SPath:
        """
        OCR the given file using the chosen OCR program.

        If it fails, it will always return an SPath object of the original passed file.

        :param file:            File to process.
        :param *args:           Arguments to pass to the program.
        :param **kwargs:        Keyword arguments to pass to the program.
        """
        sfile = SPath(file)

        if not sfile.exists():
            Log.error(f"Could not find the file \"{sfile}\"!", self.ocr)

            return sfile

        if self._install_failed:
            return sfile

        if not self.installed and not self.install():
            return sfile

        if x := self._run_method("__run", *args, file=sfile, **kwargs):
            return x

        Log.warn(f"No OCR method found for \"{self.program_name}\"!", self.ocr)

        return sfile

    def install(self, *args: Any, **kwargs: Any) -> bool:
        """Install the current member. Returns a bool representing success."""
        if self.installed:
            return self.installed

        Log.info(f"Trying to install \"{self.program_name}\" and its dependencies...", self.install)

        return self._run_method("__install", *args, **kwargs)

    def __run_vobsubocr(self, file: SPath, *args: Any, **kwargs: Any) -> SPath:
        out = file.with_suffix(".srt")

        if not (idx := self._check_idx_exists(out)):
            return file

        kwargs_params = [v for p in zip([f"-{k}" for k in kwargs.keys()], list(kwargs.values())) for v in p]

        cmd = run_cmd(["vobsubocr", "-l"] + list(args) + kwargs_params + ["-o", out.to_str(), idx.to_str()])

        if not cmd or out.exists():
            Log.error(f"There was an error while using \"{self.name.lower()}\"!")

            return file

        return out

    def __run_pgsrip(self, file: SPath, *args: Any, **kwargs: Any) -> SPath:
        from pgsrip import Options, Sup, pgsrip

        out = file.with_suffix(".srt")

        if not pgsrip.rip(Sup(file.to_str()), Options(**kwargs)) or not out.exists():
            Log.error(f"There was an error while using \"{self.name.lower()}\"!")

            return file

        return out

    def __run_subextractor(self, file: SPath, ass: bool = True, *args: Any, **kwargs: Any) -> SPath:
        out = file.with_suffix(".ass" if ass else ".srt")

        Log.info(f"Running SubExtractor. You MUST save the output file to \"{out.resolve()}\"!", self.ocr)

        run_cmd(self.installed)

        return out

    def __run_subtitleedit(
        self, file: SPath, ass: bool = False,
        ref: vs.VideoNode | None = None,
        *args: Any, **kwargs: Any
    ) -> SPath:
        """https://www.nikse.dk/subtitleedit/help#commandline"""
        out = file.with_suffix(".ass" if ass else ".srt")

        clip_args = []

        if ref:
            clip_args = [f"/fps:{ref.fps.numerator // 1001}"]

        run_cmd([self.installed, "/convert", file, "ass" if ass else "subrip"] + clip_args)

        return out

    def __install_vobsubocr(self, *args: Any, **kwargs: Any) -> bool:
        if self._install_failed:
            return False

        if not check_program_installed("cargo", "https://www.rust-lang.org/tools/install", True):
            return self._set_install_failed()

        if not IsWindows:
            Log.error("I do not know how to build this on Unix. Please build it yourself!", self.install)

            return self._set_install_failed()

        if not os.environ.get("LIBCLANG_PATH", False):
            if not check_program_installed("C:/msys64/mingw64.exe"):
                Log.info("Installing msys2, this may take a bit...", self.install)

                msys2 = temp_download("https://repo.msys2.org/distrib/x86_64/msys2-x86_64-20230718.exe")
                run_cmd([msys2, "install", "clang"])

            clang = SPath("C:/msys64/clang64.exe")

            if not clang.exists():
                Log.error("Could not install dependency: \"clang\"!", self.install)

                return self._set_install_failed()

            os.environ["LIBCLANG_PATH"] = clang.parent.to_str()

            run_cmd(["C:/msys64/mingw64.exe", "install", "mingw32-base", "mingw-developer-toolkit", "msys-base"])

        repo = SPath("vcpkg")

        if not check_program_installed(repo / "vcpkg.exe"):
            repo = clone_git_repo("https://github.com/microsoft/vcpkg")

            run_cmd([repo / "bootstrap-vcpkg.bat", "-disableMetrics"])
            run_cmd([repo / "vcpkg", "integrate", "install"])

        run_cmd([repo / "vcpkg", "install", "leptonica", "--triplet=x64-windows-static-md"])

        if (x := SPath("InstallationLog.txt")).exists():
            x.unlink(missing_ok=True)

        if not cargo_build("https://github.com/elizagamedev/vobsubocr"):
            return self._set_install_failed()

        return self.installed

    def __install_pgsrip(self, *args: Any, **kwargs: Any) -> bool:
        if self._install_failed:
            return False

        if not check_program_installed("tesseract", "https://codetoprosper.com/tesseract-ocr-for-windows/", True):
            return self._set_install_failed()

        if install_package(self.program_name) is False:
            return self._set_install_failed()

        try:
            clone_git_repo("https://github.com/tesseract-ocr/tessdata_best.git")
        except Exception as e:
            if not "exit code(128)" in str(e):
                Log.error(
                    f"Some kind of error occurred while cloning the \"tessdata_best\" repo!\n{e}",
                    self.__install_pgsrip
                )

                return self._set_install_failed()

        return self.installed

    def __install_subextractor(self, *args: Any, **kwargs: Any) -> bool:
        if self._install_failed:
            return False

        if not (x := temp_download(
            "https://www.digital-digest.com/software/getdownload.php?sid=2245&did=1"
            "&code=4hpfb3lK&decode=c58bdbe4625585881a03b5fa2df2e1d1",
            "SubExtractor1032d.zip")
        ):
            return self._set_install_failed()

        return unpack_zip(x, location=SPath.cwd().to_str())

    def __install_subtitleedit(self) -> bool:
        if self._install_failed:
            return False

        if not (x := temp_download(
            "https://github.com/SubtitleEdit/subtitleedit/releases/download/4.0.1/SubtitleEdit-4.0.1-Setup.exe"
        )):
            return self._set_install_failed()

        if not run_cmd([x]):
            return self._set_install_failed()

        if not self.installed:
            Log.error("The program was not installed correctly!", self.install)
            self._set_install_failed()

        return self.installed

    def _set_install_failed(self) -> Literal[False]:
        """Sets `self._install_failed=True` and returns `False` to indicate install was unsuccesful."""
        self._install_failed = True

        return False

    def __check_installed_vobsubocr(self, *args: Any, **kwargs: Any) -> bool:
        return check_program_installed(self.program_name)

    def __check_installed_pgsrip(self, *args: Any, **kwargs: Any) -> bool:
        return check_package_installed(self.program_name)

    def __check_installed_subextractor(self, *args: Any, **kwargs: Any) -> bool:
        if x := check_program_installed("DvdSubExtractor"):
            return x

        if (x := (SPath.cwd() / "_binaries" / "SubExtractor1032d" / "DvdSubExtractor.exe")).exists():
            return x

        return x

    def __check_installed_subtitleedit(self, *args: Any, **kwargs: Any) -> bool:
        if x := check_program_installed("subtitleedit-cli"):
            return x

        if (x := SPath("C:/") / "Program Files" / "Subtitle Edit" / "SubtitleEdit.exe"):
            return x

        return x

    def _check_idx_exists(self, file: SPathLike) -> SPath | Literal[False]:
        idx = SPath(file).with_suffix(".idx")

        if not (x := idx.exists()):
            Log.error(f"Accompanying \".idx\" file for \"{file}\" not found!", self.ocr)

            return x

        return idx

    @property
    def _install_failed(self) -> bool:
        return self.installed or False  # TODO: Add better checks

    def _run_method(self, prefix: str, *args: Any, **kwargs: Any) -> Any:
        """Try to find and run a method using self's name and a prefix."""
        method = f"{prefix}_{self.program_name}"

        if method.startswith("__"):
            method = f"_{self.__class__.__name__}{method}"

        if hasattr(OcrProgram, method):
            return getattr(OcrProgram, method)(self, *args, **kwargs)

        Log.debug(f"Could not find \"{self}.{method}\"!", self._run_method)

        return False

    @property
    def program_name(self) -> str:
        return str(self).lower()

    @property
    def installed(self) -> bool | Any:
        return self._run_method("__check_installed")
