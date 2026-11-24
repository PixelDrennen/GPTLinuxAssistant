"""Recognize spoken requests to drop the current task and optionally start another."""
import re

SWITCH = re.compile(
    r"^(?:okay[, ]+)?(?:never\s?mind(?: that)?|forget that|start a new task|cancel(?: (?:that|the) (?:task|request)| that| request)?"
    r"|(?:let['’]?s )?move (?:on|past that)(?: and do something else)?"
    r"|(?:let['’]?s )?do something else)"
    r"(?:[.!?,:;]+\s*|\s+(?:and\s+)?(?=can\b|could\b|please\b|tell\b|help\b|look\b|what\b|how\b|show\b)|\s*$)(.*)$",
    re.IGNORECASE,
)


def next_task(text):
    match = SWITCH.match(text.strip())
    return match[1].strip() if match else None


POLITE = r"^(?:(?:okay|go ahead and|please|can you|could you|would you|are you able to)[, ]+){0,3}"
DESKTOP_PREFIX = re.compile(
    POLITE + r"(?:use (?:my |the )?computer to|control (?:my |the )?desktop to)\s+(.+)", re.IGNORECASE
)
DIRECT_INPUT = re.compile(
    POLITE + r"(?:(?:click|double[- ]click|right[- ]click|scroll|drag|press|type)\s+\S"
    r"|(?:hit|tap|press)\s+(?:play|pause|stop|mute)\b|play\s+(?:this|that|the|my)\s+video\b)",
    re.IGNORECASE,
)


def desktop_request(text):
    explicit = DESKTOP_PREFIX.match(text)
    if explicit:
        return explicit[1]
    if DIRECT_INPUT.match(text):
        return text
    return None


def is_capability_wording(text):
    prefix = re.match(r"^(?:(?:okay|please)[, ]+){0,2}(can you|could you|would you|are you able to)\b",
                      text, re.IGNORECASE)
    return prefix is not None
