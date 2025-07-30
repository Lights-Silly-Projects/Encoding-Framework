import os
from typing import Literal, Sequence

from dataclasses import dataclass, field
from fractions import Fraction
from functools import lru_cache

from vstools import PackageStorage, SPath, SPathLike, to_arr, core
from vssource.utils import opt_ints, opt_int
from vssource import ExternalIndexer

__all__ = [
    'DGIndexNVAddFilenames',
]


class _SetItemMeta:
    def __setitem__(self, key: str, value: float | int) -> None:
        return self.__setattr__(key, value)


@dataclass
class IndexFileFrameData(_SetItemMeta):
    matrix: int
    pic_type: str


@dataclass
class _IndexFileInfoBase(_SetItemMeta):
    path: SPath
    file_idx: int


@dataclass
class IndexFileInfo(_IndexFileInfoBase):
    frame_data: list[IndexFileFrameData]


@dataclass
class DGIndexHeader(_SetItemMeta):
    device: int = 0
    decode_modes: list[int] = field(default_factory=lambda: [0, 0, 0, 0, 0])
    stream: tuple[int, ...] = (1, 0)
    ranges: list[int] = field(default_factory=lambda: [0, 0, 0, 0])
    depth: int = 8
    aspect: Fraction = Fraction(16, 9)
    colorimetry: tuple[int, ...] = (2, 2, 2)
    packet_size: int | None = None
    vpid: int | None = None


@dataclass
class DGIndexFrameData(IndexFileFrameData):
    vob: int | None
    cell: int | None


@dataclass
class DGIndexFooter(_SetItemMeta):
    film: float = 0.0
    frames_coded: int = 0
    frames_playback: int = 0
    order: int = 0


@dataclass
class DGIndexFileInfo(_IndexFileInfoBase):
    header: DGIndexHeader
    frame_data: list[DGIndexFrameData]
    footer: DGIndexFooter


class DGIndexNV(ExternalIndexer):
    _bin_path = 'DGIndexNV'
    _ext = 'dgi'
    _source_func = core.lazy.dgdecodenv.DGSource

    def get_cmd(self, files: list[SPath], output: SPath) -> list[str]:
        return list(
            map(str, [
                self._get_bin_path(), '-i',
                ','.join(str(path.absolute()) for path in files),
                '-h', '-o', output, '-e'
            ])
        )

    def update_video_filenames(self, index_path: SPath, filepaths: list[SPath]) -> None:
        lines = index_path.read_lines()

        str_filepaths = list(map(str, filepaths))

        if 'DGIndexNV' not in lines[0]:
            self.file_corrupted(index_path)

        start_videos = lines.index('') + 1
        end_videos = lines.index('', start_videos)

        if end_videos - start_videos != len(str_filepaths):
            self.file_corrupted(index_path)

        split_lines = [
            line.split(' ') for line in lines[start_videos:end_videos]
        ]

        current_paths = [line[:-1][0] for line in split_lines]

        if current_paths == str_filepaths:
            return

        video_args = [line[-1:] for line in split_lines]

        lines[start_videos:end_videos] = [
            ' '.join([path, *args]) for path, args in zip(str_filepaths, video_args)
        ]

        index_path.write_lines(lines)

    @lru_cache
    def get_info(self, index_path: SPath, file_idx: int = -1) -> DGIndexFileInfo:
        with open(index_path, 'r') as file:
            file_content = file.read()

        lines = file_content.split('\n')

        head, lines = self._split_lines(lines)

        if 'DGIndexNV' not in head[0]:
            self.file_corrupted(index_path)

        vid_lines, lines = self._split_lines(lines)
        raw_header, lines = self._split_lines(lines)

        header = DGIndexHeader()

        for rlin in raw_header:
            if split_val := rlin.rstrip().split(' '):
                key: str = split_val[0].upper()
                values: list[str] = split_val[1:]
            else:
                continue

            if key == 'DEVICE':
                header.device = int(values[0])
            elif key == 'DECODE_MODES':
                header.decode_modes = list(map(int, values[0].split(',')))
            elif key == 'STREAM':
                header.stream = tuple(map(int, values))
            elif key == 'RANGE':
                header.ranges = list(map(int, values))
            elif key == 'DEMUX':
                continue
            elif key == 'DEPTH':
                header.depth = int(values[0])
            elif key == 'ASPECT':
                try:
                    header.aspect = Fraction(*list(map(int, values)))
                except ZeroDivisionError:
                    header.aspect = Fraction(1, 1)
                    if os.environ.get('VSSOURCE_DEBUG', False):
                        print(ResourceWarning('Encountered video with 0/0 aspect ratio!'))
            elif key == 'COLORIMETRY':
                header.colorimetry = tuple(map(int, values))
            elif key == 'PKTSIZ':
                header.packet_size = int(values[0])
            elif key == 'VPID':
                header.vpid = int(values[0])

        video_sizes = [int(line[-1]) for line in [line.split(' ') for line in vid_lines]]

        max_sector = sum([0, *video_sizes[:file_idx + 1]])

        idx_file_sector = [max_sector - video_sizes[file_idx], max_sector]

        curr_SEQ, frame_data = 0, []

        for rawline in lines:
            if len(rawline) == 0:
                break

            line: Sequence[str | None] = [*rawline.split(" ", maxsplit=6), *([None] * 6)]

            name = str(line[0])

            if name == 'SEQ':
                curr_SEQ = opt_int(line[1]) or 0

            if curr_SEQ < idx_file_sector[0]:
                continue
            elif curr_SEQ > idx_file_sector[1]:
                break

            try:
                int(name.split(':')[0])
            except ValueError:
                continue

            frame_data.append(DGIndexFrameData(
                int(line[2] or 0) + 2, str(line[1]), *opt_ints(line[4:6])
            ))

        footer = DGIndexFooter()

        for rlin in lines[-10:]:
            if split_val := rlin.rstrip().split(' '):
                values = [split_val[0], ' '.join(split_val[1:])]
            else:
                continue

            for key in footer.__dict__.keys():
                if key.split('_')[-1].upper() in values:
                    if key == 'film':
                        try:
                            value = [float(v.replace('%', '')) for v in values if '%' in v][0]
                        except IndexError:
                            value = 0
                    else:
                        value = int(values[1])

                    footer[key] = value

        return DGIndexFileInfo(index_path, file_idx, header, frame_data, footer)


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
