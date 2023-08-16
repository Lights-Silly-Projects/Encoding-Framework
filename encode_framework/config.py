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

        self.ftp_config = ConfigParser()
        self.ftp_path = self.config_path.parent / "ftp.ini"

        self.discord_config = ConfigParser()
        self.discord_path = self.config_path.parent / "discord.ini"

    # TODO: Set properties for every key:value pair found in the config file.
    def set_properties(self) -> None:
        raise NotImplementedError

    def create_ftp_config(self) -> None:
        """Add a section for (S)FTP information."""
        if not self.discord_path.exists():
            from .logging import Log

            Log.debug("Creating FTP config file and .gitignore...")

            self.ftp_config.add_section("FTP")
            self.ftp_config.set("ftp", "host", "")
            self.ftp_config.set("ftp", "port", "")
            self.ftp_config.set("ftp", "sftp", "True")
            self.ftp_config.set("ftp", "username", "")
            self.ftp_config.set("ftp", "password", "")
            self.ftp_config.set("ftp", "upload_dir", "/")

            with open(self.ftp_path, "w") as f:
                self.ftp_config.write(f)

        if not (self.config_path.parent / ".gitignore").exists():
            create_gitignore(options=["ftp.ini"])

    def create_discord_config(self) -> None:
        """Add a section for Discord webhook information."""
        if not self.discord_path.exists():
            from .logging import Log

            Log.debug("Creating Discord config file and .gitignore...")

            self.discord_config.add_section("DISCORD")
            self.discord_config.set("discord", "name", "EncodeRunner")
            self.discord_config.set("discord", "avatar", "https://avatars.githubusercontent.com/u/88586140")
            self.discord_config.set("discord", "webhook", "")

            with open(self.discord_path, "w") as f:
                self.discord_config.write(f)

        if not (self.config_path.parent / ".gitignore").exists():
            create_gitignore(options=["discord.ini"])

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
