# Ultroid - UserBot
# Copyright (C) 2021-2026 TeamUltroid
#
# This file is a part of < https://github.com/TeamUltroid/Ultroid/ >
# PLease read the GNU Affero General Public License in
# <https://github.com/TeamUltroid/pyUltroid/blob/main/LICENSE>.

import contextlib
import glob
import os
from importlib import import_module
from logging import Logger
from pathlib import Path

from . import LOGS
from .fns.tools import get_all_files
from .paths import OFFICIAL_PLUGINS, SOURCE_ROOT


class Loader:
    def __init__(self, path=OFFICIAL_PLUGINS, key="Official", logger: Logger = LOGS):
        self.path = os.fspath(path)
        self.key = key
        self._logger = logger

    @staticmethod
    def _module_name(plugin):
        path = Path(plugin).with_suffix("")
        if path.is_absolute():
            try:
                path = path.relative_to(SOURCE_ROOT)
            except ValueError as exc:
                raise ValueError(
                    "official module is outside immutable source"
                ) from exc
            return ".".join(path.parts)
        return str(path).replace("/", ".").replace("\\", ".")

    def load(
        self,
        log=True,
        func=import_module,
        include=None,
        exclude=None,
        after_load=None,
        load_all=False,
    ):
        _single = os.path.isfile(self.path)
        if include:
            if log:
                self._logger.info("Including: {}".format("• ".join(include)))
            files = glob.glob(f"{self.path}/_*.py")
            for file in include:
                path = f"{self.path}/{file}.py"
                if os.path.exists(path):
                    files.append(path)
        elif _single:
            files = [self.path]
        else:
            if load_all:
                files = get_all_files(self.path, ".py")
            else:
                files = glob.glob(f"{self.path}/*.py")
            if exclude:
                for path in exclude:
                    if not path.startswith("_"):
                        with contextlib.suppress(ValueError):
                            files.remove(f"{self.path}/{path}.py")
        if log and not _single:
            self._logger.info(
                f"• Installing {self.key} Plugins || Count : {len(files)} •"
            )
        for plugin in sorted(files):
            if func == import_module:
                plugin = self._module_name(plugin)
            try:
                modl = func(plugin)
            except ModuleNotFoundError as er:
                modl = None
                if plugin == "assistant.games" and (
                    er.name == "akipy" or (er.name or "").startswith("akipy.")
                ):
                    self._logger.warning(
                        "Optional games plugin skipped: install 'akipy' to enable it."
                    )
                else:
                    self._logger.error(f"{plugin}: '{er.name}' not installed!")
                continue
            except Exception as exc:
                modl = None
                self._logger.error(f"pyUltroid - {self.key} - ERROR - {plugin}")
                self._logger.exception(exc)
                continue
            if _single and log:
                self._logger.info(f"Successfully Loaded {plugin}!")
            if callable(after_load):
                if func == import_module:
                    plugin = plugin.split(".")[-1]
                after_load(self, modl, plugin_name=plugin)
