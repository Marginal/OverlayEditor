from math import cos, pi
from md5 import md5
from os import listdir, mkdir, popen3, rename, unlink
from os.path import abspath, curdir, dirname, exists, isdir, join, sep
from struct import pack, unpack
from sys import platform, maxint
from tempfile import gettempdir

from version import appname, appversion

onedeg=1852*60	# 1 degree of longitude at equator (60nm) [m]
d2r=pi/180.0

if platform=='win32':
    dsftool=join(curdir,'win32','DSFTool.exe')
elif platform.lower().startswith('linux'):
    dsftool=join(curdir,'linux','DSFTool')
else:	# Mac
    dsftool=join(curdir,'MacOS','DSFTool')

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

    EXCLUDE_NAME={'sim/exclude_obj': 'Exclude: Objects',
                  'sim/exclude_fac': 'Exclude: Facades',
                  'sim/exclude_for': 'Exclude: Forests',
                  'sim/exclude_bch': 'Exclude: Beaches',
                  'sim/exclude_net': 'Exclude: Roads'}

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
#   mesh = [(texture name, [point], [st])], where
#     point = [x, y, z]
#     st = [s, t]
# Exceptions:
#   IOError, IndexError
#
# Any vector data in the DSF file is ignored.
# If terrains is defined,  assume loading terrain and discard poly data
# If terrains not defined, assume looking for an overlay DSF

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
            terrain=h.read(l-9).split('\0')
            h.read(1)
        elif c=='TJBO':
            objects=h.read(l-9).split('\0')
            h.read(1)
        elif c=='YLOP':
            polygons=h.read(l-9).split('\0')
            h.read(1)
        elif c=='WTEN':
            networks=h.read(l-9).split('\0')
            h.read(1)
        else:
            h.seek(l-8, 1)

    for i in range(len(objects)):
        objects[i]=objects[i][:-4]

    polykind=[]
    for i in range(len(polygons)):
        polykind.append(polygons[i][-4:].lower())
        polygons[i]=polygons[i][:-4]
    
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
        if c==1:
            (curpool,)=unpack('<H', h.read(2))
        elif c==2:
            h.read(4)
        elif c==3:
            (idx,)=unpack('<B', h.read(1))
        elif c==4:
            (idx,)=unpack('<H', h.read(2))
        elif c==5:
            (idx,)=unpack('<I', h.read(4))
        elif c==6:
            h.read(1)
        elif c==7:
            (d,)=unpack('<H', h.read(2))
            p=pool[curpool][d]
            placements.append(Object(objects[idx], p[1], p[0], int(p[2])))
        elif c==8:
            (first,last)=unpack('<HH', h.read(4))
            for d in range(first, last):
                p=pool[curpool][d]
                placements.append(Object(objects[idx], p[1], p[0], int(p[2])))
        elif c==9:
            # not implemented
            (l,)=unpack('<B', h.read(1))
            h.read(l*2)
        elif c==10:
            # not implemented
            h.read(4)
        elif c==11:
            # not implemented
            (l,)=unpack('<B', h.read(1))
            h.read(l*4)
        elif c==12:
            (param,l)=unpack('<HB', h.read(3))
            if terrains or l<2:
                h.read(l*2)
                continue
            winding=[]
            for i in range(l):
                (d,)=unpack('<H', h.read(2))
                p=pool[curpool][d]
                winding.append(tuple(p))
            polyplace.append(Polygon(polygons[idx], polykind[idx], param, [winding]))
        elif c==13:	# DSF2Text uses this
            (param,first,last)=unpack('<HHH', h.read(6))
            if terrains or last-first<2: continue
            winding=[]
            for d in range(first, last):
                p=pool[curpool][d]
                winding.append(tuple(p))
            polyplace.append(Polygon(polygons[idx], polykind[idx], param, [winding]))
        elif c==14:
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
                polyplace.append(Polygon(polygons[idx], polykind[idx], param, windings))
        elif c==15:
            (param,n)=unpack('<HB', h.read(3))
            i=[]
            for j in range(n):
                (l,)=unpack('<H', h.read(2))
                i.append(l)
            if terrains: continue
            windings=[]
            for j in range(len(i)-1):
                winding=[]
                for d in range(i[j],i[j+1]):
                    p=pool[curpool][d]
                    winding.append(tuple(p))
                windings.append(winding)
            polyplace.append(Polygon(polygons[idx], polykind[idx], param, windings))
        elif c==16:
            if curpatch:
                mesh.append(makemesh(curter,curpatch,centrelat,centrelon,terrains,tercache))
            curter=terrain[idx]
            curpatch=[]
        elif c==17:
            (flags,)=unpack('<B', h.read(1))
            if curpatch:
                mesh.append(makemesh(curter,curpatch,centrelat,centrelon,terrains,tercache))
            curter=terrain[idx]
            curpatch=[]
        elif c==18:
            (flags,near,far)=unpack('<Bff', h.read(9))
            if curpatch:
                mesh.append(makemesh(curter,curpatch,centrelat,centrelon,terrains,tercache))
            curter=terrain[idx]
            curpatch=[]

        elif c==23:
            (l,)=unpack('<B', h.read(1))
            if flags&1:
                points=[]
                for i in range(l):
                    (d,)=unpack('<H', h.read(2))
                    points.append(pool[curpool][d])
                curpatch.extend(points)
            else:
                h.read(2*l)
            
        elif c==24:
            (l,)=unpack('<B', h.read(1))
            if flags&1:
                points=[]
                for i in range(l):
                    (p,d)=unpack('<HH', h.read(4))
                    points.append(pool[p][d])
                curpatch.extend(points)
            else:
                h.read(4*l)

        elif c==25:
            (first,last)=unpack('<HH', h.read(4))
            if flags&1:
                curpatch.extend(pool[curpool][first:last])
            
        #elif c==26:
        #elif c==27:
        #elif c==28:
        elif c==29:
            (l,)=unpack('<B', h.read(1))
            if flags&1:
                points=[]
                for i in range(l):
                    (d,)=unpack('<H', h.read(2))
                    points.append(pool[curpool][d])
                curpatch.extend(meshfan(points))
            else:
                h.read(2*l)
            
        elif c==30:
            (l,)=unpack('<B', h.read(1))
            if flags&1:
                points=[]
                for i in range(l):
                    (p,d)=unpack('<HH', h.read(4))
                    points.append(pool[p][d])
                curpatch.extend(meshfan(points))
            else:
                h.read(4*l)

        elif c==31:
            (first,last)=unpack('<HH', h.read(4))
            if flags&1:
                curpatch.extend(meshfan(pool[curpool][first:last]))

        elif c==32:
            (l,)=unpack('<B', h.read(1))
            h.read(l)
        elif c==33:
            (l,)=unpack('<H', h.read(2))
            h.read(l)
        elif c==34:
            (l,)=unpack('<I', h.read(4))
            h.read(l)
        else:
            raise IOError, (c, "Unrecognised command", path)

    # Last one
    if curpatch:
        mesh.append(makemesh(curter,curpatch,centrelat,centrelon,terrains,tercache))
    
    h.close()
    return (properties, placements, polyplace, mesh)

def meshfan(points):
    tris=[]
    for i in range(1,len(points)-1):
        tris.append(points[0])
        tris.append(points[i])
        tris.append(points[i+1])
    return tris

def makemesh(ter, patch, centrelat, centrelon, terrains, tercache):
    # Get terrain info
    if ter in tercache:
        (texture, angle, xscale, zscale)=tercache[ter]
    else:
        texture=None
        angle=0
        xscale=zscale=0.001
        try:
            h=file(terrains[ter], 'rU')
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
                    texture=abspath(join(dirname(terrains[ter]),texture))
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
        tercache[ter]=(texture, angle, xscale, zscale)

    # Make mesh
    v=[]
    t=[]
    if len(patch[0])<7:	# no st coords (all? Laminar hard scenery)
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
    return (texture,v,t)


def writeDSF(dsfdir, key, objects, polygons):
    if not (objects or polygons): return
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
            h.write('OBJECT_DEF\t%s.obj\n' % obj.name)
    if objdefs: h.write('\n')

    polydefs=[]
    for poly in polygons:
        if poly.kind!=Polygon.EXCLUDE:
            name=poly.name+poly.kind
            if not name in polydefs:
                polydefs.append(name)
                h.write('POLYGON_DEF\t%s\n' % name)
    if polydefs: h.write('\n')

    for obj in objects:
        h.write('OBJECT\t\t%d %11.6f %10.6f %3.0f\n' % (
            objdefs.index(obj.name), obj.lon, obj.lat, obj.hdg))
    if objdefs: h.write('\n')
    
    for poly in polygons:
        if poly.kind==Polygon.EXCLUDE:
            continue
        name=poly.name+poly.kind
        # XXX h.write('BEGIN_POLYGON\t%d %d %d\n' % (
        #    polydefs.index(name), poly.param, len(poly.nodes[0][0])))
        h.write('BEGIN_POLYGON\t%d %d %d\n' % (
            polydefs.index(name), poly.param, 2))
        for w in poly.nodes:
            h.write('BEGIN_WINDING\n')
            for p in w:
                h.write('POLYGON_POINT\t')
                # XXX for n in p:
                for n in [p[0], p[1]]:
                    h.write('%11.6f ' % n)
                h.write('\n')
            h.write('END_WINDING\n')
        h.write('END_POLYGON\n')
    if polydefs: h.write('\n')
    
    h.close()
    (i,o,e)=popen3('%s -text2dsf "%s" "%s.dsf"' % (dsftool, tmp, tilename))
    i.close()
    o.read()
    err=e.read()
    o.close()
    e.close()
    #unlink(tmp)
    if err:
        raise IOError, (0, err.strip().replace('\n', ', '))

    
def NEWwriteDSF(dsfdir, key, objects, polygons):
    if not (objects or polygons): return
    (south,west)=key
    tiledir=join(dsfdir, "%+02d0%+03d0" % (int(south/10), int(west/10)))
    if not isdir(tiledir): mkdir(tiledir)
    props=('sim/planet\0earth\0'+
           'sim/overlay\01\0'+
           'sim/require_object\01/0\0'+
           'sim/require_facade\01/0\0'+
           'sim/creation_agent\0%s %4.2f\0' % (appname, appversion))
    objt=[]
    objs=[]
    for obj in objects:
        name=obj.name+'.obj'
        if name in objt:
            idx=objt.index(name)
        else:
            idx=len(objt)
            objt.append(name)
            objs.append([])
        objs[idx].append((obj.lat,obj.lon,obj.hdg))
    objt='\0'.join(objt)+'\0'
    objt='TJBO'+pack('<I', len(objt)+8)+objt

    poly=[]
    facs=[]
    for p in polygons:
        if p.name.startswith('Exclude:'):
            for k in Polygon.EXCLUDE_NAME.keys():
                if Polygon.EXCLUDE_NAME[k]==p.name:
                    minlat=minlon=maxint
                    maxlat=maxlon=-maxint
                    for n in p.nodes:
                        minlat=min(minlat,n[0])
                        maxlat=max(maxlat,n[0])
                        minlon=min(minlon,n[1])
                        maxlon=max(maxlon,n[1])
                    props+='%s\0%10.6f/%11.6f/%10.6f/%11.6f\0' % (
                        k, minlon, minlat, maxlon, maxlat)
                    break
            continue
        name=p.name+'.fac'
        if name in poly:
            idx=poly.index(name)
        else:
            idx=len(poly)
            poly.append(name)
            facs.append([])
        facs[idx].append((p.lat,p.lon))
    poly='\0'.join(poly)+'\0'
    poly='YLOP'+pack('<I', len(poly)+8)+poly

    props+=('sim/west\0%d\0'  %  west +	# last for DSFTool compatibility
            'sim/east\0%d\0'  % (west+1) +
            'sim/north\0%d\0' % (south+1) +
            'sim/south\0%d\0' %  south)
    props='PORP'+pack('<I', len(props)+8)+props
    head='DAEH'+pack('<I', len(props)+8)+props
    
    defn='TRET\x08\0\0\0'+objt+poly+'WTEN\x08\0\0\0'
    defn='NFED'+pack('<I', len(defn)+8)+defn

    opool=''
    oscal=''

    if opool:
        opool='LOOP'+pack('<I', len(opool)+8)+opool
        oscal='LACS'+pack('<Iffffff', 32, 65535, west, 360, 0)+oscal
    if ppool:
        ppool='LOOP'+pack('<I', len(ppool)+8)+ppool
        pscal='LACS'+pack('<Iffff', 24)+pscal
    geod=opool+oscal+ppool+pscal	#+'23OP\x08\0\0\023CS\x08\0\0\0'
    geod='DOEG'+pack('<I', len(geod)+8)+geod
    
    contents='XPLNEDSF\1\0\0\0'+head+defn+geod+cmds
    contents+=md5(contents).digest()

    tilename=join(tiledir, "%+03d%+04d" % (south,west))
    if exists(tilename+'.dsf'):
        if exists(tilename+'.dsf.bak'): unlink(tilename+'.dsf.bak')
        rename(tilename+'.dsf', tilename+'.dsf.bak')
    if exists(tilename+'.DSF'):
        if exists(tilename+'.DSF.BAK'): unlink(tilename+'.DSF.BAK')
        rename(tilename+'.DSF', tilename+'.DSF.BAK')
    h=file(tilename, 'wb')
    h.write(contents)
    h.close()
