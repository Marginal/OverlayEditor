import codecs
from os import getenv, mkdir
from os.path import dirname, isdir, join, expanduser
from sys import platform, getfilesystemencoding

from version import appname, appversion

if __debug__:
    from traceback import print_exc

class Prefs:
    TERRAIN=1
    ELEVATION=2
    DMS=4
    NETWORK=8
    REDRAW=TERRAIN|ELEVATION|NETWORK	# options that cause meshlist to be recalculated
    
    def __init__(self):
        self.filename=None
        self.xplane=None
        self.package=None
        self.options=Prefs.TERRAIN
        self.imageryprovider=None
        self.packageprops={}

        if platform=='win32':
            from _winreg import OpenKey, QueryValueEx, HKEY_CURRENT_USER, REG_SZ, REG_EXPAND_SZ
            try:
                handle=OpenKey(HKEY_CURRENT_USER, 'Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\User Shell Folders')
                (v,t)=QueryValueEx(handle, 'AppData')
                handle.Close()
                if t==REG_EXPAND_SZ:
                    dirs=v.rstrip('\0').decode('mbcs').strip().split('\\')
                    for i in range(len(dirs)):
                        if dirs[i][0]==dirs[i][-1]=='%':
                            dirs[i]=getenv(dirs[i][1:-1],dirs[i]).decode('mbcs')
                        v='\\'.join(dirs)
                if t in [REG_SZ,REG_EXPAND_SZ] and isdir(v):
                    self.filename=join(v,'marginal.org',appname)
                    if not isdir(dirname(self.filename)):
                        mkdir(dirname(self.filename))
            except:
                pass
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
                handle.write('%s="%s" %s\n' % (pkg, args[0], ' '.join(['%11.6f' % i for i in args[1:]])))
            handle.close()
        except:
            if __debug__: print_exc()
