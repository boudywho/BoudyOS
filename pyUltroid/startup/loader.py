# Ultroid - UserBot
# Copyright (C) 2021-2026 TeamUltroid
#
# This file is a part of < https://github.com/TeamUltroid/Ultroid/ >
# PLease read the GNU Affero General Public License in
# <https://github.com/TeamUltroid/pyUltroid/blob/main/LICENSE>.

import os
import hashlib
from pathlib import Path
from decouple import config

from .. import *
from ..dB._core import HELP
from ..loader import Loader
from ..paths import (
    OFFICIAL_ASSISTANT,
    OFFICIAL_PLUGINS,
    TRUSTED_ADDON_REGISTRY,
)
from . import *
from .utils import load_addons
from ..security.addons import AddonInstallError, load_registry
from ..security.profiles import (
    ASSISTANT_PROFILE_PLUGINS,
    PROFILE_POLICY_LEGACY,
    excluded_for_profiles,
    resolve_profiles,
)
from ..security.settings import setting_enabled


def _trusted_local_addons(addon_dir=Path("addons")):
    """Return registry-pinned local add-ons whose bytes still match."""
    try:
        registry = load_registry(TRUSTED_ADDON_REGISTRY)
    except AddonInstallError:
        return set()
    trusted = set()
    for name, entry in registry.items():
        path = addon_dir / name
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            continue
        if digest == entry.sha256:
            trusted.add(path.stem)
    return trusted


def _after_load(loader, module, plugin_name=""):
    if not module or plugin_name.startswith("_"):
        return
    from strings import get_help

    if doc_ := get_help(plugin_name) or module.__doc__:
        try:
            doc = doc_.format(i=HNDLR)
        except Exception as er:
            loader._logger.exception(er)
            loader._logger.info(f"Error in {plugin_name}: {module}")
            return
        if loader.key in HELP.keys():
            update_cmd = HELP[loader.key]
            try:
                update_cmd.update({plugin_name: doc})
            except BaseException as er:
                loader._logger.exception(er)
        else:
            try:
                HELP.update({loader.key: {plugin_name: doc}})
            except BaseException as em:
                loader._logger.exception(em)


def load_other_plugins(addons=None, pmbot=None, manager=None, vcbot=None):

    # for official
    _exclude = udB.get_key("EXCLUDE_OFFICIAL") or config("EXCLUDE_OFFICIAL", None)
    _exclude = _exclude.split() if _exclude else []

    # "INCLUDE_ONLY" was added to reduce Big List in "EXCLUDE_OFFICIAL" Plugin
    _in_only = udB.get_key("INCLUDE_ONLY") or config("INCLUDE_ONLY", None)
    _in_only = _in_only.split() if _in_only else []
    if not _in_only:
        profile_value = udB.get_key("PLUGIN_PROFILES") or config(
            "PLUGIN_PROFILES", default=None
        )
        policy_marker = udB.get_key("PLUGIN_PROFILE_POLICY") or config(
            "PLUGIN_PROFILE_POLICY", default=None
        )
        try:
            selection = resolve_profiles(
                profile_value, policy_marker=policy_marker
            )
        except ValueError as exc:
            LOGS.error("%s; preserving the legacy official plugin set", exc)
            selection = resolve_profiles(None, policy_marker=PROFILE_POLICY_LEGACY)
        if not policy_marker:
            # An unset upgraded installation is explicitly migrated to legacy-all.
            # New provisioning supplies both a marker and core,media.
            udB.set_key("PLUGIN_PROFILE_POLICY", PROFILE_POLICY_LEGACY)
        all_plugins = [
            path.stem
            for path in OFFICIAL_PLUGINS.glob("*.py")
            if path.name != "__init__.py"
        ]
        _exclude.extend(excluded_for_profiles(all_plugins, selection))
    Loader().load(include=_in_only, exclude=_exclude, after_load=_after_load)

    # for assistant
    if not USER_MODE and not udB.get_key("DISABLE_AST_PLUGINS"):
        _ast_exc = ["pmbot"]
        experimental_selected = (
            not _in_only
            and "selection" in locals()
            and (
                selection.legacy_all
                or ASSISTANT_PROFILE_PLUGINS["games"] in selection.names
            )
        )
        if (_in_only and "games" not in _in_only) or (
            not _in_only and not experimental_selected
        ):
            _ast_exc.append("games")
        Loader(path=OFFICIAL_ASSISTANT).load(
            log=False, exclude=_ast_exc, after_load=_after_load
        )

    # for addons
    if addons:
        if not os.path.exists("addons"):
            LOGS.warning(
                "ADDONS is enabled but no local add-ons directory exists. "
                "Automatic mutable repository installation is disabled; use "
                "the trusted add-on registry workflow."
            )
        else:
            _exclude = udB.get_key("EXCLUDE_ADDONS")
            _exclude = _exclude.split() if _exclude else []
            _in_only = udB.get_key("INCLUDE_ADDONS")
            _in_only = _in_only.split() if _in_only else []
            if not setting_enabled(udB, "ALLOW_UNTRUSTED_PLUGINS"):
                trusted = _trusted_local_addons()
                requested = set(_in_only) if _in_only else {
                    path.stem
                    for path in Path("addons").glob("*.py")
                    if not path.name.startswith(".")
                }
                refused = requested.difference(trusted)
                if refused:
                    LOGS.warning(
                        "Untrusted local add-ons are disabled; skipped %d file(s).",
                        len(refused),
                    )
                _in_only = sorted(requested.intersection(trusted))
            Loader(path="addons", key="Addons").load(
                func=load_addons,
                include=_in_only,
                exclude=_exclude,
                after_load=_after_load,
                load_all=True,
            )

    if not USER_MODE:
        # group manager
        if manager:
            Loader(
                path=OFFICIAL_ASSISTANT / "manager", key="Group Manager"
            ).load()

        # chat via assistant
        if pmbot:
            Loader(path=OFFICIAL_ASSISTANT / "pmbot.py").load(log=False)

    # vc bot
    if vcbot and (vcClient and not vcClient.me.bot):
        try:
            import pytgcalls  # ignore: pylint

            if not os.path.exists("vcbot"):
                LOGS.warning(
                    "VCBOT requested but not installed. Automatic mutable cloning "
                    "is disabled; install a reviewed, pinned release explicitly."
                )
            else:
                try:
                    if not os.path.exists("vcbot/downloads"):
                        os.mkdir("vcbot/downloads")
                    Loader(path="vcbot", key="VCBot").load(after_load=_after_load)
                except FileNotFoundError as e:
                    LOGS.error(f"{e} Skipping VCBot Installation.")
        except ModuleNotFoundError:
            LOGS.error("'pytgcalls' not installed!\nSkipping loading of VCBOT.")
