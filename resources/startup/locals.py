# /usr/bin/python3
# Ultroid - UserBot
# Copyright (C) 2021-2026 TeamUltroid
#
# This file is a part of < https://github.com/TeamUltroid/Ultroid/ >
# Please read the GNU Affero General Public License in
# <https://www.github.com/TeamUltroid/Ultroid/blob/main/LICENSE/>.

# Standalone file for facilitating local deploys.

import os
import shutil
import subprocess
import sys

a = r"""
  _    _ _ _             _     _
 | |  | | | |           (_)   | |
 | |  | | | |_ _ __ ___  _  __| |
 | |  | | | __| '__/ _ \| |/ _  |
 | |__| | | |_| | | (_) | | (_| |
  \____/|_|\__|_|  \___/|_|\__,_|
"""


def start():

    clear_screen()
    check_for_py()

    print(f"{a}\n\n")
    print("Welcome to BoudyOS. Let's get your workspace ready.\n")
    print("Cloning the repository...\n\n")
    target = os.path.abspath("BoudyOS")
    if os.path.isdir(target):
        shutil.rmtree(target)
    subprocess.run(
        ["git", "clone", "https://github.com/boudywho/BoudyOS.git", target],
        check=True,
        timeout=300,
    )
    print("\n\nDone")
    os.chdir("BoudyOS")
    clear_screen()
    print(a)
    print("\n\nLet's start!\n")

    # generate session if needed.
    sessionisneeded = input(
        "Do you want to generate a new session, or have an old session string? [generate/skip]",
    )
    if sessionisneeded == "generate":
        gen_session()
    elif sessionisneeded != "skip":
        print(
            'Please choose "generate" to generate a session string, or "skip" to pass on.\n\nPlease run the script again!',
        )
        exit(0)

    # start bleck megik
    print("\n\nLets start entering the variables.\n\n")
    varrs = [
        "API_ID",
        "API_HASH",
        "SESSION",
        "REDIS_URI",
        "REDIS_PASSWORD",
    ]
    all_done = "# BoudyOS environment variables.\n# Do not delete this file.\n\n"
    all_done += "PLUGIN_PROFILES=core,media\n"
    all_done += "PLUGIN_PROFILE_POLICY=new-safe-v1\n"
    for i in varrs:
        all_done += do_input(i)
    clear_screen()
    print(a)
    print("\n\nHere are the things you've entered.\nKindly check.")
    print(all_done)
    isitdone = input("\n\nIs it all correct? [y/n]")
    if isitdone == "y" or isitdone != "n":
        # https://github.com/TeamUltroid/Ultroid/blob/31b9eb1f4f8059e0ae66adb74cb6e8174df12eac/resources/startup/locals.py#L35
        f = open(".env", "w")
        f.write(all_done)
    else:
        print("Oh, let's redo these then.")
        start()
    clear_screen()
    print("\nCongrats. All done!\nTime to start the bot!")
    print("\nInstalling requirements... This might take a while...")
    constraint = (
        "constraints/py313.txt"
        if sys.version_info[:2] >= (3, 13)
        else "constraints/py310.txt"
    )
    subprocess.run(
        [
            sys.executable, "-m", "pip", "install", "--no-cache-dir",
            "-r", "requirements/media.txt", "-c", constraint,
        ],
        check=True,
        timeout=900,
    )
    ask = input(
        "Enter 'yes/y' to Install other requirements, required for local deployment."
    )
    if ask.lower().startswith("y"):
        print("Started Installing...")
        subprocess.run(
            [
                sys.executable, "-m", "pip", "install", "--no-cache-dir",
                "-r", "resources/startup/optional-requirements.txt",
                "-c", constraint,
            ],
            check=True,
            timeout=1800,
        )
    else:
        print("Skipped!")
    subprocess.run([sys.executable, "-m", "pip", "check"], check=True)
    clear_screen()
    print(a)
    print("\nStarting BoudyOS...")
    subprocess.run(["bash", "startup"], check=True)


def do_input(var):
    val = input(f"Enter your {var}: ")
    return f"{var}={val}\n"


def clear_screen():
    # clear screen
    print("\033[2J\033[H", end="")


def check_for_py():
    print(
        "Please make sure you have python installed. \nGet it from http://python.org/\n\n",
    )
    try:
        ch = int(
            input(
                "Enter Choice:\n1. Continue, python is installed.\n2. Exit and install python.\n",
            ),
        )
    except BaseException:
        print("Please run the script again, and enter the choice as a number!!")
        exit(0)
    if ch == 1:
        pass
    elif ch == 2:
        print("Please install python and continue!")
        exit(0)
    else:
        print("Weren't you taught how to read? Enter a choice!!")
        return


def gen_session():
    print("\nProcessing...")
    # https://github.com/TeamUltroid/Ultroid/main/resources/startup/locals.py#L35
    subprocess.run(
        [sys.executable, "resources/session/ssgen.py"], check=True
    )


start()
