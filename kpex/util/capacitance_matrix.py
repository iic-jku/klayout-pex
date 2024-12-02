from typing import *
from dataclasses import dataclass


@dataclass
class CapacitanceMatrix:
    conductor_names: List[str]
    rows: List[List[float]]
