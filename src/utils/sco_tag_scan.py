"""Finds the name tags in one picture of the game's window and reads them
(player ID test, Qt-free).

``TagScanner.scan(frame)`` is one look: it searches the middle of the picture
for lines of HUD capitals (``sco_tag_reader.find_lines``, a few cheap passes),
drops what is plainly not a tag (bars, prose, read-outs, the chat panel) and
gives each line left the reader's whole look (``read_place``). It returns a
``TagReading`` for every tag it could read.

Reading is the slow part, about 50 ms a tag in pure Python, so the scanner
remembers what it read where. A tag is read whole when it is first seen and
whenever the one cheap pass reads it differently. Otherwise it is carried
over to the next look without a new read, and read again ``EARLY_GAP_S``
after its last read until it has had ``SETTLED_READS`` of them, then every
``LATE_GAP_S``. The gap matters as much as the saving: two reads of one
still picture always agree, mistakes included, so reads that are to count as
two looks (``player_id.NameVotes``) have to be of two different pictures. A
carried reading is marked ``fresh=False``: it shows where the tag is now,
but it is not a new look at its letters.

With ``need_distance`` set, a line is only read when its distance stands
under it (``distance_under``): every marker the game draws has one, and menu
and cockpit text, which is most of what a look finds, has none. That check
costs a few milliseconds a line where a read costs fifty.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Optional

from src.utils import sco_tag_reader as reader
from src.utils.sco_tag_glyphs import GRID, REFERENCES
from src.utils.sco_tag_reader import (
    BAR_ASPECT, CAP_AT_2160, Frame, Reference, find_lines, read_line, read_place,
)

# Channel and brightness cut of each pass that finds where the tags are. Red
# finds white, yellow and red tags, blue the blue ones (a party member, a
# marker on foot). Reading a tag once found is read_place's job. A pass costs
# about 80 ms on a 4K picture, and finding is most of a look once the tags on
# screen have been read. These three found every tag that may be a name in
# the 43 whole frames kept from four play sessions (36 tags): red at 100 and
# blue at 140, which the sample saver also used, added none.
PASSES = (("r", 190), ("r", 140), ("b", 190))
# The part of the picture that is searched, as shares of it (left, top, right,
# bottom). The edges and the bottom hold the cockpit's own screens and the
# game's HUD, which are not name tags and cost the most to read.
AREA = (0.10, 0.10, 0.90, 0.80)
# The chat panel, as shares of the whole picture. Its text changes all the
# time and is not a tag.
CHAT_PANEL = (0.0, 0.36, 0.25, 0.66)
# A reading shaped like a ship's serial (O and 0 look alike to the reader).
SERIAL_SHAPED = re.compile(r"^[A-Z0]{2}-[0-9OD]{4}-[A-Z0]{2}$")
# A reading with at least this share of digits is a read-out (a distance, a
# speed, a heading), not a tag. A serial is exempt.
NUMBER_SHARE = 0.6
# A line with this many letters of another height beside it is prose.
PROSE_LETTERS = 2
# A tag is followed from look to look. Its place may move this many capital
# heights between looks, and it is forgotten after this many looks unseen.
PLACE_SWAY = 2.5
PLACE_FORGET_LOOKS = 6
# At most this many tags get the reader's whole look in one look at the
# picture, the ones the cheap pass matched fairly well first, then the ones
# nearest the middle.
MAX_READS = 10
LIKELY_FLOOR = 0.7
# A tag is read whole again this many seconds after its last read until it
# has been read SETTLED_READS times, and every LATE_GAP_S after that.
SETTLED_READS = 3
EARLY_GAP_S = 1.0
LATE_GAP_S = 5.0

# The distance line. Every marker the game draws (a player, a ship, UNKNOWN,
# a place) has its distance under its name ("6.2km", with "[1km/s]" after it
# when the contact moves). Cockpit screens, menu buttons and HUD read-outs
# have none, so a line with no distance under it is not a tag
# (``distance_under``, ``TagScanner.need_distance``). The limits come from
# the fourth play session's saved crops (1,509 different readings at 1080p
# and 4K): they find the distance under 49 of 50 names read right at 1080p
# and 12 of 12 at 4K, and under about one in four of the readings that are
# not names, which are the other markers.
#
# Every pass the reader has, over the small area under the line: the three
# finding passes alone see the distance under only 36 of those 50 names.
DISTANCE_PASSES = tuple((channel, threshold) for channel in reader.CHANNELS
                        for threshold in reader.THRESHOLDS)
# How far under and beside the line's box the distance is looked for, in
# capital heights.
DISTANCE_REACH = 3.4
# A line under it that starts with a digit: how far its top may be under the
# name's foot, and its middle left or right of the name's middle, in capital
# heights. The read-out's "m" is often not counted in its box, which moves
# its middle left.
DIGIT_GAP = (0.5, 1.7)
DIGIT_OFFSET = (-2.2, 1.6)
# A digit, or a letter one pass reads a small digit as.
DIGIT_LIKE = frozenset("0123456789ODQSBGZI")
# A distance holds one full stop and, with a speed after it, a dozen glyphs.
# A word under the name that a pass at the wrong brightness breaks into bars
# and specks reads as a run of 1s and marks, which is neither.
DIGIT_MARKS = 2
DIGIT_GLYPHS = 14
# At 1080p one pass can read every digit of a distance as a letter, so a
# short line sitting just where a distance sits counts whatever it reads:
# closer limits, 2 to 9 capital-height glyphs, no wider than "999.9km".
PLACED_GAP = (0.8, 1.45)
PLACED_OFFSET = (-1.2, 0.8)
PLACED_GLYPHS = (2, 9)
PLACED_WIDTH = 4.8


@dataclass(frozen=True)
class TagReading:
    """One tag in one look. *box* is the name's line in the picture's pixels
    (x, y, width, height). *crowded* counts what stands beside the line's
    ends: anything there means the name may run on under it. *fresh* is False
    for a reading carried over from an earlier look. *place* is the same
    number for one tag from look to look, as long as the scanner follows it."""
    text: str
    box: tuple
    score: float
    crowded: int
    fresh: bool = True
    place: int = 0


class _Place:
    """A tag followed from look to look."""

    def __init__(self, number: int, box, look: int):
        self.number = number
        self.box, self.last_look = box, look
        self.quick = None            # what the cheap pass read when it was last read whole
        self.text = ""
        self.score = 0.0
        self.crowded = 0
        self.reads = 0
        self.read_look = 0
        self.read_at = 0.0
        # Whether a distance line was under it when that was last looked for
        # (None before the first time), how many times running the answer
        # was the same, and when.
        self.distance: Optional[bool] = None
        self.checks = 0
        self.checked_at = 0.0

    def distance_known(self, now: float) -> bool:
        """Whether the last answer on its distance line still stands: for
        ``EARLY_GAP_S`` until the same answer has come ``SETTLED_READS``
        times running, and for ``LATE_GAP_S`` after that."""
        if self.distance is None:
            return False
        gap = EARLY_GAP_S if self.checks < SETTLED_READS else LATE_GAP_S
        return now - self.checked_at < gap

    def due(self, quick: str, now: float) -> bool:
        """Whether the tag wants the reader's whole look now."""
        if not self.reads or self.quick != quick:
            return True
        gap = EARLY_GAP_S if self.reads < SETTLED_READS else LATE_GAP_S
        return now - self.read_at >= gap

    def near(self, box, sway: float) -> bool:
        ax, ay, aw, ah = self.box
        bx, by, bw, bh = box
        if ax + aw + sway <= bx or bx + bw + sway <= ax:
            return False
        return min(ay + ah, by + bh) - max(ay, by) > -sway


def _group_by_place(lines) -> list[list]:
    groups: list[list] = []
    for line in sorted(lines, key=lambda found: -len(found.glyphs)):
        for group in groups:
            if reader._overlap(line, group[0]):
                group.append(line)
                break
        else:
            groups.append([line])
    return groups


def _tall_count(line) -> int:
    return line.pattern.count("T")


def _whole_box(group, line) -> tuple:
    """The box to look under for a tag's distance: the rows of *line*, the
    pass that read the place best, and every column that any pass's line at
    the place reaches. One pass can find only some of a name's letters, and
    the distance stands under the middle of the whole name."""
    x0 = min(found.box[0] for found in group)
    x1 = max(found.box[0] + found.box[2] for found in group)
    _x, y, _w, h = line.box
    return x0, y, x1 - x0, h


def _shaped_count(line) -> int:
    """How many of a line's glyphs have a shape to match, which a plain
    upright bar does not. Three thin uprights in a row (a fence, a row of
    lights) read as "111" with a perfect score, so a line needs more."""
    height = max(1, line.base - line.top)
    return sum(1 for g in line.glyphs if g.kind == "tall" and g.box[2] / height >= BAR_ASPECT)


def is_number(text: str) -> bool:
    """True for a read-out: mostly digits, and not shaped like a serial."""
    if SERIAL_SHAPED.match(text):
        return False
    marks = [c for c in text if c.isalnum()]
    return bool(marks) and sum(c.isdigit() for c in marks) >= NUMBER_SHARE * len(marks)


def distance_under(area: Frame, box, cap_px: float, references) -> bool:
    """Whether the line at *box* (x, y, width, height in *area*) has a
    distance line under it, as every marker in the game has and other text
    has not. A line under it counts when it starts with a digit and sits
    roughly under the name's middle, or when it is a short line just where a
    distance sits, whatever one pass makes of its small digits. A single
    digit counts only with a lower-case letter beside it ("7m"), since a
    lone upright bar reads as a 1."""
    x, y, w, h = box
    reach = round(DISTANCE_REACH * cap_px)
    x0, x1 = max(0, x - reach), min(area.width, x + w + reach)
    y0, y1 = min(area.height, y + h), min(area.height, y + h + reach)
    if x1 <= x0 or y1 - y0 < cap_px:
        return False
    piece = area.crop(x0, y0, x1 - x0, y1 - y0)
    middle = x + w / 2 - x0
    for channel, threshold in DISTANCE_PASSES:
        for under in find_lines(piece, channel, threshold, cap_px, min_glyphs=1):
            ux, uy, uw, _uh = under.box
            # The piece starts at the name's foot, so a line's top is its gap.
            gap, off = uy / cap_px, (ux + uw / 2 - middle) / cap_px
            tall = _tall_count(under)
            if (PLACED_GAP[0] <= gap <= PLACED_GAP[1]
                    and PLACED_OFFSET[0] <= off <= PLACED_OFFSET[1]
                    and PLACED_GLYPHS[0] <= tall <= PLACED_GLYPHS[1]
                    and uw <= PLACED_WIDTH * cap_px):
                return True
            if not (DIGIT_GAP[0] <= gap <= DIGIT_GAP[1]
                    and DIGIT_OFFSET[0] <= off <= DIGIT_OFFSET[1]):
                continue
            if tall > DIGIT_GLYPHS or (tall < 2 and not under.lowercase):
                continue
            if len(under.glyphs) - tall > DIGIT_MARKS:
                continue
            read_line(piece, under, references)
            text = under.text.replace(" ", "")
            if text and text[0] in DIGIT_LIKE and (any(c.isdigit() for c in text) or "k" in text):
                return True
    return False


class TagScanner:
    """Looks at pictures of the game's window, one after the other, and keeps
    track of the tags it has read. Not thread-safe: one look at a time."""

    def __init__(self):
        if tuple(GRID) != (reader.GRID_W, reader.GRID_H):
            raise ValueError("the reference glyphs were built for another grid")
        self._references = [Reference(char, tuple(feat), aspect, "")
                            for char, aspect, feat in REFERENCES]
        self._places: list[_Place] = []
        self._next_place = 1
        self._look = 0
        # The Overlay tab's switch: leave out, before it is read, a line
        # that has no distance line under it (``distance_under``).
        self.need_distance = False
        # What the last look cost and saw, for the log and the Overlay tab:
        # seconds finding, seconds in all, lines of capitals found in the
        # searched part before anything is dropped, lines left out for
        # having no distance under them, tags read whole, tags carried over.
        self.last_found_s = self.last_total_s = 0.0
        self.last_lines = 0
        self.last_no_distance = 0
        self.last_reads = self.last_carried = 0

    def reset(self) -> None:
        """Forget every tag (the game's window changed size or went away)."""
        self._places = []

    def scan(self, frame: Frame, now: Optional[float] = None) -> list[TagReading]:
        """One look at *frame*, the game's whole picture. *now* is a clock
        in seconds (``time.monotonic`` when left out)."""
        started = time.perf_counter()
        if now is None:
            now = time.monotonic()
        self._look += 1
        cap_px = CAP_AT_2160 * frame.height / 2160
        left, top = int(AREA[0] * frame.width), int(AREA[1] * frame.height)
        right, bottom = int(AREA[2] * frame.width), int(AREA[3] * frame.height)
        area = frame.crop(left, top, right - left, bottom - top)
        lines = []
        for channel, threshold in PASSES:
            lines.extend(find_lines(area, channel, threshold, cap_px))
        self.last_found_s = time.perf_counter() - started
        groups = _group_by_place(lines)
        self.last_lines = len(groups)
        wanted = []
        for group in groups:
            # The pass that saw the most capital-height glyphs, and of those
            # the one with the fewest stray marks.
            line = max(group, key=lambda found: (_tall_count(found), -len(found.glyphs),
                                                 -abs(found.threshold - 140)))
            x, y, w, h = line.box
            cx, cy = (left + x + w / 2) / frame.width, (top + y + h / 2) / frame.height
            if CHAT_PANEL[0] <= cx <= CHAT_PANEL[2] and CHAT_PANEL[1] <= cy <= CHAT_PANEL[3]:
                continue
            if _shaped_count(line) < 2 or line.lowercase >= PROSE_LETTERS:
                continue
            read_line(area, line, self._references)      # one pass, to sort out the read-outs
            if is_number(line.text):
                continue
            off = abs(x + w / 2 - area.width / 2) + abs(y + h / 2 - area.height / 2)
            wanted.append((line.score < LIKELY_FLOOR, off, line, _whole_box(group, line)))
        wanted.sort(key=lambda item: item[:2])
        readings = []
        reads = carried = no_distance = 0
        sway = PLACE_SWAY * cap_px
        for _poor, _off, line, whole in wanted:
            place = self._place_for(line.box, sway)
            if self.need_distance and not self._has_distance(area, whole, place, cap_px, now):
                no_distance += 1
                continue                 # no distance under it: not a tag, so not read
            if place.due(line.text, now) and reads < MAX_READS:
                reads += 1
                self._read(area, line, place, cap_px, now)
            elif not place.reads:
                continue                 # a crowd: not read yet, nothing to carry
            if not place.text:
                continue                 # the reader found no line at the place
            fresh = place.read_look == self._look
            carried += not fresh
            x, y, w, h = line.box
            readings.append(TagReading(place.text, (left + x, top + y, w, h), place.score,
                                       place.crowded, fresh, place.number))
        self._places = [p for p in self._places if self._look - p.last_look <= PLACE_FORGET_LOOKS]
        self.last_reads, self.last_carried, self.last_no_distance = reads, carried, no_distance
        self.last_total_s = time.perf_counter() - started
        return readings

    def _has_distance(self, area: Frame, box, place: _Place, cap_px: float, now: float) -> bool:
        """Whether the tag at *place*, whose name is at *box*, has its
        distance under it. The picture
        is asked when the place is new and then on a place's own schedule
        (``_Place.distance_known``), so text that stays put costs a check
        every few seconds, not every look. While a place has no distance
        under it nothing is read there and nothing is carried from it. What
        was read there before is kept, so a tag whose distance another tag
        covered for a moment shows again without a new read."""
        if place.distance_known(now):
            return bool(place.distance)
        found = distance_under(area, box, cap_px, self._references)
        place.checks = place.checks + 1 if found == place.distance else 1
        place.distance, place.checked_at = found, now
        return found

    def _place_for(self, box, sway: float) -> _Place:
        """The place *box* was at in an earlier look, or a new one. A place
        takes one line a look, the nearest, so two tags stacked close
        together stay two places."""
        x, y, w, h = box
        best = None
        for place in self._places:
            if place.last_look == self._look or not place.near(box, sway):
                continue
            px, py, pw, ph = place.box
            distance = abs(px + pw / 2 - x - w / 2) + abs(py + ph / 2 - y - h / 2)
            if best is None or distance < best[0]:
                best = (distance, place)
        if best is not None:
            place = best[1]
            place.box, place.last_look = box, self._look
            return place
        place = _Place(self._next_place, box, self._look)
        self._next_place += 1
        self._places.append(place)
        return place

    def _read(self, area: Frame, line, place: _Place, cap_px: float, now: float) -> None:
        """The reader's whole look at one tag: a small picture round its
        line, with room for the marker above and the distance below."""
        x, y, w, h = line.box
        pad_x, pad_top, pad_bottom = round(3 * cap_px), round(2.5 * cap_px), round(3.2 * cap_px)
        x0, y0 = max(0, x - pad_x), max(0, y - pad_top)
        x1, y1 = min(area.width, x + w + pad_x), min(area.height, y + h + pad_bottom)
        piece = area.crop(x0, y0, x1 - x0, y1 - y0)
        point = (round(x + w / 2 - x0), round(y + h / 2 - y0))
        text, best, crowded, _passes = read_place(piece, point, cap_px, self._references)
        place.quick, place.text = line.text, text
        place.score = best.score if best is not None else 0.0
        place.crowded = crowded
        place.reads += 1
        place.read_look = self._look
        place.read_at = now
