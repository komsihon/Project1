from django.views.generic import TemplateView


class SetExpressCheckout(TemplateView):
    template_name = 'billing/momo_checkout.html'
