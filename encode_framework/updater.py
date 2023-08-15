"""
    Self-auto-updater module. This is run automatically every time code is ran.
"""
import os
import subprocess
from datetime import datetime
from pathlib import Path

from .config import Config
from .logging import Log

__all__: list[str] = [
    "self_update"
]


def self_update(
    gh_package: str = "Lights-Silly-Projects/Encoding-Framework",
    timeout: int = 30, last_update_thr: int = 21600
) -> None:
    """
    Automatically updates the package to the latest version found in the repo.

    This function will try to be conservative about when to update, but no promises are made!

    This function is largely based off of the following blog post:
    <https://abhinav1107.github.io/blog/auto-update-a-python-package-using-git-repository/>_

    :param gh_package:      Name of the package on GitHub. Defaults to Light's encoding framework.
    :param timeout:         Seconds until a timeout is hit when trying to perform certain actions.
                            Default: 10 seconds.
    :param last_update_thr: Threshold for the time since it was last checked in seconds.
                            If the time since it last checked does not exceed this,
                            it will not try to auto-update.
                            Default: Check every 6 hours.
    """
    if not Config.auto_update:
        Log.debug("Auto-updating disabled... Not running auto-updater.", self_update)

        return

    try:
        from fcntl import flock, LOCK_EX, LOCK_NB, LOCK_UN
    except ModuleNotFoundError:
        Log.debug(
            "Could not access the \"fcntl\" package... Are you on 32-bit Windows? Aborting auto-update.",
            self_update
        )

        return

    # We first check how long ago the updater was last run.
    current_dir = Path.cwd()
    last_checked_file = current_dir / ".encode/last_checked.ignore"

    try:
        with open(last_checked_file, "a"):
            os.utime(str(last_checked_file), None)
    except EnvironmentError:
        Log.error("Could not write to status file... Aborting auto-update.", self_update)

        return

    with open(last_checked_file, "r") as f:
        last_update_run = f.read().strip()

    if not last_update_run:
        last_update_run = 0

    last_update_run = int(last_update_run)

    current_time = int((datetime.utcnow() - datetime(1970, 1, 1)).total_seconds() * 1000)

    if (current_time - last_update_run) < last_update_thr:
        return

    with open(last_checked_file, "w") as f:
        try:
            flock(f, LOCK_EX | LOCK_NB)
        except IOError:
            return

    try:
        Log.info("Trying to auto-update encoding framework...", self_update)

        subprocess.check_output(["pip", "install", f"git+github.com/{gh_package}", "--force"], timeout=timeout)
        f.write(current_time)

        Log.info("Succesfully auto-updated encoding framework!", self_update)
    except subprocess.CalledProcessError as e:
        Log.error("Failed to auto-update encoding framework!", self_update)
        Log.debug(e, self_update)
    finally:
        flock(f, LOCK_UN)
