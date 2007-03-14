from math import floor
from PIL.Image import open
import PIL.BmpImagePlugin, PIL.PngImagePlugin	# force for py2exe
from OpenGL.GL import *
from os import getenv, listdir, mkdir, makedirs, popen3, rename, unlink
from os.path import abspath, basename, curdir, dirname, exists, expanduser, isdir, join, normpath, pardir, sep
from sys import platform
from tempfile import gettempdir
import wx

if platform!='win32':
    import codecs

appname='OverlayEditor'
appversion='1.30'	# Must be numeric

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
    def __init__(self):
        self.xplane=None
        self.package=None
        self.filename=None

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
            handle.close()
        except:
            pass

    def write(self):
        try:
            if platform=='win32':
                handle=file(self.filename,'wt')
            else:
                handle=codecs.open(self.filename, 'wt', 'utf-8')
            handle.write('%s\n%s\n' % (self.xplane, self.package))
            handle.close()
        except:
            pass


def readApt(filename):
    byname={}
    bycode={}
    runways={}	# (lat,lon,hdg,length,width) by code
    if not exists(filename):
        return (byname, bycode, runways)
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


def readLib(filename, objects):
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
            if c[0]=='EXPORT' and len(c)>=3 and c[1][-4:].lower()=='.obj':
                c.pop(0)
                name=c[0][:-4]
                name=name.replace(':','/')
                name=name.replace('\\','/')
                if name[0][0]=='/': name=name[1:]
                lib=name
                if name.startswith('lib/'): lib=lib[4:]
                if not '/' in lib:
                    lib="uncategorised"
                else:
                    lib=lib[:lib.index('/')]
                if lib in objects and name in objects[lib]:
                    continue
                c.pop(0)
                obj=' '.join(c)	# allow single spaces
                obj=obj.replace(':','/')
                obj=obj.replace('\\','/')
                if obj=='blank.obj':
                    continue	# no point adding placeholders
                obj=join(path, normpath(obj))
                if not lib in objects:
                    objects[lib]={}
                objects[lib][name]=obj
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
            data.append((objects[int(c[1])], float(c[3]), float(c[2]), float(c[4])))
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
    if not exists(path): makedirs(path)
    for f in listdir(path):
        if f.lower()=='earth nav data':
            endpath=join(path,f)
            break
    else:
        endpath=join(path, 'Earth nav data')
        makedirs(path)

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
        if not exists(tiledir): mkdir(tiledir)
        tmp=join(gettempdir(), "%+03d%+04d.txt" % (south,west))
        h=file(tmp, 'wt')
        h.write('I\n800\nDSF2TEXT\n\n')
        h.write('PROPERTY sim/planet\tearth\n')
        h.write('PROPERTY sim/overlay\t1\n')
        h.write('PROPERTY sim/require_object\t1/0\n')
        h.write('PROPERTY sim/creation_agent\t%s %s\n' % (
            appname, appversion))
        h.write(props)
        h.write('PROPERTY sim/west\t%d\n' %  west)
        h.write('PROPERTY sim/east\t%d\n' %  (west+1))
        h.write('PROPERTY sim/north\t%d\n' %  (south+1))
        h.write('PROPERTY sim/south\t%d\n' %  south)
        h.write('\n')
        objects=[]
        for (obj, lat, lon, hdg) in placement:
            if not obj in objects:
                objects.append(obj)
                h.write('OBJECT_DEF %s.obj\n' % obj)
        h.write('\n')
        for (obj, lat, lon, hdg) in placement:
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
    
def readObj(path, texcache):
    h=None
    culled=[]
    nocull=[]
    current=culled
    tculled=[]
    tnocull=[]
    tcurrent=tculled
    texno=0
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
                texno=texcache.get(tex+ext)
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
                            texno=texcache.get(tex+ext)
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
    return (culled, nocull, tculled, tnocull, texno, maxpoly)


class TexCache:
    def __init__(self):
        self.blank=0
        self.texs={}
        self.blank=0	#self.get(join('Resources','blank.png'))
        self.texs={}

    def flush(self):
        for i in self.texs.values():
            glDeleteTextures([i])
        self.texs={}

    def get(self, path):
        if path in self.texs:
            return self.texs[path]
        try:
            id=glGenTextures(1)
            image = open(path)
            if image.mode!='RGBA':
                image=image.convert('RGBA')
            data = image.tostring("raw", 'RGBA', 0, -1)
            glBindTexture(GL_TEXTURE_2D, id)
            glTexParameterf(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_REPEAT)
            glTexParameterf(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_REPEAT)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
            glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, image.size[0], image.size[1], 0, GL_RGBA, GL_UNSIGNED_BYTE, data)
            self.texs[path]=id
            return id
        except:
            return self.blank
