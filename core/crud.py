"""Generic list/create/update/delete views shared by every academic-setup
entity page (Academic Years, Semesters, Programs, Sections, Subjects,
Classes). Each page gets four tiny view classes that just set the model,
form, templates and filters — all the HTMX/pagination/PROTECT-handling
plumbing lives here once.

Pattern: one URL per action, same URL handles both the full page and the
HTMX fragment (detected via the HX-Request header). Create/update/delete
render into a shared modal (see templates/partials/_modal.html) and signal
success back to the page via an `HX-Trigger` response header, which the
table fragment listens for to refresh itself.
"""

import json

from django.core.paginator import Paginator
from django.db.models import ProtectedError
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views import View

from .htmx import is_htmx


def trigger_response(event_name, toast=None, toast_level="success"):
    """204 response that both tells the table to refresh (event_name),
    closes the shared modal (modal-success), and — if `toast` is given —
    pops a toast via the global toast listener in base.html. htmx fires a
    DOM CustomEvent per top-level key in HX-Trigger's JSON, so the "toast"
    key here reaches the same `@toast.window` handler used by Django
    messages (templates/partials/_messages.html)."""
    triggers = {event_name: True, "modal-success": True}
    if toast:
        triggers["toast"] = {"message": toast, "level": toast_level}
    response = HttpResponse(status=204)
    response["HX-Trigger"] = json.dumps(triggers)
    return response


class EntityListView(View):
    """GET: full page on a normal request, just the table+pagination
    fragment on an HTMX request (search box / filters / pagination all
    re-GET this same URL and swap the fragment back in)."""

    model = None
    list_template = None
    table_template = None
    table_id = ""
    page_title = ""
    paginate_by = 20
    search_fields = []
    refresh_event = "refreshTable"
    allowed_roles = ()

    def get_queryset(self, request):
        return self.model.objects.all()

    def apply_filters(self, request, qs):
        return qs

    def get_extra_context(self, request):
        return {}

    def get(self, request):
        qs = self.apply_filters(request, self.get_queryset(request))

        query = request.GET.get("q", "").strip()
        if query and self.search_fields:
            condition = Q()
            for lookup in self.search_fields:
                condition |= Q(**{lookup: query})
            qs = qs.filter(condition)

        paginator = Paginator(qs, self.paginate_by)
        page_obj = paginator.get_page(request.GET.get("page"))

        querydict = request.GET.copy()
        querydict.pop("page", None)

        context = {
            "page_obj": page_obj,
            "query": query,
            "query_string": querydict.urlencode(),
            "table_id": self.table_id,
            "refresh_event": self.refresh_event,
        }
        context.update(self.get_extra_context(request))

        if is_htmx(request):
            return render(request, self.table_template, context)

        context["page_title"] = self.page_title
        context["table_template"] = self.table_template
        return render(request, self.list_template, context)


class EntityFormView(View):
    """GET renders the create/edit form into the modal; POST validates and
    saves. pk absent = create, pk present = update."""

    model = None
    form_class = None
    form_template = "partials/_entity_form_modal.html"
    modal_title_create = "Add"
    modal_title_edit = "Edit"
    refresh_event = "refreshTable"

    def get_object(self, pk):
        return get_object_or_404(self.model, pk=pk) if pk else None

    def get_context(self, request, form, obj):
        return {
            "form": form,
            "object": obj,
            "modal_title": self.modal_title_edit if obj else self.modal_title_create,
        }

    def get(self, request, pk=None):
        obj = self.get_object(pk)
        form = self.form_class(instance=obj)
        return render(request, self.form_template, self.get_context(request, form, obj))

    def post(self, request, pk=None):
        obj = self.get_object(pk)
        form = self.form_class(request.POST, instance=obj)
        if form.is_valid():
            form.save()
            verb = "updated" if obj else "created"
            return trigger_response(self.refresh_event, toast=f"{self.model._meta.verbose_name.capitalize()} {verb}.")
        return render(request, self.form_template, self.get_context(request, form, obj))


class EntityDeleteView(View):
    """GET renders a confirm-delete fragment into the modal; POST performs
    the delete. If the row is protected by a FK elsewhere, re-renders the
    same fragment with a friendly message and (if the model has an
    is_active flag) a "Deactivate instead" button."""

    model = None
    confirm_template = "partials/_confirm_delete_modal.html"
    protect_message = "This record is being used elsewhere and can't be deleted."
    deactivate_url_name = None
    refresh_event = "refreshTable"
    label_field = None

    def get_label(self, obj):
        return getattr(obj, self.label_field) if self.label_field else str(obj)

    def get_context(self, request, obj, protect_error=False):
        from django.urls import reverse

        can_deactivate = hasattr(obj, "is_active") and self.deactivate_url_name
        return {
            "object": obj,
            "label": self.get_label(obj),
            "protect_error": self.protect_message if protect_error else "",
            "can_deactivate": bool(protect_error and can_deactivate),
            "deactivate_url": reverse(self.deactivate_url_name, args=[obj.pk]) if can_deactivate else "",
        }

    def get(self, request, pk):
        obj = get_object_or_404(self.model, pk=pk)
        return render(request, self.confirm_template, self.get_context(request, obj))

    def post(self, request, pk):
        obj = get_object_or_404(self.model, pk=pk)
        label = self.get_label(obj)
        try:
            obj.delete()
        except ProtectedError:
            return render(request, self.confirm_template, self.get_context(request, obj, protect_error=True))
        return trigger_response(self.refresh_event, toast=f"{label} deleted.")


class ToggleActiveView(View):
    """POST-only: flips is_active on a record (the "Deactivate instead"
    escape hatch when a delete is blocked by PROTECT)."""

    model = None
    refresh_event = "refreshTable"

    def post(self, request, pk):
        obj = get_object_or_404(self.model, pk=pk)
        obj.is_active = not obj.is_active
        obj.save(update_fields=["is_active"])
        verb = "activated" if obj.is_active else "deactivated"
        return trigger_response(self.refresh_event, toast=f"{obj} {verb}.")
