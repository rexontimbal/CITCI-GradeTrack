// Shared "..." row-action menu (Classes, Subjects, Class Record, Setup tab
// item rows, and anywhere else a menu button lives inside a scrolling
// container). A plain `position: fixed` child of a scroll container still
// gets clipped by that container's overflow box in every browser -- the
// only reliable fix is to not be a DOM descendant of it at all, so the menu
// panel is teleported to <body> (x-teleport in the template) and
// positioned here from the trigger button's own bounding rect.
document.addEventListener("alpine:init", () => {
    Alpine.data("floatingMenu", () => ({
        open: false,
        top: 0,
        left: 0,
        _reposition: null,

        toggle() {
            if (this.open) this.close();
            else this.openMenu();
        },

        openMenu() {
            this.open = true;
            this.$nextTick(() => {
                this.position();
                this._reposition = () => this.position();
                // capture:true -- a scroll inside any ancestor (the grid's
                // own scroll container, not just the window) must reposition
                // the menu too, and only the capture phase sees those.
                window.addEventListener("scroll", this._reposition, true);
                window.addEventListener("resize", this._reposition);
            });
        },

        close() {
            if (!this.open) return;
            this.open = false;
            if (this._reposition) {
                window.removeEventListener("scroll", this._reposition, true);
                window.removeEventListener("resize", this._reposition);
                this._reposition = null;
            }
            if (this.$refs.trigger) this.$refs.trigger.focus();
        },

        position() {
            const btn = this.$refs.trigger;
            const menu = this.$refs.menu;
            if (!btn || !menu) return;
            const rect = btn.getBoundingClientRect();
            const menuRect = menu.getBoundingClientRect();
            const vw = window.innerWidth;
            const vh = window.innerHeight;

            const fitsBelow = vh - rect.bottom >= menuRect.height + 8;
            this.top = fitsBelow ? rect.bottom + 4 : Math.max(8, rect.top - menuRect.height - 4);

            let left = rect.right - menuRect.width;
            if (left < 8) left = rect.left;
            if (left + menuRect.width > vw - 8) left = vw - menuRect.width - 8;
            this.left = Math.max(8, left);
        },

        _items() {
            return this.$refs.menu ? Array.from(this.$refs.menu.querySelectorAll('[role="menuitem"]')) : [];
        },

        focusNext() {
            const items = this._items();
            if (!items.length) return;
            const i = items.indexOf(document.activeElement);
            items[(i + 1) % items.length].focus();
        },

        focusPrev() {
            const items = this._items();
            if (!items.length) return;
            const i = items.indexOf(document.activeElement);
            items[(i - 1 + items.length) % items.length].focus();
        },

        onTriggerKeydown() {
            if (!this.open) this.openMenu();
            this.$nextTick(() => this.focusNext());
        },
    }));
});
