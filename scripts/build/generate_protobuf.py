#
# --------------------------------------------------------------------------------
# SPDX-FileCopyrightText: 2024-2026 Martin Jan Köhler and Harald Pretl
# Johannes Kepler University, Institute for Integrated Circuits.
#
# This file is part of KPEX
# (see https://github.com/iic-jku/kpex).
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

"""Generate Python bindings without changing protobuf names or schema paths."""

from pathlib import Path
import re
import tempfile

from grpc_tools import protoc
import grpc_tools


def qualify_generated_modules(source: str, module_name: str) -> str:
    # protoc derives Python import paths from proto paths. The proto paths start
    # with kpex/, which is also the name of the separate application package.
    source = re.sub(r'^from (kpex(?:\.\w+)*) import ', r'from kpex_protobuf.\1 import ',
                    source, flags=re.MULTILINE)
    source, count = re.subn(r"(_builder\.BuildTopDescriptorsAndMessages\(DESCRIPTOR, )'kpex\.[^']+'",
                            lambda match: f"{match[1]}'{module_name}'", source)
    if count != 1:
        raise RuntimeError(f'Expected one protobuf module declaration in {module_name}')
    return source


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    schema_dir = root / 'protos'
    schemas = sorted(schema_dir.rglob('*.proto'))
    output_dir = root / 'kpex_protobuf'
    with tempfile.TemporaryDirectory() as directory:
        generated_dir = Path(directory)
        status = protoc.main([
            'protoc',
            f'--proto_path={schema_dir}',
            f'--proto_path={Path(grpc_tools.__file__).parent / "_proto"}',
            f'--python_out={generated_dir}',
            *(schema.relative_to(schema_dir).as_posix() for schema in schemas),
        ])
        if status:
            return status
        for schema in schemas:
            relative = schema.relative_to(schema_dir).with_name(f'{schema.stem}_pb2.py')
            generated = generated_dir / relative
            module_name = '.'.join((output_dir.name, *relative.with_suffix('').parts))
            source = qualify_generated_modules(generated.read_text(encoding='utf-8'), module_name)
            destination = output_dir / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(source, encoding='utf-8', newline='\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
