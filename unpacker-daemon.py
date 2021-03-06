#!/usr/bin/env python
# unpacker-daemon.py
#  Author: Roger Gee <rpg11a@acu.edu>

# unpacker daemon program; this script should run as root; though it uses TCP
# sockets for networking, it is not recommended to bind the server to a
# non-local network interface; note that the process will not daemonize itself;
# instead you should use another utility to do this; I recommend one of my own
# making: https://gist.github.com/RogerGee/cb68c56ec16db7f0a8fe

# usage:
#  unpacker-daemon.py [-H|--host host] [-p|--port port]

import os
import re
import sys
import pwd
import time
import select
import socket
import argparse
import subprocess

# globals
KEYVALUE_REGEX = re.compile("^(.+?)=(.+)$")
BRANCH_CHECK_REGEX = re.compile("^(fatal).*$")
CONFIGFILE = "unpack.config"
ENTRYFILE = "unpack.entry"
SECRETFILE = "unpack.secret"
appConfig = {
    'latest-rev': {} # key'd by branch
}
entryConfig = {
    'entries': {} # key'd by branch
}

class GitRepo:
    def __init__(self,url,**kwargs):
        self.url = url

        if 'workcopy' in kwargs and os.path.isdir(kwargs['workcopy']):
            self.localCopy = kwargs['workcopy']
        else:
            # attempt to find viable prefixes for the work copy url (i.e.
            # basedir)
            pre = []
            for k in ['UNPACKER_BASEDIR']:
                if k in os.environ:
                    pre.append(os.environ[k])
            if len(pre) == 0:
                pre.append('/var/tmp')

            # produce the url of the local work copy
            self.localCopy = pre[0].strip() + '/git-unpack'
            if not os.path.exists(self.localCopy):
                os.makedirs(self.localCopy)

            # clone the repository
            m = self.git_command("clone {}".format(url),
                                 "failed to clone repository @{}".format(url),
                                 "Cloning into '(.+?)'")
            self.localCopy += '/' + m.group(1)

            # deny access to anyone except root
            os.chmod(self.localCopy,0750)

    def get_latest_rev(self,branch):
        return self.git_command("rev-parse {}".format(branch),"failed to fetch revision").strip()

    def sync_trees(self,tree,dst,user,client):
        record = pwd.getpwnam(user)

        # temporarily grant access to the unpack staging area by modifying the
        # group of the top-level repository directory
        os.chown(self.localCopy,-1,record.pw_gid)

        # we do the sync operation as the specified user; so we need to fork
        # ourself again and change our user/group mode
        pid = os.fork()
        if pid != 0:
            # synchronously wait for the child to do its work
            os.wait()
            os.chown(self.localCopy,-1,0) # change back to root
            return

        # set effective permissions; we almost reproduce a login shell here
        # because we have to load up the user's supplementary group ids
        os.setegid(record.pw_gid)
        os.initgroups(user,record.pw_gid)
        os.seteuid(record.pw_uid)

        # redirect the process's stdout (underlying os-level redirection) to the
        # socket
        os.dup2(client.fileno(),1)
        os.dup2(client.fileno(),2)
        os.close(client.fileno())

        # exec rsync over this process to copy updated content to the
        # destination; we assume that rsync is installed on the system
        change_dir(self.localCopy)
        if tree[len(tree)-1] != '/':
            tree += '/' # rsync requires this
        os.execlp('rsync','rsync','--exclude=.git/','-rvu','--chmod=ugo=rwX',tree,dst)

    def git_command(self,cmdline,errorMsg=None,regex=""):
        try:
            # change working directories and run 'git'; if it returns
            # non-zero the function will throw an exception
            change_dir(self.localCopy)
            o = subprocess.check_output(['git']+cmdline.split(),stderr=subprocess.STDOUT)
            change_dir()

            if regex == "":
                return o

            lines = o.split("\n")
            rx = re.compile(regex)
            for line in lines:
                m = rx.match(line)
                if not m is None:
                    return m
        except subprocess.CalledProcessError as e:
            # if the command failed, we either raise an exception with the
            # specified error message or we ignore the error and return any
            # command output
            if errorMsg is None:
                return e.output
            raise Exception(errorMsg)
        return None

def change_dir(dirto=None):
    global oldCurrentDir
    if not dirto is None:
        oldCurrentDir = os.getcwd()
        os.chdir(dirto)
    elif not oldCurrentDir is None:
        os.chdir(oldCurrentDir)
        oldCurrentDir = None

def message(client,msg):
    client.send("unpacker: {}\n".format(msg))

def fatal(client,msg):
    client.send("fatal: {}\n".format(msg))
    client.close()
    exit(1)

# update configuration values for the global local configuration
def update_app_config(key,value):
    global appConfig

    # each key can imply a hierarchical ordering of subkeys using dot notation
    ks = map(str.strip,key.split('.'))
    i = 0
    thing = appConfig
    while i < len(ks)-1:
        if not ks[i] in thing:
            thing[ks[i]] = {}
        thing = thing[ks[i]]
        i += 1
    if ks[i] in thing:
        fatal("local config property is incorrect: '"+ks[i]+"'")
    thing[ks[i]] = value

# update and validate a specific configuration value for the global
# entry configuration
def update_entry_config(key,value):
    global entryConfig

    # the key should be of the form entry.{branch}; we organize each entry by
    # what branch is specified
    ks = map(str.strip,key.split('.'))
    if len(ks) != 2:
        fatal("entry config key '{}' is incorrect".format(key))
    if ks[0] != 'entry':
        fatal("entry config key '{}' is not of form entry.[branch]".format(key))
    if not ks[1] in entryConfig['entries']:
        entryConfig['entries'][ks[1]] = []
    entryConfig['entries'][ks[1]].append(value.split(':'))

# generic load config routine
def load_config(unpackFile,fn,fatalFail):
    try:
        with open(unpackFile) as f:
            while True:
                line = f.readline()
                if len(line) > 0:
                    m = KEYVALUE_REGEX.match(line)
                    if not m is None:
                        fn(*map(str.strip,m.groups()))
                else:
                    break
    except IOError as e:
        if fatalFail:
            raise Exception("no config file '"+unpackFile+"' found in repository")

def write_config_pair(base,next,f):
    # recursively write the configuration pair; it may have nested keys
    if isinstance(next,dict):
        for k,v in next.iteritems():
            write_config_pair("{}.{}".format(base,k),v,f)
    else:
        f.write("{}={}\n".format(base,next))

def save_config(configFile,config):
    with open(configFile,'w') as f:
        for (k,v) in config.iteritems():
            write_config_pair(k,v,f)

def try_delete(url):
    try:
        # delete the fifo object just in case it already exists
        os.unlink(url)
    except:
        pass

def hang_up_fifo(url):
    try:
        fd = os.open(url,os.O_RDONLY | os.O_NONBLOCK)
        time.sleep(0.125) # give the client a little bit of air time
        os.close(fd)
    except:
        pass

# create socket wrapper to provide asynchronous readline() operation
class NetSocket:
    def __init__(self,sock):
        self.sock = sock
        self.extra = ""

    def send(self,buf):
        return self.sock.send(buf)

    def fileno(self):
        return self.sock.fileno()

    def readline(self):
        line = ""
        while True:
            rlist = select.select([self.sock],[],[],2.5)[0]
            if len(rlist) == 0:
                fatal(self.sock,"message was not sent within timeout")
            buf = self.extra
            buf += self.sock.recv(4096)
            i = buf.find("\n")
            self.extra = buf[i+1:]
            if i >= 0:
                line += buf[:i]
                break
        return line

    def readexact(self,numBytes):
        result = ""
        while True:
            rlist = select.select([self.sock],[],[],2.5)[0]
            if len(rlist) == 0:
                fatal(self.sock,"message was not sent within timeout")
            buf = self.extra
            if len(buf) < numBytes:
                buf += self.sock.recv(4096)
            i = -1 if len(buf) < numBytes else numBytes
            self.extra = buf[i+1:]
            if i >= 0:
                result += buf[:i]
                break
        return result

    def close(self):
        self.sock.close()

# we don't want this environment variable influencing the commands we run
if 'GIT_DIR' in os.environ:
    del os.environ['GIT_DIR']

# read command line arguments
parser = argparse.ArgumentParser(description="A daemon that deploys content from git repositories")
parser.add_argument('-H','--host',dest='host',default='localhost',nargs='?',help='specify bind interface')
parser.add_argument('-p','--port',dest='port',default=1024,nargs='?',help='specify bind port')
parser.add_argument('-v','--version',action='version',version='%(prog)s 1.1')
args = parser.parse_args()

# prepare a listener socket for main server operation
bindAddr = (str(args.host),int(args.port))
listenSocket = socket.socket(socket.AF_INET,socket.SOCK_STREAM)
listenSocket.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
listenSocket.bind(bindAddr)
listenSocket.listen(socket.SOMAXCONN)

# begin server operation
while True:
    try:
        client, addr = listenSocket.accept()
    except:
        # if something exceptional happens then quit (e.g. we received a signal)
        listenSocket.shutdown(socket.SHUT_RDWR)
        listenSocket.close() # I want to close this cleanly to free up the port
        exit(0)
    pid = os.fork()
    if pid == 0: # in child process
        listenSocket.close()
        break # let control fall through to the main operation

    # we synchronously execute the child process before accepting another client
    # connection; this is important so we don't interfere with another process
    # that might be currently unpacking the same repository
    client.close()
    os.wait()

# read input from client; this should consist of just a single line with the
# following format: [user]:[url]
client = NetSocket(client)
line = client.readline()

# parse input line
try:
    user,url = map(str.strip,line.split(':'))
except Exception as e:
    fatal(client,"could not understand input: {}".format(line))

# change to specified directory
try:
    change_dir(url)
except Exception as e:
    fatal(client,"cannot locate repository: {}".format(str(e)))

# we need to challenge the specified user (to make sure they really have access
# to this repository); we do this by sending 120 random bytes to the client and
# having them write it to a file they create; this way we know they can access
# and write to the bare repository directory and that they can at least create a
# file with the correct user credentials
fifoUrl = os.path.join(url,SECRETFILE)
try_delete(fifoUrl)
challenge = os.urandom(120)
client.send("{}\n".format(fifoUrl))
client.send(challenge)

# do main operation; the try block will catch any errors and write them to the
# client so they can be reported back to the user; note that the client doesn't
# expect any more identification/authentication messages; it can safely assume
# any subsequent message is either a log message or an error message
try:
    try:
        fd = -1

        # wait for the client to indicate they have created the file; they do
        # this by sending a complete message line (with arbitrary bytes)
        client.readline()

        # verify uid of fifo file and that it can't be written to by others or
        # groups
        record = pwd.getpwnam(user)
        stdata = os.stat(fifoUrl)
        if stdata.st_uid != record.pw_uid or (stdata.st_mode & 022) != 0:
            raise Exception("file mode was incorrect")
        time.sleep(0.125) # give the client some air time to write the data

        # read bytes from the file; it may be a fifo, so open in non-block mode
        # to prevent blocking on open (which is how fifo's behave); the remote
        # process should already have attempted to open the file
        fd = os.open(fifoUrl,os.O_RDONLY | os.O_NONBLOCK)
        rlist = select.select([fd],[],[],2.5)[0] # poll file for input
        if len(rlist) == 0:
            raise Exception("challenge was not answered within enough time")
        response = os.read(fd,120) # we should get all 120 bytes at once
        os.close(fd)
        os.unlink(fifoUrl)
    except Exception as e:
        # we are nice to the client and at least make a connection attempt
        # so the client can hang up if they are blocking on opening the fifo
        if fd == -1:
            hang_up_fifo(fifoUrl)
        fatal(client,"failed challenge: {}".format(str(e)))
    if response != challenge: # binary string comparison
        fatal(client,"failed challenge")

    # load the local configuration files
    load_config(CONFIGFILE,update_app_config,False)
    load_config(ENTRYFILE,update_entry_config,True)

    # load the repository
    if 'workcopy' in appConfig:
        # repo has already been cloned
        repo = GitRepo(os.getcwd(),workcopy=appConfig['workcopy'])
    else:
        # this clones a new repository (i.e. it fetches the repo)
        repo = GitRepo(os.getcwd())
    appConfig['workcopy'] = repo.localCopy # this could have changed

    # generate a list of remote branches
    availBranches = map(lambda x: x[1],
                        filter(lambda x: len(x)==2,
                               map(lambda x: x.split('/'),
                                   repo.git_command("branch -r").split("\n"))))

    # process the repository based on the entry configuration
    if len(entryConfig['entries']) == 0:
        raise Exception("no entries were specified in {} file".format(ENTRYFILE))
    for branch, entries in entryConfig['entries'].iteritems():
        # make sure user has permission to sync the branch
        if 'whitelist' in appConfig and branch in appConfig['whitelist']:
            if not user in map(str.split,appConfig['whitelist'][branch].split(',')):
                message(client,"user '{}' does not have permission to sync branch '{}'".format(user,branch))
                continue

        # make sure specified branch exists
        if not branch in availBranches:
            message(client,"skipping branch '{}' because it does not exist".format(branch))
            continue

        # checkout the specified branch and pull down any changes
        repo.git_command("checkout {}".format(branch),
                         "failed to checkout branch '{}'".format(branch))
        repo.git_command("pull origin {}".format(branch),
                         "failed to pull down changes on branch '{}'".format(branch))
        message(client,"checking out branch '{}'...".format(branch))

        # make sure a commit was actually applied to the branch before
        # attempting a sync
        rev = repo.get_latest_rev(branch)
        if branch in appConfig['latest-rev'] and appConfig['latest-rev'][branch] == rev:
            message(client,"skipping branch '{}' because latest revision is already checked out".format(branch))
            continue # skip processing
        appConfig['latest-rev'][branch] = rev
        message(client,"found new revision {}".format(rev))

        # sync trees for each of the specified entries; 'entries' should be a
        # list of tuples s,d where s is the source path and d is the dest path
        for (s,d) in entries:
            message(client,"syncing {} => {}".format(s,d))
            repo.sync_trees(s,d,user,client)
    change_dir(url)
    save_config(CONFIGFILE,appConfig)
    client.close()
except Exception as e:
    change_dir(url)
    save_config(CONFIGFILE,appConfig)
    fatal(client,str(e))
