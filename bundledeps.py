#!/usr/bin/python

import errno
import getopt
import modulefinder
import os
from os.path import basename, dirname, isdir, isfile, join, realpath, sep
import py_compile
import shutil
import subprocess
import sys


def copylib(filename, outpath, leafname, dryrun):
    newfile = join(outpath, leafname)
    if not dryrun and isfile(newfile): return	# already done
    print leafname

    # fixup import name
    otool = subprocess.Popen(['otool', '-L', filename], stdout=subprocess.PIPE).communicate()[0].split("\n")
    otool.pop(0)	# first line is just filename
    change = []
    dependencies = []
    for line in otool:
        if '.dylib' in line and not line.startswith("\t/usr/lib"):
            depfile = line.split()[0]
            newdepfile = realpath(depfile)	# use most specific name so we don't have to bother with duplicates / symlinks
            if basename(newdepfile) == leafname:
                change = ['-id', leafname] + change
            else:
                dependencies.append(newdepfile)
                change.extend(['-change', depfile, '@loader_path/' + '../' * (len(leafname.split(sep))-1) + basename(newdepfile)])
    if not dryrun:
        shutil.copy2(filename, newfile)
        subprocess.check_call(['strip', '-x', newfile])
        if change:
            change.insert(0, 'install_name_tool')
            change.append(newfile)
            subprocess.check_call(change)

    for depfile in dependencies:
        copylib(depfile, outpath, basename(depfile), dryrun)


debug = 0
dryrun = False
optimize=0
filtered = None
addpath = []
excludes = []
outpath = None

opts, args = getopt.getopt(sys.argv[1:], "dnf:o:p:x:")

for o, a in opts:
    if o == '-d':
        debug += 1
    elif o == '-n':
        dryrun = True
    elif o == '-f':
        filtered = a
    elif o == '-o':
        outpath = a
    elif o == '-p':
        addpath = addpath + a.split(os.pathsep)
    elif o == '-x':
        excludes.append(a)

if not outpath: raise getopt.GetoptError('Missing outpath')
script = args[0]

path = sys.path[:]
path[0] = dirname(script)
path = addpath + path

mf = modulefinder.ModuleFinder(path, debug, excludes)
for arg in args[1:]: mf.load_file(arg)	# add any additional scripts

mf.run_script(script)

if filtered:
    modules = dict((k,v) for k,v in mf.modules.iteritems() if v.__file__ and k.startswith(filtered))
else:
    # only interested in site packages
    modules = dict((k,v) for k,v in mf.modules.iteritems() if v.__file__ and sep+'site-packages'+sep in v.__file__)

for k in sorted(modules.keys()):
    filename = modules[k].__file__
    leafname = modules[k].__path__ and join(k.replace('.',sep), '__init__.py') or filename[filename.index(k.replace('.',sep)):]
    newfile = join(outpath, leafname)
    try:
        if not dryrun: os.makedirs(dirname(newfile))
    except OSError, e:
        if e.errno == errno.EEXIST and isdir(dirname(newfile)): pass
        else: raise
    if newfile.endswith('.py'):
        if __debug__:	# non-optimized
            print leafname
            if not dryrun: shutil.copy2(filename, newfile)
        else:
            leafname += 'o'
            print leafname
            if not dryrun: py_compile.compile(filename, cfile=newfile+'o', dfile=leafname, doraise=True)
    elif newfile.endswith('.so'):
        copylib(filename, outpath, leafname, dryrun)
    else:
        raise	# wtf?

