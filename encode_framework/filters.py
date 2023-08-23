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
from vstools import ConvMode, CustomValueError, FrameRangesN, SPath, VSFunction, core, get_y, join, replace_ranges, vs

from .logging import Log

__all__: list[str] = [
    "fixedges",
    "setsu_dering",
    "fix_kernel_mask_edges",
    "diff_keyframes",
    "apply_squaremasks",
    "Squaremask",
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


def diff_keyframes(clip_a: vs.VideoNode, clip_b: vs.VideoNode, ep_num: str, prefilter: VSFunction | None = None) -> SPath:
    from lvsfunc import diff
    from vstools import Keyframes, check_ref_clip

    check_ref_clip(clip_a, clip_b, diff_keyframes)

    kf_path = SPath(f"_assets/diff_keyframes_{ep_num}.txt")

    if kf_path.exists():
        Log.warn("Diff keyframe file already exists!")

        match input("Want to overwrite? [Y/n] ").lower().strip():
            case "y" | "yes": kf_path.unlink(missing_ok=True)
            case _: return kf_path

    if prefilter is not None:
        clip_a, clip_b = prefilter(clip_a), prefilter(clip_b)

    _, ranges = diff(clip_a, clip_b, thr=96, return_ranges=True)

    kf_path.parents[0].mkdir(exist_ok=True)

    Keyframes(list(sum(ranges, ()))).to_file(kf_path)

    return kf_path


class Squaremask:
    ranges: tuple[int | None, int | None] | None = None
    """Ranges to apply a squaremask."""

    width: int
    height: int

    offset_x: int
    offset_y: int

    invert: bool = False

    sigma: float = 4.0

    mask_clip: vs.VideoNode = None

    def __init__(
        self, ranges: FrameRangesN = None,
        offset_x: int = 1, offset_y: int = 1,
        width: int = 0, height: int = 0,
        invert: bool = False,
        sigma: float = 4.0
    ) -> None:

        if ranges is None:
            ranges = [(None, None)]

        if width < 0:
            width = abs(width) - offset_x

        if height < 0:
            height = abs(height) - offset_y

        self.ranges = ranges
        self.width = width
        self.height = height
        self.offset_x = offset_x
        self.offset_y = offset_y
        self.invert = invert
        self.sigma = sigma

    def apply(self, clip_a: vs.VideoNode, clip_b: vs.VideoNode, ranges: FrameRangesN = None) -> vs.VideoNode:
        """Apply the squaremasks."""
        self.generate_mask(clip_a, ranges)

        merged = core.std.MaskedMerge(clip_a, clip_b, self.mask_clip)
        return merged
        return replace_ranges(clip_a, merged, self.ranges)

    def generate_mask(self, ref: vs.VideoNode, ranges: FrameRangesN = None) -> vs.VideoNode:
        """Generate a mask and add it to a mask clip."""
        from vsmasktools import squaremask
        from vsrgtools import gauss_blur
        from vstools import plane

        self.ranges = ranges or self.ranges

        if not self.mask_clip:
            self.mask_clip = plane(ref, 0).std.BlankClip(keep=True)

        # error_handling
        if (self.offset_x + self.width) > self.mask_clip.width:
            Log.warn(
                f"Squaremask ({self.offset_x} + {self.width}) is wider than "
                f"the clip ({self.mask_clip.width}) it's being applied to!",
                self.generate_mask
            )

            self.width = self.mask_clip.width - self.offset_x

        if (self.offset_y + self.height) > self.mask_clip.height:
            Log.warn(
                f"Squaremask ({self.offset_y} + {self.height}) is taller than "
                f"the clip ({self.mask_clip.height}) it's being applied to!",
                self.generate_mask
            )

            self.height = self.mask_clip.height - self.offset_y

        sq = squaremask(self.mask_clip, self.width, self.height, self.offset_x, self.offset_y, self.invert, self.apply)

        if self.sigma:
            sq = gauss_blur(sq, self.sigma)

        if self.ranges:
            sq = replace_ranges(self.mask_clip, sq, self.ranges)

        self.mask_clip = sq

        return self.mask_clip


def apply_squaremasks(
    clip_a: vs.VideoNode, clip_b: vs.VideoNode,
    squaremasks: Squaremask | list[Squaremask],
    show_mask: bool = False, streams: int | None = None
) -> vs.VideoNode:
    """Apply a bunch of squaremasks at once."""
    from vsexprtools import ExprOp

    mask = clip_a.std.BlankClip(format=vs.GRAY16)

    if isinstance(squaremasks, Squaremask):
        squaremasks = [squaremasks]

    for sqmask in squaremasks:
        sqmask_clip = sqmask.generate_mask(clip_a)
        sqmask_clip = ExprOp.MAX(sqmask_clip, mask)

        mask = replace_ranges(mask, sqmask_clip, sqmask.ranges)

    if show_mask:
        return mask

    return clip_a.std.MaskedMerge(clip_b, mask)

