// Bulk-selection state for the Subjects page. Two independent selection
// sets share one "Select" toggle (selectMode) that shows/hides every
// checkbox on the page at once -- off by default, so browsing the
// prospectus never shows a wall of checkboxes:
//   - `selected` (blue checkboxes, .offer-checkbox): not-yet-offered rows,
//     feeds "Offer selected" -> subject_offering_preview.
//   - `withdrawSelected` (red checkboxes, .withdraw-checkbox): already-
//     offered rows, feeds "Withdraw selected" -> subject_offering_bulk_
//     withdraw with an explicit offering_ids list -- this is now the ONLY
//     way to withdraw more than one at a time ("Withdraw all"/"Withdraw
//     all {Year}" were removed as redundant once this existed).
// Each table/year-level card has exactly one "select all" header
// checkbox, which toggles BOTH colors in its scope together (see the
// *Mixed methods below) -- there's no separate second header for
// withdraw-only, one shortcut covers whichever rows are actually there.
document.addEventListener("alpine:init", () => {
    Alpine.data("subjectOffering", (unitsById) => ({
        selectMode: false,
        selected: [],
        withdrawSelected: [],
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

        toggleWithdraw(id) {
            const idx = this.withdrawSelected.indexOf(id);
            if (idx === -1) {
                this.withdrawSelected.push(id);
            } else {
                this.withdrawSelected.splice(idx, 1);
            }
        },

        isWithdrawSelected(id) {
            return this.withdrawSelected.includes(id);
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

        // One "select all" header shortcut covers both colors at once --
        // there's no separate "select all for withdraw" control, this IS
        // it: a table/year-level card's header checkbox selects every
        // not-yet-offered row (blue, offerIds) and every already-offered
        // row (red, withdrawIds) it has, together.
        allCheckedMixed(offerIds, withdrawIds) {
            const total = offerIds.length + withdrawIds.length;
            if (total === 0) return false;
            return offerIds.every((id) => this.selected.includes(id)) && withdrawIds.every((id) => this.withdrawSelected.includes(id));
        },

        someCheckedMixed(offerIds, withdrawIds) {
            return offerIds.some((id) => this.selected.includes(id)) || withdrawIds.some((id) => this.withdrawSelected.includes(id));
        },

        onHeaderToggleMixed(offerIds, withdrawIds, checked) {
            this.onHeaderToggle(offerIds, checked);
            if (checked) {
                withdrawIds.forEach((id) => {
                    if (!this.withdrawSelected.includes(id)) this.withdrawSelected.push(id);
                });
            } else {
                this.withdrawSelected = this.withdrawSelected.filter((id) => !withdrawIds.includes(id));
            }
        },

        clearAll() {
            this.selected = [];
            this.withdrawSelected = [];
        },

        get count() {
            return this.selected.length;
        },

        get totalUnits() {
            return this.selected.reduce((sum, id) => sum + (parseFloat(this.unitsById[id]) || 0), 0);
        },

        get withdrawCount() {
            return this.withdrawSelected.length;
        },

        withdrawPreviewUrl(baseUrlWithQuery) {
            // baseUrlWithQuery already carries ?program=&major=&ay=&sem_term=
            // (built server-side, same params "Withdraw all" sends) -- this
            // just appends the specific offering_ids the user checked.
            return baseUrlWithQuery + "&" + this.withdrawSelected.map((id) => "offering_ids=" + encodeURIComponent(id)).join("&");
        },
    }));
});
