"""Reading what slackpkg already knows.

Both sources here are world readable, so building the package list needs no
privileges at all -- only the actions in runner.py do. Nothing in this module
writes anything or touches the network.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

WORKDIR = Path("/var/lib/slackpkg")
PACKAGES_TXT = WORKDIR / "PACKAGES.TXT"
CHANGELOG = WORKDIR / "ChangeLog.txt"
INSTALLED_DIR = Path("/var/log/packages")
BLACKLIST = Path("/etc/slackpkg/blacklist")
SLACKPKG_CONF = Path("/etc/slackpkg/slackpkg.conf")

# Where looknew (post-functions.sh:148) hunts for .new files, and the names it
# refuses to consider. Those exclusions are not arbitrary: passwd/shadow/group
# hold live account data and rc.inet1.conf holds this host's network settings,
# so a stock replacement would break the machine. Mirrored exactly, because
# this list is only useful if it reports what slackpkg itself would.
NEW_CONFIG_ROOTS = (Path("/etc"), Path("/var/yp"), Path("/usr/share/vim"))
NEW_CONFIG_SKIP = frozenset({
    "rc.inet1.conf.new", "rc.wireless.conf.new",
    "group.new", "passwd.new", "shadow.new", "gshadow.new",
})

# "===== START REPO: slackware64 : URL:ftp://... ====="  -- slackpkg+ writes
# these markers when it merges several repositories into one PACKAGES.TXT.
_REPO_RE = re.compile(r"^=====\s*START REPO:\s*(\S+)\s*:")
_PKG_SUFFIX_RE = re.compile(r"\.t[gblxz]z$")


def split_pkgname(filename: str) -> tuple[str, str, str, str]:
    """Split a Slackware package identifier into (name, version, arch, build).

    The name itself may contain hyphens ("AMF-headers-1.5.2-noarch-2"), so this
    has to split from the right and never from the left.
    """
    stem = _PKG_SUFFIX_RE.sub("", filename)
    parts = stem.rsplit("-", 3)
    if len(parts) != 4:
        return stem, "", "", ""
    return parts[0], parts[1], parts[2], parts[3]


@dataclass
class Package:
    name: str
    version: str = ""
    arch: str = ""
    build: str = ""
    repo: str = ""
    location: str = ""
    size_c: str = ""
    size_u: str = ""
    description: str = ""
    # version-arch-build as actually installed, or None
    installed: str | None = None
    # matched by a rule in /etc/slackpkg/blacklist
    blacklisted: bool = False

    @property
    def available_id(self) -> str:
        return "-".join(p for p in (self.version, self.arch, self.build) if p)

    @property
    def in_repo(self) -> bool:
        return bool(self.repo)

    @property
    def is_installed(self) -> bool:
        return self.installed is not None

    @property
    def differs(self) -> bool:
        """Installed, in a repo, and not the same build the repo offers.

        slackpkg decides an upgrade the same way -- by comparing the package
        identifier, not by parsing version numbers -- so this deliberately says
        "differs" rather than "newer": a downgrade looks identical here.
        """
        return self.is_installed and self.in_repo and self.installed != self.available_id

    @property
    def upgradable(self) -> bool:
        """Differs *and* slackpkg would actually act on it.

        Not the same question as `differs`. A blacklisted package differs from
        the mirror forever and slackpkg silently skips it, so counting it as an
        update means offering an upgrade that returns exit 20 having done
        nothing -- which is exactly what it did before this existed.
        """
        return self.differs and not self.blacklisted

    @property
    def summary(self) -> str:
        return self.description.split("\n", 1)[0].strip()

    @property
    def body(self) -> str:
        """Description minus the summary line, re-flowed.

        PACKAGES.TXT hard-wraps every description to fit a terminal, so the
        stored newlines are not meaningful; joining runs of non-blank lines
        back into paragraphs lets the label wrap to its own width instead.
        """
        lines = self.description.split("\n")[1:]
        paragraphs, current = [], []
        for line in lines:
            if line.strip():
                current.append(line.strip())
            elif current:
                paragraphs.append(" ".join(current))
                current = []
        if current:
            paragraphs.append(" ".join(current))
        return "\n\n".join(paragraphs)


def read_installed(directory: Path = INSTALLED_DIR) -> dict[str, str]:
    """name -> "version-arch-build" for every package pkgtools has recorded."""
    installed: dict[str, str] = {}
    try:
        entries = sorted(p.name for p in directory.iterdir() if p.is_file())
    except OSError:
        return installed
    for entry in entries:
        name, version, arch, build = split_pkgname(entry)
        if name:
            installed[name] = "-".join(p for p in (version, arch, build) if p)
    return installed


def read_available(path: Path = PACKAGES_TXT) -> dict[str, Package]:
    """name -> Package for every entry in the merged PACKAGES.TXT.

    Where several repositories carry the same name the first one wins, which
    follows the order slackpkg+ writes them in: patches ahead of the main tree,
    and testing/pasture last.
    """
    packages: dict[str, Package] = {}
    repo = ""
    current: Package | None = None
    description: list[str] = []

    def flush() -> None:
        nonlocal current, description
        if current is not None:
            current.description = "\n".join(description).strip()
            packages.setdefault(current.name, current)
        current, description = None, []

    try:
        text = path.read_text(errors="replace")
    except OSError:
        return packages

    for line in text.splitlines():
        marker = _REPO_RE.match(line)
        if marker:
            flush()
            repo = marker.group(1)
            continue

        if line.startswith("PACKAGE NAME:"):
            flush()
            name, version, arch, build = split_pkgname(line.split(":", 1)[1].strip())
            if name:
                current = Package(name, version, arch, build, repo=repo)
            continue

        if current is None:
            continue

        if line.startswith("PACKAGE LOCATION:"):
            current.location = line.split(":", 1)[1].strip()
        elif line.startswith("PACKAGE SIZE (compressed):"):
            current.size_c = line.split(":", 1)[1].strip()
        elif line.startswith("PACKAGE SIZE (uncompressed):"):
            current.size_u = line.split(":", 1)[1].strip()
        elif line.startswith("PACKAGE DESCRIPTION:"):
            description = []
        elif line.startswith(f"{current.name}:"):
            # description lines are prefixed with the package name
            description.append(line.split(":", 1)[1].strip())
        elif not line.strip():
            flush()

    flush()
    return packages


def read_blacklist(path: Path = BLACKLIST) -> list[re.Pattern[str]]:
    """Compile /etc/slackpkg/blacklist into extended regexes.

    Entries are ERE matched against package names, so most of them work as
    Python regexes unchanged. Anything that does not compile is skipped rather
    than raised: a malformed line should cost one rule, not the whole list.
    """
    patterns: list[re.Pattern[str]] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return patterns
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # "kde/" and friends name a package set, not a regex; slackpkg rewrites
        # those against the mirror layout, which is more than we can do from
        # here, so they are left alone rather than matched wrongly.
        if line.endswith("/"):
            continue
        try:
            patterns.append(re.compile(line))
        except re.error:
            continue
    return patterns


def is_blacklisted(pkg: Package, patterns: list[re.Pattern[str]]) -> bool:
    """Match the way mkregex_blacklist does.

    core-functions.sh feeds *both* the mirror's pkglist and /var/log/packages
    through these regexes and blacklists every name that either side matches.
    That detail is the whole point: a rule like `[0-9]+_SBo` never matches what
    the mirror offers, only the build tag of what is already installed. Testing
    the available identifier alone finds nothing.
    """
    candidates = [pkg.name]
    if pkg.installed:
        candidates.append(f"{pkg.name}-{pkg.installed}")
    if pkg.available_id:
        candidates.append(f"{pkg.name}-{pkg.available_id}")
    return any(r.search(c) for r in patterns for c in candidates)


def download_dir(conf: Path = SLACKPKG_CONF) -> Path:
    """Where slackpkg caches packages while installing them -- TEMP in
    slackpkg.conf. Values containing shell expansion are ignored rather than
    half-parsed; the stock default is the right guess in that case."""
    try:
        for line in conf.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line.startswith("#") or not line.startswith("TEMP="):
                continue
            value = line.split("=", 1)[1].strip().strip("\"'")
            if value and "$" not in value:
                return Path(value)
    except OSError:
        pass
    return Path("/var/cache/packages")


def free_bytes(path: Path) -> int | None:
    """Free space on the filesystem holding `path`, or None if unknowable.

    Walks up to the nearest existing ancestor, because the download cache may
    not have been created yet. Reports f_bavail rather than f_bfree, matching
    what df -- and therefore slackpkg's own check -- calls "Available".
    """
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        stat = os.statvfs(probe)
    except OSError:
        return None
    return stat.f_bavail * stat.f_frsize


def human_bytes(count: int) -> str:
    value = float(count)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if value < 1024 or unit == "GiB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GiB"


@dataclass
class SpaceReport:
    """Whether a pending operation fits on disk.

    slackpkg+ has this check too, but the GUI never reaches it: the version
    carrying it is defined only inside `if [ "$DIALOG" = "on" ]`
    (slackpkgplus.sh:1646) and the GUI passes -dialog=off, and CHECKDISKSPACE
    is off by default regardless. So nothing warns unless this does.

    Deliberately conservative for upgrades: the space the outgoing version
    gives back is not subtracted, because slackpkg unpacks the new package
    before removing the old one.
    """
    download_need: int
    download_free: int | None
    download_path: Path
    install_need: int
    install_free: int | None
    install_path: Path

    @property
    def download_short(self) -> bool:
        return self.download_free is not None and self.download_free < self.download_need

    @property
    def install_short(self) -> bool:
        return self.install_free is not None and self.install_free < self.install_need

    @property
    def short(self) -> bool:
        return self.download_short or self.install_short


def space_report(packages: list[Package], command: str = "") -> SpaceReport | None:
    """Size up an operation, or None when the question does not apply.

    Removals free space rather than consuming it, and a package with no size in
    PACKAGES.TXT (anything hand-built) cannot be measured -- reporting 0 for
    those would understate the total, so an all-unmeasurable set reports
    nothing at all instead of a false all-clear.
    """
    if command == "remove" or not packages:
        return None

    download_need = sum(size_to_bytes(p.size_c) for p in packages if p.size_c)
    install_need = sum(size_to_bytes(p.size_u) for p in packages if p.size_u)
    if not download_need and not install_need:
        return None

    cache = download_dir()
    root = Path("/usr")
    return SpaceReport(
        download_need=download_need, download_free=free_bytes(cache), download_path=cache,
        install_need=install_need, install_free=free_bytes(root), install_path=root,
    )


INSTALL_NEW_AWK = Path("/usr/libexec/slackpkg/install-new.awk")

# core-functions.sh:798-801 appends these to whatever the ChangeLog yields,
# unconditionally. Copied rather than inferred, because they are not derivable
# from anything -- they are a hand-maintained list of packages Slackware wants
# present.
INSTALL_NEW_ALWAYS = frozenset({
    "dialog", "aaa_terminfo", "fontconfig", "ntfs-3g", "ghostscript",
    "wqy-zenhei-font-ttf", "xbacklight", "xf86-video-geode",
})


def pending_new_packages(packages: list[Package]) -> list[Package]:
    """Packages `slackpkg install-new` would install.

    Not the same as "in a repo and not installed" -- that is every optional
    package in Slackware. install-new is ChangeLog-driven: it runs
    install-new.awk over ChangeLog.txt to find what the distribution has
    *added*, then keeps the ones a repo offers and the system lacks
    (core-functions.sh:797-808).

    The real awk script is invoked rather than reimplemented, for the same
    reason the rest of this program shells out to slackpkg: a second
    implementation of the rule is a second thing to get wrong. This is the one
    place the module runs a subprocess, and it is read-only.
    """
    if not INSTALL_NEW_AWK.exists() or not CHANGELOG.exists():
        return []
    try:
        done = subprocess.run(["awk", "-f", str(INSTALL_NEW_AWK), str(CHANGELOG)],
                              capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return []

    names = {n.strip() for n in done.stdout.split() if n.strip()} | INSTALL_NEW_ALWAYS
    by_name = {p.name: p for p in packages}
    return sorted(
        (by_name[n] for n in names
         if n in by_name and by_name[n].in_repo and not by_name[n].is_installed
         and not by_name[n].blacklisted),
        key=lambda p: p.name.lower(),
    )


def find_new_config_files(roots: tuple[Path, ...] = NEW_CONFIG_ROOTS) -> list[Path]:
    """Config files a package shipped that are not in use yet.

    Purely a report. Whether a .new file should replace a hand-edited config is
    a judgement no front end gets to make, so nothing here opens, moves or
    deletes one -- see the note in runner.py about why the hook that *does*
    offer to is switched off.

    Unreadable directories are skipped rather than raised: this runs as a normal
    user and parts of /etc are not world readable.
    """
    found: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        for dirpath, _dirs, names in os.walk(root, onerror=lambda _e: None):
            for name in names:
                if name.endswith(".new") and name not in NEW_CONFIG_SKIP:
                    found.append(Path(dirpath) / name)
    return sorted(found)


def load() -> list[Package]:
    """The merged view: everything available, plus anything installed that no
    configured repository offers (hand-built or SlackBuilds packages)."""
    available = read_available()
    installed = read_installed()

    for name, version_id in installed.items():
        pkg = available.get(name)
        if pkg is None:
            name_, version, arch, build = split_pkgname(f"{name}-{version_id}")
            available[name] = Package(name, version, arch, build, installed=version_id)
        else:
            pkg.installed = version_id

    patterns = read_blacklist()
    if patterns:
        for pkg in available.values():
            pkg.blacklisted = is_blacklisted(pkg, patterns)

    return sorted(available.values(), key=lambda p: p.name.lower())


def size_to_bytes(text: str) -> int:
    """'64 K' / '5263 M' -> bytes, for sorting. Unparseable sizes sort first."""
    match = re.match(r"\s*([\d.]+)\s*([KMG])?", text or "")
    if not match:
        return 0
    value = float(match.group(1))
    return int(value * {"K": 1024, "M": 1024**2, "G": 1024**3}.get(match.group(2) or "K", 1024))


def last_update() -> str:
    """When slackpkg last refreshed the lists. LASTUPDATE holds a unix timestamp."""
    try:
        stamp = (WORKDIR / "LASTUPDATE").read_text().strip()
        return datetime.fromtimestamp(int(stamp)).strftime("%d %b %H:%M")
    except (OSError, ValueError):
        return ""
