from typing import Literal, Sequence, overload

from vstools import (CustomValueError, FrameRangesN, core, depth, expect_bits,
                     get_depth, insert_clip, replace_ranges, vs)

__all__: Sequence[str] = [
    "splice_ncs",
    "merge_credits",
    "merge_credits_mask",
]


@overload
def splice_ncs(
    clip: vs.VideoNode,
    ncop: vs.VideoNode | None = None, opstart: int | Literal[False] = False, op_offset: int = 1, op_ignore_ranges: FrameRangesN = [],
    nced: vs.VideoNode | None = None, edstart: int | Literal[False] = False, ed_offset: int = 1, ed_ignore_ranges: FrameRangesN = [],
    minimum: int = 2, inflate: int = 5, maximum: int = 5, close: int = 9,
    show_mask: bool = False, return_scomps: bool = True,
) -> list[vs.VideoNode]:
    ...


@overload
def splice_ncs(
    clip: vs.VideoNode,
    ncop: vs.VideoNode | None = None, opstart: int | Literal[False] = False, op_offset: int = 1, op_ignore_ranges: FrameRangesN = [],
    nced: vs.VideoNode | None = None, edstart: int | Literal[False] = False, ed_offset: int = 1, ed_ignore_ranges: FrameRangesN = [],
    minimum: int = 2, inflate: int = 5, maximum: int = 5, close: int = 9,
    show_mask: bool = False, return_scomps: bool = False,
) -> tuple[vs.VideoNode, vs.VideoNode]:
    ...


@overload
def splice_ncs(
    clip: vs.VideoNode,
    ncop: vs.VideoNode | None = None, opstart: int | Literal[False] = False, op_offset: int = 1, op_ignore_ranges: FrameRangesN = [],
    nced: vs.VideoNode | None = None, edstart: int | Literal[False] = False, ed_offset: int = 1, ed_ignore_ranges: FrameRangesN = [],
    minimum: int = 2, inflate: int = 5, maximum: int = 5, close: int = 9,
    show_mask: bool = True, return_scomps: bool = False,
) -> vs.VideoNode:
    ...


def splice_ncs(
    clip: vs.VideoNode,
    ncop: vs.VideoNode | None = None, opstart: int | Literal[False] = False, op_offset: int = 1, op_ignore_ranges: FrameRangesN = [],
    nced: vs.VideoNode | None = None, edstart: int | Literal[False] = False, ed_offset: int = 1, ed_ignore_ranges: FrameRangesN = [],
    minimum: int = 2, inflate: int = 5, maximum: int = 5, close: int = 9,
    show_mask: bool = False, return_scomps: bool = False,
) -> vs.VideoNode | list[vs.VideoNode] | tuple[vs.VideoNode, vs.VideoNode]:
    """
    Splice NCs into a clip and return the spliced clip and a diff clip.

    This is useful for splicing in NCs and later add the credits back in.

    :param clip:                Clip to process.
    :param ncop:                NCOP VideoNode.
    :param opstart:             First frame of the OP in the episode.
    :param op_offset:           Amount to trim the OP by from the end.
                                Some episodes have a different length for the OP.
    :param op_ignore_ranges:    List of frames ranges to ignore for the OP.
                                This is useful for skipping parts of the OP that have no NCs.
    :param nced:                NCED VideoNode.
    :param edstart:             First frame of the ED in the episode.
    :param ed_offset:           Amount to trim the ED by from the end.
                                Some episodes have a different length for the ED.
    :param ed_ignore_ranges:    List of frames ranges to ignore for the ED.
                                This is useful for skipping parts of the ED that have no NCs.
    :param minimum:             Amount of times to perform a std.Minimum call on the mask.
    :param inflate:             Amount of times to perform a std.Inflate call on the mask.
    :param maximum:             Amount of times to perform a std.Maximum call on the mask.
    :param close:               `Size` parameter for vsmasktools.Morpho.closing.
    :param show_mask:           Return only the mask.
    :param return_scomps:       Return a bunch of clips intended for checking that trims are correct
                                and for other diagnostic purposes.
                                To aid in this, it will also print basic information for every clip in the list.

    :return:                    Regularly, a tuple containing the processed clip and a diff clip.
                                If `return_scomps=True`, a list of various clips depending on the inputs.
                                If `show_mask=True`, return a single VideoNode. This overrides `return_scomps`.
    """

    from lvsfunc import stack_compare

    if all(x is None for x in (ncop, nced)):
        raise CustomValueError("Both ncop and nced are None!", splice_ncs)

    def _process_nc_range(
        clip: vs.VideoNode, nc_clip: vs.VideoNode | None, start: int | Literal[False],
        offset: int, ignore_ranges: FrameRangesN, name: str
    ) -> tuple[vs.VideoNode, FrameRangesN, list[vs.VideoNode]]:
        if not isinstance(nc_clip, vs.VideoNode) or not isinstance(start, int) or isinstance(start, bool):
            return clip, [], []

        nc_clip = nc_clip.std.SetFrameProps(isNC=True)
        nc_clip = nc_clip + nc_clip[-1] * 12
        nc_clip = replace_ranges(nc_clip, clip[start:start + nc_clip.num_frames - 1], ignore_ranges)

        nc_range = [(start, start + nc_clip.num_frames - 1 - offset)]

        b = clip.std.BlankClip(length=1, color=[0] * 3)
        scomp = stack_compare(
            clip.text.FrameNum()[start:start + nc_clip.num_frames - 1] + b,
            nc_clip[:-offset] + b.text.FrameNum()
        )

        clip = insert_clip(clip, nc_clip[:-offset], start)

        return clip, nc_range, [scomp.std.SetFrameProps(Name=f"{name} splice trim")]

    # Preparing clips.
    clip_c = clip
    # OP/ED stack comps to check if they line up, as well as splicing them in.
    return_scomp: list[vs.VideoNode] = list[vs.VideoNode]()
    diff_rfs = []

    # Process OP
    clip, op_ranges, op_scomps = _process_nc_range(
        clip, ncop, opstart, op_offset, op_ignore_ranges, "OP"
    )

    diff_rfs += op_ranges
    return_scomp += op_scomps

    # Process ED
    clip, ed_ranges, ed_scomps = _process_nc_range(
        clip, nced, edstart, ed_offset, ed_ignore_ranges, "ED"
    )

    diff_rfs += ed_ranges
    return_scomp += ed_scomps

    return_scomp += [clip.std.SetFrameProps(Name="NCs spliced in")]

    diff = core.std.MakeDiff(*[depth(x, 32) for x in [clip_c, clip]])  # type:ignore
    # diff = DFTTest().denoise(diff, sigma=50)

    # For some reason there's ugly noise around the credits? Removing that here.
    # diff_brz = diff.std.BinarizeMask([0.0035, 0.0025])
    # diff = core.akarin.Expr([diff, diff_brz.std.Inflate().std.Maximum()], "x y min 1.01 *")

    # And somehow it creates weird values in some places? Limiting except for OP/ED.
    diff_lim = diff.std.BlankClip(keep=True).std.SetFrameProps(no_diff=True)

    # We also want to remove any extra junk from different compressions so they don't get diff'd back.
    # diff_brz = core.std.Binarize(get_y(diff).akarin.Expr("x abs"), 0.02)
    # diff_mask = iterate(diff_brz, core.std.Deflate, minimum)
    # diff_mask = iterate(diff_mask, core.std.Inflate, inflate)
    # diff_mask = iterate(diff_mask, core.std.Inflate, maximum)
    # diff_mask = Morpho.closing(diff_mask, size=close).std.BinarizeMask()
    # diff = gauss_blur(diff_mask, 0.5)

    if show_mask:
        return diff

    # diff = core.std.MaskedMerge(diff_lim, diff, diff_brz)
    diff = replace_ranges(diff_lim, diff, diff_rfs)  # type:ignore

    return_scomp += [diff.std.SetFrameProps(Name="Credits diff")]

    if return_scomps:
        return return_scomp

    return clip, diff


def merge_credits(flt: vs.VideoNode, diff: vs.VideoNode) -> vs.VideoNode:
    """A simple helper function to merge the diff onto the filtered clip. Must be 32bit."""
    flt, bits = expect_bits(flt, 32)

    if get_depth(diff) != 32:
        raise ValueError(f"Expected diff to be 32 bits, not {get_depth(diff)}!")

    out = core.std.MergeDiff(flt, diff)

    return depth(out, bits)


def merge_credits_mask(
    flt: vs.VideoNode, diff: vs.VideoNode, src: vs.VideoNode, show_mask: bool = False
) -> vs.VideoNode:
    """A simple helper function to merge the credits back onto a clip by creating a mask."""
    from vsexprtools import norm_expr
    from vstools import get_neutral_value

    flt = depth(flt, diff)
    src = depth(src, flt)

    credit_mask = norm_expr(diff, f"x {get_neutral_value(diff)} = 0 1 ?")

    if show_mask:
        return credit_mask

    return flt.std.MaskedMerge(src, credit_mask)
