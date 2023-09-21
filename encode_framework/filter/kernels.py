"""
    "Fixed" Kernel subclasses that have `border_handling` support.

    Most of these will be removed in a future patch,
    assuming Setsu implements proper border_handling support.
"""

from typing import Any

from vskernels import Bicubic, BicubicSharp, Bilinear, Catrom, Lanczos, Mitchell, Scaler
from vstools import Transfer, inject_self, vs

__all__: list[str] = [
    "FixCatrom",
    "FixMitchell",
    "FixBicubicSharp", "FixSharp",
    "FixLanczos",
    "FixBilinear",

    "LinearBicubic",
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


class LinearBicubic(Scaler):
    """Perform linear conversion prior to scaling."""

    def __init__(self, b: float = 0, c: float = 1 / 2, **kwargs: Any) -> None:
        self.b = b
        self.c = c
        super().__init__(**kwargs)

    @inject_self.cached
    def scale(  # type: ignore[override]
        self, clip: vs.VideoNode, width: int, height: int, shift: tuple[float, float] = (0, 0), **kwargs: Any
    ) -> vs.VideoNode:
        wclip = Transfer.LINEAR.apply(clip)

        wclip = Bicubic(self.b, self.c).scale(
            wclip, **Bicubic(self.b, self.c).get_scale_args(wclip, shift, width, height, **kwargs)
        )

        return Transfer.from_video(clip).apply(wclip)


# Aliases
FixSharp = FixBicubicSharp
