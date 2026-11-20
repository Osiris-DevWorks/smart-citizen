# Security Policy

## Reporting a problem

Please don't report security problems in a public issue.

Use GitHub's private reporting instead: open the repository's **Security** tab and click **Report a vulnerability**. Only the maintainer sees the report.

Include what you found, the Smart Citizen version, and steps to reproduce it if you can. You'll get a reply within a week.

## Supported versions

Only the latest release gets security fixes. Please update before reporting.

## Checking a download

Download Smart Citizen only from the [GitHub releases page](https://github.com/Osiris-DevWorks/smart-citizen/releases).

Each release lists VirusTotal scan links for its files in the release notes. You can also check that a file was built by this repository's release workflow:

```
gh attestation verify SmartCitizen-X.Y.Z-Setup.exe --repo Osiris-DevWorks/smart-citizen
```

Windows Defender sometimes flags new, unsigned apps with a machine-learning guess such as "Bearfoos.A!ml". That is a false positive. Code signing is planned for a future release.
