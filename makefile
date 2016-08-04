# makefile to build frozen Python programs of the unpacker scripts

all: dist/unpacker dist/unpacker-daemon

dist/unpacker: unpacker.py
	cxfreeze --no-copy-deps $<
dist/unpacker-daemon: unpacker-daemon.py
	cxfreeze --no-copy-deps $<
