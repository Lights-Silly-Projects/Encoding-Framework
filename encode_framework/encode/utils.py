from typing import Any


__all__: list[str] = [
    "normalize_track_type_args",
    "split_track_args",
]


def normalize_track_type_args(track_args: dict[str, Any]) -> dict[str, Any]:
    """
    Normalize track type arguments by converting underscores to dashes in keys
    and handling special track type flags.
    """

    flag_params = [
        "hearing_impaired",
        "visual_impaired",
        "text_description",
        "original",
        "commentary",
    ]

    normalized_args = {k.replace("_", "-"): v for k, v in track_args.items()}

    for param in flag_params:
        if param in track_args:
            param_key = f"{param.replace('_', '-')}-flag"

            normalized_args[param_key] = track_args[param]
            normalized_args.pop(param.replace("_", "-"), None)

    return normalized_args


def split_track_args(track_args: dict[str, Any], track_num: int = 0) -> dict[str, Any]:
    """
    Split track arguments into to_track parameters and command-line args.

    Returns:
        tuple: (to_track_kwargs, args_list) where:
        - to_track_kwargs: dict of parameters that to_track accepts
        - args_list: list of command-line argument strings
    """

    # Parameters that to_track accepts directly
    to_track_params = {
        "name",
        "lang",
        "default",
        "forced",
    }

    to_track_kwargs = {}
    args_list = []

    for param in to_track_params:
        if param in track_args:
            to_track_kwargs[param] = track_args[param]
            track_args.pop(param, None)

    for param, value in track_args.items():
        if value is None:
            continue

        if not isinstance(value, bool):
            args_list.append(f"--{param} 0:{value}")
        else:
            args_list.append(f"--{param} 0:{'yes' if value else 'no'}")

    to_track_kwargs["args"] = args_list

    return to_track_kwargs
