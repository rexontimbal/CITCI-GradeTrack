// Keyboard navigation for the Class Record score-encoding grid. Autosave
// itself is plain htmx (hx-trigger="blur changed" on each input, see
// templates/grading/_grid_row.html) — this file only moves focus between
// cells so Up/Down/Left/Right/Enter feel like a spreadsheet.
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
        case "ArrowDown":
        case "Enter":
            focusCell(input.dataset.down);
            break;
        case "ArrowUp":
            focusCell(input.dataset.up);
            break;
        case "ArrowRight":
            if (input.selectionStart === input.value.length) focusCell(input.dataset.right);
            break;
        case "ArrowLeft":
            if (input.selectionStart === 0) focusCell(input.dataset.left);
            break;
    }
});
