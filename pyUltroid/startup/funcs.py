# Ultroid - UserBot
# Copyright (C) 2021-2026 TeamUltroid
#
# This file is a part of < https://github.com/TeamUltroid/Ultroid/ >
# PLease read the GNU Affero General Public License in
# <https://github.com/TeamUltroid/pyUltroid/blob/main/LICENSE>.

import asyncio
import os
import shutil
import time
from datetime import datetime, timezone as dt_timezone
from random import randint

from ..configs import Var

try:
    from pytz import timezone
except ImportError:
    timezone = None

from telethon.errors import (
    ChannelsTooMuchError,
    ChatAdminRequiredError,
    MessageIdInvalidError,
    MessageNotModifiedError,
    UserNotParticipantError,
)
from telethon.tl.custom import Button
from telethon.tl.functions.channels import (
    CreateChannelRequest,
    EditAdminRequest,
    EditPhotoRequest,
    InviteToChannelRequest,
)
from telethon.tl.functions.contacts import UnblockRequest
from telethon.tl.types import (
    ChatAdminRights,
    ChatPhotoEmpty,
    InputChatUploadedPhoto,
    InputMessagesFilterDocument,
)
from telethon.utils import get_peer_id
from decouple import config, RepositoryEnv
from .. import LOGS, ULTConfig
from ..fns.helper import download_file, inline_mention, updater
from ..paths import source_resource

db_url = 0
REDIS_KEEPALIVE_KEY = "KEEP_ACTIVE"
REDIS_KEEPALIVE_INTERVAL_SECONDS = 7 * 24 * 60 * 60
BOUDYOS_BRAND_VERSION_KEY = "BOUDYOS_BRAND_VERSION"
BOUDYOS_BRAND_VERSION = 1
BOTFATHER_SUCCESS_INDICATORS = ("done", "success", "successfully")
BOTFATHER_ERROR_INDICATORS = (
    "cannot",
    "can't",
    "error",
    "failed",
    "flood",
    "invalid",
    "not allowed",
    "not updated",
    "sorry",
    "too many",
    "try again",
)


def _botfather_mutation_succeeded(response):
    """Return whether BotFather explicitly confirmed a completed mutation."""
    text = getattr(response, "text", response) or ""
    normalized = " ".join(str(text).casefold().split())
    if any(indicator in normalized for indicator in BOTFATHER_ERROR_INDICATORS):
        return False
    return any(indicator in normalized for indicator in BOTFATHER_SUCCESS_INDICATORS)


async def _latest_botfather_response(client):
    messages = await client.get_messages("botfather", limit=1)
    return messages[0] if messages else None


async def _require_botfather_success(client, operation):
    response = await _latest_botfather_response(client)
    if not _botfather_mutation_succeeded(response):
        text = getattr(response, "text", response) or "no response"
        raise RuntimeError(f"BotFather rejected {operation}: {text}")


async def autoupdate_local_database():
    from .. import Var, asst, udB, ultroid_bot

    global db_url
    db_url = (
        udB.get_key("TGDB_URL") or Var.TGDB_URL or ultroid_bot._cache.get("TGDB_URL")
    )
    if db_url:
        _split = db_url.split("/")
        _channel = _split[-2]
        _id = _split[-1]
        try:
            await asst.edit_message(
                int(_channel) if _channel.isdigit() else _channel,
                message=_id,
                file="database.json",
                text="**Do not delete this file.**",
            )
        except MessageNotModifiedError:
            return
        except MessageIdInvalidError:
            pass
    try:
        LOG_CHANNEL = (
            udB.get_key("LOG_CHANNEL")
            or Var.LOG_CHANNEL
            or asst._cache.get("LOG_CHANNEL")
            or "me"
        )
        msg = await asst.send_message(
            LOG_CHANNEL, "**Do not delete this file.**", file="database.json"
        )
        asst._cache["TGDB_URL"] = msg.message_link
        udB.set_key("TGDB_URL", msg.message_link)
    except Exception as ex:
        LOGS.error(f"Error on autoupdate_local_database: {ex}")


def update_envs():
    """Update Var. attributes to udB"""
    from .. import udB
    _envs = [*list(os.environ)]
    env_file = config._find_file(".")
    if env_file:
        try:
            [_envs.append(_) for _ in list(RepositoryEnv(env_file).data)]
        except Exception:
            pass
    for envs in _envs:
        if (
            envs in ["LOG_CHANNEL", "BOT_TOKEN", "BOTMODE", "DUAL_MODE", "language"]
            or envs in udB.keys()
        ):
            if _value := os.environ.get(envs):
                udB.set_key(envs, _value)
            else:
                udB.set_key(envs, config(envs, default=None))


async def startup_stuff():
    from .. import udB

    x = ["resources/auth", "resources/downloads"]
    for x in x:
        if not os.path.isdir(x):
            os.mkdir(x)

    CT = udB.get_key("CUSTOM_THUMBNAIL")
    if CT:
        path = "resources/downloads/thumbnail.jpg"
        ULTConfig.thumb = path
        try:
            await download_file(CT, path)
        except Exception as er:
            LOGS.exception(er)
    elif CT is False:
        ULTConfig.thumb = None
    GT = udB.get_key("GDRIVE_AUTH_TOKEN")
    if GT:
        with open("resources/auth/gdrive_creds.json", "w") as t_file:
            t_file.write(GT)

    if udB.get_key("AUTH_TOKEN"):
        udB.del_key("AUTH_TOKEN")

    MM = udB.get_key("MEGA_MAIL")
    MP = udB.get_key("MEGA_PASS")
    if MM and MP:
        with open(".megarc", "w") as mega:
            mega.write(f"[Login]\nUsername = {MM}\nPassword = {MP}")

    TZ = udB.get_key("TIMEZONE")
    if TZ and timezone:
        try:
            timezone(TZ)
            os.environ["TZ"] = TZ
            time.tzset()
        except AttributeError as er:
            LOGS.debug(er)
        except BaseException:
            LOGS.warning("Invalid time zone configured; falling back to UTC.")
            os.environ["TZ"] = "UTC"
            time.tzset()


async def keep_redis_alive():
    from .. import udB

    if udB.name != "Redis":
        return

    interval = udB.get_key("REDIS_KEEPALIVE_INTERVAL")
    try:
        interval = int(interval) if interval else REDIS_KEEPALIVE_INTERVAL_SECONDS
    except (TypeError, ValueError):
        interval = REDIS_KEEPALIVE_INTERVAL_SECONDS
    interval = max(interval, 60)

    while True:
        try:
            now = datetime.now(dt_timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            udB.set_key(REDIS_KEEPALIVE_KEY, f"Updated value at {now}")
            LOGS.debug(
                "Redis keepalive updated key '%s' (next run in %s seconds).",
                REDIS_KEEPALIVE_KEY,
                interval,
            )
        except Exception as exc:
            LOGS.warning("Redis keepalive update failed: %s", exc)
        await asyncio.sleep(interval)


async def autobot():
    from .. import udB, ultroid_bot

    if udB.get_key("BOT_TOKEN"):
        return
    await ultroid_bot.start()
    LOGS.info("Creating your BoudyOS assistant with @BotFather...")
    who = ultroid_bot.me
    name = who.first_name + "'s BoudyOS Assistant"
    if who.username:
        username = who.username + "_bot"
    else:
        username = "boudyos_" + (str(who.id))[5:] + "_bot"
    bf = "@BotFather"
    await ultroid_bot(UnblockRequest(bf))
    await ultroid_bot.send_message(bf, "/cancel")
    await asyncio.sleep(1)
    await ultroid_bot.send_message(bf, "/newbot")
    await asyncio.sleep(1)
    isdone = (await ultroid_bot.get_messages(bf, limit=1))[0].text
    if isdone.startswith("That I cannot do.") or "20 bots" in isdone:
        LOGS.critical(
            "Please make a Bot from @BotFather and add it's token in BOT_TOKEN, as an env var and restart me."
        )
        import sys

        sys.exit(1)
    await ultroid_bot.send_message(bf, name)
    await asyncio.sleep(1)
    isdone = (await ultroid_bot.get_messages(bf, limit=1))[0].text
    if not isdone.startswith("Good."):
        await ultroid_bot.send_message(bf, "BoudyOS Assistant")
        await asyncio.sleep(1)
        isdone = (await ultroid_bot.get_messages(bf, limit=1))[0].text
        if not isdone.startswith("Good."):
            LOGS.critical(
                "Please make a Bot from @BotFather and add it's token in BOT_TOKEN, as an env var and restart me."
            )
            import sys

            sys.exit(1)
    await ultroid_bot.send_message(bf, username)
    await asyncio.sleep(1)
    isdone = (await ultroid_bot.get_messages(bf, limit=1))[0].text
    await ultroid_bot.send_read_acknowledge("botfather")
    if isdone.startswith("Sorry,"):
        ran = randint(1, 100)
        username = "boudyos_" + (str(who.id))[6:] + str(ran) + "_bot"
        await ultroid_bot.send_message(bf, username)
        await asyncio.sleep(1)
        isdone = (await ultroid_bot.get_messages(bf, limit=1))[0].text
    if isdone.startswith("Done!"):
        token = isdone.split("`")[1]
        udB.set_key("BOT_TOKEN", token)
        await enable_inline(ultroid_bot, username)
        LOGS.info("Created BoudyOS assistant @%s.", username)
    else:
        LOGS.info(
            "Please Delete Some Of your Telegram bots at @Botfather or Set Var BOT_TOKEN with token of a bot"
        )

        import sys

        sys.exit(1)


async def autopilot():
    from .. import asst, udB, ultroid_bot

    channel = udB.get_key("LOG_CHANNEL")
    new_channel = None
    if channel:
        try:
            chat = await ultroid_bot.get_entity(channel)
        except BaseException as err:
            LOGS.exception(err)
            udB.del_key("LOG_CHANNEL")
            channel = None
    if not channel:

        async def _save(exc):
            udB._cache["LOG_CHANNEL"] = ultroid_bot.me.id
            await asst.send_message(
                ultroid_bot.me.id, f"Failed to Create Log Channel due to {exc}.."
            )

        if ultroid_bot._bot:
            msg_ = "'LOG_CHANNEL' not found! Add it in order to use 'BOTMODE'"
            LOGS.error(msg_)
            return await _save(msg_)
        LOGS.info("Creating the BoudyOS log group...")
        try:
            r = await ultroid_bot(
                CreateChannelRequest(
                    title="BoudyOS Logs",
                    about=(
                        "Private logs for BoudyOS.\n"
                        "https://github.com/boudywho/BoudyOS"
                    ),
                    megagroup=True,
                ),
            )
        except ChannelsTooMuchError as er:
            LOGS.critical(
                "You Are in Too Many Channels & Groups , Leave some And Restart The Bot"
            )
            return await _save(str(er))
        except BaseException as er:
            LOGS.exception(er)
            LOGS.info(
                "Something Went Wrong , Create A Group and set its id on config var LOG_CHANNEL."
            )

            return await _save(str(er))
        new_channel = True
        chat = r.chats[0]
        channel = get_peer_id(chat)
        udB.set_key("LOG_CHANNEL", channel)
    assistant = True
    try:
        await ultroid_bot.get_permissions(int(channel), asst.me.username)
    except UserNotParticipantError:
        try:
            await ultroid_bot(InviteToChannelRequest(int(channel), [asst.me.username]))
        except BaseException as er:
            LOGS.info("Error while Adding Assistant to Log Channel")
            LOGS.exception(er)
            assistant = False
    except BaseException as er:
        assistant = False
        LOGS.exception(er)
    if assistant and new_channel:
        try:
            achat = await asst.get_entity(int(channel))
        except BaseException as er:
            achat = None
            LOGS.info("Error while getting Log channel from Assistant")
            LOGS.exception(er)
        if achat and not achat.admin_rights:
            rights = ChatAdminRights(
                add_admins=True,
                invite_users=True,
                change_info=True,
                ban_users=True,
                delete_messages=True,
                pin_messages=True,
                anonymous=False,
                manage_call=True,
            )
            try:
                await ultroid_bot(
                    EditAdminRequest(
                        int(channel), asst.me.username, rights, "Assistant"
                    )
                )
            except ChatAdminRequiredError:
                LOGS.info(
                    "Failed to promote 'Assistant Bot' in 'Log Channel' due to 'Admin Privileges'"
                )
            except BaseException as er:
                LOGS.info("Error while promoting assistant in Log Channel..")
                LOGS.exception(er)
    if isinstance(chat.photo, ChatPhotoEmpty):
        try:
            photo = str(source_resource("extras", "boudyos_avatar.jpg"))
            uploaded = await ultroid_bot.upload_file(photo)
            await ultroid_bot(
                EditPhotoRequest(int(channel), InputChatUploadedPhoto(uploaded))
            )
        except BaseException as er:
            LOGS.warning("Could not set the optional BoudyOS log-group image: %s", er)


# customize assistant


async def _apply_boudyos_branding(asst, udB, ultroid_bot):
    try:
        owner = getattr(ultroid_bot, "me", None)
        assistant = getattr(asst, "me", None)
        if (
            asst is ultroid_bot
            or getattr(owner, "bot", None) is not False
            or getattr(assistant, "bot", None) is not True
        ):
            return
        if udB.get_key(BOUDYOS_BRAND_VERSION_KEY) == BOUDYOS_BRAND_VERSION:
            return
        chat_id = udB.get_key("LOG_CHANNEL")
        LOGS.info("Customizing the BoudyOS assistant with @BotFather...")
        UL = f"@{assistant.username}"
        if not owner.username:
            sir = owner.first_name
        else:
            sir = f"@{owner.username}"
        file = str(source_resource("extras", "boudyos_avatar.jpg"))
        msg = await asst.send_message(
            chat_id, "**BoudyOS assistant customization** started in @BotFather."
        )
        await asyncio.sleep(1)
        await ultroid_bot.send_message("botfather", "/cancel")
        await asyncio.sleep(1)
        await ultroid_bot.send_message("botfather", "/setuserpic")
        await asyncio.sleep(1)
        isdone = (await _latest_botfather_response(ultroid_bot)).text
        if isdone.startswith("Invalid bot"):
            LOGS.info("Error while trying to customise assistant, skipping...")
            return
        await ultroid_bot.send_message("botfather", UL)
        await asyncio.sleep(1)
        await ultroid_bot.send_file("botfather", file)
        await asyncio.sleep(2)
        await _require_botfather_success(ultroid_bot, "profile photo")
        await ultroid_bot.send_message("botfather", "/setname")
        await asyncio.sleep(1)
        await ultroid_bot.send_message("botfather", UL)
        await asyncio.sleep(1)
        await ultroid_bot.send_message("botfather", "BoudyOS Assistant")
        await asyncio.sleep(2)
        await _require_botfather_success(ultroid_bot, "name")
        await ultroid_bot.send_message("botfather", "/setabouttext")
        await asyncio.sleep(1)
        await ultroid_bot.send_message("botfather", UL)
        await asyncio.sleep(1)
        await ultroid_bot.send_message(
            "botfather", f"BoudyOS assistant for {sir}"
        )
        await asyncio.sleep(2)
        await _require_botfather_success(ultroid_bot, "about text")
        await ultroid_bot.send_message("botfather", "/setdescription")
        await asyncio.sleep(1)
        await ultroid_bot.send_message("botfather", UL)
        await asyncio.sleep(1)
        await ultroid_bot.send_message(
            "botfather",
            (
                f"Personal Telegram assistant for {sir}, powered by BoudyOS.\n"
                "https://github.com/boudywho/BoudyOS"
            ),
        )
        await asyncio.sleep(2)
        await _require_botfather_success(ultroid_bot, "description")
        await msg.edit("BoudyOS assistant customization completed.")
        udB.set_key(BOUDYOS_BRAND_VERSION_KEY, BOUDYOS_BRAND_VERSION)
        LOGS.info("Assistant customization completed.")
    except Exception as e:
        LOGS.warning(
            "Assistant branding was not completed; it will retry later: %s", e
        )


async def customize():
    from .. import asst, udB, ultroid_bot

    await _apply_boudyos_branding(asst, udB, ultroid_bot)


async def plug(plugin_channels):
    from .. import ultroid_bot
    from ..security.settings import setting_enabled
    from .utils import load_addons

    if ultroid_bot._bot:
        LOGS.info("Plugin Channels can't be used in 'BOTMODE'")
        return
    from .. import udB

    if not setting_enabled(udB, "ALLOW_UNTRUSTED_PLUGINS"):
        LOGS.warning(
            "Plugin-channel downloads are disabled by default. Existing local "
            "add-on files remain available."
        )
        return
    if os.path.exists("addons") and not os.path.exists("addons/.git"):
        shutil.rmtree("addons")
    if not os.path.exists("addons"):
        os.mkdir("addons")
    if not os.path.exists("addons/__init__.py"):
        with open("addons/__init__.py", "w") as f:
            f.write("from plugins import *\n\nbot = ultroid_bot")
    LOGS.info("• Loading Plugins from Plugin Channel(s) •")
    for chat in plugin_channels:
        LOGS.info(f"{'•'*4} {chat}")
        try:
            async for x in ultroid_bot.iter_messages(
                chat, search=".py", filter=InputMessagesFilterDocument, wait_time=10
            ):
                plugin = "addons/" + x.file.name.replace("_", "-").replace("|", "-")
                if not os.path.exists(plugin):
                    await asyncio.sleep(0.6)
                    if x.text == "#IGNORE":
                        continue
                    plugin = await x.download_media(plugin)
                    try:
                        load_addons(plugin)
                    except Exception as e:
                        LOGS.info(f"BoudyOS - plugin channel - error - {plugin}")
                        LOGS.exception(e)
                        os.remove(plugin)
        except Exception as er:
            LOGS.exception(er)



async def ready():
    from .. import asst, udB, ultroid_bot

    chat_id = udB.get_key("LOG_CHANNEL")
    spam_sent = None
    if not udB.get_key("INIT_DEPLOY"):  # Detailed Message at Initial Deploy
        MSG = """**Welcome to BoudyOS**

Your personal Telegram workspace is ready. Open the guide to review the essentials."""
        PHOTO = str(source_resource("extras", "boudyos_avatar.jpg"))
        BTTS = Button.inline("Open guide", "initft_2")
        udB.set_key("INIT_DEPLOY", "Done")
    else:
        MSG = (
            "**BoudyOS is ready.**\n\n"
            f"**User:** {inline_mention(ultroid_bot.me)}\n"
            f"**Assistant:** @{asst.me.username}\n"
            "**Support:** [BoudyOS on GitHub]"
            "(https://github.com/boudywho/BoudyOS)"
        )
        BTTS, PHOTO = None, None
        prev_spam = udB.get_key("LAST_UPDATE_LOG_SPAM")
        if prev_spam:
            try:
                await ultroid_bot.delete_messages(chat_id, int(prev_spam))
            except Exception as E:
                LOGS.info("Error while Deleting Previous Update Message :" + str(E))
        if await updater():
            BTTS = Button.inline("Update Available", "updtavail")

    try:
        spam_sent = await asst.send_message(chat_id, MSG, file=PHOTO, buttons=BTTS)
    except ValueError as e:
        try:
            await (await ultroid_bot.send_message(chat_id, str(e))).delete()
            spam_sent = await asst.send_message(chat_id, MSG, file=PHOTO, buttons=BTTS)
        except Exception as g:
            LOGS.info(g)
    except Exception as el:
        LOGS.info(el)
        try:
            spam_sent = await ultroid_bot.send_message(chat_id, MSG)
        except Exception as ef:
            LOGS.exception(ef)
    if spam_sent and not spam_sent.media:
        udB.set_key("LAST_UPDATE_LOG_SPAM", spam_sent.id)
async def WasItRestart(udb):
    key = udb.get_key("_RESTART")
    if not key:
        return
    from .. import asst, ultroid_bot

    try:
        data = key.split("_")
        who = asst if data[0] == "bot" else ultroid_bot
        await who.edit_message(
            int(data[1]), int(data[2]), "__Restarted Successfully.__"
        )
    except Exception as er:
        LOGS.exception(er)
    udb.del_key("_RESTART")


def _version_changes(udb):
    for _ in [
        "BOT_USERS",
        "BOT_BLS",
        "VC_SUDOS",
        "SUDOS",
        "CLEANCHAT",
        "LOGUSERS",
        "PLUGIN_CHANNEL",
        "CH_SOURCE",
        "CH_DESTINATION",
        "BROADCAST",
    ]:
        key = udb.get_key(_)
        if key and not isinstance(key, list):
            key_str = str(key)
            new_ = [
                int(z) if z.isdigit() or (z.startswith("-") and z[1:].isdigit()) else z
                for z in key_str.split()
            ]
            udb.set_key(_, new_)


async def enable_inline(ultroid_bot, username):
    bf = "BotFather"
    await ultroid_bot.send_message(bf, "/setinline")
    await asyncio.sleep(1)
    await ultroid_bot.send_message(bf, f"@{username}")
    await asyncio.sleep(1)
    await ultroid_bot.send_message(bf, "Search")
    await ultroid_bot.send_read_acknowledge(bf)
