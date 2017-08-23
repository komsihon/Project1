from django.utils.translation import gettext_lazy as _

PENDING = 'Pending'
CONFIRMED = 'Confirmed'
STATUS_CHOICES = (
    (PENDING, _('Pending')),
    (CONFIRMED, _('Confirmed'))
)

MALE = 'Male'
FEMALE = 'Female'
GENDER_CHOICES = (
    (MALE, _('Male')),
    (FEMALE, _('Female'))
)
