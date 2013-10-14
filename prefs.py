import codecs
from os import getenv, makedirs
from os.path import dirname, isdir, join, expanduser
from sys import platform, getfilesystemencoding
from time import sleep

from version import appname, appversion

if __debug__:
    from traceback import print_exc

class Prefs:
    TERRAIN=1
    ELEVATION=2
    DMS=4
    NETWORK=8
    REDRAW=TERRAIN|ELEVATION|NETWORK	# options that cause meshlist to be recalculated
    IMPERIAL=16
    
    def __init__(self):
        self.filename=None
        self.xplane=None
        self.package=None
        self.options=Prefs.TERRAIN
        self.imageryprovider=None
        self.imageryopacity=50	# percent
        self.packageprops={}

        if platform=='win32':
            import ctypes.wintypes
            buf= ctypes.create_unicode_buffer(ctypes.wintypes.MAX_PATH)
            if not ctypes.windll.shell32.SHGetFolderPathW(0, 0x801a, 0, 0, buf):	# CSIDL_FLAG_CREATE|CSIDL_APPDATA
                self.filename=join(buf.value,'marginal.org',appname)
            else:
                # can fail on 64 bit - race condition?
                self.filename=join(getenv('APPDATA', '.'),'marginal.org',appname)
            if not isdir(dirname(self.filename)):
                makedirs(dirname(self.filename))
        if not self.filename:
            self.filename=join(expanduser('~').decode(getfilesystemencoding() or 'utf-8'), '.%s' % appname.lower())
        self.read()

    def read(self):
        try:
            handle=codecs.open(self.filename, 'rU', 'utf-8')
            self.xplane=handle.readline().strip()
            handle.readline().strip()	# skip package
            #if self.package=='None': self.package=None
            for line in handle:
                try:
                    (pkg,args)=line.split('=')
                    pkg=pkg.strip()
                    if pkg=='*options':
                        self.options=int(args)
                    elif pkg=='*imagery':
                        self.imageryprovider=args.strip()
                    elif pkg.startswith('*'):
                        pass	# option from the future!
                    else:
                        args=args.split()
                        f=args.pop(0).strip('"')
                        self.packageprops[pkg]=(f,)+tuple([float(i) for i in args])
                except:
                    pass
            handle.close()
        except:
            if __debug__: print_exc()

    def write(self):
        try:
            handle=codecs.open(self.filename, 'w', 'utf-8')
            handle.write('%s\n%s\n*options=%d\n' % (
                self.xplane, self.package, self.options))
            if self.imageryprovider:
                handle.write('*imagery=%s\n' % self.imageryprovider)
            for pkg, args in self.packageprops.iteritems():
                if not pkg: continue	# unsaved Untitled
                handle.write('%s="%s" %s\n' % (pkg, args[0], ' '.join(['%14.9f' % i for i in args[1:]])))
            handle.close()
        except:
            if __debug__: print_exc()
