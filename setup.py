#!/usr/bin/env python3

from pathlib import Path

import setuptools  # type:ignore[import]

package_name = 'encode_framework'

exec(Path(f'{package_name}/_metadata.py').read_text(), meta := dict[str, str]())

readme = Path('README.md').read_text()
requirements = Path('requirements.txt').read_text()


setuptools.setup(
    name=package_name,
    version=meta.get('__version__'),
    author=meta.get('__author_name__'),
    author_email=meta.get('__author_email__'),
    maintainer=meta.get('__maintainer_name__'),
    maintainer_email=meta.get('__maintainer_email__'),
    description=meta.get('__doc__'),
    long_description=readme,
    long_description_content_type='text/markdown',
    project_urls={
        'Source Code': 'https://github.com/Lights-Silly-Projects/Encoding-Framework',
        'Contact': 'https://discord.gg/qxTxVJGtst',
    },
    install_requires=requirements,
    python_requires='>=3.11',
    packages=[
        package_name,
        f"{package_name}.config",
        f"{package_name}.encode",
        f"{package_name}.filter",
        f"{package_name}.git",
        f"{package_name}.integrations",
        f"{package_name}.script",
        f"{package_name}.types",
        f"{package_name}.util",
    ],
    package_data={
        package_name: ['py.typed']
    },
    classifiers=[
        'Programming Language :: Python :: 3',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
    ],
)
