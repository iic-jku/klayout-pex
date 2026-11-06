#
# --------------------------------------------------------------------------------
# SPDX-FileCopyrightText: 2024-2026 Martin Jan Köhler and Harald Pretl
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

"""
The peak memory of a run as resident set size, to size the next run on a larger layout (#409):
of this process, and of its largest subprocess that has ended (e.g. KLayout's LVS, FasterCap)
"""

from __future__ import annotations

from dataclasses import dataclass
import sys
from typing import *

from ..log import info


@dataclass(frozen=True)
class PeakMemory:
    process: int  # bytes

    # bytes, 0 before one has ended, None where the platform doesn't tell (Windows),
    # NOTE: on Linux at least the resident set size of this process when it started it, which Linux carries over
    largest_subprocess: Optional[int]


def _windows_peak_working_set() -> int:
    """
    :return: the peak working set of this process in bytes, the resident set size of Windows
    """
    import ctypes
    from ctypes import wintypes

    class ProcessMemoryCounters(ctypes.Structure):
        _fields_ = [('cb', wintypes.DWORD),
                    ('PageFaultCount', wintypes.DWORD),
                    ('PeakWorkingSetSize', ctypes.c_size_t),
                    ('WorkingSetSize', ctypes.c_size_t),
                    ('QuotaPeakPagedPoolUsage', ctypes.c_size_t),
                    ('QuotaPagedPoolUsage', ctypes.c_size_t),
                    ('QuotaPeakNonPagedPoolUsage', ctypes.c_size_t),
                    ('QuotaNonPagedPoolUsage', ctypes.c_size_t),
                    ('PagefileUsage', ctypes.c_size_t),
                    ('PeakPagefileUsage', ctypes.c_size_t)]

    # NOTE: a kernel32 of its own, as the types set on the functions of ctypes.windll.kernel32 would apply to all users
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    get_process_memory_info = kernel32.K32GetProcessMemoryInfo
    get_process_memory_info.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessMemoryCounters), wintypes.DWORD]
    get_process_memory_info.restype = wintypes.BOOL
    counters = ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    if not get_process_memory_info(kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
        raise ctypes.WinError(ctypes.get_last_error())
    return counters.PeakWorkingSetSize


def _linux_peak_resident_set_size() -> Optional[int]:
    """
    :return: the peak resident set size of this process in bytes (VmHWM), None without /proc

    NOTE: not ru_maxrss, which Linux carries over from what the process ran before exec,
          e.g. from the large process that started it (a test runner of 1.4 GiB)
    """
    try:
        with open('/proc/self/status', encoding='utf-8') as f:
            sizes = [int(line.split()[1]) * 1024 for line in f if line.startswith('VmHWM:')]  # NOTE: in kB
    except OSError:
        return None
    return sizes[0] if sizes else None


def peak_memory() -> PeakMemory:
    """
    :return: the peak resident set sizes so far
    """
    if sys.platform == 'win32':
        return PeakMemory(process=_windows_peak_working_set(), largest_subprocess=None)
    import resource
    unit = 1 if sys.platform == 'darwin' else 1024  # NOTE: ru_maxrss is in bytes on macOS, in KiB on Linux
    process = _linux_peak_resident_set_size() if sys.platform.startswith('linux') else None
    return PeakMemory(process=process or resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * unit,
                      largest_subprocess=resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss * unit)


def format_bytes(size: int) -> str:
    """
    :return: e.g. '512 B', '245.3 MiB', '5.7 GiB'
    """
    for unit, scale in (('GiB', 1 << 30), ('MiB', 1 << 20), ('KiB', 1 << 10)):
        if size >= scale:
            return f"{size / scale:.1f} {unit}"
    return f"{size} B"


def log_peak_memory(stage: str):
    """
    Logs the peak memory so far, e.g. 'Peak memory (resident set size) after FasterCap: 245.3 MiB,
    largest subprocess 5.7 GiB', the subprocess only if it is the larger one, as on Linux a smaller one
    may be the size of this process when it started the subprocess (see PeakMemory)

    :param stage: of the run, e.g. 'FasterCap'
    """
    memory = peak_memory()
    subprocess = f", largest subprocess {format_bytes(memory.largest_subprocess)}" \
                 if memory.largest_subprocess and memory.largest_subprocess > memory.process else ''
    info(f"Peak memory (resident set size) after {stage}: {format_bytes(memory.process)}{subprocess}",
         stacklevel=3)  # NOTE: logged as of the caller, the stage
