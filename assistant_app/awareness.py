"""Local answers and descriptions for the app's observed runtime state."""
import re


def question_kind(words):
    if words in ("what skills are available", "what skills do you have", "list skills", "show skills"):
        return "skills"
    if re.fullmatch(r"(?:please )?check for updates(?: please)?", words):
        return "check"
    if re.fullmatch(r"(?:can you tell me )?(?:what(?: s| is) new|what (?:changed|was added)"
                    r"(?: (?:in|since|with) (?:the |your |this )?(?:last |latest )?(?:version|update))?)", words):
        return "changes"
    if re.fullmatch(r"(?:are you up to date|do you have (?:any |an )?updates?|is (?:an |there an )?update available"
                    r"|what(?: s| is) your update status)", words):
        return "updates"
    if re.fullmatch(r"(?:do you (?:already )?(?:have )?(?:(?:my |the |desktop |input |screen )?permissions?|access)"
                    r"|have you (?:already )?got (?:permission|access)|are you (?:already )?allowed"
                    r"|what permissions do you (?:already )?have"
                    r"|is desktop control (?:available|enabled|granted))(?: (?:already|now|yet|to do (?:it|that)"
                    r"|to control (?:my |the )?(?:computer|desktop)))?", words):
        return "permissions"
    if re.fullmatch(r"(?:what version (?:is this|are you running|are you on)|what(?: s| is) your version"
                    r"|what(?: s| is) your status|what are you doing(?: right now)?|app status)", words):
        return "status"
    if re.fullmatch(r"(?:what can you do|what are you able to do)(?: (?:right now|now|for me))?"
                    r"|(?:are you able to|can you) (?:control my (?:computer|desktop)|send keystrokes)", words):
        return "capabilities"
    return None


def change_lines(entries):
    return "\n".join(f"• {item['summary']} ({item['date']})" for item in entries)


def changes_answer(state):
    release = state["release"]
    notes = release["changes"]
    if not notes:
        return "I don’t have installed change notes for this copy."
    heading = "Changes installed since your previous version" if release["since_previous"] else "Recent changes in this copy"
    return f"{heading}\n{change_lines(notes)}"


def update_answer(state):
    update = state["updates"]
    if update["status"] == "checking":
        return "I’m checking for updates."
    if update["status"] == "installing":
        return "I’m installing the update. I’ll restart when it’s ready."
    if update["status"] == "available":
        summary = update["changes"][0]["summary"] if update["changes"] else ""
        return ("An update is available. " + (summary + ". " if summary else "")
                + "Open Check for updates to install it.")
    if update["status"] == "current":
        return "No newer update was found at the last check."
    if update["status"] == "error":
        return "The last update operation failed. " + update["error"]
    return "I haven’t checked for updates yet. Say check for updates."


def capabilities_answer(state):
    screen = "Monitors are shared." if state["screen"]["monitor_granted"] else "Screen viewing needs your share permission."
    desktop = state["desktop_control"]
    if desktop["permission_granted"]:
        control = "Desktop input is granted for the current task. Each move, click, or keystroke needs your approval."
    elif desktop["openai_key_configured"]:
        control = "Say use my computer to start a desktop task. KDE will ask for access, and you’ll review each input."
    else:
        control = "Save an OpenAI API key to use desktop control."
    bridges = [name.title() for name, state in state["editor_bridges"].items() if state["enabled"]]
    editing = " I can also work on shared " + " or ".join(bridges) + " selections." if bridges else ""
    return f"I can answer questions, inspect shared screens, and watch for a panel.{editing} {screen} {control}"


def status_answer(state):
    revision = state["release"]["revision"]
    screen = state["screen"]
    control = state["desktop_control"]
    return (
        f"Version {revision or 'unknown'}. {state['profile'].title()} profile. {state['activity']}. "
        f"{'Monitors shared.' if screen['monitor_granted'] else 'No monitors shared.'} "
        f"Desktop control: {control['phase']}. {update_answer(state)}"
    )


def permissions_answer(state):
    screen, control = state["screen"], state["desktop_control"]
    if screen["monitor_granted"]:
        viewing = "I have screen-viewing permission for the shared monitors."
    elif control["permission_granted"]:
        viewing = "I can see the display selected for this desktop task."
    else:
        viewing = "I don’t have a monitor shared right now."
    if control["permission_granted"]:
        inputs = "KDE has granted keyboard and pointer input for this task. Each input still needs your approval."
    elif control["phase"] == "awaiting KDE permission":
        inputs = "I’m waiting for the KDE keyboard and pointer permission prompt."
    else:
        inputs = "Keyboard and pointer access haven’t been granted for a desktop task."
    return viewing + " " + inputs
