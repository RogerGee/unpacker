# unpacker

`unpacker` is a tool written in Python that provides automatic deployment from
git repositories on Linux systems. It uses a client-server model to provide a
system service that syncs specified trees from within the repository to the
filesystem.

## How does it work?

`unpacker` comes with two programs: the client and the server (i.e. daemon).
Both the client and the server run on the same local host. The server should run
in the background as a daemon (you have to do this yourself; I recommend [this
tool](https://gist.github.com/RogerGee/cb68c56ec16db7f0a8fe) of mine, which
daemonizes a process before executing a specified command). The server must run
as root.

The client connects locally to the daemon when it wants to issue instructions to
the server. It sends a user name and the URL of the bare git repository to
unpack. The server then looks up that repository, checks it out and unpacks it
according to rules defined in the `unpack.entry` file, which is located within
the bare git repository directory. Another file called `unpack.config` is stored
locally within each bare git repository. It is used by the server to remember
the configuration of each repository's deployment.

When the server syncs an unpacked repository with the filesystem, it uses the
effective permissions of the user specified by the client. The client program
obtains this from the running process before sending it to the server. This way
file permissions can be handled on a per-user basis (that is, the user who
pushed the commit). Obviously this presents a security concern; see the section
on *file permissions and security* to learn how users are verified.

The server unpacks the repositories to `/var/tmp/git-unpack`. Then it calls the
`rsync` utility to sync the checked-out tree with the destination tree. This
process is very efficient because it only syncs the parts of trees that were
modified. The downside is that currently the software doesn't remove files that
were either deleted or renamed.

## How do you set it up?

First you need to install the scripts so that your shell can conveniently
execute them. This is optional but recommended. I recommend installing
`unpacker-daemon.py` to `/usr/local/sbin` and `unpacker-client.py` to
`/usr/local/bin`. Also make sure you have the `rsync` utility installed on your
system. (Fortunately `rsync` is common on linux systems.)

As root, launch the daemon. You should use my `launch` tool or something similar
to do this since the script doesn't daemonize itself:
```
$ launch unpacker-daemon.py
```
Optionally you can specify the network interface and port the server is to run
on. It is strongly recommended that you bind to `localhost` (which is the
default).

Now you can setup your repositories to use the daemon to unpack their contents
when a push is received. You do this by creating a `post-receive` hook. The hook
can either be a symlink to `unpacker.py` or a simple shell script like so:
```shell
#!/bin/bash

# write over the current process with the hook script
exec unpacker.py
```

Now when a push is updated to the remote it will run the unpack rules specified
in the `unpack.entry` file. This file has a simple, line-oriented format:
```
entry.{BRANCH}={SRC-TREE}:{DST-TREE}
```
As you can see, entries work on branches, meaning different rules can be applied
to different branches. `{SRC-TREE}` must be a path in the git repository and
`{DST-TREE}` must be a path in the file system. The utility will sync the source
and destination trees such that the children of the source tree become the
children of the destination tree. It is completely fine to merge multiple
repository trees into the same destination tree.

## What about access control?

`unpacker` provides limited access control in the form of whitelists. Each
branch can have its own whitelist that allows only a set of specified users to
apply rules defined for that branch. You configure a whitelist in the
`unpacker.config` file. You can create this file if it hasn't been created
already.

Here's the format:
```
whitelist.{BRANCH}={USER_1},{USER_2},...{USER_N}
```

## What about file permissions and security?

This software handles file permissions by having the the client program send the
user name that should be applied when syncing trees from the repo to the
filesystem. Obviously this presents some security concerns. Therefore the server
validates the client by issuing a challenge sequence. If the client is able to
successfully complete the challenge, then the server has proven their ability to
write to the remote git directory as the specified user.

The client program allows you to specify which user is sent to the server
explicitly on the command-line. This is only possible if the client is running
as root or with elevated effective privileges.

Note that this software was designed to work in a multiuser environment where
git repositories and destination trees have shared access by a set of users who
work collaboratively on a project that benefits from going live when pushed to a
remote (e.g. via a group and the sticky bit).
