import os
from configparser import ConfigParser
from pathlib import Path

from .util import create_gitignore

__all__: list[str] = [
    "EncodeConfig",
    "Config",
]


class EncodeConfig:
    """A class representing the encoding config file."""

    config_path: Path
    """Path to the project config file."""

    config_parsed: ConfigParser
    """Parsed config file."""

    ftp_config: ConfigParser
    """Parsed ftp config file."""

    discord_config: ConfigParser
    """Parsed Discord config file."""

    def __init__(self, config_file: str = "config.ini") -> None:
        if "/" in config_file:
            self.config_path = Path(config_file)
        else:
            self.config_path = Path.cwd() / config_file

        if not self.config_path.exists():
            raise FileNotFoundError(f"Could not find config file at \"{self.config_path}\"! You MUST create one first!")

        self.config_parsed = ConfigParser()
        self.config_parsed.read(self.config_path)

        self.auth_config = ConfigParser()
        self.auth_path = self.config_path.parent / "auth.ini"

    # TODO: Set properties for every key:value pair found in the config file.
    def set_properties(self) -> None:
        raise NotImplementedError

    def _create_auth_if_not_exists(self) -> None:
        if not self.auth_path.exists():
            self.auth_path.touch(exist_ok=True)

        self.auth_config.read(self.auth_path)

        if not (self.config_path.parent / ".gitignore").exists():
            create_gitignore(options=["auth.ini"])

    def create_ftp_config(self) -> None:
        """Add a section for (S)FTP information."""
        self._create_auth_if_not_exists()

        if self.auth_config.has_section("FTP"):
            return

        from .logging import Log

        Log.debug(f"Adding FTP section to \"{self.auth_path.name}\"...", self.create_ftp_config)

        self.auth_config.add_section("FTP")
        self.auth_config.set("FTP", "host", "")
        self.auth_config.set("FTP", "port", "")
        self.auth_config.set("FTP", "sftp", "False")
        self.auth_config.set("FTP", "username", "")
        self.auth_config.set("FTP", "password", "")
        self.auth_config.set("FTP", "upload_dir", "/")

        with open(self.auth_path, "w") as f:
            self.auth_config.write(f)

    def create_discord_config(self) -> None:
        """Add a section for Discord webhook information."""
        self._create_auth_if_not_exists()

        if self.auth_config.has_section("DISCORD"):
            return

        from .logging import Log

        Log.debug(f"Adding Discord section to \"{self.auth_path.name}\"...", self.create_discord_config)

        self.auth_config.add_section("DISCORD")
        self.auth_config.set("DISCORD", "name", "EncodeRunner")
        self.auth_config.set("DISCORD", "user", os.getlogin() or os.getenv("username") or "")
        self.auth_config.set("DISCORD", "avatar", "https://avatars.githubusercontent.com/u/88586140")
        self.auth_config.set("DISCORD", "webhook", "")

        with open(self.auth_path, "w") as f:
            self.auth_config.write(f)

    def _value_is_true(self, key: str, section: str = "SETUP", default_true: bool = False) -> bool:
        """Check whether a value in the config file is True or False."""
        return self.config_parsed.get(section, key, fallback=default_true).strip().lower() \
            in ("true", "yes", "y", "debug", "1")

    @property
    def is_debug(self) -> bool:
        return self._value_is_true("debug")

    @property
    def auto_update(self) -> bool:
        return self._value_is_true("auto_update", default_true=True)


Config = EncodeConfig()
