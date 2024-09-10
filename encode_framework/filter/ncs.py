from typing import Literal, Sequence, overload

from vstools import (FrameRangesN, FunctionUtil, core, depth, expect_bits,
                     get_depth, get_y, insert_clip, iterate, replace_ranges,
                     vs)

from ..util import Log

__all__: Sequence[str] = [
    "splice_ncs",
    "merge_credits",
    "merge_credits_mask",
]


@overload
def splice_ncs(
    clip: vs.VideoNode,
    ncop: vs.VideoNode | None = None, opstart: int | Literal[False] = False, op_offset: int = 1,
    nced: vs.VideoNode | None = None, edstart: int | Literal[False] = False, ed_offset: int = 1,
    minimum: int = 2, inflate: int = 5, maximum: int = 5, close: int = 9,
    show_mask: bool = False, return_scomps: bool = True,
) -> list[vs.VideoNode]:
    ...

@overload
def splice_ncs(
    clip: vs.VideoNode,
    ncop: vs.VideoNode | None = None, opstart: int | Literal[False] = False, op_offset: int = 1,
    nced: vs.VideoNode | None = None, edstart: int | Literal[False] = False, ed_offset: int = 1,
    minimum: int = 2, inflate: int = 5, maximum: int = 5, close: int = 9,
    show_mask: bool = False, return_scomps: bool = False,
) -> tuple[vs.VideoNode, vs.VideoNode]:
    ...

@overload
def splice_ncs(
    clip: vs.VideoNode,
    ncop: vs.VideoNode | None = None, opstart: int | Literal[False] = False, op_offset: int = 1,
    nced: vs.VideoNode | None = None, edstart: int | Literal[False] = False, ed_offset: int = 1,
    minimum: int = 2, inflate: int = 5, maximum: int = 5, close: int = 9,
    show_mask: bool = True, return_scomps: bool = False,
) -> vs.VideoNode:
    ...

def splice_ncs(
    clip: vs.VideoNode,
    ncop: vs.VideoNode | None = None, opstart: int | Literal[False] = False, op_offset: int = 1,
    nced: vs.VideoNode | None = None, edstart: int | Literal[False] = False, ed_offset: int = 1,
    minimum: int = 2, inflate: int = 5, maximum: int = 5, close: int = 9,
    show_mask: bool = False, return_scomps: bool = False,
) -> vs.VideoNode | list[vs.VideoNode] | tuple[vs.VideoNode, vs.VideoNode]:
    """
    Splice NCs into a clip and return the spliced clip and a diff clip.

    This is useful for splicing in NCs and later add the credits back in.

    :param clip:            Clip to process.
    :param ncop:            NCOP VideoNode.
    :param opstart:         First frame of the OP in the episode.
    :param op_offset:       Amount to trim the OP by from the end.
                            Some episodes have a different length for the OP.
    :param nced:            NCED VideoNode.
    :param edstart:         First frame of the ED in the episode.
    :param ed_offset:       Amount to trim the ED by from the end.
                            Some episodes have a different length for the ED.
    :param minimum:         Amount of times to perform a std.Minimum call on the mask.
    :param inflate:         Amount of times to perform a std.Inflate call on the mask.
    :param maximum:         Amount of times to perform a std.Maximum call on the mask.
    :param close:           `Size` parameter for vsmasktools.Morpho.closing.
    :param show_mask:       Return only the mask.
    :param return_scomps:   Return a bunch of clips intended for checking that trims are correct
                            and for other diagnostic purposes.
                            To aid in this, it will also print basic information for every clip in the list.

    :return:                Regularly, a tuple containing the processed clip and a diff clip.
                            If `return_scomps=True`, a list of various clips depending on the inputs.
                            If `show_mask=True`, return a single VideoNode. This overrides `return_scomps`.
    """
    from lvsfunc import stack_compare
    from vsdenoise import DFTTest
    from vsmasktools import Morpho
    from vsrgtools import gauss_blur

    # Preparing clips.
    b = clip.std.BlankClip(length=1, color=[0] * 3)
    clip_c = clip

    # OP/ED stack comps to check if they line up, as well as splicing them in.
    return_scomp: list[vs.VideoNode] = list()
    diff_rfs = FrameRangesN()

    if isinstance(ncop, vs.VideoNode) and isinstance(opstart, int) and not isinstance(opstart, bool):
        ncop = ncop + ncop[-1] * 12
        diff_rfs += [(opstart, opstart+ncop.num_frames-1-op_offset)]  # type:ignore

        op_scomp = stack_compare(clip.text.FrameNum()[opstart:opstart+ncop.num_frames-1]+b, ncop[:-op_offset]+b)  # noqa
        clip = insert_clip(clip, ncop[:-op_offset], opstart)
        return_scomp += [op_scomp.std.SetFrameProps(Name="OP splice trim")]

    if isinstance(nced, vs.VideoNode) and isinstance(edstart, int) and not isinstance(edstart, bool):
        nced = nced + nced[-1] * 12
        diff_rfs += [(edstart, edstart+nced.num_frames-1-ed_offset)]  # type:ignore

        ed_scomp = stack_compare(clip.text.FrameNum()[edstart:edstart+nced.num_frames-1]+b, nced[:-ed_offset]+b)  # noqa
        clip = insert_clip(clip, nced[:-ed_offset], edstart)
        return_scomp += [ed_scomp.std.SetFrameProps(Name="ED splice trim")]

    return_scomp += [clip.std.SetFrameProps(Name="NCs spliced in")]

    diff = core.std.MakeDiff(*[depth(x, 32) for x in [clip_c, clip]])  # type:ignore
    diff = DFTTest.denoise(diff, sigma=100)

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
    from vstools import get_neutral_value
    from vsexprtools import norm_expr

    flt = depth(flt, diff)
    src = depth(src, flt)

    credit_mask = norm_expr(diff, f"x {get_neutral_value(diff)} = 0 1 ?")

    if show_mask:
        return credit_mask

    return flt.std.MaskedMerge(src, credit_mask)


