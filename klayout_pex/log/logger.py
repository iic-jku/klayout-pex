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
from __future__ import annotations
from enum import IntEnum
from functools import cached_property
import logging
import rich.console
import rich.logging
from typing import *


class LogLevel(IntEnum):
    ALL = 0
    DEBUG = 10
    SUBPROCESS = 12
    VERBOSE = 15
    INFO = 20
    WARNING = 30
    ERROR = 40
    CRITICAL = 50
    DEFAULT = SUBPROCESS

    @classmethod
    @cached_property
    def level_by_name(cls) -> Dict[str, LogLevel]:
        return {e.name: e for e in cls}


class LogLevelFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        msg = record.getMessage()
        match record.levelno:
            case LogLevel.WARNING.value: return f"[yellow]{msg}"
            case LogLevel.ERROR.value: return f"[red]{msg}"
            case _:
                return msg


class LogLevelFilter(logging.Filter):
    def __init__(self, levels: Iterable[str], invert: bool = False):
        super().__init__()
        self.levels = levels
        self.invert = invert

    def filter(self, record: logging.LogRecord) -> bool:
        if self.invert:
            return record.levelname not in self.levels
        else:
            return record.levelname in self.levels


console = rich.console.Console()
__logger = logging.getLogger("__kpex__")


def set_log_level(log_level: LogLevel):
    __logger.setLevel(log_level)


def get_log_level() -> LogLevel:
    return LogLevel(__logger.level)


def register_additional_handler(handler: logging.Handler):
    """
    Adds a new handler to the default logger.

    :param handler: The new handler. Must be of type ``logging.Handler``
        or its subclasses.
    """
    __logger.addHandler(handler)


def deregister_additional_handler(handler: logging.Handler):
    """
    Removes a registered handler from the default logger.

    :param handler: The handler. If not registered, the behavior
        of this function is undefined.
    """
    __logger.removeHandler(handler)



def configure_logger():
    global __logger, console

    for level in LogLevel:
        logging.addLevelName(level=level.value, levelName=level.name)

    subprocess_rich_handler = rich.logging.RichHandler(
        console=console,
        show_time=False,
        omit_repeated_times=False,
        show_level=False,
        show_path=False,
        enable_link_path=False,
        markup=False,
        tracebacks_word_wrap=False,
        keywords=[]
    )
    subprocess_rich_handler.addFilter(LogLevelFilter(['SUBPROCESS']))

    rich_handler = rich.logging.RichHandler(
        console=console,
        omit_repeated_times=False,
        show_level=True,
        markup=True,
        rich_tracebacks=True,
        tracebacks_suppress=[],
        keywords=[]
    )

    rich_handler.setFormatter(LogLevelFormatter(fmt='%(message)s', datefmt='[%X]'))
    rich_handler.addFilter(LogLevelFilter(['SUBPROCESS'], invert=True))

    set_log_level(LogLevel.SUBPROCESS)

    __logger.handlers.clear()
    __logger.addHandler(subprocess_rich_handler)
    __logger.addHandler(rich_handler)


def debug(*args, **kwargs):
    if not kwargs.get('stacklevel'):  # ensure logged file location is correct
        kwargs['stacklevel'] = 2
    __logger.debug(*args, **kwargs)


def subproc(msg: object, **kwargs):
    if not kwargs.get('stacklevel'):  # ensure logged file location is correct
        kwargs['stacklevel'] = 2
    __logger.log(LogLevel.SUBPROCESS, msg, **kwargs)


def rule(title: str = '', **kwargs):  # pragma: no cover
    """
    Prints a horizontal line on the terminal enclosing the first argument
    if the log level is <= INFO.

    Kwargs are passed to https://rich.readthedocs.io/en/stable/reference/console.html#rich.console.Console.rule

    :param title: A title string to enclose in the console rule
    """
    console.rule(title)


def info(*args, **kwargs):
    if not kwargs.get('stacklevel'):  # ensure logged file location is correct
        kwargs['stacklevel'] = 2
    __logger.info(*args, **kwargs)


def warning(*args, **kwargs):
    if not kwargs.get('stacklevel'):  # ensure logged file location is correct
        kwargs['stacklevel'] = 2
    __logger.warning(*args, **kwargs)


def error(*args, **kwargs):
    if not kwargs.get('stacklevel'):  # ensure logged file location is correct
        kwargs['stacklevel'] = 2
    __logger.error(*args, **kwargs)


configure_logger()
