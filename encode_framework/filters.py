"""
    A handful of common functions to use in scripts.
    These aren't in other packages, and often highly experimental.
"""

from typing import Any

from vsdehalo import base_dehalo_mask
from vsdeinterlace import vinverse
from vsexprtools import ExprOp
from vsmasktools import Kirsch, MagDirection, retinex
from vsrgtools import BlurMatrix, RemoveGrainMode, limit_filter
from vsscale import DescaleResult
from vstools import ConvMode, CustomValueError, core, get_y, join, vs

from .logging import Log

__all__: list[str] = [
    "fixedges",
    "setsu_dering",
    "fix_kernel_mask_edges",
]


def fixedges(clip: vs.VideoNode, **kwargs: Any) -> vs.VideoNode:
    """
    Zewia's naive edgefixing function.

    :param clip:    Clip to process.
    :param kwargs:  Args to pass on to `rekt.rektlvls`.

    :return:        Clip with edges fixed.
    """
    from rekt import rektlvls  # type:ignore

    fix = rektlvls(clip, prot_val=None, **kwargs)
    prot = rektlvls(clip, **kwargs)
    pp = prot.cf.ContinuityFixer(3, 3, 3, 3, 30)

    expr = "x z < y z - xor z x y - abs x a - abs < y z a y max min ? ?"
    return core.std.Expr([clip, fix, prot, pp], expr)


def setsu_dering(clip: vs.VideoNode, mode: int = "w") -> vs.VideoNode:
    """
    Setsu's WIP deringing function. Lightly modified.

    This deringing function was written to deal with the ringing introduced
    when a 1920x1080 video is squashed to 1440x1080 with the HDCAM profile(?).

    Originally written for Hayate no Gotoku S1.
    """
    from vsaa import Nnedi3

    if not any(x in mode for x in "wh"):
        raise CustomValueError("Mode must be either \"w\", \"h\", or both", setsu_dering, mode)

    if all(x in mode for x in "wh"):
        if len(mode) > 2:
            Log.warn(f"Performing {len(mode)} iterations. It's not recommended to do more than 2!", setsu_dering)

        for x in mode:
            clip = setsu_dering(clip, x)

        return clip

    transpose = mode == "h"

    clip_y = get_y(clip)

    if transpose:
        clip_y = clip_y.std.Transpose()

    # TODO: Better resolution checking because this is kinda :koronesweat: atm.
    de_width = 1080 if transpose else 1440
    de_height = 1440 if transpose else 1080

    up_width = 1080 if transpose else 1920
    up_height = 1920 if transpose else 1080

    y = clip_y.descale.Delanczos(de_width, de_height, 5)

    ret_y = retinex(y)

    kirsch = Kirsch(MagDirection.E | MagDirection.W).edgemask(ret_y)

    ring0 = kirsch.std.Expr('x 2 * 65535 >= x 0 ?')
    ring1 = kirsch.std.Expr('x 2 * 65535 >= 0 x ?')
    ring2 = ring0.resize.Bilinear(up_width, up_height)

    ring = RemoveGrainMode.BOB_TOP_CLOSE(RemoveGrainMode.BOB_BOTTOM_INTER(ring1))

    ring = ring.std.Transpose()

    ring = RemoveGrainMode.SMART_RGCL(ring)

    ring = ring.std.Transpose()

    ring = core.std.Expr([
        ring, kirsch.std.Maximum().std.Maximum().std.Maximum()
    ], 'y 2 * 65535 >= x 0 ?').std.Maximum()

    nag0 = vinverse(y, 6.0, 255, 0.25, ConvMode.HORIZONTAL)
    nag1 = vinverse(y, 5.0, 255, 0.2, ConvMode.HORIZONTAL)
    nag = nag0.std.MaskedMerge(nag1, ring)

    gauss = BlurMatrix.gauss(0.35)
    nag = gauss(nag, 0, ConvMode.HORIZONTAL, passes=2)

    # nag1 = Waifu2x(tiles=4, num_streams=2).scale(nag, up_width, up_height)
    nag1 = Nnedi3.scale(nag, up_width, up_height)

    nag2 = nag.fmtc.resample(up_width, up_height, kernel='gauss', a1=12)

    nag3 = nag2.std.MaskedMerge(nag1, ring2.std.Maximum())

    fine_mask = ring2.std.Minimum().std.Inflate()

    nag = nag3.std.MaskedMerge(clip_y, fine_mask)

    nag = nag.std.MaskedMerge(nag2, ring.resize.Bilinear(up_width, up_height))

    de_mask = ExprOp.ADD(
        base_dehalo_mask(ret_y), ring1,
        core.std.Expr([clip_y, nag], 'x y - abs 120 * 65535 >= 65535 0 ?').resize.Bicubic(ring1.width, ring1.height)
    ).resize.Bilinear(up_width, up_height)

    de_mask = de_mask.std.MaskedMerge(de_mask.std.BlankClip(), fine_mask)
    de_mask = de_mask.std.Inflate().std.Maximum().std.Deflate()
    de_mask = de_mask.std.Minimum().std.Minimum().std.Maximum().std.Minimum()
    de_mask = de_mask.std.Minimum().std.Expr('x 1.5 *').std.Maximum().std.Deflate()
    de_mask = de_mask.std.MaskedMerge(de_mask.std.BlankClip(), fine_mask)
    nag1 = clip_y.std.Merge(nag, 0.5).std.MaskedMerge(nag, de_mask)

    deringed = limit_filter(nag, nag1, clip_y).std.MaskedMerge(nag2, ring.resize.Bilinear(up_width, up_height))

    if transpose:
        deringed = deringed.std.Transpose()

    return join(deringed, clip)


def fix_kernel_mask_edges(clip: vs.VideoNode | DescaleResult, crop: int = 8) -> vs.VideoNode | DescaleResult:
    """
    Crop the edges of an error mask if using fixed kernels.

    Note that this will cause issues with scrolling credits!
    """
    crops = (crop, crop, crop, crop)

    if isinstance(clip, DescaleResult):
        assert clip.error_mask

        clip.error_mask = clip.error_mask.std.Crop(*crops).std.AddBorders(*crops)

        return clip

    return clip.std.Crop(*crops).std.AddBorders(*crops)
