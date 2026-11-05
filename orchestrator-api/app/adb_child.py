"""Linux-only ADB launcher: never leave a client running after its worker dies."""

import ctypes
import os
import signal
import sys


def main() -> None:
    expected_parent = int(sys.argv[1])
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0:  # PR_SET_PDEATHSIG
        raise SystemExit("Cannot enforce worker parent-death signal")
    if os.getppid() != expected_parent:
        raise SystemExit("Worker exited before ADB launch")
    os.execvp(sys.argv[2], sys.argv[2:])


if __name__ == "__main__":
    main()
