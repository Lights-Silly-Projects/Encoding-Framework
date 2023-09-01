
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, no_type_check

from git import GitCommandError, RemoteProgress, Repo
from rich import console, progress
from vstools import SPath, SPathLike

from .logging import Log

__all__: list[str] = [
    "clone_git_repo",
    "create_gitignore"
]


def clone_git_repo(
    url: str, out_dir: SPathLike | None = None
) -> SPath:
    """Clone a git repository."""
    repo_name = str(url).split("/")[-1].split(".")[0]

    if out_dir is None:
        out_dir = SPath.cwd() / repo_name

    out_path = SPath(out_dir)

    if SPath(out_path / ".git").exists():
        return out_path

    try:
        Log.info(f"Cloning repository \"{repo_name}\" (\"{url}\")...", clone_git_repo)
        Repo.clone_from(url, out_path.to_str(), progress=_CloneProgress())  # type:ignore[arg-type]
    except GitCommandError as e:
        if "already exists" in str(e):
            Log.info(f"\"{repo_name}\" has already been cloned!")
        else:
            raise Log.error(str(e), clone_git_repo)

        pass
    except Exception as e:
        raise Log.error(str(e), clone_git_repo)

    return out_path


class _CloneProgress(RemoteProgress):
    OP_CODES = [
        "BEGIN",
        "CHECKING_OUT",
        "COMPRESSING",
        "COUNTING",
        "END",
        "FINDING_SOURCES",
        "RECEIVING",
        "RESOLVING",
        "WRITING",
    ]
    OP_CODE_MAP = {
        getattr(RemoteProgress, _op_code): _op_code for _op_code in OP_CODES
    }

    def __init__(self) -> None:
        super().__init__()
        self.progressbar = progress.Progress(
            progress.SpinnerColumn(),
            # *progress.Progress.get_default_columns(),
            progress.TextColumn("[progress.description]{task.description}"),
            progress.BarColumn(),
            progress.TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            "eta",
            progress.TimeRemainingColumn(),
            progress.TextColumn("{task.fields[message]}"),
            console=console.Console(),
            transient=False,
        )
        self.progressbar.start()
        self.active_task = None

    def __del__(self) -> None:
        # logger.info("Destroying bar...")
        self.progressbar.stop()

    @classmethod
    def get_curr_op(cls, op_code: int) -> str:
        """Get OP name from OP code."""
        # Remove BEGIN- and END-flag and get op name
        op_code_masked = op_code & cls.OP_MASK
        return cls.OP_CODE_MAP.get(op_code_masked, "?").title()

    @no_type_check
    def update(
        self,
        op_code: int,
        cur_count: str | float,
        max_count: str | float | None = None,
        message: str | None = "",
    ) -> None:
        # Start new bar on each BEGIN-flag
        if op_code & self.BEGIN:
            self.curr_op = self.get_curr_op(op_code)
            # logger.info("Next: %s", self.curr_op)
            self.active_task = self.progressbar.add_task(
                description=self.curr_op,
                total=max_count,
                message=message,
            )

        self.progressbar.update(
            task_id=self.active_task,
            completed=cur_count,
            message=message,
        )

        # End progress monitoring on each END-flag
        if op_code & self.END:
            # logger.info("Done: %s", self.curr_op)
            self.progressbar.update(
                task_id=self.active_task,
                message=f"[bright_black]{message}",
            )


def create_gitignore(
    out_file: str = ".gitignore",
    options: list[Any] = [],
    **kwargs: Any
) -> Path:
    """Simple function to create a gitignore."""

    gitignore = Path(out_file)

    if not options:
        return gitignore

    lines = "\n".join([str(x) for x in options]) + "\n"

    _write_file(gitignore, "w" if not gitignore.exists() else "a", lines, **kwargs)

    return gitignore


def _write_file(file: Path, mode: str, lines: str, **kwargs: Any) -> None:
    header = "# Autogenerated .gitignore file (through Light's automated encode tooling)\n" + \
        f"# Generated at {datetime.now()}\n\n"

    with open(file, mode, **kwargs) as f:
        if mode == "w":
            f.write(header)

        f.write(lines)