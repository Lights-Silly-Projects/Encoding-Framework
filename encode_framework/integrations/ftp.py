"""
    An FTP module, created to automatically upload or download files to or from an FTP.
"""
from stgpytools import SPath, SPathLike, CustomNotImplementedError, CustomError
from configparser import ConfigParser, NoSectionError, NoOptionError
from ftplib import FTP

from encode_framework.config.base import add_option, get_option
from ..util.logging import Log
from ..git.ignore import append_gitignore

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

    def __init__(self) -> None:
        from ..config.auth import setup_auth

        auth = setup_auth()

        if not auth.has_section("FTP"):
            self._create_basic_config()

            raise Log.error(
                "New section \"FTP\" added to \"auth.ini\". Please set it up first!",
                self.__class__.__name__,
                CustomError[NoSectionError]
            )

        self.config_parsed = auth

        if not (sftp := auth.getboolean("FTP", "sftp")):
            raise CustomNotImplementedError(
                "Non-SFTP connections are currently not supported!",
                self.__class__.__name__
            )
        else:
            self._create_sftp_config()

        self.sftp = sftp

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
            append_gitignore(options=[self.config_file])

    def _hasopt(self, key) -> bool:
        return self.config_parsed.has_option("FTP", key)

    def _getopt(self, key, fallback=None, *, raw=False) -> str:
        return self.config_parsed.get("FTP", key, fallback=fallback, raw=raw)

    def _create_sftp_config(self) -> None:
        if not (self._hasopt("host") and self._hasopt("username") and self._hasopt("password")):
            missing = ', '.join(k for k in ('host', 'username', 'password') if not self._hasopt(k))

            raise Log.error(
                f"Please configure the missing FTP settings! Missing key(s): {missing}",
                self.__class__.__name__, CustomError[NoOptionError]
            )

        self.host = self._getopt("host")
        self.port = int(self._getopt("port", 22))
        self.username = self._getopt("username")
        self.password = self._getopt("password", raw=True)
        self.upload_directory = SPath(self._getopt("upload_dir", "/"))

        Log.debug(f"SFTP setup complete. Uploading to \"{self.address}\"", self.__class__.__name__)

    def get_welcome(self) -> None:
        ...

    def upload(self, target_file: SPath) -> None:
        """Upload the given file to the FTP following the details given in \"auth.ini\"."""
        import pysftp  # type:ignore[import]

        if not self.sftp:
            raise Log.error(
                "Only SFTP connections are currently supported!",
                self.upload, CustomNotImplementedError  # type:ignore[arg-type]
            )

        with pysftp.Connection(self.host, self.username, None, self.password) as sftp:
            with sftp.cd(self.upload_directory):
                Log.info(f"Uploading \"{target_file}\" to \"{self.address}\"", self.upload)

                sftp.put(target_file)

    @property
    def address(self) -> str:
        return f"{self.username}@{self.host}:{self.port}:{self.upload_directory}"
