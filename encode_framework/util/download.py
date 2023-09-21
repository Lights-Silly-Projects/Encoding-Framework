import shutil
import subprocess
import sys
from importlib.util import find_spec
from pathlib import Path
from tempfile import gettempdir
from typing import Any, overload
from typing import Any, Literal, overload
from urllib.request import urlretrieve
from zipfile import ZipFile

from ..types import TruthyInput
from .logging import Log

__all__: list[str] = [
    "cargo_build",
    "check_package_installed",
    "check_program_installed",
    "iew_latest",
    "install_package",
    "run_cmd",
    "temp_download",
    "unpack_zip",
    "install_docker",
]

# TODO: Improve a bunch of these.


def check_package_installed(pkg: str) -> bool:
    """Check whether the given Python package is installed."""
    return (pkg in sys.modules) or (find_spec(pkg) is not None)


def install_package(pkg: str, extra_params: list[str] = [], prompt: bool = False) -> bool:
    """Install a given Python package."""
    Log.info(f"Installing \"{pkg}\" via pip!", install_package)

    if prompt and not input("Continue with this process? [Y/n] ").strip().lower() in TruthyInput:
        return False

    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", pkg] + extra_params)
    except subprocess.CalledProcessError as e:
        Log.error(str(e))

        return False

    return True


def iew_latest() -> None:
    """Forcibly update all IEW packages to latest via `vsiew latest`."""
    try:
        subprocess.check_call([sys.executable, "-m", "vsiew", "latest"])
    except subprocess.CalledProcessError as e:
        raise Log.error(str(e))


def check_program_installed(program: str, installer: str | None = None, warn: bool = False) -> bool:
    """
    Check whether a program is installed and warn the user if it isn't.

    :param program:         The program you're looking for as called in the terminal.
    :param installer:       An optional string including installation instructions.
                            In most cases, this will be a link to an installer.
    :param warn:            Whether to warn the user about the missing program.

    :return:                Bool representing whether the program is installed or not.
    """
    if x := bool(shutil.which(program)):
        return x

    if warn:
        Log.warn(
            f"The program \"{program}\" could not be found on this system! "
            "If you've installed it, you may need to add it to your PATH. "
            + f"Installation instructions: \"{installer}\"" if installer else "",
            check_program_installed
        )

    return x


def cargo_build(package: str) -> bool:
    """Attempt to build a given cargo package."""
    if not check_program_installed("cargo", "https://www.rust-lang.org/tools/install/", warn=True):
        return False

    params = ["cargo", "install"]

    if "github.com" in package:
        params += ["--git"]

    params += [str(package)]

    try:
        subprocess.run(params, shell=True)
    except subprocess.SubprocessError as e:
        Log.warn(f"An error occurred while trying to build the cargo for {package}! \n{str(e)}")

        return False

    return True


def run_cmd(params: list[str] = [], shell: bool = True) -> bool:
    """Try to run a commandline instance with the given params."""
    p = list(str(param) for param in params)

    try:
        subprocess.run(p, shell=shell)
    except subprocess.SubprocessError as e:
        Log.error(
            f"An error occurred while trying to run this command! \n{str(e)}\n"
            f"Command run: {p}", run_cmd
        )

        return False

    return True


def temp_download(url: str, filename: str | None = None) -> Path:
    """Install the latest package from a direct link using curl."""
    if filename is None:
        filename = url.split("/")[-1]

    out = urlretrieve(url, f"{gettempdir()}/{filename}")[0]

    out_file = Path(out)

    if not out_file.exists():
        raise FileNotFoundError(f"The file \"{out}\" was not found!")

    return out_file


@overload
def unpack_zip(path: str, file_to_extract: str | None = None, **kwargs: Any) -> list[str]:
    ...

@overload
def unpack_zip(path: str, file_to_extract: str | None = "", **kwargs: Any) -> str:
    ...

def unpack_zip(path: str, file_to_extract: str | None = None, **kwargs: Any) -> list[str] | str:
    """Try to unpack a zip file. Returns either an individual filepath or a list of extracted contents."""
    zip_file = Path(path)

    if not zip_file.exists():
        raise ValueError(f"Could no find the path \"{path}\"!")

    out_dir = zip_file.parent / zip_file.stem
    out_dir.mkdir(exist_ok=True)

    with ZipFile(zip_file) as z:
        if file_to_extract:
            return z.extract(file_to_extract, out_dir, **kwargs)

        z.extractall(out_dir, **kwargs)

    return list(str(x) for x in out_dir.glob("*"))
def install_docker() -> str | Literal[False]:
    docker_pf_path = Path("C:/") / "Program Files" / "Docker" / "Docker" / "resources" / "bin" / "docker.exe"
    docker_param = "docker"

    if check_program_installed(docker_param):
        return docker_param
    elif docker_pf_path.exists():
        return docker_pf_path

    if not (x := temp_download(
        "https://desktop.docker.com/win/main/amd64/Docker%20Desktop%20Installer.exe?utm_source=docker&utm_medium=webreferral&utm_campaign=dd-smartbutton&utm_location=module",
        "Docker Desktop Installer.exe"
    )):
        return x

    run_cmd(x)

    return docker_param
