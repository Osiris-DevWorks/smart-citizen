"""The qualities each mined material can come at, for the SCO Order tab.

Ores and minerals no longer roll any quality from 0 to 1000: each has one
quality per tier (F to S, then Perfect). The Order tab's quality sliders
snap to those, so a slot can only be set to a quality the material really
comes at.

The table is the community's datamined one (Alpha 4.9), pasted as it was
given. To update it after a patch, paste the new rows over ``QUALITY_TABLE``:
one material per line, its name then one number per tier. A row with fewer
numbers than tiers is missing its lowest tiers (Carinite has no F tier), so
the numbers line up from Perfect down.
"""

from __future__ import annotations

import re
from typing import Iterable, Optional

QUALITY_TABLE_SOURCE = "Alpha 4.9"
TIER_NAMES = ("F", "E", "D", "C", "B", "A", "S", "Perfect")

QUALITY_TABLE = """
Agricium 346 588 667 796 852 943 971 1000
Aluminum 318 511 614 783 896 919 953 1000
Aslarite 287 575 602 741 854 927 963 1000
Beryl 324 547 677 717 860 937 955 1000
Bexalite 302 597 632 756 875 941 959 1000
Borase 359 584 676 743 892 903 976 1000
Copper 359 593 652 742 855 917 958 1000
Corundum 318 504 665 793 886 904 971 1000
Gold 359 553 644 786 864 916 959 1000
Hephaestanite 330 572 692 758 896 916 975 1000
Iron 325 521 664 710 874 907 970 1000
Laranite 298 510 698 707 858 910 975 1000
Lindinium 305 585 618 729 853 930 954 1000
Ouratite 310 523 647 779 860 912 960 1000
Pressurized Ice 322 561 659 714 873 922 966 1000
Quantainium 344 514 669 762 852 901 974 1000
Quartz 330 552 641 710 899 914 969 1000
Riccite 325 525 671 743 870 942 965 1000
Saldynium 301 575 674 757 861 938 955 1000
Savrilium 322 580 636 776 878 905 967 1000
Silicon 310 510 672 782 889 926 968 1000
Stileron 330 517 681 747 874 947 972 1000
Taranite 310 525 646 718 853 925 957 1000
Tin 340 537 664 704 880 940 964 1000
Titanium 295 516 622 784 866 916 959 1000
Torite 262 528 661 785 873 944 951 1000
Tungsten 363 530 662 787 858 902 964 1000
Aphorite 348 523 686 717 861 916 975 1000
Beradom 287 578 656 723 881 937 969 1000
Carinite 554 647 716 880 909 959 1000
Dolivine 304 577 621 743 886 901 957 1000
Feynmaline 371 561 682 769 880 906 965 1000
Glacosite 360 567 678 724 857 916 972 1000
Hadanite 274 526 665 762 867 916 959 1000
Janalite 269 596 623 732 898 929 964 1000
Sadaryx 258 510 688 797 865 940 971 1000
"""

# Other spellings of a table name (CIG's loc keys and the compendium differ
# from the table in places): normalized spelling -> normalized table name.
NAME_ALIASES = {
    "aluminium": "aluminum",
    "savrillium": "savrilium",
    "ice": "pressurizedice",
    "beradon": "beradom",
    "caranite": "carinite",
}

_ROW = re.compile(r"^\s*(\D+?)\s+((?:\d+\s*)+)$")


def _norm(name: str) -> str:
    return re.sub(r"[^a-z]", "", (name or "").casefold())


def parse_quality_table(text: str) -> dict[str, tuple[tuple[str, int], ...]]:
    """``{normalized name: ((tier, quality), ...)}`` from rows of the table,
    lowest tier first. A row with fewer numbers than tiers lines up from
    Perfect down. Rows that are not a name and numbers are skipped."""
    out: dict[str, tuple[tuple[str, int], ...]] = {}
    for line in text.splitlines():
        match = _ROW.match(line)
        if not match:
            continue
        values = [int(v) for v in match.group(2).split()][-len(TIER_NAMES) :]
        tiers = TIER_NAMES[len(TIER_NAMES) - len(values) :]
        out[_norm(match.group(1))] = tuple(zip(tiers, values))
    return out


QUALITY_TIERS = parse_quality_table(QUALITY_TABLE)


def quality_tiers(names: Iterable[str]) -> Optional[tuple[tuple[str, int], ...]]:
    """The tiers of the first of *names* the table knows (a material key
    such as ``pressurized_ice``, then its display names), or None."""
    for name in names:
        key = _norm(name)
        key = NAME_ALIASES.get(key, key)
        if key in QUALITY_TIERS:
            return QUALITY_TIERS[key]
    return None


def tier_of(tiers, quality: int) -> str:
    """The tier name a snapped *quality* sits at, or "" off the table."""
    return next((tier for tier, value in tiers or () if value == quality), "")
