import os
from typing import Literal, Sequence

from vssource import DGIndexNV
from vstools import PackageStorage, SPath, SPathLike, to_arr

__all__ = [
    'DGIndexNVAddFilenames',
]


class DGIndexNVAddFilenames(DGIndexNV):
    """DGIndexNV with the filenames added to the index file."""

    def index(
        self, files: Sequence[SPath], force: bool = False, split_files: bool = False,
        output_folder: SPathLike | Literal[False] | None = None, *cmd_args: str
    ) -> list[SPath]:
        files = to_arr(files)

        if len(unique_folders := list(set([f.get_folder().to_str() for f in files]))) > 1:
            return [
                c for s in (
                    self.index(
                        [f for f in files if f.get_folder().to_str() == folder],
                        force, split_files, output_folder
                    )
                    for folder in unique_folders
                ) for c in s
            ]

        dest_folder = self.get_out_folder(output_folder, files[0])

        files = list(sorted(set(files)))

        hash_str = self.get_videos_hash(files)

        def _index(files: list[SPath], output: SPath) -> None:
            if output.is_file():
                if output.stat().st_size == 0 or force:
                    output.unlink()
                else:
                    return self.update_video_filenames(output, files)

            return self._run_index(files, output, cmd_args)

        if not split_files:
            output = self.get_video_idx_path(files[0], dest_folder, hash_str, 'JOINED' if len(files) > 1 else 'SINGLE')
            _index(files, output)
            return [output]

        outputs = [self.get_video_idx_path(file, dest_folder, hash_str, file.name) for file in files]

        for file, output in zip(files, outputs):
            _index([file], output)

        return outputs

    def get_video_idx_path(self, file_name: SPath, folder: SPath, file_hash: str, video_name: SPathLike) -> SPath:
        vid_name = SPath(video_name).stem
        current_indxer = os.path.basename(self._bin_path)
        filename = '_'.join([file_name.stem, file_hash, vid_name, current_indxer])

        return self.get_idx_file_path(PackageStorage(folder).get_file(filename))
