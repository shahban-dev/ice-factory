"""Template filters for money display. Never trust browser formatting."""

from django import template

from core.money import format_balance, format_rs

register = template.Library()


@register.filter
def rs(value):
    return format_rs(value)


@register.filter
def balance(value):
    return format_balance(value)
