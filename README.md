# GPT Linux Assistant

A voice-first tray assistant for Fedora KDE Plasma 6 on Wayland. Start a listening session and speak while you work. The dashboard shows both voice signals, live recognition, and a running activity log. Every edit, clipboard copy, and browser launch initiated by the assistant needs a one-use approval.

| App | What it can do |
| --- | --- |
| Unity | Offer a handoff when your narration and open apps indicate dialogue wiring. Preview and fill one empty component reference in the open prefab after you explicitly share the source, field, and destination. |
| Rider | Complete a selected prompt in an editor document or scratch file, including unsaved text. Preview the full replacement and apply it as one undoable edit. |
| Browser | Answer questions or summarize page text you paste in. Preview an HTTP or HTTPS URL and open it in your default browser after approval. |
| Slack | Draft replies or summarize excerpts you paste in. Copy the approved draft for you to paste into Slack. |
| Other apps | Draft text from a task and optional shared excerpt. Copy the result after approval. |

## Run on Fedora

```bash
sudo dnf install python3-qt5 python3-gobject qt5-qtwayland pipewire-utils espeak-ng
git clone https://github.com/PixelDrennen/GPTLinuxAssistant.git
cd GPTLinuxAssistant
/usr/bin/python3 -m assistant_app
```

The app launches paused. A configured Vosk model enables the microphone when you select **Start listening**. Window context and editor bridges have separate opt-ins under **Setup**. Use **Pause**, the tray menu, or “pause” to clear the in-memory log and revoke pending approvals. The KDE screen-lock signal also pauses collection. Unlocking leaves it paused.

### Window context

```bash
kpackagetool6 --type=KWin/Script --install ./kwin
```

Enable **GPT Linux Assistant** in System Settings → Window Management → KWin Scripts. In the assistant, enable **Use KWin app identities**, then switch focus once. The panel shows application IDs. Enter exact application IDs in the exclusion box to drop them from the working context. The KWin script shares app identity and a PID for process-name fallback. It does not capture pixels, titles, browser tabs, or keystrokes.

### Set up voice once

1. Create a virtual environment with `/usr/bin/python3 -m venv --system-site-packages .venv` and run `.venv/bin/python -m pip install vosk`.
2. Download and extract a small English model from the [Vosk model catalog](https://alphacephei.com/vosk/models). Put the extracted model directory at `~/.local/share/gpt-linux-assistant/vosk-model`, or pass its path with `--vosk-model`.
3. Choose a model for conversation and drafting.

   - **OpenAI API.** Launch with the API key in your environment. The prompt below accepts it without displaying it or putting the key itself into shell history.

     ```bash
     read -rsp 'OpenAI API key: ' OPENAI_API_KEY
     printf '\n'
     export OPENAI_API_KEY
     .venv/bin/python -m assistant_app --openai-model gpt-4.1-mini
     ```

   - **Local Ollama.** Run [Ollama](https://ollama.com/) with a downloaded local model and cloud features disabled (`OLLAMA_NO_CLOUD=1` in the Ollama server environment). Launch with `.venv/bin/python -m assistant_app --ollama-model YOUR_MODEL`.

### Work by voice

Select **Start listening** once. Conversation mode is on by default. Speak your request or answer normally. To think aloud without sending each utterance to the reply model, turn off **Conversation mode** under Setup. In that mode you can still say “Assistant” before a request, pause briefly after the wake word, or click **Ask by voice**.

| Say | What happens |
| --- | --- |
| “what am I working on?” | Hear the current local task summary. |
| “finish this prompt in Rider.” | Hear what to share if a draft is missing. Sharing a selection within 90 seconds resumes the request automatically. |
| “help me connect this Unity prefab.” | Share a prefab reference from Unity, then review the proposed connection. |
| “write a Slack update about the prefab changes.” | Hear the draft or a clarifying question. Answer the question naturally. |
| “copy that.” | Review the proposed clipboard copy. |
| “Approve it” or “Decline it” | Respond to the single visible approval preview after the announcement ends. |
| “repeat that” or “pause” | Replay the last model reply or stop the session. |

The microphone and assistant meters use microphone audio and the assistant's local playback signal. Vosk transcribes locally. OpenAI replies use the Marin voice by default and stream audio through PipeWire as it arrives. Under **Setup**, pick **OpenAI · Cedar** for a different voice, or choose either OpenAI voice alongside local Ollama using `OPENAI_API_KEY`. The fully local voice uses eSpeak NG. The microphone pauses while the assistant speaks so playback cannot be treated as a request or approval. Wait for the microphone indicator to resume before talking. **Quiet mode** suppresses unsolicited suggestions, and **Speak replies** can mute audio. **Manual controls** exposes text inputs and preview controls when useful.

When you choose an OpenAI voice, the assistant’s spoken text is sent for synthesis. When you choose OpenAI for replies, the request text, selected draft or excerpt, and the previous turn in the same voice workflow can be sent to the API. The separate narration checkbox also allows sending recent narration and focused app identity. Microphone audio stays local, and the app uses the API key from the environment without saving it.

### Look at any shareable window

Install the KDE portal and GStreamer capture packages once:

```bash
sudo dnf install xdg-desktop-portal-kde gstreamer1 gstreamer1-plugins-good pipewire-gstreamer
```

Say “Look at this window and explain what’s on screen,” or click **Look at a window**. Choose the app or game in the desktop share picker. The assistant analyzes one frame with the selected vision-capable model, closes capture, and speaks the answer. For a fullscreen game that the picker cannot list as a window, say “Look at my screen” and share the display. This includes everything visible on that display. Availability depends on what the compositor and the game or app allow you to capture.

Choose a vision-capable OpenAI model such as `gpt-4.1-mini`, or a local vision model in Ollama. An OpenAI vision request sends the selected image and question to OpenAI. The app does not save the image, continuously monitor the source, or send input to it. The KWin metadata script is optional for visual questions.

### Rider

1. Install a JDK that can read your Rider build's classes, such as JDK 25 for Rider 2026.2 or JDK 21 for Rider 2025.3. Run `bash rider/build-local.sh /path/to/Rider`, pointing to your installed Rider directory containing `lib/`. The build uses that installation's SDK jars.
2. In Rider, use Settings → Plugins → ⚙ → **Install Plugin from Disk** and choose the ZIP in `rider/build/distributions/`. Restart Rider if prompted.
3. In the assistant, start the session and enable **Rider**. Select text in a Rider editor or scratch file and right-click → **Share Selection with Work Assistant**. Ask “Finish writing this prompt for me in Rider.” Approve the exact replacement in the panel. The selected document and text range must still match when the edit runs.
4. The assistant leaves prompt submission to you. Rider's AI chat composer is outside this integration.

### Unity

1. In Unity 2022.3 or later, open Package Manager → **Add package from disk** and choose `unity/package.json` from this checkout.
2. Start the assistant session and enable **Unity**. Open the prefab in Prefab Mode, then open **Tools → GPT Linux Assistant**. Choose the source component, one empty reference field, and the destination within that prefab. Click **Share Unity connection**.
3. In the assistant, choose **Review Unity handoff** if suggested, or select the Unity workflow and click **Preview Unity connection**. The bridge rechecks the source snapshot, object identities, field state, and asset editability. Unity Undo can revert the approved edit. Save via your normal Prefab Mode workflow.
4. To try it in a sample project, import **Dialogue Reference Example** from the package's Samples tab. Add its component to two objects in the same prefab and connect the first node's `fallback` field to the second node.
5. The initial bridge handles one explicitly chosen empty top-level serialized object reference at a time. Perforce checkout stays in your normal workflow. Project-specific rules for picking dialogue destinations can be added once the dialogue schema is available.

### Browser, Slack, and other apps

Pick the workflow under **App** and paste the relevant excerpt under **Shared context**. Ask for a summary, reply, search query, form text, or another draft. Preview and approve a clipboard copy, then paste into the destination. Slack sending and browser form submission are manual. To open a page or Slack link, enter the URL and choose **Preview open link**.

## Permission model

The session keeps recent observations and shared context in memory. The microphone and KWin sources are separate switches. KWin publishes window metadata only when the assistant has opted in during an active session. Editor bridges publish a selected target only after an explicit share. The same-user bridges use an authenticated loopback endpoint with a private runtime credential. An approved edit is single-use and expires if the editor fails to claim it. If an edit has already been handed to the editor, inspect the reported outcome and use the editor's undo command if needed.

The broker exposes no shell or generic input control. Ollama receives text and returns draft text, with no assistant tools or credentials. A local process running as the same Linux user remains inside the system's normal user trust boundary.

## Checks

```bash
python3 -m unittest discover -s tests -v
node --check kwin/contents/code/main.js
QT_QPA_PLATFORM=offscreen PYTHONPATH=. /usr/bin/python3 tests/voice_smoke.py
```

For a desktop smoke test, deny an edit and verify that the target remains untouched, approve it and use Undo, then change the target during a preview and verify that approval is rejected. Test screen lock and resume on the target Plasma session.
