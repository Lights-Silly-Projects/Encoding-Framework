"""
    "Fixed" Kernel subclasses that have `border_handling` support.

    Most of these will be removed in a future patch,
    assuming Setsu implements proper border_handling support.
"""

from typing import Any

from vskernels import BicubicSharp, Catrom, Lanczos, Mitchell, Bilinear, Bicubic
from vstools import vs

__all__: list[str] = [
    "FixCatrom",
    "FixMitchell",
    "FixBicubicSharp", "FixSharp",
    "FixLanczos",
    "FixBilinear",
    "ZewiaCubicNew",
]


class FixCatrom(Catrom):
    def get_params_args(
        self, is_descale: bool, clip: vs.VideoNode,
        width: int | None = None, height: int | None = None, **kwargs: Any
    ) -> dict[str, Any]:
        args = super().get_params_args(is_descale, clip, width, height, **kwargs)

        if is_descale:
            return args | dict(border_handling=1)

        return args


class FixMitchell(Mitchell):
    def get_params_args(
        self, is_descale: bool, clip: vs.VideoNode,
        width: int | None = None, height: int | None = None, **kwargs: Any
    ) -> dict[str, Any]:
        args = super().get_params_args(is_descale, clip, width, height, **kwargs)

        if is_descale:
            return args | dict(border_handling=1)

        return args


class FixBicubicSharp(BicubicSharp):
    def get_params_args(
        self, is_descale: bool, clip: vs.VideoNode,
        width: int | None = None, height: int | None = None, **kwargs: Any
    ) -> dict[str, Any]:
        args = super().get_params_args(is_descale, clip, width, height, **kwargs)

        if is_descale:
            return args | dict(border_handling=1)

        return args


class FixLanczos(Lanczos):
    def get_params_args(
        self, is_descale: bool, clip: vs.VideoNode,
        width: int | None = None, height: int | None = None, **kwargs: Any
    ) -> dict[str, Any]:
        args = super().get_params_args(is_descale, clip, width, height, **kwargs)

        if is_descale:
            return args | dict(border_handling=1)

        return args


class FixBilinear(Bilinear):
    def get_params_args(
        self, is_descale: bool, clip: vs.VideoNode,
        width: int | None = None, height: int | None = None, **kwargs: Any
    ) -> dict[str, Any]:
        args = super().get_params_args(is_descale, clip, width, height, **kwargs)

        if is_descale:
            return args | dict(border_handling=1)

        return args


class ZewiaCubicNew(Bicubic):
    """Bicubic b=-1/2, c=-1/4"""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(b=-1/2, c=-1/4, **kwargs)


FixSharp = FixBicubicSharp

