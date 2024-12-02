"""
The Logging Module
------------------

kpex logging handler,
implemented using the ``logging`` and ``rich`` libraries.
"""

from .logger import (
    LogLevel,
    set_log_level,
    console,
    debug,
    info,
    warning,
    error
)