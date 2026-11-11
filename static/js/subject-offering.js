// Bulk-selection state for the Subjects page's "Offer" checkboxes: per-
// table and per-year-level "select all" headers (indeterminate when only
// some of their rows are checked), a page-wide "select all", and the
// sticky bottom bar's running "n subjects selected · x units" total.
// Already-offered rows are checked+disabled server-side and never appear
// in `ids` arrays passed to this component, so every "select all" already
// skips them.
document.addEventListener("alpine:init", () => {
    Alpine.data("subjectOffering", (unitsById) => ({
        selected: [],
        unitsById: unitsById || {},

        toggle(id) {
            const idx = this.selected.indexOf(id);
            if (idx === -1) {
                this.selected.push(id);
            } else {
                this.selected.splice(idx, 1);
            }
        },

        isSelected(id) {
            return this.selected.includes(id);
        },

        allChecked(ids) {
            return ids.length > 0 && ids.every((id) => this.selected.includes(id));
        },

        someChecked(ids) {
            return ids.some((id) => this.selected.includes(id));
        },

        onHeaderToggle(ids, checked) {
            if (checked) {
                ids.forEach((id) => {
                    if (!this.selected.includes(id)) this.selected.push(id);
                });
            } else {
                this.selected = this.selected.filter((id) => !ids.includes(id));
            }
        },

        clearAll() {
            this.selected = [];
        },

        get count() {
            return this.selected.length;
        },

        get totalUnits() {
            return this.selected.reduce((sum, id) => sum + (parseFloat(this.unitsById[id]) || 0), 0);
        },
    }));
});
