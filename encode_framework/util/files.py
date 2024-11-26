
from vstools import SPath

__all__: list[str] = [
    "get_script_path",
]


def get_script_path() -> SPath:
    import __main__

    return SPath(__main__.__file__)
