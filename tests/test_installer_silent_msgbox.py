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
on that list. ``TaskDialogMsgBox`` counts as plain too (``/SUPPRESSMSGBOXES``
does not answer it either), and so does any spelling Pascal Script accepts:
``MsgBox (`` with a gap before the bracket, ``msgbox(`` in any case.
"""

import re
from pathlib import Path

import pytest

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
        "the report after the opt-in delete-all, which only runs once that box is ticked",
    ),
}

# A routine header in any spelling Pascal Script accepts (any case, any gap after
# the keyword), so a box is always charged to the routine it sits in, never to
# the one above it, where a listed routine's allowance could cover it.
_ROUTINE = re.compile(r"^(?:function|procedure)\s+(\w+)", re.M | re.I)
# A plain box call however it is spelled: Pascal Script ignores case and the
# whitespace before the bracket, and TaskDialogMsgBox is no more answered by
# /SUPPRESSMSGBOXES than MsgBox is. The lookbehind lets SuppressibleMsgBox,
# SuppressibleTaskDialogMsgBox and any other name that only ends in these words
# (MyMsgBox, My_MsgBox, Box2MsgBox) through.
_PLAIN_MSGBOX = re.compile(r"(?<![A-Za-z0-9_])(?:TaskDialog)?MsgBox\s*\(", re.I)


def _installer_source():
    return INSTALLER.read_text(encoding="utf-8-sig")


def _code_section(source):
    """The ``[Code]`` section of *source* (the text of installer.iss) with
    comments and string literals blanked out (newlines kept, so line numbers
    still match), leaving only the code."""
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
    """``{routine name: [line, ...]}`` for every plain message box call."""
    routines = [(m.start(), m.group(1)) for m in _ROUTINE.finditer(code)]
    found = {}
    for call in _PLAIN_MSGBOX.finditer(code):
        owner = [name for start, name in routines if start < call.start()][-1]
        found.setdefault(owner, []).append(code.count("\n", 0, call.start()) + 1)
    return found


def _unexpected_plain_msgboxes(source):
    """``{routine name: [line, ...]}`` for the routines of *source* (the text of
    installer.iss) that call a plain message box they are not allowed to: one
    that is not on the list, or more calls than the list allows."""
    return {
        name: lines
        for name, lines in _plain_msgbox_routines(_code_section(source)).items()
        if name not in _PERSON_PRESENT or len(lines) > _PERSON_PRESENT[name][0]
    }


def test_plain_msgbox_only_where_a_person_is_present():
    unexpected = _unexpected_plain_msgboxes(_installer_source())
    assert not unexpected, (
        "installer.iss calls a plain MsgBox (or TaskDialogMsgBox) in "
        + ", ".join(f"{name} (line {lines[-1]})" for name, lines in unexpected.items())
        + ". /SUPPRESSMSGBOXES does not answer a plain MsgBox, so a silent run (the in-app "
        "updater, #211) would wait for a click. Use SuppressibleMsgBox with the answer a silent "
        "run should take, or add the routine to _PERSON_PRESENT with the reason a person is "
        "always there."
    )


def test_the_guard_finds_the_boxes_in_the_real_installer():
    # The real file has plain boxes (the allowed ones). A guard that found none
    # would be passing the test above without having read anything.
    assert _plain_msgbox_routines(_code_section(_installer_source()))


def test_data_folder_warning_leaves_silent_runs_alone():
    # Setup "clicks" Next through every page on a silent run, so NextButtonClick
    # runs there too. Its OneDrive question is a plain MsgBox, which is only
    # allowed because the routine returns first.
    code = _code_section(_installer_source())
    body = re.search(r"^function NextButtonClick\(.*?^end;$", code, re.S | re.M)
    assert body, "function NextButtonClick not found in installer.iss"
    silent = body.group(0).find("WizardSilent()")
    box = _PLAIN_MSGBOX.search(body.group(0))
    assert box, "NextButtonClick has no plain message box any more, update this check"
    assert 0 <= silent < box.start(), (
        "NextButtonClick must return on WizardSilent() before its MsgBox"
    )


# The guard on synthetic sources, so each spelling is tried without editing the
# real installer.iss.


def _source(*routines):
    """installer.iss text whose ``[Code]`` section holds the ``(name, body)`` routines."""
    code = "\n".join(f"procedure {name};\nbegin\n{body}\nend;\n" for name, body in routines)
    return "[Setup]\nAppName=x\n\n[Code]\n" + code


def _line_of(source, text):
    return source.splitlines().index(text) + 1


@pytest.mark.parametrize(
    "call",
    [
        "  MsgBox('x', mbInformation, MB_OK);",
        "  MsgBox ('x', mbInformation, MB_OK);",
        "  MsgBox   ('x', mbInformation, MB_OK);",
        "  MsgBox\t('x', mbInformation, MB_OK);",
        "  MsgBox { why } ('x', mbInformation, MB_OK);",
        "  MsgBox (* why *) ('x', mbInformation, MB_OK);",
        "  TaskDialogMsgBox('T', 'x', mbInformation, MB_OK, ['OK'], 0);",
        "  TaskDialogMsgBox ('T', 'x', mbInformation, MB_OK, ['OK'], 0);",
        "  msgbox('x', mbInformation, MB_OK);",
        "  MSGBOX ('x', mbInformation, MB_OK);",
        "  taskdialogmsgbox ('T', 'x', mbInformation, MB_OK, ['OK'], 0);",
        "  Result := MsgBox ('x', mbConfirmation, MB_YESNO) = IDYES;",
        "  if MsgBox('x', mbConfirmation, MB_YESNO) = IDYES then Exit;",
    ],
)
def test_every_spelling_of_a_plain_box_is_caught(call):
    source = _source(("Unlisted", call))
    assert _unexpected_plain_msgboxes(source) == {"Unlisted": [_line_of(source, call)]}


def test_a_gap_that_runs_over_lines_is_caught():
    for gap in ("\n    ", "\r\n    ", " // why\n    ", " { why }\n    "):
        source = _source(("Unlisted", f"  MsgBox{gap}('x', mbInformation, MB_OK);"))
        assert _unexpected_plain_msgboxes(source) == {"Unlisted": [_line_of(source, "begin") + 1]}


@pytest.mark.parametrize(
    "declaration",
    [
        "Procedure Sneaky;",
        "PROCEDURE Sneaky;",
        "procedure  Sneaky;",
        "procedure\tSneaky;",
        "Function Sneaky(): Boolean;",
        "function  Sneaky(): Boolean;",
    ],
)
def test_a_box_is_charged_to_its_own_routine_however_that_is_declared(declaration):
    # CurStepChanged may hold one plain box. Sneaky, declared in another spelling
    # right after it, must not slip its box in under that allowance.
    box = "  MsgBox('x', mbInformation, MB_OK);"
    source = (
        "[Setup]\nAppName=x\n\n[Code]\n"
        "procedure CurStepChanged;\nbegin\n  Log('x');\nend;\n\n"
        f"{declaration}\nbegin\n{box}\nend;\n"
    )
    assert _unexpected_plain_msgboxes(source) == {"Sneaky": [_line_of(source, box)]}


@pytest.mark.parametrize(
    "call",
    [
        "  SuppressibleMsgBox('x', mbInformation, MB_OK, IDOK);",
        "  SuppressibleMsgBox ('x', mbInformation, MB_OK, IDOK);",
        "  SuppressibleTaskDialogMsgBox('T', 'x', mbInformation, MB_OK, [], 0, MB_OK, IDOK);",
        "  SuppressibleTaskDialogMsgBox ('T', 'x', mbInformation, MB_OK, [], 0, MB_OK, IDOK);",
        "  MyMsgBox('x');",
        "  MyTaskDialogMsgBox ('x');",
        "  ShowMsgBox ('x');",
        "  My_MsgBox ('x');",
        "  Box2MsgBox('x');",
        "  // MsgBox('x') is only a comment",
        "  { MsgBox ('x') } { TaskDialogMsgBox('x') }",
        "  (* MsgBox ('x') *)",
        "  Log('MsgBox(');",
        "  Log('it''s a MsgBox (' + 'TaskDialogMsgBox(');",
    ],
)
def test_suppressible_wrappers_lookalikes_comments_and_strings_pass(call):
    assert _unexpected_plain_msgboxes(_source(("Unlisted", call))) == {}


@pytest.fixture
def allowed_once(monkeypatch):
    monkeypatch.setitem(_PERSON_PRESENT, "Allowed", (1, "a person is always there"))


@pytest.mark.parametrize("call", ["  MsgBox('x');", "  TaskDialogMsgBox ('x');"])
def test_a_listed_routine_may_make_its_one_call(allowed_once, call):
    assert _unexpected_plain_msgboxes(_source(("Allowed", call))) == {}


def test_a_second_call_in_a_listed_routine_is_a_new_decision(allowed_once):
    # Whichever spelling the second one uses.
    first, second = "  MsgBox('a');", "  TaskDialogMsgBox ('b');"
    source = _source(("Allowed", first + "\n" + second))
    assert _unexpected_plain_msgboxes(source) == {
        "Allowed": [_line_of(source, first), _line_of(source, second)]
    }


def test_a_call_is_charged_to_its_own_routine_not_a_listed_neighbour(allowed_once):
    listed, other = "  MsgBox('a');", "  MsgBox ('b');"
    source = _source(("Allowed", listed), ("Unlisted", other))
    assert _unexpected_plain_msgboxes(source) == {"Unlisted": [_line_of(source, other)]}
