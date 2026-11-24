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
sudo dnf install python3-qt5 python3-gobject qt5-qtwayland pipewire-utils espeak-ng libsecret
git clone https://github.com/PixelDrennen/GPTLinuxAssistant.git
cd GPTLinuxAssistant
/usr/bin/python3 scripts/install-launcher.py
```

Open **GPT Linux Assistant** from KDE’s Applications menu or search for it in KRunner. The launcher uses the checkout’s `.venv/bin/python` when available and otherwise uses system Python. If you move the checkout, run the installer again from its new location.

The app launches paused. A configured Vosk model enables the microphone when you select **Start listening**. Conversation, spoken replies, app context, editor bridges, and on-demand monitor context are on by default once their dependencies are installed. **Setup** lets you turn them off per profile. Use **Pause**, the tray menu, or “pause” to stop collection and revoke pending approvals and monitor access. Saved chat history remains available. The KDE screen-lock signal also pauses collection. Unlocking leaves it paused.

### Window context

```bash
kpackagetool6 --type=KWin/Script --install ./kwin
```

Enable **GPT Linux Assistant** in System Settings → Window Management → KWin Scripts. Start listening in the assistant, then switch focus once. The panel shows application IDs. Enter exact application IDs in the exclusion box to drop them from the working context. The KWin script shares app identity and a PID for process-name fallback. It does not capture pixels, titles, browser tabs, or keystrokes.

### Set up voice once

1. Create a virtual environment with `/usr/bin/python3 -m venv --system-site-packages .venv` and run `.venv/bin/python -m pip install vosk webrtcvad-wheels`. WebRTC VAD helps separate speech from background sound. For optional OpenAI transcription, also run `.venv/bin/python -m pip install openai`.
2. Download and extract a small English model from the [Vosk model catalog](https://alphacephei.com/vosk/models). Put the extracted model directory at `~/.local/share/gpt-linux-assistant/vosk-model`, or pass its path with `--vosk-model`.
3. Choose a model for conversation and drafting.

   - **OpenAI API.** Open **⋯ → Settings**, enter the key, and click **Save to wallet**. This selects OpenAI for the current profile. The desktop wallet keeps the key across launches and shares it across Work and Play. You can still launch with `OPENAI_API_KEY`. If the wallet has no saved key, the app imports that key when the wallet is available.

   - **Local Ollama.** Run [Ollama](https://ollama.com/) with a downloaded local model and cloud features disabled (`OLLAMA_NO_CLOUD=1` in the Ollama server environment). Launch with `.venv/bin/python -m assistant_app --ollama-model YOUR_MODEL`.

### Work by voice

The microphone waits four seconds after speech before submitting a turn. Adjust **Wait after speech** in Settings if you need more thinking time. For clearer transcripts, enable **OpenAI transcription** in Settings and use your existing API key. This sends the completed utterance to OpenAI for transcription. Vosk remains the offline option. The optional **Recognition vocabulary** field can include terms such as TradeSkillMaster, TSM, and character names. Keep a local Vosk model configured if you approve actions by voice, so the app can corroborate approval phrases locally.

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

The microphone and assistant meters use microphone audio and the assistant's local playback signal. Vosk transcribes locally. OpenAI replies use the Marin voice by default and stream audio through PipeWire as it arrives. Under **Setup**, pick **OpenAI · Cedar** for a different voice, or choose either OpenAI voice alongside local Ollama using `OPENAI_API_KEY`. The fully local voice uses eSpeak NG. The microphone pauses while the assistant speaks so playback cannot be treated as a request or approval. Wait for the microphone indicator to resume before talking. **Quiet mode** suppresses unsolicited suggestions, and **Speak replies** can mute audio. **⋯ → Manual request** opens text inputs and preview controls when useful.

When you choose an OpenAI voice, the assistant’s spoken text is sent for synthesis. When you choose OpenAI for replies, the request text, selected draft or excerpt, and up to four recent turns from the current chat and workflow can be sent to the API. By default, active session narration and focused app identity can be sent too. Turn off that scope in **Setup**. Microphone audio stays local unless you enable OpenAI transcription. The API key is stored separately in the desktop wallet.

### Look at any shareable window

Install the KDE portal and GStreamer capture packages once:

```bash
sudo dnf install xdg-desktop-portal-kde gstreamer1 gstreamer1-plugins-good pipewire-gstreamer
```

Say “Look at this window and explain what’s on screen,” or choose **⋯ → Screen sharing → View a window**. Choose the app or game in the desktop share picker. The assistant analyzes one frame and closes the window capture.

Use **⋯ → Screen sharing → View monitors** or say “Look at my screen” for fullscreen games or anything spanning multiple apps. Choose the displays you want to share. When an ordinary question needs visual context, the assistant can open the picker itself. It can then take fresh frames from the approved displays when needed for the rest of the listening session. The picker and capture availability depend on the compositor. Select **Stop monitor sharing**, say “Stop sharing,” or pause to revoke display access. Switching chats or profiles also revokes access.

If the requested panel is missing from shared monitors, the assistant can ask you to open it and check again every five seconds. Say “it’s open now” to check right away, “stop watching” to end rechecks, or “never mind” to drop the current task. You can continue with a new task in the same sentence. The completed and canceled tasks stay in chat history.

Choose a vision-capable OpenAI model such as `gpt-4.1-mini`, or a local vision model in Ollama. An OpenAI vision request sends the requested frames and question to OpenAI. The chat saves a clickable local preview of the frames sent to the model, resized to at most 1440 × 1000. The KWin metadata script is optional for visual questions.

### Desktop control

While listening, say “Use my computer to click the Accounting tab in TradeSkillMaster,” or open **⋯ → Desktop control → Start task**. Select one monitor and grant keyboard and pointer access in KDE’s Remote Desktop prompt. Desktop control uses the OpenAI computer-use tool and sends screenshots to OpenAI, independently of the text reply provider.

You can also say “go ahead and hit play on this video.” If a request sounds like a question about whether the app can do something, it explains the next step and asks if you want to proceed. “Yes” starts the task, and the input still needs review. Ask “what permissions do you have?” to distinguish viewing from control.

Each step shows the selected display and the proposed input. Review it and click **Send this input**. You can approve clicks, scrolls, drags, shortcuts, or typed text. Keyboard input needs an approved click on the intended field first. If the target area changes while you’re reviewing, the input is skipped. Say “stop desktop control,” use the tray stop action, or pause to close the session.

When the assistant speaks, a small movable overlay shows the spoken line and pulses with the voice level. Drag it by its body. Wayland window placement is managed by the compositor.

### Chats and profiles

Use **Work** or **Play** in the sidebar. Each has its own settings, chat list, and model context. **New chat** starts a fresh thread. Unselected chat history is compressed in the local SQLite database and automatically decompressed when opened. History includes transcript, replies, and activity text. Use the sidebar to resume a chat with its prior turns. Files are stored under `~/.local/share/gpt-linux-assistant/work/` and `play/` by default. Compression saves space. The history files use local filesystem permissions.

### Skills

Open **⋯ → Skills** or ask “what skills are available?” The bundled skills adapt [OpenAI’s screenshot skill](https://github.com/openai/skills/tree/main/skills/.curated/screenshot) and [Vercel Labs’ agent-desktop skill](https://github.com/vercel-labs/agent-desktop/tree/main/skills/agent-desktop) to this app. They match common requests automatically. You can also write `@screenshot take a screenshot of my window` or say “use the desktop navigation skill to open this menu.”

To add a skill, put its `SKILL.md` in `~/.local/share/gpt-linux-assistant/skills/<name>/`. Use the skill folder name as the frontmatter `name` and include a `description`. Add a comma-separated `metadata.linux-assistant-triggers` string to match requests automatically. Full YAML frontmatter uses PyYAML, which you can install with `.venv/bin/python -m pip install PyYAML`. Built-in skills need no extra package. Selected Markdown instructions are sent to the model used for the task. The app applies the instructions as guidance within its existing input review and permissions.

### Updates

Ask “what changed in the last update?” or open **⋯ → App status** for the installed revision, recent changes, and current capabilities. For a checkout cloned from GitHub, the app checks at launch and periodically while it is open. Choose **Update and restart** in the popup to install an available fast-forward update. The tray also has **Check for updates**. Updates preserve chat history and settings and stop if the source checkout has local changes. To get the version that adds the popup, update your existing checkout once with `git pull --ff-only`.

### Rider

1. Install a JDK that can read your Rider build's classes, such as JDK 25 for Rider 2026.2 or JDK 21 for Rider 2025.3. Run `bash rider/build-local.sh /path/to/Rider`, pointing to your installed Rider directory containing `lib/`. The build uses that installation's SDK jars.
2. In Rider, use Settings → Plugins → ⚙ → **Install Plugin from Disk** and choose the ZIP in `rider/build/distributions/`. Restart Rider if prompted.
3. In the assistant, start the session. Select text in a Rider editor or scratch file and right-click → **Share Selection with Work Assistant**. Ask “Finish writing this prompt for me in Rider.” Approve the exact replacement in the panel. The selected document and text range must still match when the edit runs.
4. The assistant leaves prompt submission to you. Rider's AI chat composer is outside this integration.

### Unity

1. In Unity 2022.3 or later, open Package Manager → **Add package from disk** and choose `unity/package.json` from this checkout.
2. Start the assistant session. Open the prefab in Prefab Mode, then open **Tools → GPT Linux Assistant**. Choose the source component, one empty reference field, and the destination within that prefab. Click **Share Unity connection**.
3. In the assistant, choose **Review Unity handoff** if suggested, or select the Unity workflow and click **Preview Unity connection**. The bridge rechecks the source snapshot, object identities, field state, and asset editability. Unity Undo can revert the approved edit. Save via your normal Prefab Mode workflow.
4. To try it in a sample project, import **Dialogue Reference Example** from the package's Samples tab. Add its component to two objects in the same prefab and connect the first node's `fallback` field to the second node.
5. The initial bridge handles one explicitly chosen empty top-level serialized object reference at a time. Perforce checkout stays in your normal workflow. Project-specific rules for picking dialogue destinations can be added once the dialogue schema is available.

### Browser, Slack, and other apps

Pick the workflow under **App** and paste the relevant excerpt under **Shared context**. Ask for a summary, reply, search query, form text, or another draft. Preview and approve a clipboard copy, then paste into the destination. Slack sending and browser form submission are manual. To open a page or Slack link, enter the URL and choose **Preview open link**.

## Permission model

The active session keeps app observations, shared editor targets, and full-resolution monitor frames in memory. Chat transcript, replies, and activity text are saved in the selected profile. The microphone and KWin sources are separate switches. KWin publishes window metadata only when the assistant has opted in during an active session. Editor bridges publish a selected target only after an explicit share. The same-user bridges use an authenticated loopback endpoint with a private runtime credential. An approved edit is single-use and expires if the editor fails to claim it. If an edit has already been handed to the editor, inspect the reported outcome and use the editor's undo command if needed.

The broker exposes no shell or generic input control. Ollama receives text and returns draft text, with no assistant tools or credentials. A local process running as the same Linux user remains inside the system's normal user trust boundary.

## Checks

```bash
python3 -m unittest discover -s tests -v
node --check kwin/contents/code/main.js
QT_QPA_PLATFORM=offscreen PYTHONPATH=. /usr/bin/python3 tests/voice_smoke.py
```

For a desktop smoke test, deny an edit and verify that the target remains untouched, approve it and use Undo, then change the target during a preview and verify that approval is rejected. Test screen lock and resume on the target Plasma session.
