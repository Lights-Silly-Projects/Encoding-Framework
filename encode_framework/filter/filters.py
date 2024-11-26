"""
    A handful of common functions to use in scripts.
    These aren't in other packages, and often highly experimental.
"""

from typing import Any, Literal

from vsexprtools import norm_expr
from vsscale import DescaleResult
from vstools import (CustomValueError, FrameRangesN, SPath, VSFunction, core,
                     replace_ranges, vs)

from ..util.logging import Log

__all__: list[str] = [
    "fixedges",
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
    if isinstance((rownum := kwargs.pop("rownum", None)), int):
        rownum = [rownum]

    if isinstance((rowval := kwargs.pop("rowval", None)), int):
        rowval = [rowval]

    if isinstance((colnum := kwargs.pop("colnum", None)), int):
        colnum = [colnum]

    if isinstance((colval := kwargs.pop("colval", None)), int):
        colval = [colval]

    fix = _rektlvls(clip, rownum, rowval, colnum, colval, prot_val=None)
    prot = _rektlvls(clip, rownum, rowval, colnum, colval)
    pp = prot.cf.ContinuityFixer(3, 3, 3, 3, 30)

    return norm_expr([clip, fix, prot, pp], "x z < y z - xor z x y - abs x a - abs < y z a y max min ? ?")


def _rektlvls(
    clip, rownum=None, rowval=None, colnum=None, colval=None,
    prot_val=[16, 235], min_val=16, max_val=235
) -> vs.VideoNode:
    """Copied here as a temporary fix for the pip package not working."""
    if rownum:
        if isinstance(rownum, int):
            rownum = [rownum]
        if isinstance(rowval, int):
            rowval = [rowval]
        for _ in range(len(rownum)):
            if rownum[_] < 0:
                rownum[_] = clip.height + rownum[_]
            clip = _rektlvl(clip, rownum[_], rowval[_], alignment='row',
                            prot_val=prot_val, min_val=min_val, max_val=max_val)
    if colnum:
        if isinstance(colnum, int):
            colnum = [colnum]
        if isinstance(colval, int):
            colval = [colval]
        for _ in range(len(colnum)):
            if colnum[_] < 0:
                colnum[_] = clip.width + colnum[_]
            clip = _rektlvl(clip, colnum[_], colval[_], alignment='column',
                            prot_val=prot_val, min_val=min_val, max_val=max_val)

    return clip


def _rektlvl(c, num, adj_val, alignment='row', prot_val=[16, 235], min_val=16, max_val=235):
    from rekt.rekt_fast import rekt_fast  # type:ignore[import]

    if adj_val == 0:
        return c
    from vsutil import get_y, scale_value
    core = vs.core

    if (adj_val > 100 or adj_val < -100) and prot_val:
        raise ValueError("adj_val must be between -100 and 100!")
    if c.format.color_family == vs.RGB:
        raise TypeError("RGB color family is not supported by rektlvls.")
    bits = c.format.bits_per_sample

    min_val = scale_value(min_val, 8, bits)
    max_val = scale_value(max_val, 8, bits)
    diff_val = max_val - min_val
    ten = scale_value(10, 8, bits)

    if c.format.color_family != vs.GRAY:
        c_orig = c
        c = get_y(c)
    else:
        c_orig = None

    if prot_val:
        adj_val = scale_value(adj_val * 2.19, 8, bits)
        if adj_val > 0:
            expr = f'x {min_val} - 0 <= {min_val} {max_val} {adj_val} - {min_val} - 0 <= 0.01 {max_val} {adj_val} - {min_val} - ? / {diff_val} * x {min_val} - {max_val} {adj_val} - {min_val} - 0 <= 0.01 {max_val} {adj_val} - {min_val} - ? / {diff_val} * {min_val} + ?'
        elif adj_val < 0:
            expr = f'x {min_val} - 0 <= {min_val} {diff_val} / {max_val} {adj_val} + {min_val} - * x {min_val} - {diff_val} / {max_val} {adj_val} + {min_val} - * {min_val} + ?'

        if isinstance(prot_val, int):
            prot_top = [scale_value(255 - prot_val, 8, bits), scale_value(245 - prot_val, 8, bits)]
            expr += f' x {prot_top[0]} - -{ten} / 0 max 1 min * x x {prot_top[1]} - {ten} / 0 max 1 min * +'
        else:
            prot_val = [scale_value(prot_val[0], 8, bits), scale_value(prot_val[1], 8, bits)]
            expr += f' x {prot_val[1]} - -{ten} / 0 max 1 min * x x {prot_val[1]} {ten} - - {ten} / 0 max 1 min * + {prot_val[0]} x - -{ten} / 0 max 1 min * x {prot_val[0]} {ten} + x - {ten} / 0 max 1 min * +'

        def last(x): return core.std.Expr(x, expr=expr)
    else:
        adj_val = adj_val * (max_val - min_val) / 100
        if adj_val < 0:
            def last(x): return core.std.Levels(
                x, min_in=min_val, max_in=max_val, min_out=min_val, max_out=max_val + adj_val)
        elif adj_val > 0:
            def last(x): return core.std.Levels(
                x, min_in=min_val, max_in=max_val - adj_val, min_out=min_val, max_out=max_val)

    if alignment == 'row':
        last = rekt_fast(c, last, bottom=c.height - num - 1, top=num)
    elif alignment == 'column':
        last = rekt_fast(c, last, right=c.width - num - 1, left=num)
    else:
        raise ValueError("Alignment must be 'row' or 'column'.")

    if c_orig:
        last = core.std.ShufflePlanes([last, c_orig], planes=[0, 1, 2], colorfamily=c_orig.format.color_family)

    return last


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


def diff_keyframes(
    clip_a: vs.VideoNode, clip_b: vs.VideoNode,
    ep_num: str, prefilter: VSFunction | None = None,
    raise_if_error: bool = True
) -> SPath:
    from lvsfunc import diff
    from vstools import Keyframes, check_ref_clip

    check_ref_clip(clip_a, clip_b, diff_keyframes)

    kf_path = SPath(f"_assets/diff_keyframes_{ep_num}.txt")

    if kf_path.exists():
        Log.warn("Diff keyframe file already exists!")

        match input("Want to overwrite? [Y/n] ").lower().strip():
            case "y" | "yes":
                kf_path.unlink(missing_ok=True)
            case _:
                return kf_path

    if prefilter is not None:
        clip_a, clip_b = prefilter(clip_a), prefilter(clip_b)

    _, ranges = diff(clip_a, clip_b, thr=96, return_ranges=True)

    kf_path.parents[0].mkdir(exist_ok=True)

    Keyframes(list(sum(ranges, ()))).to_file(kf_path)

    if raise_if_error:
        raise CustomValueError("Check the diff keyframes!", diff_keyframes, f"raise_if_error={raise_if_error}")

    return kf_path


class Squaremask:
    ranges: tuple[int | None | Literal["auto"], int | None | Literal["auto"]] | None = None
    """Ranges to apply a squaremask."""

    width: int
    height: int

    offset_x: int
    offset_y: int

    invert: bool = False

    sigma: float = 4.0

    mask_clip: vs.VideoNode

    def __init__(
        self, ranges: FrameRangesN | None = None,
        offset_x: int = 1, offset_y: int = 1,
        width: int | bool = 0, height: int | bool = 0,
        invert: bool = False,
        sigma: float = 4.0,
    ) -> None:

        if ranges is None:
            ranges = [(None, None)]

        if (isinstance(width, bool) or width == "auto") and width:
            width = "auto"  # type:ignore[assignment]
        elif width < 0:
            width = abs(width) - offset_x

        if (isinstance(height, bool) or height == "auto") and height:
            height = "auto"  # type:ignore[assignment]
        elif height < 0:
            height = abs(height) - offset_y

        self.ranges = ranges or []  # type:ignore[assignment]
        self.width = width
        self.height = height
        self.offset_x = offset_x
        self.offset_y = offset_y
        self.invert = invert
        self.sigma = sigma

    def __str__(self) -> str:
        out = f"Squaremask {self.width}x{self.height}"

        if self.ranges:
            out += f" @ {self.ranges[0]}-f{self.ranges[1]}"

        out += f" (offset_x: {self.offset_x}, offset_y: {self.offset_y},"
        out += f" width: {self.width}, height: {self.height}) "

        return out

    def apply(self, clip_a: vs.VideoNode, clip_b: vs.VideoNode, ranges: FrameRangesN | None = None) -> vs.VideoNode:
        """Apply the squaremasks."""
        self.generate_mask(clip_a, ranges)

        return core.std.MaskedMerge(clip_a, clip_b, self.mask_clip)

    def generate_mask(self, ref: vs.VideoNode, ranges: FrameRangesN | None = None) -> vs.VideoNode:
        """Generate a mask and add it to a mask clip."""
        from vsmasktools import squaremask
        from vsrgtools import gauss_blur
        from vstools import plane

        self.ranges = ranges or self.ranges  # type:ignore[assignment]

        if not self.mask_clip:
            self.mask_clip = plane(ref, 0).std.BlankClip(keep=True)

        if self.width == "auto":
            self.width = ref.width - self.offset_x

        if self.height == "auto":
            self.height = ref.height - self.offset_y

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
            sq = replace_ranges(self.mask_clip, sq, self.ranges or [])  # type:ignore[arg-type]

        self.mask_clip = sq

        return self.mask_clip


def apply_squaremasks(
    clip_a: vs.VideoNode, clip_b: vs.VideoNode,
    squaremasks: Squaremask | list[Squaremask],
    show_mask: bool = False, print_sq: bool = False,
) -> vs.VideoNode:
    """Apply a bunch of squaremasks at once."""
    from vsexprtools import ExprOp

    if not squaremasks:
        return clip_a

    mask = clip_a.std.BlankClip(format=vs.GRAY16)

    if isinstance(squaremasks, Squaremask):
        squaremasks = [squaremasks]

    for i, sqmask in enumerate(squaremasks, start=1):
        sqmask_clip = sqmask.generate_mask(clip_a)
        sqmask_clip = ExprOp.MAX(sqmask_clip, mask)

        if print_sq:
            print(i, "-", sqmask)

        mask = replace_ranges(mask, sqmask_clip, sqmask.ranges or [])  # type:ignore[arg-type]

    if show_mask:
        return mask

    return clip_a.std.MaskedMerge(clip_b, mask)
