import os
import shutil
import threading
from typing import Any
from vstools import CustomValueError, SPath, SPathLike
from vstools import FileWasNotFoundError

__all__: list[str] = [
    "normalize_track_type_args",
    "split_track_args",
    "safe_copy_file",
    "FileProtector",
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
        param = param.replace("_", "-")

        if value is None:
            args_list.append(f"--{param}")
            args_list.append("0:")
            continue

        args_list.append(f"--{param}")

        if isinstance(value, bool):
            value = "yes" if value else "no"

        args_list.append(f"0:{value}")

    to_track_kwargs["args"] = args_list

    return to_track_kwargs


def safe_copy_file(src: SPathLike, dst: SPathLike) -> SPath:
    """
    Safely copy a file, creating independent data since the original may be deleted.

    This function always copies the file data (never uses hardlinks) because
    the original files may be deleted by other processes.

    Args:
        src: Source file path
        dst: Destination file path

    Returns:
        The destination path
    """

    if not (src := SPath(src)).exists():
        raise FileWasNotFoundError(
            f"The source file {src} does not exist.", safe_copy_file
        )

    if not (dst := SPath(dst)).exists():
        raise FileWasNotFoundError(
            f"The destination file {dst} does not exist.", safe_copy_file
        )

    if src == dst:
        raise CustomValueError(
            f"The source and destination files cannot be the same: {src} == {dst}",
            safe_copy_file,
        )

    return SPath(shutil.copy2(src, dst))


class FileProtector:
    """
    Context manager to protect files from deletion by external processes.

    Uses file locking to prevent vsmuxtools and other processes from deleting
    files during critical operations like muxing.
    """

    def __init__(self, protect_files: bool = True):
        """
        Initialize the file protector.

        Args:
            protect_files: Whether to actually protect files (can be disabled for testing)
        """

        self.protect_files = protect_files
        self._protected_files: list[SPath] = []
        self._lock = threading.Lock()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._release_all()

    def protect_file(self, file_path: SPath) -> SPath:
        """
        Protect a file from deletion by creating a read-only copy if needed.

        Args:
            file_path: Path to the file to protect

        Returns:
            Path to the protected file (may be a copy)
        """

        if not self.protect_files:
            return SPath(file_path)

        file_path = SPath(file_path)

        with self._lock:
            if file_path in self._protected_files:
                return file_path

            try:
                if file_path.exists():
                    os.chmod(file_path, 0o444)  # Read-only
                    self._protected_files.append(file_path)

                return file_path

            # If we can't protect the original, create a safe copy
            except (OSError, PermissionError):
                protected_path = file_path.with_suffix(f"{file_path.suffix}.protected")
                safe_copy_file(file_path, protected_path)

                self._protected_files.append(protected_path)

                return protected_path

    def _release_all(self):
        """Release all protected files by restoring their original permissions."""

        with self._lock:
            for file_path in self._protected_files:
                try:
                    if file_path.exists():
                        os.chmod(file_path, 0o644)
                except (OSError, PermissionError):
                    pass

            self._protected_files.clear()

    def protect_multiple(self, *file_paths: SPath) -> list[SPath]:
        """
        Protect multiple files at once.

        Args:
            *file_paths: Paths to files to protect

        Returns:
            List of protected file paths
        """

        return [self.protect_file(path) for path in file_paths]
