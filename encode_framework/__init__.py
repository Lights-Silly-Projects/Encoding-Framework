from vsmuxtools import Setup  # type:ignore[import]

from .config import *  # noqa: F401, F403
from .encode import *  # noqa: F401, F403
from .filter import *  # noqa: F401, F403
from .git import *  # noqa: F401, F403
from .integrations import *  # noqa: F401, F403
from .script import *  # noqa: F401, F403
from .types import *  # noqa: F401, F403
from .util import *  # noqa: F401, F403

# Forcibly create config files before we do anything.
setup_auth()

try:
    Setup()
except Exception as e:
    create_anilist_section()

    raise e

del Setup

create_anilist_section()
