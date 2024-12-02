#! /usr/bin/env python3

from typing import *
from dataclasses import dataclass
from enum import Enum
import io
from fastercap_file_format_pb2 import *


"""
Callback to get a file stream for a given file name
"""
FasterCapFileProvider = Callable[[str], TextIO]


class FasterCapSubFileStrategy(Enum):
    INLINE = 'inline'  # single file with inline conductor/dielectric files
    MULTI_FILE = 'multi_file'    # multiple files with separate conductor/dielectric files


@dataclass
class FasterCapFileWriter:
    @staticmethod
    def _to_s(vector: Vector3D) -> str:
        return f"{vector.x} {vector.y} {vector.z}"

    def _resolve_panel_oneof(self,
                             panel: Union[QuadrilateralPanel3D,
                                          TriangularPanel3D]) -> Tuple[str, str]:
        conductor_name: str
        ref_point: str
        oneof_kind = panel.WhichOneof('either_conductor_or_dielectric')
        match oneof_kind:
            case 'conductor_name':
                conductor_name = panel.conductor_name
                ref_point = ""
            case 'dielectric_reference_point':
                conductor_name = "__dielectric__"
                ref_point = self._to_s(panel.dielectric_reference_point)
            case _:
                raise ValueError(f"Unexpected oneof kind: {oneof_kind}")
        return conductor_name, ref_point

    def write_3d_file(self,
                      input_file: InputFile3D,
                      file_provider: FasterCapFileProvider,
                      sub_file_strategy: FasterCapSubFileStrategy):
        with file_provider(input_file.file_name) as lst_file:
            self._write_3d_file(input_file=input_file,
                                output_file=lst_file)

            match sub_file_strategy:
                case FasterCapSubFileStrategy.INLINE:
                    print(f"End\n",
                          file=lst_file)
                    pass
                case FasterCapSubFileStrategy.MULTI_FILE:
                    pass

            for sub_input_file in input_file.sub_input_files:
                match sub_file_strategy:
                    case FasterCapSubFileStrategy.INLINE:
                        print(f"File {sub_input_file.file_name}",
                              file=lst_file)
                        self._write_3d_file(input_file=sub_input_file,
                                            output_file=lst_file)
                        print(f"End\n",
                              file=lst_file)

                    case FasterCapSubFileStrategy.MULTI_FILE:
                        with file_provider(sub_input_file.file_name) as sub_file:
                            self._write_3d_file(input_file=sub_input_file,
                                                output_file=sub_file)

    def _write_3d_file(self,
                       input_file: InputFile3D,
                       output_file: TextIO):
        for line in input_file.lines:
            match line.WhichOneof('kind'):
                case 'comment':
                    msg = line.comment.message
                    if len(msg) >= 1:
                        msg = f"* {msg}"
                    print(msg, file=output_file)

                case 'conductor':
                    conductor = line.conductor
                    print(f"C {conductor.file_name}   "
                          f"{conductor.relative_permittivity}   "
                          f"{self._to_s(conductor.offset_in_space)} ",
                          file=output_file, end='')
                    print("+" if conductor.merge_with_next else "",
                          file=output_file)

                case 'dielectric':
                    dielectric = line.dielectric
                    print(f"D {dielectric.file_name}   "
                          f"{dielectric.out_permittivity}   "
                          f"{dielectric.in_permittivity}   "
                          f"{self._to_s(dielectric.offset_in_space)}   "
                          f"{self._to_s(dielectric.reference_point)} "
                          "-" if dielectric.reference_lies_on_in_permittivity else "",
                          file=output_file)

                case 'quadrilateral_panel':
                    q = line.quadrilateral_panel
                    name, ref_point = self._resolve_panel_oneof(q)

                    print(f"Q {name}   "
                          f"{self._to_s(q.point_0)}   "
                          f"{self._to_s(q.point_1)}   "
                          f"{self._to_s(q.point_2)}   "
                          f"{self._to_s(q.point_3)}   "
                          f"{ref_point}",
                          file=output_file)

                case 'triangular_panel':
                    t = line.triangular_panel
                    name, ref_point = self._resolve_panel_oneof(t)

                    print(f"T {name}   "
                          f"{self._to_s(t.point_0)}   "
                          f"{self._to_s(t.point_1)}   "
                          f"{self._to_s(t.point_2)}   "
                          f"{ref_point}",
                          file=output_file)

                case 'conductor_rename_event':
                    re = line.conductor_rename_event
                    print(f"N {re.old_name} {re.new_name}",
                          file=output_file)

