#!/usr/bin/python3

import os

from setuptools import setup, Command, find_packages

class CleanCommand(Command):
    user_options = []
    def initialize_options(self):
        #pylint: disable=attribute-defined-outside-init
        self.cwd = None
    def finalize_options(self):
        #pylint: disable=attribute-defined-outside-init
        self.cwd = os.getcwd()
    def run(self):
        assert os.getcwd() == self.cwd, 'Must be in package root: %s' % self.cwd
        os.system('rm -rf ./build ./dist ./*.pyc ./*.egg-info')

setup(
    name='pcs',
    version='0.10.0.1',
    description='Pacemaker Configuration System',
    author='Chris Feist',
    author_email='cfeist@redhat.com',
    url='https://github.com/ClusterLabs/pcs',
    packages=find_packages(),
    package_data={'pcs':[
        'bash_completion',
        'pcs.8',
        'pcs',
        'test/resources/*.xml',
        'test/resources/*.conf',
        'test/resources/qdevice-certs/*'
    ]},
    zip_safe=False,
    entry_points={
        'console_scripts': [
            'pcs = pcs.app:main',
            'pcsd = pcs.run:daemon',
            'pcs_snmp_agent = pcs.run:pcs_snmp_agent',
        ],
    },
    cmdclass={
        'clean': CleanCommand,
    }
)
