from typing import Literal

from typing import overload
from vstools import SPath, SPathLike

from ..types import ByteUnits

__all__: list[str] = [
    "get_script_path",
]


def get_script_path() -> SPath:
    import __main__

    return SPath(__main__.__file__)
