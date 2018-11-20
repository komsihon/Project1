import logging
try:
    from logging.config import dictConfig
except ImportError:
    from django.utils.dictconfig import dictConfig

getLogger = logging.getLogger

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
            'filename': '/var/www/ikwen_info.log',
            'maxBytes': 1000000,
            'backupCount': 4
        },
        'error_log_handler': {
            'level': 'ERROR',
            'formatter': 'default',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': '/var/www/ikwen_error.log',
            'maxBytes': 1000000,
            'backupCount': 4
        },
        'rewarding_info_log_handler': {
            'level': 'DEBUG',
            'filters': ['require_lower_than_error'],
            'formatter': 'default',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': '/var/www/rewarding_info.log',
            'maxBytes': 10000000,
            'backupCount': 4
        },
        'rewarding_error_log_handler': {
            'level': 'ERROR',
            'formatter': 'default',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': '/var/www/rewarding_error.log',
            'maxBytes': 10000000,
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
        'ikwen.rewarding': {
            'handlers': ['rewarding_info_log_handler', 'rewarding_error_log_handler', 'mail_admins'],
            'level': 'DEBUG',
            'propagate': False,
        },
        'ikwen.crons': {
            'handlers': ['info_log_handler', 'error_log_handler', 'mail_admins'],
            'level': 'DEBUG',
            'propagate': False,
        }
    }
}


class RequireLowerThanError(logging.Filter):
    def filter(self, record):
        return record.levelno < 40
