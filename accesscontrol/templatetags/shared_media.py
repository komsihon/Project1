from django.conf import settings

from django import template
from django.template.defaultfilters import stringfilter
from ikwen.core.utils import get_service_instance

register = template.Library()


@register.filter
@stringfilter
def from_provider(image, provider):
    """
    Gets the URL of the image in its platform of origin.
    That is url of the image with the MEDIA_URL replaced
    by the media_url of the provider of the product.

    :param image: Image field
    :param provider: provider of the Product which the Image belong to
    :return:
    """
    if image:
        media_url = getattr(settings, 'MEDIA_URL')
        image = image.replace(media_url, '')
        if provider == get_service_instance():
            return media_url + image
        else:
            return provider.config.media_url + image
