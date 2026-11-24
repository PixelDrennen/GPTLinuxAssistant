---
{
  "name": "screenshot",
  "description": "Capture or inspect an approved screen or window. Use for screenshots, reading visible UI or identifying an open panel.",
  "license": "Apache-2.0",
  "metadata": {
    "source": "https://github.com/openai/skills/tree/49f948faa9258a0c61caceaf225e179651397431/skills/.curated/screenshot",
    "linux-assistant-triggers": "screenshot,screen capture,capture my screen,look at my screen,look at this screen,look at this window,look at my window,what do you see"
  }
}
---

# Screenshot

Adapted from the OpenAI screenshot skill for GPT Linux Assistant’s Wayland portal and chat history.

1. Select the narrowest source that covers the request. Use the window picker for a named app. Use a display when the task spans windows or the user asks to see the whole screen.
2. Use the app’s existing ScreenCast flow and wait for the user to finish the picker. If the permission prompt covers the target, wait for a clean frame.
3. Verify the requested window or panel is visible before describing it. Identify uncertain or obscured values, and ask the user to reveal the panel if needed.
4. The captured preview appears in chat. Report what the frame showed. Only promise to save elsewhere if the app actually provides that operation.
