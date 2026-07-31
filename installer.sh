#!/usr/bin/env bash

REPO="https://github.com/boudywho/BoudyOS.git"
CURRENT_DIR="$(pwd)"
ENV_FILE_PATH=".env"
DIR="/root/TeamUltroid"

while [ $# -gt 0 ]; do
    case "$1" in
    --dir=*)
        DIR="${1#*=}" || DIR="/root/TeamUltroid"
        ;;
    --branch=*)
        BRANCH="${1#*=}" || BRANCH="main"
        ;;
    --env-file=*)
        ENV_FILE_PATH="${1#*=}" || ENV_FILE_PATH=".env"
        ;;
    --no-root)
        NO_ROOT=true
        ;;
    *)
        echo "Unknown parameter passed: $1"
        exit 1
        ;;
    esac
    shift
done

check_dependencies() {
    # check if debian
    echo "Checking dependencies..."
    # read file with root access
    if ! [[ $(ls -l "/etc/sudoers" | cut -d " " -f1) =~ "r" ]]; then
        # check dependencies if installed
        echo -e "Root access not found. Checking if dependencies are installed." >&2
        if ! [ -x "$(command -v python3)" ] || ! [ -x "$(command -v python)" ]; then
            echo -e "Python3 isn't installed. Please install python3.10 or higher to run this bot." >&2
            exit 1
        fi
        if [ $(python3 -c "import sys; print(sys.version_info[1])") -lt 10 ] || [ $(python -c "import sys; print(sys.version_info[1])") -lt 10 ]; then
            echo -e "Python 3.10 or higher is required to run this bot." >&2
            exit 1
        fi
        # check if any of ffmpeg, mediainfo, neofetch, git is not installed
        if ! command -v ffmpeg &>/dev/null || ! command -v mediainfo &>/dev/null || ! command -v neofetch &>/dev/null || ! command -v git &>/dev/null; then
            echo -e "Some dependencies aren't installed. Please install ffmpeg, mediainfo, neofetch and git to run this bot." >&2
            exit 1
        fi
    fi
    if [ -x "$(command -v apt-get)" ]; then
        echo -e "Installing dependencies..."
        # check if any of ffmpeg, mediainfo, neofetch, git is not installed via dpkg
        if dpkg -l | grep -q ffmpeg || dpkg -l | grep -q mediainfo || dpkg -l | grep -q neofetch || dpkg -l | grep -q git; then
            sudo apt-get -qq -o=Dpkg::Use-Pty=0 update
            sudo apt-get install -qq -o=Dpkg::Use-Pty=0 python3 python3-pip ffmpeg mediainfo neofetch git -y
        fi
    elif [ -x "$(command -v pacman)" ]; then
        echo -e "Installing dependencies..."
        if pacman -Q | grep -q ffmpeg || pacman -Q | grep -q mediainfo || pacman -Q | grep -q neofetch || pacman -Q | grep -q git; then
            sudo pacman -Sy python python-pip git ffmpeg mediainfo neofetch --noconfirm
        fi
    else
        echo -e "Unknown OS. Checking if dependecies are installed" >&2
        if ! [ -x "$(command -v python3)" ] || ! [ -x "$(command -v python)" ]; then
            echo -e "Python3 isn't installed. Please install python3.10 or higher to run this bot." >&2
            exit 1
        fi
        if [ $(python3 -c "import sys; print(sys.version_info[1])") -lt 10 ] || [ $(python -c "import sys; print(sys.version_info[1])") -lt 10 ]; then
            echo -e "Python 3.10 or higher is required to run this bot." >&2
            exit 1
        fi
        if ! command -v ffmpeg &>/dev/null || ! command -v mediainfo &>/dev/null || ! command -v neofetch &>/dev/null || ! command -v git &>/dev/null; then
            echo -e "Some dependencies aren't installed. Please install ffmpeg, mediainfo, neofetch and git to run this bot." >&2
            exit 1
        fi
    fi
}

check_python() {
    # check if python is installed
    if ! command -v python3 &>/dev/null; then
        echo -e "Python3 isn't installed. Please install python3.10 or higher to run this bot."
        exit 1
    elif ! command -v python &>/dev/null; then
        echo -e "Python3 isn't installed. Please install python3.10 or higher to run this bot."
        exit 1
    fi
    if [ $(python3 -c "import sys; print(sys.version_info[1])") -lt 10 ]; then
        echo -e "Python 3.10 or higher is required to run this bot."
        exit 1
    elif [ $(python -c "import sys; print(sys.version_info[1])") -lt 3 ]; then
        if [ $(python -c "import sys; print(sys.version_info[1])") -lt 10 ]; then
            echo -e "Python 3.10 or higher is required to run this bot."
            exit 1
        fi
    fi
}

clone_repo() {
    # check if pyultroid, startup, plugins folders exist
    cd $DIR
    if [ -d $DIR ]; then
        if [ -d $DIR/.git ]; then
            echo -e "Updating Ultroid ${BRANCH}... "
            cd $DIR
            git pull
            currentbranch="$(git rev-parse --abbrev-ref HEAD)"
            if [ ! $BRANCH ]; then
                export BRANCH=$currentbranch
            fi
            case $currentbranch in
            $BRANCH)
                # do nothing
                ;;
            *)
                echo -e "Switching to branch ${BRANCH}... "
                echo -e $currentbranch
                git checkout $BRANCH
                ;;
            esac
        else
            rm -rf $DIR
            exit 1
        fi
        if [ -d "addons" ]; then
            cd addons
            git pull
        fi
        return
    else
        if [ ! $BRANCH ]; then
            export BRANCH="main"
        fi
        mkdir -p $DIR
        echo -e "Cloning Ultroid ${BRANCH}... "
        git clone -b $BRANCH $REPO $DIR
    fi
}

install_requirements() {
    echo -e "\n\nInstalling requirements... "
    if [ "$(python3 -c 'import sys; print(sys.version_info[:2] >= (3, 13))')" = "True" ]; then
        CONSTRAINT_FILE="$DIR/constraints/py313.txt"
    else
        CONSTRAINT_FILE="$DIR/constraints/py310.txt"
    fi
    python3 -m pip install -q --no-cache-dir \
        -r "$DIR/requirements/media.txt" \
        -c "$CONSTRAINT_FILE"
    python3 -m pip check
}

misc_install() {
    if [ "${VCBOT:-}" ]; then
        echo "VCBOT dependencies are optional; install requirements/voice.txt explicitly."
    fi
}

dep_install() {
    echo -e "\n\nInstalling DB Requirement..."
    if [ $MONGO_URI ]; then
        echo -e "   Installing MongoDB Requirements..."
        python3 -m pip install -q -r "$DIR/requirements/integrations.txt" -c "$CONSTRAINT_FILE"
    elif [ $DATABASE_URL ]; then
        echo -e "   Installing PostgreSQL Requirements..."
        python3 -m pip install -q -r "$DIR/requirements/integrations.txt" -c "$CONSTRAINT_FILE"
    elif [ $REDIS_URI ]; then
        echo -e "   Installing Redis Requirements..."
        python3 -m pip install -q -r "$DIR/requirements/integrations.txt" -c "$CONSTRAINT_FILE"
    fi
    python3 -m pip check
}

main() {
    echo -e "Starting Ultroid Setup..."
    if [ -d "pyUltroid" ] && [ -d "resources" ] && [ -d "plugins" ]; then
        DIR=$CURRENT_DIR
    fi
    if [ -f $ENV_FILE_PATH ]
    then
        set -a
        source <(cat $ENV_FILE_PATH | sed -e '/^#/d;/^\s*$/d' -e "s/'/'\\\''/g" -e "s/=\(.*\)/='\1'/g")
        set +a
        cp $ENV_FILE_PATH .env
    fi
    (check_dependencies)
    (check_python)
    (clone_repo)
    (install_requirements)
    (dep_install)
    (misc_install)
    echo -e "\n\nSetup Completed."
}

if [ $NO_ROOT ]; then
    echo -e "Running with non root"
    main
    return 0
elif [ -t 0 ]; then
    unameOut="$(uname -s)"
    case "${unameOut}" in
        Linux*)     machine=Linux;;
        Darwin*)    machine=Mac;;
        CYGWIN*)    machine=Cygwin;;
        MINGW*)     machine=MinGw;;
        *)          machine="UNKNOWN:${unameOut}"
    esac
    if machine != "Linux"; then
        echo -e "This script is only for Linux. Please use the Windows installer."
        exit 1
    fi
    # check if sudo is installed
    if ! command -v sudo &>/dev/null; then
        echo -e "Sudo isn't installed. Please install sudo to run this bot."
        exit 1
    fi
    sudo echo "Sudo permission granted."
    main
else
    echo "Not an interactive terminal, skipping sudo."
    # run main function
    main
fi
