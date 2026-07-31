printf "Updating System..\n\n"
pkg update -y
apt update
apt upgrade -y

python_not_installed="$(python -c 'exit()')"

# Install Python if n0t installed..
if [ python_not_installed ]
then
    printf "Installing Python..\nThis may take some long...\n"
    pkg install python3 -y
fi

printf "*Installing the tested BoudyOS media profile...*"
if python -c 'import sys; raise SystemExit(sys.version_info[:2] < (3, 13))'
then
    constraint="constraints/py313.txt"
else
    constraint="constraints/py310.txt"
fi
python -m pip install -q -r requirements/media.txt -c "$constraint"
python -m pip check

printf "Running up Installation tool.\n"
python resources/startup/_termux.py
