#
# --------------------------------------------------------------------------------
# SPDX-FileCopyrightText: 2024-2025 Martin Jan Köhler and Harald Pretl
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
import gzip
import io
import os.path
import shutil
import sys
from typing import *
import xml.etree.ElementTree as ET

import klayout.rdb as rdb
from ..log import (
    LogLevel,
    set_log_level,
    register_additional_handler,
    deregister_additional_handler,
    # console,
    # debug,
    info,
    warning,
    subproc,
    error,
    rule
)


def parse_category_path(category_path: str) -> List[str]:
    within_escaped = False
    within_backslash = False
    current_word = ''
    path_list = []
    for c in category_path:
        match c:
            case '.':
                if within_backslash:
                    current_word += c
                    within_backslash = False
                elif within_escaped:
                    current_word += c
                else:
                    path_list.append(current_word)
                    current_word = ''
            case '\\':
                if within_backslash:
                    current_word += c
                    within_backslash = False
                else:
                    within_backslash = True
            case '\'':
                if within_backslash:
                    current_word += c
                    within_backslash = False
                else:
                    within_escaped = not within_escaped
            case _:
                current_word += c
    if len(current_word) >= 1:
        path_list.append(current_word)
    return path_list

def repair_rdb_xml(xml_file: io.IOBase, new_xml_path: str):
    et = ET.parse(xml_file)
    root = et.getroot()

    categories: Set[str] = set(
        [e.text for e in root.findall('./items/item/category')]
    )
    category_paths = [parse_category_path(c) for c in categories]
    category_paths.sort()
    # print(category_paths)
    for p in category_paths:
        elem = root
        for c in p:
            elemcats = elem.find("./categories")
            subelem = elemcats.find("./category/name[.='{0}']/..".format(c))
            if subelem is None:
                warning(f"In category path {p}, can't find element for component {c}")
                new_category = ET.SubElement(elemcats, "category")
                new_cname = ET.SubElement(new_category, "name")
                new_cname.text = c
                ET.SubElement(new_category, 'description')
                ET.SubElement(new_category, 'categories')
                elem = new_category
            else:
                elem = subelem

    et.write(new_xml_path)


def repair_rdb(rdb_path: str):
    rdb_file: io.IOBase
    suffix = os.path.splitext(rdb_path)[-1]
    new_xml_path = rdb_path + '.repair.xml'

    if suffix == '.gz':
        with gzip.open(rdb_path, 'r') as f:
            repair_rdb_xml(f, new_xml_path)
    else:
        with open(rdb_path, 'r') as f:
            repair_rdb_xml(f, new_xml_path)

    report = rdb.ReportDatabase('')
    try:
        report.load(new_xml_path)
        info(f"Succeeded in repairing broken marker database {rdb_path} under {new_xml_path}")

    except Exception as e:
        error(f"Failed to repair broken marker database {rdb_path} due to exception: {e}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} file.rdb.gz")
        sys.exit(1)

    repair_rdb(sys.argv[1])
