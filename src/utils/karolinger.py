"""Links for the Karolinger Guides collaboration (#602).

One place for both links, so the footer logo, the Help panel and the guided
tour's last step all open the same pages.
"""

# PLACEHOLDER (#602): the Smart Citizen guides page on Karolinger Guides is
# not published yet. Replace this with the real link before release.
KAROLINGER_GUIDES_URL = "https://github.com/Osiris-DevWorks/smart-citizen"

# PLACEHOLDER (#602): the Smart Citizen video tutorial is not published yet.
# Replace this with the real link before release.
KAROLINGER_VIDEO_TUTORIAL_URL = "https://github.com/Osiris-DevWorks/smart-citizen"

# HELP.md (every language) writes the guides link as this token, which the
# Help panel swaps for KAROLINGER_GUIDES_URL, so the link lives only here.
GUIDES_URL_TOKEN = "{KAROLINGER_GUIDES_URL}"


def with_guides_url(markdown: str) -> str:
    """Return *markdown* with the guides link token replaced by the link."""
    return markdown.replace(GUIDES_URL_TOKEN, KAROLINGER_GUIDES_URL)
