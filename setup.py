import os
import re
import shutil
import sys
from io import open

from setuptools import find_packages, setup

CURRENT_PYTHON = sys.version_info[:2]
REQUIRED_PYTHON = (3, 8)

# This check and everything above must remain compatible with Python 2.7.
if CURRENT_PYTHON < REQUIRED_PYTHON:
    sys.stderr.write("""
==========================
Unsupported Python version
==========================

This version of Django API Helper requires Python {}.{}, but you're trying
to install it on Python {}.{}.

This may be because you are using a version of pip that doesn't
understand the python_requires classifier. Make sure you
have pip >= 9.0 and setuptools >= 24.2, then try again:

    $ python -m pip install --upgrade pip setuptools
    $ python -m pip install django-api-helper

This will install the latest version of Django API Helper which works on
your version of Python. If you can't upgrade your pip (or Python), request
an older version of Django API Helper:

    $ python -m pip install "django-api-helper"
""".format(*(REQUIRED_PYTHON + CURRENT_PYTHON)))
    sys.exit(1)

def read(f):
    with open(f, 'r', encoding='utf-8') as file:
        return file.read()

setup(
    name                            =   "django-api-helper",
    version                         =   "0.0.1",
    author                          =   "Ruchit Kharwa",
    author_email                    =   "ruchit@wolfx.io",
    description                     =   "An abstraction layer for creating APIs in Django Rest Framework, supports rpc style APIs.",
    long_description                =   read('README.md'),
    long_description_content_type   =   "text/markdown",
    url                             =   "https://github.com/ruchitmicro/django-api-helper",
    packages                        =   find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3",
        "Framework :: Django",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires='>=3.6',
    install_requires=[
        "django>=3.0",
        "django-api-helper",
        "django-filter",
        "django-import-export",
    ],
)


