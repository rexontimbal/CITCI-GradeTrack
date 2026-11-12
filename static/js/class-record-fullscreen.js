// Full-screen toggle for the Class Record grid (Setup/Class Record/
// Summary page). Prefers the browser Fullscreen API on the grid's own
// root element (hides the sidebar/topbar automatically, by definition,
// since they're outside that element) -- falls back to a plain CSS
// fixed-inset-0 overlay when the API isn't available (e.g. a sandboxed
// iframe). Esc exits either way: the native API fires "fullscreenchange"
// on its own Esc handling; the CSS fallback needs an explicit listener.
document.addEventListener("alpine:init", () => {
    Alpine.data("classRecordFullScreen", () => ({
        fullScreen: false,

        toggle() {
            if (this.fullScreen) {
                this.exit();
                return;
            }
            const el = this.$refs.recordRoot;
            if (el.requestFullscreen) {
                el.requestFullscreen().catch(() => {});
            }
            this.fullScreen = true;
        },

        exit() {
            if (document.fullscreenElement) {
                document.exitFullscreen().catch(() => {});
            }
            this.fullScreen = false;
        },

        init() {
            document.addEventListener("fullscreenchange", () => {
                if (!document.fullscreenElement) this.fullScreen = false;
            });
        },
    }));
});
