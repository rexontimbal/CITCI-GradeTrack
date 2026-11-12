// The Setup tab's "By component" / "By term" toggle -- remembered per
// browser (localStorage), not per class, since an instructor who prefers
// the matrix view almost certainly prefers it everywhere. Wrapped in
// try/catch: a sandboxed/private-browsing context can throw on storage
// access, and the toggle should still work for that page load either way.
const SETUP_VIEW_STORAGE_KEY = "gradetrack-setup-view";

document.addEventListener("alpine:init", () => {
    Alpine.data("setupViewToggle", () => ({
        view: "component",

        init() {
            try {
                const stored = localStorage.getItem(SETUP_VIEW_STORAGE_KEY);
                if (stored === "component" || stored === "term") this.view = stored;
            } catch (e) {
                // ignore -- default view stands
            }
        },

        setView(view) {
            this.view = view;
            try {
                localStorage.setItem(SETUP_VIEW_STORAGE_KEY, view);
            } catch (e) {
                // ignore -- in-memory choice still applies for this page load
            }
        },
    }));
});
