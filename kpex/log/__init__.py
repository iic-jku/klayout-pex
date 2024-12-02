"""
The Logging Module
------------------

kpex log handler,
implemented using the ``log`` and ``rich`` libraries.
"""

from .logger import (
    LogLevel,
    set_log_level,
    register_additional_handler,
    deregister_additional_handler,
    console,
    debug,
    rule,
    subproc,
    info,
    warning,
    error
)