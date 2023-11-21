"""
    An FTP module, created to automatically upload or download files to or from an FTP.
"""
from vstools import SPath, SPathLike, CustomNotImplementedError, CustomValueError
from configparser import ConfigParser
from ftplib import FTP

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

    def __init__(self, config_file: SPathLike = "ftp.ini") -> None:
        from ..config.auth import setup_auth
        
        auth = setup_auth()
        if auth.has_section("FTP") and auth.has_option("FTP", "sftp") and auth.getboolean("FTP", "sftp"):
            # valid(?) sftp config found
            self.config_parsed = auth
            self._create_sftp_config()
            self.sftp = True
            return
        
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
            append_gitignore(options=[self.config_file])

    def _hasopt(self, key) -> bool:
        return self.config_parsed.has_option("FTP", key)
    
    def _getopt(self, key, fallback=None, *, raw=False) -> str:
        return self.config_parsed.get("FTP", key, fallback=fallback, raw=raw)

    def _create_sftp_config(self) -> None:
        if not (self._hasopt("host") and self._hasopt("username") and self._hasopt("password")):
            missing = ', '.join(k for k in ('host', 'username', 'password') if not self._hasopt(k))
            Log.warn(f"Please configure FTP settings! Missing key(s): {missing}", self.__class__.__name__)
            raise CustomValueError(f"FTP settings missing one or more required values: {missing}")

        self.host = self._getopt("host")
        self.port = int(self._getopt("port", 22))
        self.username = self._getopt("username")
        self.password = self._getopt("password", raw=True)
        self.upload_directory = self._getopt("upload_dir", "/")

        Log.debug(f"Set up SFTP, uploading to {self.username}@{self.host}:{self.port}:{self.upload_directory}", self.__class__.__name__)

    def get_welcome(self) -> None:
        ...

    def upload(self, target_file: SPath) -> None:
        if not self.sftp:
            Log.warn("Only SFTP is supported currently", self.upload)
            raise CustomNotImplementedError("Only SFTP is supported currently", self)
        import pysftp
        with pysftp.Connection(self.host, username=self.username, password=self.password) as sftp:
            with sftp.cd(self.upload_directory):
                Log.info(f"Uploading {target_file} to {self.username}@{self.host}:{self.port}:{self.upload_directory}", self.upload)
                sftp.put(target_file)