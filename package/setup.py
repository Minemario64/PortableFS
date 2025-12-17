from setuptools import setup, find_packages

setup(
    name="pfs",
    version="1.0.0",
    description="A Python implementation of the PortableFS spec",
    packages=find_packages(),
    install_requires=[
        "rich",
        "tqdm"
    ],
    author="Minemario64",
    classifiers=[
        'Programming Language :: Python :: 3.13'
    ]
)