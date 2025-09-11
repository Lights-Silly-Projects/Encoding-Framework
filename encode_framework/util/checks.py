import re
from typing import Any, Callable

from jetpytools import SPathLike, FuncExcept
from vstools import CustomValueError, SPath, SPathLike

from .logging import Log

__all__: list[str] = ["assert_truthy", "path_has_non_ascii_or_bracket_chars"]


def assert_truthy(var: Any, caller: str | Callable[[Any], Any] | None = None) -> bool:
    """Asserts whether a given variable is truthy. If not, raises a CustomValue log error."""
    if not (x := bool(var)):
        Log.error(
            f'The variable "{var}" is not truthy!',
            caller or assert_truthy,
            CustomValueError,
            4,
        )

    return x


def path_has_non_ascii_or_bracket_chars(
    path: SPathLike, _raise: bool = False, func_except: FuncExcept | None = None
) -> bool:
    """
    Check if the given path contains any non-ASCII characters or brackets.

    This is mostly only useful for programs such as DGIndexNV.

    :param path:            The path to check.
    :param _raise:          Whether to raise an error if the path contains any non-ASCII characters or brackets.
    :param func_except:     Function to raise the error from.

    :return:                Bool representing whether the path contains any non-ASCII characters or brackets.
    """

    if _raise:
        if path_has_non_ascii_or_bracket_chars(path):
            raise CustomValueError(
                f"The path {path} contains non-ASCII characters or brackets!",
                func_except or path_has_non_ascii_or_bracket_chars,
            )

        return False

    path = SPath(path).to_str()

    try:
        path.encode("ascii")
    except UnicodeEncodeError:
        return True

    if re.search(r"[\[\]\(\){}<>]", path):
        return True

    return False
