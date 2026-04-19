"""
stars_automater.py

Functions to launch and manipulate a Stars! game using Wine and xdotool.

The resolutions of windows and mouse positions are shamelessly hard-coded.
Use xprop, xwininfo and xmousepos to get mouse coordinates and resolutions.

:author: Brandon Arrendondo
:license: MIT
"""

import logging
import subprocess
import time

STARS_SPLASH_GEOMETRY = "1600x900"
# STARS_SPLASH_GEOMETRY = "2560x1600"
# STARS_SPLASH_GEOMETRY = "2222x1348"
NEW_GAME_SAVE_GEOMETRY = "413x218"
# STARS_GAME_GEOMETRY = "1535x1161"
STARS_GAME_GEOMETRY = "2540x1569"


class UniverseSize:
    Tiny = 1
    Small = 2
    Medium = 3
    Large = 4
    Huge = 5


class UniverseDensity:
    Sparse = 1
    Normal = 2
    Dense = 3
    Packed = 4


def launch_stars(stars_executable):
    process = subprocess.Popen(["/usr/bin/wine", stars_executable])

    cmd = "xdotool search stars"
    while True:
        try:
            result = subprocess.check_output(cmd, shell=True)
            break
        except subprocess.CalledProcessError:
            logging.warning("Failed to find window. Trying again.")
            time.sleep(1)

    for line in result.splitlines():
        discovered_geometry = get_window_geometry(line)
        logging.debug("Discovered geometry: {0!s}".format(discovered_geometry))
        if discovered_geometry == STARS_SPLASH_GEOMETRY:
            return (True, line, process)

    return (False, None, None)


def get_window_geometry(id):
    cmd = "xdotool getwindowgeometry {0!s}".format(id)
    result = subprocess.check_output(cmd, shell=True)

    for line in result.splitlines():
        actual_line = line.strip()
        if actual_line.startswith("Geometry"):
            geometry = actual_line.replace("Geometry: ", "")
            return geometry


def select_new_game():
    logging.debug("Selecting New Game...")

    cmd = "xdotool mousemove 306 1536 click 1"
    subprocess.check_output(cmd, shell=True)


def select_universe_size(size):
    if size == UniverseSize.Tiny:
        logging.debug("Choosing Tiny universe size.")
        cmd = "xdotool mousemove 1132 810 click 1"
    elif size == UniverseSize.Small:
        logging.debug("Choosing Small universe size.")
        cmd = "xdotool mousemove 1132 830 click 1"
    elif size == UniverseSize.Medium:
        logging.debug("Choosing Medium universe size.")
        cmd = "xdotool mousemove 1132 860 click 1"
    elif size == UniverseSize.Large:
        logging.debug("Choosing Large universe size.")
        cmd = "xdotool mousemove 1132 880 click 1"
    elif size == UniverseSize.Huge:
        logging.debug("Choosing Huge universe size.")
        cmd = "xdotool mousemove 1132 900 click 1"
    else:
        raise Exception("Invalid universe size.")

    subprocess.check_output(cmd, shell=True)


def select_advanced_game():
    logging.debug("Selecting Advanced Game...")

    cmd = "xdotool mousemove 1340 880 click 1"
    subprocess.check_output(cmd, shell=True)


def select_universe_density(density):
    if density == UniverseDensity.Sparse:
        logging.debug("Choosing Sparse universe density.")
        cmd = "xdotool mousemove 1143 865 click 1"
    elif density == UniverseDensity.Normal:
        logging.debug("Choosing Normal universe density.")
        cmd = "xdotool mousemove 1143 890 click 1"
    elif density == UniverseDensity.Dense:
        logging.debug("Choosing Dense universe density.")
        cmd = "xdotool mousemove 1143 905 click 1"
    elif density == UniverseDensity.Packed:
        logging.debug("Choosing Packed universe density.")
        cmd = "xdotool mousemove 1143 925 click 1"
    else:
        raise Exception("Invalid universe density.")

    subprocess.check_output(cmd, shell=True)


def select_finish_advanced_game():
    logging.debug("Selecting Finish...")

    cmd = "xdotool mousemove 1434 972 click 1"
    subprocess.check_output(cmd, shell=True)


def default_ok_new_game():
    cmd = "xdotool search stars"
    result = subprocess.check_output(cmd, shell=True)
    for line in result.splitlines():
        discovered_geometry = get_window_geometry(line)
        logging.debug("Discovered geometry: {0!s}".format(discovered_geometry))
        if discovered_geometry == NEW_GAME_SAVE_GEOMETRY:
            window_id = int(line.strip())
            cmd = "xdotool key Return {0!s}".format(window_id)
            result = subprocess.check_output(cmd, shell=True)
            return

    raise Exception("Could not find new game save window.")


def dump_universe_map():
    cmd = "xdotool search stars"
    result = subprocess.check_output(cmd, shell=True)
    for line in result.splitlines():
        discovered_geometry = get_window_geometry(line)
        logging.debug("Discovered geometry: {0!s}".format(discovered_geometry))
        if discovered_geometry == STARS_GAME_GEOMETRY:
            window_id = int(line.strip())
            logging.debug("Pressing Alt R")
            cmd = "xdotool windowactivate {0!s} key Alt key R".format(window_id)
            result = subprocess.check_output(cmd, shell=True)

            time.sleep(0.5)
            cmd = "xdotool windowactivate {0!s} key D".format(window_id)
            result = subprocess.check_output(cmd, shell=True)

            time.sleep(0.5)
            cmd = "xdotool windowactivate {0!s} key U".format(window_id)
            result = subprocess.check_output(cmd, shell=True)

            time.sleep(0.5)

            return

    raise Exception("Could not find main game window.")
