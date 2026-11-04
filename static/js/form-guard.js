// Disables a plain (non-HTMX) form's submit button(s) on submit, to block
// double-submission while a request is in flight (Phase 8 part A). HTMX
// forms/buttons already get this for free via the global .htmx-request CSS
// rule in .django_tailwind_cli/source.css, so this only needs to handle
// forms that don't carry hx-post/hx-get themselves.
document.addEventListener("submit", (event) => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement)) return;
    if (form.hasAttribute("hx-post") || form.hasAttribute("hx-get") || form.hasAttribute("hx-put")) return;

    form.querySelectorAll("button[type='submit'], input[type='submit']").forEach((btn) => {
        if (btn.disabled) return;
        btn.disabled = true;
        btn.classList.add("opacity-60", "pointer-events-none");
    });
});
