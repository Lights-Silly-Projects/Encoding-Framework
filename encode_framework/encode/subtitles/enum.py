import os
from enum import Enum, auto
from typing import Any

from vstools import SPath, SPathLike

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
        pfile = SPath(file)

        if x := self._run_method("__run_", pfile, *args, **kwargs):
            return x

        Log.warn(f"No OCR method found for \"{self.program_name}\"!", self.ocr)

        return pfile

    def install(self) -> bool:
        """Install the current member. Returns a bool representing success."""
        if self.installed:
            return self.installed

        Log.info(f"Trying to install \"{self.program_name}\" and its dependencies!", self.install)

        self._run_method("__install_")

    def __run_vobsubocr(self, file: SPath, *args: Any, **kwargs: Any) -> SPath:
        out = file.with_suffix(".srt")
        idx = file.with_suffix(".idx")

        if not idx.exists():
            Log.error(f"Accompanying \".idx\" file for \"{file}\" not found!", self.ocr)

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

    def __install_vobsubocr(self) -> bool:
        if not check_program_installed("cargo", "https://www.rust-lang.org/tools/install", True):
            return False

        if not IsWindows:
            Log.error("I do not know how to build this on Unix. Please build it yourself!", self.install)

            return False

        if not os.environ.get("LIBCLANG_PATH", False):
            if not check_program_installed("C:/msys64/mingw64.exe"):
                Log.info("Installing msys2, this may take a bit...", self.install)

                msys2 = temp_download("https://repo.msys2.org/distrib/x86_64/msys2-x86_64-20230718.exe")
                run_cmd([msys2, "install", "clang"])

            clang = SPath("C:/msys64/clang64.exe")

            if not clang.exists():
                Log.error("Could not install dependency: \"clang\"!", self.install)

                return False

            os.environ["LIBCLANG_PATH"] = clang.parent.to_str()

            run_cmd(["C:/msys64/mingw64.exe", "install", "mingw32-base", "mingw-developer-toolkit", "msys-base"])

        repo = SPath("vcpkg")

        if not check_program_installed(repo / "vcpkg.exe"):
            repo = clone_git_repo("https://github.com/microsoft/vcpkg")

            run_cmd([str(repo / "bootstrap-vcpkg.bat"), "-disableMetrics"])
            run_cmd([str(repo / "vcpkg"), "integrate", "install"])

        run_cmd([str(repo / "vcpkg"), "install", "leptonica", "--triplet=x64-windows-static-md"])

        if (x := SPath("InstallationLog.txt")).exists():
            x.unlink(missing_ok=True)

        if not cargo_build("https://github.com/elizagamedev/vobsubocr"):
            return False

        return self.installed

    def __install_pgsrip(self) -> bool:
        if x := check_program_installed("tesseract", "https://codetoprosper.com/tesseract-ocr-for-windows/", True):
            return x

        if (x := install_package(self.program_name)) is False:
            return x

        try:
            clone_git_repo("https://github.com/tesseract-ocr/tessdata_best.git")
        except Exception as e:
            if not "exit code(128)" in str(e):
                Log.error(
                    f"Some kind of error occurred while cloning the \"tessdata_best\" repo!\n{e}",
                    self.__install_pgsrip
                )

                return False

        return self.installed

    def _run_method(self, prefix: str, **kwargs: Any) -> Any:
        """Try to find and run a method using self's name and a prefix."""
        method = f"{prefix}{self.program_name}"

        if method.startswith("__"):
            method = f"_{self.__class__.__name__}{method}"

        if hasattr(OcrProgram, method):
            return getattr(OcrProgram, method)(self, **kwargs)

        Log.warn(f"Could not find \"{self}.{method}\"!", self._run_method)

        return False

    @property
    def program_name(self) -> str:
        return str(self)

    @property
    def installed(self) -> bool:
        return check_package_installed(self.program_name)
