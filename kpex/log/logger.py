from enum import IntEnum
import logging
import rich.console
import rich.logging


class LogLevel(IntEnum):
    ALL = logging.NOTSET
    DEBUG = logging.DEBUG
    INFO = logging.INFO
    WARNING = logging.WARNING
    ERROR = logging.ERROR
    DEFAULT = logging.INFO


class LogLevelFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        msg = record.getMessage()
        match record.levelno:
            case LogLevel.WARNING.value: return f"[yellow]{msg}"
            case LogLevel.ERROR.value: return f"[red]{msg}"
            case _:
                return msg


console = rich.console.Console()
__logger = logging.getLogger("__kpex__")


def set_log_level(log_level: LogLevel):
    __logger.setLevel(log_level)


def configure_logger():
    global __logger, console

    for level in LogLevel:
        logging.addLevelName(level=level.value, levelName=level.name)

    rich_handler = rich.logging.RichHandler(
        console=console,
        rich_tracebacks=True,
        omit_repeated_times=False,
        markup=True,
        tracebacks_suppress=[],
        show_level=True,
        keywords=[]
    )
    rich_handler.setFormatter(LogLevelFormatter(fmt='%(message)s', datefmt='[%X]'))
    set_log_level(LogLevel.DEFAULT)
    __logger.handlers.clear()
    __logger.addHandler(rich_handler)


def debug(*args, **kwargs):
    if not kwargs.get('stacklevel'):  # ensure logged file location is correct
        kwargs['stacklevel'] = 2
    __logger.debug(*args, **kwargs)


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