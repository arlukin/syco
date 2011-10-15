#!/usr/bin/env python
'''
Install cobbler.

'''

__author__ = "daniel.lindh@cybercow.se"
__copyright__ = "Copyright 2011, The System Console project"
__maintainer__ = "Daniel Lindh"
__email__ = "syco@cybercow.se"
__credits__ = ["???"]
__license__ = "???"
__version__ = "1.0.0"
__status__ = "Production"

import os
import shutil
import time
import subprocess

import app
import config
import general
import iptables
import version
import install

# The version of this module, used to prevent
# the same script version to be executed more then
# once on the same host.
SCRIPT_VERSION = 3

def build_commands(commands):
  commands.add("install-cobbler",        install_cobbler, help="Install cobbler on the current server.")
  commands.add("install-cobbler-refresh", setup_all_systems, help="Refresh settings and repo info.")

def install_cobbler(args):
  '''
  Install cobbler on current host.

  '''
  app.print_verbose("Install cobbler version: %d" % SCRIPT_VERSION)
  version_obj = version.Version("installCobbler", SCRIPT_VERSION)
  version_obj.check_executed()

  # Initialize password.
  app.get_root_password_hash()

  _install_cobbler()

  iptables.add_cobbler_chain()
  iptables.save()

  _modify_cobbler_settings()

  _import_repos()
  setup_all_systems(args)

  version_obj.mark_executed()

def setup_all_systems(args):
  '''
  Update cobbler with all settings in install.cfg.

  '''
  _refresh_repo()
  _refresh_all_profiles()
  _remove_all_systems()
  _add_all_systems()
  _cobbler_sync()

def _install_cobbler():
  #
  # Install cobbler
  #
  # See http://linux.die.net/man/1/cobbler
  # See https://fedorahosted.org/cobbler/wiki/DownloadInstructions
  # See https://fedorahosted.org/cobbler/wiki/UsingCobblerImport
  # See http://www.ithiriel.com/content/2010/02/22/installing-linux-vms-under-kvm-cobbler-and-koan

  # Cobbler packages are in the EPEL repo.
  install.epel_repo()

  # To get cobbler and kvm work correct.
  general.shell_exec("yum -y install yum-utils cobbler koan httpd")
  general.shell_exec("/sbin/chkconfig httpd on")

  # This allows the Apache httpd server to connect to the network
  general.shell_exec('/usr/sbin/semanage fcontext -a -t public_content_rw_t "/var/lib/tftpboot/.*"')
  general.shell_exec('/usr/sbin/semanage fcontext -a -t public_content_rw_t "/var/www/cobbler/images/.*"')
  general.shell_exec('/usr/sbin/semanage fcontext -a -t httpd_sys_content_rw_t "/var/lib/cobbler/webui_sessions/.*"')
  general.shell_exec('restorecon -R -v "/var/lib/tftpboot/"')
  general.shell_exec('restorecon -R -v "/var/www/cobbler/images"')
  general.shell_exec('restorecon -R -v "/var/lib/cobbler/webui_sessions/"')

  # Enables cobbler to read/write public_content_rw_t
  general.shell_exec('/usr/sbin/setsebool -P cobbler_anon_write on')

  # Enable httpd to connect to cobblerd (optional, depending on if web interface is installed)
  # Notice: If you enable httpd_can_network_connect_cobbler and you should switch httpd_can_network_connect off
  general.shell_exec('/usr/sbin/setsebool -P httpd_can_network_connect off')
  general.shell_exec('/usr/sbin/setsebool -P httpd_can_network_connect_cobbler on')

  #Enabled cobbler to use rsync etc.. (optional)
  general.shell_exec('/usr/sbin/setsebool -P cobbler_can_network_connect on')

  #Enable cobbler to use CIFS based filesystems (optional)
  #general.shell_exec('/usr/sbin/setsebool -P cobbler_use_cifs on')

  # Enable cobbler to use NFS based filesystems (optional)
  #general.shell_exec('/usr/sbin/setsebool -P cobbler_use_nfs on')

  _install_custom_selinux_policy()

  # Double check your choices
  general.shell_exec('getsebool -a|grep cobbler')

  app.print_verbose("Update xinetd config files")
  general.set_config_property("/etc/xinetd.d/tftp", '[\s]*disable[\s]*[=].*', "        disable                 = no")
  general.set_config_property("/etc/xinetd.d/rsync", '[\s]*disable[\s]*[=].*', "        disable         = no")
  general.shell_exec("/etc/init.d/xinetd restart")

def _modify_cobbler_settings():
  app.print_verbose("Update cobbler config files")
  general.set_config_property("/etc/cobbler/settings", '^server:.*', "server: " + config.general.get_installation_server_ip())
  general.set_config_property("/etc/cobbler/settings", '^next_server:.*', "next_server: " + config.general.get_installation_server_ip())
  general.set_config_property("/etc/cobbler/settings", '^default_virt_bridge:.*', "default_virt_bridge: br0")
  general.set_config_property("/etc/cobbler/settings", '^default_password_crypted:.*', "default_password_crypted: " + app.get_root_password_hash())
  general.set_config_property("/etc/cobbler/settings", '^default_virt_type:.*', "default_virt_type: qemu")
  general.set_config_property("/etc/cobbler/settings", '^anamon_enabled:.*', "anamon_enabled: 1")
  general.set_config_property("/etc/cobbler/settings", '^yum_post_install_mirror:.*', "yum_post_install_mirror: 1")
  general.set_config_property("/etc/cobbler/settings", '^manage_dhcp:.*', "manage_dhcp: 0")

  shutil.copyfile(app.SYCO_PATH + "/var/kickstart/cobbler.ks", "/var/lib/cobbler/kickstarts/cobbler.ks")

  # Config crontab to update repo automagically
  general.set_config_property2("/etc/crontab", "01 4 * * * syco install-cobbler-repo")

  # Set apache servername
  general.set_config_property("/etc/httpd/conf/httpd.conf", "#ServerName www.example.com:80", "ServerName " + config.general.get_installation_server() + ":80")

  general.shell_exec("/etc/init.d/httpd restart")

  # TODO: Do we need no_return=True
  # general.shell_exec("/etc/init.d/cobblerd restart", no_return=True)
  general.shell_exec("/etc/init.d/cobblerd restart")

  # Wait for cobblered to restart
  time.sleep(1)

  # Iptables rules need be fixed now.
  general.shell_exec("cobbler get-loaders")

  # Setup distro/repo for centos
  general.shell_exec("cobbler check")

def _import_repos():
  if (os.access("/var/www/cobbler/ks_mirror/centos-x86_64", os.F_OK)):
    app.print_verbose("Centos-x86_64 already imported")
  else:
    general.shell_exec('cobbler import --path=rsync://ftp.sunet.se/pub/Linux/distributions/centos/6/os/x86_64/ --name=centos --arch=x86_64')

  if (os.access("/var/www/cobbler/repo_mirror/centos-updates-x86_64", os.F_OK)):
    app.print_verbose("Centos-updates-x86_64 repo already imported")
  else:
    general.shell_exec("cobbler repo add --arch=x86_64 --name=centos-updates-x86_64 --mirror=rsync://ftp.sunet.se/pub/Linux/distributions/centos/6/updates/x86_64/")
    general.shell_exec("cobbler repo add --arch=x86_64 --name=epel-x86_64 --mirror=http://download.fedora.redhat.com/pub/epel/6/x86_64")
    general.shell_exec("cobbler reposync")

def _refresh_all_profiles():
  # Removed unused distros/profiles
  general.shell_exec("cobbler distro remove --name centos-xen-x86_64")
  general.shell_exec("cobbler profile remove --name centos-x86_64")

  # Setup installation profiles and systems
  general.shell_exec("cobbler profile remove --name=centos-vm_host")
  general.shell_exec(
    'cobbler profile add --name=centos-vm_host' +
    ' --distro=centos-x86_64' +
    ' --repos="centos-updates-x86_64 epel-x86_64"' +
    ' --kickstart=/var/lib/cobbler/kickstarts/cobbler.ks'
  )

  general.shell_exec("cobbler profile remove --name=centos-vm_guest")
  general.shell_exec(
    'cobbler profile add --name=centos-vm_guest' +
    ' --parent=centos-vm_host' +
    ' --virt-type=qemu' +
    ' --virt-ram=1024 --virt-cpus=1' +
    ' --virt-bridge=br0'
  )

def _remove_all_systems():
  stdout = general.shell_exec("cobbler system list")
  for name in stdout.rsplit():
    general.shell_exec("cobbler system remove --name " + name)

def _add_all_systems():
  for hostname in config.get_servers():
    # Is a KVM host?
    if config.host(hostname).is_host():
      _host_add(hostname)
    else:
      _guest_add(hostname)

def _host_add(hostname):
  app.print_verbose("Add baremetalhost " + hostname)

  general.shell_exec(
    "cobbler system add --profile=centos-vm_host " +
    "--name=" + hostname + " --hostname=" + hostname + " " +
    '--name-servers="' + config.general.get_front_resolver_ip() + '" ' +
    ' --ksmeta="disk_var_mb=' + str(config.host(hostname).get_disk_var_mb()) +
    ' total_disk_mb=' + str(config.host(hostname).get_total_disk_mb()) +
    ' disk_swap_mb=' + str(config.host(hostname).get_disk_swap_mb()) +
    ' boot_device=' + str(config.host(hostname).get_boot_device("cciss/c0d0")) + '"')

  _setup_network(hostname)

  general.shell_exec(
    "cobbler system edit --name=" + hostname +
    " --interface=eth0" +
    " --mac=" + str(config.host(hostname).get_back_mac()))

  general.shell_exec(
    "cobbler system edit --name=" + hostname +
    " --interface=eth1" +
    " --mac=" + str(config.host(hostname).get_front_mac()))

def _guest_add(hostname):
  app.print_verbose("Add guest " + hostname)

  general.shell_exec(
    "cobbler system add --profile=centos-vm_guest"
    " --virt-path=\"/dev/VolGroup00/" + hostname + "\"" +
    " --virt-ram=" + str(config.host(hostname).get_ram()) +
    " --virt-cpus=" + str(config.host(hostname).get_cpu()) +
    " --name=" + hostname + " --hostname=" + hostname +
    ' --name-servers="' + config.general.get_front_resolver_ip() + '"' +
    ' --ksmeta="disk_var_mb=' + str(config.host(hostname).get_disk_var_mb()) +
    ' total_disk_mb=' + str(config.host(hostname).get_total_disk_mb()) +
    ' disk_swap_mb=' + str(config.host(hostname).get_disk_swap_mb()) +
    ' boot_device=' + str(config.host(hostname).get_boot_device("vda")) + '"')

  _setup_network(hostname)

  general.shell_exec(
    "cobbler system edit --name=" + hostname +
    " --interface=eth0" +
    ' --virt-bridge=br0')

  general.shell_exec(
    "cobbler system edit --name=" + hostname +
    " --interface=eth1" +
    ' --virt-bridge=br1')

def _setup_network(hostname):
  cmd  = "cobbler system edit --name=" + hostname
  cmd += " --interface=eth0 --static=1"

  if config.host(hostname).get_back_ip():
    cmd += " --ip=" + config.host(hostname).get_back_ip()
    cmd += " --subnet=" + config.general.get_back_netmask()

  if config.general.get_back_gateway_ip():
    cmd += " --gateway=" + config.general.get_back_gateway_ip()

  general.shell_exec(cmd)

  cmd  = "cobbler system edit --name=" + hostname
  cmd += " --interface=eth1 --static=1"

  if config.host(hostname).get_front_ip():
    cmd += " --ip=" + config.host(hostname).get_front_ip()
    cmd += " --subnet=" + config.general.get_front_netmask()

  if config.general.get_front_gateway_ip():
    cmd += " --gateway=" + config.general.get_front_gateway_ip()

  general.shell_exec(cmd)

def _refresh_repo():
  '''
  Refresh all repos on the cobbler/repo server.

  Syco uses lots of external files, this function downloads all latest
  versions.

  TODO: Move the downloads array to each script, and this function
  should retrieve a download array from each script.

  '''
  #downloads = {}
  #downloads['jdk-6u26-linux-x64-rpm.bin'] = 'http://cds.sun.com/is-bin/INTERSHOP.enfinity/WFS/CDS-CDS_Developer-Site/en_US/-/USD/VerifyItem-Start/jdk-6u26-linux-x64-rpm.bin?BundledLineItemUUID=pGSJ_hCvabIAAAEu870pGPfd&OrderID=1ESJ_hCvsh4AAAEu1L0pGPfd&ProductID=oSKJ_hCwOlYAAAEtBcoADqmS&FileName=/jdk-6u26-linux-x64-rpm.sbin'

  #for dst, src in downloads.items():
  #  general.shell_exec("wget --background -O /var/www/cobbler/repo_mirror/" + dst + " "  + src)

  #general.wait_for_processes_to_finish('wget')

  general.shell_exec("cobbler reposync --tries=3 --no-fail")

def _cobbler_sync():
  general.shell_exec("cobbler sync")
  general.shell_exec("cobbler report")

def _install_custom_selinux_policy():
  '''
  Install customized SELinux policy for cobbler.
  '''
  install.package("policycoreutils")

  te = app.SYCO_PATH + "/var/selinux/cobbler.te"
  mod = "/tmp/cobbler.te"
  pp = "/tmp/cobbler.te"

  general.shell_exec("checkmodule -M -m -o %s %s" % (mod, te))
  general.shell_exec("semodule_package -o %s -m %s" % (pp, mod))
  general.shell_exec("semodule -i %s" % pp)
