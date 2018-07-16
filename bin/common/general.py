#!/usr/bin/env python
'''
General python functions that don't fit in it's own file.

'''

__author__ = "daniel.lindh@cybercow.se"
__copyright__ = "Copyright 2011, The System Console project"
__maintainer__ = "Daniel Lindh"
__email__ = "syco@cybercow.se"
__credits__ = ["???"]
__license__ = "???"
__version__ = "1.0.0"
__status__ = "Production"

from random import choice
from socket import *
import glob
import hashlib
import inspect
import os
import re
import shutil
import string
import subprocess
import time
import urllib
import struct
import config
import install

from constant import *
import app
import expect
import pexpect
import ssh

def remove_file(path):
    '''
    Remove file(s) in path, can use wildcard.

    Example
    remove_file('/var/log/libvirt/qemu/%s.log*')

    '''
    for file_name in glob.glob(path):
        app.print_verbose('Remove file %s' % file_name)
        os.remove('%s' % file_name)

def grep(file_name, pattern):
    '''
    Return true if regexp pattern is included in the file.

    '''
    if (os.access(file_name, os.R_OK)):
        prog = re.compile(pattern)
        for line in open(file_name):
            if prog.search(line):
                return True
    return False

def delete_install_dir():
    '''
    Delete the folder where installation files are stored during installation.

    '''
    if (os.access(app.INSTALL_DIR, os.W_OK | os.X_OK)):
        app.print_verbose("Delete " + app.INSTALL_DIR + " used during installation.")
        os.chdir("/tmp")
        x("rm -rf " + app.INSTALL_DIR)

def create_install_dir():
    '''
    Create folder where installation files are stored during installation.

    It could be files downloaded with wget, like rpms or tar.gz files, that should
    be installed.

    '''
    import atexit

    if (not os.access(app.INSTALL_DIR, os.W_OK | os.X_OK)):
        app.print_verbose("Create install dir " + app.INSTALL_DIR + " to use during installation.")
        x("mkdir -p " + app.INSTALL_DIR)
        atexit.register(delete_install_dir)

    if (os.access(app.INSTALL_DIR, os.W_OK | os.X_OK)):
        x("chmod 777 " + app.INSTALL_DIR)
        os.chdir(app.INSTALL_DIR)
    else:
        raise Exception("Can't create install dir.")


def get_first_ip_from_nic(nic):

    _install_netifaces()
    import netifaces

    return netifaces.ifaddresses(nic)[netifaces.AF_INET][0]['addr']


def get_front_nic_name():

    _install_netifaces()
    import netifaces

    front_net = config.general.get_front_subnet()

    for nic in netifaces.interfaces():
        ip = get_first_ip_from_nic(nic)
        if _address_in_network(ip, front_net):
            return nic


def get_install_dir():
    '''
    Create and return the installtion tmp dir.

    This dir will automatically be deleted when the script ends.

    '''
    create_install_dir()
    return app.INSTALL_DIR


def install_packages(packages):
    """
    Install the supplied packages unless they are already installed
    packages supplied as whitespace separated string.
    """

    cmd = "("
    for package in packages.split(" "):
        if len(cmd) > 1:
            cmd += ' && '
        cmd += "rpm -q %s" % package

    cmd += ") || yum install -y %s" % packages

    x(cmd)


def download_file(src, dst=None, user="", remote_user=None,
                  remote_password=None, cookie=None, md5=None, sha1=None):
    """
    Download a file using wget, and place in the installation tmp folder.

    """
    app.print_verbose("Download: " + src)
    if not dst:
        dst = os.path.basename(src)

    dst_file = app.INSTALL_DIR + dst

    create_install_dir()
    if not os.access(dst_file, os.F_OK):
        cmd = "-O " + dst_file
        if remote_user:
            cmd += " --user \"" + remote_user + "\" "

            if remote_password:
                cmd += " --password \"" + remote_password+ "\" "

        shell_exec("wget " + cmd + " " + src, user=user)

        # Looks like the file is not flushed to disk immediatley,
        # making the script not able to read the file immediatley after it's
        # downloaded. A sleep fixes this.
        time.sleep(2)

    if not os.access(dst_file, os.F_OK):
        raise Exception("Couldn't download: " + dst_file)

    if os.path.getsize(dst_file) == 0:
        raise Exception("File has size zero: " + dst_file)

    if md5 and md5checksum(dst_file) != md5:
        raise Exception("MD5 Checksum dont match for " + dst_file)

    if sha1 and sha1checksum(dst_file) != sha1:
        raise Exception("SHA! Checksum dont match for " + dst_file)


def urlretrive(src_url, dst_filename):
    '''
    Download a file using urlretrive, and place in the installation tmp folder.

    urlretrive("http://www.example.com/file.gz", "file.gz")

    '''
    app.print_verbose("Download: " + src_url)
    dst_path = "%s/%s" % (app.INSTALL_DIR, dst_filename)

    create_install_dir()
    if (not os.access(app.INSTALL_DIR + dst_filename, os.F_OK)):
        urllib.urlretrieve (src_url, dst_path)

    if (not os.access(app.INSTALL_DIR + dst_filename, os.F_OK)):
        raise Exception("Couldn't download: " + dst_filename)

    return dst_path

# Restricted version of string.punctuation, has removed some "dangerous" chars,
# that might crash some scripts if not properly escaped.
punctuation = '!#$%()*+,-./:;<=>?@[\]^_{|}~'
def generate_password(length=8, chars=string.letters + string.digits + punctuation):
    '''Generate a random password'''
    return ''.join([choice(chars) for i in range(length)])


def is_server_alive(server, port, proto='tcp'):
    """Is port on a server responding, this assumes the server is alive."""
    try:
        if proto=='udp':
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        elif proto=='tcp':
            s = socket(AF_INET, SOCK_STREAM)
        else:
            raise Exception("Invalid proto")
        s = socket(AF_INET, SOCK_STREAM)
        s.settimeout(5)
        result = s.connect_ex((server, int(port)))
    finally:
        s.close()

    if result == 0:
        return True
    return False


def is_server_root_open(server):
    """Check if root account is accessible."""
    ssh_con = ssh.Ssh(server, app.get_root_password())
    try:
        ssh_con.ssh_exec('whoami', silent = True)
        return True
    except Exception:
        return False


def retrieve_from_server(remote_server, remote_path, local_path, verify_local=None, remove_remote_files=False):
    """
    This function uses scp with syco root login to retrieve a directory or file from
    a remote server to the local machine.

    It will automatically wait for root login and verify the files locally after the copy
    if a list of files is specified with the verify_local keyword argument
    """
    wait_for_server_root_login(remote_server)

    while True:
        _scp_from(remote_server, remote_path, local_path)

        if not verify_local:
            # Assume success
            break

        if not _do_files_exist(verify_local):
            app.print_verbose(
                    "Waiting for files to be successfully copied from %s%s" % (
                        remote_server, remote_path
                    )
                )
        else:
            break

    if remove_remote_files:
        run_remote_command(remote_server, "rm -rf {0}".format(remote_path))


def run_remote_command(host, command):
    shell_run("ssh root@{0} {1}".format(host, command),
                  events={
                      'Are you su1re you want to continue connecting \(yes\/no\)\?': "YES\n",
                      host + "\'s password\:": app.get_root_password() + "\n"
                  }
              )


def wait_for_server_root_login(server):
    """Wait until the root account on the sever is accessible"""
    if server is None:
        raise Exception("Servers wasn't given.")

    app.print_verbose(
        "\nWait until " + str(server) +
        " on port 22 is accessible using the root account.",
        new_line=False
    )
    while not is_server_root_open(server):
        app.print_verbose(".", new_line=False, enable_caption=False)
        time.sleep(5)
    app.print_verbose(".")


def wait_for_server_to_start(server, port):
    """Wait until a network port is opened."""
    app.print_verbose("\nWait until " + str(server) + " on port " + str(port) + " starts.", new_line=False)
    while(not is_server_alive(server, port)):
        app.print_verbose(".", new_line=False, enable_caption=False)
        time.sleep(5)
    app.print_verbose(".")


def wait_for_procesess_to_finish(name):
    while(True):
        num_of_processes = subprocess.Popen(
            "ps aux | grep " + name, stdout=subprocess.PIPE, shell=True
        ).communicate()[0].count("\n")
        if num_of_processes <=2:
            break
        app.print_verbose(str(num_of_processes-2) + " processes running, wait 10 more sec.")
        time.sleep(10)

def shell_exec(command, user="", cwd=None, events=None, output=True):
    '''
    Execute a shell command using pexpect, and writing verbose affected output.

    '''
    # Build command to execute
    args=[]
    if (user):
        args.append(user)
    args.append('-c ' + command)

    if (output):
        app.print_verbose(BOLD +"Command: su " + RESET + user + " -c '" + command + "'")

    # Setting default events
    if events is None:
        events = {}

    events["Verify the SYCO master password:"] = app.get_master_password

    keys = events.keys()
    value = events.values()

    num_of_events = len(keys)

    # Timeout for ssh.expect
    keys.append(pexpect.TIMEOUT)

    # When ssh.expect reaches the end of file. Probably never
    # does, is probably reaching [PEXPECT]# first.
    keys.append(pexpect.EOF)

    # Set current working directory
    if (cwd == None):
        cwd = os.getcwd()

    out = expect.spawn("su", args, cwd=cwd)

    if (not output):
        out.disable_output()

    if (output):
        app.print_verbose("---- Result ----", 2)
    stdout = ""
    index = 0
    while (index < num_of_events+1):
        index = out.expect(keys, timeout=3600)
        stdout += out.before

        if index >= 0 and index < num_of_events:
            if (inspect.isfunction(value[index])):
                out.send(str(value[index]())  + "\n")
            else:
                out.send(value[index])
        elif index == num_of_events:
            app.print_error("Catched a timeout from pexpect.expect, lets try again.")

    if (out.exitstatus and output):
        app.print_error("Invalid exitstatus %d" % out.exitstatus)

    if (out.signalstatus and output):
        app.print_error("Invalid signalstatus %d - %s" % out.signalstatus, out.status)

    # An extra line break for the looks.
    if (output and stdout and app.options.verbose >= 2):
        print("\n"),

    out.close()

    return stdout

def shell_run(command, user="root", cwd=None, events={}):
    '''
    Execute a shell command using pexpect.run, and writing verbose affected output.

    Use shell_exec if possible.

    #TODO: Try to replace this with shell_exec

    '''
    command = "su " + user + ' -c "' + command + '"'

    # Need by Ubuntu when doing SU.
    #if (user != ""):
    #  user_password = app.get_user_password(user)
    #  events["(?i)Password: "] = user_password + "\n"

    # Set current working directory
    if (cwd == None):
        cwd = os.getcwd()

    app.print_verbose(BOLD + "Command: " + RESET + command)
    (stdout, exit_status) = pexpect.run(command,
                                        cwd=cwd,
                                        events=events,
                                        withexitstatus=True,
                                        timeout=10000
                                        )

    app.print_verbose("---- Result (" + str(exit_status) + ")----", 2)
    app.print_verbose(stdout, 2)

    if (exit_status == None):
        raise Exception("Couldnt execute " + command)

    return stdout


X_OUTPUT_NONE = 0
X_OUTPUT_ALL = 1
X_OUTPUT_CMD = 2


def x_communicate(command, user = "", output = X_OUTPUT_ALL, cwd=None):
    if (user):
        command = command.replace('"', '\\"')
        command="su " + user + ' -c "' + command + '"'

    if (cwd == None):
        cwd = os.getcwd()
    elif (output > X_OUTPUT_NONE):
        app.print_verbose(BOLD + "Command: " + RESET + "cd " + cwd)

    if (output > X_OUTPUT_NONE):
        app.print_verbose(BOLD + "Command: " + RESET + command)

    p = subprocess.Popen(command, shell=True, cwd=cwd)
    (stdout, stderr) = p.communicate()


def x(command, user = "", output = X_OUTPUT_ALL, cwd=None):
    '''
    Execute a shell command and handles output verbosity.

    '''
    if (user):
        command = command.replace('"', '\\"')
        command="su " + user + ' -c "' + command + '"'

    if (cwd == None):
        cwd = os.getcwd()
    elif (output > X_OUTPUT_NONE):
        app.print_verbose(BOLD + "Command: " + RESET + "cd " + cwd)

    if (output > X_OUTPUT_NONE):
        app.print_verbose(BOLD + "Command: " + RESET + command)

    p = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd)

    return handle_subprocess(p, output)


def handle_subprocess(p, output):
    stdout=""
    stderr=""
    while (True):
        for txt in p.stdout:
            # Only write caption once.
            if (output == X_OUTPUT_ALL):
                if (stdout==""):
                    app.print_verbose("---- Result ----", 2)
                app.print_verbose(txt, 2, new_line=False)
            stdout+=txt

        for txt in p.stderr:
            stderr += txt

        if (p.poll() != None):
            break

    if (stderr and output == X_OUTPUT_ALL):
        app.print_error(stderr.strip())

    #
    # Error messages is enough to print. A failure doesn't always mean a failure.
    # For example [ -f '/etc/cron.allow' ] && chmod og-rwx /etc/cron.allow
    # will return returncode 1, when the file doesn't exist.
    # if (p.returncode and output == X_OUTPUT_ALL):
    #   app.print_error("Invalid returncode %d" % p.returncode)

    # An extra line break for the looks.
    if ((stdout or stderr) and app.options.verbose >=2 and output == X_OUTPUT_ALL):
        print("\n"),

    return stdout + str(stderr)

def set_config_property(file_name, search_exp, replace_exp, add_if_not_exist=True):
    '''
    Change or add a config property to a specific value.

    #TODO: Optimize, do more then one change in the file at the same time.
    #TODO: Replace with scOpen??

    '''
    if os.path.exists(file_name):
        if (replace_exp == None):
            replace_exp = ""

        exist = False
        try:
            shutil.copyfile(file_name, file_name + ".bak")
            r = open(file_name + ".bak", 'r')
            w = open(file_name, 'w')
            for line in r:
                if re.search(search_exp, line):
                    line = re.sub(search_exp, replace_exp, line)
                    exist = True
                w.write(line)

            if (exist == False and add_if_not_exist):
                w.write(replace_exp + "\n")
        finally:
            r.close()
            w.close()
            os.remove(file_name + ".bak")
    else:
        w = open(file_name, 'w')
        w.write(replace_exp + "\n")
        w.close()


def set_config_property_batch(file_name, key_value_dict, add_if_not_exist=True):
    for key, value in key_value_dict.iteritems():
        set_config_property(file_name, key, value, add_if_not_exist)


def get_config_value(file_name, config_name):
    '''
    Get a value from an option in a config file.

    '''
    prog = re.compile("[\s]*" + config_name + "[:=\s]*(.*)")
    for line in open(file_name):
        m = prog.search(line)
        if m:
            return m.group(1)
    return False


def store_file(file_name, value):
    '''
    Store a text in a file.

    '''
    x("echo '%s' > %s" % (value, file_name))

# TODO: Set a good name.
def set_config_property2(file_name, replace_exp):
    search_exp = r".*" + re.escape(replace_exp) + r".*"
    set_config_property(file_name, search_exp, replace_exp)


def md5checksum(filePath):
    fh = open(filePath, 'rb')
    m = hashlib.md5()
    while True:
        data = fh.read(8192)
        if not data:
            break
        m.update(data)
    return m.hexdigest()

def sha1checksum(filePath):
    fh = open(filePath, 'rb')
    m = hashlib.sha1()
    while True:
        data = fh.read(8192)
        if not data:
            break
        m.update(data)
    return m.hexdigest()

def use_original_file(filename):
    '''
    Backup original file, and restore if backup exist.

    With this procedure it's possible to have script makeing changes to a file
    with sed/awk, and then run the script again to to make the same changes
    to the original data.

    '''
    if not filename.startswith('/'):
        raise Exception("Filename {0} must start with /.".format(filename))
    syco_bak_folder = '/tmp/syco_bak'
    bak_file = '{0}{1}'.format(syco_bak_folder, filename)

    if os.path.exists(bak_file):
        x("cp -f {0} {1}".format(bak_file, filename))
    else:
        bak_folder = bak_file.rsplit('/', 1)[0]
        x("mkdir -p {0}".format(bak_folder))
        x("cp -f {0} {1}".format(filename, bak_file))


def require_linux_user(required_user):
    """Check if script is executed as root, raise Exception if not."""
    user = x("whoami", output = X_OUTPUT_NONE).strip()
    if required_user != user:
        raise Exception("Invalid user, you are %s but need to be %s. " % (
            user, required_user
        ))

def _scp_from(server, src, dst):
    shell_run("scp -r " + server + ":" + src + " " + dst,
                      events={
                          'Are you sure you want to continue connecting \(yes\/no\)\?': "YES\n",
                          server + "\'s password\:": app.get_root_password() + "\n"
                      }
    )

def _do_files_exist(files):
    for file in files:
        if not os.path.exists(file):
            return False

    return True

def _address_in_network(ip, net):

   ipaddr = struct.unpack('<L', inet_aton(ip))[0]
   netaddr, bits = net.split('/')
   netmask = struct.unpack('<L', inet_aton(netaddr))[0] & ((2L<<int(bits)-1) - 1)

   return ipaddr & netmask == netmask

def _install_netifaces():

    install.epel_repo()
    install_packages("python-netifaces")
