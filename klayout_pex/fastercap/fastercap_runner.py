#
# --------------------------------------------------------------------------------
# SPDX-FileCopyrightText: 2024-2025 Martin Jan Köhler and Harald Pretl
# Johannes Kepler University, Institute for Integrated Circuits.
#
# This file is part of KPEX 
# (see https://github.com/iic-jku/kpex).
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
from dataclasses import dataclass
import math
import os
import signal
from numbers import Real
import re
import subprocess
import sys
import threading
import time
from typing import *

from ..log import (
    info,
    # warning,
    rule,
    subproc,
)
from ..common.capacitance_matrix import CapacitanceMatrix
from .fastercap_error import FasterCapError, FasterCapExecutionError, FasterCapTimeoutError, FasterCapCancelledError


# NOTE: the exit codes of FasterCap 6.2 (see the README of iic-jku/FasterCap), earlier versions exit 0 or 1.
#       75 fails the run too, as the matrix it prints, the one of the last iteration, misses the tolerance
FASTERCAP_EXIT_CODE_MEANINGS: Dict[int, str] = {
    1: "other error",
    64: "wrong command line",
    65: "the matrix has NaN or infinite entries",
    66: "the input file can't be opened",
    71: "out of memory",
    74: "the input can't be read",
    75: "GMRES didn't converge",
    97: "the run can't go out-of-core",
    98: "unexpected exception",
    125: "stopped, e.g. by Ctrl-C or SIGTERM",
}


@dataclass(frozen=True)
class FasterCapRunResult:
    arguments: Tuple[str, ...]
    returncode: Optional[int]
    duration_seconds: float
    report_path: Optional[str] = None


def _stop_process(proc: subprocess.Popen, *, include_exited_group: bool = False):
    """Stop the owned process group, including non-detached solver children."""
    if proc.poll() is not None and not include_exited_group:
        proc.wait()
        return
    if os.name == 'posix':
        try:
            os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(timeout=0.2)
            except subprocess.TimeoutExpired:
                pass
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except PermissionError:
            # Darwin's killpg excludes zombies and can return EPERM when only
            # exited members remain (xnu/bsd/kern/kern_sig.c, killpg1). The
            # group belongs to this child; never suppress denial for a live
            # leader, or apply this Darwin teardown rule on other platforms.
            if sys.platform != 'darwin' or proc.poll() is None:
                raise
    elif proc.poll() is None:
        # Windows has no POSIX process groups. taskkill /T terminates descendants.
        subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'],
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=5, check=False)
        if proc.poll() is None:
            proc.kill()
    proc.wait()


def _positive_finite(value: float, name: str):
    try:
        valid = (not isinstance(value, bool) and isinstance(value, Real)
                 and math.isfinite(value) and value > 0)
    except OverflowError:
        valid = False
    if not valid:
        raise FasterCapError(f'{name} must be finite and greater than zero')


def run_fastercap(exe_path: str,
                  lst_file_path: str,
                  log_path: str,
                  tolerance: Optional[float],
                  d_coeff: float,
                  ooc_condition: Optional[int],
                  auto_preconditioner: bool,
                  galerkin_scheme: bool,
                  jacobi_preconditioner: bool,
                  *,
                  timeout_seconds: Optional[float] = None,
                  cwd: Optional[str] = None,
                  env: Optional[Mapping[str, str]] = None,
                  mesh_refinement: Optional[float] = None,
                  gmres_tolerance: Optional[float] = None,
                  cancel_event: Optional[threading.Event] = None,
                  report_path: Optional[str] = None) -> FasterCapRunResult:
    """Run and stream FasterCap, retaining the log on errors and timeouts.

    ``env`` is a complete child environment, as for ``subprocess.Popen``. A
    caller can copy its environment and set per-run thread limits without
    modifying other concurrent runs. Cancellation and deadlines stop the owned
    process tree. ``exe_path`` must not detach children into separate sessions.

    Automatic refinement uses ``tolerance`` and couples mesh and GMRES settings.
    To control them independently, pass ``tolerance=None`` and set both
    ``mesh_refinement`` and ``gmres_tolerance``. Mixing the modes is an error:
    FasterCap silently overrides manual controls when ``-a`` is present.
    """
    if '"' in lst_file_path:
        raise FasterCapError('Input path cannot contain double quotes')
    if report_path is not None:
        if not isinstance(report_path, str) or not report_path or '"' in report_path:
            raise FasterCapError('report_path must be a nonempty path without double quotes')
        report_path = os.path.abspath(os.path.join(cwd or os.getcwd(), report_path))
        if os.path.lexists(report_path):
            raise FasterCapError(f"Numerical report already exists: {report_path}")
        if report_path == os.path.abspath(log_path):
            raise FasterCapError('Numerical report and console log must have different paths')
    if timeout_seconds is not None:
        _positive_finite(timeout_seconds, 'timeout_seconds')
        if timeout_seconds > threading.TIMEOUT_MAX:
            raise FasterCapError(f'timeout_seconds must not exceed {threading.TIMEOUT_MAX:g} on this platform')
    if tolerance is None:
        if mesh_refinement is None or gmres_tolerance is None:
            raise FasterCapError('Manual refinement requires both mesh_refinement and gmres_tolerance')
        _positive_finite(mesh_refinement, 'mesh_refinement')
        _positive_finite(gmres_tolerance, 'gmres_tolerance')
        refinement_args = [f'-m{mesh_refinement}', f'-t{gmres_tolerance}']
    else:
        if mesh_refinement is not None or gmres_tolerance is not None:
            raise FasterCapError('Automatic tolerance cannot be combined with manual refinement controls')
        _positive_finite(tolerance, 'tolerance')
        refinement_args = [f'-a{tolerance}']
    args = [
        exe_path,
        '-b',                          # console mode, without GUI
        '-i',                          # Dump detailed time and memory information
        '-v',                          # Verbose output
        *refinement_args,
        f"-d{d_coeff}",                # Direct potential interaction coefficient to mesh refinement ratio
    ]

    if ooc_condition is not None:
        args += [f"-f{ooc_condition}"]
    
    if auto_preconditioner:
        args += ['-ap']

    if galerkin_scheme:
        args += ['-g']

    if jacobi_preconditioner:
        args += ['-pj']

    if report_path is not None:
        args += [f'--report={report_path}']
    # FasterCap joins argv and tokenizes it again. Literal quotes are required
    # inside this argument to preserve whitespace; subprocess still uses no shell.
    input_argument = f'"{lst_file_path}"' if any(c.isspace() for c in lst_file_path) else lst_file_path
    args += [input_argument]
    info(f"Calling FasterCap")
    subproc(f"{' '.join(args)}, output file: {log_path}")

    rule('FasterCap Output')
    start = time.monotonic()
    timed_out = threading.Event()
    cancelled = threading.Event()
    finished = threading.Event()
    watchdog: Optional[threading.Thread] = None

    # Open the log first: an unwritable log must not leave a running solver.
    try:
        log_file = open(log_path, 'w', encoding='utf-8')
    except OSError as exc:
        result = FasterCapRunResult(tuple(args), None, time.monotonic() - start,
                                        report_path if report_path and os.path.isfile(report_path) else None)
        raise FasterCapExecutionError(f'Could not open FasterCap log: {exc}', result=result) from exc
    proc: Optional[subprocess.Popen] = None
    try:
        with log_file as f:
            try:
                proc = subprocess.Popen(args,
                                        stdin=subprocess.DEVNULL,
                                        stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT,
                                        text=True,
                                        encoding='utf-8',
                                        errors='replace',
                                        cwd=cwd,
                                        env=env,
                                        start_new_session=os.name == 'posix')
            except OSError as exc:
                result = FasterCapRunResult(tuple(args), None, time.monotonic() - start,
                                        report_path if report_path and os.path.isfile(report_path) else None)
                raise FasterCapExecutionError(f'Could not start FasterCap: {exc}', result=result) from exc

            def watch_process():
                while not finished.wait(0.02):
                    if cancel_event is not None and cancel_event.is_set():
                        cancelled.set()
                        _stop_process(proc, include_exited_group=True)
                        return
                    if timeout_seconds is not None and time.monotonic() - start >= timeout_seconds:
                        timed_out.set()
                        _stop_process(proc, include_exited_group=True)
                        return

            try:
                if timeout_seconds is not None or cancel_event is not None:
                    watchdog = threading.Thread(target=watch_process, daemon=True)
                    watchdog.start()
                while True:
                    line = proc.stdout.readline()
                    if not line:
                        break
                    f.write(line)
                    f.flush()
                    subproc(line.rstrip('\r\n'))
                proc.wait()
            finally:
                finished.set()
                if watchdog is not None and watchdog.ident is not None:
                    watchdog.join()
                try:
                    _stop_process(proc)
                finally:
                    proc.stdout.close()
    except OSError as exc:
        result = FasterCapRunResult(tuple(args), proc.returncode if proc is not None else None,
                                    time.monotonic() - start,
                                    report_path if report_path and os.path.isfile(report_path) else None)
        raise FasterCapExecutionError(f'Could not capture FasterCap output: {exc}', result=result) from exc

    duration = time.monotonic() - start
    result = FasterCapRunResult(tuple(args), proc.returncode, duration,
                                report_path if report_path and os.path.isfile(report_path) else None)

    rule()

    if cancelled.is_set():
        raise FasterCapCancelledError(f'FasterCap cancelled, see log file: {log_path}', result=result)
    if timed_out.is_set():
        raise FasterCapTimeoutError(
            f'FasterCap exceeded timeout of {timeout_seconds:g}s after {duration:.4g}s, '
            f'see log file: {log_path}', result=result)
    if proc.returncode == 0:
        info(f"FasterCap succeeded after {'%.4g' % duration}s")
    else:
        meaning = FASTERCAP_EXIT_CODE_MEANINGS.get(proc.returncode, None)
        raise FasterCapExecutionError(f"FasterCap failed with exit code {proc.returncode}"
                                      f"{f' ({meaning})' if meaning else ''} after {'%.4g' % duration}s, "
                                      f"see log file: {log_path}", result=result)
    return result


def fastercap_parse_capacitance_matrix(log_path: str) -> CapacitanceMatrix:
    """Read the final complete square matrix; preserve native labels and signs."""
    try:
        with open(log_path, 'r', encoding='utf-8') as stream:
            lines = stream.read().splitlines()
        starts = [i for i, line in enumerate(lines) if line.strip() == 'Capacitance matrix is:']
        if not starts:
            raise ValueError('no capacitance matrix')
        start = starts[-1]
        dimensions = re.fullmatch(r'Dimension (\d+) x (\d+)', lines[start + 1].strip())
        if dimensions is None:
            raise ValueError('invalid matrix dimensions')
        count, columns = map(int, dimensions.groups())
        if count <= 0 or count != columns or start + count + 2 > len(lines):
            raise ValueError('incomplete or nonsquare matrix')
        names: List[str] = []
        rows: List[List[float]] = []
        for line in lines[start + 2:start + 2 + count]:
            cells = line.split()
            if len(cells) != count + 1 or cells[0] in names:
                raise ValueError('invalid matrix row or repeated conductor label')
            names.append(cells[0])
            raw = [float(value) for value in cells[1:]]
            values = [value / 1e6 for value in raw]
            if any(value != 0 and scaled == 0 for value, scaled in zip(raw, values)):
                raise ValueError('matrix unit conversion underflows')
            if any(not math.isfinite(value) for value in values):
                raise ValueError('nonfinite matrix entry')
            rows.append(values)
        if any(line.startswith('Iteration number #') for line in lines[start + 2 + count:]):
            raise ValueError('unfinished iteration after final matrix')
        return CapacitanceMatrix(conductor_names=names, rows=rows)
    except (OSError, ValueError, IndexError) as exc:
        raise FasterCapError(f"Could not extract capacitance matrix from FasterCap log '{log_path}': {exc}") from exc
