#!/usr/bin/env python
# unpacker.py

# unpacker client program; this script connects to the unpacker daemon and gets
# it to unpack the current repository; this should be run as a git post-receive
# hook; simply create a symlink to the location of this script on disk
# usage:
#  unpacker.py [host] [port]

import os
import sys
import socket
import getpass
import argparse

# parse command-line arguments
parser = argparse.ArgumentParser(description="unpacker client program")
parser.add_argument('host',default='localhost',nargs='?',help="specify connect host address")
parser.add_argument('port',default=1024,nargs='?',help="specify connect host port")
args = parser.parse_args()

sock = socket.socket(socket.AF_INET,socket.SOCK_STREAM)

# connect to daemon and send information (user name and url of git repo)
sock.connect((str(args.host),int(args.port)))
sock.send("{}:{}\n".format(getpass.getuser(),os.getcwd()))

# now read all input from peer and write it to our process's stdout; this will
# be reported back to the user
f = sock.makefile()
while True:
    line = f.readline()
    if len(line) == 0:
        sock.close()
        exit(0)
    sys.stdout.write(line)
