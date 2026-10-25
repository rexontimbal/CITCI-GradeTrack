// Django's CSRF middleware requires the token on every unsafe request (POST/PUT/DELETE).
// <form> submissions carry it via {% csrf_token %}, but plain hx-post/hx-delete buttons
// (Delete, Deactivate, Set as active, Drop/Re-enroll, ...) don't — so every htmx request
// gets it attached here, from the csrftoken cookie Django already sets.
function getCookie(name) {
    const match = document.cookie.match("(^|;)\\s*" + name + "\\s*=\\s*([^;]+)");
    return match ? match.pop() : "";
}

document.body.addEventListener("htmx:configRequest", (event) => {
    event.detail.headers["X-CSRFToken"] = getCookie("csrftoken");
});
