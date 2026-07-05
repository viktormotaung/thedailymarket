from django import template

register = template.Library()


@register.filter
def replace(value, arg):
    """
    Usage:
    {{ value|replace:"_, " }}
    """
    old, new = arg.split(",", 1)
    return str(value).replace(old, new)