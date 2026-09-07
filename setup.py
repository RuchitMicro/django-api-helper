from io import open

from setuptools import find_packages, setup

def read(f):
    with open(f, 'r', encoding='utf-8') as file:
        return file.read()

setup(
    name                            =   "django-api-helper",
    version                         =   "0.1.0",
    author                          =   "Ruchit Kharwa",
    author_email                    =   "ruchit@wolfx.io",
    description                     =   "An abstraction layer for creating APIs in Django Rest Framework, supports rpc style APIs.",
    long_description                =   read('README.md'),
    long_description_content_type   =   "text/markdown",
    url                             =   "https://github.com/RuchitMicro/django-api-helper",
    packages                        =   find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3 :: Only",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
        "Framework :: Django",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires='>=3.9',
    install_requires=[
        "Django>=4.2,<5.3",
        "djangorestframework>=3.14",
        "django-filter>=23.5",
    ],
    extras_require={
        "uploads": ["django-import-export>=3.3"],
        "test": ["coverage[toml]>=7.0"],
    },
)

