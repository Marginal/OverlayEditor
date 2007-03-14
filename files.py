from math import floor, cos, pi
from PIL.Image import open, BILINEAR
import PIL.BmpImagePlugin, PIL.JpegImagePlugin, PIL.PngImagePlugin	# force for py2exe
from OpenGL.GL import *
from os import getenv, listdir, mkdir, popen3, rename, unlink
from os.path import abspath, basename, curdir, dirname, exists, expanduser, isdir, join, normpath, pardir, sep, splitext
from shutil import copyfile
from sys import platform, maxint
from tempfile import gettempdir
import wx

import DSFLib

if platform!='win32':
    import codecs

onedeg=1852*60	# 1 degree of longitude at equator (60nm) [m]
d2r=pi/180.0

appname='OverlayEditor'
appversion=1.42	# Must be numeric

if platform=='win32':
    dsftool=join(curdir,'win32','DSFTool.exe')
elif platform.lower().startswith('linux'):
    dsftool=join(curdir,'linux','DSFTool')
else:	# Mac
    dsftool=join(curdir,'MacOS','DSFTool')


# 2.3 version of case-insensitive sort
# 2.4-only version is faster: sort(cmp=lambda x,y: cmp(x.lower(), y.lower()))
def sortfolded(seq):
    seq.sort(lambda x,y: cmp(x.lower(), y.lower()))


class Prefs:
    TERRAIN=1
    ELEVATION=2
    
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
            if platform=='win32':
                handle=file(self.filename,'rU')
            else:
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
            if platform=='win32':
                handle=file(self.filename,'wt')
            else:
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
    byname={}
    bycode={}
    runways={}	# (lat,lon,hdg,length,width) by code
    if platform=='win32':
        h=file(filename,'rU')
    else:
        h=codecs.open(filename, 'rU', 'latin1')
    if not h.readline().strip() in ['A','I']:
        raise IOError
    if not h.readline().split()[0] in ['715','810']:
        raise IOError
    loc=None
    name=None
    code=None
    run=[]
    for line in h:
        c=line.split()
        if not len(c) or (len(c)==1 and int(c[0])==99):
            if loc:
                #tile=[int(floor(loc[0])),int(floor(loc[1]))]
                byname['%s - %s' % (name,code)]=loc
                bycode['%s - %s' % (code,name)]=loc
                runways[code]=run
            loc=None
            run=[]
        elif int(c[0]) in [1,16,17]:
            code=c[4]
            name=' '.join(c[5:])
        elif int(c[0])==10:	# Runway / taxiway
            if not loc:
                loc=[float(c[1]),float(c[2])]
            stop=c[7].split('.')
            if len(stop)<2: stop.append(0)
            run.append((float(c[1]),float(c[2]), float(c[4]),
                        float(c[5])+float(stop[0])+float(stop[1]),float(c[8])))
        elif int(c[0])==14:	# Prefer tower
            loc=[float(c[1]),float(c[2])]
    if loc:	# No terminating 99
        byname['%s - %s' % (name,code)]=loc
        bycode['%s - %s' % (code,name)]=loc
        runways[code]=run
    h.close()
    return (byname, bycode, runways)


def readLib(filename, objects, terrain):
    h=None
    try:
        path=dirname(filename)
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
            if c[0]=='EXPORT' and len(c)>=3 and c[1][-4:].lower() in ['.obj', '.ter']:
                c.pop(0)
                name=c[0]
                name=name.replace(':','/')
                name=name.replace('\\','/')
                #if name[0][0]=='/': name=name[1:]	# No! keep leading '/'
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
                if name[-4:]=='.obj':
                    name=name[:-4]
                    if lib in objects:
                        if name in objects[lib]: continue
                    else:
                        objects[lib]={}
                    objects[lib][name]=obj
                else:
                    if name in terrain: continue
                    terrain[name]=obj
    except:
        if h: h.close()
            

def readDsf(filename):
    tmp=join(gettempdir(), basename(filename[:-4])+'.txt')
    (i,o,e)=popen3('%s -dsf2text "%s" "%s"' % (dsftool, filename, tmp))
    i.close()
    o.read()
    err=e.read()
    o.close()
    e.close()
    tile=[0,0]
    objects=[]
    data=[]
    props=''
    other=''
    overlay=False
    h=file(tmp, 'rU')
    if not h.readline().strip()[0] in ['I','A']:
        raise IOError
    if not h.readline().split()[0]=='800':
        raise IOError
    if not h.readline().split()[0]=='DSF2TEXT':
        raise IOError
    while 1:
        line=h.readline()
        if not line: break
        c=line.split()
        if not c: continue
        if c[0]=='PROPERTY':
            if c[1]=='sim/overlay' and int(c[2])==1: overlay=True
            elif c[1]=='sim/south': tile[0]=int(c[2])
            elif c[1]=='sim/west': tile[1]=int(c[2])
            elif c[1].startswith('sim/exclude'): props+=line
        elif c[0]=='OBJECT_DEF':
            if not overlay:	# crap out early
                h.close()
                unlink(tmp)
                wx.MessageBox("Can't edit this package:\n%s is not an overlay." % basename(filename), 'Error', wx.ICON_ERROR|wx.OK, None)
                raise IOError
            obj=line.strip()[10:].strip()[:-4]
            obj=obj.replace(':','/')
            obj=obj.replace('\\','/')
            objects.append(obj)
        elif c[0]=='OBJECT':
            data.append((objects[int(c[1])], float(c[3]), float(c[2]), float(c[4]), None))
        elif line.startswith('# Result code:'):
            if int(c[3]):
                h.close()
                unlink(tmp)
                wx.MessageBox("Can't edit this package:\nCan't parse %s." % basename(filename), 'Error', wx.ICON_ERROR|wx.OK, None)
                raise IOError
        elif c[0][0]!='#':
            other+=line
    h.close()
    unlink(tmp)
    if not overlay:
        wx.MessageBox("Can't edit this package:\n%s is not an overlay." % basename(filename), 'Error', wx.ICON_ERROR|wx.OK, None)
        raise IOError
    return ((tile[0],tile[1]), data, props, other)


def writeDsfs(path, placements, baggage):
    if not isdir(path): mkdir(path)
    for f in listdir(path):
        if f.lower()=='earth nav data':
            endpath=join(path,f)
            break
    else:
        endpath=join(path, 'Earth nav data')
        if not isdir(endpath): mkdir(endpath)

    for key in placements.keys():
        (south,west)=key
        tiledir=join(endpath, "%+02d0%+03d0" % (int(south/10), int(west/10)))
        tilename=join(tiledir, "%+03d%+04d" % (south,west))
        if exists(tilename+'.dsf'):
            if exists(tilename+'.dsf.bak'): unlink(tilename+'.dsf.bak')
            rename(tilename+'.dsf', tilename+'.dsf.bak')
        if exists(tilename+'.DSF'):
            if exists(tilename+'.DSF.BAK'): unlink(tilename+'.DSF.BAK')
            rename(tilename+'.DSF', tilename+'.DSF.BAK')
        placement=placements[key]
        if key not in baggage:
            props=other=''
        else:
            (props,other)=baggage[key]
        if not (placement or props or other): continue
        if not isdir(tiledir): mkdir(tiledir)
        tmp=join(gettempdir(), "%+03d%+04d.txt" % (south,west))
        h=file(tmp, 'wt')
        h.write('I\n800\nDSF2TEXT\n\n')
        h.write('PROPERTY sim/planet\tearth\n')
        h.write('PROPERTY sim/overlay\t1\n')
        h.write('PROPERTY sim/require_object\t1/0\n')
        h.write('PROPERTY sim/creation_agent\t%s %4.2f\n' % (
            appname, appversion))
        h.write(props)
        h.write('PROPERTY sim/west\t%d\n' %  west)
        h.write('PROPERTY sim/east\t%d\n' %  (west+1))
        h.write('PROPERTY sim/north\t%d\n' %  (south+1))
        h.write('PROPERTY sim/south\t%d\n' %  south)
        h.write('\n')
        objects=[]
        for (obj, lat, lon, hdg, height) in placement:
            if not obj in objects:
                objects.append(obj)
                h.write('OBJECT_DEF %s.obj\n' % obj)
        h.write('\n')
        for (obj, lat, lon, hdg, height) in placement:
            h.write('OBJECT %3d %11.6f %10.6f %3.0f\n' % (
                objects.index(obj), lon, lat, hdg))
        h.write('\n')
        h.write(other)
        h.close()
        (i,o,e)=popen3('%s -text2dsf "%s" "%s.dsf"' % (dsftool, tmp, tilename))
        i.close()
        o.read()
        err=e.read()
        o.close()
        e.close()
        unlink(tmp)

    
class TexCache:
    def __init__(self, clampmode):
        self.blank=0
        self.texs={}
        self.blank=0	#self.get(join('Resources','blank.png'))
        self.texs={}
        self.clampmode=clampmode

    def flush(self):
        if self.texs:
            glDeleteTextures(self.texs.values())
        self.texs={}

    def get(self, path, isterrain=False):
        if not path: return 0
        if path in self.texs:
            return self.texs[path]
        try:
            id=glGenTextures(1)
            image = open(path)
            if not isterrain:
                if image.mode=='RGBA':
                    data = image.tostring("raw", 'RGBA', 0, -1)
                    format=GL_RGBA
                else:
                    data = image.tostring("raw", 'RGB', 0, -1)
                    format=GL_RGB
            else:
                if image.mode!='RGB': image=image.convert('RGB')
                image.resize((image.size[0]/2, image.size[1]/2), BILINEAR)
                data = image.tostring("raw", 'RGB', 0, -1)
                format=GL_RGB
            glBindTexture(GL_TEXTURE_2D, id)
            #glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, self.clampmode)
            #glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, self.clampmode)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
            glTexImage2D(GL_TEXTURE_2D, 0, format, image.size[0], image.size[1], 0, format, GL_UNSIGNED_BYTE, data)
            self.texs[path]=id
            return id
        except:
            return self.blank


class VertexCache:
    defObj=join('Resources','default.obj')
    defSea=join('Resources','Sea01.png')

    def __init__(self, clampmode):
        # indices = (base, #culled, #nocull, texno, maxpoly)
        self.obj={}		# name -> physical obj
        self.geo={}		# physical obj -> geo
        self.idx={}		# physical obj -> indices
        self.objcache={}	# name -> indices

        # indices = (base, #culled, texno)
        self.ter={}		# name -> physical ter
        self.mesh={}		# tile -> [patches] where patch=(texture, v, t)
        self.meshdata={}	# tile->[(bbox, [(points, plane coeffs)])]
        self.meshcache=[]	# [indices] of current tile
        self.lasttri=None	# take advantage of locality of reference

        self.texcache=TexCache(clampmode)
        self.varray=[]
        self.tarray=[]
        self.valid=False
        self.dsfdir=None

    def flush(self):
        # invalidate array indices
        self.idx={}
        self.objcache={}
        self.meshcache=[]
        self.varray=[]
        self.tarray=[]
        self.valid=False
        self.lasttri=None

    def flushObjs(self, objects, terrain, dsfdir):
        # invalidate object geometry and textures
        self.obj=objects
        self.ter=terrain
        self.dsfdir=dsfdir
        self.geo={}
        self.idx={}
        self.flush()
        self.texcache.flush()
    
    def realize(self):
        # need to call this before drawing
        if not self.valid:
            if self.varray:
                glVertexPointerf(self.varray)
                glTexCoordPointerf(self.tarray)
            else:	# need something or get conversion error
                glVertexPointerf([[0,0,0],[0,0,0],[0,0,0]])
                glTexCoordPointerf([[0,0],[0,0]])
            self.valid=True

    def getObj(self, name):
        # object better be in cache or we go bang
        return self.objcache[name]

    def addObj(self, name, path):
        # Import a new object
        self.obj[name]=path
        
    def loadObj(self, name, usefallback=False):
        # read object into cache, but don't update OpenGL arrays
        # returns False if error reading object

        if name in self.objcache:
            # Already loaded (or fallbacked)
            return True
        
        if not name in self.obj:
            # Physical object is missing
            if usefallback:
                self.obj[name]=VertexCache.defObj
            else:
                return False
        
        path=self.obj[name]
        if path in self.idx:
            # Object is already in the array under another name
            self.objcache[name]=self.idx[path]
            return True

        if path in self.geo:
            # Object geometry is loaded, but not in the array
            (culled, nocull, tculled, tnocull, texture, maxpoly)=self.geo[path]
            base=len(self.varray)
            self.varray.extend(culled)
            self.varray.extend(nocull)
            self.tarray.extend(tculled)
            self.tarray.extend(tnocull)
            texno=self.texcache.get(texture)
            self.objcache[name]=self.idx[path]=(base, len(culled), len(nocull), texno, maxpoly)
            self.valid=False	# new geometry -> need to update OpenGL
            return True
            
        try:
            # Physical object has not yet been read
            h=None
            culled=[]
            nocull=[]
            current=culled
            tculled=[]
            tnocull=[]
            tcurrent=tculled
            texture=None
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
                while 1:
                    line=h.readline()
                    if not line: raise IOError
                    tex=line.strip()
                    if tex:
                        if '//' in tex: tex=tex[:tex.index('//')]
                        tex=tex.strip()
                        tex=tex.replace(':', sep)
                        tex=tex.replace('/', sep)
                        break
                tex=abspath(join(texpath,tex))
                for ext in ['', '.png', '.PNG', '.bmp', '.BMP']:
                    if exists(tex+ext):
                        texture=tex+ext
                        break
            if version=='2':
                while 1:
                    line=h.readline()
                    if not line: break
                    c=line.split()
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
                        current.append(v[0])
                        tcurrent.append([uv[0],uv[3]])
                        current.append(v[1])
                        tcurrent.append([uv[1],uv[2]])
                        current.append(v[2])
                        tcurrent.append([uv[1],uv[3]])
                    else:
                        uv=[float(c[1]), float(c[2]), float(c[3]), float(c[4])]
                        v=[]
                        for i in range(4):
                            c=h.readline().split()
                            v.append([float(c[0]), float(c[1]), float(c[2])])
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
                while 1:
                    line=h.readline()
                    if not line: break
                    c=line.split()
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
                            seq=[]	# XXX implement me
                        elif c[0]=='tri_fan':
                            count=int(c[1])
                            for i in range(1,count-1):
                                seq.extend([0,i,i+1])
                        else:
                            count=4
                            seq=[0,1,2,0,2,3]
                        v=[]
                        t=[]
                        i=0
                        while i<count:
                            c=h.readline().split()
                            v.append([float(c[0]), float(c[1]), float(c[2])])
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
                idx=[]
                anim=[[0,0,0]]
                while 1:
                    line=h.readline()
                    if not line: break
                    c=line.split()
                    if not c: continue
                    if c[0]=='TEXTURE':
                        if len(c)>1:
                            tex=line[7:].strip()
                            tex=tex.replace(':', sep)
                            tex=tex.replace('/', sep)
                            tex=abspath(join(texpath,tex))
                            for ext in ['', '.png', '.PNG', '.bmp', '.BMP']:
                                if exists(tex+ext):
                                    texture=tex+ext
                                    break
                    elif c[0]=='VT':
                        vt.append([float(c[1]), float(c[2]), float(c[3]),
                                   float(c[7]), float(c[8])])
                    elif c[0]=='IDX':
                        idx.append(int(c[1]))
                    elif c[0]=='IDX10':
                        idx.extend([int(c[1]), int(c[2]), int(c[3]), int(c[4]), int(c[5]), int(c[6]), int(c[7]), int(c[8]), int(c[9]), int(c[10])])
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
                        anim.append([anim[-1][0], anim[-1][1], anim[-1][2]])
                    elif c[0]=='ANIM_end':
                        anim.pop()
                    elif c[0]=='ANIM_trans':
                        anim[-1]=[anim[-1][0]+float(c[1]),
                                  anim[-1][1]+float(c[2]),
                                  anim[-1][2]+float(c[3])]
                    elif c[0]=='TRIS':
                        for i in range(int(c[1]), int(c[1])+int(c[2])):
                            v=vt[idx[i]]
                            current.append([anim[-1][0]+v[0],
                                            anim[-1][1]+v[1],
                                            anim[-1][2]+v[2]])
                            tcurrent.append([v[3], v[4]])
            h.close()
            if not (len(culled)+len(nocull)):
                # show empty objects as placeholders otherwise can't edit
                self.loadObj('*default', True)
                self.objcache[name]=self.idx[path]=self.getObj('*default')
            else:
                self.geo[path]=(culled, nocull, tculled, tnocull, texture, maxpoly)
                base=len(self.varray)
                self.varray.extend(culled)
                self.varray.extend(nocull)
                self.tarray.extend(tculled)
                self.tarray.extend(tnocull)
                texno=self.texcache.get(texture)
                self.objcache[name]=self.idx[path]=(base, len(culled), len(nocull), texno, maxpoly)
                self.valid=False	# new geometry -> need to update OpenGL
        except:
            if usefallback:
                self.loadObj('*default', True)
                self.objcache[name]=self.idx[path]=self.getObj('*default')
            return False
        return True


    def loadMesh(self, tile, options):
        key=(tile[0],tile[1],options&Prefs.TERRAIN)
        if key in self.mesh: return	# don't reload
        try:
            if not options&Prefs.TERRAIN: raise IOError
            (properties, placements, meshdata)=DSFLib.read(join(self.dsfdir, "%+02d0%+03d0" % (int(tile[0]/10), int(tile[1]/10)), "%+03d%+04d.dsf" % (tile[0], tile[1])))
        except:
            if exists(join(self.dsfdir, "%+02d0%+03d0" % (int(tile[0]/10), int(tile[1]/10)), "%+03d%+04d.dsf" % (tile[0], tile[1]))) or exists(join(self.dsfdir, pardir, pardir, pardir, 'Earth nav data', "%+02d0%+03d0" % (int(tile[0]/10), int(tile[1]/10)), "%+03d%+04d.env" % (tile[0], tile[1]))):
                # DSF or ENV exists but can't read it
                ter='lib/terrain/grass_Af.ter'	# plain v8.0 terrain
            else:
                ter='terrain_Water'
            meshdata=[(ter, [[tile[1],   tile[0],   0],
                             [tile[1]+1, tile[0]+1, 0],
                             [tile[1]+1, tile[0],   0],
                             [tile[1],   tile[0],   0],
                             [tile[1],   tile[0]+1, 0],
                             [tile[1]+1, tile[0]+1, 0]])]
        mesh=[]
        terraincache={}
        centrelat=tile[0]+0.5
        centrelon=tile[1]+0.5
        for (ter, patch) in meshdata:
            texture=None
            angle=0
            xscale=zscale=0.001
            if ter=='terrain_Water':
                texture=abspath(VertexCache.defSea)
            elif ter in terraincache:
                (texture, angle, xscale, zscale)=terraincache[ter]
            else:
                try:
                    h=file(self.ter[ter], 'rU')
                    if not (h.readline().strip() in ['I','A'] and
                            h.readline().strip()=='800' and
                            h.readline().strip()=='TERRAIN'):
                        raise IOError
                    for line in h:
                        line=line.strip()
                        c=line.split()
                        if not c: continue
                        if c[0]=='BASE_TEX':
                            texture=line[8:].strip()
                            texture=texture.replace(':', sep)
                            texture=texture.replace('/', sep)
                            texture=abspath(join(dirname(self.ter[ter]),texture))
                        elif c[0]=='PROJECTED':
                            xscale=1/float(c[1])
                            zscale=1/float(c[2])
                        elif c[0]=='PROJECT_ANGLE':
                            if float(c[1])==0 and float(c[2])==1 and float(c[3])==0:
                                # no idea what rotation about other axes means
                                angle=int(float(c[4]))
                    h.close()
                except:
                    pass
                terraincache[ter]=(texture, angle, xscale, zscale)

            v=[]
            t=[]
            if len(patch[0])<7:	# no st coords (all? Laminar hard scenery)
                for p in patch:
                    x=(p[0]-centrelon)*onedeg*cos(d2r*p[1])
                    z=(centrelat-p[1])*onedeg
                    v.append([x, p[2], z])
                    if angle==90:
                        t.append([z*zscale, x*xscale])
                        #texture=join('Resources','FS2X-palette.png')
                        #t.append([0.24,0])	# red
                    elif angle==180:
                        t.append([-x*xscale, z*zscale])
                        #texture=join('Resources','FS2X-palette.png')
                        #t.append([0,0.24])	# green
                    elif angle==270:
                        t.append([-z*zscale, -x*xscale])
                        #texture=join('Resources','FS2X-palette.png')
                        #t.append([0.75,0.75])	# blue
                    else: # angle==0 or not square
                        t.append([x*xscale, -z*zscale])
                        #texture=join('Resources','FS2X-palette.png')
                        #t.append([0.96,0.96])	# white
            else: # untested
                for p in patch:
                    v.append([(p[0]-centrelon)*onedeg*cos(d2r*p[1]),
                              p[2], (centrelat-p[1])*onedeg])
                    if angle==90:
                        t.append([p[6],p[5]])
                    elif angle==180:
                        t.append([-p[5],p[6]])
                    elif angle==270:
                        t.append([-p[6],-p[5]])
                    else: # angle==0 or not square
                        t.append([p[5],-p[6]])
            mesh.append((texture,v,t))
        self.mesh[key]=mesh


    def getMesh(self, tile, options):
        if self.meshcache:
            return self.meshcache
        # merge patches that use same texture
        bytex={}
        for texture, v, t in self.mesh[(tile[0],tile[1],options&Prefs.TERRAIN)]:
            if texture in bytex:
                (v2,t2)=bytex[texture]
                v2.extend(v)
                t2.extend(t)
            else:
                bytex[texture]=(list(v), list(t))
        # add into array
        for texture, (v, t) in bytex.iteritems():
            base=len(self.varray)
            self.varray.extend(v)
            self.tarray.extend(t)
            texno=self.texcache.get(texture, True)
            self.meshcache.append((base, len(v), texno))
        self.valid=False	# new geometry -> need to update OpenGL
        return self.meshcache


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
        for (texture, v, t) in self.mesh[(tile[0],tile[1],options&Prefs.TERRAIN)]:
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
        if self.lasttri:
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
    if path.startswith(pkgpath):
        raise IOError, (0, "This object is already in the package")

    # find base texture location
    if sep+'custom objects'+sep in path.lower():
        oldtexpath=path[:path.lower().index(sep+'custom objects'+sep)]
        for t in listdir(oldtexpath):
            if t.lower()=='custom object textures': break
        else:
            t='custom object textures'
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
    badobj=(0, "This is not an X-Plane v6, v7 or v8 object")
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
    if not c or not c[0] in ['2', '700','800']:
        raise IOError, badobj
    version=c[0]
    if version!='2':
        line=h.readline().strip()
        header+=line+'\n'
        c=line.split()
        if not c or not c[0]=='OBJ':
            raise IOError, badobj
    if version in ['2','700']:
        while 1:
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
    else: # v8
        while 1:
            line=h.readline()
            if not line: raise IOError, badobj
            line=line.strip()
            if not line or line[0]=='#':
                header+=line+'\n'
            elif line.split()[0] in ['TEXTURE', 'TEXTURE_LIT']:
                c=line.split()
                if len(c)==1:
                    header+=c[0]+'\t\n'
                else:
                    tex=line[len(c[0]):].strip()
                    tex=tex.replace(':', sep)
                    tex=tex.replace('/', sep)
                    header+=c[0]+'\t'+newtexprefix+basename(tex)+'\n'
                    if not isdir(newtexpath): mkdir(newtexpath)
                    if not exists(join(newtexpath, basename(tex))):
                        copyfile(join(oldtexpath, tex),
                                 join(newtexpath, basename(tex)))
            else:
                header+=line+'\n'
                break	# Stop at first non-texture statement

    # Write new OBJ
    newfile=join(newpath,basename(path))
    w=file(newfile, 'wU')
    w.write(header)
    for line in h:
        w.write(line.strip()+'\n')
    w.close()
    h.close()
    return newfile
