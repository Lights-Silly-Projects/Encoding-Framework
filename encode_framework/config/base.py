from configparser import ConfigParser, NoOptionError, NoSectionError
from itertools import zip_longest
from typing import Any

from lautils import get_caller_module
from vstools import SPath, SPathLike

__all__: list[str] = [
    "touch_ini",

    "add_section",

    "add_option", "get_option",

    "get_items"
]


def touch_ini(
    name: SPathLike, sections: list[str] | str = [],
    fields: list[dict[str, Any]] | dict[str, Any] = [],
    raise_on_new: bool = False, caller: str | None = None
) -> ConfigParser:
    """
    Touch, populate, and sanitize an ini file.

    If the ini file does not exist yet, it will create it.

    Optionally, if `raise_on_new` is True, it will raise an error
    prompting the user to configure the ini file.

    `sections` and `fields` are a list to allow for multiple sections
    to be populated trivially in case they get expanded in the future.

    This is mostly useful for the `auth` config file.
    """
    caller = caller or get_caller_module()

    filename = SPath(name)

    config = ConfigParser()
    config.read(filename.to_str())

    if filename.exists() and not sections:
        return config

    if isinstance(sections, str):
        sections = [sections]

    if isinstance(fields, dict):
        fields = [fields]

    if not filename.exists():
        filename.parent.mkdir(exist_ok=True)

        for section, field_dict in zip(sections, fields):
            config[section] = field_dict

        with open(filename, "w") as f:
            config.write(f)

        if raise_on_new:
            from ..util.logging import Log

            raise Log.error(f"Template config created at {filename.resolve()}.\nPlease configure it!", caller)

    config.read(filename.to_str())

    return config


def add_section(
    name: SPathLike,
    sections: list[str] | str,
    fields: list[dict[str, Any]] | dict[str, Any] = [],
    caller: str | None = None,
    config: ConfigParser | None = None
) -> ConfigParser:
    """Add a new section to a given config file. If the file does not exist, it will create it."""
    caller = caller or get_caller_module()

    filename = SPath(name)

    if not filename.exists():
        return touch_ini(name, sections, fields, caller=caller)

    if not config:
        config_obj = ConfigParser()
        config_obj.read(filename)
    else:
        config_obj = config

    if isinstance(sections, str):
        sections = [sections]

    if isinstance(fields, dict):
        fields = [fields]

    for section, field_dict in zip_longest(sections, fields):
        section = str(section).upper()

        if section == "DEFAULT":
            continue

        if not config_obj.has_section(section):
            config_obj.add_section(section)

        if field_dict:
            for k, v in field_dict.items():
                add_option(filename, section, (k, v), config_obj)

    with open(filename, "w") as f:
        config_obj.write(f)

    return config_obj


def add_option(
    name: SPathLike, section: str, field: tuple[str, Any],
    config: ConfigParser | None = None,
) -> ConfigParser:
    """Add an option to a given config file's section. If a section does not exist, it will create it."""
    filename = SPath(name)

    if not filename.exists():
        from ..util.logging import Log

        raise Log.error(f"The config file \"{filename.name}\" does not exist!", add_option)  # type:ignore[arg-type]

    if not config:
        config_obj = ConfigParser()
        config_obj.read(filename)
    else:
        config_obj = config

    if not config_obj.has_section(section):
        config_obj = add_section(filename, section, config=config_obj)

    if not config_obj.has_option(section, field[0]):
        config_obj.set(section, *(str(f) for f in field))

    with open(filename, "w") as f:
        config_obj.write(f)

    return config_obj


def get_items(
    name: SPathLike, section: str,
    config: ConfigParser | None = None
) -> dict[str, str]:
    """
    Get all items of a specific section from a given config file.

    If the section or its parents do not exist, return an empty string.
    """
    filename = SPath(name)

    if not filename.exists():
        return dict()

    if not config:
        config_obj = ConfigParser()
        config_obj.read(filename)
    else:
        config_obj = config

    try:
        return dict(config_obj.items(section))
    except NoSectionError:
        return dict()


def get_option(
    name: SPathLike, section: str, option: str,
    config: ConfigParser | None = None
) -> str:
    """
    Get a specific option from a given config file and section.

    If the option or its parents do not exist, return an empty string.
    """
    filename = SPath(name)

    if not filename.exists():
        return ""

    if not config:
        config_obj = ConfigParser()
        config_obj.read(filename)
    else:
        config_obj = config

    try:
        return config_obj.get(section, option)
    except (NoOptionError, NoSectionError):
        return ""
