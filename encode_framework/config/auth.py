import getpass
from configparser import ConfigParser

from lautils import get_all_functions, get_caller_module
from vstools import SPath

from .base import add_section, touch_ini

__all__: list[str] = [
    "setup_auth"
]


def setup_auth() -> ConfigParser:
    """Create the auth file."""
    from . import auth

    filepath = SPath("auth.ini")

    touch_ini(filepath)

    for name, func in get_all_functions(auth):
        if not name.startswith("__auth__"):
            continue

        func(filepath)

    config = ConfigParser()
    config.read(filepath)

    return config


def __auth__add_discord(file_path: SPath, caller: str | None = None) -> ConfigParser:
    """Add discord auth information."""
    if not caller:
        caller = get_caller_module()

    return add_section(file_path, "DISCORD", {
        "system_name": getpass.getuser(),
        "webhook_url": "https://support.discord.com/hc/en-us/articles/228383668-Intro-to-Webhooks"
    })


def __auth__add_ftp(file_path: SPath, caller: str | None = None) -> ConfigParser:
    """Add (S)FTP auth information."""
    if not caller:
        caller = get_caller_module()

    return add_section(file_path, "FTP", {
        "host": "", "port": "", "sftp": False,
        "username": "", "password": "",
        "upload_dir": "/"
    })
