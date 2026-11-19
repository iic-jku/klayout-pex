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

"""Portable, hashed protobuf artifacts for calibration execution and collection."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path, PurePosixPath
import re
from typing import Iterable, List, TypeVar
from uuid import uuid4

from google.protobuf.json_format import MessageToJson, ParseError
from google.protobuf.message import Message

from .validation import CalibrationError
from ..util.protobuf_json import parse_protobuf_json

MessageType = TypeVar('MessageType', bound=Message)
MAX_JSON_BYTES = 16 * 1024 * 1024


def read_message(path: Path, message: MessageType) -> MessageType:
    try:
        if path.is_symlink():
            raise CalibrationError(f"Artifact '{path}' must not be a symlink")
        with path.open('rb') as stream:
            data = stream.read(MAX_JSON_BYTES + 1)
        if len(data) > MAX_JSON_BYTES:
            raise CalibrationError(f"Artifact '{path}' exceeds {MAX_JSON_BYTES} bytes")
        return parse_protobuf_json(data.decode('utf-8'), message)
    except (OSError, UnicodeError, ValueError, ParseError, RecursionError) as exc:
        raise CalibrationError(f"Cannot read protobuf artifact '{path}': {exc}") from exc


def write_message(path: Path, message: Message, *, replace: bool = False) -> Path:
    data = (MessageToJson(message, preserving_proto_field_name=True, sort_keys=True,
                         ensure_ascii=False, always_print_fields_with_no_presence=True) + '\n').encode('utf-8')
    temporary = path.with_name(path.name + '.' + uuid4().hex + '.tmp')
    try:
        with temporary.open('xb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if replace:
            if path.is_symlink():
                raise CalibrationError(f"Checkpoint '{path}' must not be a symlink")
            os.replace(temporary, path)
        else:
            # A hard link creates the name exclusively; never overwrite existing evidence.
            os.link(temporary, path)
        return path
    except OSError as exc:
        raise CalibrationError(f"Cannot write protobuf artifact '{path}': {exc}") from exc
    finally:
        temporary.unlink(missing_ok=True)


def sha256_file(path: Path) -> str:
    try:
        with path.open('rb') as stream:
            return hashlib.file_digest(stream, 'sha256').hexdigest()
    except OSError as exc:
        raise CalibrationError(f"Cannot hash artifact '{path}': {exc}") from exc


def artifact_path(directory: Path, name: str, *, required: bool = True) -> Path:
    if (not name or '\\' in name or ':' in name or '\x00' in name
            or name != PurePosixPath(name).as_posix() or PurePosixPath(name).is_absolute()
            or any(part in ('.', '..') for part in PurePosixPath(name).parts)):
        raise CalibrationError(f"Invalid relative artifact path {name!r}")
    path = directory
    for part in PurePosixPath(name).parts:
        path = path / part
        if path.is_symlink():
            raise CalibrationError(f"Artifact path '{name}' must not contain symlinks")
    if required and not path.is_file():
        raise CalibrationError(f"Artifact '{name}' is missing or is not a regular file")
    return path


def verify_artifacts(directory: Path, records: Iterable[Message]) -> List[Path]:
    paths = []
    seen = set()
    for record in records:
        path = artifact_path(directory, record.path)
        if record.path.casefold() in seen:
            raise CalibrationError(f"Artifact path '{record.path}' repeats ignoring case")
        seen.add(record.path.casefold())
        if re.fullmatch(r'[0-9a-f]{64}', record.sha256) is None:
            raise CalibrationError(f"Artifact '{record.path}' needs a lowercase SHA256 digest")
        if sha256_file(path) != record.sha256:
            raise CalibrationError(f"Artifact '{record.path}' has changed (SHA256 mismatch)")
        paths.append(path)
    return paths


def copy_artifact(source: Path, destination: Path, expected_hash: str) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with source.open('rb') as src, destination.open('xb') as dst:
        while chunk := src.read(1024 * 1024):
            dst.write(chunk)
    if sha256_file(destination) != expected_hash:
        raise CalibrationError(f"Artifact '{source}' changed during copying")
    return destination


def validate_output_directory(path: Path):
    if path.exists() or path.is_symlink():
        raise CalibrationError(f"Output path '{path}' already exists; choose a new directory")
    if not path.parent.is_dir():
        raise CalibrationError(f"Output parent '{path.parent}' must be an existing directory")
