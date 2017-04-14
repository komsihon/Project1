# -*- coding: utf-8 -*-

__author__ = 'Kom Sihon'

from django.db.models.fields.files import ImageField, ImageFieldFile
from PIL import Image
import os


def _add_suffix(suffix, s):
    """
    Modifies a string (filename, URL) containing an image filename, to insert
    '.suffix' (Eg: .small, .thumb, etc.) before the file extension (which is changed to be '.jpg').
    """
    parts = s.split(".")
    parts.insert(-1, suffix)
    # if parts[-1].lower() not in ['jpeg', 'jpg']:
    #     parts[-1] = 'jpg'
    return ".".join(parts)


class MultiImageFieldFile(ImageFieldFile):

    def _get_lowqual_name(self):
        return _add_suffix('lowqual', self.name)
    lowqual_name = property(_get_lowqual_name)

    def _get_lowqual_path(self):
        return _add_suffix('lowqual', self.path)
    lowqual_path = property(_get_lowqual_path)

    def _get_lowqual_url(self):
        return _add_suffix('lowqual', self.url)
    lowqual_url = property(_get_lowqual_url)

    def _get_small_name(self):
        return _add_suffix('small', self.name)
    small_name = property(_get_small_name)

    def _get_small_path(self):
        return _add_suffix('small', self.path)
    small_path = property(_get_small_path)

    def _get_small_url(self):
        return _add_suffix('small', self.url)
    small_url = property(_get_small_url)

    def _get_thumb_name(self):
        return _add_suffix('thumb', self.name)
    thumb_name = property(_get_thumb_name)

    def _get_thumb_path(self):
        return _add_suffix('thumb', self.path)
    thumb_path = property(_get_thumb_path)

    def _get_thumb_url(self):
        return _add_suffix('thumb', self.url)
    thumb_url = property(_get_thumb_url)

    def save(self, name, content, save=True):
        super(MultiImageFieldFile, self).save(name, content, save)

        # Save the .small version of the image
        img = Image.open(self.path)
        img.thumbnail(
            (self.field.small_size, self.field.small_size),
            Image.ANTIALIAS
        )
        img.save(self.small_path, quality=96)

        # Save the .thumb version of the image
        img = Image.open(self.path)
        img.thumbnail(
            (self.field.thumb_size, self.field.thumb_size),
            Image.ANTIALIAS
        )
        img.save(self.thumb_path, quality=96)

        # Save the low quality version of the image with the original dimensions
        if self.field.lowqual > 0:  # Create the Low Quality version only if lowqual is set
            img = Image.open(self.path)
            IMAGE_WIDTH_LIMIT = 1600  # Too big img are of no use on this web site
            lowqual_size = img.size if img.size[0] <= IMAGE_WIDTH_LIMIT else IMAGE_WIDTH_LIMIT, IMAGE_WIDTH_LIMIT
            img.thumbnail(lowqual_size, Image.NEAREST)
            img.save(self.lowqual_path, quality=self.field.lowqual)

        max_size = self.field.max_size
        if max_size > 0:  # Create a new version of image if too large
            img = Image.open(self.path)
            if img.size[0] > max_size or img.size[1] > max_size:
                new_size = (max_size, max_size)
            else:
                new_size = img.size
            img.thumbnail(new_size, Image.ANTIALIAS)
            img.save(self.path, quality=96)

    def delete(self, save=True):
        if os.path.exists(self.lowqual_path):
            os.remove(self.lowqual_path)
        if os.path.exists(self.small_path):
            os.remove(self.small_path)
        if os.path.exists(self.thumb_path):
            os.remove(self.thumb_path)
        super(MultiImageFieldFile, self).delete(save)


class MultiImageField(ImageField):
    """
    Behaves like a regular ImageField, but stores extra (JPEG) img providing get_FIELD_lowqual_url(), get_FIELD_small_url(),
    get_FIELD_thumb_url(), get_FIELD_small_filename(), get_FIELD_lowqual_filename() and get_FIELD_thumb_filename().
    Accepts three additional, optional arguments: lowqual, small_size and thumb_size,
    respectively defaulting to 15(%), 250 and 60 (pixels).
    """
    attr_class = MultiImageFieldFile

    def __init__(self, small_size=480, thumb_size=150, max_size=0, lowqual=0, *args, **kwargs):
        self.small_size = small_size
        self.thumb_size = thumb_size
        self.max_size = max_size
        self.lowqual = lowqual
        super(MultiImageField, self).__init__(*args, **kwargs)
