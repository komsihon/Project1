# -*- coding: utf-8 -*-
import json
import os
from datetime import datetime

from currencies.models import Currency
from django.conf import settings
from django.core import mail
from django.core.files import File
from django.core.mail import EmailMessage
from django.db import transaction
from django.http import HttpResponse
from django.utils.translation import gettext as _

from ikwen.conf.settings import WALLETS_DB_ALIAS
from ikwen.conf import settings as ikwen_settings
from ikwen.accesscontrol.backends import UMBRELLA
from ikwen.accesscontrol.models import Member
from ikwen.core.utils import get_service_instance, get_item_list, get_mail_content, send_sms, get_sms_label
from ikwen.core.models import Service
from ikwen.core.views import HybridListView, ChangeObjectBase
from ikwen.revival.models import ProfileTag
from ikwen.revival.admin import ProfileTagAdmin
from ikwen.revival.models import CyclicRevival
from ikwen_kakocase.kako.models import Product


class ProfileTagList(HybridListView):
    model = ProfileTag
    ordering = ('name', )
    template_name = 'revival/profile_tag_list.html'
    queryset = ProfileTag.objects.filter(is_reserved=False, is_auto=False)

    def get_context_data(self, **kwargs):
        context = super(ProfileTagList, self).get_context_data(**kwargs)
        context['reserved_tag_list'] = ProfileTag.objects.filter(is_reserved=True)
        return context


class ChangeProfileTag(ChangeObjectBase):
    template_name = 'revival/change_profile_tag.html'
    model = ProfileTag
    model_admin = ProfileTagAdmin

    def get_context_data(self, **kwargs):
        context = super(ChangeProfileTag, self).get_context_data(**kwargs)
        obj = context['obj']
        items_fk_list = []
        if obj:
            try:
                cyclic_revival = CyclicRevival.objects.using(UMBRELLA).get(profile_tag_id=obj.id)
                cyclic_revival.day_of_month_list = ', '.join(['%d' % i for i in cyclic_revival.day_of_month_list])
                cyclic_revival.day_of_week_list = ', '.join(['%d' % i for i in cyclic_revival.day_of_week_list])
                cyclic_revival.end_on_alt = cyclic_revival.end_on.strftime('%Y-%m-%d')
                items_fk_list = cyclic_revival.items_fk_list
                context['revival'] = cyclic_revival
                context['set_cyclic'] = True
            except CyclicRevival.DoesNotExist:
                pass
        if self.request.GET.get('items_fk_list'):
            items_fk_list = self.request.GET.get('items_fk_list').split(',')
            context['set_cyclic'] = True
        context['items_fk_list'] = ','.join(items_fk_list)
        context['item_list'] = get_item_list('kako.Product', items_fk_list)
        return context

    def get(self, request, *args, **kwargs):
        if request.GET.get('action') == 'toggle_activation':
            return self.toggle_activation(request)
        elif request.GET.get('action') == 'run_test':
            return self.run_test(request)
        return super(ChangeProfileTag, self).get(request, *args, **kwargs)

    def after_save(self, request, obj, *args, **kwargs):
        set_cyclic_revival = request.POST.get('set_cyclic_revival')
        if not set_cyclic_revival:
            try:
                revival_umbrella = CyclicRevival.objects.using(UMBRELLA).get(profile_tag_id=obj.id)
                try:
                    os.unlink(getattr(settings, 'MEDIA_ROOT') + revival_umbrella.mail_image.name)
                except IOError as e:
                    if getattr(settings, 'DEBUG', False):
                        raise e
                revival_umbrella.delete()
            except CyclicRevival.DoesNotExist:
                pass
            return
        frequency_type = request.POST['frequency_type']
        mail_image_url = request.POST['mail_image_url']
        days_cycle = request.POST.get('days_cycle')
        week_days = request.POST.get('week_days')
        month_days = request.POST.get('month_days')
        hour_of_sending = int(request.POST['hour_of_sending'])
        mail_subject = request.POST['mail_subject']
        mail_content = request.POST['mail_content']
        sms_text = request.POST['sms_text']
        items_fk_list = request.POST.get('items_fk_list')
        if items_fk_list:
            items_fk_list = items_fk_list.split(',')
        else:
            items_fk_list = []
        end_on = request.POST['end_on'].split('-')
        end_on = datetime(int(end_on[0]), int(end_on[1]), int(end_on[2])).date()
        day_of_week_list = []
        day_of_month_list = []
        if frequency_type == 'days_cycle':
            days_cycle = int(days_cycle)
        elif frequency_type == 'week_days':
            days_cycle = None
            day_of_week_list = [int(i) for i in week_days.split(',')]
            day_of_week_list.sort()
        elif frequency_type == 'month_days':
            days_cycle = None
            day_of_month_list = [int(i) for i in month_days.split(',')]
            day_of_month_list.sort()
        try:
            revival_umbrella = CyclicRevival.objects.using(UMBRELLA).get(profile_tag_id=obj.id)
            CyclicRevival.objects.using(UMBRELLA).filter(profile_tag_id=obj.id)\
                .update(mail_subject=mail_subject, mail_content=mail_content,
                        sms_text=sms_text,  days_cycle=days_cycle, day_of_week_list=day_of_week_list,
                        day_of_month_list=day_of_month_list, hour_of_sending=hour_of_sending, end_on=end_on,
                        items_fk_list=items_fk_list)
        except CyclicRevival.DoesNotExist:
            service = get_service_instance()
            srvc = Service.objects.using(UMBRELLA).get(pk=service.id)
            revival = CyclicRevival.objects.create(service=service, profile_tag_id=obj.id)
            revival_umbrella = CyclicRevival.objects.using(UMBRELLA)\
                .create(id=revival.id, service=srvc, profile_tag_id=obj.id, mail_subject=mail_subject,
                        mail_content=mail_content, sms_text=sms_text,  days_cycle=days_cycle,
                        day_of_week_list=day_of_week_list, day_of_month_list=day_of_month_list,
                        hour_of_sending=hour_of_sending, end_on=end_on, items_fk_list=items_fk_list)
        if mail_image_url:
            s = get_service_instance()
            media_root = getattr(settings, 'MEDIA_ROOT')
            path = mail_image_url.replace(getattr(settings, 'MEDIA_URL'), '')
            path = path.replace(ikwen_settings.MEDIA_URL, '')
            if not revival_umbrella.mail_image.name or path != revival_umbrella.mail_image.name:
                filename = mail_image_url.split('/')[-1]
                try:
                    with open(media_root + path, 'r') as f:
                        content = File(f)
                        destination = media_root + CyclicRevival.UPLOAD_TO + "/" + s.project_name_slug + '_' + filename
                        revival_umbrella.mail_image.save(destination, content)
                    os.unlink(media_root + path)
                except IOError as e:
                    if getattr(settings, 'DEBUG', False):
                        raise e

    def toggle_activation(self, request):
        revival_id = request.GET['revival_id']
        cyclic_revival = CyclicRevival.objects.using(UMBRELLA).get(pk=revival_id)
        cyclic_revival.is_active = not cyclic_revival.is_active
        cyclic_revival.save()
        response = {'message': _("Successful update"), 'is_active': cyclic_revival.is_active}
        return HttpResponse(json.dumps(response))

    def run_test(self, request):
        from echo.utils import count_pages
        from echo.models import Balance, SMSObject
        revival_id = request.GET['revival_id']
        test_email_list = request.GET['test_email_list'].split(',')
        test_phone_list = request.GET['test_phone_list'].split(',')
        service = get_service_instance()
        revival = CyclicRevival.objects.using(UMBRELLA).get(pk=revival_id)
        balance = Balance.objects.using(WALLETS_DB_ALIAS).get(service_id=service.id)
        if balance.mail_count == 0 and balance.sms_count == 0:
            response = {'error': 'Insufficient Email and SMS credit'}
            return HttpResponse(json.dumps(response))

        connection = mail.get_connection()
        try:
            connection.open()
        except:
            response = {'error': 'Failed to connect to mail server. Please check your internet'}
            return HttpResponse(json.dumps(response))
        config = service.config

        warning = []
        for email in test_email_list:
            if balance.mail_count == 0:
                warning.append('Insufficient email Credit')
                break
            email = email.strip()
            subject = revival.mail_subject
            try:
                member = Member.objects.filter(email=email)[0]
                message = revival.mail_content.replace('$client', member.first_name)
            except:
                message = revival.mail_content.replace('$client', _("<Unknown>"))
            sender = '%s <no-reply@%s>' % (config.company_name, service.domain)
            media_url = ikwen_settings.CLUSTER_MEDIA_URL + service.project_name_slug + '/'
            product_list = []
            if service.app.slug == 'kakocase':
                product_list = Product.objects.filter(pk__in=revival.items_fk_list)
            try:
                currency = Currency.objects.get(is_base=True)
            except Currency.DoesNotExist:
                currency = None
            html_content = get_mail_content(subject, message, template_name='revival/mails/default.html',
                                            extra_context={'media_url': media_url, 'product_list': product_list,
                                                           'revival': revival, 'currency': currency})
            msg = EmailMessage(subject, html_content, sender, [email])
            msg.content_subtype = "html"
            with transaction.atomic(using='wallets'):
                try:
                    balance.mail_count -= 1
                    balance.save()
                    if not msg.send():
                        transaction.rollback(using='wallets')
                        warning.append('Mail not sent to %s' % email)
                except:
                    transaction.rollback(using='wallets')
        try:
            connection.close()
        except:
            pass

        if revival.sms_text:
            label = get_sms_label(config)
            for phone in test_phone_list:
                if balance.sms_count == 0:
                    warning.append('Insufficient SMS Credit')
                    break
                try:
                    member = Member.objects.filter(phone=phone)[0]
                    sms_text = revival.sms_text.replace('$client', member.first_name)
                except:
                    sms_text = revival.mail_content.replace('$client', "")
                page_count = count_pages(sms_text)
                with transaction.atomic():
                    try:
                        balance.sms_count -= page_count
                        balance.save()
                        phone = phone.strip()
                        if len(phone) == 9:
                            phone = '237' + phone
                        send_sms(recipient=phone, text=revival.sms_text, fail_silently=False)
                        SMSObject.objects.create(recipient=phone, text=revival.sms_text, label=label)
                    except:
                        transaction.rollback()
                        warning.append('SMS not sent to %s' % phone)
        response = {'success': True, 'warning': warning}
        return HttpResponse(json.dumps(response))
