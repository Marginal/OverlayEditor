from math import cos, floor, pi
from md5 import md5
from os import listdir, mkdir, popen3, popen4, rename, unlink
from os.path import abspath, curdir, dirname, exists, expanduser, isdir, join, pardir, sep
from struct import pack, unpack
from sys import platform, maxint
from tempfile import gettempdir
import types

import wx

from version import appname, appversion

onedeg=1852*60	# 1 degree of longitude at equator (60nm) [m]
d2r=pi/180.0
resolution=8*65535
minres=1.0/resolution
maxres=1-minres

if platform=='win32':
    dsftool=join(curdir,'win32','DSFTool.exe')
elif platform.lower().startswith('linux'):
    dsftool=join(curdir,'linux','DSFTool')
else:	# Mac
    dsftool=join(curdir,'MacOS','DSFTool')


def round2res(x):
    i=floor(x)
    return i+round((x-i)*resolution,0)*minres


class Object:

    def __init__(self, name, lat, lon, hdg, height=None):
        self.name=name
        self.lat=lat
        self.lon=lon
        self.hdg=hdg
        self.height=height

    def clone(self):
        return Object(self.name, self.lat, self.lon, self.hdg, self.height)

    def __str__(self):
        return '<"%s" %11.6f %10.6f %d %s>' % (
            self.name, self.lat, self.lon, self.hdg, self.height)
    

class Polygon:
    EXCLUDE='Exclude:'
    FACADE='.fac'
    FOREST='.for'
    POLYGON='.pol'

    EXCLUDE_NAME={'sim/exclude_bch': 'Exclude: Beaches',
                  'sim/exclude_pol': 'Exclude: Draped',
                  'sim/exclude_fac': 'Exclude: Facades',
                  'sim/exclude_for': 'Exclude: Forests',
                  'sim/exclude_obj': 'Exclude: Objects',
                  'sim/exclude_net': 'Exclude: Roads',
                  'sim/exclude_str': 'Exclude: Strings'}

    def __init__(self, name, kind, param, nodes):
        self.name=name
        self.lat=self.lon=0	# For centreing etc
        self.kind=kind		# enum, or extension if unknown type
        self.param=param
        self.nodes=nodes	# [[(lon,lat,...)]]
        self.points=[]		# list of 1st winding in world space (x,y,z)
        self.quads=[]		# list of points (x,y,z,s,t)
        self.roof=[]		# list of points (x,y,z,s,t)

    def clone(self):
        return Polygon(self.name, self.kind, self.param,
                       [list(w) for w in self.nodes])
        
    def __str__(self):
        return '<"%s" %d %f %s>' % (self.name,self.kind,self.param,self.points)


# Takes a DSF path name.
# Returns (properties, placements, polygons, mesh), where:
#   properties = [(property, string value)]
#   placements
#   polygons
#   mesh = [(texture name, flags, [point], [st])], where
#     flags=patch flags: 1=hard, 2=overlay
#     point = [x, y, z]
#     st = [s, t]
# Exceptions:
#   IOError, IndexError
#
# Any vector data in the DSF file is ignored.
# If terrains is defined,  assume loading terrain and discard non-mesh data
# If terrains not defined, assume looking for an overlay DSF
#
def readDSF(path, terrains={}):
    baddsf=(0, "Invalid DSF file", path)

    h=file(path, 'rb')
    if h.read(8)!='XPLNEDSF' or unpack('<I',h.read(4))!=(1,) or h.read(4)!='DAEH':
        raise IOError, baddsf
    (l,)=unpack('<I', h.read(4))
    headend=h.tell()+l-8
    if h.read(4)!='PORP':
        raise IOError, baddsf
    (l,)=unpack('<I', h.read(4))
    properties=[]
    c=h.read(l-9).split('\0')
    h.read(1)
    overlay=0
    for i in range(0, len(c)-1, 2):
        if c[i]=='sim/overlay': overlay=int(c[i+1])
        elif c[i]=='sim/south': centrelat=int(c[i+1])+0.5
        elif c[i]=='sim/west': centrelon=int(c[i+1])+0.5
        properties.append((c[i],c[i+1]))
    h.seek(headend)
    if not overlay and not terrains:
        # Not an Overlay DSF - bail early
        h.close()
        return (properties, [], [], [])

    # Definitions Atom
    if h.read(4)!='NFED':
        raise IOError, baddsf
    (l,)=unpack('<I', h.read(4))
    defnend=h.tell()+l-8
    terrain=objects=polygons=network=[]
    while h.tell()<defnend:
        c=h.read(4)
        (l,)=unpack('<I', h.read(4))
        if l==8:
            pass	# empty
        elif c=='TRET':
            terrain=h.read(l-9).replace('\\','/').replace(':','/').split('\0')
            h.read(1)
        elif c=='TJBO':
            objects=h.read(l-9).replace('\\','/').replace(':','/').split('\0')
            h.read(1)
        elif c=='YLOP':
            polygons=h.read(l-9).replace('\\','/').replace(':','/').split('\0')
            h.read(1)
        elif c=='WTEN':
            networks=h.read(l-9).replace('\\','/').replace(':','/').split('\0')
            h.read(1)
        else:
            h.seek(l-8, 1)

    polykind=[]
    for i in range(len(polygons)):
        polykind.append(polygons[i][-4:].lower())
    
    # Geodata Atom
    if h.read(4)!='DOEG':
        raise IOError, baddsf
    (l,)=unpack('<I', h.read(4))
    geodend=h.tell()+l-8
    pool=[]
    scal=[]
    while h.tell()<geodend:
        c=h.read(4)
        (l,)=unpack('<I', h.read(4))
        if c=='LOOP':
            thispool=[]
            (n,)=unpack('<I', h.read(4))
            (p,)=unpack('<B', h.read(1))
            for i in range(p):
                thisplane=[]
                (e,)=unpack('<B', h.read(1))
                if e==0 or e==1:
                    last=0
                    for j in range(n):
                        (d,)=unpack('<H', h.read(2))
                        if e==1: d=(last+d)&65535
                        thisplane.append(d)
                        last=d
                elif e==2 or e==3:
                    last=0
                    while(len(thisplane))<n:
                        (r,)=unpack('<B', h.read(1))
                        if (r&128):
                            (d,)=unpack('<H', h.read(2))
                            for j in range(r&127):
                                if e==3:
                                    thisplane.append((last+d)&65535)
                                    last=(last+d)&65535
                                else:
                                    thisplane.append(d)
                        else:
                            for j in range(r):
                                (d,)=unpack('<H', h.read(2))
                                if e==3: d=(last+d)&65535
                                thisplane.append(d)
                                last=d
                else:
                    raise IOError, baddsf
                thispool.append(thisplane)  
            pool.append(thispool)
        elif c=='LACS':
            thisscal=[]
            for i in range(0, l-8, 8):
                d=unpack('<2f', h.read(8))
                thisscal.append(d)
            scal.append(thisscal)
        else:
            h.seek(l-8, 1)
    
    # Rescale pool and transform to one list per entry
    if len(scal)!=len(pool): raise(IOError)
    newpool=[]
    for i in range(len(pool)):
        curpool=pool[i]
        n=len(curpool[0])
        newpool=[[] for j in range(n)]
        for plane in range(len(curpool)):
            (scale,offset)=scal[i][plane]
            scale=scale/65535
            for j in range(n):
                newpool[j].append(curpool[plane][j]*scale+offset)
        pool[i]=newpool

    # Commands Atom
    if h.read(4)!='SDMC':
        raise IOError, baddsf
    (l,)=unpack('<I', h.read(4))
    cmdsend=h.tell()+l-8
    curpool=0
    idx=0
    near=0
    far=-1
    flags=0	# 1=physical, 2=overlay
    placements=[]
    polyplace=[]
    mesh=[]
    curter='terrain_Water'
    curpatch=[]
    tercache={'terrain_Water':(join('Resources','Sea01.png'), 0, 0.001,0.001)}
    while h.tell()<cmdsend:
        (c,)=unpack('<B', h.read(1))
        if c==1:	# Coordinate Pool Select
            (curpool,)=unpack('<H', h.read(2))
            
        elif c==2:	# Junction Offset Select
            h.read(4)	# not implemented
            
        elif c==3:	# Set Definition
            (idx,)=unpack('<B', h.read(1))
            
        elif c==4:	# Set Definition
            (idx,)=unpack('<H', h.read(2))
            
        elif c==5:	# Set Definition
            (idx,)=unpack('<I', h.read(4))
            
        elif c==6:	# Set Road Subtype
            h.read(1)	# not implemented
            
        elif c==7:	# Object
            (d,)=unpack('<H', h.read(2))
            p=pool[curpool][d]
            if not terrains:
                placements.append(Object(objects[idx],
                                         p[1], p[0], int(round(p[2],0))))
                
        elif c==8:	# Object Range
            (first,last)=unpack('<HH', h.read(4))
            if not terrains:
                for d in range(first, last):
                    p=pool[curpool][d]
                    placements.append(Object(objects[idx],
                                             p[1], p[0], int(round(p[2],0))))
                    
        elif c==9:	# Network Chain
            (l,)=unpack('<B', h.read(1))
            h.read(l*2)	# not implemented
            
        elif c==10:	# Network Chain Range
            h.read(4)	# not implemented
            
        elif c==11:	# Network Chain
            (l,)=unpack('<B', h.read(1))
            h.read(l*4)	# not implemented
            
        elif c==12:	# Polygon
            (param,l)=unpack('<HB', h.read(3))
            if terrains or l<2:
                h.read(l*2)
                continue
            winding=[]
            for i in range(l):
                (d,)=unpack('<H', h.read(2))
                p=pool[curpool][d]
                winding.append(tuple(p))
            polyplace.append(Polygon(polygons[idx], polykind[idx],
                                     param, [winding]))
            
        elif c==13:	# Polygon Range (DSF2Text uses this one)
            (param,first,last)=unpack('<HHH', h.read(6))
            if terrains or last-first<2: continue
            winding=[]
            for d in range(first, last):
                p=pool[curpool][d]
                winding.append(tuple(p))
            polyplace.append(Polygon(polygons[idx], polykind[idx],
                                     param, [winding]))
            
        elif c==14:	# Nested Polygon
            (param,n)=unpack('<HB', h.read(3))
            windings=[]
            for i in range(n):
                (l,)=unpack('<B', h.read(1))
                winding=[]
                for j in range(l):
                    (d,)=unpack('<H', h.read(2))
                    p=pool[curpool][d]
                    winding.append(tuple(p))
                windings.append(winding)
            if not terrains and n>0 and len(windings[0])>=2:
                polyplace.append(Polygon(polygons[idx], polykind[idx],
                                         param, windings))
                
        elif c==15:	# Nested Polygon Range (DSF2Text uses this one too)
            (param,n)=unpack('<HB', h.read(3))
            i=[]
            for j in range(n+1):
                (l,)=unpack('<H', h.read(2))
                i.append(l)
            if terrains: continue
            windings=[]
            for j in range(n):
                winding=[]
                for d in range(i[j],i[j+1]):
                    p=pool[curpool][d]
                    winding.append(tuple(p))
                windings.append(winding)
            polyplace.append(Polygon(polygons[idx], polykind[idx],
                                     param, windings))
            
        elif c==16:	# Terrain Patch
            if curpatch:
                newmesh=makemesh(flags,path,curter,curpatch,centrelat,centrelon,terrains,tercache)
                if newmesh: mesh.append(newmesh)
            curter=terrain[idx]
            curpatch=[]
            
        elif c==17:	# Terrain Patch w/ flags
            if curpatch:
                newmesh=makemesh(flags,path,curter,curpatch,centrelat,centrelon,terrains,tercache)
                if newmesh: mesh.append(newmesh)
            (flags,)=unpack('<B', h.read(1))
            curter=terrain[idx]
            curpatch=[]
            
        elif c==18:	# Terrain Patch w/ flags & LOD
            if curpatch:
                newmesh=makemesh(flags,path,curter,curpatch,centrelat,centrelon,terrains,tercache)
                if newmesh: mesh.append(newmesh)
            (flags,near,far)=unpack('<Bff', h.read(9))
            curter=terrain[idx]
            curpatch=[]

        elif c==23:	# Patch Triangle
            (l,)=unpack('<B', h.read(1))
            points=[]
            for i in range(l):
                (d,)=unpack('<H', h.read(2))
                points.append(pool[curpool][d])
            curpatch.extend(points)
            
        elif c==24:	# Patch Triangle - cross-pool
            (l,)=unpack('<B', h.read(1))
            points=[]
            for i in range(l):
                (p,d)=unpack('<HH', h.read(4))
                points.append(pool[p][d])
            curpatch.extend(points)

        elif c==25:	# Patch Triangle Range
            (first,last)=unpack('<HH', h.read(4))
            curpatch.extend(pool[curpool][first:last])
            
        #elif c==26:	# Patch Triangle Strip (not used by DSF2Text)
        #elif c==27:
        #elif c==28:
        
        elif c==29:	# Patch Triangle Fan
            (l,)=unpack('<B', h.read(1))
            points=[]
            for i in range(l):
                (d,)=unpack('<H', h.read(2))
                points.append(pool[curpool][d])
            curpatch.extend(meshfan(points))
            
        elif c==30:	# Patch Triangle Fan - cross-pool
            (l,)=unpack('<B', h.read(1))
            points=[]
            for i in range(l):
                (p,d)=unpack('<HH', h.read(4))
                points.append(pool[p][d])
            curpatch.extend(meshfan(points))

        elif c==31:	# Patch Triangle Fan Range
            (first,last)=unpack('<HH', h.read(4))
            curpatch.extend(meshfan(pool[curpool][first:last]))

        elif c==32:	# Comment
            (l,)=unpack('<B', h.read(1))
            h.read(l)
            
        elif c==33:	# Comment
            (l,)=unpack('<H', h.read(2))
            h.read(l)
            
        elif c==34:	# Comment
            (l,)=unpack('<I', h.read(4))
            h.read(l)
            
        else:
            raise IOError, (c, "Unrecognised command (%d)" % c, path)

    # Last one
    if curpatch:
        newmesh=makemesh(flags,path,curter,curpatch,centrelat,centrelon,terrains,tercache)
        if newmesh: mesh.append(newmesh)
    
    h.close()
    return (properties, placements, polyplace, mesh)

def meshfan(points):
    tris=[]
    for i in range(1,len(points)-1):
        tris.append(points[0])
        tris.append(points[i])
        tris.append(points[i+1])
    return tris

def makemesh(flags,path, ter, patch, centrelat, centrelon, terrains, tercache):
    # Get terrain info
    if ter in tercache:
        (texture, angle, xscale, zscale)=tercache[ter]
    else:
        texture=None
        angle=0
        xscale=zscale=0
        try:
            if ter in terrains:	# Library terrain
                phys=terrains[ter]
            else:		# Package-specific terrain
                phys=abspath(join(dirname(path), pardir, pardir, ter))
            h=file(phys, 'rU')
            if not (h.readline().strip() in ['I','A'] and
                    h.readline().strip()=='800' and
                    h.readline().strip()=='TERRAIN'):
                raise IOError
            for line in h:
                line=line.strip()
                c=line.split()
                if not c: continue
                if c[0] in ['BASE_TEX', 'BASE_TEX_NOWRAP']:
                    texture=line[len(c[0]):].strip()
                    texture=texture.replace(':', sep)
                    texture=texture.replace('/', sep)
                    texture=abspath(join(dirname(phys), texture))
                elif c[0]=='PROJECTED':
                    xscale=1/float(c[1])
                    zscale=1/float(c[2])
                elif c[0]=='PROJECT_ANGLE':
                    if float(c[1])==0 and float(c[2])==1 and float(c[3])==0:
                        # no idea what rotation about other axes means
                        angle=int(float(c[4]))
            h.close()
        except:
            if __debug__: print 'Failed to load terrain "%s"' % ter
        tercache[ter]=(texture, angle, xscale, zscale)

    # Make mesh
    v=[]
    t=[]
    if flags&1 and (len(patch[0])<7 or xscale):	# hard and no st coords
        for p in patch:
            x=(p[0]-centrelon)*onedeg*cos(d2r*p[1])
            z=(centrelat-p[1])*onedeg
            v.append([x, p[2], z])
            if angle==90:
                t.append([z*zscale, x*xscale])
            elif angle==180:
                t.append([-x*xscale, z*zscale])
            elif angle==270:
                t.append([-z*zscale, -x*xscale])
            else: # angle==0 or not square
                t.append([x*xscale, -z*zscale])
    elif not (len(patch[0])<7 or xscale):	# st coords but not projected
        for p in patch:
            v.append([(p[0]-centrelon)*onedeg*cos(d2r*p[1]),
                      p[2], (centrelat-p[1])*onedeg])
            t.append([p[5],p[6]])
    else:
        return None
    return (texture,flags,v,t)


def writeDSF(dsfdir, key, objects, polygons):
    (south,west)=key
    tiledir=join(dsfdir, "%+02d0%+03d0" % (int(south/10), int(west/10)))
    if not isdir(tiledir): mkdir(tiledir)
    tilename=join(tiledir, "%+03d%+04d" % (south,west))
    if exists(tilename+'.dsf'):
        if exists(tilename+'.dsf.bak'): unlink(tilename+'.dsf.bak')
        rename(tilename+'.dsf', tilename+'.dsf.bak')
    if exists(tilename+'.DSF'):
        if exists(tilename+'.DSF.BAK'): unlink(tilename+'.DSF.BAK')
        rename(tilename+'.DSF', tilename+'.DSF.BAK')
    if not (objects or polygons): return

    tmp=join(gettempdir(), "%+03d%+04d.txt" % (south,west))
    h=file(tmp, 'wt')
    h.write('I\n800\nDSF2TEXT\n\n')
    h.write('PROPERTY\tsim/planet\tearth\n')
    h.write('PROPERTY\tsim/overlay\t1\n')
    h.write('PROPERTY\tsim/require_object\t1/0\n')
    h.write('PROPERTY\tsim/require_facade\t1/0\n')
    h.write('PROPERTY\tsim/creation_agent\t%s %4.2f\n' % (appname, appversion))
    for poly in polygons:
        if poly.kind==Polygon.EXCLUDE:
            for k in Polygon.EXCLUDE_NAME.keys():
                if Polygon.EXCLUDE_NAME[k]==poly.name:
                    minlat=minlon=maxint
                    maxlat=maxlon=-maxint
                    for n in poly.nodes[0]:
                        minlon=min(minlon,n[0])
                        maxlon=max(maxlon,n[0])
                        minlat=min(minlat,n[1])
                        maxlat=max(maxlat,n[1])
                    h.write('PROPERTY\t%s\t%11.6f/%10.6f/%11.6f/%10.6f\n' % (
                        k, minlon, minlat, maxlon, maxlat))
                    break
    h.write('PROPERTY\tsim/west\t%d\n' %  west)
    h.write('PROPERTY\tsim/east\t%d\n' %  (west+1))
    h.write('PROPERTY\tsim/north\t%d\n' %  (south+1))
    h.write('PROPERTY\tsim/south\t%d\n' %  south)
    h.write('\n')

    objdefs=[]
    for obj in objects:
        if not obj.name in objdefs:
            objdefs.append(obj.name)
            h.write('OBJECT_DEF\t%s\n' % obj.name)
    if objdefs: h.write('\n')

    polydefs=[]
    for poly in polygons:
        if poly.kind!=Polygon.EXCLUDE:
            if not poly.name in polydefs:
                polydefs.append(poly.name)
                h.write('POLYGON_DEF\t%s\n' % poly.name)
    if polydefs: h.write('\n')

    for obj in objects:
        h.write('OBJECT\t\t%d %12.7f %12.7f %3.0f\n' % (
            objdefs.index(obj.name), min(west+1, obj.lon+minres/2), min(south+1, obj.lat+minres/2), obj.hdg))
    if objects: h.write('\n')
    
    for poly in polygons:
        if poly.kind==Polygon.EXCLUDE:
            continue
        h.write('BEGIN_POLYGON\t%d %d %d\n' % (
            polydefs.index(poly.name), poly.param, len(poly.nodes[0][0])))
            #polydefs.index(poly.name), poly.param, 2))
        for w in poly.nodes:
            h.write('BEGIN_WINDING\n')
            for p in w:
                h.write('POLYGON_POINT\t')
                for n in range(len(p)):
                    if poly.param==65535 and len(p)-n<=2:
                        h.write('%12.7f ' % p[n]) # don't adjust UV coords
                    elif n&1:	# lat
                        h.write('%12.7f ' % min(south+1, p[n]+minres/2))
                    else:	# lon
                        h.write('%12.7f ' % min(west+1, p[n]+minres/2))
                h.write('\n')
            h.write('END_WINDING\n')
        h.write('END_POLYGON\n')
    if polydefs: h.write('\n')
    
    h.close()
    if platform.lower().startswith('linux') and not isdir(join(expanduser('~'), '.wine')):
        # Let Wine initialise font cache etc on first run
        progress=wx.ProgressDialog('Setting up Wine', 'Please wait')
        (i,o,e)=popen3('wine --version')
        i.close()
        o.read()
        e.read()
        o.close()
        e.close()
        progress.Destroy()
    if platform=='win32':
        quote='"'
    else:
        quote="'"
    cmds='%s -text2dsf %s%s%s %s%s.dsf%s' % (dsftool, quote, tmp, quote, quote, tilename, quote)
    if platform=='win32' and type(cmds)==types.UnicodeType:
        # commands must be MBCS encoded
        cmds=cmds.encode("mbcs")
    (i,o,e)=popen3(cmds)
    i.close()
    o.read()
    err=e.read()
    o.close()
    e.close()
    #unlink(tmp)
    if err or not exists(tilename+'.dsf'):
        if exists(tilename+'.dsf.bak'):
            rename(tilename+'.dsf.bak', tilename+'.dsf')
        elif exists(tilename+'.DSF.BAK'):
            rename(tilename+'.DSF.BAK', tilename+'.DSF')
        raise IOError, (0, err.strip().replace('\n', ', '))
