from django import forms


class SearchableSelectWidget(forms.Widget):
    """A text box that live-filters options via HTMX as you type (see
    static/js/searchable-select.js + templates/partials/_searchable_select_widget.html).
    Drop-in replacement for a ModelChoiceField's default <select> when the
    queryset is long enough that scrolling a plain dropdown is painful.

    `search_url` must point at a view that renders `partials/_searchable_select_options.html`
    for a `?q=` query, matching `queryset`.
    """

    template_name = "partials/_searchable_select_widget.html"

    def __init__(self, search_url, queryset=None, attrs=None):
        self.search_url = search_url
        self.queryset = queryset
        super().__init__(attrs)

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        label = ""
        if value and self.queryset is not None:
            obj = self.queryset.filter(pk=value).first()
            label = str(obj) if obj else ""
        context.update(
            {
                "search_url": self.search_url,
                "selected_value": value or "",
                "selected_label": label,
                "widget_name": name,
                "widget_id": attrs.get("id", name) if attrs else name,
            }
        )
        return context

    def value_from_datadict(self, data, files, name):
        return data.get(name) or None

    def format_value(self, value):
        return value
