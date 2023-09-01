from typing import Any
from configparser import ConfigParser
import os
from vstools import SPath
from ..util.logging import Log

__all__: list[str] = [
    "touch_ini"
]

def touch_ini(
    name: str, sections: list[str] | str,
    fields: list[dict[str, Any]] | dict[str, Any] = [],
    raise_on_new: bool = True, caller: str = ""
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
    config = ConfigParser()

    if isinstance(sections, str):
        sections = [sections]

    if isinstance(fields, dict):
        fields = [fields]

    if not os.path.exists(name):
        Log.info(f"Writing {SPath(name).resolve()}...", caller)

        for section, field_dict in zip(sections, fields):
            config[section] = field_dict

            with open(name, "w") as f:
                config.write(f)

            if raise_on_new:
                raise Log.error(f"Template config created at {SPath(name).resolve()}.\nPlease configure it!")

    config.read(name)

    return config
