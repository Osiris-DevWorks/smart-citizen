"""The game's tag tree read out of Game2.dcb (src/utils/dcb_tags.py).

Each test builds a small DataForge database in memory with the layout the
reader expects (the header, the struct, property, enum, mapping and record
tables, the reference array, the text and blob tables, then the Tag and
TagDatabase instances), so no game install is needed. Both record sizes are
built: 36 bytes from version 8, 32 before it.
"""

from __future__ import annotations

import json
import struct
import uuid
from pathlib import Path

import pytest

from src.utils import dcb_tags

pytestmark = pytest.mark.unit

ROOT_A = "1ca2768d-33ab-4583-97ac-17afcd0dafb0"
CHILD = "a45f6533-982c-45dc-97ea-0166a3560617"
GRANDCHILD = "9878bc41-7585-4bd2-bc49-8862580b1b3b"
ROOT_B = "66ee5bfc-d90b-41bd-ad2e-e0a2b3efe359"

# (guid, name, child indexes); the TagDatabase lists the roots by index.
TREE = [
    (ROOT_A, "AI", [1]),
    (CHILD, "Faction", [2]),
    (GRANDCHILD, "Criminal", []),
    (ROOT_B, "Ship", []),
]
ROOTS = [0, 3]


def raw_guid(text: str) -> bytes:
    """A GUID as DataForge stores it, the inverse of dcb_tags.guid_text."""
    b = uuid.UUID(text).bytes
    return b[7::-1] + b[15:7:-1]


def build_dcb(tree=TREE, roots=ROOTS, record_size: int = 36, version: int = 8) -> bytes:
    blob = bytearray()
    text = bytearray()

    def name_in(table: bytearray, s: str) -> int:
        offset = len(table)
        table.extend(s.encode("utf-8") + b"\0")
        return offset

    structs = [
        (name_in(blob, "Tag"), 0xFFFFFFFF, 3, 0, 0),
        (name_in(blob, "TagDatabase"), 0xFFFFFFFF, 1, 3, 0),
    ]
    props = [
        (name_in(blob, "legacyGUID"), 0, 0x0008, 0, 0),
        (name_in(blob, "tagName"), 0, 0x000A, 0, 0),
        (name_in(blob, "children"), 0, 0x0310, 1, 0),
        (name_in(blob, "tags"), 0, 0x0310, 1, 0),
    ]
    refs: list[tuple[int, bytes]] = []
    tag_instances = bytearray()
    for _guid, name, children in tree:
        first = len(refs)
        refs.extend((c, raw_guid(tree[c][0])) for c in children)
        tag_instances += struct.pack(
            "<IIII", 0, name_in(text, name), len(children), first
        )
    db_first = len(refs)
    refs.extend((r, raw_guid(tree[r][0])) for r in roots)
    db_instance = struct.pack("<II", len(roots), db_first)
    maps = [(len(tree), 0), (1, 1)]
    record_guid = raw_guid(str(uuid.uuid4()))
    if record_size == 36:
        record = struct.pack("<IIII16sHH", 0, 0, 0, 1, record_guid, 0, 0)
    else:
        record = struct.pack("<III16sHH", 0, 0, 1, record_guid, 0, 0)
    counts = (
        [len(structs), len(props), 0, len(maps), 1] + [0] * 19 + [len(text), len(blob)]
    )
    counts[22] = len(refs)
    out = bytearray(struct.pack("<ii4H26I", 0, version, 0, 0, 0, 0, *counts))
    for s in structs:
        out += struct.pack("<IIHHI", *s)
    for p in props:
        out += struct.pack("<IHHHH", *p)
    for m in maps:
        out += struct.pack("<II", *m)
    out += record
    for index, guid in refs:
        out += struct.pack("<I", index) + guid
    out += text + blob + tag_instances + db_instance
    return bytes(out)


class TestGuidText:
    def test_matches_unforge(self):
        # The TagDatabase record's id as Game2.dcb holds it and unforge writes it.
        raw = bytes.fromhex("bd410bd9fc5bee6659e3efb3a2e02ead")
        assert dcb_tags.guid_text(raw) == ROOT_B

    def test_round_trip(self):
        assert dcb_tags.guid_text(raw_guid(CHILD)) == CHILD


class TestReadTagTree:
    @pytest.mark.parametrize("record_size,version", [(36, 8), (32, 6)])
    def test_every_tag_with_its_parent(self, record_size, version):
        tags = dcb_tags.read_tag_tree(
            build_dcb(record_size=record_size, version=version)
        )
        assert tags == {
            ROOT_A: ("AI", None),
            CHILD: ("Faction", ROOT_A),
            GRANDCHILD: ("Criminal", CHILD),
            ROOT_B: ("Ship", None),
        }

    def test_a_cycle_ends(self):
        tree = [(ROOT_A, "AI", [1]), (CHILD, "Faction", [0])]
        tags = dcb_tags.read_tag_tree(build_dcb(tree, [0]))
        assert tags == {ROOT_A: ("AI", None), CHILD: ("Faction", ROOT_A)}

    def test_a_file_cut_short_is_refused(self):
        data = build_dcb()
        with pytest.raises(dcb_tags.DcbFormatError):
            dcb_tags.read_tag_tree(data[:-3])
        with pytest.raises(dcb_tags.DcbFormatError):
            dcb_tags.read_tag_tree(data[:20])

    def test_a_database_with_no_tags_is_refused(self):
        with pytest.raises(dcb_tags.DcbFormatError):
            dcb_tags.read_tag_tree(build_dcb([(ROOT_A, "AI", [])], []))


class TestWriteAndLoad:
    @staticmethod
    def _write(path: Path, text: str) -> None:
        path.write_text(text, encoding="utf-8")

    def test_saves_the_tree_and_loads_it_back(self, tmp_path):
        dcb = tmp_path / "Game2.dcb"
        dcb.write_bytes(build_dcb())
        out = tmp_path / "tag_database.json"
        assert dcb_tags.write_tag_database(dcb, out, self._write) is None
        saved = json.loads(out.read_text(encoding="utf-8"))
        assert (
            saved["version"] == dcb_tags.TAG_DATABASE_VERSION and "error" not in saved
        )
        assert dcb_tags.load_tag_database(out)[GRANDCHILD] == ("Criminal", CHILD)

    @pytest.mark.parametrize("content", [b"", b"not a database"])
    def test_a_database_it_cannot_read_saves_no_tags_and_the_error(
        self, tmp_path, content
    ):
        dcb = tmp_path / "Game2.dcb"
        dcb.write_bytes(content)
        out = tmp_path / "tag_database.json"
        error = dcb_tags.write_tag_database(dcb, out, self._write)
        assert error
        saved = json.loads(out.read_text(encoding="utf-8"))
        assert saved["tags"] == {} and saved["error"] == error
        assert dcb_tags.load_tag_database(out) == {}

    def test_a_missing_database_saves_no_tags(self, tmp_path):
        out = tmp_path / "tag_database.json"
        assert dcb_tags.write_tag_database(tmp_path / "gone.dcb", out, self._write)
        assert dcb_tags.load_tag_database(out) == {}

    @pytest.mark.parametrize(
        "text",
        [
            None,
            "",
            "{",
            "[]",
            '{"version": 2, "tags": {}}',
            '{"version": 1, "tags": []}',
        ],
    )
    def test_load_reads_nothing_it_does_not_know(self, tmp_path, text):
        path = tmp_path / "tag_database.json"
        if text is not None:
            path.write_text(text, encoding="utf-8")
        assert dcb_tags.load_tag_database(path) == {}

    def test_load_skips_a_malformed_entry(self, tmp_path):
        path = tmp_path / "tag_database.json"
        path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "tags": {
                        ROOT_A: ["AI", None],
                        CHILD: "Faction",
                        GRANDCHILD: [3, None],
                    },
                }
            ),
            encoding="utf-8",
        )
        assert dcb_tags.load_tag_database(path) == {ROOT_A: ("AI", None)}


class TestPathsAndAncestors:
    TAGS = {
        ROOT_A: ("AI", None),
        CHILD: ("Faction", ROOT_A),
        GRANDCHILD: ("Criminal", CHILD),
    }

    def test_paths(self):
        assert dcb_tags.tag_paths(self.TAGS)[GRANDCHILD] == "AI/Faction/Criminal"

    def test_ancestors(self):
        assert dcb_tags.with_ancestors([GRANDCHILD], self.TAGS) == {
            GRANDCHILD,
            CHILD,
            ROOT_A,
        }

    def test_an_unknown_tag_counts_for_itself(self):
        assert dcb_tags.with_ancestors(["x"], self.TAGS) == {"x"}
