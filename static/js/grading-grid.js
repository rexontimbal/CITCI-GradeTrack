// Class Record score-encoding grid behavior: keyboard navigation between
// cells, and keeping each cell's value to digits only (scores/max scores are
// whole numbers — see grading/services.py). Autosave itself is plain htmx
// (hx-trigger="blur changed" on each input, see templates/grading/_grid_row.html).

document.addEventListener("keydown", function (event) {
    var input = event.target;
    if (!input.classList || !input.classList.contains("grade-cell-input")) return;

    function focusCell(id) {
        if (!id) return;
        var target = document.getElementById(id);
        if (!target) return;
        event.preventDefault();
        target.focus();
        target.select();
    }

    switch (event.key) {
        case "Enter":
            // Moving focus to the cell below already blurs this one (which
            // is what triggers the hx-trigger="blur changed" autosave) --
            // but the last row has no cell below, so without this the
            // input would just stay focused forever with a blinking
            // cursor, looking like the edit never finished. Blur it
            // directly so Enter always "completes" the cell.
            if (input.dataset.down) {
                focusCell(input.dataset.down);
            } else {
                event.preventDefault();
                input.blur();
            }
            return;
        case "ArrowDown":
            focusCell(input.dataset.down);
            return;
        case "ArrowUp":
            focusCell(input.dataset.up);
            return;
        case "ArrowRight":
            if (input.selectionStart === input.value.length) focusCell(input.dataset.right);
            return;
        case "ArrowLeft":
            if (input.selectionStart === 0) focusCell(input.dataset.left);
            return;
    }

    // Everything else: only digits and basic editing/navigation keys are
    // allowed through — no '.', '-', 'e', letters, etc. No mouse-wheel/
    // spinner concerns either since the input is type="text", not "number".
    var editingKeys = ["Backspace", "Delete", "Tab", "Home", "End"];
    var isDigit = event.key.length === 1 && event.key >= "0" && event.key <= "9";
    var isClipboardShortcut = (event.ctrlKey || event.metaKey) && ["a", "c", "v", "x"].includes(event.key.toLowerCase());
    if (!isDigit && !isClipboardShortcut && editingKeys.indexOf(event.key) === -1) {
        event.preventDefault();
    }
});

// Safety net for paste/drag-drop/autofill, which keydown can't catch.
document.addEventListener("input", function (event) {
    var input = event.target;
    if (!input.classList || !input.classList.contains("grade-cell-input")) return;
    var cleaned = input.value.replace(/[^0-9]/g, "");
    if (cleaned !== input.value) input.value = cleaned;
});
