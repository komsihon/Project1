import logging

from django.conf import settings

try:
    from logging.config import dictConfig
except ImportError:
    from django.utils.dictconfig import dictConfig

getLogger = logging.getLogger

DEBUG = getattr(settings, 'DEBUG', False) or getattr(settings, 'UNIT_TESTING', False)
BASE_DIR = getattr(settings, 'BASE_DIR')

ikwen_info_log_filename = BASE_DIR + '/ikwen_info.log' if DEBUG else '/var/www/ikwen_info.log'
ikwen_error_log_filename = BASE_DIR + '/ikwen_error.log' if DEBUG else '/var/www/ikwen_error.log'
crons_info_log_filename = BASE_DIR + '/crons_info.log' if DEBUG else '/var/www/crons_info.log'
crons_error_log_filename = BASE_DIR + '/crons_error.log' if DEBUG else '/var/www/crons_error.log'

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'default': {
            'format': '%(asctime)-27s %(message)s'
        }
    },
    'filters': {
        'require_lower_than_error': {
            '()': 'ikwen.core.log.RequireLowerThanError'
        }
    },
    'handlers': {
        'info_log_handler': {
            'level': 'DEBUG',
            'filters': ['require_lower_than_error'],
            'formatter': 'default',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': ikwen_info_log_filename,
            'maxBytes': 1000000,
            'backupCount': 4
        },
        'error_log_handler': {
            'level': 'ERROR',
            'formatter': 'default',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': ikwen_error_log_filename,
            'maxBytes': 1000000,
            'backupCount': 4
        },
        'mail_admins': {
            'level': 'ERROR',
            'class': 'django.utils.log.AdminEmailHandler'
        }
    },
    'loggers': {
        'ikwen': {
            'handlers': ['info_log_handler', 'error_log_handler'],
            'level': 'DEBUG',
            'propagate': True,
        },
    }
}

CRONS_LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'default': {
            'format': '%(asctime)-27s %(message)s'
        }
    },
    'filters': {
        'require_lower_than_error': {
            '()': 'ikwen.core.log.RequireLowerThanError'
        }
    },
    'handlers': {
        'crons_info_log_handler': {
            'level': 'DEBUG',
            'filters': ['require_lower_than_error'],
            'formatter': 'default',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': crons_info_log_filename,
            'maxBytes': 10000000,
            'backupCount': 4
        },
        'crons_error_log_handler': {
            'level': 'ERROR',
            'formatter': 'default',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': crons_error_log_filename,
            'maxBytes': 10000000,
            'backupCount': 4
        },
        'mail_admins': {
            'level': 'ERROR',
            'class': 'django.utils.log.AdminEmailHandler'
        }
    },
    'loggers': {
        'ikwen.crons': {
            'handlers': ['crons_info_log_handler', 'crons_error_log_handler', 'mail_admins'],
            'level': 'DEBUG',
            'propagate': True,
        }
    }
}


class RequireLowerThanError(logging.Filter):
    def filter(self, record):
        return record.levelno < 40
