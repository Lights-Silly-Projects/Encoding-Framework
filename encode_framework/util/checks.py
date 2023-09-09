from .logging import Log
from typing import Any, Callable
from vstools import CustomValueError

__all__: list[str] = [
    "assert_truthy"
]


def assert_truthy(var: Any, caller: str | Callable[[Any], Any] | None = None) -> bool:
    """Asserts whether a given variable is truthy. If not, raises a CustomValue log error."""
    try:
        assert var
    except AssertionError:
        raise Log.error(f"The variable \"{var}\" is not truthy!", caller or assert_truthy, CustomValueError, 4)

    return True
