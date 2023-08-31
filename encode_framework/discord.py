"""
Module for using Discord webhooks. NEVER share your webhook url or account details with strangers, kids!
"""
import re
from random import choice
from typing import Any, Literal

import requests

from .logging import Log

__all__: list[str] = [
    "markdownify",
    "notify_webhook",
]


def notify_webhook(
    show_name: str, ep_num: str,
    username: str, author: str, avatar: str,
    webhook_url: str, color: str = "33023",
    title: str = "{show_name} {ep_num} has finished encoding!",
    description: str = "", image: str | Literal[False] = False,
    retries: int = 3,
    **kwargs: Any
) -> None:
    """
    Notify users through a discord webhook.
    """
    format_args = {
        "show_name": show_name,
        "ep_num": ep_num,
        "username": username,
        "author": author,
        "avatar": avatar,
    }

    format_args |= kwargs

    if format_args.get("description", False):
        kwargs["description"] = str(kwargs.get("description")).strip().title()

    headers = {
        "content-type": "application/json",
        "Accept-Charset": "UTF-8"
    }

    payload = {
        "username": username,
        "avatar_url": avatar,
        "embeds": [
                {
                "author": {
                    "name": author,
                },
                "title": title.format(**format_args),
                "description": description.format(**format_args),
                "color": color,
            }
        ]
    }

    if image:
        Log.debug(f"Image to send within the payload: {image}")
        payload["embeds"]["image"] = {"url": image}

    attempts = 0

    while attempts < retries:
        Log.debug(f"Sending the payload to the Discord webhook (attempt {attempts + 1}/{retries})", notify_webhook)
        r = requests.post(webhook_url, json=payload, headers=headers)

        if r.ok:
            break

        attempts += 1
    else:
        Log.error(f"Could not send payload after {retries} attempts. Giving up.", notify_webhook)

        try:
            r.raise_for_status()
        except requests.exceptions.HTTPError as e:
            Log.error(e, notify_webhook)


def markdownify(string: str) -> str:
    """Markdownify a given string."""
    string = re.sub(r"\[bold\]([a-zA-Z0-9\.!?:\-]+)?\[\/\]", r"**\1**", str(string))
    string = re.sub(r"\[italics\]([a-zA-Z0-9\.!?:\-]+)?\[\/\]", r"_\1_", str(string))

    return string
