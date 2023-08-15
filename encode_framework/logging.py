"""
    Largely stolen and rewritten from muxtools.
"""
import logging
import sys
import time
from configparser import ConfigParser
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Literal

from rich.logging import RichHandler
from vstools import CustomError

from .config import Config

__all__: list[str] = [
    "Logger",
    "Log"
]


class Logger:
    """Logger class."""

    logger: logging.Logger
    """The logger object."""

    log_file: Path | Literal[False] = False
    """Path to the log file."""

    def __init__(
        self, logger_name: str | None = None,
        log_file: Path | None | Literal[False] = None,
        format: str = "%(name)s | %(message)s",
        datefmt: str = "[%X]",
        **kwargs: Any
    ) -> None:
        log_name = logger_name or "Project"

        if Config.config_path.exists():
            if not logger_name:
                log_name = Config.config_parsed.get("SETUP", "show_name") or log_name

        log_name = log_name.replace(" ", "_")

        if log_file is None:
            log_file = Path() / Path(f"{log_name}.log")

        self.log_file = log_file

        logging.basicConfig(
            format=format, datefmt=datefmt,
            handlers=[RichHandler(markup=True, omit_repeated_times=False, show_path=False)],
        )

        log_name_join = "_".join([log_name, "Script"])
        self.logger = logging.getLogger(log_name_join)

        self.logger.setLevel(logging.INFO)

        if Config.config_path.exists():
            if Config.is_debug:
                self.logger.setLevel(logging.DEBUG)

            if logger_name is None:
                self.debug(f"Config file found, logger name: \"{log_name_join}\"", "logging")

        if self.log_file:
            self.debug(f"Writing to log file \"{self.log_file}\"", "logging")

    def _format_msg(self, msg: str | bytes, caller: str | Callable[[Any], Any] | None) -> str:
        if caller and not isinstance(caller, str):
            caller = caller.__class__.__qualname__ if hasattr(caller, "__class__") \
                and caller.__class__.__name__ not in ["function", "method"] else caller

            caller = caller.__name__ if not isinstance(caller, str) else caller

        if isinstance(msg, bytes):
            msg = msg.decode("utf-8")

        return msg if caller is None else f"[bold]{caller}:[/] {msg}"

    def _write(self, formatted_msg: str, caller: str | Callable[[Any], Any] | None) -> None:
        if not self.log_file:
            return

        if caller and not isinstance(caller, str):
            caller = caller.__class__.__qualname__ if hasattr(caller, "__class__") \
                and caller.__class__.__name__ not in ["function", "method"] else caller

            caller = caller.__name__ if not isinstance(caller, str) else caller

        formatted_msg = formatted_msg \
            .replace("[bold]", "") \
            .replace("[/]", "")

        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        self.log_file.touch(exist_ok=True)

        with open(self.log_file, "a") as f:
            f.write(f"{datetime.now()} | [{str(caller).upper()}] {formatted_msg}\n")

    def crit(self, msg: str | bytes, caller: str | Callable[[Any], Any] | None = None) -> Exception:
        message = self._format_msg(msg, caller)

        if self.log_file:
            self._write(message, self.crit)

        self.logger.critical(message)

        return Exception(message)

    def debug(self, msg: str | bytes, caller: str | Callable[[Any], Any] | None = None, force: bool = False) -> None:
        if not Config.config_path.exists():
            return

        if not self.is_debug and not force:
            return

        message = self._format_msg(msg, caller)

        if self.log_file:
            self._write(message, self.debug)

        self.logger.debug(message)

    def info(self, msg: str | bytes, caller: str | Callable[[Any], Any] | None = None) -> None:
        message = self._format_msg(msg, caller)

        if self.log_file:
            self._write(message, self.info)

        self.logger.info(message)

    def warn(self, msg: str | bytes, caller: str | Callable[[Any], Any] | None = None, sleep: int = 0) -> None:
        message = self._format_msg(msg, caller)

        if self.log_file:
            self._write(message, self.warn)

        self.logger.warning(message)

        if sleep:
            time.sleep(sleep)

    def error(
        self, msg: str | bytes, caller: str | Callable[[Any], Any] | None = None,
        custom_exception: CustomError | Exception | None = None, tb_limit: int = 2, **kwargs: Any
    ) -> Exception:
        message = self._format_msg(msg, caller)

        if self.log_file:
            self._write(message, self.error)

        self.logger.error(message)

        sys.tracebacklimit = tb_limit

        if custom_exception is not None:
            raise custom_exception(msg, caller, **kwargs)  # type:ignore[operator]

        return Exception(message)

    def exit(self, msg: str | bytes, caller: str | Callable[[Any], Any] | None = None) -> None:
        message = self._format_msg(msg, caller)

        if self.log_file:
            self._write(message, self.exit)

        self.logger.info(message)

        sys.exit(0)

    @property
    def is_debug(self) -> bool:
        return self.logger.getEffectiveLevel() <= 10


Log = Logger()
