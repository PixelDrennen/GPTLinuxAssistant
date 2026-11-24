# GPT Linux Assistant

A tray assistant for Fedora KDE Plasma 6 on Wayland. Start a listening session, enable the context sources you want, and talk through your work. Every edit, clipboard copy, and browser launch initiated by the assistant needs a one-use approval.

| App | What v0.1 can do |
| --- | --- |
| Unity | Offer a handoff when your narration and open apps indicate dialogue wiring. Preview and fill one empty component reference in the open prefab after you explicitly share the source, field, and destination. |
| Rider | Complete a selected prompt in an editor document or scratch file, including unsaved text. Preview the full replacement and apply it as one undoable edit. |
| Browser | Answer questions or summarize page text you paste in. Preview an HTTP or HTTPS URL and open it in your default browser after approval. |
| Slack | Draft replies or summarize excerpts you paste in. Copy the approved draft for you to paste into Slack. |
| Other apps | Draft text from a task and optional shared excerpt. Copy the result after approval. |

## Run on Fedora

```bash
sudo dnf install python3-qt5 python3-gobject qt5-qtwayland pipewire-utils
git clone https://github.com/PixelDrennen/GPTLinuxAssistant.git
cd GPTLinuxAssistant
/usr/bin/python3 -m assistant_app
```

The app launches paused with all observation sources and editor bridges off. **Start listening** starts the session. Use **Pause** or the tray menu to clear the session and revoke pending approvals. The KDE screen-lock signal also pauses collection. Unlocking leaves it paused.

### Window context

```bash
kpackagetool6 --type=KWin/Script --install ./kwin
```

Enable **GPT Linux Assistant** in System Settings → Window Management → KWin Scripts. In the assistant, enable **Use KWin app identities**, then switch focus once. The panel shows application IDs. Enter exact application IDs in the exclusion box to drop them from the working context. The KWin script shares app identity and a PID for process-name fallback. It does not capture pixels, titles, browser tabs, or keystrokes.

### Voice and drafting

- For local speech recognition, create a virtual environment with `/usr/bin/python3 -m venv --system-site-packages .venv`, install with `.venv/bin/python -m pip install vosk`, and download and extract an English model from the [Vosk model catalog](https://alphacephei.com/vosk/models). Launch with `.venv/bin/python -m assistant_app --vosk-model /path/to/extracted/model` and turn on **Use microphone (Vosk)**.
- Narrate normally to give the assistant context. Use **Ask by voice** or start a request with “Assistant” to address it directly. When a preview is visible, click **Answer by voice** and say “yes” or “no,” or use the approval buttons. A “yes” in regular narration cannot approve anything. Quiet mode suppresses proactive offers.
- For generated drafts, run [Ollama](https://ollama.com/) with a downloaded local model and cloud features disabled (`OLLAMA_NO_CLOUD=1` in the Ollama server environment). Enter the model name in the app and tell it what to draft. The app sends the requested text to Ollama on loopback and includes recent narration only if you enable that option. If you prefer to skip model setup, type the replacement directly in **Draft** and use the preview button.

### Rider

1. With JDK 21 and Gradle 9 installed, run `gradle -p rider buildPlugin` from the repository. To target another supported Rider version, add `-PriderVersion=<version>`.
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
```

For a desktop smoke test, deny an edit and verify that the target remains untouched, approve it and use Undo, then change the target during a preview and verify that approval is rejected. Test screen lock and resume on the target Plasma session.
