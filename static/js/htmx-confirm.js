// Replaces the native browser confirm() dialog for every hx-confirm="..."
// attribute app-wide with the shared premium confirm dialog in base.html
// (Alpine state: confirmOpen/confirmMessage/confirmAction, opened here via
// the "open-confirm" window event). htmx fires htmx:confirm before issuing
// any request that carries hx-confirm; evt.detail.issueRequest(true) is
// htmx's own documented way to resume that request once confirmed.
document.body.addEventListener("htmx:confirm", function (evt) {
    if (!evt.detail.question) return;
    evt.preventDefault();
    window.dispatchEvent(
        new CustomEvent("open-confirm", {
            detail: {
                message: evt.detail.question,
                onConfirm: () => evt.detail.issueRequest(true),
            },
        })
    );
});
