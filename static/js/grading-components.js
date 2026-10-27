// Instructor "Grading Components" panel (class Setup tab). Plain JS, no
// framework formset library — just the standard Django formset tricks:
// clone the empty_form template with the prefix swapped in, and bump
// TOTAL_FORMS. Locked (school-fixed) rows are rendered with disabled
// inputs server-side, so they're naturally excluded from form submission;
// here they're also excluded from the live total so the instructor is only
// ever asked to balance the share that's actually theirs to set.

(function () {
    function panel() {
        return document.getElementById("components-form");
    }

    function updateTotal() {
        var form = panel();
        if (!form) return;

        var target = parseInt(form.dataset.instructorShare, 10) || 0;
        var total = 0;
        form.querySelectorAll(".component-row").forEach(function (row) {
            var deleteBox = row.querySelector('input[type="checkbox"][name$="-DELETE"]');
            if (deleteBox && deleteBox.checked) return;
            var weightInput = row.querySelector('input[name$="-weight"]');
            if (!weightInput || weightInput.disabled || weightInput.readOnly) return;
            var value = parseInt(weightInput.value, 10);
            if (!isNaN(value)) total += value;
        });

        var label = document.getElementById("components-total-label");
        var bar = document.getElementById("components-total-bar");
        var saveButton = document.getElementById("save-components-btn");
        if (label) label.textContent = total + " / " + target + "%";
        if (bar) {
            bar.style.width = Math.min(100, target ? (total / target) * 100 : 0) + "%";
            bar.classList.toggle("bg-green-500", total === target);
            bar.classList.toggle("bg-amber-400", total !== target);
        }
        if (saveButton) saveButton.disabled = total !== target;
    }

    function removeRow(row) {
        var idInput = row.querySelector('input[name$="-id"]');
        var deleteBox = row.querySelector('input[type="checkbox"][name$="-DELETE"]');
        if (idInput && idInput.value) {
            // Existing (saved) row: mark for deletion on submit, hide it.
            if (deleteBox) deleteBox.checked = true;
            row.classList.add("hidden");
        } else {
            // Freshly-added, never-saved row: just drop it from the DOM.
            row.remove();
        }
        updateTotal();
    }

    function addRow() {
        var template = document.getElementById("empty-component-row");
        var rows = document.getElementById("component-rows");
        var totalFormsInput = document.querySelector('input[name="components-TOTAL_FORMS"]');
        if (!template || !rows || !totalFormsInput) return;

        var index = parseInt(totalFormsInput.value, 10);
        var html = template.innerHTML.replace(/__prefix__/g, index);
        var wrapper = document.createElement("div");
        wrapper.innerHTML = html.trim();
        rows.appendChild(wrapper.firstElementChild);
        totalFormsInput.value = index + 1;
        updateTotal();
    }

    document.addEventListener("click", function (event) {
        if (event.target.closest("#add-component-btn")) {
            event.preventDefault();
            addRow();
        }
        var removeButton = event.target.closest(".remove-row-btn");
        if (removeButton) {
            event.preventDefault();
            removeRow(removeButton.closest(".component-row"));
        }
    });

    document.addEventListener("input", function (event) {
        if (event.target.matches('.component-row input[name$="-weight"]')) updateTotal();
    });

    document.addEventListener("htmx:afterSwap", function (event) {
        if (event.target.id === "components-panel" || event.target.querySelector("#components-form")) updateTotal();
    });

    document.addEventListener("DOMContentLoaded", updateTotal);
})();
