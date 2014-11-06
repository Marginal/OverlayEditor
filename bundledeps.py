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


debug = 0
dryrun = False
filtered = None
addpath = []
excludes = []
outpath = None	# app folder
respath = None	# Python version specific subfolder of app MacOS folder - equivalent of /Library/Python/x.y
dylpath = None	# app MacOS folder - equivalent of /usr/local/lib


def printhelp():
    print """usage:\t%s [-d] [-n] [-f name] [-i path] [-x name] -o outpath script ...
where:
-d\t\t: debug
-n\t\t: dry run
-f name\t\t: process only this named package
-i path\t\t: add path to Python's sys.path
-x name\t\t: exclude package by name.
-o outpath\t: path to application bundle
script\t\t: script(s) to process
""" % basename(sys.argv[0])


def copylib(filename, leafname):
    global dryrun, debug, respath, dylpath
    newfile = join(leafname.endswith('.dylib') and dylpath or respath, leafname)
    if not dryrun and isfile(newfile): return	# already done
    if debug:
        print leafname, filename
    else:
        print leafname

    # fixup import name
    otool = subprocess.Popen(['otool', '-L', filename], stdout=subprocess.PIPE).communicate()[0].split("\n")
    otool.pop(0)	# first line is just filename
    change = []
    dependencies = []
    for line in otool:
        if '.dylib' in line and not line.startswith("\t/usr/lib"):
            depfile = line.split()[0]
            if debug: print '\t%s' % depfile
            newdepfile = realpath(depfile)	# use most specific name so we don't have to bother with duplicates / symlinks
            if basename(newdepfile) == leafname:
                change = ['-id', leafname] + change
            elif leafname.endswith('.dylib'):	# we're a dylib
                dependencies.append(newdepfile)
                change.extend(['-change', depfile, '@loader_path/' + basename(newdepfile)])	# other dylibs are with us
            else:
                dependencies.append(newdepfile)
                change.extend(['-change', depfile, '@loader_path/' + '../' * len(leafname.split(sep)) + basename(newdepfile)])
    if not dryrun:
        shutil.copy2(filename, newfile)
        subprocess.check_call(['strip', '-x', newfile])
        if change:
            change.insert(0, 'install_name_tool')
            change.append(newfile)
            subprocess.check_call(change)

    for depfile in dependencies:
        copylib(depfile, basename(depfile))


try:
    opts, args = getopt.getopt(sys.argv[1:], "hdnf:o:i:x:")
except getopt.GetoptError, e:
    print str(e)
    printhelp()
    exit(2)

for o, a in opts:
    if o == '-h':
        printhelp();
        exit(0);
    elif o == '-d':
        debug += 1
    elif o == '-n':
        dryrun = True
    elif o == '-f':
        filtered = a
    elif o == '-i':
        addpath = addpath + a.split(os.pathsep)
    elif o == '-o':
        outpath = a
    elif o == '-x':
        excludes.append(a)

if len(args)==0:
    printhelp()
    exit(2)
script = args[0]

if not outpath:
    print 'Missing outpath'
    printhelp()
    exit(2)
dylpath = join(outpath, 'Contents', 'MacOS')
if not dryrun and not isdir(dylpath): os.makedirs(dylpath)
respath = join(dylpath, '%d%d' % sys.version_info[:2])
if not dryrun and not isdir(respath): os.makedirs(respath)


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
    if debug: print k, modules[k]
    filename = modules[k].__file__
    leafname = modules[k].__path__ and join(k.replace('.',sep), '__init__.py') or filename[filename.rindex(k.replace('.',sep)):]
    newfile = join(respath, leafname)
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
        copylib(filename, leafname)
    else:
        raise	# wtf?
