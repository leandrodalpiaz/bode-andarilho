import asyncio
import functools
import logging
from telegram import Bot
from telegram.ext import ExtBot
from telegram.error import RetryAfter, TelegramError

logger = logging.getLogger(__name__)

def patch_telegram_bot_classes():
    """
    Monkey-patches the send and edit methods of python-telegram-bot classes
    (Bot and ExtBot) to automatically handle rate-limiting (RetryAfter)
    and add a tiny safety interval between requests.
    """
    if getattr(Bot, "_patched_for_rate_limits", False):
        logger.info("Telegram Bot classes already patched for rate limits.")
        return
    Bot._patched_for_rate_limits = True

    methods_to_patch = [
        "send_message",
        "send_photo",
        "edit_message_text",
        "edit_message_media",
        "edit_message_caption",
        "send_document",
    ]

    for name in methods_to_patch:
        for cls in (Bot, ExtBot):
            if hasattr(cls, name):
                original_method = getattr(cls, name)
                
                # Avoid double wrapping if subclass inherits or already patched
                if getattr(original_method, "__name__", "") == "safe_call":
                    continue

                def make_safe_call(orig):
                    @functools.wraps(orig)
                    async def safe_call(self, *args, **kwargs):
                        max_retries = 5
                        for attempt in range(max_retries):
                            try:
                                # Apply a small safety delay to prevent burst flood
                                await asyncio.sleep(0.05)
                                return await orig(self, *args, **kwargs)
                            except RetryAfter as e:
                                sleep_time = e.retry_after
                                logger.warning(
                                    "Telegram rate limit hit (RetryAfter) on %s. Sleeping for %.2f seconds (attempt %d/%d)...",
                                    orig.__name__, sleep_time, attempt + 1, max_retries
                                )
                                await asyncio.sleep(sleep_time + 0.1)
                            except TelegramError as e:
                                raise e
                        # Final attempt if all retries exhausted (letting error bubble up)
                        return await orig(self, *args, **kwargs)
                    return safe_call

                setattr(cls, name, make_safe_call(original_method))
                logger.debug("Patched method %s.%s for rate limiting", cls.__name__, name)

    logger.info("Successfully patched Telegram Bot classes for rate limiting and RetryAfter handling.")
