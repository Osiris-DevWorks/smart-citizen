"""installer.iss keeps plain message boxes off the silent auto-update path (#436).

The in-app updater (#211) runs the installer with
``/SILENT /SUPPRESSMSGBOXES /AUTOUPDATE=1``. ``/SUPPRESSMSGBOXES`` only answers
``SuppressibleMsgBox``, so a plain ``MsgBox`` on that path waits for a click
nobody gives and the update stops. #420 converted the ones it found, but
nothing stopped the next one from coming back, and CI never runs Setup.

This reads the ``[Code]`` section of installer.iss as text and fails on a plain
``MsgBox`` in any routine that is not on a short list, each with the reason a
person is always present when it runs. A new plain box has to become a
``SuppressibleMsgBox`` with the answer a silent run should take, or earn a line
on that list.
"""

import re
from pathlib import Path

INSTALLER = Path(__file__).resolve().parent.parent / "installer.iss"

# Routines allowed to call a plain MsgBox: how many calls, and why none of them
# can stop a silent run. A second call in the same routine is a new decision, so
# it fails too.
_PERSON_PRESENT = {
    "CurStepChanged": (
        1,
        "the missing-unins000.exe notice: it reports a failure that has already "
        "happened and has only an OK button, so it is deliberately not suppressible",
    ),
    "NextButtonClick": (1, "returns early on a silent run (WizardSilent) before it asks anything"),
    "DeleteAllCheckBoxOnClick": (1, "a click on the uninstall dialog's delete-all box"),
    "DeleteAllUserSettings": (
        1,
        "the report after the opt-in delete-all, which only runs once that box is ticked "
        "(listed ahead of #419, which adds it)",
    ),
}

_ROUTINE = re.compile(r"^(?:function|procedure) (\w+)", re.M)
_PLAIN_MSGBOX = re.compile(r"(?<![A-Za-z])MsgBox\(")


def _code_section():
    """The ``[Code]`` section with comments and string literals blanked out
    (newlines kept, so line numbers still match), leaving only the code."""
    source = INSTALLER.read_text(encoding="utf-8-sig")
    start = source.index("\n[Code]")
    code = source[start:]
    out, i, n = [], 0, len(code)
    while i < n:
        ch = code[i]
        if ch == "'":  # a string literal; '' is an escaped quote
            j = i + 1
            while j < n:
                if code[j] == "'":
                    if code[j + 1 : j + 2] == "'":
                        j += 2
                        continue
                    break
                j += 1
            out.append(" " * (j + 1 - i))  # blanked too: only calls matter here
            i = j + 1
            continue
        if ch == "{":
            end = code.index("}", i) + 1
        elif code.startswith("(*", i):
            end = code.index("*)", i) + 2
        elif code.startswith("//", i):
            end = code.find("\n", i)
            end = n if end == -1 else end
        else:
            out.append(ch)
            i += 1
            continue
        out.append(re.sub(r"[^\n]", " ", code[i:end]))
        i = end
    # Everything before [Code] is blanked too, so line numbers match the file.
    return re.sub(r"[^\n]", " ", source[:start]) + "".join(out)


def _plain_msgbox_routines(code):
    """``{routine name: [line, ...]}`` for every plain ``MsgBox(`` call."""
    routines = [(m.start(), m.group(1)) for m in _ROUTINE.finditer(code)]
    found = {}
    for call in _PLAIN_MSGBOX.finditer(code):
        owner = [name for start, name in routines if start < call.start()][-1]
        found.setdefault(owner, []).append(code.count("\n", 0, call.start()) + 1)
    return found


def test_plain_msgbox_only_where_a_person_is_present():
    found = _plain_msgbox_routines(_code_section())
    unexpected = {
        name: lines
        for name, lines in found.items()
        if name not in _PERSON_PRESENT or len(lines) > _PERSON_PRESENT[name][0]
    }
    assert not unexpected, (
        "installer.iss calls a plain MsgBox in "
        + ", ".join(f"{name} (line {lines[-1]})" for name, lines in unexpected.items())
        + ". /SUPPRESSMSGBOXES does not answer a plain MsgBox, so a silent run (the in-app "
        "updater, #211) would wait for a click. Use SuppressibleMsgBox with the answer a silent "
        "run should take, or add the routine to _PERSON_PRESENT with the reason a person is "
        "always there."
    )


def test_data_folder_warning_leaves_silent_runs_alone():
    # Setup "clicks" Next through every page on a silent run, so NextButtonClick
    # runs there too. Its OneDrive question is a plain MsgBox, which is only
    # allowed because the routine returns first.
    code = _code_section()
    body = re.search(r"^function NextButtonClick\(.*?^end;$", code, re.S | re.M)
    assert body, "function NextButtonClick not found in installer.iss"
    silent = body.group(0).find("WizardSilent()")
    ask = body.group(0).find("MsgBox(")
    assert 0 <= silent < ask, "NextButtonClick must return on WizardSilent() before its MsgBox"
