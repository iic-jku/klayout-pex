#! /usr/bin/env python3

import psutil
import sys

def get_memory_usage(pid: int) -> int:
    process = psutil.Process(pid)
    mem = process.memory_info()
    mem_kb = mem.vms / 1024
    return mem_kb

def main():
    if len(sys.argv) != 2:
         print(f"Usage: {sys.argv[0]} <pid>")
         sys.exit(1)

    pid: int
    try:
        pid = int(sys.argv[1])
    except ValueError:
        print(f"ERROR: could not parse pid {sys.argv[1]}")
        sys.exit(2)

    mem_kb = get_memory_usage(pid)
    print(f" total           {round(mem_kb)}K")

if __name__ == '__main__':
    main()

