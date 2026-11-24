const service = "io.github.PixelDrennen.WorkAssistant";
const path = "/io/github/PixelDrennen/WorkAssistant";
let revision = 0;

function isApplication(window) {
    return window && window.normalWindow;
}

function identity(window) {
    return {
        app: String(window.desktopFileName || window.resourceClass || ""),
        pid: Number(window.pid || 0)
    };
}

function publish() {
    const request = ++revision;
    callDBus(service, path, service, "WantsWindows", function (enabled) {
        if (request !== revision || enabled !== true) {
            return;
        }
        const focus = workspace.activeWindow;
        const windows = [];
        const order = workspace.stackingOrder;
        for (let index = order.length - 1; index >= 0 && windows.length < 100; index--) {
            if (isApplication(order[index])) {
                windows.push(identity(order[index]));
            }
        }
        callDBus(service, path, service, "Observe", JSON.stringify({
            focus: isApplication(focus) ? identity(focus) : null,
            windows: windows
        }));
    });
}

workspace.windowActivated.connect(publish);
workspace.windowAdded.connect(publish);
workspace.windowRemoved.connect(publish);
publish();
