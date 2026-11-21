"""Memory-mapped member index for large ZIP archives.

Built once per archive into a compact sorted layout that any number of
processes can map read-only, so a worker pool shares one page-cached
index instead of each process materializing the archive's ZipInfo set.
"""

from __future__ import annotations

import mmap
import os
import struct
import tempfile
import zlib
from array import array
from dataclasses import dataclass
from pathlib import Path

from edgar_sec.foundation.runtime.memory import reclaim
from edgar_sec.infra.storage.bulk_archive import MEMBER_INDEX_FILE_NAME
from edgar_sec.infra.storage.parquet import read_parquet_table

_MAGIC = b"MBIDX001"
_HEADER = struct.Struct("<8sQQQ32s")
_LOCAL_HEADER = struct.Struct("<IHHHHHIIIHH")
_CD_HEADER = struct.Struct("<IHHHHHHIIIHHHHHII")
_ZIP64_EXTRA = 0x0001
_STORED = 0
_DEFLATE = 8

__all__ = ["MemberEntry", "MemberIndex", "ensure_member_index"]


@dataclass(frozen=True, slots=True)
class MemberEntry:
    """One member's location and integrity data within its archive."""

    header_offset: int
    compressed_size: int
    uncompressed_size: int
    crc32: int


def _section_offsets(count: int, names_size: int) -> tuple[int, int, int, int, int]:
    """Byte offsets of the (names, headers, compressed, uncompressed, crc) sections."""
    names_at = _HEADER.size + 8 * (count + 1)
    headers_at = names_at + names_size
    headers_at += -headers_at % 8
    compressed_at = headers_at + 8 * count
    uncompressed_at = compressed_at + 8 * count
    crc_at = uncompressed_at + 8 * count
    return names_at, headers_at, compressed_at, uncompressed_at, crc_at


class MemberIndex:
    """Read-only sorted member index over a memory-mapped index file."""

    def __init__(self, index_path: str | Path) -> None:
        self._file = open(index_path, "rb")
        self._map = mmap.mmap(self._file.fileno(), 0, access=mmap.ACCESS_READ)
        magic, count, names_size, _zip_size, _sha = _HEADER.unpack_from(self._map, 0)
        if magic != _MAGIC:
            self.close()
            raise ValueError(f"{index_path} is not a member index file")
        self._count = count
        sections = _section_offsets(count, names_size)
        self._names_at = sections[0]
        self._headers_at = sections[1]
        self._compressed_at = sections[2]
        self._uncompressed_at = sections[3]
        self._crc_at = sections[4]
        self._offsets_at = _HEADER.size

    def __len__(self) -> int:
        return self._count

    def close(self) -> None:
        self._map.close()
        self._file.close()

    def find(self, member_name: str) -> MemberEntry | None:
        """The entry for ``member_name``, or None when it is not a member."""
        position = self._position(member_name.encode("utf-8"))
        if position is None:
            return None
        return MemberEntry(
            header_offset=self._uint64(self._headers_at, position),
            compressed_size=self._uint64(self._compressed_at, position),
            uncompressed_size=self._uint64(self._uncompressed_at, position),
            crc32=self._uint32(self._crc_at, position),
        )

    def read_member(self, zip_fd: int, member_name: str) -> bytes | None:
        """One member's inflated bytes from an open archive descriptor.

        None means the member is absent; a corrupt or unsupported member
        raises ValueError, matching zipfile's refusal to serve it.
        """
        entry = self.find(member_name)
        if entry is None:
            return None
        header = _LOCAL_HEADER.unpack(
            os.pread(zip_fd, _LOCAL_HEADER.size, entry.header_offset)
        )
        if header[0] != 0x04034B50:
            raise ValueError(f"member {member_name!r} has no local header")
        flags, method = header[2], header[3]
        if flags & 0x1:
            raise ValueError(f"member {member_name!r} is encrypted")
        data_at = entry.header_offset + _LOCAL_HEADER.size + header[9] + header[10]
        raw = os.pread(zip_fd, entry.compressed_size, data_at)
        if method == _STORED:
            payload = raw
        elif method == _DEFLATE:
            payload = zlib.decompress(raw, wbits=-zlib.MAX_WBITS)
        else:
            raise ValueError(
                f"member {member_name!r} uses unsupported compression {method}"
            )
        if len(payload) != entry.uncompressed_size:
            raise ValueError(f"member {member_name!r} size mismatch")
        if zlib.crc32(payload) != entry.crc32:
            raise ValueError(f"member {member_name!r} failed its CRC check")
        return payload

    def _position(self, key: bytes) -> int | None:
        low, high = 0, self._count
        while low < high:
            middle = (low + high) // 2
            if self._name_at(middle) < key:
                low = middle + 1
            else:
                high = middle
        if low < self._count and self._name_at(low) == key:
            return low
        return None

    def _name_at(self, position: int) -> bytes:
        start = self._uint64(self._offsets_at, position)
        end = self._uint64(self._offsets_at, position + 1)
        return bytes(self._map[self._names_at + start : self._names_at + end])

    def _uint64(self, section_at: int, position: int) -> int:
        return struct.unpack_from("<Q", self._map, section_at + 8 * position)[0]

    def _uint32(self, section_at: int, position: int) -> int:
        return struct.unpack_from("<I", self._map, section_at + 4 * position)[0]


def ensure_member_index(zip_path: str | Path, archive_sha256: str) -> Path:
    """The shared index file for one archive, building it when stale or absent."""
    archive = Path(zip_path)
    target = Path(tempfile.gettempdir()) / f"member-index-{archive_sha256}.bin"
    if not _is_current(target, archive, archive_sha256):
        _write_index(target, archive, archive_sha256, _collect_sections(archive))
        reclaim()
    return target


def _is_current(index_path: Path, archive: Path, archive_sha256: str) -> bool:
    try:
        with open(index_path, "rb") as handle:
            header = handle.read(_HEADER.size)
        if len(header) != _HEADER.size:
            return False
        magic, count, names_size, zip_size, sha = _HEADER.unpack(header)
        crc_end = _section_offsets(count, names_size)[4] + 4 * count
        return (
            magic == _MAGIC
            and sha == bytes.fromhex(archive_sha256)
            and zip_size == archive.stat().st_size
            and index_path.stat().st_size == crc_end
        )
    except (OSError, ValueError):
        return False


_Sections = tuple[int, bytes, bytes, bytes, bytes, bytes, bytes]


def _collect_sections(archive: Path) -> _Sections:
    """Sorted index sections, from the store's parquet index when one is beside the ZIP."""
    parquet_path = archive.parent / MEMBER_INDEX_FILE_NAME
    if parquet_path.is_file():
        return _parquet_sections(parquet_path)
    rows = _central_directory_rows(archive)
    rows.sort(key=lambda row: row[0])
    offsets = array("Q", [0]) * (len(rows) + 1)
    running = 0
    for position, row in enumerate(rows):
        running += len(row[0])
        offsets[position + 1] = running
    return (
        len(rows),
        offsets.tobytes(),
        b"".join(row[0] for row in rows),
        array("Q", [row[4] for row in rows]).tobytes(),
        array("Q", [row[2] for row in rows]).tobytes(),
        array("Q", [row[3] for row in rows]).tobytes(),
        array("I", [row[1] for row in rows]).tobytes(),
    )


def _parquet_sections(parquet_path: Path) -> _Sections:
    """Index sections taken from the parquet buffers, widening only the offsets."""
    table = read_parquet_table(parquet_path).sort_by("member_name")
    names = table.column("member_name").combine_chunks()
    name_buffers = names.buffers()
    narrow_offsets = array("i")
    narrow_offsets.frombytes(bytes(name_buffers[1]))
    blob = bytes(name_buffers[2])[: narrow_offsets[-1]]

    def _values(column: str) -> bytes:
        return bytes(table.column(column).combine_chunks().buffers()[1])

    crc_wide = array("q")
    crc_wide.frombytes(_values("crc32"))
    return (
        len(narrow_offsets) - 1,
        array("Q", narrow_offsets).tobytes(),
        blob,
        _values("header_offset"),
        _values("compressed_size"),
        _values("uncompressed_size"),
        array("I", crc_wide).tobytes(),
    )


def _write_index(
    target: Path, archive: Path, archive_sha256: str, sections: _Sections
) -> None:
    count, offsets, blob, headers, compressed, uncompressed, crcs = sections
    layout = _section_offsets(count, len(blob))
    staging = target.with_suffix(f".{os.getpid()}.tmp")
    with open(staging, "wb") as handle:
        handle.write(
            _HEADER.pack(
                _MAGIC,
                count,
                len(blob),
                archive.stat().st_size,
                bytes.fromhex(archive_sha256),
            )
        )
        handle.write(offsets)
        handle.write(blob)
        handle.write(b"\0" * (layout[1] - layout[0] - len(blob)))
        handle.write(headers)
        handle.write(compressed)
        handle.write(uncompressed)
        handle.write(crcs)
    os.replace(staging, target)


def _central_directory_rows(archive: Path) -> list[tuple[bytes, int, int, int, int]]:
    """Stream the ZIP central directory without materializing ZipInfo objects."""
    size = archive.stat().st_size
    with open(archive, "rb") as handle:
        count, cd_offset, cd_size = _directory_bounds(handle, size)
        handle.seek(cd_offset)
        cursor = _Cursor(handle, cd_size)
        rows = []
        for _ in range(count):
            fixed = cursor.take(_CD_HEADER.size)
            fields = _CD_HEADER.unpack(fixed)
            crc, compressed_size, uncompressed_size = fields[7], fields[8], fields[9]
            name_len, extra_len, comment_len = fields[10], fields[11], fields[12]
            header_offset = fields[16]
            name = cursor.take(name_len)
            extra = cursor.take(extra_len)
            cursor.take(comment_len)
            if (
                uncompressed_size == 0xFFFFFFFF
                or compressed_size == 0xFFFFFFFF
                or header_offset == 0xFFFFFFFF
            ):
                uncompressed_size, compressed_size, header_offset = _zip64_sizes(
                    extra, uncompressed_size, compressed_size, header_offset
                )
            rows.append(
                (
                    _member_key(name, fields[3]),
                    crc,
                    compressed_size,
                    uncompressed_size,
                    header_offset,
                )
            )
    return rows


def _directory_bounds(handle, size: int) -> tuple[int, int, int]:
    """(entry count, directory offset, directory size), ZIP64-aware."""
    tail_len = min(size, 22 + 65536)
    handle.seek(size - tail_len)
    tail = handle.read(tail_len)
    eocd = tail.rfind(b"PK\x05\x06")
    if eocd < 0:
        raise ValueError("not a ZIP archive: no end of central directory")
    fields = struct.unpack_from("<IHHHHIIH", tail, eocd)
    count, cd_size, cd_offset = fields[4], fields[5], fields[6]
    if count != 0xFFFF and cd_size != 0xFFFFFFFF and cd_offset != 0xFFFFFFFF:
        return count, cd_offset, cd_size
    eocd_at = size - tail_len + eocd
    handle.seek(eocd_at - 20)
    locator = handle.read(20)
    if len(locator) != 20 or locator[:4] != b"PK\x06\x07":
        raise ValueError("not a ZIP64 archive: no locator before the end record")
    zip64_at = struct.unpack_from("<Q", locator, 8)[0]
    handle.seek(zip64_at)
    record = struct.unpack_from("<IQHHIIQQQQ", handle.read(56))
    if record[0] != 0x06064B50:
        raise ValueError("not a ZIP64 archive: bad 64-bit end record")
    return record[7], record[9], record[8]


def _zip64_sizes(
    extra: bytes, uncompressed: int, compressed: int, header_offset: int
) -> tuple[int, int, int]:
    """Resolve 0xFFFFFFFF placeholders from the ZIP64 extra field, in field order."""
    position = 0
    while position + 4 <= len(extra):
        field_id, field_size = struct.unpack_from("<HH", extra, position)
        position += 4
        if field_id == _ZIP64_EXTRA:
            values = struct.unpack_from(f"<{field_size // 8}Q", extra, position)
            index = 0
            if uncompressed == 0xFFFFFFFF:
                uncompressed, index = values[index], index + 1
            if compressed == 0xFFFFFFFF:
                compressed, index = values[index], index + 1
            if header_offset == 0xFFFFFFFF:
                header_offset = values[index]
            return uncompressed, compressed, header_offset
        position += field_size
    raise ValueError("ZIP64 member is missing its extra field")


def _member_key(raw_name: bytes, flags: int) -> bytes:
    """The index key for a central-directory name: its zipfile-reported form, UTF-8."""
    encoding = "utf-8" if flags & 0x800 else "cp437"
    try:
        return raw_name.decode(encoding).encode("utf-8")
    except UnicodeDecodeError:
        return raw_name


class _Cursor:
    """Bounded forward reader over one region of an open file."""

    def __init__(self, handle, size: int) -> None:
        self._handle = handle
        self._remaining = size
        self._buffer = bytearray()

    def take(self, count: int) -> bytes:
        while len(self._buffer) < count:
            if self._remaining <= 0:
                raise ValueError("central directory is truncated")
            chunk = self._handle.read(min(1 << 20, self._remaining))
            if not chunk:
                raise ValueError("central directory is truncated")
            self._remaining -= len(chunk)
            self._buffer += chunk
        taken = bytes(self._buffer[:count])
        del self._buffer[:count]
        return taken
