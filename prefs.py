import codecs
from os import getenv, mkdir
from os.path import dirname, isdir, join, expanduser
from sys import platform

from version import appname, appversion


class Prefs:
    TERRAIN=1
    ELEVATION=2
    DRAW=TERRAIN|ELEVATION
    DMS=4
    
    def __init__(self):
        self.filename=None
        self.xplane=None
        self.package=None
        self.options=Prefs.TERRAIN
        self.packageprops={}

        if platform=='win32':
            from _winreg import OpenKey, QueryValueEx, HKEY_CURRENT_USER, REG_SZ, REG_EXPAND_SZ
            try:
                handle=OpenKey(HKEY_CURRENT_USER, 'Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\User Shell Folders\\')
                (v,t)=QueryValueEx(handle, 'AppData')
                handle.Close()
                if t==REG_EXPAND_SZ:
                    dirs=v.split('\\')
                    for i in range(len(dirs)):
                        if dirs[i][0]==dirs[i][-1]=='%':
                            dirs[i]=getenv(dirs[i][1:-1],dirs[i])
                        v='\\'.join(dirs)
                if t in [REG_SZ,REG_EXPAND_SZ] and isdir(v):
                    self.filename=join(v,'marginal.org',appname)
                    if not isdir(dirname(self.filename)):
                        mkdir(dirname(self.filename))
            except:
                pass
        if not self.filename:
            self.filename=join(expanduser('~'), '.%s' % appname.lower())
        self.read()

    def read(self):
        try:
            handle=codecs.open(self.filename, 'rU', 'utf-8')
            self.xplane=handle.readline().strip()
            handle.readline().strip()	# skip package
            #if self.package=='None': self.package=None
            for line in handle:
                if '=' in line:
                    pkg=line[:line.index('=')]
                    if pkg=='*options':
                        self.options=int(line[9:])
                    else:
                        line=line[len(pkg)+2:]
                        f=line[:line.index('"')]
                        c=line[len(f)+1:].split()
                        self.packageprops[pkg]=(f, float(c[0]), float(c[1]), int(c[2]), float(c[3]), float(c[4]), int(c[5]))
            handle.close()
        except:
            pass

    def write(self):
        try:
            handle=codecs.open(self.filename, 'wt', 'utf-8')
            handle.write('%s\n%s\n*options=%d\n' % (
                self.xplane, self.package, self.options))
            for pkg, (f,lat,lon,hdg,w,h,o) in self.packageprops.iteritems():
                if not pkg: continue	# unsaved Untitled
                handle.write('%s="%s" %10.6f %11.6f %3d %8.2f %8.2f %2d\n' % (
                    pkg, f,lat,lon,hdg,w,h,o))
            handle.close()
        except:
            pass
