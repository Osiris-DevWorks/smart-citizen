"""Player ID test: which name tag readings to trust and how to mark them
(Qt-free, settings-free).

Everything here works on text. ``sco_tag_scan.TagScanner`` reads the tags of
one look, and ``PlayerIdTracker.look`` turns those readings into ``Mark``s:
the names to draw something round, each with a colour.

Nothing is looked up anywhere. A name gets its colour from the player's own
lists (``PlayerLists``, kept on the Overlay tab and saved with the settings),
and a name on no list gets the lists' "unlisted" colour.

**Which readings count as a name.** One look of the reader gets about three
names in four right at 1080p, and most words on screen are not names at all
(cockpit labels, menu buttons, place names). So a reading is only taken for a
name when it passes ``could_be_name``:

- one word of the characters a handle may hold, not shaped like a ship's
  serial, and with nothing standing beside it (a tag half behind something
  reads as a piece of itself)
- not digits only, and nothing like the game's ``UNKNOWN``
- matched well (``MATCH_FLOOR``)
- not one of the game's own words (``game_words``, read from the English
  ``base.ini``, the game's own text, which holds every label, button, place
  and thing the game can draw)

and it is only trusted once it has been read in two looks (``NameVotes``).
Spellings that differ only in look-alike letters (O 0 D Q, B 8, S 5) count as
one name, and the spelling read most often wins. Measured on a log of every
look of two play sessions: in half an hour at 1080p this let 54 words through
as names, 44 of them real, where 999 passed without it.

**A name on the player's lists is trusted at once**, also when it differs
from the listed spelling only in look-alike letters: the list says the name
exists, which a single reading cannot.

**The test switch** (``PlayerIdTracker.mark_all``) marks every tag that is
read, at once, with the text that was read above it: a possible name in
``UNTRUSTED_COLOR`` until it is trusted, and anything that cannot be a name
(the game's UNKNOWN, a ship's serial, two words) in ``NOT_A_NAME_COLOR``. It
is there to see whether the reading works at all on a setup, not for play.

**Locations.** The player can also list locations to highlight
(``PlaceList``: the text a marker shows, such as NEW BABBAGE, and a colour).
A reading that is one of them gets a mark of its own kind (``Mark.place``),
at once, whether or not names are being marked. A location's text may be
several words, so it is matched with the spaces left out.

**Past players.** The names read are kept from session to session
(``PastPlayers``, fed by ``PlayerIdTracker.take_new_names``), so the lists
editor can offer the last session's names and everyone read before. They
stay on this PC and are never part of a settings backup.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable, Optional

from src.utils.sco_tag_reader import ALIKE, skeleton
from src.utils.sco_tag_scan import TagReading

# One word of the characters a handle may hold, three or more long.
HANDLE = re.compile(r"^[A-Z0-9_-]{3,}$")
SERIAL = re.compile(r"^[A-Z]{2}-[0-9]{4}-[A-Z]{2}$")
# The game's own label for a contact nobody has identified.
UNKNOWN = "UNKNOWN"
# The lowest match a reading may have to count as a name. Cockpit text read
# through the glass matches worse than a tag does. At 1080p 0.85 already
# loses names and 0.9 nearly all of them.
MATCH_FLOOR = 0.8
# A reading that is on the player's lists may match a little worse.
LISTED_FLOOR = 0.7
# Looks a spelling must be read in before it is trusted, and how far apart
# two of them must be to count as two. A still picture reads the same every
# time, mistakes included, so two looks only agree on something when the
# picture has had time to change (a tag moves, its background changes).
TRUST_LOOKS = 2
VOTE_GAP_S = 0.9
# A mark stays this long after its name was last read, so one missed look
# does not blink it off.
HOLD_S = 1.5
# The votes are dropped once this many different readings have been seen (a
# very long session), so the checks on them stay quick.
MAX_SEEN = 20000

# Folded wider than the reader's own look-alikes, for the game's words: a
# button's ONLINE read as ONL1NE, or the cockpit's V S I read as VS1, is still
# the game's word.
_WORD_FOLD = {**ALIKE, "1": "I", "L": "I", "2": "Z", "6": "G"}
_WORD = re.compile(r"[A-Z0-9][A-Z0-9_\-]{2,}")
# Mark-up the game's text carries: ~mission(...) values, <tags>, \n, %s, [x].
_MARKUP = re.compile(r"~\w+\([^)]*\)|<[^>]*>|\\n|%\w+|\[[^\]]*\]")


def could_be_handle(text: str) -> bool:
    """True for a reading shaped like a player's handle: one word of the
    characters a handle may hold, neither a serial nor the game's UNKNOWN."""
    return bool(HANDLE.match(text)) and not SERIAL.match(text) and text != UNKNOWN


def _distance(a: str, b: str, limit: int) -> int:
    """Edit distance, given up on once it is over *limit*."""
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    row = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        new = [i]
        for j, cb in enumerate(b, 1):
            new.append(min(row[j] + 1, new[j - 1] + 1, row[j - 1] + (ca != cb)))
        row = new
        if min(row) > limit:
            return limit + 1
    return row[-1]


def near_unknown(text: str) -> bool:
    """The game's UNKNOWN, a misreading of it (one letter off) or a piece of
    it (three letters or more, one letter off in a longer piece)."""
    key = skeleton(text)
    if abs(len(key) - len(UNKNOWN)) <= 1 and _distance(key, UNKNOWN, 1) <= 1:
        return True
    if not 3 <= len(key) <= len(UNKNOWN):
        return False
    if key in UNKNOWN:
        return True
    if len(key) < 6:
        return False
    return any(_distance(key, UNKNOWN[start:start + size], 1) <= 1
               for size in (len(key) - 1, len(key), len(key) + 1) if size >= 4
               for start in range(0, len(UNKNOWN) - size + 1))


def folded(text: str) -> str:
    """*text* with look-alike characters made one, for the game's words."""
    return "".join(_WORD_FOLD.get(c, c) for c in text)


def game_words(ini_text: str) -> frozenset:
    """Every word of three characters or more in the game's text (the text
    of the English ``base.ini``), in capitals and folded, plus short labels
    run together ("Key Bindings" is drawn KEYBINDINGS on one button)."""
    words = set()
    for line in ini_text.splitlines():
        _key, sep, value = line.partition("=")
        if not sep:
            continue
        value = _MARKUP.sub(" ", value).upper()
        found = _WORD.findall(value)
        for word in found:
            words.add(folded(word.strip("-_")))
            for piece in re.split(r"[-_]", word):
                if len(piece) >= 3:
                    words.add(folded(piece))
        if 2 <= len(found) <= 3 and len(value) <= 40:
            words.add(folded("".join(found)))
    words.discard("")
    return frozenset(words)


def read_game_words(path: Path) -> frozenset:
    """``game_words`` of the English ``base.ini`` at *path*. Raises OSError
    when it cannot be read."""
    return game_words(Path(path).read_bytes().decode("utf-8-sig", errors="replace"))


def could_be_name(text: str, score: float, crowded: int, words: frozenset = frozenset()) -> bool:
    """True for a reading that may be a player's name (see the module's
    text). *words* is ``game_words`` of the game's text."""
    return (could_be_handle(text) and not crowded and score >= MATCH_FLOOR
            and not text.isdigit() and not near_unknown(text) and folded(text) not in words)


class NameVotes:
    """Counts, look by look, the readings that may be names, and says which
    spelling to trust."""

    def __init__(self):
        self._votes: dict[str, Counter] = defaultdict(Counter)
        self._voted_at: dict[str, float] = {}

    def reset(self) -> None:
        self._votes.clear()
        self._voted_at.clear()

    def add_look(self, texts: Iterable[str], now: float) -> None:
        """The readings of one look that may be names, at *now* seconds.
        Each different one counts once, however many tags read it, and not
        again within ``VOTE_GAP_S``."""
        if len(self._voted_at) > MAX_SEEN:
            self.reset()
        for text in set(texts):
            last = self._voted_at.get(text)
            if last is not None and now - last < VOTE_GAP_S:
                continue
            self._voted_at[text] = now
            self._votes[skeleton(text)][text] += 1

    def spelling(self, text: str) -> Optional[str]:
        """The spelling to trust for a reading, or None while there is none:
        the spelling of its look-alikes that was read most often, once that
        one has been read in ``TRUST_LOOKS`` looks and leads the next. A
        reading that is a piece of a longer one seen so far is never trusted
        (a name half behind something, or still being drawn)."""
        key = skeleton(text)
        ranked = self._votes.get(key)
        if not ranked:
            return None
        (top, count), *rest = ranked.most_common(2)
        if count < TRUST_LOOKS or (rest and count <= rest[0][1]):
            return None
        if any(len(other) > len(key) and key in other for other in self._votes):
            return None
        return top


# Colour names the lists take, besides #RRGGBB.
COLOR_NAMES = {
    "red": "#FA5252", "green": "#40C057", "blue": "#4DABF7", "yellow": "#FCC419",
    "orange": "#FF922B", "purple": "#B197FC", "pink": "#F783AC", "cyan": "#3BC9DB",
    "white": "#F8F9FA", "grey": "#ADB5BD", "gray": "#ADB5BD",
}
_HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")
UNLISTED_DEFAULT = COLOR_NAMES["grey"]
# The test switch's colour for a reading that may be a name and is not
# trusted yet: read once, or with something beside it. A trusted one takes
# the unlisted colour.
UNTRUSTED_COLOR = COLOR_NAMES["yellow"]
# The test switch's colour for a tag that cannot be a name: the game's
# UNKNOWN, a ship's serial, two words.
NOT_A_NAME_COLOR = COLOR_NAMES["cyan"]
# Names read in play that are kept from session to session for the lists
# editor (``PastPlayers``). The oldest go first.
MAX_PAST_NAMES = 2000
# What a location to highlight may be: 3 to 40 characters a marker can show,
# in capitals, starting and ending with a letter or a digit.
PLACE = re.compile(r"^[A-Z0-9][A-Z0-9 _\-.']{1,38}[A-Z0-9]$")
# A reading one character off a listed location still counts when the
# location's text is at least this long, spaces left out.
PLACE_SLIP_LENGTH = 6


def parse_color(text: str) -> Optional[str]:
    """A colour name or ``#RRGGBB`` as ``#RRGGBB``, or None."""
    text = str(text).strip()
    if _HEX_COLOR.match(text):
        return text.upper()
    return COLOR_NAMES.get(text.lower())


def clean_name(text: str) -> str:
    """A name as its tag shows it: capitals, nothing round it."""
    return str(text).strip().upper()


@dataclass(frozen=True)
class Listed:
    """A player on the lists: the name in capitals, their colour, and the
    org they are listed under ("" for a colour of their own)."""
    name: str
    color: str
    label: str


class PlayerLists:
    """The player's own lists: orgs with a colour, players with an org or a
    colour of their own, and the colour of names on no list. They are kept
    on the Overlay tab and saved with the settings
    (``AppSettings.get_/set_player_lists``) in this shape::

        {"orgs": [[name, colour], ...],
         "players": [[name, org or "", colour], ...],
         "unlisted": colour}

    A player's colour only counts when they have no org."""

    def __init__(self, players: Optional[dict] = None, unlisted: str = UNLISTED_DEFAULT,
                 problems: tuple = ()):
        self.players: dict[str, Listed] = dict(players or {})
        self.unlisted = unlisted
        # Entries that could not be used, for the log.
        self.problems = tuple(problems)
        by_look = defaultdict(list)
        for name in self.players:
            by_look[skeleton(name)].append(name)
        # Two listed names that differ only in look-alike letters cannot be
        # told apart by a look-alike match, so those need the exact spelling.
        self._by_look = {key: names[0] for key, names in by_look.items() if len(names) == 1}

    @classmethod
    def from_data(cls, data) -> "PlayerLists":
        """The lists from what the settings hold. An entry that cannot be
        used is left out and named in ``problems``, so a damaged value never
        stops the overlay."""
        data = data if isinstance(data, dict) else {}
        problems = []
        orgs: dict[str, tuple[str, str]] = {}
        for entry in _rows(data.get("orgs"), 2, "org", problems):
            # An org's name is in capitals too, as the editor shows it, so
            # the label over a mark reads like the tag under it.
            name, color = clean_name(entry[0]), parse_color(entry[1])
            if name and color:
                orgs[name] = (name, color)
            else:
                problems.append(f"org {name!r}: no name or no color")
        players = {}
        for entry in _rows(data.get("players"), 3, "player", problems):
            name, org = clean_name(entry[0]), clean_name(entry[1])
            if not HANDLE.match(name):
                problems.append(f"player {name!r}: cannot be a name tag")
                continue
            found = orgs.get(org) if org else None
            color = found[1] if found else parse_color(entry[2])
            if org and not found:
                problems.append(f"player {name!r}: org {org!r} is not on the list")
            if color:
                players[name] = Listed(name, color, found[0] if found else "")
            elif not org:
                problems.append(f"player {name!r}: no org and no color")
        unlisted = parse_color(data.get("unlisted", "")) or UNLISTED_DEFAULT
        return cls(players, unlisted, tuple(problems))

    def find(self, reading: str) -> Optional[Listed]:
        """The listed player a reading is: by its exact spelling, or by its
        look-alike letters when only one listed name fits."""
        listed = self.players.get(reading)
        if listed is None:
            listed = self.players.get(self._by_look.get(skeleton(reading), ""))
        return listed


class PastPlayers:
    """The names read in play, kept from one session to the next for the
    lists editor: every name with the session it was last read in, and which
    session was the last to read any. A session is one run of the app, named
    by the time its overlay first started, as text that sorts by time
    ("2026-11-15 14:02:10"). Nothing here is looked up or sent anywhere: it
    is what the overlay read off the screen, kept on this PC
    (``AppSettings.get_/set_player_history``) in this shape, newest first::

        {"session": when the last session began,
         "names": [[name, the session it was last read in], ...]}
    """

    def __init__(self):
        self.session = ""
        self._names: dict[str, str] = {}             # oldest first

    @classmethod
    def from_data(cls, data) -> "PastPlayers":
        """The record from what the settings hold. Anything that cannot be
        used is left out, so a damaged value only loses names."""
        made = cls()
        data = data if isinstance(data, dict) else {}
        rows = data.get("names")
        for entry in reversed(rows if isinstance(rows, list) else []):
            if isinstance(entry, (list, tuple)) and len(entry) == 2:
                name, session = clean_name(entry[0]), str(entry[1]).strip()
                if HANDLE.match(name):
                    made._names.pop(name, None)      # a name twice: its newest entry counts
                    made._names[name] = session
        session = data.get("session")
        made.session = session.strip() if isinstance(session, str) else ""
        return made

    def to_data(self) -> dict:
        return {"session": self.session,
                "names": [[name, session] for name, session in self.everyone()]}

    def saw(self, name: str, session: str) -> bool:
        """Note that *name* was read in *session*. True when that is news:
        the name is new, or was last read in an earlier session."""
        if self._names.get(name) == session and self.session == session:
            return False
        self._names.pop(name, None)
        self._names[name] = session
        self.session = session
        while len(self._names) > MAX_PAST_NAMES:
            del self._names[next(iter(self._names))]
        return True

    def last_session(self) -> list[str]:
        """The names read in the last session that read any, newest first."""
        return [name for name, session in self.everyone() if session == self.session]

    def everyone(self) -> list[tuple[str, str]]:
        """(name, the session it was last read in) of every name, newest first."""
        return list(reversed(self._names.items()))


def clean_place(text) -> str:
    """A location as its marker shows it: capitals, one space between words."""
    return " ".join(str(text).upper().split())


def _place_key(text: str) -> str:
    """A location's text for matching: no spaces (the reader can miss or add
    a gap between words), look-alike characters made one."""
    return folded(text.replace(" ", ""))


class PlaceList:
    """The player's own list of locations to highlight: the text a marker
    shows ("NEW BABBAGE") and a colour for it. Kept on the Overlay tab and
    saved with the settings (``AppSettings.get_/set_location_list``) as
    ``[[text, colour], ...]``."""

    def __init__(self, places: Optional[dict] = None, problems: tuple = ()):
        self.places: dict[str, str] = dict(places or {})     # text -> colour
        # Entries that could not be used, for the log.
        self.problems = tuple(problems)
        by_key = defaultdict(list)
        for text in self.places:
            by_key[_place_key(text)].append(text)
        # Two listed texts that differ only in spaces or look-alike letters
        # cannot be told apart by such a match, so those need the exact text.
        self._by_key = {key: texts[0] for key, texts in by_key.items() if len(texts) == 1}

    @classmethod
    def from_data(cls, data) -> "PlaceList":
        """The list from what the settings hold. An entry that cannot be
        used is left out and named in ``problems``."""
        problems, places = [], {}
        for entry in _rows(data, 2, "location", problems):
            text, color = clean_place(entry[0]), parse_color(entry[1])
            if not PLACE.match(text):
                problems.append(f"location {text!r}: cannot be read off a marker")
            elif not color:
                problems.append(f"location {text!r}: no color")
            else:
                places.setdefault(text, color)
        return cls(places, tuple(problems))

    def find(self, reading: str) -> Optional[tuple[str, str]]:
        """(text, colour) of the listed location a reading is: by its exact
        text, by its look-alike letters with the spaces left out, or, for a
        text of ``PLACE_SLIP_LENGTH`` characters or more, one character off
        when only one listed location is that close."""
        text = clean_place(reading)
        if text in self.places:
            return text, self.places[text]
        key = _place_key(text)
        found = self._by_key.get(key)
        if found is None and key:
            near = [listed for listed_key, listed in self._by_key.items()
                    if len(listed_key) >= PLACE_SLIP_LENGTH and _distance(key, listed_key, 1) <= 1]
            found = near[0] if len(near) == 1 else None
        return (found, self.places[found]) if found is not None else None


def _rows(value, width: int, what: str, problems: list) -> list:
    """The entries of a stored list that have *width* fields."""
    rows = []
    for entry in value if isinstance(value, list) else []:
        if isinstance(entry, (list, tuple)) and len(entry) == width:
            rows.append(entry)
        else:
            problems.append(f"{what} entry {entry!r}: not {width} fields")
    return rows


@dataclass(frozen=True)
class Mark:
    """A name to draw something round: *box* is its line in the picture's
    pixels (x, y, width, height). *label* is drawn above it: the org a listed
    player is under, or with the test switch on, the text that was read.
    *trusted* is False only for the test switch's marks of a reading that is
    not a trusted name: one not trusted yet, or a tag that is no name.
    *place* is True for a location on the player's list, whose *name* is the
    listed text."""
    name: str
    box: tuple
    color: str
    label: str
    listed: bool
    trusted: bool = True
    place: bool = False


def _same_tag(text: str, name: str) -> bool:
    """Whether a reading is the tag that was read as *name* before, read a
    little differently: a letter or two off."""
    limit = 1 if len(name) <= 5 else 2
    return _distance(skeleton(text), skeleton(name), limit) <= limit


class PlayerIdTracker:
    """Turns the readings of each look into the marks to show. Used from one
    thread."""

    def __init__(self):
        self.votes = NameVotes()
        self.lists = PlayerLists()
        self.places = PlaceList()
        self.words: frozenset = frozenset()
        # The Overlay tab's two main switches: mark players' names, and
        # highlight the locations on the player's list.
        self.mark_names = True
        self.mark_places = False
        # Names on no list get the lists' unlisted colour once trusted.
        self.mark_unlisted = True
        # The test switch: every tag read is marked at once, with the text
        # that was read above it.
        self.mark_all = False
        self._marks: dict[int, tuple[Mark, float]] = {}      # by the tag's place
        # The names read so far, and the ones nobody has been told of yet.
        self._noted: set[str] = set()
        self._new_names: list[str] = []

    def reset(self) -> None:
        """Forget the marks on show (the game went to the back). The votes
        stay: a name read twice before is still that name."""
        self._marks = {}

    def look(self, readings: Iterable[TagReading], now: float) -> list[Mark]:
        """The marks after one look. *now* is a clock in seconds."""
        readings = list(readings)
        self.votes.add_look((r.text for r in readings
                             if r.fresh and could_be_name(r.text, r.score, r.crowded, self.words)),
                            now)
        for reading in readings:
            mark = self._mark_for(reading, now)
            if mark is None or not mark.trusted:
                # The tag at this place was a name a moment ago. A reading a
                # letter or two off is that tag misread, not another tag, so
                # its mark stays on it.
                kept = self._marks.get(reading.place)
                if kept is not None and kept[0].trusted and _same_tag(reading.text, kept[0].name):
                    mark = replace(kept[0], box=reading.box)
            if mark is not None:
                self._marks[reading.place] = (mark, now)
            else:
                self._marks.pop(reading.place, None)
        self._marks = {place: (mark, seen) for place, (mark, seen) in self._marks.items()
                       if now - seen <= HOLD_S}
        return [mark for mark, _seen in self._marks.values()]

    def take_new_names(self) -> list[str]:
        """The names read since the last call that had not been read before:
        listed players, and names on no list once they are trusted. Each name
        is given once, for the record of past players (``PastPlayers``)."""
        names, self._new_names = self._new_names, []
        return names

    def _note(self, name: str) -> None:
        if name not in self._noted:
            if len(self._noted) > MAX_SEEN:
                self._noted.clear()
            self._noted.add(name)
            self._new_names.append(name)

    def _mark_for(self, reading: TagReading, now: float) -> Optional[Mark]:
        text = reading.text
        if self.mark_places and text and reading.score >= LISTED_FLOOR:
            place = self.places.find(text)
            if place is not None:
                return Mark(place[0], reading.box, place[1], "", True, place=True)
        if not self.mark_names:
            return None
        if could_be_handle(text) and reading.score >= LISTED_FLOOR:
            listed = self.lists.find(text)
            if listed is not None:
                self._note(listed.name)
                label = listed.label or (listed.name if self.mark_all else "")
                return Mark(listed.name, reading.box, listed.color, label, True)
        if could_be_name(text, reading.score, reading.crowded, self.words):
            name = self.votes.spelling(text)
            if name is not None:
                self._note(name)
                if self.mark_unlisted or self.mark_all:
                    return Mark(name, reading.box, self.lists.unlisted,
                                name if self.mark_all else "", False)
                return None
        if self.mark_all and text:
            color = UNTRUSTED_COLOR if could_be_handle(text) else NOT_A_NAME_COLOR
            return Mark(text, reading.box, color, text, False, trusted=False)
        return None
