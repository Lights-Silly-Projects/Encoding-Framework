"""
    An FTP module, created to automatically upload or download files to or from an FTP.
"""
from vstools import SPath, SPathLike, CustomNotImplementedError
from configparser import ConfigParser
from ftplib import FTP

from .logging import Log
from .util import create_gitignore

__all__: list[str] = [
    "Ftp"
]

class Ftp:
    """Class representing an FTP worker."""

    ftp_conn: FTP
    """An FTP object containing information about the connection."""

    config_file: SPath
    """Config file containing all the login and destination information."""

    config_parsed: ConfigParser
    """Parsed config file."""

    sftp: bool
    """Whether this is a SFTP connection."""

    host: str
    """The address to connect to."""

    port: int | None = None
    """The port to connect to."""

    username: str
    """The username to connect with."""

    password: str
    """The accompanying password for the username."""

    upload_directory: SPath
    """The directory to upload the files to."""

    def __init__(self, config_file: SPathLike = "ftp.ini") -> None:
        raise CustomNotImplementedError(None, self)
        self.config_file = SPath(config_file).with_suffix(".ini")

        self.config_parsed = ConfigParser()
        self.config_parsed.read(self.config_file)

        if not self.config_parsed.has_section("FTP"):
            self._create_basic_config()

            raise Log.crit("Please set up the FTP config file before continuing!", self.__class__.__name__)

        self.ftp_conn = FTP(
            self.config_parsed.get("FTP", "host"),
            self.config_parsed.get("FTP", "username"),
            self.config_parsed.get("FTP", "password")
        )

        self.ftp_conn.port = self.config_parsed.get("FTP", "port")

        self.ftp_conn.login(
            self.config_parsed.get("FTP", "username"),
            self.config_parsed.get("FTP", "password")
        )

    def _create_basic_config(self) -> None:
        self.config_parsed.add_section("FTP")

        self.config_parsed.set("FTP", "sftp", "True")

        for val in ("host", "port", "username", "password"):
            self.config_parsed.set("FTP", val, "Please set a value!" if not val == "port" else None)

        self.config_parsed.set("FTP", "upload_directory", "/")

        with open(self.config_file, "w") as f:
            self.config_parsed.write(f)

        # We really don't want users accidentally pushing these files to a public repo...
        if not SPath(".gitignore").exists():
            create_gitignore(options=[self.config_file])

    def get_welcome(self) -> None:
        ...

    def upload(self) -> None:
        ...
