// Bulk-selection state for the Classes page: row checkboxes + a header
// "select all" (indeterminate when some but not all are checked), and the
// sticky bottom bar's instructor/room/schedule actions. Each bulk action
// fans out to the same per-row class_update_field endpoint the inline
// edits already use (one POST per selected class, `silent=1` so only one
// combined toast fires instead of one per row) -- no separate bulk
// endpoint to keep in sync with it.
document.addEventListener("alpine:init", () => {
    Alpine.data("classBulkSelect", (urlTemplate) => ({
        selected: [],
        roomValue: "",
        scheduleValue: "",
        urlTemplate: urlTemplate,

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

        _rowUrl(id) {
            return this.urlTemplate.replace("/0/update-field/", "/" + id + "/update-field/");
        },

        _bulkPost(field, value, successMessage) {
            const ids = [...this.selected];
            const requests = ids.map((id) =>
                htmx.ajax("POST", this._rowUrl(id), {
                    target: "#class-row-" + id,
                    swap: "outerHTML",
                    values: { field: field, value: value, silent: "1" },
                })
            );
            Promise.all(requests).then(() => {
                window.dispatchEvent(new CustomEvent("toast", { detail: { message: successMessage, level: "success" } }));
            });
        },

        assignInstructor(instructorId) {
            if (this.count === 0) return;
            const label = instructorId
                ? document.querySelector('option[value="' + instructorId + '"]')?.textContent?.trim() || "Instructor"
                : "Unassigned";
            this._bulkPost("instructor", instructorId, `${label} assigned to ${this.count} class${this.count === 1 ? "" : "es"}.`);
        },

        setRoom() {
            if (this.count === 0 || !this.roomValue) return;
            this._bulkPost("room", this.roomValue, `Room updated for ${this.count} class${this.count === 1 ? "" : "es"}.`);
            this.roomValue = "";
        },

        setSchedule() {
            if (this.count === 0 || !this.scheduleValue) return;
            this._bulkPost("schedule", this.scheduleValue, `Schedule updated for ${this.count} class${this.count === 1 ? "" : "es"}.`);
            this.scheduleValue = "";
        },
    }));
});
