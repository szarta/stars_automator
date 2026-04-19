#!/usr/bin/python3
"""
Uses the stars_automator.ui module to open the original Stars! game and
generate maps of different sizes.

:author: Brandon Arrendondo
:license: MIT
"""
import sys
import argparse
import time
import shutil
import os
import glob

from stars_automator import ui as stars_automater
import logging


def main(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument("stars_exe")
    parser.add_argument("--num_runs", type=int, default=100)
    parser.add_argument("--universe_size", type=int, default=1,
                        help="Universe Size [1-5]")

    parser.add_argument("--universe_density", type=int, default=1,
                        help="Universe Density [1-4]")

    parser.add_argument("-v", "--verbose", help="increase output verbosity",
                        action="store_true")

    args = parser.parse_args()

    logging.basicConfig(format='[map-generator:%(asctime)s] %(message)s')
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    else:
        logging.getLogger().setLevel(logging.INFO)

    for i in range(args.num_runs):
        exists, window_id, process = stars_automater.launch_stars(
            args.stars_exe)

        if exists:
            logging.info("Stars! launched.")

            time.sleep(3)

            try:
                stars_automater.select_new_game()
                stars_automater.select_universe_size(args.universe_size)
                stars_automater.select_advanced_game()
                stars_automater.select_universe_density(args.universe_density)
                stars_automater.select_finish_advanced_game()
                time.sleep(1)
                stars_automater.default_ok_new_game()
                time.sleep(1)
                stars_automater.dump_universe_map()

                shutil.copy("Game.map", "Run{0!s}.map".format(i))
                logging.info("Generated map: Run{0!s}.map".format(i))

            except Exception as inst:
                logging.error(inst.args)
                process.kill()
                sys.exit()

            logging.debug("Cleaning up.")
            process.kill()

            for f in glob.glob("Game.*"):
                os.unlink(f)

        else:
            logging.error("Stars! failed to launch!")
            sys.exit()


if __name__ == "__main__":
    main(sys.argv[1:])
