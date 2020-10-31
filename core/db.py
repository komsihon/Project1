# -*- coding: utf-8 -*-
from bson import ObjectId
from djongo import models
from djongo.models import DjongoManager


class ClassicManager(DjongoManager):
    """
    Traditionally querying by id would be done like this:
        obj = Klass.objects.get(pk=id_as_string)
        ...
    But with Djongo, queries by id expects an ObjectId() resulting in ...
        obj = Klass.objects.get(pk=ObjectId(id_as_string))
        ...

    This helper Manager helps automatically convert id passed
    as string to ObjectId() thus allowing to write our code the
    classic way and make it portable without hassle.
    """

    def get(self, *args, **kwargs):
        if kwargs.get('id'):
            id_val = kwargs.pop('id')
            if type(id_val) == str:
                kwargs['_id'] = ObjectId(id_val)
        if kwargs.get('pk'):
            id_val = kwargs['pk']
            if type(id_val) == str:
                kwargs['pk'] = ObjectId(id_val)
        return super(ClassicManager, self).get(*args, **kwargs)

    def filter(self, *args, **kwargs):
        if kwargs.get('id'):
            id_val = kwargs.pop('id')
            if type(id_val) == str:
                kwargs['_id'] = ObjectId(id_val)
        if kwargs.get('pk'):
            id_val = kwargs['pk']
            if type(id_val) == str:
                kwargs['pk'] = ObjectId(id_val)
        return super(ClassicManager, self).filter(*args, **kwargs)

    def exclude(self, *args, **kwargs):
        if kwargs.get('id'):
            id_val = kwargs.pop('id')
            if type(id_val) == str:
                kwargs['_id'] = ObjectId(id_val)
        if kwargs.get('pk'):
            id_val = kwargs['pk']
            if type(id_val) == str:
                kwargs['pk'] = ObjectId(id_val)
        return super(ClassicManager, self).exclude(*args, **kwargs)

    def get_or_create(self, defaults=None, **kwargs):
        if kwargs.get('id'):
            id_val = kwargs.pop('id')
            if type(id_val) == str:
                kwargs['_id'] = ObjectId(id_val)
        if kwargs.get('pk'):
            id_val = kwargs['pk']
            if type(id_val) == str:
                kwargs['pk'] = ObjectId(id_val)
        return super(ClassicManager, self).get_or_create(defaults, **kwargs)


class BaseModel(models.Model):
    """
    In order to force the sole use of MongoDB generated _id as
    id of models, you must explicitly declare it as such on Djongo.
    This class creates the field and adds
    """
    _id = models.ObjectIdField()

    class Meta:
        abstract = True

    objects = ClassicManager()

    def __getattr__(self, name):
        if name == 'id':
            return str(self._id)
