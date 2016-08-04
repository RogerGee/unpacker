#!/usr/bin/env python
# unpacker.py

# unpacker client program; this script connects to the unpacker daemon and gets
# it to unpack the current repository; this should be run as a git post-receive
# hook; simply create a symlink to the location of this script on disk
# usage:
#  unpacker.py [host] [port]

import os
import sys
import pwd
import socket
import getpass
import argparse

# parse command-line arguments
parser = argparse.ArgumentParser(description="unpacker client program")
parser.add_argument('host',default='localhost',nargs='?',help="specify connect host address")
parser.add_argument('port',default=1024,nargs='?',help="specify connect host port")
parser.add_argument('-u','--user',dest="user",default=getpass.getuser(),nargs='?',
                    help="specify the user name to send to the server")
parser.add_argument('-v','--version',action='version',version='%(prog)s 1.0')
args = parser.parse_args()

sock = socket.socket(socket.AF_INET,socket.SOCK_STREAM)

# connect to daemon and send information (user name and url of git repo)
try:
    sock.connect((str(args.host),int(args.port)))
except socket.error as e:
    sys.stderr.write("unpacker: error: couldn't connect: {}\n".format(str(e)))
    exit(1)
sock.send("{}:{}\n".format(args.user,os.getcwd()))

# expect a challenge from the server that we have to fullfil
reader = sock.makefile()
url = reader.readline().strip()
try:
    # the server will send us 120 random bytes that we must write to the
    # specified file
    data = ""
    while len(data) < 120:
        d = reader.read(120 - len(data))
        if d == "":
            break
        data += d

    # as part of the challenge, we have to create the file (in this case we
    # create a fifo); the server will verify the credentials of this file to
    # make sure they match the user name we sent; the file must not be writable
    # by group or others
    record = pwd.getpwnam(args.user)
    os.mkfifo(url,0600)
    if os.geteuid() != record.pw_uid:
        # process should be privileged to do this
        os.chown(url,record.pw_uid,-1)

    # this tells the server we finished and to begin reading the fifo; we just
    # send something arbitrary (the url in this case)
    sock.send("{}\n".format(url))

    # opening fifos block until the server opens it (slightly unusual semantics)
    with open(url,'w') as f:
        f.write(data)
except Exception as e:
    print "internal error:", e

# now read all further input from peer and write it to our process's stdout;
# this will be reported back to the user
while True:
    line = reader.readline()
    if len(line) == 0:
        sock.close()
        exit(0)
    sys.stdout.write("unpacker: {}".format(line))
