// Reusable searchable <select> replacement: a text box that live-filters
// options via HTMX as you type, with full keyboard navigation. Used by
// core.widgets.SearchableSelectWidget (templates/partials/_searchable_select_widget.html).
document.addEventListener("alpine:init", () => {
    Alpine.data("searchableSelect", (initialValue, initialLabel) => ({
        open: false,
        query: initialLabel || "",
        value: initialValue || "",
        highlightedIndex: -1,

        select(value, label) {
            this.value = value;
            this.query = label;
            this.open = false;
            this.highlightedIndex = -1;
        },

        clear() {
            this.value = "";
            this.query = "";
        },

        onKeydown(event) {
            const items = this.$refs.list ? Array.from(this.$refs.list.querySelectorAll("[data-option]")) : [];
            if (!items.length) return;

            if (event.key === "ArrowDown") {
                event.preventDefault();
                this.open = true;
                items.forEach((item) => item.classList.remove("bg-gray-100"));
                this.highlightedIndex = Math.min(this.highlightedIndex + 1, items.length - 1);
                items[this.highlightedIndex].classList.add("bg-gray-100");
                items[this.highlightedIndex].scrollIntoView({ block: "nearest" });
            } else if (event.key === "ArrowUp") {
                event.preventDefault();
                items.forEach((item) => item.classList.remove("bg-gray-100"));
                this.highlightedIndex = Math.max(this.highlightedIndex - 1, 0);
                items[this.highlightedIndex].classList.add("bg-gray-100");
                items[this.highlightedIndex].scrollIntoView({ block: "nearest" });
            } else if (event.key === "Enter") {
                event.preventDefault();
                const item = items[this.highlightedIndex] || items[0];
                if (item) item.click();
            } else if (event.key === "Escape") {
                this.open = false;
            }
        },
    }));
});
