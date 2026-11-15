"""Where the game's window is (``src/utils/game_window.py``), Qt-free.

The Windows calls are replaced: which window counts as the game, and where a
window sits inside a capture of its screen, are plain logic.
"""
import pytest

from src.utils import game_window as gw


@pytest.mark.parametrize("title, cls, program", [
    ("Star Citizen", "CryENGINE", "StarCitizen.exe"),
    ("", "", "starcitizen.EXE"),
    (" Star Citizen ", "SomeClass", "other.exe"),
    ("Other", "CryEngine", ""),
])
def test_the_game_is_known_by_its_program_title_or_class(title, cls, program):
    assert gw.is_game(title, cls, program)


@pytest.mark.parametrize("title, cls, program", [
    ("Star Citizen Launcher", "Chrome_WidgetWin_1", "RSI Launcher.exe"),
    ("Notes", "Notepad", "notepad.exe"),
    ("", "", ""),
])
def test_another_window_is_not_the_game(title, cls, program):
    assert not gw.is_game(title, cls, program)


def test_a_window_inside_a_capture_of_its_screen():
    # The game in a 1920x1080 window on a 2560x1440 screen.
    assert gw.window_in_capture((320, 180, 1920, 1080), (0, 0), (2560, 1440)) == (
        320, 180, 1920, 1080)
    # On a second screen that starts 2560 pixels to the right.
    assert gw.window_in_capture((2660, 50, 800, 600), (2560, 0), (1920, 1080)) == (
        100, 50, 800, 600)
    # Hanging off the screen's top-left and bottom-right: cut to what is there.
    assert gw.window_in_capture((-100, -50, 1920, 1080), (0, 0), (1920, 1080)) == (
        0, 0, 1820, 1030)
    assert gw.window_in_capture((1000, 800, 1920, 1080), (0, 0), (1920, 1080)) == (
        1000, 800, 920, 280)
    # Wholly off it: nothing.
    assert gw.window_in_capture((3000, 0, 800, 600), (0, 0), (1920, 1080))[2] == 0


class TestTheGamesAreaWhenItIsInFront:
    AREA = (0, 0, 1920, 1080)

    @pytest.fixture
    def windows(self, monkeypatch):
        """Fake the window in front and its place."""
        front = {"window": (5, "Star Citizen", "CryENGINE", "StarCitizen.exe")}
        monkeypatch.setattr(gw, "foreground_window", lambda: front["window"])
        monkeypatch.setattr(gw, "client_area", lambda hwnd: self.AREA if hwnd == 5 else None)
        return front

    def test_the_game_in_front_gives_its_area(self, windows):
        assert gw.foreground_game_area() == self.AREA

    def test_another_program_in_front_gives_nothing(self, windows):
        windows["window"] = (5, "Notes", "Notepad", "notepad.exe")
        assert gw.foreground_game_area() is None

    def test_no_window_in_front_gives_nothing(self, windows):
        windows["window"] = (0, "", "", "")
        assert gw.foreground_game_area() is None
        assert gw.foreground_game_area(any_window=True) is None

    def test_any_window_counts_when_asked_but_never_our_own(self, windows):
        windows["window"] = (5, "Notes", "Notepad", "notepad.exe")
        assert gw.foreground_game_area(any_window=True) == self.AREA
        assert gw.foreground_game_area(any_window=True, own_windows=(5,)) is None

    def test_a_minimised_game_gives_nothing(self, windows, monkeypatch):
        monkeypatch.setattr(gw, "client_area", lambda hwnd: None)
        assert gw.foreground_game_area() is None
