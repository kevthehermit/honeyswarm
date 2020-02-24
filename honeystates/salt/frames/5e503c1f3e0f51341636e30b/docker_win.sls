# Just copied a state file for something random

# https://docs.saltstack.com/en/master/topics/windows/windows-package-manager.html

"""
salt -G 'os:windows' pkg.list_pkgs
salt winminion pkg.list_available firefox
salt winminion pkg.install 'firefox'
salt winminion pkg.install 'firefox' version=16.0.2
"""

# First install python

 
{% set EXE_VERSIONS = [('3.7.4', '3.7.4150.0'),
                       ('3.7.3', '3.7.3150.0'),
                       ('3.7.0', '3.7.150.0'),
                       ('3.6.8', '3.6.8150.0'),
                       ('3.6.6', '3.6.6150.0'),
                       ('3.5.4', '3.5.4150.0'),
                       ('3.5.2', '3.5.2150.0'),
                       ('3.5.1', '3.5.1150.0')] %}
{% set MSI_VERSIONS = [('3.4.3', '3.4.3150'),
                       ('3.4.2', '3.4.2150'),
                       ('3.4.1', '3.4.1150'),
                       ('3.3.3', '3.3.3150')] %}
python3_x86:
  {% for VER, RAW_VER in EXE_VERSIONS %}
  '{{ RAW_VER }}':
    full_name: 'Python {{ VER }} (32-bit)'
    installer: 'https://www.python.org/ftp/python/{{ VER }}/python-{{ VER }}.exe'
    install_flags: '/quiet InstallAllUsers=1'
    uninstaller: 'https://www.python.org/ftp/python/{{ VER }}/python-{{ VER }}.exe'
    uninstall_flags: '/quiet /uninstall'
    msiexec: False
    locale: en_US
    reboot: False
  {% endfor %}
  {% for VER, RAW_VER in MSI_VERSIONS %}
  '{{ RAW_VER }}':
    full_name: 'Python {{ VER }} (32-bit)'
    installer: 'https://www.python.org/ftp/python/{{ VER }}/python-{{ VER }}.msi'
    install_flags: '/qn ALLUSERS=1 /norestart'
    uninstaller: 'https://www.python.org/ftp/python/{{ VER }}/python-{{ VER }}.msi'
    uninstall_flags: '/qn /norestart'
    msiexec: True
    locale: en_US
    reboot: False
  {% endfor %}