"""Store the OpenAI credential in the desktop Secret Service."""
import subprocess


ATTRIBUTES = ("application", "io.github.PixelDrennen.WorkAssistant", "credential", "openai-api")


def secret_tool(*args, value=None):
    try:
        return subprocess.run(["secret-tool", *args], input=value, text=True, capture_output=True,
                              timeout=30, check=False)
    except FileNotFoundError:
        raise RuntimeError("Install libsecret to save keys in your desktop wallet.") from None
    except subprocess.TimeoutExpired:
        raise RuntimeError("The desktop wallet did not respond. Unlock it and try again.") from None
    except OSError:
        raise RuntimeError("The desktop wallet could not be reached.") from None


def read_key():
    result = secret_tool("lookup", *ATTRIBUTES)
    if result.returncode and result.stderr.strip():
        raise RuntimeError("The desktop wallet could not be opened. Unlock it and try again.")
    return result.stdout.strip() if not result.returncode else ""


def save_key(key):
    if not key or any(char.isspace() or ord(char) < 32 for char in key):
        raise ValueError("Enter a valid OpenAI API key.")
    result = secret_tool("store", "--label=GPT Linux Assistant OpenAI API key", *ATTRIBUTES, value=key)
    if result.returncode:
        raise RuntimeError("Could not save the API key. Unlock your desktop wallet and try again.")
