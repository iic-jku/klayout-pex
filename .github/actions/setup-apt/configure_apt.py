#
# --------------------------------------------------------------------------------
# SPDX-FileCopyrightText: 2024-2026 Martin Jan Köhler and Harald Pretl
# Johannes Kepler University, Institute for Integrated Circuits.
#
# This file is part of KPEX
# (see https://github.com/iic-jku/klayout-pex).
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later
# --------------------------------------------------------------------------------
#

"""Keep runner APT authentication while adding independent archive mirrors."""

from pathlib import Path
from typing import List


MIRROR_URI = "mirror+file:/etc/apt/apt-mirrors.txt"
# The runner's defaults share ubuntu.com DNS. These registered mirrors use
# independent domains; the existing Ubuntu archive key still verifies their data.
# Equal priority lets APT choose between them before the runner defaults (1-3),
# avoiding repeated DNS timeouts when the whole ubuntu.com domain is unavailable.
# https://launchpad.net/ubuntu/+archivemirrors
INDEPENDENT_MIRRORS = (
    "https://mirror.math.princeton.edu/pub/ubuntu/",
    "https://mirrors.mit.edu/ubuntu/",
)
APT_CONFIG = """Acquire::Retries "2";
Acquire::http::Timeout "20";
Acquire::https::Timeout "20";
APT::Update::Error-Mode "any";
"""


def configure_apt(apt_dir: Path):
    """Extend the runner's existing mirror transport without rewriting sources."""
    sources: List[Path] = [apt_dir / "sources.list"]
    source_dir = apt_dir / "sources.list.d"
    sources.extend(sorted(source_dir.glob("*.sources")))
    sources.extend(sorted(source_dir.glob("*.list")))
    active_lines = [
        line.strip()
        for source in sources if source.is_file()
        for line in source.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if not any(MIRROR_URI in line for line in active_lines):
        raise ValueError("Runner Ubuntu sources do not use " + MIRROR_URI)

    mirror_file = apt_dir / "apt-mirrors.txt"
    original = mirror_file.read_text(encoding="utf-8")
    mirrors = {
        line.split()[0] for line in original.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    if not mirrors:
        raise ValueError("Runner Ubuntu mirror list is empty")
    additions = [
        f"{url}\tpriority:0\n"
        for url in INDEPENDENT_MIRRORS
        if url not in mirrors
    ]
    if additions:
        separator = "" if original.endswith("\n") else "\n"
        mirror_file.write_text(original + separator + "".join(additions), encoding="utf-8")
    config_dir = apt_dir / "apt.conf.d"
    config_dir.mkdir(exist_ok=True)
    (config_dir / "99-kpex-network").write_text(APT_CONFIG, encoding="utf-8")


if __name__ == "__main__":
    configure_apt(Path("/etc/apt"))
