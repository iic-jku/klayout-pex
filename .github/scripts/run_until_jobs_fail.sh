#! /bin/bash
##
## --------------------------------------------------------------------------------
## SPDX-FileCopyrightText: 2024-2026 Martin Jan Köhler and Harald Pretl
## Johannes Kepler University, Institute for Integrated Circuits.
##
## This file is part of KPEX
## (see https://github.com/iic-jku/kpex).
##
## This program is free software: you can redistribute it and/or modify
## it under the terms of the GNU General Public License as published by
## the Free Software Foundation, either version 3 of the License, or
## (at your option) any later version.
##
## This program is distributed in the hope that it will be useful,
## but WITHOUT ANY WARRANTY; without even the implied warranty of
## MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
## GNU General Public License for more details.
##
## You should have received a copy of the GNU General Public License
## along with this program. If not, see <http://www.gnu.org/licenses/>.
## SPDX-License-Identifier: GPL-3.0-or-later
## --------------------------------------------------------------------------------
##

# Usage: run_until_jobs_fail.sh JOB_NAME_PREFIX COMMAND [ARGUMENT...]
#
# Runs COMMAND, and interrupts it once a job of this workflow run attempt whose name starts
# with JOB_NAME_PREFIX has failed, e.g. the slow tests once a unit test job has failed.
# GitHub cancels only whole runs, which would also cancel the jobs publishing the reports.
#
# Exits with the status of COMMAND, or 1 if it was interrupted. Checks every
# POLL_INTERVAL_SECONDS (default 30) with gh, which needs GH_TOKEN with actions: read.
# A failed check leaves COMMAND running.

if [[ $# -lt 2 ]]
then
    echo "Usage: $0 JOB_NAME_PREFIX COMMAND [ARGUMENT...]" >&2
    exit 2
fi

prefix="$1"
shift
interval="${POLL_INTERVAL_SECONDS:-30}"
jobs_url="repos/$GITHUB_REPOSITORY/actions/runs/$GITHUB_RUN_ID/attempts/$GITHUB_RUN_ATTEMPT/jobs?per_page=100"

# NOTE: job control puts COMMAND in a process group of its own, whose ID is its PID: the interrupt
#       reaches the processes COMMAND starts (poetry, coverage, pytest), but not this script
set -m
"$@" &
command_pid=$!
set +m  # NOTE: the group stays, without job status messages
trap 'kill -INT -- "-$command_pid" 2>/dev/null' INT
trap 'kill -TERM -- "-$command_pid" 2>/dev/null' TERM

while sleep "$interval" && kill -0 "$command_pid" 2>/dev/null
do
    failed=$(gh api "$jobs_url" --jq "[.jobs[] | select((.name | startswith(\"$prefix\"))
                                                     and .conclusion == \"failure\") | .name] | join(\", \")") \
        || failed=''
    if [[ -n "$failed" ]]
    then
        echo "::error::Interrupting, as these jobs failed: $failed"
        kill -INT -- "-$command_pid" 2>/dev/null
        wait "$command_pid"
        # NOTE: until pytest, not just the process started first, has written its results
        while kill -0 -- "-$command_pid" 2>/dev/null
        do
            sleep 1
        done
        exit 1
    fi
done

wait "$command_pid"
