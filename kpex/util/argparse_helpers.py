#! /usr/bin/env python3

import argparse
from enum import Enum
from typing import *


def render_enum_help(topic: str,
                     enum_cls: Type[Enum],
                     print_default: bool = True) -> str:
    if not hasattr(enum_cls, 'DEFAULT'):
        raise ValueError("Enum must declare case 'DEFAULT'")
    enum_help = f"{topic} ∈ {set([name.lower() for name, member in enum_cls.__members__.items()])}"
    if print_default:
        enum_help += f".\nDefaults to '{enum_cls.DEFAULT.name.lower()}'"
    return enum_help


def true_or_false(arg) -> bool:
    if isinstance(arg, bool):
        return arg

    match str(arg).lower():
        case 'yes' | 'true' | 't' | 'y' | 1:
            return True
        case 'no' | 'false' | 'f' | 'n' | 0:
            return False
        case _:
            raise argparse.ArgumentTypeError('Boolean value expected.')
