"""The player ID test's scanner (``src/utils/sco_tag_scan.py``) on made-up
game pictures.

The fixtures in ``tests/fixtures/sco_tags/`` are two lossless crops the tag
sample saver cut from a 3840x2160 capture of the game: an ``UNKNOWN`` contact
and a ship's serial, each with its distance under it. Neither holds a
player's name. A test pastes them onto a black picture the size of the game's
window and has the scanner look at it.
"""
from pathlib import Path

import pytest

from src.utils import sco_tag_scan
from src.utils.sco_tag_reader import CAP_AT_2160, Frame
from src.utils.sco_tag_scan import (
    EARLY_GAP_S, LATE_GAP_S, SETTLED_READS, TagScanner, distance_under, is_number,
)

FIXTURES = Path(__file__).parent / "fixtures" / "sco_tags"
UNKNOWN = "4k_UNKNOWN.png"
SERIAL = "4k_OA-3601-TW.png"
SIZE = (3840, 2160)
# Where the tests on the distance line put a fixture.
AT = (2200, 1200)


def picture(placed: dict, blank=(), pasted=()) -> Frame:
    """A black 4K picture with each fixture's top-left corner at its place.
    Each (x, y, width, height) of *blank* is then painted black, and each
    (image, x, y) of *pasted* drawn on top."""
    from PyQt6.QtGui import QColor, QImage, QPainter

    image = QImage(SIZE[0], SIZE[1], QImage.Format.Format_RGB32)
    image.fill(QColor(0, 0, 0))
    painter = QPainter(image)
    for name, (x, y) in placed.items():
        painter.drawImage(x, y, QImage(str(FIXTURES / name)))
    for x, y, width, height in blank:
        painter.fillRect(x, y, width, height, QColor(0, 0, 0))
    for piece, x, y in pasted:
        painter.drawImage(x, y, piece)
    painter.end()
    return Frame.from_rgb32(image.width(), image.height(),
                            image.constBits().asstring(image.sizeInBytes()))


def name_box(fixture: str) -> tuple:
    """The box of a fixture's name line in a picture that holds the fixture
    at ``AT``, as the scanner finds it."""
    (reading,) = TagScanner().scan(picture({fixture: AT}), 0.0)
    return reading.box


def under(box) -> tuple:
    """Everything under a name's box that a fixture holds: its distance line."""
    x, y, _w, h = box
    return (AT[0], y + h + 4, 300, 80)


@pytest.fixture(scope="module")
def two_tags(qapp):
    return picture({UNKNOWN: (1200, 700), SERIAL: (2200, 1200)})


def texts(readings):
    return sorted(r.text for r in readings)


def test_it_reads_the_tags_of_a_picture(two_tags):
    readings = TagScanner().scan(two_tags, 0.0)
    assert texts(readings) == ["OA-3601-TW", "UNKNOWN"]
    by_text = {r.text: r for r in readings}
    # Each box is the name's own line, inside the crop that was pasted.
    x, y, w, h = by_text["UNKNOWN"].box
    assert 1200 <= x and x + w <= 1200 + 213 and 700 <= y and y + h <= 700 + 113
    assert 16 <= h <= 18                       # a capital is 17 px at 2160
    x, y, w, h = by_text["OA-3601-TW"].box
    assert 2200 <= x and x + w <= 2200 + 243 and 1200 <= y and y + h <= 1200 + 113
    assert all(r.fresh and r.score > 0.9 and r.crowded == 0 for r in readings)


def test_a_tag_is_carried_until_its_next_read_is_due(two_tags):
    scanner = TagScanner()
    now = 0.0
    assert all(r.fresh for r in scanner.scan(two_tags, now))
    carried = scanner.scan(two_tags, now + 0.3)
    assert texts(carried) == ["OA-3601-TW", "UNKNOWN"]
    assert not any(r.fresh for r in carried)
    # Read again once EARLY_GAP_S has passed, until it has had SETTLED_READS.
    for _read in range(SETTLED_READS - 1):
        now += EARLY_GAP_S + 0.1
        assert all(r.fresh for r in scanner.scan(two_tags, now))
    assert scanner.last_reads == 2
    # Settled: carried for LATE_GAP_S, then read again.
    assert not any(r.fresh for r in scanner.scan(two_tags, now + EARLY_GAP_S + 0.1))
    assert scanner.last_reads == 0 and scanner.last_carried == 2
    assert all(r.fresh for r in scanner.scan(two_tags, now + LATE_GAP_S + 0.1))


def test_a_tag_outside_the_searched_area_is_not_read(qapp):
    assert TagScanner().scan(picture({SERIAL: (10, 10)}), 0.0) == []
    assert TagScanner().scan(picture({SERIAL: (1800, 1950)}), 0.0) == []


def test_it_counts_the_lines_it_found_before_anything_is_dropped(two_tags, qapp):
    """For the Overlay tab's status line: lines found says the picture
    reached the reader and held HUD text, also when no tag was read."""
    scanner = TagScanner()
    assert scanner.last_lines == 0
    # Each tag's name and the distance under it: the two distances are
    # found and then dropped as read-outs.
    assert len(scanner.scan(two_tags, 0.0)) == 2 and scanner.last_lines == 4
    assert len(scanner.scan(picture({SERIAL: (2200, 1200)}), 0.3)) == 1
    assert scanner.last_lines == 2
    assert scanner.scan(picture({}), 0.6) == [] and scanner.last_lines == 0
    assert scanner.scan(picture({SERIAL: (10, 10)}), 0.9) == []     # outside the search
    assert scanner.last_lines == 0


def test_a_tag_that_moves_a_little_is_still_the_same_tag(qapp):
    scanner = TagScanner()
    first = scanner.scan(picture({SERIAL: (2200, 1200)}), 0.0)
    moved = scanner.scan(picture({SERIAL: (2225, 1210)}), 0.3)
    assert texts(moved) == ["OA-3601-TW"] and not moved[0].fresh
    assert (moved[0].box[0] - first[0].box[0], moved[0].box[1] - first[0].box[1]) == (25, 10)


def test_a_tag_that_reads_differently_is_read_again_at_once(qapp):
    scanner = TagScanner()
    scanner.scan(picture({SERIAL: (2200, 1200)}), 0.0)
    changed = scanner.scan(picture({UNKNOWN: (2215, 1200)}), 0.3)
    assert [(r.text, r.fresh) for r in changed] == [("UNKNOWN", True)]


def test_reset_forgets_every_tag(two_tags):
    scanner = TagScanner()
    scanner.scan(two_tags, 0.0)
    scanner.reset()
    assert all(r.fresh for r in scanner.scan(two_tags, 0.3))


class TestTheDistanceLine:
    """Every marker the game draws has its distance under its name, and menu
    and cockpit text has none. With ``need_distance`` set, a line with no
    distance under it is left out before it is read."""

    @staticmethod
    def area_box(box) -> tuple:
        """A box of the picture in the co-ordinates ``distance_under`` takes.
        The tests hand it the whole picture, so they are the same."""
        return box

    def test_a_tag_with_its_distance_under_it_is_read_as_before(self, two_tags):
        scanner = TagScanner()
        scanner.need_distance = True
        assert texts(scanner.scan(two_tags, 0.0)) == ["OA-3601-TW", "UNKNOWN"]
        assert scanner.last_no_distance == 0 and scanner.last_reads == 2

    def test_a_line_with_nothing_under_it_is_left_out(self, qapp):
        serial = name_box(SERIAL)
        shown = picture({SERIAL: AT, UNKNOWN: (1200, 700)}, blank=[under(serial)])
        scanner = TagScanner()
        scanner.need_distance = True
        assert texts(scanner.scan(shown, 0.0)) == ["UNKNOWN"]
        assert scanner.last_no_distance == 1 and scanner.last_reads == 1
        # Without the switch it is read like any other line: the control.
        plain = TagScanner()
        assert texts(plain.scan(shown, 0.0)) == ["OA-3601-TW", "UNKNOWN"]
        assert plain.need_distance is False and plain.last_no_distance == 0

    def test_the_check_finds_the_distance_and_not_other_things(self, qapp):
        from PyQt6.QtGui import QImage

        scanner = TagScanner()
        references = scanner._references
        for fixture in (SERIAL, UNKNOWN):
            box = name_box(fixture)
            whole = picture({fixture: AT})
            assert distance_under(whole, box, CAP_AT_2160, references), fixture
            # With the distance painted out there is nothing under the name.
            assert not distance_under(picture({fixture: AT}, blank=[under(box)]), box,
                                      CAP_AT_2160, references), fixture
            # A distance has no distance of its own: the box of everything
            # under the name, asked the same question.
            x, y, w, h = box
            assert not distance_under(whole, (x, y + h + 19, w, h), CAP_AT_2160, references)
        # A word standing where a distance would stand is not a distance: a
        # menu's next button, a list's next row.
        box = name_box(UNKNOWN)
        x, y, w, h = box
        word = QImage(str(FIXTURES / UNKNOWN)).copy(x - AT[0] - 4, y - AT[1] - 3, w + 8, h + 6)
        stacked = picture({UNKNOWN: AT}, blank=[under(box)], pasted=[(word, x - 4, y + h + 16)])
        assert not distance_under(stacked, box, CAP_AT_2160, references)
        scanner.need_distance = True
        assert scanner.scan(stacked, 0.0) == [] and scanner.last_no_distance == 2

    @staticmethod
    def distance_glyphs():
        """The serial fixture's distance line, cut into pieces to build
        other distances from: its second digit, the "m" at its end, and the
        whole line. Each is (image, the line's top in the picture)."""
        from PyQt6.QtGui import QImage

        from src.utils.sco_tag_reader import find_lines

        box = name_box(SERIAL)
        x, y, w, h = box
        area = picture({SERIAL: AT})
        piece = area.crop(AT[0], y + h, 243, 60)
        line = max(find_lines(piece, "r", 140, CAP_AT_2160, min_glyphs=1),
                   key=lambda found: len(found.glyphs))
        glyphs = sorted((g for g in line.glyphs if g.kind == "tall"), key=lambda g: g.box[0])
        assert len(glyphs) == 4                             # 1, 4, 6 and k of "14.6km"
        fixture = QImage(str(FIXTURES / SERIAL))
        top = y + h + line.top - AT[1]                      # in the fixture's own pixels
        digit = glyphs[1].box
        last = glyphs[-1].box
        start, end = line.box[0] - 2, last[0] + last[2] + 16        # with the "m" after the k
        return {
            "digit": fixture.copy(digit[0] - 1, top - 1, digit[2] + 2, 19),
            "m": fixture.copy(last[0] + last[2] + 1, top - 1, 16, 19),
            "line": fixture.copy(start, top - 1, end - start, 19),
            "top": y + h + line.top - 1, "left": AT[0] + start, "name": box,
        }

    def test_a_distance_off_to_one_side_counts_while_it_starts_with_a_digit(self, qapp):
        """The found box can miss some of a name's letters, which moves its
        middle. A line that starts with a digit may sit a little further
        from the middle than a line that is only placed like a distance."""
        scanner = TagScanner()
        cut = self.distance_glyphs()
        box = cut["name"]
        hidden = [under(box)]

        def shifted(by: int):
            return picture({SERIAL: AT}, blank=hidden,
                           pasted=[(cut["line"], cut["left"] + by, cut["top"])])

        references = scanner._references
        assert distance_under(shifted(0), box, CAP_AT_2160, references)       # where it was
        assert distance_under(shifted(-22), box, CAP_AT_2160, references)     # 1.3 capitals left
        assert not distance_under(shifted(-75), box, CAP_AT_2160, references)  # 4.4: another tag's

    def test_a_short_line_placed_like_a_distance_counts_whatever_it_reads(self, qapp):
        """At 1080p one pass can read every digit of a distance as a letter.
        So four letters standing just where a distance stands count, where
        the seven-letter word of the test above does not."""
        from PyQt6.QtGui import QImage

        box = name_box(UNKNOWN)
        x, y, w, h = box
        # The middle four letters of the name itself, as a stand-in.
        letters = QImage(str(FIXTURES / UNKNOWN)).copy(x - AT[0] + 16, y - AT[1] - 3, 62, h + 6)
        placed = picture({UNKNOWN: AT}, blank=[under(box)],
                         pasted=[(letters, x + w // 2 - 31, y + h + 16)])
        references = TagScanner()._references
        assert distance_under(placed, box, CAP_AT_2160, references)
        # The same four letters well to one side are another thing's text.
        aside = picture({UNKNOWN: AT}, blank=[under(box)],
                        pasted=[(letters, x + w // 2 + 40, y + h + 16)])
        assert not distance_under(aside, box, CAP_AT_2160, references)

    def test_one_digit_counts_only_with_its_unit_beside_it(self, qapp):
        """A marker a few metres off reads "4m": one digit. One digit alone
        does not count, since a lone upright bar reads as a 1."""
        cut = self.distance_glyphs()
        box = cut["name"]
        x, _y, w, _h = box
        middle = x + w // 2
        references = TagScanner()._references
        alone = picture({SERIAL: AT}, blank=[under(box)],
                        pasted=[(cut["digit"], middle - 6, cut["top"])])
        assert not distance_under(alone, box, CAP_AT_2160, references)
        with_unit = picture({SERIAL: AT}, blank=[under(box)],
                            pasted=[(cut["digit"], middle - 14, cut["top"]),
                                    (cut["m"], middle - 14 + cut["digit"].width() + 1, cut["top"])])
        assert distance_under(with_unit, box, CAP_AT_2160, references)

    def test_the_distance_is_looked_for_under_the_whole_name(self, qapp, monkeypatch):
        """One finding pass can see only some of a name's letters, and the
        distance stands under the middle of the whole name. So the check is
        asked about every column any pass's line reaches at the place."""
        from dataclasses import replace

        whole = name_box(UNKNOWN)
        real_find, real_check, asked = sco_tag_scan.find_lines, sco_tag_scan.distance_under, []

        def some_letters(frame, channel, threshold, cap_px, min_glyphs=3):
            if min_glyphs != 3:                       # the distance check's own passes
                return real_find(frame, channel, threshold, cap_px, min_glyphs)
            # The fixture's name is whole in the blue pass alone. Here two
            # passes each see four of its seven letters, the first four and
            # the last four, and the third sees nothing.
            parts = {("r", 190): slice(0, 4), ("r", 140): slice(-4, None)}
            if (channel, threshold) not in parts:
                return []
            names = [line for line in real_find(frame, "b", 190, cap_px) if len(line.glyphs) == 7]
            return [replace(line, glyphs=sorted(line.glyphs, key=lambda g: g.box[0])[
                parts[(channel, threshold)]]) for line in names]

        def spy(area, box, cap_px, references):
            asked.append(box)
            return real_check(area, box, cap_px, references)

        monkeypatch.setattr(sco_tag_scan, "find_lines", some_letters)
        monkeypatch.setattr(sco_tag_scan, "distance_under", spy)
        scanner = TagScanner()
        scanner.need_distance = True
        readings = scanner.scan(picture({UNKNOWN: AT}), 0.0)
        assert texts(readings) == ["UNKNOWN"]
        # The scanner looks at the middle of the picture, so its boxes start
        # from that part's corner.
        left, top = int(sco_tag_scan.AREA[0] * SIZE[0]), int(sco_tag_scan.AREA[1] * SIZE[1])
        (box,) = asked
        assert (box[0] + left, box[1] + top) == whole[:2] and box[2] == whole[2]
        # The line it read from is only the name's last four letters.
        assert readings[0].box[2] < 0.7 * whole[2]

    def test_the_picture_is_asked_on_a_schedule(self, two_tags, monkeypatch):
        """A check costs a few milliseconds, and most text on screen stays
        where it is, so a place is asked again only when its answer is old:
        after ``EARLY_GAP_S`` until the same answer has come
        ``SETTLED_READS`` times running, then every ``LATE_GAP_S``."""
        asked = []
        real = sco_tag_scan.distance_under

        def counting(area, box, cap_px, references):
            asked.append(box)
            return real(area, box, cap_px, references)

        monkeypatch.setattr(sco_tag_scan, "distance_under", counting)
        scanner = TagScanner()
        scanner.need_distance = True
        now = 0.0
        scanner.scan(two_tags, now)
        assert len(asked) == 2                              # each tag once
        scanner.scan(two_tags, now + 0.3)
        assert len(asked) == 2                              # the answers still stand
        for check in range(1, SETTLED_READS):
            now += EARLY_GAP_S + 0.1
            scanner.scan(two_tags, now)
            assert len(asked) == 2 * (check + 1)
        scanner.scan(two_tags, now + EARLY_GAP_S + 0.1)     # settled: not asked yet
        assert len(asked) == 2 * SETTLED_READS
        scanner.scan(two_tags, now + LATE_GAP_S + 0.1)
        assert len(asked) == 2 * SETTLED_READS + 2

    def test_a_changed_answer_is_asked_again_soon(self, qapp, monkeypatch):
        """Once the same answer has come ``SETTLED_READS`` times a place is
        asked only every ``LATE_GAP_S``. Another answer starts the count
        again: a tag that has just lost its distance, or got it back, is
        asked again after ``EARLY_GAP_S``."""
        asked = []
        real = sco_tag_scan.distance_under

        def counting(area, box, cap_px, references):
            asked.append(box)
            return real(area, box, cap_px, references)

        monkeypatch.setattr(sco_tag_scan, "distance_under", counting)
        box = name_box(SERIAL)
        covered, clear = picture({SERIAL: AT}, blank=[under(box)]), picture({SERIAL: AT})
        scanner = TagScanner()
        scanner.need_distance = True
        now = 0.0
        for _check in range(SETTLED_READS):
            assert texts(scanner.scan(clear, now)) == ["OA-3601-TW"]
            last, now = now, now + EARLY_GAP_S + 0.1
        assert len(asked) == SETTLED_READS                  # settled on "it has one"
        now = last + LATE_GAP_S + 0.1
        assert scanner.scan(covered, now) == [] and len(asked) == SETTLED_READS + 1
        again = scanner.scan(clear, now + EARLY_GAP_S + 0.1)
        assert len(asked) == SETTLED_READS + 2              # not five seconds later
        assert texts(again) == ["OA-3601-TW"]

    def test_a_tag_is_read_at_once_when_its_distance_shows(self, qapp):
        """Another tag can cover a distance for a moment. The tag is left
        out while it is covered and read the moment it shows again."""
        box = name_box(SERIAL)
        covered, clear = picture({SERIAL: AT}, blank=[under(box)]), picture({SERIAL: AT})
        scanner = TagScanner()
        scanner.need_distance = True
        assert scanner.scan(covered, 0.0) == []
        assert scanner.scan(clear, 0.3) == []               # the answer of 0.0 still stands
        again = scanner.scan(clear, EARLY_GAP_S + 0.1)
        assert [(r.text, r.fresh) for r in again] == [("OA-3601-TW", True)]

    def test_a_tag_that_loses_its_distance_is_no_longer_carried(self, qapp):
        box = name_box(SERIAL)
        covered, clear = picture({SERIAL: AT}, blank=[under(box)]), picture({SERIAL: AT})
        scanner = TagScanner()
        scanner.need_distance = True
        assert texts(scanner.scan(clear, 0.0)) == ["OA-3601-TW"]
        assert texts(scanner.scan(covered, 0.3)) == ["OA-3601-TW"]      # carried: not asked yet
        assert scanner.scan(covered, EARLY_GAP_S + 0.1) == []
        assert scanner.last_no_distance == 1

    def test_switching_it_off_reads_what_was_left_out(self, qapp):
        box = name_box(SERIAL)
        covered = picture({SERIAL: AT}, blank=[under(box)])
        scanner = TagScanner()
        scanner.need_distance = True
        assert scanner.scan(covered, 0.0) == []
        scanner.need_distance = False
        assert texts(scanner.scan(covered, 0.3)) == ["OA-3601-TW"]
        assert scanner.last_no_distance == 0


@pytest.mark.parametrize("text, number", [
    ("14.6", True), ("210", True), ("12 3k", True), ("7 2", True),
    ("OA-3601-TW", False), ("O0-36O1-TW", False), ("PILOT_ONE", False), ("R4C3R", False),
    ("", False),
])
def test_a_read_out_is_mostly_digits_and_a_serial_is_not(text, number):
    assert is_number(text) is number
