from vstools import FrameRangesN, core, vs

__all__: list[str] = [
    "filtering",
]


def filtering(
    clip: vs.VideoNode, filename: str = "",
    ed_clip: vs.VideoNode | None = None, ed_replace_ranges: FrameRangesN = [],
    # ncop: vs.VideoNode, nced: vs.VideoNode,
    # op_start: int, ed_start: int,
    # op_offset: int = 1, ed_offset: int = -1,
    show_mask: bool = False, thr=0.0825,
    streams: int | None = None, tiles: int = 1, dirty_edges: bool = False,
    ed_shift_ranges: FrameRangesN = [], frac_descale_ranges: FrameRangesN = []
) -> vs.VideoNode:
    """Main filterchain."""
    from awsmfunc import bbmod
    from vodesfunc import DescaleTarget
    from vsaa import Eedi3, based_aa, pre_aa
    from vsdeband import AddNoise, Placebo, deband_detail_mask
    from vsdehalo import dehalomicron
    from vsdenoise import (BM3DCudaRTC, MotionMode, MVTools, Point422ChromaRecon, ReconOutput, SADMode, SearchMode,
                           dpir, dpir_mask, nl_means, prefilter_to_full_range)
    from vsexprtools import ExprOp
    from vskernels import Bilinear, Catrom, Lanczos
    from vsmasktools import Kirsch, Morpho, flat_mask, retinex
    from vsrgtools import contrasharpening_median, gauss_blur
    from vsscale import Waifu2x, descale_detail_mask
    from vstools import FieldBased, SPath, get_w, initialize_clip, iterate, join, plane, replace_ranges, ChromaLocation

    from .filters import fixedges
    from .kernels import ZewiaCubicNew

    assert clip.format

    clip = initialize_clip(clip).std.RemoveFrameProps("Name")
    clip = ChromaLocation.CENTER.apply(clip)

    # Denoising.
    mv = MVTools.denoise(
        clip, tr=2, thSAD=100, block_size=16, overlap=8, range_conversion=4.0,
        sad_mode=(SADMode.ADAPTIVE_SPATIAL_MIXED, SADMode.ADAPTIVE_SATD_MIXED),
        search=SearchMode.DIAMOND, motion=MotionMode.HIGH_SAD,
        planes=None
    )

    bm3d = BM3DCudaRTC.denoise(clip, sigma=0.3, tr=1, ref=mv, planes=0)
    nlm = nl_means(clip, strength=0.3, tr=2, ref=mv, planes=[1, 2])
    den = join(bm3d, nlm)

    csharp = contrasharpening_median(den, clip, mode=gauss_blur, planes=None)

    # Rescaling.
    rescaled = DescaleTarget(
        height=874, kernel=Lanczos(taps=4),
        upscaler=Waifu2x(tiles=tiles, num_streams=streams, scaler=ZewiaCubicNew),
        downscaler=ZewiaCubicNew,
        do_post_double=dehalomicron,
        credit_mask_thr=0.05
    ).generate_clips(csharp)

    scaled, err_mask = rescaled.get_upscaled(csharp, csharp), rescaled.credit_mask

    err_mask = iterate(err_mask, core.std.Inflate, 3)
    err_mask = iterate(err_mask, core.std.Maximum, 3)
    err_mask = gauss_blur(err_mask, 1.0)

    scaled = scaled.std.MaskedMerge(csharp, err_mask)

    if show_mask:
        return err_mask, scaled

    # # Weak post-dehaloing.
    baa = based_aa(
        scaled, rfactor=2.0,
        supersampler=Waifu2x(num_streams=streams, tiles=tiles, scaler=ZewiaCubicNew),
        antialiaser=Eedi3(alpha=0.1, beta=0.2, gamma=60, nrad=3, vthresh0=12, vthresh1=24, field=1, sclip_aa=None)
    ).std.MaskedMerge(scaled, err_mask)

    # Debanding.
    pref = retinex(prefilter_to_full_range(baa, 5.0, planes=0), [50, 150, 450])
    deb_mask = gauss_blur(deband_detail_mask(pref, brz=(0.04, 0.065)), 2.0)
    flat = gauss_blur(flat_mask(baa, radius=2, thr=0.0065), 4.0)

    deband_mask = ExprOp.ADD(deb_mask, flat).std.Limiter()

    deband = Placebo.deband(baa, radius=64, thr=1.2, iterations=8)

    deband_masked = deband.std.MaskedMerge(baa, deband_mask)

    # Regraining.
    grain = AddNoise.FBM_SIMPLEX.grain(
        deband_masked, strength=(2.0, 0.0), size=1.03,
        luma_scaling=3.0, seed=69420, dynamic=True
    )

    return grain.std.SetFrameProps(_SARNum=1, _SARDen=1)
