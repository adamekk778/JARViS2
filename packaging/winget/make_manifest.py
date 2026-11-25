"""3.14 návrh 115: the winget manifests for a release (Windows Package Manager: `winget install adamekk778.JARVIS`).

    python packaging/winget/make_manifest.py 3.14.0 dist/JARVIS-Setup.exe out/winget [owner/repo]

Writes the three files winget wants (version, installer, locale) with the installer's SHA-256 and its download address
on GitHub Releases. The release workflow attaches them to every stable release; getting JARVIS into the public winget
catalog is one pull request with these files to microsoft/winget-pkgs (see docs/WINGET.md) – that step needs a person.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

PACKAGE_ID = "adamekk778.JARVIS"
REPO = "adamekk778/JARViS2"
MANIFEST_VERSION = "1.6.0"
SCHEMA = "https://aka.ms/winget-manifest.{kind}.1.6.0.schema.json"


def sha256(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def manifests(version: str, sha: str, repo: str = REPO) -> dict[str, str]:
    url = f"https://github.com/{repo}/releases/download/v{version}/JARVIS-Setup.exe"
    head = f"PackageIdentifier: {PACKAGE_ID}\nPackageVersion: {version}\n"
    return {
        f"{PACKAGE_ID}.yaml": f"# yaml-language-server: $schema={SCHEMA.format(kind='version')}\n{head}"
                              f"DefaultLocale: cs-CZ\nManifestType: version\nManifestVersion: {MANIFEST_VERSION}\n",
        f"{PACKAGE_ID}.installer.yaml": f"# yaml-language-server: $schema={SCHEMA.format(kind='installer')}\n{head}"
                                        "InstallerType: inno\nScope: user\nInstallModes:\n  - interactive\n  - silent\n"
                                        "UpgradeBehavior: install\nMinimumOSVersion: 10.0.17763.0\nInstallers:\n"
                                        f"  - Architecture: x64\n    InstallerUrl: {url}\n    InstallerSha256: {sha}\n"
                                        f"ManifestType: installer\nManifestVersion: {MANIFEST_VERSION}\n",
        f"{PACKAGE_ID}.locale.cs-CZ.yaml": f"# yaml-language-server: $schema={SCHEMA.format(kind='defaultLocale')}\n{head}"
                                          "PackageLocale: cs-CZ\nPublisher: adamekk778\nPackageName: JARVIS\n"
                                          f"PackageUrl: https://github.com/{repo}\nLicense: Proprietary\n"
                                          "ShortDescription: Osobní AI asistent pro Windows – hlas, notch, ovládání PC a telefon.\n"
                                          "Description: JARVIS mluví česky, ovládá počítač, čte e-maily a kalendář, hlídá výkon PC a "
                                          "spolupracuje s telefonem.\nMoniker: jarvis\nTags:\n  - ai\n  - assistant\n  - voice\n  - czech\n"
                                          f"ReleaseNotesUrl: https://github.com/{repo}/releases/tag/v{version}\n"
                                          f"ManifestType: defaultLocale\nManifestVersion: {MANIFEST_VERSION}\n",
    }


def write(version: str, installer: str | Path, out: str | Path, repo: str = REPO) -> list[Path]:
    folder = Path(out)
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, text in manifests(version, sha256(installer), repo).items():
        p = folder / name
        p.write_text(text, encoding="utf-8", newline="\n")
        paths.append(p)
    return paths


if __name__ == "__main__":
    if len(sys.argv) not in (4, 5):
        print(__doc__)
        sys.exit(2)
    for p in write(*sys.argv[1:5]):
        print(p)
