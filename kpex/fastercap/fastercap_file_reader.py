#! /usr/bin/env python3

from typing import *
import os.path
import sys

from fastercap_file_format_pb2 import *
from .fastercap_file_writer import FasterCapFileProvider


class FasterCapFileReader:
    def read_3d_file(self,
                     input_file_name: str,
                     file_provider: FasterCapFileProvider) -> InputFile3D:
        with file_provider(input_file_name) as input_stream:
            for line in input_stream.readlines():
                pass
        raise NotImplementedError


def main():
    fc_input_path = sys.argv[1]
    fc_input_filename = os.path.basename(fc_input_path)
    fc_input_dir = os.path.dirname(fc_input_path)

    def provide_fastcap_file(name: str) -> TextIO:
        path = os.path.join(fc_input_dir, name)
        textio = open(path, mode="r")
        return textio

    reader = FasterCapFileReader()
    reader.read_3d_file(input_file_name=fc_input_filename,
                        file_provider=provide_fastcap_file)


if __name__ == '__main__':
    main()
