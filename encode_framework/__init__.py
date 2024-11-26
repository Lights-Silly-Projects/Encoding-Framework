# ruff: noqa: F401, F403, F405

from vsmuxtools import Setup  # type:ignore[import]

from .config import *
from .encode import *
from .filter import *
from .git import *
from .integrations import *
from .script import *
from .types import *
from .util import *

# Forcibly create config files before we do anything.
setup_auth()

try:
    Setup()
except Exception as e:
    create_anilist_section()

    raise e

del Setup

create_anilist_section()
