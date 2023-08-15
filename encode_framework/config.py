from configparser import ConfigParser
from pathlib import Path

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

    def __init__(self, config_file: str = "config.ini") -> None:
        if "/" in config_file:
            self.config_path = Path(config_file)
        else:
            self.config_path = Path.cwd() / config_file

        if not self.config_path.exists():
            raise FileNotFoundError(f"Could not find config file at \"{self.config_path}\"! You MUST create one first!")

        self.config_parsed = ConfigParser()
        self.config_parsed.read(self.config_path)

    # TODO: Set properties for every key:value pair found in the config file.
    def set_properties(self) -> None:
        raise NotImplementedError

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
