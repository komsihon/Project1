from django.utils.translation import gettext_lazy as _

PENDING_FOR_PAYMENT = 'PendingForPayment'
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

STARTED = 'Started'
COMPLETE = 'Complete'

ACCEPTED = 'Accepted'
REJECTED = 'Rejected'


PC = 'PC'
TABLET = 'Tablet'
MOBILE = 'Mobile'
DEVICE_FAMILY_CHOICES = (
    (PC, _('PC')),
    (TABLET, _('Tablet')),
    (MOBILE, _('Mobile'))
)
