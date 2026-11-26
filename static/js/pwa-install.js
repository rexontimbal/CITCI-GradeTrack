// Captures Chrome/Android's install prompt so the app can offer its own
// "Install App" button (in the sidebar user-card popover) instead of
// relying on users to find it buried in the browser's own menu.
// Fires no-op on browsers that never dispatch beforeinstallprompt
// (iOS Safari, or when the app is already installed) -- the button
// just stays hidden in that case.
let deferredInstallPrompt = null;

window.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault();
    deferredInstallPrompt = event;
    window.dispatchEvent(new CustomEvent("pwa-install-available"));
});

window.addEventListener("appinstalled", () => {
    deferredInstallPrompt = null;
    window.dispatchEvent(new CustomEvent("pwa-install-consumed"));
});

window.triggerPwaInstall = async function () {
    if (!deferredInstallPrompt) return;
    deferredInstallPrompt.prompt();
    await deferredInstallPrompt.userChoice;
    deferredInstallPrompt = null;
    window.dispatchEvent(new CustomEvent("pwa-install-consumed"));
};
