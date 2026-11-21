"""Form helpers shared by every app."""
from django import forms


class BootstrapFormMixin:
    """Add Bootstrap 5 classes to every widget and mark invalid fields after validation."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxSelectMultiple):
                widget.attrs["class"] = "form-check-input"
                continue
            if isinstance(widget, (forms.CheckboxInput,)):
                css = "form-check-input"
            elif isinstance(widget, (forms.Select, forms.SelectMultiple)):
                css = "form-select"
            else:
                css = "form-control"
            existing = widget.attrs.get("class", "")
            widget.attrs["class"] = f"{existing} {css}".strip()
            if field.required and not isinstance(widget, forms.CheckboxInput):
                widget.attrs.setdefault("required", "required")

    def full_clean(self):
        """Validate, then flag invalid widgets (done here, never in __init__)."""
        super().full_clean()
        for name in self._errors or {}:
            if name in self.fields:
                attrs = self.fields[name].widget.attrs
                if "is-invalid" not in attrs.get("class", ""):
                    attrs["class"] = f"{attrs.get('class', '')} is-invalid".strip()
                attrs["aria-invalid"] = "true"
