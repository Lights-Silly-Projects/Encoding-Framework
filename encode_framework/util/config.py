from configparser import ConfigParser, NoOptionError, NoSectionError

__all__: list[str] = [
    "get_items",
    "get_option",
]


def get_items(file: str, section: str) -> list[tuple[str, str]]:
    """Get all items of a specific section from a given config file."""
    config = ConfigParser()

    config.read(file)

    try:
        return config.items(section)
    except NoSectionError:
        return []


def get_option(file: str, section: str, option: str) -> str:
    """Get a specific option from a given config file and section."""
    config = ConfigParser()

    config.read(file)

    try:
        return config.get(section, option)
    except NoOptionError:
        return ""
