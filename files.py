from PIL.Image import open, NEAREST, BILINEAR, BICUBIC
import PIL.BmpImagePlugin, PIL.JpegImagePlugin, PIL.PngImagePlugin	# force for py2exe
from OpenGL.GL import *
try:
    from OpenGL.GL.ARB.texture_non_power_of_two import glInitTextureNonPowerOfTwoARB
except:	# not in 2.0.0.44
    def glInitTextureNonPowerOfTwoARB(): return False

import codecs
from glob import glob
from math import cos, log, pi, radians
from os import listdir, mkdir
from os.path import abspath, basename, curdir, dirname, exists, isdir, join, normpath, pardir, sep, splitext
from shutil import copyfile
import sys	# for version
from sys import platform, maxint
import wx
if __debug__:
    import time

#from Numeric import array

from clutterdef import BBox, KnownDefs, SkipDefs
from DSFLib import readDSF
from prefs import Prefs
from version import appname, appversion


# memory leak? causing SegFault on Linux - Ubuntu seems OK for some reason
cantreleasetexs=(platform.startswith('linux') and 'ubuntu' not in sys.version.lower())

onedeg=1852*60	# 1 degree of longitude at equator (60nm) [m]
f2m=0.3041	# 1 foot [m] (not accurate, but what X-Plane appears to use)

GL_CLAMP_TO_EDGE=0x812F	# Not defined in PyOpenGL 2.x

# 2.3 version of case-insensitive sort
# 2.4-only version is faster: sort(cmp=lambda x,y: cmp(x.lower(), y.lower()))
def sortfolded(seq):
    seq.sort(lambda x,y: cmp(x.lower(), y.lower()))


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
    if loc:	# No terminating 99
        if not run: raise IOError
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
                # ignore EXPORT_BACKUP
                if c[0]=='EXPORT_RATIO': c.pop(1)
                if len(c)<3 or c[1][-4:].lower() in SkipDefs: continue
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
        self.terraintexs=[]	# terrain textures will not be reloaded
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
            a=[]
            for name in self.texs.keys():
                if self.texs[name] not in self.terraintexs:
                    a.append(self.texs[name])
                    self.texs.pop(name)
            if a:
                glDeleteTextures(a)

    def get(self, path, wrap=True, alpha=True, downsample=False, fixsize=False):
        if not path: return 0
        if path in self.texs:
            return self.texs[path]
        try:
            image = open(path)
            if fixsize and not self.npot:
                size=[image.size[0],image.size[1]]
                for i in [0,1]:
                    l=log(size[i],2)
                    if l!=int(l): size[i]=2**(1+int(l))
                    if size[i]>glGetIntegerv(GL_MAX_TEXTURE_SIZE):
                        size[i]=glGetIntegerv(GL_MAX_TEXTURE_SIZE)
                if size!=[image.size[0],image.size[1]]:
                    image=image.resize((size[0], size[1]), BICUBIC)

            if (downsample or not alpha) and image.mode!='RGB':
                image=image.convert('RGB')
                
            if downsample:
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
            if wrap:
                glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_S,GL_REPEAT)
                glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_T,GL_REPEAT)
            else:
                glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_S,self.clampmode)
                glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_T,self.clampmode)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
            glTexImage2D(GL_TEXTURE_2D, 0, format, image.size[0], image.size[1], 0, format, GL_UNSIGNED_BYTE, data)
            self.texs[path]=id
            if downsample:
                self.terraintexs.append(id)
            return id
        except IOError, e:
            self.texs[path]=0
            if __debug__:
                if e.errno==2:
                    print 'Failed to find texture "%s"' % basename(path)
                else:
                    print 'Failed to load texture "%s" - %s' % (basename(path), e)
        except:
            self.texs[path]=0
            if __debug__: print 'Failed to load texture "%s"' % basename(path)
        return self.blank


class VertexCache:

    def __init__(self):
        self.ter={}		# name -> physical ter
        self.mesh={}		# tile -> [patches] where patch=(texture,f,v,t)
        self.meshdata={}	# tile->[(bbox, [(points, plane coeffs)])]
        self.currenttile=None
        self.meshcache=[]	# [indices] of current tile
        self.lasttri=None	# take advantage of locality of reference

        self.texcache=TexCache()
        self.varray=[]
        self.tarray=[]
        self.valid=False
        self.dsfdirs=None	# [custom, default]

    def reset(self, terrain, dsfdirs):
        # invalidate geometry and textures
        self.ter=terrain
        self.dsfdirs=dsfdirs
        self.flush()
        self.texcache.flush()
    
    def flush(self):
        # invalidate array indices
        self.currenttile=None
        self.meshcache=[]
        self.varray=[]
        self.tarray=[]
        self.valid=False
        self.lasttri=None

    def realize(self, context):
        # need to call this before drawing
        if not self.valid:
            if self.varray:
                glVertexPointerf(self.varray)
                glTexCoordPointerf(self.tarray)
            else:	# need something or get conversion error
                glVertexPointerf([[0,0,0]])
                glTexCoordPointerf([[0,0]])
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
        if __debug__: print "%6.3f time in loadMesh" % (time.clock()-clock)
        if not key in self.mesh:
            if glob(join(self.dsfdirs[1], '*', '[eE][aA][rR][tT][hH] [nN][aA][vV] [dD][aA][tT][aA]', "%+02d0%+03d0" % (int(tile[0]/10), int(tile[1]/10)), "%+03d%+04d.[dD][sS][fF]" % (tile[0], tile[1]))) + glob(join(self.dsfdirs[1], pardir, '[eE][aA][rR][tT][hH] [nN][aA][vV] [dD][aA][tT][aA]', "%+02d0%+03d0" % (int(tile[0]/10), int(tile[1]/10)), "%+03d%+04d.[eE][nN][vV]" % (tile[0], tile[1]))):
                # DSF or ENV exists but can't read it
                tex=join('Resources','airport0_000.png')
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

    # return mesh data sorted by tex for drawing
    def getMesh(self, tile, options):
        if tile==self.currenttile:
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
            texno=self.texcache.get(texture, True, False, flags&1)
            self.meshcache.append((base, len(v), texno, flags/2))
        if __debug__: print "%6.3f time in getMesh" % (time.clock()-clock)
        self.valid=False	# new geometry -> need to update OpenGL
        self.currenttile=tile
        return self.meshcache


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
            if flags>1: continue	# not interested in overlays
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
    newfile=join(newpath,basename(path)[:-4]+path[-4:].lower())
    w=file(newfile, 'wU')
    w.write(header)
    for line in h:
        w.write(line.rstrip()+'\n')
    w.close()
    h.close()
    return newfile
