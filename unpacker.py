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
parser.add_argument('-u','--user',dest="user",default=getpass.getuser(),nargs='?',
                    help="specify the user name to send to the server")
args = parser.parse_args()

sock = socket.socket(socket.AF_INET,socket.SOCK_STREAM)

# connect to daemon and send information (user name and url of git repo)
sock.connect((str(args.host),int(args.port)))
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
        data += d
    # as part of the challenge, we have to create the file (in this case we
    # create a fifo)
    os.mkfifo(url,0660)
    # this tells the server we finished and to begin reading the fifo; we just
    # send something arbitrary
    sock.send("{}\n".format(url))
    with open(url,'w') as f:
        f.write(data)
except Exception as e:
    print "failed challenge:", e

# now read all further input from peer and write it to our process's stdout;
# this will be reported back to the user
while True:
    line = reader.readline()
    if len(line) == 0:
        sock.close()
        exit(0)
    sys.stdout.write(line)
