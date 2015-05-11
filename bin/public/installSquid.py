#!/usr/bin/env python
'''
This script will install Squid Caching Proxy on the targeted server.

This script is dependent on the following config files for this script to work.
    var/squid/*

'''

__author__ = "David Skeppstedt"
__copyright__ = "Copyright 2014, Fareoffice CRS AB"
__maintainer__ = "David Skeppstedt"
__email__ = "davske@fareoffice.com"
__credits__ = ["Daniel Lindh, Mattias Hemmingsson, Kristoffer Borgstrom"]
__license__ = "???"
__version__ = "1.5"
__status__ = "Production"

import os
from general import x, urlretrive
import ssh
import config
import iptables
import socket
import install
import app
import password
import version
import scopen
import fcntl
import struct
import sys
import re

script_version = 1

SQUID_CONF_DIR = "/etc/squid/"

def build_commands(commands):
    '''
    Defines the commands that can be executed through the syco.py shell script.
    '''
    commands.add("install-squid", install_squid, help="Install Squid Caching Proxy on the server.")
    commands.add("uninstall-squid", uninstall_squid, help="Uninstall Squid Caching Proxy from the server.")

def _service(service,command):
    x("/sbin/service {0} {1}".format(service, command))

def _chkconfig(service,command):
    x("/sbin/chkconfig {0} {1}".format(service, command))

def install_haproxy(args):
    global SYCO_PLUGIN_PATH, ACCEPTED_SQUID_ENV

    SYCO_PLUGIN_PATH = app.get_syco_plugin_paths("/var/squid/").next()

    app.print_verbose("Install Squid Caching Proxy version: %d" % script_version)
    version_obj = version.Version("InstallSquid", script_version)
    version_obj.check_executed()
    os.chdir("/")

    x("yum install -y squid")
    _configure_iptables()
    _configure_squid()

    version_obj.mark_executed()

def _configure_haproxy():
    x("mv {0}squid.conf {0}org.squid.conf".format(SQUID_CONF_DIR))
    x("cp {0}/squid.conf {2}squid.conf".format(SYCO_PLUGIN_PATH, SQUID_ENV, SQUID_CONF_DIR))
    x("mkdir -p {0}/acl".format(SQUID_CONF_DIR))
    x("cp {0}/acl/* {1}acl/".format(SYCO_PLUGIN_PATH, SQUID_CONF_DIR))

    scopen.scOpen(SQUID_CONF_DIR + "squid.conf").replace("${ENV_IP}", get_ip_address('eth0'))

    _chkconfig("squid","on")
    _service("squid","restart")

def _configure_iptables():
    '''
    Accept TCP traffic on 3128 from localnets and allow output to anywhere on port 80 and 443

    '''
    iptables.iptables("-A syco_input -p tcp -m multiport --dports 3128 -j allowed_tcp")
    iptables.iptables("-A syco_output -p tcp -m multiport --dports 80,443 -j allowed_tcp")
    iptables.save()

def get_ip_address(ifname):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    return socket.inet_ntoa(fcntl.ioctl(
        s.fileno(),
        0x8915,  # SIOCGIFADDR
        struct.pack('256s', ifname[:15])
    )[20:24])

def uninstall_haproxy(args=""):
    '''
    Remove Squid Caching Proxy from the server.
    '''
    app.print_verbose("Uninstall Squid Caching Proxy")
    os.chdir("/")

    _chkconfig("squid","off")
    _service("squid","stop")

    x("yum -y remove squid")
    x("rm -rf {0}*".format(SQUID_CONF_DIR))
    iptables.iptables("-D syco_input -p tcp -m multiport --dports 3128 -j allowed_tcp")
    iptables.iptables("-D syco_output -p tcp -m multiport --dports 80,443 -j allowed_tcp")
    iptables.save()


'''
End of Squid Caching Proxy installation script.
'''