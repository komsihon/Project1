from django import template

register = template.Library()


@register.filter
def index(a_list, i):
    """
    Given a list. Returns the item at index i
    Allows dynamin list indexing in templates
    """
    try:
        return a_list[int(i)]
    except IndexError:
        return None
