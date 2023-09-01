from __future__ import annotations
from enum import Enum

__all__: list[str] = [
    "FilesizeUnits",
]


class FilesizeUnits(Enum):
    """An enum representing the units for bytes."""

    BYTES = 0
    KILOBYTES = 1
    MEGABYTES = 2
    GIGABYTES = 3
    TERABYTES = 4
    PETABYTES = 5

    def __str__(self) -> str:
        """Return the short abbreviation of the current unit."""
        first_char = self.name[0].upper()

        if first_char.startswith('B'):
            return first_char

        return first_char + 'B'

    def from_bytes(self, filesize_in_bytes: int) -> float:
        """Convert a filesize from bytes into the current unit."""
        if self is self.BYTES:
            return filesize_in_bytes

        return filesize_in_bytes / self.factor

    def to_bytes(self, filesize: float) -> int:
        """Convert a filesize in the current unit to bytes."""
        if self is self.BYTES:
            return int(filesize)

        return int(filesize * self.factor)

    def from_unit(self, filesize: float, unit: FilesizeUnits) -> float:
        """Convert a filesize from a given unit to the current unit."""
        if self is unit:
            return filesize

        return self.from_bytes(unit.to_bytes(filesize))

    def to_unit(self, filesize: float, unit: FilesizeUnits) -> float:
        """Convert a filesize from the current unit to a given unit."""
        if self is unit:
            return filesize

        return unit.from_bytes(self.to_bytes(filesize))

    def pretty_string(self, filesize_in_bytes: int) -> str:
        """Create a pretty string using a given filesize in bytes."""
        return f"{round(self.from_bytes(filesize_in_bytes), 2)}{self}"

    @classmethod
    def human_readable_string(self, filesize_in_bytes: int) -> str:
        """
        Create a human-readable pretty string using a given filesize in bytes.

        This automatically uses the largest sensible unit.
        """
        factors = self.get_factors()
        factors.reverse()

        for factor, unit in factors:
            if filesize_in_bytes >= factor:
                break

        return unit.pretty_string(filesize_in_bytes)

    @classmethod
    def get_factors(self) -> list[tuple[int, FilesizeUnits]]:
        """A list of filesize factors and suffixes in reverse order."""
        unit_vals = [(unit.factor, unit) for unit in FilesizeUnits]

        return unit_vals

    @property
    def factor(self) -> int:
        """Factor of the current unit."""
        return 1024 ** self.value
