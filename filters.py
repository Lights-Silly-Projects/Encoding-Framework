from typing import Any

from vsdehalo import base_dehalo_mask
from vsdeinterlace import vinverse
from vsexprtools import ExprOp
from vsmasktools import Kirsch, MagDirection, retinex
from vsrgtools import BlurMatrix, RemoveGrainMode, limit_filter
from vsscale import DescaleResult
from vstools import ConvMode, core, get_y, join, vs

__all__: list[str] = [
    "fixedges",
    "setsu_dering",
    "fix_kernel_mask_edges"
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


def setsu_dering(clip: vs.VideoNode, descale: bool = False) -> vs.VideoNode:
    """Setsu's WIP deringing function. Lightly modified."""
    from vsaa import Nnedi3

    clip_y = get_y(clip)

    if descale:
        y = clip_y.descale.Delanczos(1440, 1080, 5)
    else:
        y = clip_y

    ret_y = retinex(y)

    kirsch = Kirsch(MagDirection.E | MagDirection.W).edgemask(ret_y)

    ring0 = kirsch.std.Expr('x 2 * 65535 >= x 0 ?')
    ring1 = kirsch.std.Expr('x 2 * 65535 >= 0 x ?')
    ring2 = ring0.resize.Bilinear(1920)

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

    # nag1 = Waifu2x(tiles=4, num_streams=2).scale(nag, 1920, 1080)

    if descale:
        nag1 = Nnedi3.scale(nag, 1920, 1080)
    else:
        nag1 = nag

    nag2 = nag.fmtc.resample(1920, kernel='gauss', a1=12)

    nag3 = nag2.std.MaskedMerge(nag1, ring2.std.Maximum())

    fine_mask = ring2.std.Minimum().std.Inflate()

    nag = nag3.std.MaskedMerge(clip_y, fine_mask)

    nag = nag.std.MaskedMerge(nag2, ring.resize.Bilinear(1920))

    de_mask = ExprOp.ADD(
        base_dehalo_mask(ret_y), ring1,
        core.std.Expr([clip_y, nag], 'x y - abs 120 * 65535 >= 65535 0 ?').resize.Bicubic(ring1.width)
    ).resize.Bilinear(1920)

    de_mask = de_mask.std.MaskedMerge(de_mask.std.BlankClip(), fine_mask)
    de_mask = de_mask.std.Inflate().std.Maximum().std.Deflate()
    de_mask = de_mask.std.Minimum().std.Minimum().std.Maximum().std.Minimum()
    de_mask = de_mask.std.Minimum().std.Expr('x 1.5 *').std.Maximum().std.Deflate()
    de_mask = de_mask.std.MaskedMerge(de_mask.std.BlankClip(), fine_mask)
    nag1 = clip_y.std.Merge(nag, 0.5).std.MaskedMerge(nag, de_mask)

    deringed = limit_filter(nag, nag1, clip_y).std.MaskedMerge(nag2, ring.resize.Bilinear(1920))
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
