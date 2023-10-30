"""
    "Fixed" Kernel subclasses that have `border_handling` support.

    Most of these will be removed in a future patch,
    assuming Setsu implements proper border_handling support.
"""

from typing import Any

from vskernels import Bicubic, Bilinear, Lanczos
from vstools import vs

__all__: list[str] = [
    "BhBicubic",
    "BhCatrom",
    "BhMitchell",
    "BhBicubicSharp",
    "BhLanczos",
    "BhBilinear",
]


class BhBicubic(Bicubic):
    """Bicubic with Border Handling for descaling."""

    def get_params_args(
        self, is_descale: bool, clip: vs.VideoNode,
        width: int | None = None, height: int | None = None, **kwargs: Any
    ) -> dict[str, Any]:
        args = super().get_params_args(is_descale, clip, width, height, **kwargs)

        if is_descale:
            return args | dict(border_handling=1)

        return args


class BhCatrom(BhBicubic):
    """Bicubic b=0, c=0.5 with Border Handling for descaling."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(b=0, c=1 / 2, **kwargs)


class BhMitchell(BhBicubic):
    """Bicubic b=0.33, c=0.33 with Border Handling for descaling."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(b=1 / 3, c=1 / 3, **kwargs)


class BhBicubicSharp(BhBicubic):
    """Bicubic b=0, c=1 with Border Handling for descaling."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(b=0, c=1, **kwargs)


class BhLanczos(Lanczos):
    """Lanczos with Border Handling for descaling."""

    def get_params_args(
        self, is_descale: bool, clip: vs.VideoNode,
        width: int | None = None, height: int | None = None, **kwargs: Any
    ) -> dict[str, Any]:
        args = super().get_params_args(is_descale, clip, width, height, **kwargs)

        if is_descale:
            return args | dict(border_handling=1)

        return args


class BhBilinear(Bilinear):
    """Bilinear with Border Handling for descaling."""

    def get_params_args(
        self, is_descale: bool, clip: vs.VideoNode,
        width: int | None = None, height: int | None = None, **kwargs: Any
    ) -> dict[str, Any]:
        args = super().get_params_args(is_descale, clip, width, height, **kwargs)

        if is_descale:
            return args | dict(border_handling=1)

        return args
