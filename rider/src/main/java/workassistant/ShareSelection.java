package workassistant;

import com.google.gson.JsonObject;
import com.intellij.openapi.actionSystem.ActionUpdateThread;
import com.intellij.openapi.actionSystem.AnAction;
import com.intellij.openapi.actionSystem.AnActionEvent;
import com.intellij.openapi.actionSystem.CommonDataKeys;
import com.intellij.openapi.application.ApplicationManager;
import com.intellij.openapi.command.WriteCommandAction;
import com.intellij.openapi.editor.Document;
import com.intellij.openapi.editor.Editor;
import com.intellij.openapi.fileEditor.FileDocumentManager;
import com.intellij.openapi.fileEditor.FileEditorManager;
import com.intellij.openapi.project.Project;
import com.intellij.openapi.ui.Messages;
import com.intellij.util.concurrency.AppExecutorUtil;
import org.jetbrains.annotations.NotNull;

import java.util.UUID;
import java.util.concurrent.TimeUnit;

public final class ShareSelection extends AnAction {
    private static final String TITLE = "GPT Linux Assistant";

    @Override
    public @NotNull ActionUpdateThread getActionUpdateThread() {
        return ActionUpdateThread.EDT;
    }

    @Override
    public void update(@NotNull AnActionEvent event) {
        Editor editor = event.getData(CommonDataKeys.EDITOR);
        event.getPresentation().setEnabled(event.getProject() != null && editor != null
                && editor.getCaretModel().getCaretCount() == 1 && editor.getSelectionModel().hasSelection());
    }

    @Override
    public void actionPerformed(@NotNull AnActionEvent event) {
        Editor editor = event.getData(CommonDataKeys.EDITOR);
        Project project = event.getProject();
        if (editor == null || project == null || editor.getCaretModel().getCaretCount() != 1) {
            return;
        }
        var selection = editor.getSelectionModel();
        String original = selection.getSelectedText();
        if (original == null || original.isBlank() || original.length() > 16000) {
            Messages.showWarningDialog(project, "Select a nonempty draft of up to 16,000 characters.", TITLE);
            return;
        }
        Document document = editor.getDocument();
        var file = FileDocumentManager.getInstance().getFile(document);
        String label = project.getName() + " / " + (file == null ? "Editor selection" : file.getName());
        Capture target = new Capture(project, editor, document, selection.getSelectionStart(),
                selection.getSelectionEnd(), document.getModificationStamp(), original,
                UUID.randomUUID().toString().replace("-", ""), System.nanoTime());
        ApplicationManager.getApplication().executeOnPooledThread(() -> share(target, label));
    }

    private static void share(Capture target, String label) {
        try {
            Bridge bridge = Bridge.connect();
            JsonObject body = new JsonObject();
            body.addProperty("label", label);
            JsonObject data = new JsonObject();
            data.addProperty("text", target.original());
            data.addProperty("start", target.start());
            data.addProperty("end", target.end());
            body.add("data", data);
            bridge.send("/capture", target.id(), body);
            schedulePoll(bridge, target);
        } catch (Exception error) {
            ApplicationManager.getApplication().invokeLater(() -> {
                if (!target.project().isDisposed()) {
                    Messages.showWarningDialog(target.project(),
                            "Could not share the selection. Start the assistant and enable Rider.\n" + error.getMessage(),
                            TITLE);
                }
            });
        }
    }

    private static void schedulePoll(Bridge bridge, Capture target) {
        AppExecutorUtil.getAppScheduledExecutorService().schedule(() -> poll(bridge, target),
                400, TimeUnit.MILLISECONDS);
    }

    private static void poll(Bridge bridge, Capture target) {
        if (target.project().isDisposed() || System.nanoTime() - target.created() >= TimeUnit.SECONDS.toNanos(190)) {
            return;
        }
        try {
            JsonObject result = bridge.send("/poll", target.id(), new JsonObject());
            if (result.has("id")) {
                String id = result.get("id").getAsString();
                String replacement = result.get("replacement").getAsString();
                long received = System.nanoTime();
                ApplicationManager.getApplication().invokeLater(() -> {
                    String outcome = System.nanoTime() - received > TimeUnit.SECONDS.toNanos(2)
                            ? "stale" : apply(target, replacement);
                    ApplicationManager.getApplication().executeOnPooledThread(() -> finish(bridge, target, id, outcome));
                });
            } else if (result.has("waiting") && result.get("waiting").getAsBoolean()) {
                schedulePoll(bridge, target);
            }
        } catch (Exception ignored) {
            // A paused or unavailable assistant revokes the capture.
        }
    }

    private static String apply(Capture target, String replacement) {
        Project project = target.project();
        if (project.isDisposed() || target.editor().isDisposed() || replacement.isBlank()
                || replacement.length() > 48000) {
            return "stale";
        }
        String[] outcome = {"stale"};
        try {
            WriteCommandAction.writeCommandAction(project).withName("Apply Work Assistant draft").run(() -> {
                Document document = target.document();
                var selection = target.editor().getSelectionModel();
                if (FileEditorManager.getInstance(project).getSelectedTextEditor() != target.editor()
                        || target.editor().getCaretModel().getCaretCount() != 1
                        || !document.isWritable() || document.getModificationStamp() != target.stamp()
                        || target.end() > document.getTextLength()
                        || selection.getSelectionStart() != target.start() || selection.getSelectionEnd() != target.end()
                        || !target.original().contentEquals(document.getCharsSequence().subSequence(target.start(), target.end()))) {
                    return;
                }
                document.replaceString(target.start(), target.end(), replacement.replace("\r\n", "\n").replace('\r', '\n'));
                outcome[0] = "applied";
            });
        } catch (RuntimeException error) {
            return "failed";
        }
        return outcome[0];
    }

    private static void finish(Bridge bridge, Capture target, String id, String outcome) {
        JsonObject body = new JsonObject();
        body.addProperty("id", id);
        body.addProperty("outcome", outcome);
        try {
            bridge.send("/finish", target.id(), body);
        } catch (Exception ignored) {
            // The broker reports a missing receipt if the session is still active.
        }
    }

    private record Capture(Project project, Editor editor, Document document, int start, int end,
                           long stamp, String original, String id, long created) {}
}
