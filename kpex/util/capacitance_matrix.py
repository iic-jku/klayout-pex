from typing import *
from dataclasses import dataclass


@dataclass
class CapacitanceMatrix:
    conductor_names: List[str]
    rows: List[List[float]]   # NOTE: in µm

    def write_csv(self, output_path: str, separator: str = ';'):
        with open(output_path, "w") as f:
            header_line = separator.join(self.conductor_names)
            f.write(header_line)
            f.write('\n')

            for row in self.rows:
                row_line = separator.join('%.12g' % row)
                f.write(row_line)
                f.write('\n')
