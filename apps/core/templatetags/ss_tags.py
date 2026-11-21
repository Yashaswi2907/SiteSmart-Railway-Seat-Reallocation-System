"""Presentation helpers used across templates."""
from decimal import Decimal

from django import template
from django.utils.html import format_html

register = template.Library()

BOOKING_TONES = {"CONFIRMED": "success", "CANCELLED": "danger"}
BOARDING_TONES = {"PENDING": "secondary", "BOARDED": "success", "NOT_BOARDED": "warning"}
SIM_TONES = {"SCHEDULED": "secondary", "AT_STATION": "success", "IN_TRANSIT": "primary", "COMPLETED": "neutral"}


@register.filter
def money(value):
    try:
        value = Decimal(value)
    except Exception:
        return value
    whole = int(value)
    s = str(abs(whole))
    if len(s) > 3:  # Indian digit grouping: 12,34,567
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts) + "," + tail
    return f"{'-' if whole < 0 else ''}₹{s}"


@register.filter
def hm(value):
    return value.strftime("%H:%M") if value else "—"


@register.simple_tag
def booking_chip(status, label=None):
    tone = BOOKING_TONES.get(status, "secondary")
    return format_html('<span class="chip chip-{}">{}</span>', tone, label or status.title())


@register.simple_tag
def boarding_chip(boarding):
    status = getattr(boarding, "status", "PENDING")
    label = boarding.get_status_display() if boarding else "Pending verification"
    return format_html('<span class="chip chip-{}">{}</span>', BOARDING_TONES.get(status, "secondary"), label)


@register.simple_tag
def sim_chip(sim):
    if sim is None:
        return format_html('<span class="chip chip-secondary">Scheduled</span>')
    return format_html('<span class="chip chip-{}">{}</span>', SIM_TONES.get(sim.status, "secondary"),
                       sim.get_status_display())


@register.simple_tag(takes_context=True)
def qs(context, **kwargs):
    """Rebuild the current query string with some keys replaced (for filters/pagination)."""
    params = context["request"].GET.copy()
    for k, v in kwargs.items():
        if v in (None, ""):
            params.pop(k, None)
        else:
            params[k] = v
    encoded = params.urlencode()
    return f"?{encoded}" if encoded else "?"


@register.filter
def get_item(mapping, key):
    try:
        return mapping.get(key)
    except AttributeError:
        return None


@register.filter
def widget_type(field):
    return field.field.widget.__class__.__name__.lower()
