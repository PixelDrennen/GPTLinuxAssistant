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
