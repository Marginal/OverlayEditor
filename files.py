from PIL.Image import open, NEAREST, BILINEAR, BICUBIC
import PIL.BmpImagePlugin, PIL.JpegImagePlugin, PIL.PngImagePlugin	# force for py2exe
from OpenGL.GL import *
try:
    from OpenGL.GL.ARB.texture_non_power_of_two import glInitTextureNonPowerOfTwoARB
except:	# not in 2.0.0.44
    def glInitTextureNonPowerOfTwoARB(): return False

import codecs
from glob import glob
from math import cos, log, pi, fabs
from os import getenv, listdir, mkdir
from os.path import abspath, basename, curdir, dirname, exists, expanduser, isdir, join, normpath, pardir, sep, splitext
from shutil import copyfile
import sys	# for version
from sys import platform, maxint
import wx
if __debug__:
    import time

from DSFLib import readDSF
from version import appname, appversion

# memory leak? causing SegFault on Linux - Ubuntu seems OK for some reason
cantreleasetexs=(platform.startswith('linux') and 'ubuntu' not in sys.version.lower())

onedeg=1852*60	# 1 degree of longitude at equator (60nm) [m]
d2r=pi/180.0
f2m=0.3041	# 1 foot [m] (not accurate, but what X-Plane appears to use)

GL_CLAMP_TO_EDGE=0x812F	# Not defined in PyOpenGL 2.x

# 2.3 version of case-insensitive sort
# 2.4-only version is faster: sort(cmp=lambda x,y: cmp(x.lower(), y.lower()))
def sortfolded(seq):
    seq.sort(lambda x,y: cmp(x.lower(), y.lower()))


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
            self.package=handle.readline().strip()
            if self.package=='None': self.package=None
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
                handle.write('%s="%s" %10.6f %11.6f %3d %8.2f %8.2f %2d\n' % (
                    pkg, f,lat,lon,hdg,w,h,o))
            handle.close()
        except:
            pass


def readApt(filename):
    airports={}	# (name, [lat,lon], [(lat,lon,hdg,length,width,stop,stop)]) by code
    nav=[]	# (type,lat,lon,hdg)
    firstcode=None
    h=codecs.open(filename, 'rU', 'latin1')
    if not h.readline().strip() in ['A','I']:
        raise IOError
    while True:	# NYEXPRO has a blank line here
        c=h.readline().split()
        if c: break
    ver=c[0]
    if not ver in ['600','703','715','810','850']:
        raise IOError
    ver=int(ver)
    code=name=loc=None
    run=[]
    pavement=[]
    for line in h:
        c=line.split()
        if not c or c[0][0]=='#': continue
        id=int(c[0])
        if pavement and id not in range(111,120):
            run.append(pavement[:-1])
            pavement=[]
        if loc and id in [1,16,17,99]:
            if not run: raise IOError
            run.reverse()	# drawn in reverse order
            airports[code]=(name,loc,run)
            code=name=loc=None
            run=[]
        if id in [1,16,17]:		# Airport/Seaport/Heliport
            code=c[4]
            if not firstcode: firstcode=code
            name=' '.join(c[5:])
        elif id==14:	# Prefer tower location
            loc=[float(c[1]),float(c[2])]
        elif id==10:	# Runway / taxiway
            # (lat,lon,h,length,width,stop1,stop2)
            lat=float(c[1])
            lon=float(c[2])
            if not loc: loc=[lat,lon]
            stop=c[7].split('.')
            if len(stop)<2: stop.append(0)
            if len(c)<11: surface=int(c[9])/1000000	# v6
            else: surface=int(c[10])
            run.append((lat, lon, float(c[4]), f2m*float(c[5]),f2m*float(c[8]),
                        f2m*float(stop[0]),f2m*float(stop[1]),surface))
        elif id==102: # 850 Helipad
            # (lat,lon,h,length,width,stop1,stop2)
            lat=float(c[2])
            lon=float(c[3])
            if not loc: loc=[lat,lon]
            run.append((lat, lon, float(c[4]), float(c[5]),float(c[6]),
                        0,0, float(c[7])))
        elif id==100: # and int(c[2]) not in [13,15]: # 850 Runway
            # ((lat1,lon1),(lat2,lon2),width,stop1,stop2)
            if not loc:
                loc=[(float(c[9])+float(c[18]))/2,
                     (float(c[10])+float(c[19]))/2]
            run.append(((float(c[9]), float(c[10])),
                        (float(c[18]), float(c[19])),
                        float(c[1]), float(c[12]),float(c[21]), float(c[2])))
        elif id==110:
            pavement=[int(c[1]),[]]	# surface
        elif id==111 and pavement:
            pavement[-1].append((float(c[1]),float(c[2])))
        elif id==112 and pavement:
            pavement[-1].append((float(c[1]),float(c[2]),float(c[3]),float(c[4])))
        elif id==113 and pavement:
            pavement[-1].append((float(c[1]),float(c[2])))
            pavement.append([])
        elif id==114 and pavement:
            pavement[-1].append((float(c[1]),float(c[2]),float(c[3]),float(c[4])))
            pavement.append([])
        elif id==18 and int(c[3]):	# Beacon - goes in nav
            if ver<850:
                nav.append((id, float(c[1]),float(c[2]), 0))
            else:
                nav.append((id*10+int(c[3]), float(c[1]),float(c[2]), 0))
        elif id==19:	# Windsock - goes in nav
            nav.append((id, float(c[1]),float(c[2]), 0))
        elif id==21:	# VASI/PAPI - goes in nav
            nav.append((id*10+int(c[3]), float(c[1]),float(c[2]), float(c[4])))
    if loc:	# No terminating 99
        if not run: raise IOError
        run.reverse()	# drawn in reverse order
        airports[code]=(name,loc,run)
    h.close()
    return (airports, nav, firstcode)


def readNav(filename):
    nav=[]	# (type,lat,lon,hdg)
    if platform=='win32':
        h=file(filename,'rU')
    else:
        h=codecs.open(filename, 'rU', 'latin1')
    if not h.readline().strip() in ['A','I']:
        raise IOError
    if not h.readline().split()[0] in ['740','810']:
        raise IOError
    for line in h:
        c=line.split()
        if not c: continue
        id=int(c[0])
        if id>=2 and id<=5:
            nav.append((id, float(c[1]), float(c[2]), float(c[6])))
        elif id>=6 and id<=9:	# heading ignored
            nav.append((id, float(c[1]), float(c[2]), 0))
    h.close()
    return nav


def readLib(filename, objects, terrain):
    h=None
    path=dirname(filename)
    if basename(dirname(filename))=='800 objects':
        filename=join('Resources','800library.txt')
        builtinhack=True
    else:
        builtinhack=False
    try:
        h=file(filename, 'rU')
        if not h.readline().strip()[0] in ['I','A']:
            raise IOError
        if not h.readline().split()[0]=='800':
            raise IOError
        if not h.readline().split()[0]=='LIBRARY':
            raise IOError
        for line in h:
            c=line.split()
            if not c: continue
            if c[0] in ['EXPORT', 'EXPORT_RATIO', 'EXPORT_EXTEND']:
                if c[0]=='EXPORT_RATIO': c.pop(1)
                if len(c)<3 or c[1][-4:].lower() not in ['.obj', '.fac', '.for', '.pol', '.ter']: continue
                c.pop(0)
                name=c[0]
                name=name.replace(':','/')
                name=name.replace('\\','/')
                if builtinhack:
                    lib='misc v800'
                else:
                    lib=name
                    if lib.startswith('/'): lib=lib[1:]
                    if lib.startswith('lib/'): lib=lib[4:]
                    if not '/' in lib:
                        lib="uncategorised"
                    else:
                        lib=lib[:lib.index('/')]
                c.pop(0)
                obj=' '.join(c)	# allow single spaces
                obj=obj.replace(':','/')
                obj=obj.replace('\\','/')
                if obj=='blank.obj':
                    continue	# no point adding placeholders
                obj=join(path, normpath(obj))
                if not exists(obj):
                    continue	# no point adding missing objects
                if name[-4:]=='.ter':
                    if name in terrain: continue
                    terrain[name]=obj
                else:
                    if lib in objects:
                        if name in objects[lib]: continue
                    else:
                        objects[lib]={}
                    objects[lib][name]=obj
    except:
        if h: h.close()
            

class TexCache:
    
    def __init__(self):
        self.blank=0	#self.get(join('Resources','blank.png'))
        self.texs={}
        # Must be after init
        self.npot=glInitTextureNonPowerOfTwoARB()
        if glGetString(GL_VERSION) >= '1.2':
            self.clampmode=GL_CLAMP_TO_EDGE
        else:
            self.clampmode=GL_REPEAT

    def flush(self):
        if cantreleasetexs:
            # Hack round suspected memory leak causing SegFault on SUSE
            pass
        else:
            if self.texs:
                glDeleteTextures(self.texs.values())
            self.texs={}

    def get(self, path, isbaseterrain=False, fixsize=False):
        if not path: return 0
        if path in self.texs:
            return self.texs[path]
        try:
            image = open(path)
            #image=wx.Image(path)
            if fixsize and not self.npot:
                size=[image.size[0],image.size[1]]
                #size=[image.Width,image.Height]
                for i in [0,1]:
                    l=log(size[i],2)
                    if l!=int(l): size[i]=2**(1+int(l))
                    if size[i]>glGetIntegerv(GL_MAX_TEXTURE_SIZE):
                        size[i]=glGetIntegerv(GL_MAX_TEXTURE_SIZE)
                if size!=[image.size[0],image.size[1]]:
                    image=image.resize((size[0], size[1]), BICUBIC)
                    #image.Rescale(size[0],size[1],wx.IMAGE_QUALITY_HIGH)

            if isbaseterrain:
                if image.mode!='RGB': image=image.convert('RGB')
                image=image.resize((image.size[0]/4,image.size[1]/4), NEAREST)
                data = image.tostring("raw", 'RGB', 0, -1)
                format=GL_RGB
            elif image.mode=='RGBA':
                data = image.tostring("raw", 'RGBA', 0, -1)
                format=GL_RGBA
            elif image.mode=='RGB':
                data = image.tostring("raw", 'RGB', 0, -1)
                format=GL_RGB
            elif image.mode=='LA':
                image=image.convert('RGBA')
                data = image.tostring("raw", 'RGBA', 0, -1)
                format=GL_RGBA
            else:	# dunno - hope it converts
                image=image.convert('RGB')
                data = image.tostring("raw", 'RGB', 0, -1)
                format=GL_RGB

            id=glGenTextures(1)
            glBindTexture(GL_TEXTURE_2D, id)
            if fixsize:
                glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_S,self.clampmode)
                glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_T,self.clampmode)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
            glTexImage2D(GL_TEXTURE_2D, 0, format, image.size[0], image.size[1], 0, format, GL_UNSIGNED_BYTE, data)
            self.texs[path]=id
            return id
        except IOError, args:
            self.texs[path]=0
            if __debug__:
                if isinstance(args, tuple) and args[1]==2:
                    print 'Failed to find texture "%s"' % basename(path)
                else:
                    print 'Failed to load texture "%s" - %s' % (basename(path), args)
        except:
            self.texs[path]=0
            if __debug__: print 'Failed to load texture "%s"' % basename(path)
        return self.blank


class FacadeDef:

    def __init__(self, path, texcache):
        # Only reads first wall in first LOD
        self.texture=0
        self.ring=0
        self.two_sided=False
        self.roof=[]
        # per-wall
        self.roof_slope=0
        self.hscale=100
        self.vscale=100
        self.horiz=[]
        self.vert=[]
        self.hends=[0,0]
        self.vends=[0,0]
    
        co=sep+'custom objects'+sep
        if co in path.lower():
            texpath=path[:path.lower().index(co)]
            for f in listdir(texpath):
                if f.lower()=='custom object textures':
                    texpath=join(texpath,f)
                    break
        else:
            texpath=dirname(path)
        h=file(path, 'rU')
        if not h.readline().strip()[0] in ['I','A']:
            raise IOError
        if not h.readline().split('#')[0].strip() in ['800']:
            raise IOError
        if not h.readline().strip() in ['FACADE']:
            raise IOError
        while True:
            line=h.readline()
            if not line: break
            c=line.split('#')[0].split()
            if not c: continue
            if c[0]=='TEXTURE' and len(c)>1:
                tex=abspath(join(texpath, line[7:].strip().replace(':', sep).replace('/', sep)))
                self.texture=texcache.get(tex)
            elif c[0]=='RING':
                if int(c[1]): self.ring=1
            elif c[0]=='TWO_SIDED': self.two_sided=(int(c[1])!=0)
            elif c[0]=='LOD':
                # LOD
                roof=[]
                while True:
                    line=h.readline()
                    if not line: break
                    c=line.split('#')[0].split()
                    if not c: continue
                    if c[0]=='LOD': break	# stop after first LOD
                    elif c[0]=='ROOF':
                        roof.append((float(c[1]), float(c[2])))
                    elif c[0]=='WALL':
                        # WALL
                        if len(roof) in [0,4]:
                            self.roof=roof
                        else:
                            self.roof=[roof[0], roof[0], roof[0], roof[0]]
                        while True:
                            line=h.readline()
                            if not line: break
                            c=line.split('#')[0].split()
                            if not c: continue
                            if c[0] in ['LOD', 'WALL']: break
                            elif c[0]=='SCALE':
                                self.hscale=float(c[1])
                                self.vscale=float(c[2])
                            elif c[0]=='ROOF_SLOPE':
                                self.roof_slope=float(c[1])
                            elif c[0] in ['LEFT', 'CENTER', 'RIGHT']:
                                self.horiz.append((float(c[1]),float(c[2])))
                                if c[0]=='LEFT': self.hends[0]+=1
                                elif c[0]=='RIGHT': self.hends[1]+=1
                            elif c[0] in ['BOTTOM', 'MIDDLE', 'TOP']:
                                self.vert.append((float(c[1]),float(c[2])))
                                if c[0]=='BOTTOM': self.vends[0]+=1
                                elif c[0]=='TOP': self.vends[1]+=1
                            elif c[0] in ['HARD_ROOF', 'HARD_WALL']:
                                pass
                            else:
                                raise IOError
                        break # stop after first WALL
                    else:
                        raise IOError
                break	# stop after first LOD
        h.close()
        if not self.horiz or not self.vert:
            raise IOError


class ExcludeDef:
    pass

class ForestDef:
    def __init__(self, path, texcache):
        pass

class DrapedDef:

    def __init__(self, path, texcache):
        self.texture=0
        self.ortho=False
        self.hscale=100
        self.vscale=100
        self.layer=None
    
        co=sep+'custom objects'+sep
        if co in path.lower():
            texpath=path[:path.lower().index(co)]
            for f in listdir(texpath):
                if f.lower()=='custom object textures':
                    texpath=join(texpath,f)
                    break
        else:
            texpath=dirname(path)
        h=file(path, 'rU')
        if not h.readline().strip()[0] in ['I','A']:
            raise IOError
        if not h.readline().split('#')[0].strip() in ['850']:
            raise IOError
        if not h.readline().strip() in ['DRAPED_POLYGON']:
            raise IOError
        while True:
            line=h.readline()
            if not line: break
            c=line.split('#')[0].split()
            if not c: continue
            if c[0] in ['TEXTURE', 'TEXTURE_NOWRAP'] and len(c)>1:
                if c[0]=='TEXTURE_NOWRAP':
                    self.ortho=True
                tex=abspath(join(texpath, line[len(c[0]):].strip().replace(':', sep).replace('/', sep)))
                self.texture=texcache.get(tex)
            elif c[0]=='SCALE':
                self.hscale=float(c[1])
                self.vscale=float(c[2])
        h.close()


class VertexCache:

    def __init__(self):
        # indices = (base, #culled, #nocull, texno, maxpoly)
        self.obj={}		# name -> physical obj/fac/etc
        self.geo={}		# physical obj -> geo
        self.idx={}		# physical obj -> indices
        self.objcache={}	# name -> indices
        self.poly={}		# physical fac -> facade

        # indices = (base, #culled, texno)
        self.ter={}		# name -> physical ter
        self.mesh={}		# tile -> [patches] where patch=(texture,f,v,t)
        self.meshdata={}	# tile->[(bbox, [(points, plane coeffs)])]
        self.meshcache=[]	# [indices] of current tile
        self.lasttri=None	# take advantage of locality of reference

        self.texcache=TexCache()
        self.varray=[]
        self.tarray=[]
        self.valid=False
        self.dsfdirs=None	# [custom, default]

    def flush(self):
        # invalidate array indices
        self.idx={}
        self.objcache={}
        self.meshcache=[]
        self.varray=[]
        self.tarray=[]
        self.valid=False
        self.lasttri=None

    def flushObjs(self, objects, terrain, dsfdirs):
        # invalidate object geometry and textures
        self.obj=objects
        self.ter=terrain
        self.dsfdirs=dsfdirs
        self.geo={}
        self.idx={}
        self.poly={}
        self.flush()
        self.texcache.flush()
    
    def realize(self, context):
        # need to call this before drawing
        if not self.valid:
            if self.varray:
                glVertexPointerf(self.varray)
                glTexCoordPointerf(self.tarray)
            else:	# need something or get conversion error
                glVertexPointerf([[0,0,0],[0,0,0],[0,0,0]])
                glTexCoordPointerf([[0,0],[0,0]])
            self.valid=True

    def get(self, name):
        # object better be in cache or we go bang
        if name in self.objcache:
            return self.objcache[name]
        elif name.startswith('Exclude:'):
            return ExcludeDef()
        else:
            return self.poly[self.obj[name]]

    def add(self, name, path):
        # Import a new object
        self.obj[name]=path
        
    def load(self, name, usefallback=False):
        # read object or facade into cache, but don't update OpenGL arrays
        # returns False if error reading object or facade
        retval=True
        
        if name in self.objcache:
            # Already loaded (or fallbacked)
            return True
        
        if not name in self.obj:
            # Physical object is missing
            if name.startswith('Exclude:') or name[-4:].lower() not in ['.obj', '.fac', '.for', '.pol']:
                return True	# Don't need a physical object
            if name[0]=='*':	# this application's resource
                self.obj[name]=join('Resources', name[1:])
            else:
                if __debug__: print 'Failed to find object "%s"' % name
                if usefallback:
                    self.obj[name]=join('Resources','default'+name[-4:].lower())
                    retval=False	# Load default obj
                else:
                    return False
        
        path=self.obj[name]
        if path in self.idx:
            # Object is already in the array under another name
            self.objcache[name]=self.idx[path]
            return retval
        if path in self.poly:
            # Facade already loaded
            return retval

        if path in self.geo:
            # Object geometry is loaded, but not in the array
            (culled, nocull, tculled, tnocull, texture, maxpoly, maxsize)=self.geo[path]
            base=len(self.varray)
            self.varray.extend(culled)
            self.varray.extend(nocull)
            self.tarray.extend(tculled)
            self.tarray.extend(tnocull)
            texno=self.texcache.get(texture)
            self.objcache[name]=self.idx[path]=(base, len(culled), len(nocull), texno, maxpoly, maxsize)
            self.valid=False	# new geometry -> need to update OpenGL
            return retval
            
        # Physical poly has not yet been read
        if path[-4:].lower()=='.fac':
            try:
                self.poly[path]=FacadeDef(path, self.texcache)
                return retval
            except:
                if __debug__: print 'Failed to load facade "%s"' % path
                if usefallback:
                    self.poly[path]=FacadeDef(join('Resources','default.fac'),
                                              self.texcache)
                return False
        elif path[-4:].lower()=='.for':
            self.poly[path]=ForestDef(path, self.texcache)
            return retval
        elif path[-4:].lower()=='.pol':
            self.poly[path]=DrapedDef(path, self.texcache)
            return retval

        # Physical object has not yet been read
        try:
            h=None
            culled=[]
            nocull=[]
            current=culled
            tculled=[]
            tnocull=[]
            tcurrent=tculled
            texture=None
            maxsize=0.1	# mustn't be 0
            maxpoly=0
            co=sep+'custom objects'+sep
            if co in path.lower():
                texpath=path[:path.lower().index(co)]
                for f in listdir(texpath):
                    if f.lower()=='custom object textures':
                        texpath=join(texpath,f)
                        break
            else:
                texpath=dirname(path)
            h=file(path, 'rU')
            if not h.readline().strip()[0] in ['I','A']:
                raise IOError
            version=h.readline().split()[0]
            if not version in ['2', '700','800']:
                raise IOError
            if version!='2' and not h.readline().split()[0]=='OBJ':
                raise IOError
            if version in ['2','700']:
                while True:
                    line=h.readline()
                    if not line: raise IOError
                    tex=line.strip()
                    if tex:
                        if '//' in tex: tex=tex[:tex.index('//')].strip()
                        tex=abspath(join(texpath, tex.replace(':', sep).replace('/', sep)))
                        break
                for ext in ['', '.png', '.PNG', '.bmp', '.BMP']:
                    if exists(tex+ext):
                        texture=tex+ext
                        break
                else:
                    texture=tex
                    
            if version=='2':
                while True:
                    line=h.readline()
                    if not line: break
                    c=line.split('//')[0].split()
                    if not c: continue
                    if c[0]=='99':
                        break
                    if c[0]=='1':
                        h.readline()
                    elif c[0]=='2':
                        h.readline()
                        h.readline()
                    elif c[0] in ['6','7']:	# smoke
                        for i in range(4): h.readline()
                    elif c[0]=='3':
                        uv=[float(c[1]), float(c[2]), float(c[3]), float(c[4])]
                        v=[]
                        for i in range(3):
                            c=h.readline().split()
                            v.append([float(c[0]), float(c[1]), float(c[2])])
                            maxsize=max(maxsize, fabs(v[i][0]), 0.55*v[i][1], fabs(v[i][2]))	# ad-hoc
                        current.append(v[0])
                        tcurrent.append([uv[0],uv[3]])
                        current.append(v[1])
                        tcurrent.append([uv[1],uv[2]])
                        current.append(v[2])
                        tcurrent.append([uv[1],uv[3]])
                    elif int(c[0]) < 0:	# strip
                        count=-int(c[0])
                        seq=[]
                        for i in range(0,count*2-2,2):
                            seq.extend([i,i+1,i+2,i+3,i+2,i+1])
                        v=[]
                        t=[]
                        for i in range(count):
                            c=h.readline().split()
                            v.append([float(c[0]), float(c[1]), float(c[2])])
                            maxsize=max(maxsize, fabs(v[i][0]), 0.55*v[i][1], fabs(v[i][2]))	# ad-hoc
                            v.append([float(c[3]), float(c[4]), float(c[5])])
                            maxsize=max(maxsize, fabs(v[i][0]), 0.55*v[i][1], fabs(v[i][2]))	# ad-hoc
                            t.append([float(c[6]), float(c[8])])
                            t.append([float(c[7]), float(c[9])])
                        for i in seq:
                            current.append(v[i])
                            tcurrent.append(t[i])
                    else:	# quads: type 4, 5, 6, 7, 8
                        uv=[float(c[1]), float(c[2]), float(c[3]), float(c[4])]
                        v=[]
                        for i in range(4):
                            c=h.readline().split()
                            v.append([float(c[0]), float(c[1]), float(c[2])])
                            maxsize=max(maxsize, fabs(v[i][0]), 0.55*v[i][1], fabs(v[i][2]))	# ad-hoc
                        current.append(v[0])
                        tcurrent.append([uv[1],uv[3]])
                        current.append(v[1])
                        tcurrent.append([uv[1],uv[2]])
                        current.append(v[2])
                        tcurrent.append([uv[0],uv[2]])
                        current.append(v[0])
                        tcurrent.append([uv[1],uv[3]])
                        current.append(v[2])
                        tcurrent.append([uv[0],uv[2]])
                        current.append(v[3])
                        tcurrent.append([uv[0],uv[3]])
            elif version=='700':
                while True:
                    line=h.readline()
                    if not line: break
                    c=line.split('//')[0].split()
                    if not c: continue
                    if c[0]=='end':
                        break
                    elif c[0]=='ATTR_LOD':
                        if float(c[1])!=0: break
                    elif c[0]=='ATTR_poly_os':
                        maxpoly=max(maxpoly,int(float(c[1])))
                    elif c[0]=='ATTR_cull':
                        current=culled
                        tcurrent=tculled
                    elif c[0]=='ATTR_no_cull':
                        current=nocull
                        tcurrent=tnocull
                    elif c[0] in ['tri', 'quad', 'quad_hard', 'polygon', 
                                  'quad_strip', 'tri_strip', 'tri_fan',
                                  'quad_movie']:
                        count=0
                        seq=[]
                        if c[0]=='tri':
                            count=3
                            seq=[0,1,2]
                        elif c[0]=='polygon':
                            count=int(c[1])
                            for i in range(1,count-1):
                                seq.extend([0,i,i+1])
                        elif c[0]=='quad_strip':
                            count=int(c[1])
                            for i in range(0,count-2,2):
                                seq.extend([i,i+1,i+2,i+3,i+2,i+1])
                        elif c[0]=='tri_strip':
                            count=int(c[1])
                            for i in range(0,count-2):
                                if i&1:
                                    seq.extend([i+2,i+1,i])
                                else:
                                    seq.extend([i,i+1,i+2])
                        elif c[0]=='tri_fan':
                            count=int(c[1])
                            for i in range(1,count-1):
                                seq.extend([0,i,i+1])
                        else:	# quad
                            count=4
                            seq=[0,1,2,0,2,3]
                        v=[]
                        t=[]
                        i=0
                        while i<count:
                            c=h.readline().split()
                            v.append([float(c[0]), float(c[1]), float(c[2])])
                            maxsize=max(maxsize, fabs(v[i][0]), 0.55*v[i][1], fabs(v[i][2]))	# ad-hoc
                            t.append([float(c[3]), float(c[4])])
                            if len(c)>5:	# Two per line
                                v.append([float(c[5]), float(c[6]), float(c[7])])
                                t.append([float(c[8]), float(c[9])])
                                i+=2
                            else:
                                i+=1
                        for i in seq:
                            current.append(v[i])
                            tcurrent.append(t[i])
            elif version=='800':
                vt=[]
                vtt=[]
                idx=[]
                anim=[]
                while True:
                    line=h.readline()
                    if not line: break
                    c=line.split('#')[0].split('//')[0].split()
                    if not c: continue
                    if c[0]=='TEXTURE':
                        if len(c)>1:
                            tex=line[7:].strip()
                            if '//' in tex: tex=tex[:tex.index('//')].strip()
                            texture=abspath(join(texpath, tex.replace(':', sep).replace('/', sep)))
                    #elif c[0]=='POINT_COUNTS':
                    #    vt=empty((int(c[1]),3),'f')
                    #    vtt=empty((int(c[1]),2),'f')
                    #    vti=0
                    #    idx=empty((int(c[4])),'i')
                    #    ii=0
                    elif c[0]=='VT':
                        x=float(c[1])
                        y=float(c[2])
                        z=float(c[3])
                        vt.append([x,y,z])
                        vtt.append([float(c[7]), float(c[8])])
                        #vt[vti]=array([x,y,z],'f')
                        #vtt[vti]=array([float(c[7]), float(c[8])],'f')
                        #vti+=1
                        maxsize=max(maxsize, fabs(x), 0.55*y, fabs(z))	# ad-hoc
                    elif c[0]=='IDX':
                        idx.append(int(c[1]))
                        #idx[ii]=int(c[1])
                        #ii+=1
                    elif c[0]=='IDX10':
                        idx.extend([int(c[i]) for i in range(1,11)])
                        #idx[ii:ii+10]=[int(c[i]) for i in range(1,11)]
                        #ii+=10
                    elif c[0]=='ATTR_LOD':
                        if float(c[1])!=0: break
                    elif c[0]=='ATTR_poly_os':
                        maxpoly=max(maxpoly,int(float(c[1])))
                    elif c[0]=='ATTR_cull':
                        current=culled
                        tcurrent=tculled
                    elif c[0]=='ATTR_no_cull':
                        current=nocull
                        tcurrent=tnocull
                    elif c[0]=='ANIM_begin':
                        if anim:
                            anim.append(list(anim[-1]))
                        else:
                            anim=[[0,0,0]]
                    elif c[0]=='ANIM_end':
                        anim.pop()
                    elif c[0]=='ANIM_trans':
                        anim[-1]=[anim[-1][i]+float(c[i+1]) for i in range(3)]
                    elif c[0]=='TRIS':
                        start=int(c[1])
                        new=int(c[2])
                        if anim:
                            current.extend([[vt[idx[i]][j]+anim[-1][j] for j in range (3)] for i in range(start, start+new)])
                        else:
                            current.extend([vt[idx[i]] for i in range(start, start+new)])
                        tcurrent.extend([vtt[idx[i]] for i in range(start, start+new)])
                        #i=take(idx, arange(start, start+new, 1, 'i'))
                        #if anim:
                        #    current.extend(take(vt, i)+anim[-1])
                        #else:
                        #    current.extend(take(vt, i))
                        #tcurrent.extend(take(vtt, i))
            h.close()
            if not (len(culled)+len(nocull)):
                if usefallback!=0:
                    # show empty objects as placeholders otherwise can't edit
                    self.load('*default.obj')
                    self.objcache[name]=self.idx[path]=self.get('*default.obj')
                else:
                    return False
            else:
                self.geo[path]=(culled, nocull, tculled, tnocull, texture, maxpoly, maxsize)
                base=len(self.varray)
                self.varray.extend(culled)
                self.varray.extend(nocull)
                self.tarray.extend(tculled)
                self.tarray.extend(tnocull)
                texno=self.texcache.get(texture)
                self.objcache[name]=self.idx[path]=(base, len(culled), len(nocull), texno, maxpoly, maxsize)
                self.valid=False	# new geometry -> need to update OpenGL
        except:
            if __debug__: print 'Failed to load object "%s"' % path
            if usefallback:
                self.load('*default.obj')
                self.objcache[name]=self.idx[path]=self.get('*default.obj')
            return False
        return retval


    # load mesh from DSF
    def loadMesh(self, tile, options):
        key=(tile[0],tile[1],options&Prefs.TERRAIN)
        if key in self.mesh: return	# don't reload
        dsfs=[]
        if options&Prefs.TERRAIN:
            for path in self.dsfdirs:
                dsfs+=glob(join(path, '*', '[eE][aA][rR][tT][hH] [nN][aA][vV] [dD][aA][tT][aA]', "%+02d0%+03d0" % (int(tile[0]/10), int(tile[1]/10)), "%+03d%+04d.[dD][sS][fF]" % (tile[0], tile[1])))
            #print join(path, '*', '[eE][aA][rR][tT][hH] [nN][aA][vV] [dD][aA][tT][aA]', "%+02d0%+03d0" % (int(tile[0]/10), int(tile[1]/10)), "%+03d%+04d.[dD][sS][fF]" % (tile[0], tile[1]))
            #print dsfs
            dsfs.sort()	# asciibetical, custom first
        if __debug__: clock=time.clock()	# Processor time
        for dsf in dsfs:
            try:
                (properties, placements, polygons, mesh)=readDSF(dsf, self.ter)
                if mesh:
                    self.mesh[key]=mesh
                    break
            except:
                pass
        if __debug__: print "%s CPU time in loadMesh" % (time.clock()-clock)
        if not key in self.mesh:
            if glob(join(self.dsfdirs[1], '*', '[eE][aA][rR][tT][hH] [nN][aA][vV] [dD][aA][tT][aA]', "%+02d0%+03d0" % (int(tile[0]/10), int(tile[1]/10)), "%+03d%+04d.[dD][sS][fF]" % (tile[0], tile[1]))) + glob(join(self.dsfdirs[1], pardir, '[eE][aA][rR][tT][hH] [nN][aA][vV] [dD][aA][tT][aA]', "%+02d0%+03d0" % (int(tile[0]/10), int(tile[1]/10)), "%+03d%+04d.[eE][nN][vV]" % (tile[0], tile[1]))):
                # DSF or ENV exists but can't read it
                tex=join('Resources','airport0_000.png')
            else:
                tex=join('Resources','Sea01.png')
            self.mesh[key]=[(tex, 1,
                             [[-onedeg*cos(d2r*(tile[0]+1))/2, 0, -onedeg/2],
                              [ onedeg*cos(d2r* tile[0]   )/2, 0,  onedeg/2],
                              [-onedeg*cos(d2r* tile[0]   )/2, 0,  onedeg/2],
                              [-onedeg*cos(d2r*(tile[0]+1))/2, 0, -onedeg/2],
                              [ onedeg*cos(d2r*(tile[0]+1))/2, 0, -onedeg/2],
                              [ onedeg*cos(d2r* tile[0]   )/2, 0,  onedeg/2]],
                             [[0, 0], [100, 100], [0, 100],
                              [0, 0], [100, 0], [100, 100]])]


    # populate arrays and load texs
    def getMesh(self, tile, options):
        if self.meshcache:
            return self.meshcache
        # merge patches that use same texture
        bytex={}
        for texture, flags, v, t in self.mesh[(tile[0],tile[1],options&Prefs.TERRAIN)]:
            #if options&Prefs.ELEVATION:
            #    # Transfrom from lat,lon,e to curved surface in cartesian space
            #    (x,y,z)=v
            
            if (texture,flags) in bytex:
                (v2,t2)=bytex[(texture,flags)]
                v2.extend(v)
                t2.extend(t)
            else:
                bytex[(texture,flags)]=(list(v), list(t))
        # add into array
        if __debug__: clock=time.clock()	# Processor time
        for (texture, flags), (v, t) in bytex.iteritems():
            base=len(self.varray)
            self.varray.extend(v)
            self.tarray.extend(t)
            texno=self.texcache.get(texture, flags&1)
            self.meshcache.append((base, len(v), texno, flags/2))
        if __debug__: print "%s CPU time in getMesh" % (time.clock()-clock)
        self.valid=False	# new geometry -> need to update OpenGL
        return self.meshcache


    # create sets of bounding boxes for height testing
    def getMeshdata(self, tile, options):
        key=(tile[0],tile[1],options&Prefs.ELEVATION)
        if key in self.meshdata:
            return self.meshdata[key]	# don't reload
        if not options&Prefs.ELEVATION:
            meshdata=[([-maxint,maxint,-maxint,maxint],
                       [([[-maxint,0,-maxint],
                          [-maxint,0, maxint],
                          [ maxint,0,-maxint]],[0,0,0,0])])]
            self.meshdata[key]=meshdata
            return meshdata
        meshdata=[]
        tot=0
        if __debug__: clock=time.clock()	# Processor time
        for (texture, flags, v, t) in self.mesh[(tile[0],tile[1],options&Prefs.TERRAIN)]:
            minx=minz=maxint
            maxx=maxz=-maxint
            tris=[]
            for i in range(0,len(v),3):
                minx=min(minx, v[i][0], v[i+1][0], v[i+2][0])
                maxx=max(maxx, v[i][0], v[i+1][0], v[i+2][0])
                minz=min(minz, v[i][2], v[i+1][2], v[i+2][2])
                maxz=max(maxz, v[i][2], v[i+1][2], v[i+2][2])
                tris.append(([v[i], v[i+1], v[i+2]], [0,0,0,0]))
            meshdata.append(([minx, maxx, minz, maxz], tris))
            tot+=len(tris)
        if __debug__: print "%s CPU time in getMeshdata" % (time.clock()-clock)
        #print len(meshdata), "patches,", tot, "tris,", tot/len(meshdata), "av"
        self.meshdata[key]=meshdata
        return meshdata
            

    def height(self, tile, options, x, z, likely=None):
        # returns height of mesh at (x,z) using tri if supplied
        if not options&Prefs.ELEVATION: return 0

        # first test candidates
        if likely:
            h=self.heighttest([likely], x, z)
            if h!=None: return h
        if self.lasttri and (not likely or self.lasttri!=likely):
            h=self.heighttest([self.lasttri], x, z)
            if h!=None: return h

        # test all patches then
        for (bbox, tris) in self.getMeshdata(tile,options):
            if x<bbox[0] or x>bbox[1] or z<bbox[2] or z>bbox[3]: continue
            h=self.heighttest(tris, x, z)
            if h!=None: return h
        
        # dunno
        return 0

    def heighttest(self, tris, x, z):
        # helper for above
        for tri in tris:
            (pt, coeffs)=tri
            # http://astronomy.swin.edu.au/~pbourke/geometry/insidepoly
            c=False
            for i in range(3):
                j=(i+1)%3
                if ((((pt[i][2] <= z) and (z < pt[j][2])) or
                     ((pt[j][2] <= z) and (z < pt[i][2]))) and
                    (x < (pt[j][0]-pt[i][0]) * (z - pt[i][2]) / (pt[j][2] - pt[i][2]) + pt[i][0])):
                    c = not c
            if c:
                self.lasttri=tri
                # http://astronomy.swin.edu.au/~pbourke/geometry/planeline
                if not coeffs[3]:
                    coeffs[0] = pt[0][1]*(pt[1][2]-pt[2][2]) + pt[1][1]*(pt[2][2]-pt[0][2]) + pt[2][1]*(pt[0][2]-pt[1][2]) # A
                    coeffs[1] = pt[0][2]*(pt[1][0]-pt[2][0]) + pt[1][2]*(pt[2][0]-pt[0][0]) + pt[2][2]*(pt[0][0]-pt[1][0]) # B
                    coeffs[2] = pt[0][0]*(pt[1][1]-pt[2][1]) + pt[1][0]*(pt[2][1]-pt[0][1]) + pt[2][0]*(pt[0][1]-pt[1][1]) # C
                    coeffs[3] = -(pt[0][0]*(pt[1][1]*pt[2][2]-pt[2][1]*pt[1][2]) + pt[1][0]*(pt[2][1]*pt[0][2]-pt[0][1]*pt[2][2]) + pt[2][0]*(pt[0][1]*pt[1][2]-pt[1][1]*pt[0][2])) # D
                return -(coeffs[0]*x + coeffs[2]*z + coeffs[3]) / coeffs[1]
        # no hit
        return None
        


def importObj(pkgpath, path):
    # find base texture location
    if sep+'custom objects'+sep in path.lower():
        oldtexpath=path[:path.lower().index(sep+'custom objects'+sep)]
        for t in listdir(oldtexpath):
            if t.lower()=='custom object textures': break
        else:
            t='custom object textures'
        oldtexpath=join(oldtexpath, t)
    elif sep+'autogen objects'+sep in path.lower():
        oldtexpath=path[:path.lower().index(sep+'autogen objects'+sep)]
        for t in listdir(oldtexpath):
            if t.lower()=='autogen textures': break
        else:
            t='AutoGen textures'
        oldtexpath=join(oldtexpath, t)
    else:
        oldtexpath=dirname(path)

    # find destination
    for o in listdir(pkgpath):
        if o.lower()=='custom objects':
            newpath=join(pkgpath, o)
            for t in listdir(pkgpath):
                if t.lower()=='custom object textures': break
            else:
                t='custom object textures'
            newtexpath=join(pkgpath, t)
            newtexprefix=''
            break
    else:
        for o in listdir(pkgpath):
            if o.lower()=='objects':
                newpath=join(pkgpath, o)
                for t in listdir(pkgpath):
                    if t.lower()=='textures': break
                else:
                    t='textures'
                newtexpath=join(pkgpath, t)
                newtexprefix='../'+t+'/'
                break
        else:
            newpath=newtexpath=pkgpath
            newtexprefix=''
    for f in listdir(newpath):
        if f.lower()==basename(path).lower():
            raise IOError, (0, "An object with this name already exists in this package")
    if path[-4:].lower()=='.obj':
        badobj=(0, "This is not an X-Plane v6, v7 or v8 object")
    else:
        badobj=(0, "This is not an X-Plane v8 facade, forest or polygon")
    h=file(path, 'rU')
    # Preserve comments, copyrights etc
    line=h.readline().strip()
    if not line[0] in ['I','A']:
        raise IOError, badobj
    if platform=='darwin':
        header='A'+line[1:]+'\n'
    else:
        header='I'+line[1:]+'\n'
    line=h.readline().strip()
    header+=line+'\n'
    c=line.split()
    if not c or not c[0] in ['2', '700', '800', '850']:
        raise IOError, badobj
    version=c[0]
    if version!='2':
        line=h.readline().strip()
        header+=line+'\n'
        c=line.split()
        if not c or not (c[0]=='OBJ' or
                         (version=='800' and c[0] in ['FACADE', 'FOREST']) or
                         (version=='850' and c[0]=='DRAPED_POLYGON')):
            raise IOError, badobj
    if version in ['2','700']:
        while True:
            line=h.readline()
            if not line: raise IOError, badobj
            line=line.strip()
            if not line:
                header+='\n'
            else:
                if '//' in line:
                    tex=line[:line.index('//')].strip()
                    rest='\t'+line[line.index('//'):]+'\n'
                else:
                    tex=line
                    rest='\n'
                tex=tex.replace(':', sep)
                tex=tex.replace('/', sep)
                (tex, ext)=splitext(tex)
                header+=newtexprefix+basename(tex)+rest
                for e in [ext, '.png', '.PNG', '.bmp', '.BMP']:
                    if exists(join(oldtexpath, tex+e)):
                        if not isdir(newtexpath): mkdir(newtexpath)
                        if not exists(join(newtexpath, basename(tex)+e)):
                            copyfile(join(oldtexpath, tex+e),
                                     join(newtexpath, basename(tex)+e))
                        break
                for lit in [tex+'_LIT', tex+'_lit', tex+'LIT', tex+'lit']:
                    for e in [ext, '.png', '.PNG', '.bmp', '.BMP']:
                        if exists(join(oldtexpath, lit+e)):
                            if not isdir(newtexpath): mkdir(newtexpath)
                            if not exists(join(newtexpath, basename(tex)+'_LIT'+e)):
                                copyfile(join(oldtexpath, lit+e),
                                         join(newtexpath, basename(tex)+'_LIT'+e))
                            break
                    else:
                        continue	# next lit
                    break
                break
    else: # v8.x
        while True:
            line=h.readline()
            if not line: raise IOError, badobj
            line=line.strip()
            if not line or line[0]=='#':
                header+=line+'\n'
            elif line.split()[0] in ['TEXTURE', 'TEXTURE_LIT', 'TEXTURE_NOWRAP', 'TEXTURE_LIT_NOWRAP']:
                c=line.split()
                if len(c)==1:
                    header+=c[0]+'\t\n'
                else:
                    tex=line[len(c[0]):].strip()
                    tex=tex.replace(':', sep)
                    tex=tex.replace('/', sep)
                    header+=c[0]+'\t'+newtexprefix+basename(tex)+'\n'
                    if not isdir(newtexpath): mkdir(newtexpath)
                    if exists(join(oldtexpath, tex)) and not exists(join(newtexpath, basename(tex))):
                        copyfile(join(oldtexpath, tex), join(newtexpath, basename(tex)))
            else:
                header+=line+'\n'
                break	# Stop at first non-texture statement

    # Write new OBJ
    newfile=join(newpath,basename(path))
    w=file(newfile, 'wU')
    w.write(header)
    for line in h:
        w.write(line.rstrip()+'\n')
    w.close()
    h.close()
    return newfile
