"""
Module for using Discord webhooks. NEVER share your webhook url or account details with strangers, kids!
"""
from random import choice
from typing import Any

import requests

from .logging import Log

__all__: list[str] = [
    "notify_webhook"
]


def notify_webhook(
    show_name: str, ep_num: str,
    username: str, author: str, avatar: str,
    webhook_url: str, color: str = "33023",
    title: str = "{show_name} {ep_num} has finished encoding!",
    description: str = "",
    retries: int = 3, footer: int | dict[str, str] | list[dict[str, str]] | None = None,
    **kwargs: Any
) -> None:
    """
    Notify users through a discord webhook.
    """
    stock_footers = [
        {
            "text": "Powered by sleepy Light magic 🪄",
            "icon_url": "https://i.imgur.com/rsJS9YL.png"
        },
        {
            "text": "Bbreaking the game balance",
            "icon_url": "https://emoji.discadia.com/emojis/NepOkay.png"
        },
        {
            "text": "Conquered the Sea of Stars",
            "icon_url": "https://static.wikia.nocookie.net/fategrandorder/images/9/9d/CEIcon569.webp"
        }
    ]

    if isinstance(footer, int):
        try:
            dfooter = stock_footers[footer]
        except KeyError:
            dfooter = choice(stock_footers)
    elif isinstance(footer, dict):
        dfooter = footer
    elif isinstance(footer, list):
        dfooter = choice(footer)
    elif footer is None:
        dfooter = choice(stock_footers)
    else:
        dfooter = {"text": "", "icon_url": ""}

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
                "footer": {
                    "text": list(dfooter.values())[0],
                    "icon_url": list(dfooter.values())[1]
                }
            }
        ]
    }

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
