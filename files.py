import PIL.Image
import PIL.PngImagePlugin, PIL.BmpImagePlugin, PIL.JpegImagePlugin 	# force for py2exe
import OpenGL	# for __version__
from OpenGL.GL import *
from OpenGL.GL.EXT.bgra import glInitBgraEXT, GL_BGR_EXT, GL_BGRA_EXT
from OpenGL.GL.ARB.texture_compression import glInitTextureCompressionARB, glCompressedTexImage2DARB, GL_COMPRESSED_RGB_ARB, GL_COMPRESSED_RGBA_ARB, GL_TEXTURE_COMPRESSION_HINT_ARB
try:
    from OpenGL.GL.EXT.texture_compression_s3tc import glInitTextureCompressionS3tcEXT, GL_COMPRESSED_RGB_S3TC_DXT1_EXT, GL_COMPRESSED_RGBA_S3TC_DXT1_EXT, GL_COMPRESSED_RGBA_S3TC_DXT3_EXT, GL_COMPRESSED_RGBA_S3TC_DXT5_EXT
except:
    try:	# Full SWIG rebuild, eg Fedora
        from OpenGL.GL.EXT.texture_compression_s3tc import glInitTextureCompressionS3TcEXT, GL_COMPRESSED_RGB_S3TC_DXT1_EXT, GL_COMPRESSED_RGBA_S3TC_DXT1_EXT, GL_COMPRESSED_RGBA_S3TC_DXT3_EXT, GL_COMPRESSED_RGBA_S3TC_DXT5_EXT
        glInitTextureCompressionS3tcEXT=glInitTextureCompressionS3TcEXT
    except:
        def glInitTextureCompressionS3tcEXT(): return False

try:
    from OpenGL.GL.ARB.texture_non_power_of_two import glInitTextureNonPowerOfTwoARB
except:	# not in 2.0.0.44
    def glInitTextureNonPowerOfTwoARB(): return False

try:
    from OpenGL.GL.ARB.vertex_buffer_object import glInitVertexBufferObjectARB, glGenBuffersARB, glBindBufferARB, glBufferDataARB, GL_ARRAY_BUFFER_ARB, GL_STATIC_DRAW_ARB
except:
    def glInitVertexBufferObjectARB(): return False

import codecs
from glob import glob
from math import cos, log, pi, radians
from os import listdir, mkdir
from os.path import basename, curdir, dirname, exists, isdir, join, normpath, pardir, sep, splitext
from shutil import copyfile
from struct import unpack
from sys import platform, maxint
from traceback import print_exc
import time
import wx
if OpenGL.__version__ >= '3':
    from numpy import array, hstack, float32

from clutterdef import BBox, KnownDefs, SkipDefs, NetworkDef
from DSFLib import readDSF
from palette import PaletteEntry
from prefs import Prefs
from version import appname, appversion


# memory leak? causing SegFault on Linux - Ubuntu seems OK for some reason
cantreleasetexs=(platform.startswith('linux'))

onedeg=1852*60	# 1 degree of longitude at equator (60nm) [m]
f2m=0.3041	# 1 foot [m] (not accurate, but what X-Plane appears to use)

GL_CLAMP_TO_EDGE=0x812F	# Not defined in PyOpenGL 2.x

# DDS surface flags
DDSD_CAPS	= 0x00000001
DDSD_HEIGHT	= 0x00000002
DDSD_WIDTH	= 0x00000004
DDSD_PITCH	= 0x00000008
DDSD_PIXELFORMAT= 0x00001000
DDSD_MIPMAPCOUNT= 0x00020000
DDSD_LINEARSIZE	= 0x00080000
DDSD_DEPTH	= 0x00800000
# DS pixelformat flags
DDPF_ALPHAPIXELS= 0x00000001
DDPF_FOURCC	= 0x00000004
DDPF_RGB	= 0x00000040
# DDS caps1
DDSCAPS_COMPLEX	= 0x00000008
DDSCAPS_TEXTURE	= 0x00001000
DDSCAPS_MIPMAP	= 0x00400000

# 2.3 version of case-insensitive sort
# 2.4-only version is faster: sort(cmp=lambda x,y: cmp(x.lower(), y.lower()))
def sortfolded(seq):
    seq.sort(lambda x,y: cmp(x.lower(), y.lower()))


# Scan global airport list - assumes code is ASCII for speed
def scanApt(filename):
    airports={}	# (name, [lat,lon], fileoffset) by code
    nav=[]	# (type,lat,lon,hdg)
    h=file(filename, 'rU')	# assumes ascii
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
    offset=0
    # mixing read and tell - http://www.thescripts.com/forum/post83277-3.html
    while True:
        line=h.readline()
        if not line: break
        c=line.split()
        if not c: continue
        id=int(c[0])
        if id in [1,16,17]:		# Airport/Seaport/Heliport
            if code and loc:
                airports[code]=(name,loc,offset)
                code=name=loc=None
            offset=long(h.tell())	# cast to long for 64bit Linux
            code=c[4]#.decode('latin1')
            if len(code)>4: raise IOError	# X-Plane doesn't like
            name=(' '.join(c[5:])).decode('latin1')
        elif id==18 and int(c[3]):	# Beacon - goes in nav
            nav.append((id*10+int(c[3]), float(c[1]),float(c[2]), 0))
        elif id==19:	# Windsock - goes in nav
            nav.append((id, float(c[1]),float(c[2]), 0))
        elif id==21:	# VASI/PAPI - goes in nav
            nav.append((id*10+int(c[3]), float(c[1]),float(c[2]), float(c[4])))
        elif id==99:
            break
        elif loc:	# Don't bother parsing past first location
            pass
        elif id==14:	# Prefer tower location
            loc=[float(c[1]),float(c[2])]
        elif id==10:	# Runway / taxiway
            loc=[float(c[1]),float(c[2])]
        elif id==100:	# 850 Runway
            loc=[(float(c[9])+float(c[18]))/2,(float(c[10])+float(c[19]))/2]
        elif id==101:	# 850 Water runway
            loc=[(float(c[4])+float(c[7]))/2, (float(c[5])+float(c[8]))/2]
        elif id==102:	# 850 Helipad
            loc=[float(c[2]),float(c[3])]
    if code and loc:	# No terminating 99
        airports[code]=(name,loc,offset)
    h.close()
    return (airports, nav)

# two modes of operation:
# - without offset, return all airports and navs (used for custom apt.dats)
# - with offset, just return airport at offset (used for global apt.dat)
def readApt(filename, offset=None):
    airports={}	# (name, [lat,lon], [(lat,lon,hdg,length,width,stop,stop)]) by code
    nav=[]	# (type,lat,lon,hdg)
    firstcode=None
    h=open(filename, 'rU')
    if offset:
        h.seek(offset)
    else:
        if not h.readline().strip() in ['A','I']:
            raise AssertionError, "The apt.dat file in this package is invalid."
        while True:	# NYEXPRO has a blank line here
            c=h.readline().split()
            if c: break
        ver=c[0]
        if not ver in ['600','703','715','810','850','1000']:
            raise AssertionError, "The apt.dat file in this package is invalid."
        ver=int(ver)

    code=name=loc=None
    run=[]
    pavement=[]
    for line in h:
        c=line.split()
        if not c: continue
        id=int(c[0])
        if pavement and id not in range(111,120):
            run.append(pavement[:-1])
            pavement=[]
        if id in [1,16,17]:		# Airport/Seaport/Heliport
            if offset:	# reached next airport
                if not run: raise AssertionError, "Airport %s does not have any runways." % code
                h.close()
                return run
            if code:
                if code in airports: raise AssertionError, "Airport %s is listed more than once." % code
                if not run: raise AssertionError, "Airport %s does not have any runways." % code
                airports[code]=(name,loc,run)
                code=name=loc=None
                run=[]
            code=c[4].decode('latin1')
            if len(code)>4: raise AssertionError, "Airport %s has an ICAO code longer than 4 characters." % code	# X-Plane doesn't like
            if not firstcode: firstcode=code
            name=(' '.join(c[5:])).decode('latin1')
        elif id==14:	# Prefer tower location
            loc=[float(c[1]),float(c[2])]
        elif id==10:	# Runway / taxiway
            # (lat,lon,h,length,width,stop1,stop2,surface,shoulder,isrunway)
            lat=float(c[1])
            lon=float(c[2])
            if not loc: loc=[lat,lon]
            stop=c[7].split('.')
            if len(stop)<2: stop.append(0)
            if len(c)<11:
                surface=int(c[9])/1000000	# v6
            else:
                surface=int(c[10])
            if len(c)<12:
                shoulder=0
            else:
                shoulder=int(c[11])
            if c[3][0]=='H': surface=surface-5
            run.append((lat, lon, float(c[4]), f2m*float(c[5]),f2m*float(c[8]),
                        f2m*float(stop[0]), f2m*float(stop[1]),
                        surface, shoulder, c[3]!='xxx'))
        elif id==100:	# 850 Runway
            # ((lat1,lon1),(lat2,lon2),width,stop1,stop2,surface,shoulder)
            if not loc:
                loc=[(float(c[9])+float(c[18]))/2,
                     (float(c[10])+float(c[19]))/2]
            run.append(((float(c[9]), float(c[10])),
                        (float(c[18]), float(c[19])),
                        float(c[1]), float(c[12]),float(c[21]), int(c[2]), int(c[3])))
        elif id==101:	# 850 Water runway
            # ((lat1,lon1),(lat2,lon2),width,stop1,stop2,surface,shoulder)
            if not loc:
                loc=[(float(c[4])+float(c[7]))/2,
                     (float(c[5])+float(c[8]))/2]
            run.append(((float(c[4]), float(c[5])),
                        (float(c[7]), float(c[8])),
                        float(c[1]), 0,0, 13, 0))
        elif id==102:	# 850 Helipad
            # (lat,lon,h,length,width,stop1,stop2,surface,shoulder,isrunway)
            lat=float(c[2])
            lon=float(c[3])
            if not loc: loc=[lat,lon]
            run.append((lat, lon, float(c[4]), float(c[5]),float(c[6]),
                        0,0, int(c[7]), int(c[9]), True))
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
            nav.append((id*10+int(c[3]), float(c[1]),float(c[2]), 0))
        elif id==19:	# Windsock - goes in nav
            nav.append((id, float(c[1]),float(c[2]), 0))
        elif id==21:	# VASI/PAPI - goes in nav
            nav.append((id*10+int(c[3]), float(c[1]),float(c[2]), float(c[4])))
        elif id==99:
            break
            if offset:	# reached next airport
                if not run: raise AssertionError, "Airport %s does not have any runways." % code
                h.close()
                return run
            if not loc or not run: raise IOError
            airports[code]=(name,loc,run)
            code=name=loc=None
            run=[]
            break
    # No terminating 99
    if offset:
        if not run: raise AssertionError, "Airport %s does not have any runways." % code
        h.close()
        return run
    if code:
        if code in airports: raise AssertionError, "Airport %s is listed more than once." % code
        if not run: raise AssertionError, "Airport %s does not have any runways." % code
        airports[code]=(name,loc,run)
    else:
        raise AssertionError, "The apt.dat file in this package is empty."
    h.close()
    return (airports, nav, firstcode)


def readNav(filename):
    nav=[]	# (type,lat,lon,hdg)
    h=open(filename, 'rU')
    if not h.readline().strip() in ['A','I']:
        raise IOError
    while True:
        c=h.readline().split()
        if c: break
    ver=c[0]
    if not ver in ['740','810']:
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
    thisfileobjs={}
    h=None
    path=dirname(filename)
    if basename(dirname(filename))=='800 objects':
        filename=join('Resources','800library.txt')
        builtinhack=True
    else:
        builtinhack=False
    try:
        h=codecs.open(filename, 'rU', 'latin1')
        if not h.readline().strip()[0] in ['I','A']:
            raise IOError
        if not h.readline().split()[0]=='800':
            raise IOError
        if not h.readline().split()[0]=='LIBRARY':
            raise IOError
        regionskip=False
        for line in h:
            c=line.split()
            if not c: continue
            id=c[0]
            if id=='REGION':
                regionskip=(c[1]!='all')	# we don't yet handle region-specific libraries (e.g. terrain)
            elif regionskip:
                continue
            elif id in ['EXPORT', 'EXPORT_RATIO', 'EXPORT_EXTEND', 'EXPORT_EXCLUDE']:
                # ignore EXPORT_BACKUP
                if id=='EXPORT_RATIO': c.pop(1)
                if len(c)<3 or (c[1][-4:].lower() in SkipDefs and c[1]!=NetworkDef.DEFAULTFILE): continue
                name=c[1].replace(':','/').replace('\\','/')
                if builtinhack:
                    lib='misc v800'
                else:
                    lib=name
                    if lib.startswith('/'): lib=lib[1:]
                    if lib.startswith('lib/'):
                        lib=lib[4:lib.index('/',4)]
                    elif lib.startswith('opensceneryx/'):
                        lib=lib[:lib.index('/',13)]
                    elif not '/' in lib:
                        lib="uncategorised"
                    else:
                        lib=lib[:lib.index('/')]
                # allow single spaces
                obj=' '.join(c[2:]).replace(':','/').replace('\\','/')
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
                        if name in thisfileobjs:
                            objects[lib][name].multiple=True
                            continue
                        else:
                            thisfileobjs[name]=True
                            if name in objects[lib]:
                                continue	# already defined elsewhere
                    else:
                        thisfileobjs[name]=True
                        objects[lib]={}
                    objects[lib][name]=PaletteEntry(obj)
    except:
        if h: h.close()
        if __debug__:
            print filename
            print_exc()
            

def readNet(filename):
    objs={#'highway_pylon.obj':		(0,20),
          'highway_susp_twr.obj':	(41,41),	# fixed height
          #'local_pylon.obj':		(0,15.8),
          #'powerline_tower.obj':	(0,0),		# on ground          
          #'railroad_pylon.obj':		(0,15.1),
          #'ramp_pylon.obj':		(0,20.5),
          #'secondary_oldpylon.obj':	(0,23.4),
          #'secondary_pylon.obj':	(0,23),
          }
    path=dirname(filename)
    currentdef=None
    defs=[]
    texs=[]
    h=codecs.open(filename, 'rU', 'latin1')
    if not h.readline().strip()[0] in ['I','A']:
        raise IOError
    if not h.readline().split()[0]=='800':
        raise IOError
    if not h.readline().split()[0]=='ROADS':
        raise IOError
    comment=None
    scale=1
    for line in h:
        c=line.split()
        if not c:
            pass
        elif c[0]=='#' and len(c)==2:
            comment=c[1]
            if comment.startswith('net_'): comment=comment[4:]
            continue
        elif c[0] in ['TEXTURE', 'TEXTURE_BRIDGE']:
            texs.append((join(path,c[2]), int(float(c[1]))))
        elif c[0]=='SCALE':
            scale=int(c[1])
        elif c[0]=='ROAD_TYPE':
            n=int(c[1])
            if comment:
                name=comment
                # detect duplicate names
                for x in defs:
                    if x and x.name==name:
                        name="%03d" % n
                        break
            else:
                name="%03d" % n
            if n>=len(defs): defs.extend([None for i in range(n+1-len(defs))])
            currentdef=defs[n]=NetworkDef(filename, name, n, float(c[2]), float(c[3]), texs[int(c[4])][0], texs[int(c[4])][1], (float(c[5]), float(c[6]), float(c[7])))
        elif c[0]=='REQUIRE_EVEN':
            currentdef.even=True
        elif c[0] in ['SEGMENT', 'SEGMENT_HARD']:
            if not float(c[1]):	# 0 LOD
                currentdef.segments.append(((float(c[3])-0.5)*currentdef.width, float(c[4]), float(c[5])/scale, (float(c[6])-0.5)*currentdef.width, float(c[7]), float(c[8])/scale))
        elif c[0]=='OBJECT':
            if c[1] in objs: currentdef.height=objs[c[1]]
            assert not float(c[3])	# don't handle rotation
            currentdef.objs.append((join(path,c[1]), (float(c[2])-0.5)*currentdef.width, int(c[4]), float(c[5]), float(c[6])))
        comment=None

    h.close()
    return defs


class TexCache:
    
    def __init__(self):
        self.blank=0	#self.get(join('Resources','blank.png'))
        self.texs={}
        self.terraintexs=[]	# terrain textures will not be reloaded
        # Must be after init
        self.maxtexsize=glGetIntegerv(GL_MAX_TEXTURE_SIZE)
        self.npot=glInitTextureNonPowerOfTwoARB()
        self.compress=glInitTextureCompressionARB()
        self.s3tc=self.compress and glInitTextureCompressionS3tcEXT()
        self.bgra=glInitBgraEXT()
        # Texture compression appears severe on Mac, but this doesn't help
        if self.compress: glHint(GL_TEXTURE_COMPRESSION_HINT_ARB, GL_NICEST)
        if glGetString(GL_VERSION) >= '1.2':
            self.clampmode=GL_CLAMP_TO_EDGE
        else:
            self.clampmode=GL_CLAMP

    def reset(self):
        if cantreleasetexs:
            # Hack round suspected memory leak causing SegFault on SUSE
            pass
        else:
            a=[]
            for name in self.texs.keys():
                if self.texs[name] not in self.terraintexs:
                    a.append(self.texs[name])
                    self.texs.pop(name)
            if a:
                glDeleteTextures(a)

    def get(self, path, wrap=True, alpha=True, downsample=False, fixsize=False):
        if not path: return self.blank
        if path in self.texs:
            return self.texs[path]
        #self.texs[path]=self.blank	# don't do this - want error reported for each file that uses this texture

        #if __debug__: clock=time.clock()	# Processor time

        # X-Plane 10 will load dds or png depending on user's compression settings.
        # We will prefer dds if the texture is to be downsampled (terrain), otherwise png (objects).
        (base,oldext)=splitext(path)
        if downsample:
            for ext in ['.dds', '.DDS', '.png', '.PNG']:
                if exists(base+ext): break
                else: ext=oldext
        else:
            for ext in ['.png', '.PNG', '.dds', '.DDS']:
                if exists(base+ext): break
                else: ext=oldext

        try:
            if ext.lower()=='.dds':
                # Do DDS manually - files need flipping
                h=file(base+ext,'rb')
                if h.read(4)!='DDS ': raise IOError, 'This is not a DDS file'
                (ssize,sflags,height,width,size,depth,mipmaps)=unpack('<7I', h.read(28))
                #print ssize,sflags,height,width,size,depth,mipmaps
                if sflags&(DDSD_CAPS|DDSD_PIXELFORMAT|DDSD_WIDTH|DDSD_HEIGHT)!=(DDSD_CAPS|DDSD_PIXELFORMAT|DDSD_WIDTH|DDSD_HEIGHT): raise IOError, 'Missing mandatory fields'
                if sflags&DDSD_DEPTH: raise IOError, 'Volume texture not supported'
                for dim in [width,height]:
                    l=log(dim,2)
                    if l!=int(l):
                        raise IOError, "Width and/or height is not a power of two"
                if sflags&(DDSD_PITCH|DDSD_LINEARSIZE)==DDSD_PITCH:
                    size*=height
                #elif sflags&(DDSD_PITCH|DDSD_LINEARSIZE)!=DDSD_LINEARSIZE:
                #    raise IOError, 'Invalid size'
                h.seek(0x4c)
                (psize,pflags,fourcc,bits,redmask,greenmask,bluemask,alphamask,caps1,caps2)=unpack('<2I4s7I', h.read(40))
                if not sflags&DDSD_MIPMAPCOUNT or not caps1&DDSCAPS_MIPMAP:
                    mipmaps=0

                if pflags&DDPF_FOURCC:
                    # http://oss.sgi.com/projects/ogl-sample/registry/EXT/texture_compression_s3tc.txt
                    if not self.s3tc: raise IOError, 'This video driver does not support DXT compression'
                    if fourcc=='DXT1':
                        if not (sflags&(DDSD_PITCH|DDSD_LINEARSIZE)):
                            size=width*height/2
                        else:
                            assert size==width*height/2
                        iformat=GL_COMPRESSED_RGBA_S3TC_DXT1_EXT
                    elif fourcc=='DXT3':
                        if not (sflags&(DDSD_PITCH|DDSD_LINEARSIZE)):
                            size=width*height
                        else:
                            assert size==width*height
                        iformat=GL_COMPRESSED_RGBA_S3TC_DXT3_EXT
                    elif fourcc=='DXT5':
                        if not (sflags&(DDSD_PITCH|DDSD_LINEARSIZE)):
                            size=width*height
                        else:
                            assert size==width*height
                        iformat=GL_COMPRESSED_RGBA_S3TC_DXT5_EXT
                    else:
                        raise IOError, '%s format not supported' % fourcc

                    if downsample and mipmaps>=2 and width>=16 and height>=16:
                        h.seek(4+ssize + (size*5)/4)
                        size/=16
                        width/=4
                        height/=4
                    else:	# don't downsample
                        h.seek(4+ssize)
                    if not alpha:	# discard alpha
                        if iformat==GL_COMPRESSED_RGBA_S3TC_DXT1_EXT:
                            data=h.read(size)
                        else:
                            data=''
                            for i in range(size/16):
                                data+=h.read(16)[8:]	# skip alpha
                        iformat=GL_COMPRESSED_RGB_S3TC_DXT1_EXT
                    else:
                        data=h.read(size)
                    h.close()
                        
                    id=glGenTextures(1)
                    glBindTexture(GL_TEXTURE_2D, id)
                    if wrap:
                        glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_S,GL_REPEAT)
                        glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_T,GL_REPEAT)
                    else:
                        glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_S,self.clampmode)
                        glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_T,self.clampmode)
                    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
                    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
                    if OpenGL.__version__ < '3':
                        glCompressedTexImage2DARB(GL_TEXTURE_2D, 0, iformat, width, height, 0, data)
                    else:
                        glCompressedTexImage2DARB(GL_TEXTURE_2D, 0, iformat, width, height, 0, len(data), data)
                    #if __debug__: print "%6.3f" % (time.clock()-clock), basename(path), wrap, alpha, downsample, fixsize

                    self.texs[path]=id
                    if downsample:
                        self.terraintexs.append(id)
                    return id
                    
                elif pflags&DDPF_RGB:	# uncompressed
                    assert size==width*height*bits/8	# pitch appears unreliable
                    if bits==24 and redmask==0xff0000 and greenmask==0x00ff00 and bluemask==0x0000ff:
                        if not self.bgra: raise IOError, 'This video driver does not support BGR format'
                        format=GL_BGR_EXT
                        iformat=GL_RGB
                    elif bits==24 and redmask==0x0000ff and greenmask==0x00ff00 and bluemask==0xff0000:
                        format=GL_RGB
                        iformat=GL_RGB
                    elif bits==32 and pflags&DDPF_ALPHAPIXELS and alphamask==0xff000000L and redmask==0x00ff0000 and greenmask==0x0000ff00 and bluemask==0x000000ff:
                        if not self.bgra: raise IOError, 'This video driver does not support BGRA format'
                        format=GL_BGRA_EXT
                        iformat=GL_RGBA
                    elif bits==32 and not pflags&DDPF_ALPHAPIXELS and redmask==0x00ff0000 and greenmask==0x0000ff00 and bluemask==0x000000ff:
                        if not self.bgra: raise IOError, 'This video driver does not support BGRA format'
                        format_GL_BGRA_EXT
                        iformat=GL_RGB
                    else:
                        raise IOError, '%dbpp format not supported' % bits

                    if downsample and mipmaps>=2 and width>4 and height>4:
                        h.seek(4+ssize + (size*5)/4)
                        size/=16
                        width/=4
                        height/=4
                    else:	# don't downsample
                        h.seek(4+ssize)
                    data=h.read(size)
                    h.close()
                    
                    # fall through

                else:	# wtf?
                    raise IOError, 'Invalid compression type'

            else:	# supported PIL formats
                image = PIL.Image.open(base+ext)
                size=[image.size[0],image.size[1]]
                for i in [0,1]:
                    l=log(size[i],2)
                    if l!=int(l): size[i]=2**(1+int(l))
                    if size[i]>self.maxtexsize:
                        size[i]=self.maxtexsize
                    if size!=[image.size[0],image.size[1]]:
                        if not fixsize:
                            raise IOError, "Width and/or height is not a power of two"
                        elif not self.npot:
                            image=image.resize((size[0], size[1]), PIL.Image.BICUBIC)

                if downsample and image.size[0]>4 and image.size[1]>4:
                    image=image.resize((image.size[0]/4,image.size[1]/4), PIL.Image.NEAREST)
                
                if image.mode=='RGBA':
                    data = image.tostring("raw", 'RGBA')
                    format=iformat=GL_RGBA
                elif image.mode=='RGB':
                    data = image.tostring("raw", 'RGB')
                    format=iformat=GL_RGB
                elif image.mode=='LA' or 'transparency' in image.info:
                    image=image.convert('RGBA')
                    data = image.tostring("raw", 'RGBA')
                    format=iformat=GL_RGBA
                else:
                    image=image.convert('RGB')
                    data = image.tostring("raw", 'RGB')
                    format=iformat=GL_RGB
                width=image.size[0]
                height=image.size[1]

            # variables used: data, format, iformat, width, height
            if not alpha:	# Discard alpha
                iformat=GL_RGB
            if self.compress:
                if iformat==GL_RGB:
                    iformat=GL_COMPRESSED_RGB_ARB
                elif iformat==GL_RGBA:
                    iformat=GL_COMPRESSED_RGBA_ARB                        

            id=glGenTextures(1)
            glBindTexture(GL_TEXTURE_2D, id)
            if wrap:
                glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_S,GL_REPEAT)
                glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_T,GL_REPEAT)
            else:
                glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_S,self.clampmode)
                glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_T,self.clampmode)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
            glTexImage2D(GL_TEXTURE_2D, 0, iformat, width, height, 0, format, GL_UNSIGNED_BYTE, data)
            #if __debug__: print "%6.3f" % (time.clock()-clock), basename(path), wrap, alpha, downsample, fixsize
                
            self.texs[path]=id
            if downsample:
                self.terraintexs.append(id)
            return id

        # Callers expect an IOError
        except IOError, e:
            if e.errno==2:
                if __debug__: print "%s file not found" % basename(path)
                raise IOError, (2, "%s: %s" % (path, e.strerror))
            elif e.strerror:
                if __debug__: print "%s %s" % (basename(path), e.strerror)
                raise IOError, (e.errno, e.strerror)
            else:	# PIL "cannot read interlaced PNG files"
                if __debug__: print "%s: %s" % (basename(path), e)
                raise IOError, (0, str(e))
        except GLerror, e:
            if __debug__: print "%s %s" % (basename(path), e)
            raise IOError, (0, str(e))
        except:
            if __debug__:
                print "%s unknown error" % basename(path)
                print_exc()
            raise IOError, (0, 'unknown error')


class VertexCache:

    def __init__(self):
        self.ter={}		# name -> physical ter
        self.mesh={}		# tile -> [patches] where patch=(texture,f,v,t)
        self.meshdata={}	# tile -> [(bbox, [(points, plane coeffs)])]
        self.nets={}		# tile -> [(type, [points])]
        self.currenttile=None
        self.meshcache=[]	# [indices] of current tile
        self.lasttri=None	# take advantage of locality of reference

        self.texcache=TexCache()
        self.varray=[]
        self.tarray=[]
        self.valid=False
        self.dsfdirs=None	# [custom, global, default]

        self.vbo=False # XXX (OpenGL.__version__ >= '3') and glInitVertexBufferObjectARB()
        self.vertexbuf=0

    def reset(self, terrain, dsfdirs):
        # invalidate geometry and textures
        self.ter=terrain
        self.dsfdirs=dsfdirs
        self.flush()
        self.texcache.reset()
    
    def flush(self):
        # invalidate array indices
        self.currenttile=None
        self.meshcache=[]
        self.varray=[]
        self.tarray=[]
        self.valid=False
        self.lasttri=None

    def realize(self, canvas):
        # need to call this before drawing
        if not self.valid:
            if __debug__: clock=time.clock()	# Processor time
            if wx.VERSION >= (2,9):
                canvas.SetCurrent(canvas.context)
            if self.vbo:
                # PyOpenGL 3b8 with numpy - broken
                if not self.vertexbuf:
                    from OpenGL.arrays import vbo
                    assert vbo.get_implementation()
                    self.vertexbuf=vbo.VBO(hstack((array(self.tarray, float32), array(self.varray, float32))).flatten())
                    if __debug__: print "VBOs enabled! %s" % self.vertexbuf
                self.vertexbuf.bind()
                glInterleavedArrays(GL_T2F_V3F, 0, self.vertexbuf)
            elif False:
                # PyOpenGL 3b6 with numpy - also broken
                if not self.vertexbuf:
                    self.vertexbuf=long(glGenBuffersARB(1))
                    if __debug__: print "VBOs enabled! %s" % self.vertexbuf
                glBindBufferARB(GL_ARRAY_BUFFER_ARB, self.vertexbuf)
                glBufferDataARB(GL_ARRAY_BUFFER_ARB, hstack((array(self.tarray, float32), array(self.varray, float32))).flatten(), GL_STATIC_DRAW_ARB)
                glInterleavedArrays(GL_T2F_V3F, 0, None)
            elif self.varray:
                #glInterleavedArrays(GL_T2F_V3F, 0, hstack((array(self.tarray, float32), array(self.varray, float32))).flatten())	# XXX requires numpy
                glVertexPointerf(self.varray)
                glTexCoordPointerf(self.tarray)
                #b=array(map(lambda x,y: x+y, self.tarray, self.varray), float32)
                #glInterleavedArrays(GL_T2F_V3F, 0, b.tostring())
            else:	# need something or get conversion error
                if __debug__: print "Empty arrays!"
                #glInterleavedArrays(GL_T2F_V3F, 0, [[0.0,0,0,0,0]])
                glVertexPointerf([[0,0,0]])
                glTexCoordPointerf([[0,0]])
            if __debug__:
                print "%6.3f time to realize arrays" % (time.clock()-clock)
            self.valid=True

    def allocate(self, vdata, tdata):
        # allocate geometry data into cache, but don't update OpenGL arrays
        base=len(self.varray)
        self.varray.extend(vdata)
        self.tarray.extend(tdata)
        self.valid=False	# new geometry -> need to update OpenGL
        return base

    def loadMesh(self, tile, options):
        key=(tile[0],tile[1],options&Prefs.TERRAIN)
        netkey=(tile[0],tile[1],options&Prefs.NETWORK)
        if key in self.mesh and netkey in self.nets:
            return	# don't reload
        dsfs=[]
        if options&Prefs.TERRAIN:
            for path in self.dsfdirs:
                if not glob(path): continue
                pathlen=len(glob(path)[0])+1
                thisdsfs=glob(join(path, '*', '[eE][aA][rR][tT][hH] [nN][aA][vV] [dD][aA][tT][aA]', "%+02d0%+03d0" % (int(tile[0]/10), int(tile[1]/10)), "%+03d%+04d.[dD][sS][fF]" % (tile[0], tile[1])))
                # asciibetical, except global is last
                thisdsfs.sort(lambda x,y: ((x[pathlen:].lower().startswith('-global ') and 1) or
                                           (y[pathlen:].lower().startswith('-global ') and -1) or
                                           cmp(x,y)))
                dsfs+=thisdsfs
                #print join(path, '*', '[eE][aA][rR][tT][hH] [nN][aA][vV] [dD][aA][tT][aA]', "%+02d0%+03d0" % (int(tile[0]/10), int(tile[1]/10)), "%+03d%+04d.[dD][sS][fF]" % (tile[0], tile[1]))
        if __debug__: clock=time.clock()	# Processor time
        for dsf in dsfs:
            try:
                (lat, lon, placements, nets, mesh)=readDSF(dsf, False, False, self.ter)
                if mesh:
                    self.mesh[key]=mesh
                    # post-process networks
                    centrelat=lat+0.5
                    centrelon=lon+0.5
                    newnets=[]
                    for (road, points) in nets:
                        newpoints=[[(p[0]-centrelon)*onedeg*cos(radians(p[1])),
                                    p[2],
                                    (centrelat-p[1])*onedeg] for p in points]
                        newnets.append((road, newpoints))
                    self.nets[(tile[0],tile[1],0)]=[]	# prevents reload on stepping down
                    self.nets[netkey]=newnets
                    break
            except:
                if __debug__: print_exc()
        if __debug__: print "%6.3f time in loadMesh" % (time.clock()-clock)
        if not key in self.mesh:
            for path in self.dsfdirs[1:]:
                if glob(join(path, '*', '[eE][aA][rR][tT][hH] [nN][aA][vV] [dD][aA][tT][aA]', "%+02d0%+03d0" % (int(tile[0]/10), int(tile[1]/10)), "%+03d%+04d.[dD][sS][fF]" % (tile[0], tile[1]))) or glob(join(path, pardir, '[eE][aA][rR][tT][hH] [nN][aA][vV] [dD][aA][tT][aA]', "%+02d0%+03d0" % (int(tile[0]/10), int(tile[1]/10)), "%+03d%+04d.[eE][nN][vV]" % (tile[0], tile[1]))):
                    # DSF or ENV exists but can't read it
                    tex=join('Resources','airport0_000.png')
                    break
            else:
                tex=join('Resources','Sea01.png')
            self.mesh[key]=[(tex, 1,
                             [[-onedeg*cos(radians(tile[0]+1))/2, 0,-onedeg/2],
                              [ onedeg*cos(radians(tile[0]  ))/2, 0, onedeg/2],
                              [-onedeg*cos(radians(tile[0]  ))/2, 0, onedeg/2],
                              [-onedeg*cos(radians(tile[0]+1))/2, 0,-onedeg/2],
                              [ onedeg*cos(radians(tile[0]+1))/2, 0,-onedeg/2],
                              [ onedeg*cos(radians(tile[0]  ))/2, 0, onedeg/2]],
                             [[0, 0], [100, 100], [0, 100],
                              [0, 0], [100, 0], [100, 100]])]
            self.nets[(tile[0],tile[1],0)]=[]	# prevents reload on stepping down
            self.nets[(tile[0],tile[1],Prefs.NETWORK)]=[]

    # return mesh data sorted by tex for drawing
    def getMesh(self, tile, options):
        if tile==self.currenttile:
            return self.meshcache
        # merge patches that use same texture
        bytex={}
        for texture, flags, v, t in self.mesh[(tile[0],tile[1],options&Prefs.TERRAIN)]:
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
            texno=self.texcache.get(texture, flags&8, False, flags&1)
            self.meshcache.append((base, len(v), texno, flags&2))
        if __debug__: print "%6.3f time in getMesh" % (time.clock()-clock)
        self.valid=False	# new geometry -> need to update OpenGL
        self.currenttile=tile
        return self.meshcache


    # return net data
    def getNets(self, tile, options):
        return self.nets[(tile[0],tile[1],options&Prefs.NETWORK)]


    # create sets of bounding boxes for height testing
    def getMeshdata(self, tile, options):
        if not options&Prefs.ELEVATION:
            mlat=max(abs(tile[0]),abs(tile[0]+1))
            return [(BBox(-onedeg*cos(radians(mlat))/2, onedeg*cos(radians(mlat))/2, -onedeg/2,onedeg/2),
                     [([[-onedeg*cos(radians(tile[0]+1))/2, 0,-onedeg/2],
                        [ onedeg*cos(radians(tile[0]  ))/2, 0, onedeg/2],
                        [-onedeg*cos(radians(tile[0]  ))/2, 0, onedeg/2]],
                       [0,0,0,0]),
                      ([[-onedeg*cos(radians(tile[0]+1))/2, 0,-onedeg/2],
                        [ onedeg*cos(radians(tile[0]+1))/2, 0,-onedeg/2],
                        [ onedeg*cos(radians(tile[0]  ))/2, 0, onedeg/2]],
                       [0,0,0,0])])]
        key=(tile[0],tile[1],options&Prefs.ELEVATION)
        if key in self.meshdata:
            return self.meshdata[key]	# don't reload
        meshdata=[]
        tot=0
        if __debug__: clock=time.clock()	# Processor time
        for (texture, flags, v, t) in self.mesh[(tile[0],tile[1],options&Prefs.TERRAIN)]:
            if not flags&1: continue	# not interested in overlays
            minx=minz=maxint
            maxx=maxz=-maxint
            tris=[]
            for i in range(0,len(v),3):
                minx=min(minx, v[i][0], v[i+1][0], v[i+2][0])
                maxx=max(maxx, v[i][0], v[i+1][0], v[i+2][0])
                minz=min(minz, v[i][2], v[i+1][2], v[i+2][2])
                maxz=max(maxz, v[i][2], v[i+1][2], v[i+2][2])
                tris.append(([v[i], v[i+1], v[i+2]], [0,0,0,0]))
            meshdata.append((BBox(minx, maxx, minz, maxz), tris))
            tot+=len(tris)
        if __debug__: print "%6.3f time in getMeshdata" % (time.clock()-clock)
        #print len(meshdata), "patches,", tot, "tris,", tot/len(meshdata), "av"
        self.meshdata[key]=meshdata
        return meshdata
            

    def height(self, tile, options, x, z, likely=[]):
        # returns height of mesh at (x,z) using tri if supplied
        if not options&Prefs.ELEVATION: return 0

        # first test candidates
        if likely:
            h=self.heighttest(likely, x, z)
            if h!=None: return h
        if self.lasttri and (self.lasttri not in likely):
            h=self.heighttest([self.lasttri], x, z)
            if h!=None: return h

        # test all patches then
        for (bbox, tris) in self.getMeshdata(tile,options):
            if not bbox.inside(x,z): continue
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
                    # only if "textures" folder exists
                    if t.lower()=='textures':
                        newtexpath=join(pkgpath, t)
                        newtexprefix='../'+t+'/'
                        break
                else:
                    newtexpath=newpath
                    newtexprefix=''
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
        badobj=(0, "This is not an X-Plane v8 polygon")
    h=codecs.open(path, 'rU', 'latin1')
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
                for e in [ext, '.dds', '.DDS', '.png', '.PNG', '.bmp', '.BMP']:
                    if exists(join(oldtexpath, tex+e)):
                        if not isdir(newtexpath): mkdir(newtexpath)
                        if not exists(join(newtexpath, basename(tex)+e)):
                            copyfile(join(oldtexpath, tex+e),
                                     join(newtexpath, basename(tex)+e))
                        break
                for lit in [tex+'_LIT', tex+'_lit', tex+'LIT', tex+'lit']:
                    for e in [ext, '.dds', '.DDS', '.png', '.PNG', '.bmp', '.BMP']:
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
                    (tex, ext)=splitext(tex)
                    for e in [ext, '.dds', '.DDS', '.png', '.PNG', '.bmp', '.BMP']:
                        if exists(join(oldtexpath, tex+e)):
                            if not isdir(newtexpath): mkdir(newtexpath)
                            if not exists(join(newtexpath, basename(tex)+e)):
                                copyfile(join(oldtexpath, tex+e),
                                         join(newtexpath, basename(tex)+e))
                            header+=c[0]+'\t'+newtexprefix+basename(tex)+e+'\n'
                            break
                    else:
                        header+=c[0]+'\t'+newtexprefix+basename(tex)+ext+'\n'
            else:
                header+=line+'\n'
                break	# Stop at first non-texture statement

    # Write new OBJ
    newfile=join(newpath,basename(path)[:-4]+path[-4:].lower())
    w=file(newfile, 'wt')
    w.write(header)
    for line in h:
        w.write(line.rstrip()+'\n')
    w.close()
    h.close()
    return newfile
