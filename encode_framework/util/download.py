import subprocess
import sys
import shutil
from importlib.util import find_spec

from .logging import Log
from ..types import TrueOutputs

__all__: list[str] = [
    "cargo_build",
    "check_package_installed",
    "check_program_installed",
    "iew_latest",
    "install_package",
    "run_cmd",
]

# TODO: Improve a bunch of these.


def check_package_installed(pkg: str) -> bool:
    """Check whether the given Python package is installed."""
    return (pkg in sys.modules) or (find_spec(pkg) is not None)


def install_package(pkg: str, extra_params: list[str] = [], prompt: bool = False) -> bool:
    """Install a given Python package."""
    Log.info(f"Installing \"{pkg}\" via pip!", install_package)

    if prompt and not input("Continue with this process? [Y/n] ").strip().lower() in TrueOutputs:
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


def check_binary_installed(exe: str) -> bool:
    """Check whether the given binary is installed."""
    return bool(shutil.which(exe))  # TODO: Add _binaries dir check


def check_program_installed(program: str, installer: str | None = None, _raise: bool = False) -> bool:
    """Check whether a program is installed and raise a FileNotFoundError if it isn't."""
    if not shutil.which(program):
        if not _raise:
            return False

        raise FileNotFoundError(
            f"\"{program}\" could not be found on this system! "
            "If you've installed it, you may need to add it to your PATH."
            + f" Installation instructions: \"{installer}\"" if installer else ""
        )

    return True


def cargo_build(package: str) -> bool:
    """Attempt to build a given cargo package."""
    check_program_installed("cargo", "https://www.rust-lang.org/tools/install/", _raise=True)

    try:
        subprocess.run(["cargo", "install", str(package)], shell=True)
    except subprocess.SubprocessError as e:
        raise ValueError(f"An error occurred while trying to build this cargo! \n{str(e)}")

    return True


def run_cmd(params: list[str] = [], shell: bool = True) -> bool:
    """Try to run a commandline instance with the given params."""
    try:
        subprocess.run(list(str(param) for param in params), shell=shell)
    except subprocess.SubprocessError as e:
        raise ValueError(f"An error occurred while trying to run this command! \n{str(e)}")

    return True
