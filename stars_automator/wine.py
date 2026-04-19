"""
Wine and Xvfb helpers shared across all automation scripts.
"""

import os
import subprocess
import time

from stars_automator._cli import die
from stars_automator.config import DEFAULT_DISPLAY, DEFAULT_WINEPREFIX


def make_wine_env(
    display: str = DEFAULT_DISPLAY,
    wineprefix: str = DEFAULT_WINEPREFIX,
) -> dict:
    """Return an os.environ copy with Wine variables set."""
    return {
        **os.environ,
        "WINEPREFIX": wineprefix,
        "WINEARCH": "win32",
        "DISPLAY": display,
    }


def wine_path(linux_path: str, wine_env: dict) -> str:
    """Convert an absolute Linux path to a Windows path via winepath."""
    result = subprocess.run(
        ["winepath", "-w", linux_path],
        env=wine_env,
        capture_output=True,
    )
    if result.returncode != 0:
        die(f"winepath failed for {linux_path!r}: {result.stderr.decode().strip()}")
    return result.stdout.decode().strip()


def ensure_xvfb(display: str) -> "subprocess.Popen | None":
    """
    Start Xvfb on `display` if it is not already running.

    Returns the Popen handle if a new process was started, None if one was
    already running.  The caller is responsible for terminating the process.
    """
    probe = subprocess.run(
        ["xdpyinfo", "-display", display],
        capture_output=True,
    )
    if probe.returncode == 0:
        print(f"  Xvfb already running on {display}")
        return None

    print(f"  Starting Xvfb on {display}…", end=" ", flush=True)
    proc = subprocess.Popen(
        ["Xvfb", display, "-screen", "0", "1024x768x24"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(1)
    probe = subprocess.run(
        ["xdpyinfo", "-display", display],
        capture_output=True,
    )
    if probe.returncode != 0:
        die(f"Xvfb failed to start on {display}")
    print("ok")
    return proc
