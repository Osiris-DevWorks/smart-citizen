"""The game's tag tree, read straight out of Game2.dcb.

A mission spawns its ships by tags (a faction, a difficulty class, a ship
model), and each ship entity lists the tags it carries. Matching the two
names the ships a mission can spawn, but a spawn option often asks for a
parent tag (``AI/Faction``) while a ship carries its child
(``AI/Faction/Criminal``), and nothing in the XML unforge writes says which
tag is under which: the tags are not records of their own, only struct
instances the TagDatabase record points at, so unforge writes the
TagDatabase's list of ids and nothing else. The names are needed too: a
spawn option that matches no ship is shown by its tags' names.

So this reads them from the database file unforge converts, during the
DataForge extraction while Game2.dcb is still in the working folder, and
``pak_extractor`` saves the result beside the cache as
``DATAFORGE_TAGS_FILE``: ``{"version": 1, "tags": {guid: [name, parent]}}``,
the parent ``None`` for a root tag. A database this cannot read (a new
format after a game patch) saves the file with no tags and the error, so the
cache still reads as complete and the generator falls back to spawn counts.

The format, as unforge reads it (only what this needs): a header of two
int32s (zero and the version), four uint16s, then 26 uint32 counts. Then the
struct, property, enum, data-mapping and record tables, the value arrays
(their sizes from the counts), the text table, the blob table (struct and
property names), and last the struct instances, one data mapping after the
other. A record is 32 bytes before version 8 and 36 from it (an extra name
offset), so the size is the one that makes the instances end exactly at the
end of the file. A GUID is stored as two little-endian 8-byte halves.

Stdlib only and Qt-free. Locked by ``tests/test_dcb_tags.py``.
"""

from __future__ import annotations

import json
import mmap
import struct
import uuid
from pathlib import Path

TAG_DATABASE_VERSION = 1

_HEADER = struct.Struct("<ii4H26I")
_STRUCT_DEF = struct.Struct(
    "<IIHHI"
)  # name, parent, property count, first property, node type
_PROPERTY_DEF = struct.Struct("<IHHHH")  # name, struct, data type, conversion, padding
_ENUM_DEF = struct.Struct("<IHH")
_MAPPING = struct.Struct("<II")  # instance count, struct
_RECORD_SIZES = (36, 32)
_NO_PARENT = 0xFFFFFFFF

# Data types and their inline sizes; a property with a conversion (an array)
# is a uint32 count and a uint32 first index instead.
_CLASS = 0x0010
_INLINE_SIZE = {
    0x0001: 1,
    0x0002: 1,
    0x0003: 2,
    0x0004: 4,
    0x0005: 8,
    0x0006: 1,
    0x0007: 2,
    0x0008: 4,
    0x0009: 8,
    0x000A: 4,
    0x000B: 4,
    0x000C: 8,
    0x000D: 4,
    0x000E: 16,
    0x000F: 4,
    0x0110: 8,
    0x0210: 8,
    0x0310: 20,
}
# The value arrays between the record table and the text table, in file
# order, by their header count's index and their element size.
_VALUE_ARRAYS = (
    (6, 1),
    (7, 2),
    (8, 4),
    (9, 8),
    (10, 1),
    (11, 2),
    (12, 4),
    (13, 8),  # int8..uint64
    (5, 1),  # bool
    (14, 4),
    (15, 8),
    (16, 16),  # single, double, guid
    (17, 4),
    (18, 4),
    (19, 4),  # string, locale, enum
    (20, 8),
    (21, 8),  # strong, weak
    (22, 20),  # reference
    (23, 4),  # enum option
)
_REFERENCE_INDEX = 22
_REFERENCE_SIZE = 20


class DcbFormatError(ValueError):
    """Game2.dcb is not laid out as this reader expects."""


def guid_text(raw: bytes) -> str:
    """A 16-byte DataForge GUID as unforge writes it in the XML."""
    return str(uuid.UUID(bytes=raw[7::-1] + raw[15:7:-1]))


def _cstring(data, start: int, offset: int, end: int) -> str:
    pos = start + offset
    if not start <= pos < end:
        raise DcbFormatError(f"string offset {offset} is outside its table")
    stop = data.find(b"\0", pos, end)
    if stop < 0:
        raise DcbFormatError(f"string at {offset} has no end")
    return bytes(data[pos:stop]).decode("utf-8", "replace")


def read_tag_tree(data) -> dict[str, tuple[str, str | None]]:
    """Every tag under the TagDatabase record: ``{guid: (name, parent guid)}``.

    *data* is the whole database as bytes or a memory map. Raises
    DcbFormatError when it is not laid out as expected.
    """
    if len(data) < _HEADER.size:
        raise DcbFormatError("file is shorter than its header")
    header = _HEADER.unpack_from(data, 0)
    counts = header[6:]
    n_struct, n_prop, n_enum, n_map, n_rec = counts[:5]
    text_len, blob_len = counts[24], counts[25]

    offset = _HEADER.size
    structs_at = offset
    offset += n_struct * _STRUCT_DEF.size
    props_at = offset
    offset += n_prop * _PROPERTY_DEF.size
    offset += n_enum * _ENUM_DEF.size
    maps_at = offset
    offset += n_map * _MAPPING.size
    records_at = offset
    values_size = sum(counts[i] * size for i, size in _VALUE_ARRAYS)

    structs = [
        _STRUCT_DEF.unpack_from(data, structs_at + i * _STRUCT_DEF.size)
        for i in range(n_struct)
    ]
    props = [
        _PROPERTY_DEF.unpack_from(data, props_at + i * _PROPERTY_DEF.size)
        for i in range(n_prop)
    ]
    maps = [
        _MAPPING.unpack_from(data, maps_at + i * _MAPPING.size) for i in range(n_map)
    ]

    def struct_props(index: int) -> list[int]:
        chain = []
        seen = set()
        while index != _NO_PARENT:
            if index in seen or index >= n_struct:
                raise DcbFormatError(f"struct {index} has a bad parent chain")
            seen.add(index)
            chain.append(index)
            index = structs[index][1]
        out: list[int] = []
        for s in reversed(chain):
            _, _, count, first, _ = structs[s]
            out.extend(range(first, first + count))
        return out

    sizes: dict[int, int] = {}

    def struct_size(index: int, depth: int = 0) -> int:
        if index in sizes:
            return sizes[index]
        if depth > 64:
            raise DcbFormatError("structs nest too deep")
        total = 0
        for p in struct_props(index):
            if p >= n_prop:
                raise DcbFormatError(f"property {p} is out of range")
            _, p_struct, data_type, conversion, _ = props[p]
            if conversion:
                total += 8
            elif data_type == _CLASS:
                total += struct_size(p_struct, depth + 1)
            elif data_type in _INLINE_SIZE:
                total += _INLINE_SIZE[data_type]
            else:
                raise DcbFormatError(f"unknown data type {data_type:#x}")
        sizes[index] = total
        return total

    instances_size = sum(count * struct_size(s) for count, s in maps)
    record_size = None
    for size in _RECORD_SIZES:
        end = (
            records_at
            + n_rec * size
            + values_size
            + text_len
            + blob_len
            + instances_size
        )
        if end == len(data):
            record_size = size
            break
    if record_size is None:
        raise DcbFormatError("the tables do not add up to the file's size")

    values_at = records_at + n_rec * record_size
    references_at = values_at
    for i, size in _VALUE_ARRAYS:
        if i == _REFERENCE_INDEX:
            break
        references_at += counts[i] * size
    text_at = values_at + values_size
    blob_at = text_at + text_len
    instances_at = blob_at + blob_len

    pools: dict[int, int] = {}
    pos = instances_at
    for count, s in maps:
        pools.setdefault(s, pos)
        pos += count * struct_size(s)

    names = {
        _cstring(data, blob_at, structs[i][0], instances_at): i for i in range(n_struct)
    }
    tag_struct = names.get("Tag")
    database_struct = names.get("TagDatabase")
    if tag_struct is None or database_struct is None:
        raise DcbFormatError("no Tag or TagDatabase struct")

    def field_offsets(index: int) -> dict[str, tuple[int, int, int]]:
        out = {}
        at = 0
        for p in struct_props(index):
            name_offset, p_struct, data_type, conversion, _ = props[p]
            out[_cstring(data, blob_at, name_offset, instances_at)] = (
                at,
                data_type,
                conversion,
            )
            if conversion:
                at += 8
            elif data_type == _CLASS:
                at += struct_size(p_struct)
            else:
                at += _INLINE_SIZE[data_type]
        return out

    tag_fields = field_offsets(tag_struct)
    database_fields = field_offsets(database_struct)
    try:
        name_at, name_type, _ = tag_fields["tagName"]
        children_at, children_type, children_conv = tag_fields["children"]
        list_at, list_type, list_conv = database_fields["tags"]
    except KeyError as e:
        raise DcbFormatError(f"Tag or TagDatabase has no {e} field") from None
    if (
        name_type != 0x000A
        or children_type != 0x0310
        or not children_conv
        or list_type != 0x0310
        or not list_conv
    ):
        raise DcbFormatError("Tag or TagDatabase fields have unexpected types")

    database_instance = None
    for i in range(n_rec):
        at = records_at + i * record_size
        struct_index = struct.unpack_from("<I", data, at + record_size - 24)[0]
        if struct_index == database_struct:
            database_instance = struct.unpack_from("<H", data, at + record_size - 4)[0]
            break
    if database_instance is None:
        raise DcbFormatError("no TagDatabase record")

    tag_count = next((count for count, s in maps if s == tag_struct), 0)
    tag_size = struct_size(tag_struct)
    n_refs = counts[_REFERENCE_INDEX]

    def references(first: int, count: int) -> list[tuple[int, str]]:
        if first + count > n_refs:
            raise DcbFormatError("a reference list runs past its array")
        out = []
        for k in range(first, first + count):
            at = references_at + k * _REFERENCE_SIZE
            index = struct.unpack_from("<I", data, at)[0]
            out.append((index, guid_text(bytes(data[at + 4 : at + 20]))))
        return out

    db_at = pools[database_struct] + database_instance * struct_size(database_struct)
    count, first = struct.unpack_from("<II", data, db_at + list_at)
    tags: dict[str, tuple[str, str | None]] = {}
    stack = [(index, guid, None) for index, guid in reversed(references(first, count))]
    while stack:
        index, guid, parent = stack.pop()
        if guid in tags:
            continue
        if index >= tag_count:
            raise DcbFormatError(f"tag {guid} points past the tag instances")
        at = pools[tag_struct] + index * tag_size
        name = _cstring(
            data, text_at, struct.unpack_from("<I", data, at + name_at)[0], blob_at
        )
        tags[guid] = (name, parent)
        c_count, c_first = struct.unpack_from("<II", data, at + children_at)
        stack.extend(
            (ci, cg, guid) for ci, cg in reversed(references(c_first, c_count))
        )
    if not tags:
        raise DcbFormatError("the TagDatabase holds no tags")
    return tags


def write_tag_database(dcb_path: Path, out_path: Path, write_text) -> str | None:
    """Read *dcb_path*'s tag tree and save it at *out_path* through
    *write_text* (``atomic_io.atomic_write_text``). A database this cannot
    read saves no tags, with the error, and returns the error's text; a
    good read returns None. An OSError writing *out_path* is raised.
    """
    error = None
    try:
        with open(dcb_path, "rb") as f, mmap.mmap(
            f.fileno(), 0, access=mmap.ACCESS_READ
        ) as data:
            tags = read_tag_tree(data)
    except (DcbFormatError, OSError, struct.error, ValueError) as e:
        tags = {}
        error = f"{type(e).__name__}: {e}"
    payload: dict = {
        "version": TAG_DATABASE_VERSION,
        "tags": {g: [name, parent] for g, (name, parent) in sorted(tags.items())},
    }
    if error:
        payload["error"] = error
    write_text(out_path, json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    return error


def load_tag_database(path: Path) -> dict[str, tuple[str, str | None]]:
    """The tags a ``write_tag_database`` file holds; ``{}`` when it is
    missing, unreadable, of another version or saved without tags."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(payload, dict) or payload.get("version") != TAG_DATABASE_VERSION:
        return {}
    tags = payload.get("tags")
    if not isinstance(tags, dict):
        return {}
    out = {}
    for guid, entry in tags.items():
        if isinstance(entry, list) and len(entry) == 2 and isinstance(entry[0], str):
            out[guid] = (entry[0], entry[1] if isinstance(entry[1], str) else None)
    return out


def tag_paths(tags: dict[str, tuple[str, str | None]]) -> dict[str, str]:
    """Each tag's full path, its ancestors' names joined with ``/``
    (``AI/Faction/Criminal``)."""
    out: dict[str, str] = {}
    for guid in tags:
        names = []
        seen = set()
        g: str | None = guid
        while g is not None and g in tags and g not in seen:
            seen.add(g)
            names.append(tags[g][0])
            g = tags[g][1]
        out[guid] = "/".join(reversed(names))
    return out


def with_ancestors(guids, tags: dict[str, tuple[str, str | None]]) -> frozenset[str]:
    """*guids* and every tag above each of them."""
    out = set()
    for guid in guids:
        g: str | None = guid
        while g is not None and g not in out:
            out.add(g)
            g = tags[g][1] if g in tags else None
    return frozenset(out)
