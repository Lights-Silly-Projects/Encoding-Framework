from typing import Any, Callable

from vstools import CustomValueError

from .logging import Log

__all__: list[str] = ["assert_truthy"]


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
