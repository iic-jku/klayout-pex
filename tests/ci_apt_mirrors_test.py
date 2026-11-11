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

from pathlib import Path
import runpy

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / ".github/actions/setup-apt/configure_apt.py"
configure_apt = runpy.run_path(str(SCRIPT))["configure_apt"]
MIRROR_URI = "mirror+file:/etc/apt/apt-mirrors.txt"
PRIMARY = "https://archive.ubuntu.com/ubuntu/\tpriority:1\n"


@pytest.fixture
def apt_dir(tmp_path: Path) -> Path:
    sources = tmp_path / "sources.list.d"
    sources.mkdir()
    (sources / "ubuntu.sources").write_text(
        f"Types: deb\nURIs: {MIRROR_URI}\nSuites: noble noble-security\n"
        "Components: main universe\nSigned-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg\n",
        encoding="utf-8",
    )
    (tmp_path / "apt-mirrors.txt").write_text(PRIMARY, encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize("trailing_newline", [False, True])
def test_fallback_preserves_sources_keys_and_existing_mirror_order(apt_dir: Path, trailing_newline: bool):
    # The final line boundary must not concatenate a fallback with the old URL.
    mirror_file = apt_dir / "apt-mirrors.txt"
    original = PRIMARY if trailing_newline else PRIMARY.rstrip("\n")
    mirror_file.write_text(original, encoding="utf-8")
    source = apt_dir / "sources.list.d/ubuntu.sources"
    before = source.read_bytes()
    configure_apt(apt_dir)
    assert source.read_bytes() == before
    lines = mirror_file.read_text(encoding="utf-8").splitlines()
    assert lines == [PRIMARY.rstrip("\n"),
                     "https://mirror.math.princeton.edu/pub/ubuntu/\tpriority:0",
                     "https://mirrors.mit.edu/ubuntu/\tpriority:0"]


def test_rerun_does_not_duplicate_mirrors(apt_dir: Path):
    configure_apt(apt_dir)
    before = (apt_dir / "apt-mirrors.txt").read_bytes()
    configure_apt(apt_dir)
    assert (apt_dir / "apt-mirrors.txt").read_bytes() == before


def test_existing_fallback_keeps_its_priority(apt_dir: Path):
    mirror_file = apt_dir / "apt-mirrors.txt"
    original = PRIMARY + "https://mirrors.mit.edu/ubuntu/\tpriority:2\n"
    mirror_file.write_text(original, encoding="utf-8")
    configure_apt(apt_dir)
    actual = mirror_file.read_text(encoding="utf-8")
    assert actual.startswith(original)
    assert actual.count("https://mirrors.mit.edu/ubuntu/") == 1


@pytest.mark.parametrize("source_name", ["sources.list", "sources.list.d/ubuntu.list"])
def test_legacy_sources_are_supported(apt_dir: Path, source_name: str):
    (apt_dir / "sources.list.d/ubuntu.sources").unlink()
    (apt_dir / source_name).write_text(f"deb {MIRROR_URI} noble main\n", encoding="utf-8")
    configure_apt(apt_dir)
    assert "princeton.edu" in (apt_dir / "apt-mirrors.txt").read_text(encoding="utf-8")


@pytest.mark.parametrize("contents", ["", "# URIs: " + MIRROR_URI + "\n",
                                      "URIs: https://archive.ubuntu.com/ubuntu/\n"])
def test_unexpected_sources_fail_without_changes(apt_dir: Path, contents: str):
    # A future runner layout must fail visibly instead of claiming failover works.
    (apt_dir / "sources.list.d/ubuntu.sources").write_text(contents, encoding="utf-8")
    with pytest.raises(ValueError, match="do not use"):
        configure_apt(apt_dir)
    assert (apt_dir / "apt-mirrors.txt").read_text(encoding="utf-8") == PRIMARY
    assert not (apt_dir / "apt.conf.d/99-kpex-network").exists()


@pytest.mark.parametrize("contents", ["", "\n # mirrors unavailable\n"])
def test_empty_mirror_list_fails_without_configuration(apt_dir: Path, contents: str):
    (apt_dir / "apt-mirrors.txt").write_text(contents, encoding="utf-8")
    with pytest.raises(ValueError, match="empty"):
        configure_apt(apt_dir)
    assert not (apt_dir / "apt.conf.d/99-kpex-network").exists()


def test_missing_mirror_list_fails_without_configuration(apt_dir: Path):
    (apt_dir / "apt-mirrors.txt").unlink()
    with pytest.raises(FileNotFoundError):
        configure_apt(apt_dir)
    assert not (apt_dir / "apt.conf.d/99-kpex-network").exists()


def test_downloads_are_bounded_and_update_errors_fail(apt_dir: Path):
    configure_apt(apt_dir)
    config = (apt_dir / "apt.conf.d/99-kpex-network").read_text(encoding="utf-8")
    assert 'Acquire::Retries "2";' in config
    assert 'Acquire::http::Timeout "20";' in config
    assert 'Acquire::https::Timeout "20";' in config
    assert 'APT::Update::Error-Mode "any";' in config
    assert "AllowUnauthenticated" not in config
    assert "AllowInsecureRepositories" not in config
