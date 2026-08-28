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
``pex25d`` — the standalone PEX25D format tool.

Deliberately *not* part of ``kpex``. Everything this tool does is format work:
    - validating
    - converting between encodings
    - resolving a file into a scene
    - writing a scene as a solver's native input
    - looking at what is inside
None of it needs a layout, an LVS run, or KLayout — and that is the point.

Another group can install this, check their own custom PEX25D writer against the reference validator,
and never take on the rest of kpex and its dependencies.

*Generating* PEX25D from a layout however need all of that machinery, so it lives in ``kpex pex25d`` instead.
"""

from __future__ import annotations

import argparse
import contextlib
import shlex
import sys
from typing import *

import rich.console
import rich.markdown
import rich.text
from rich_argparse import RichHelpFormatter

from ..log import (
    LogLevel,
    set_log_level,
    info,
    warning,
    error,
    rule,
    subproc,
)
from ..util.argparse_helpers import render_enum_help, true_or_false
from ..version import __version__

from .exporters import ExportError, ExporterOptions, SolverTarget
from .artifact import (
    ArtifactFormat,
    ArtifactKind,
    ArtifactNamingError,
    ArtifactSpec,
    STDIO_PATH,
    infer_artifact_spec,
)
from .protobuf import ProtobufNotGeneratedError
from .reader import ReadError
from .resolver import ResolveError
from .diagnostics import (
    DiagnosticsFormat,
    DiagnosticsReport,
    ExitCode,
    diagnostics_stream,
)


PROGRAM_NAME = "pex25d"


class ArgumentValidationError(Exception):
    pass


EPILOG_MARKDOWN = """
| Exit code | Meaning |
| --------- | ------- |
| 0 | success (warnings do not fail a run unless `--werror` is given) |
| 1 | input is not valid PEX25D |
| 2 | command line is wrong, or an input could not be read |
| 3 | requested operation is not implemented yet |

A path of `-` means stdin for inputs and stdout for outputs. 
When an artifact goes to stdout, diagnostics go to stderr instead, 
so the stream stays a valid PEX25D artifact.

Artifact naming, inferred from the file name and overridable with
`--in_kind` / `--in_format` / `--out_kind` / `--out_format`:

| Name | Holds | Encoding |
| ---- | ----- | -------- |
| `NAME.pex25d` | PEX25DFile | PEX25D text format |
| `NAME.pex25d.pb` | PEX25DFile | binary protobuf |
| `NAME.pex25d.textpb` | PEX25DFile | protobuf text format |
| `NAME.pex25d.scene.pb` | PEX25DScene | binary protobuf |
| `NAME.pex25d.scene.textpb` | PEX25DScene | protobuf text format |

A trailing `.gz` is honoured on any of them. 
There is deliberately no text-format spelling of a scene: 
the text format is the unresolved one, and resolution is not reversible.
"""


def _epilog() -> rich.console.Group:
    return rich.console.Group(
        rich.text.Text('Exit codes and file naming:', style='argparse.groups'),
        rich.markdown.Markdown(EPILOG_MARKDOWN, style='argparse.text')
    )


class Pex25DCLI:
    # ------------------------------------------------------------------ parsing

    @staticmethod
    def _add_special_options(parser: argparse.ArgumentParser) -> None:
        group = parser.add_argument_group("Special Options")
        group.add_argument("--help", "-h", action='help',
                           help="show this help message and exit")
        group.add_argument("--version", "-v", action='version',
                           version=f'{PROGRAM_NAME} {__version__}')
        group.add_argument("--log_level", dest='log_level', default='subprocess',
                           help=render_enum_help(topic='log_level', enum_cls=LogLevel))

    @staticmethod
    def _add_input_argument(parser: argparse.ArgumentParser) -> None:
        parser.add_argument("input_path", type=str, metavar='INPUT',
                            help="Input PEX25D artifact ('-' for stdin)")
        group = parser.add_argument_group("Input Interpretation")
        group.add_argument("--in_kind", dest='in_kind',
                           default=ArtifactKind.AUTO, type=ArtifactKind,
                           choices=list(ArtifactKind),
                           help="Which message the input holds "
                                "(default is '%(default)s', i.e. inferred from the file name)")
        group.add_argument("--in_format", dest='in_format',
                           default=ArtifactFormat.AUTO, type=ArtifactFormat,
                           choices=list(ArtifactFormat),
                           help="How the input is encoded "
                                "(default is '%(default)s', i.e. inferred from the file name)")
        group.add_argument("--with_source_refs", dest='with_source_refs',
                           action='store_true', default=False,
                           help="Record where each record came from while reading the "
                                "text format (default is %(default)s). Useful when an "
                                "INCLUDE tree has been flattened; diagnostics carry "
                                "positions either way.")

    @staticmethod
    def _add_output_arguments(parser: argparse.ArgumentParser,
                              required: bool = True) -> None:
        group = parser.add_argument_group("Output")
        group.add_argument("--output", "-o", dest='output_path',
                           required=required, metavar='PATH',
                           help="Output path ('-' for stdout)")
        group.add_argument("--out_kind", dest='out_kind',
                           default=ArtifactKind.AUTO, type=ArtifactKind,
                           choices=list(ArtifactKind),
                           help="Which message to write "
                                "(default is '%(default)s', i.e. inferred from the file name)")
        group.add_argument("--out_format", dest='out_format',
                           default=ArtifactFormat.AUTO, type=ArtifactFormat,
                           choices=list(ArtifactFormat),
                           help="How to encode the output "
                                "(default is '%(default)s', i.e. inferred from the file name)")
        group.add_argument("--comments", dest='comments',
                           action='store_true', default=False,
                           help="Include the syntax hints from the specification as "
                                "comments (default is %(default)s). Text format only.")

    @staticmethod
    def _add_diagnostics_arguments(parser: argparse.ArgumentParser) -> None:
        group = parser.add_argument_group(
            "Diagnostics",
            description="'json' and 'pb' emit stable PEX25D-Ennnn codes and are the "
                        "supported way to check a PEX25D writer in CI; 'human' output "
                        "is for reading, and its wording is not stable."
        )
        group.add_argument("--diagnostics", dest='diagnostics_format',
                           default=DiagnosticsFormat.DEFAULT, type=DiagnosticsFormat,
                           choices=list(DiagnosticsFormat),
                           help=render_enum_help(topic='diagnostics', enum_cls=DiagnosticsFormat))
        group.add_argument("--diagnostics_out", dest='diagnostics_path', default=None,
                           metavar='PATH',
                           help="Write diagnostics here instead of to the console "
                                "('-' for stdout)")
        group.add_argument("--strict", dest='strict',
                           action='store_true', default=False,
                           help="Also run the geometric tier: ring and box "
                                "wellformedness, hole containment, conductor "
                                "overlap (default is %(default)s)")
        group.add_argument("--werror", dest='warnings_are_errors',
                           action='store_true', default=False,
                           help="Treat warnings as errors for the exit code "
                                "(default is %(default)s)")

    def parse_args(self, arg_list: List[str] = None) -> argparse.Namespace:
        main_parser = argparse.ArgumentParser(
            description=f"{PROGRAM_NAME}: PEX25D format tool for KLayout-PEX",
            prog=PROGRAM_NAME,
            add_help=False,
            formatter_class=RichHelpFormatter,
            epilog=_epilog(),
        )
        self._add_special_options(main_parser)

        subparsers = main_parser.add_subparsers(dest="command", metavar='<subcommand>',
                                                help="Sub-commands help")

        # ---------------------------------------------------------- validate
        parser_validate = subparsers.add_parser(
            "validate",
            help="Check a PEX25D artifact against the reference validator",
            description="Check a PEX25D artifact and report coded diagnostics. "
                        "Exits 1 if the file is invalid, 0 if it is not.",
            add_help=False, formatter_class=RichHelpFormatter)
        parser_validate.add_argument("--help", "-h", action='help',
                                     help="show this help message and exit")
        self._add_input_argument(parser_validate)
        self._add_diagnostics_arguments(parser_validate)

        # ----------------------------------------------------------- convert
        parser_convert = subparsers.add_parser(
            "convert",
            help="Re-encode a PEX25D artifact (text / pb / textpb)",
            description="Change how a PEX25D artifact is encoded, without changing "
                        "what it says. To turn a file into a scene use 'resolve'; to "
                        "leave PEX25D for a solver use 'export'.",
            add_help=False, formatter_class=RichHelpFormatter)
        parser_convert.add_argument("--help", "-h", action='help',
                                    help="show this help message and exit")
        self._add_input_argument(parser_convert)
        self._add_output_arguments(parser_convert)

        # ----------------------------------------------------------- resolve
        parser_resolve = subparsers.add_parser(
            "resolve",
            help="Resolve a PEX25DFile into a PEX25DScene",
            description="Resolve CONNECTS / BETWEEN / WRAPS, flatten wrap depth and "
                        "compute terminal intersections, producing the scene that "
                        "solver adapters consume.",
            add_help=False, formatter_class=RichHelpFormatter)
        parser_resolve.add_argument("--help", "-h", action='help',
                                    help="show this help message and exit")
        self._add_input_argument(parser_resolve)
        self._add_output_arguments(parser_resolve)
        self._add_diagnostics_arguments(parser_resolve)

        # ------------------------------------------------------------ export
        parser_export = subparsers.add_parser(
            "export",
            help="Export a PEX25D scene as a solver's native input files",
            description="Export the scene to an engine's own input format. Does "
                        "not run the engine — that is 'kpex extract'.",
            add_help=False, formatter_class=RichHelpFormatter)
        parser_export.add_argument("--help", "-h", action='help',
                                   help="show this help message and exit")
        self._add_input_argument(parser_export)
        parser_export.add_argument("--to", dest='solver_target', required=True,
                                   type=SolverTarget, choices=list(SolverTarget),
                                   help=render_enum_help(topic='to',
                                                         enum_cls=SolverTarget))
        parser_export.add_argument("--out_dir", dest='output_dir_path', required=True,
                                   help="Directory to export the solver input files into")
        parser_export.add_argument("--prefix", dest='prefix', default='',
                                   help="Prefix for the generated file names "
                                        "(default is the target's own)")
        parser_export.add_argument("--field_margin", dest='field_margin',
                                   type=float, default=8.0, metavar='UM',
                                   help="How far to draw the laterally unbounded "
                                        "materials beyond the geometry, in µm "
                                        "(default is %(default)s). Ignored when the "
                                        "scene carries a DOMAIN_BOX.")
        parser_export.add_argument("--delaunay_amax", dest='delaunay_amax',
                                   type=float, default=0.0, metavar='AREA',
                                   help="Maximum triangle area (default is "
                                        "%(default)s, i.e. unconstrained)")
        parser_export.add_argument("--delaunay_b", dest='delaunay_b',
                                   type=float, default=1.0, metavar='B',
                                   help="Minimum mesh angle as b = 2·sin(angle) "
                                        "(default is %(default)s, i.e. 30 degrees)")
        parser_export.add_argument("--stl", dest='write_stl',
                                   action='store_true', default=False,
                                   help="Also dump the generated solids as STL")
        parser_export.add_argument("--geo_check", dest='geometry_check',
                                   action='store_true', default=False,
                                   help="Validate the geometry before writing")
        self._add_diagnostics_arguments(parser_export)

        # -------------------------------------------------------------- show
        parser_show = subparsers.add_parser(
            "show",
            help="Summarize what is inside a PEX25D artifact",
            description="Print a human-readable summary. For machine consumption use "
                        "'convert --out_format textpb' instead — this output is not stable.",
            add_help=False, formatter_class=RichHelpFormatter)
        parser_show.add_argument("--help", "-h", action='help',
                                 help="show this help message and exit")
        self._add_input_argument(parser_show)
        parser_show.add_argument("--section", dest='sections', action='append',
                                 default=None, metavar='NAME',
                                 choices=['header', 'meta', 'layers', 'dielectrics',
                                          'conductors', 'terminals', 'resistance',
                                          'domain', 'all'],
                                 help="Section to print; repeatable (default is 'all')")

        if arg_list is None:
            arg_list = sys.argv[1:]
        args = main_parser.parse_args(arg_list)

        if args.command is None:
            main_parser.print_help()
            sys.exit(ExitCode.USAGE)

        self.validate_args(args)
        return args

    # --------------------------------------------------------------- validation

    @staticmethod
    def validate_args(args: argparse.Namespace) -> None:
        found_errors = False

        try:
            args.log_level = LogLevel[args.log_level.upper()]
        except KeyError:
            error(f"Requested log level {args.log_level.lower()} does not exist, "
                  f"{render_enum_help(topic='log_level', enum_cls=LogLevel, print_default=False)}")
            found_errors = True

        # Input spec. A scene default for stdin would be wrong:
        # the only thing you can pipe in without a file name to inspect is what another tool wrote,
        # and the format's own serialization is the text file.
        try:
            args.input_spec = infer_artifact_spec(args.input_path,
                                                  kind=args.in_kind,
                                                  format=args.in_format)
        except ArtifactNamingError as e:
            error(str(e))
            found_errors = True

        if hasattr(args, 'output_path') and args.output_path is not None:
            default_kind = ArtifactKind.SCENE if args.command == 'resolve' else ArtifactKind.FILE
            default_format = ArtifactFormat.PB if default_kind == ArtifactKind.SCENE \
                else ArtifactFormat.TEXT
            try:
                args.output_spec = infer_artifact_spec(args.output_path,
                                                       kind=args.out_kind,
                                                       format=args.out_format,
                                                       default_kind=default_kind,
                                                       default_format=default_format)
            except ArtifactNamingError as e:
                error(str(e))
                found_errors = True

            if args.command == 'resolve' and getattr(args, 'output_spec', None) is not None:
                if args.output_spec.kind != ArtifactKind.SCENE:
                    error("'resolve' produces a PEX25DScene; the output path or --out_kind asks for a PEX25DFile.")
                    found_errors = True

        if found_errors:
            raise ArgumentValidationError("Argument validation failed")

    # -------------------------------------------------------------------- verbs

    @staticmethod
    def _load(args: argparse.Namespace, report: DiagnosticsReport) -> Any:
        from .codec import load_artifact
        return load_artifact(args.input_spec, report=report)

    def run_validate(self, args: argparse.Namespace, report: DiagnosticsReport) -> None:
        from .validator import validate
        message = self._load(args, report)
        validate(message, report=report, strict=args.strict)

    def run_convert(self, args: argparse.Namespace, report: DiagnosticsReport) -> None:
        from .codec import load_artifact, save_artifact

        if args.input_spec.kind != args.output_spec.kind:
            raise ArgumentValidationError(
                f"'convert' re-encodes, it does not transform: input is a "
                f"{args.input_spec.kind.value}, output would be a "
                f"{args.output_spec.kind.value}. Use 'resolve' to turn a file into a scene."
            )

        message = load_artifact(args.input_spec, report=report,
                                with_source_refs=args.with_source_refs)
        save_artifact(message, args.output_spec, comments=args.comments)
        if not args.output_spec.is_stdio:
            info(f"Wrote {args.output_spec}")

    def run_resolve(self, args: argparse.Namespace, report: DiagnosticsReport) -> None:
        from .codec import load_artifact, save_artifact
        from .resolver import resolve

        message = load_artifact(args.input_spec, report=report,
                                with_source_refs=args.with_source_refs)
        scene = resolve(message, report=report, strict=args.strict)
        save_artifact(scene, args.output_spec, comments=args.comments)
        if not args.output_spec.is_stdio:
            info(f"Wrote {args.output_spec}")

    def run_export(self, args: argparse.Namespace, report: DiagnosticsReport) -> None:
        from .exporters import export
        from .codec import load_artifact
        from .resolver import resolve

        message = load_artifact(args.input_spec, report=report,
                                with_source_refs=args.with_source_refs)
        if args.input_spec.kind == ArtifactKind.FILE:
            info("Input is an unresolved PEX25DFile, resolving it first")
            message = resolve(message, report=report, strict=args.strict)

        written = export(message,
                         target=args.solver_target,
                         output_dir_path=args.output_dir_path,
                         prefix=args.prefix)
        for path in written:
            subproc(path)
        info(f"Wrote {len(written)} {args.solver_target.value} input file(s) to {args.output_dir_path}")

    def run_show(self, args: argparse.Namespace, report: DiagnosticsReport) -> None:
        from .codec import load_artifact
        from .show import show

        message = load_artifact(args.input_spec, report=report,
                                with_source_refs=args.with_source_refs)
        show(message, kind=args.input_spec.kind, sections=args.sections or ['all'])

    # --------------------------------------------------------------------- main

    def main(self, argv: List[str]) -> None:
        try:
            args = self.parse_args(argv[1:])
        except ArgumentValidationError:
            sys.exit(ExitCode.USAGE)

        set_log_level(args.log_level)

        # When the artifact goes to stdout, stdout belongs to the artifact and to
        # nothing else — one stray log line and the consumer of the pipe is parsing garbage.
        # Redirecting sys.stdout to stderr for the whole run is therefore necessary:
        # the rich console resolves sys.stdout at write time, so every info()/rule()/warning() follows,
        # including ones written by code that never considered being in a pipeline.
        # The artifact I/O itself uses sys.__stdout__ and is unaffected.
        output_spec: Optional[ArtifactSpec] = getattr(args, 'output_spec', None)
        artifact_on_stdout = output_spec is not None and output_spec.is_stdio

        with contextlib.ExitStack() as stack:
            if artifact_on_stdout:
                stack.enter_context(contextlib.redirect_stdout(sys.stderr))
            self._run(args)

    def _run(self, args: argparse.Namespace) -> None:
        if args.input_spec.path != STDIO_PATH:
            rule('Command line arguments')
            subproc(' '.join(map(shlex.quote, sys.argv)))

        report = DiagnosticsReport(
            warnings_are_errors=getattr(args, 'warnings_are_errors', False))

        handler = {
            'validate': self.run_validate,
            'convert': self.run_convert,
            'resolve': self.run_resolve,
            'export': self.run_export,
            'show': self.run_show,
        }[args.command]

        try:
            handler(args, report)
        except NotImplementedError as e:
            error(str(e))
            sys.exit(ExitCode.NOT_IMPLEMENTED)
        except ArgumentValidationError as e:
            error(str(e))
            sys.exit(ExitCode.USAGE)
        except ExportError as e:
            error(str(e))
            sys.exit(ExitCode.USAGE)
        except (ReadError, ResolveError) as e:
            error(str(e))
            self._emit_diagnostics(args, report)
            sys.exit(ExitCode.DIAGNOSTIC_ERRORS)
        except ProtobufNotGeneratedError as e:
            error(str(e))
            sys.exit(ExitCode.USAGE)
        except (OSError, ValueError) as e:
            error(f"Failed to process {args.input_spec}: {e}")
            sys.exit(ExitCode.USAGE)

        self._emit_diagnostics(args, report)
        sys.exit(report.exit_code)

    @staticmethod
    def _emit_diagnostics(args: argparse.Namespace,
                          report: DiagnosticsReport) -> None:
        diagnostics_format: DiagnosticsFormat = getattr(
            args, 'diagnostics_format', DiagnosticsFormat.HUMAN)

        output_spec: Optional[ArtifactSpec] = getattr(args, 'output_spec', None)
        artifact_on_stdout = output_spec is not None and output_spec.is_stdio

        diagnostics_path: Optional[str] = getattr(args, 'diagnostics_path', None)
        if diagnostics_path is not None and diagnostics_path != STDIO_PATH:
            mode = 'wb' if diagnostics_format == DiagnosticsFormat.PB else 'w'
            with open(diagnostics_path, mode) as f:
                report.render(diagnostics_format, stream=f)
            return

        if diagnostics_format == DiagnosticsFormat.HUMAN:
            # 'validate' answers with its diagnostics, so an explicit "none" is the
            # result. For the other verbs a clean run should simply be quiet.
            if report.diagnostics or args.command == 'validate':
                report.render(diagnostics_format)
            return

        with diagnostics_stream(writes_to_stdout=artifact_on_stdout) as stream:
            report.render(diagnostics_format, stream=stream)
