"""
Django settings for ikwen project.

For more information on this file, see
https://docs.djangoproject.com/en/1.6/topics/settings/

For the full list of settings and their values, see
https://docs.djangoproject.com/en/1.6/ref/settings/
"""

# Build paths inside the project like this: os.path.join(BASE_DIR, ...)
import os
BASE_DIR = os.path.dirname(os.path.dirname(__file__))


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/1.6/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = 'zedpmxz&d(5swy9@8b2cb-k2wa(xg!%ow&2s5j_&_^wa*t5lgh'

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

TEMPLATE_DEBUG = True

ALLOWED_HOSTS = []


# ApplicationList definition

INSTALLED_APPS = (
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.webdesign',
    'django.contrib.humanize',

    #Third parties
    'ajaxuploader',
    # 'paypal.standard',
    # 'paypal.pro',

    'ikwen.foundation.core',
    'ikwen.foundation.accesscontrol',
    'ikwen.foundation.billing',
)

MIDDLEWARE_CLASSES = (
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.locale.LocaleMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
)

TEMPLATE_CONTEXT_PROCESSORS = (
    "django.contrib.auth.context_processors.auth",
    "django.core.context_processors.debug",
    "django.core.context_processors.i18n",
    "django.core.context_processors.media",
    "django.core.context_processors.static",
    "django.contrib.messages.context_processors.messages",
    'django.core.context_processors.request',
    'ikwen.foundation.core.context_processors.base_urls',
)

ROOT_URLCONF = 'ikwen.conf.urls'

WSGI_APPLICATION = 'ikwen.conf.wsgi.application'


# Database
# https://docs.djangoproject.com/en/1.6/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': 'django_mongodb_engine', # Add 'postgresql_psycopg2', 'mysql', 'sqlite3' or 'oracle'.
        'NAME': 'ikwen_umbrella',
    },
    'umbrella': {
        'ENGINE': 'django_mongodb_engine', # Add 'postgresql_psycopg2', 'mysql', 'sqlite3' or 'oracle'.
        'NAME': 'ikwen_umbrella',
    },
    # 'kakocase_rel': {  # kakocase app relational database used to store transactional objects among which CashOutRequest
    #     'ENGINE': 'django.db.backends.sqlite3',
    #     'NAME': os.path.join(BASE_DIR, 'db.sqlite3'),
    # }
}

CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.memcached.MemcachedCache',
        'LOCATION': '127.0.0.1:11211',
        'TIMEOUT': 60 * 9,
        'KEY_PREFIX': 'umbrella',  # cnmxprod for Production
        'VERSION': '1'
    }
}

IS_IKWEN = True
SITE_ID = '54eb6d3379b531e09cb3704b'

AUTH_USER_MODEL = 'accesscontrol.Member'

AUTHENTICATION_BACKENDS = (
    'permission_backend_nonrel.backends.NonrelPermissionBackend',
    'ikwen.foundation.accesscontrol.backends.LocalDataStoreBackend',
)

# Model to use to generate Invoice for.
# Typically the Service which the Member subscribed to
BILLING_SUBSCRIPTION_MODEL = 'core.Service'
BILLING_SUBSCRIPTION_MODEL_ADMIN = 'ikwen.foundation.core.admin.ServiceAdmin'

HOTSPOT_APP_ID = '55eb6d04b37b3379b531e09c'

IKWEN_SERVICE_ID = '57b702ca4fc0c2139660d9f8'

LOGIN_URL = 'ikwen:sign_in'
LOGIN_REDIRECT_URL = 'home'

PROJECT_URL = 'http://localhost' if DEBUG else 'http://www.ikwen.com'

LOGOUT_REDIRECT_URL = 'home'

# Internationalization
# https://docs.djangoproject.com/en/1.6/topics/i18n/

LANGUAGE_CODE = 'en'

TIME_ZONE = 'Africa/Douala'

USE_I18N = True

USE_L10N = True

USE_TZ = False

# Absolute filesystem path to the directory that will hold user-uploaded files.
# Example: "/var/www/example.com/media/"
MEDIA_ROOT = os.path.join(BASE_DIR,  'media')

# URL that handles the media served from MEDIA_ROOT. Make sure to use a
# trailing slash.
# Examples: "http://example.com/media/", "http://media.example.com/"
MEDIA_URL = '/ikwen/media/'

# Absolute path to the directory static files should be collected to.
# Don't put anything in this directory yourself; store your static files
# in apps' "static/" subdirectories and in STATICFILES_DIRS.
# Example: "/var/www/example.com/static/"
STATIC_ROOT = os.path.join(BASE_DIR,  'static')

# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/1.6/howto/static-files/

STATIC_URL = '/ikwen/static/'

TEMPLATE_DIRS = (os.path.join(BASE_DIR,  'templates'),)