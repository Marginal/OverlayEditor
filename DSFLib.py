from math import cos, floor, pi, radians
from os import mkdir, popen3, rename, unlink, SEEK_CUR, SEEK_END
from os.path import basename, curdir, dirname, exists, expanduser, isdir, join, normpath, pardir, sep
from struct import unpack
from sys import platform, maxint
from tempfile import gettempdir
import types
import time
import py7zlib
from cStringIO import StringIO
if __debug__:
    from traceback import print_exc

from clutter import PolygonFactory, Object, Polygon, Draped, Exclude, Network, minres, minhdg
from version import appname, appversion

onedeg=1852*60	# 1 degree of longitude at equator (60nm) [m]

if platform=='win32':
    dsftool=join(curdir,'win32','DSFTool.exe')
elif platform.startswith('linux'):
    dsftool=join(curdir,'linux','DSFTool')
else:	# Mac
    dsftool=join(curdir,'MacOS','DSFTool')


# Takes a DSF path name.
# Returns (lat, lon, placements, nets, mesh), where:
#   placements = [Clutter]
#   roads= [(type, [lon, lat, elv, ...])]
#   mesh = [(texture name, flags, [point], [st])], where
#     flags=patch flags: 1=hard, 2=overlay
#     point = [x, y, z]
#     st = [s, t]
# Exceptions:
#   IOError, IndexError
#
# If terrains is defined,  assume loading terrain and discard non-mesh data
# If terrains not defined, assume looking for an overlay DSF
#
def readDSF(path, wantoverlay, wantnetwork, terrains={}):
    assert wantoverlay or terrains
    baddsf=(0, "Invalid DSF file", path)

    h=file(path, 'rb')
    sig=h.read(8)
    if sig.startswith('7z\xBC\xAF\x27\x1C'):	# X-Plane 10 compressed
        if __debug__: clock=time.clock()
        h.seek(0)
        data=py7zlib.Archive7z(h).getmember(basename(path)).read()
        h.close()
        h=StringIO(data)
        sig=h.read(8)
        if __debug__: print "%6.3f time in decompression" % (time.clock()-clock)
    if sig!='XPLNEDSF' or unpack('<I',h.read(4))!=(1,):
        raise IOError, baddsf

    # scan for contents
    table={}
    h.seek(-16,SEEK_END)	# stop at MD5 checksum
    end=h.tell()
    p=12
    while p<end:
        h.seek(p)
        d=h.read(8)
        (c,l)=unpack('<4sI', d)
        table[c]=p+4
        p+=l
    if __debug__: print path, table
    if not 'DAEH' in table or not 'NFED' in table or not 'DOEG' in table or not 'SDMC' in table:
        raise IOError, baddsf

    # header
    h.seek(table['DAEH'])
    (l,)=unpack('<I', h.read(4))
    headend=h.tell()+l-8
    if h.read(4)!='PORP':
        raise IOError, baddsf
    (l,)=unpack('<I', h.read(4))
    placements=[]
    nets=[]
    mesh=[]
    c=h.read(l-9).split('\0')
    h.read(1)
    overlay=0
    for i in range(0, len(c)-1, 2):
        if c[i]=='sim/overlay': overlay=int(c[i+1])
        elif c[i]=='sim/south': south=int(c[i+1])
        elif c[i]=='sim/west': west=int(c[i+1])
        elif c[i] in Exclude.NAMES:
            if ',' in c[i+1]:	# Fix for FS2XPlane 0.99
                v=[float(x) for x in c[i+1].split(',')]
            else:
                v=[float(x) for x in c[i+1].split('/')]
            placements.append(Exclude(Exclude.NAMES[c[i]], 0,
                                      [[(v[0],v[1]),(v[2],v[1]),
                                        (v[2],v[3]),(v[0],v[3])]]))
    if wantoverlay and not overlay:
        # Not an Overlay DSF - bail early
        h.close()
        raise IOError (0, "%s is not an overlay." % basename(path))
    if not wantoverlay and overlay:
        # only interested in mesh data - bail early
        h.close()
        raise IOError (0, "%s is an overlay." % basename(path))
        
    h.seek(headend)

    # Definitions Atom
    h.seek(table['NFED'])
    (l,)=unpack('<I', h.read(4))
    defnend=h.tell()+l-8
    terrain=objects=polygons=network=rasternames=[]
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
        elif c=='NMED':
            rasternames=h.read(l-9).replace('\\','/').replace(':','/').split('\0')
            h.read(1)
        else:
            h.seek(l-8, 1)

    # Geodata Atom
    if __debug__: clock=time.clock()	# Processor time
    h.seek(table['DOEG'])
    (l,)=unpack('<I', h.read(4))
    geodend=h.tell()+l-8
    pool=[]
    scal=[]
    po32=[]
    sc32=[]
    while h.tell()<geodend:
        c=h.read(4)
        (l,)=unpack('<I', h.read(4))
        if not wantnetwork and c in ['23OP','23CS']:
            h.seek(l-8, 1)	# Skip network data
        elif c in ['LOOP','23OP']:
            if c=='LOOP':
                poolkind=pool
                fmt='<H'
                fmtd='<%dH'
                size=2
                mask=0xffff
            else:
                poolkind=po32
                fmt='<I'
                fmtd='<%dI'
                size=4
                mask=0xffffffffL
            thispool=[]
            (n,)=unpack('<I', h.read(4))
            (p,)=unpack('<B', h.read(1))
            #if __debug__: print c,n,p
            for i in range(p):
                thisplane=[]
                (e,)=unpack('<B', h.read(1))
                if e==3:	# RLE differenced, default terrain uses this
                    last=0
                    while(len(thisplane))<n:
                        (r,)=unpack('<B', h.read(1))
                        if (r&128):	# repeat
                            (d,)=unpack(fmt, h.read(size))
                            for j in range(r&127):
                                last=(last+d)&mask
                                thisplane.append(last)
                        else:
                            for d in unpack(fmtd % r, h.read(size*r)):
                                last=(last+d)&mask
                                thisplane.append(last)
                elif e==2:	# RLE
                    while(len(thisplane))<n:
                        (r,)=unpack('<B', h.read(1))
                        if (r&128):	# repeat
                            (d,)=unpack(fmt, h.read(size))
                            thisplane.extend([d for j in range(r&127)])
                        else:
                            thisplane.extend(unpack(fmtd % r, h.read(size*r)))
                elif e==1:	# differenced
                    last=0
                    for d in unpack(fmtd % n, h.read(size*n)):
                        last=(last+d)&mask
                        thisplane.append(last)
                elif e==0:	# raw
                    thisplane=unpack(fmtd % n, h.read(size*n))
                else:
                    raise IOError, baddsf
                thispool.append(thisplane)  
            poolkind.append(thispool)
        elif c=='LACS':
            scal.append([unpack('<2f', h.read(8)) for i in range(0, l-8, 8)])
        elif c=='23CS':
            sc32.append([unpack('<2f', h.read(8)) for i in range(0, l-8, 8)])
        else:
            h.seek(l-8, 1)
    if __debug__: print "%6.3f time in GEOD atom" % (time.clock()-clock)
    
    # Rescale pool and transform to one list per entry
    if __debug__: clock=time.clock()	# Processor time
    for (poolkind,scalkind,mask) in [(pool,scal,0xffff), (po32,sc32,0xffffffffL)]:
        assert len(poolkind)==len(scalkind)
        for i in range(len(poolkind)):	# number of pools
            curpool=poolkind[i]
            if len(curpool)==0:		# empty
                continue
            n=len(curpool[0])		# number of entries in this pool
            newpool=[[] for j in range(n)]
            for plane in range(len(curpool)):	# number of planes in this pool
                (scale,offset)=scalkind[i][plane]
                if scale:
                    scale=scale/mask
                    for j in range(n):
                        newpool[j].append(curpool[plane][j]*scale+offset)
                else:	# network junction IDs are unscaled
                    for j in range(n):
                        newpool[j].append(curpool[plane][j]+offset)
            poolkind[i]=newpool
    if __debug__: print "%6.3f time in rescale" % (time.clock()-clock)

    # X-Plane 10 raster data
    raster={}
    elev=elevwidth=elevheight=None
    if 'SMED' in table:
        if __debug__: clock=time.clock()
        h.seek(table['SMED'])
        (l,)=unpack('<I', h.read(4))
        demsend=h.tell()+l-8
        layerno=0
        while h.tell()<demsend:
            if h.read(4)!='IMED': raise IOError, baddsf
            (l,)=unpack('<I', h.read(4))
            (ver,bpp,flags,width,height,scale,offset)=unpack('<BBHIIff', h.read(20))
            if __debug__: print 'IMED', ver, bpp, flags, width, height, scale, offset, rasternames[layerno]
            if h.read(4)!='DMED': raise IOError, baddsf
            (l,)=unpack('<I', h.read(4))
            assert l==8+bpp*width*height
            if flags&3==0:	# float
                fmt='f'
                assert bpp==4
            elif flags&3==3:
                raise IOError, baddsf
            else:		# signed
                if bpp==1:
                    fmt='b'
                elif bpp==2:
                    fmt='h'
                elif bpp==4:
                    fmt='i'
                else:
                    raise IOError, baddsf
                if flags&3==2:	# unsigned
                    fmt=fmt.upper()
            data=[]
            for i in range(height):
                data.append(unpack('<%d%s' % (width, fmt), h.read(bpp*width)))
            raster[rasternames[layerno]]=data
            if rasternames[layerno]=='elevation':	# we're only interested in elevation
                assert flags&4				# algorithm below assumes post-centric data
                assert scale==1.0 and offset==0		# we don't handle other cases
                elev=raster['elevation']
                elevwidth=width-1
                elevheight=height-1
            layerno+=1
        if __debug__: print "%6.3f time in DEMS atom" % (time.clock()-clock)

    # Commands Atom
    if __debug__: clock=time.clock()	# Processor time
    h.seek(table['SDMC'])
    (l,)=unpack('<I', h.read(4))
    cmdsend=h.tell()+l-8
    curpool=0
    netbase=0
    idx=0
    near=0
    far=-1
    flags=0	# 1=physical, 2=overlay
    roadtype=0
    curter='terrain_Water'
    curpatch=[]
    tercache={'terrain_Water':(join('Resources','Sea01.png'), 8, 0, 0.001,0.001)}
    while h.tell()<cmdsend:
        (c,)=unpack('<B', h.read(1))
        if c==1:	# Coordinate Pool Select
            (curpool,)=unpack('<H', h.read(2))
            
        elif c==2:	# Junction Offset Select
            (netbase,)=unpack('<I', h.read(4))
            #print "\nJunction Offset %d" % netbase
            
        elif c==3:	# Set Definition
            (idx,)=unpack('<B', h.read(1))
            
        elif c==4:	# Set Definition
            (idx,)=unpack('<H', h.read(2))
            
        elif c==5:	# Set Definition
            (idx,)=unpack('<I', h.read(4))
            
        elif c==6:	# Set Road Subtype
            (roadtype,)=unpack('<B', h.read(1))
            #print "\nRoad type %d" % roadtype
            
        elif c==7:	# Object
            (d,)=unpack('<H', h.read(2))
            p=pool[curpool][d]
            if wantoverlay:
                placements.append(Object(objects[idx], p[1],p[0], round(p[2],1)))
                
        elif c==8:	# Object Range
            (first,last)=unpack('<HH', h.read(4))
            if wantoverlay:
                for d in range(first, last):
                    p=pool[curpool][d]
                    placements.append(Object(objects[idx], p[1],p[0], round(p[2],1)))
                    
        elif c==9:	# Network Chain
            (l,)=unpack('<B', h.read(1))
            if not wantnetwork:
                h.read(l*2)
                continue
            #print "\nChain %d" % l
            (d,)=unpack('<H', h.read(2))
            thisnet=[(True,)+tuple(po32[curpool][d+netbase])]
            for i in range(l-1):
                (d,)=unpack('<H', h.read(2))
                p=po32[curpool][d+netbase]
                thisnet.append((True,)+tuple(p))
                if p[3]:	# this is a junction
                    nets.append((roadtype, thisnet))
                    thisnet=[(True,)+tuple(p)]
            
        elif c==10:	# Network Chain Range
            (first,last)=unpack('<HH', h.read(4))
            if not wantnetwork or last-first<2: continue
            #print "\nChain Range %d %d" % (first,last)
            thisnet=[(True,)+tuple(po32[curpool][first+netbase])]
            for d in range(first+netbase+1, last+netbase):
                p=po32[curpool][d]
                thisnet.append((True,)+tuple(p))
                if p[3]:	# this is a junction
                    nets.append((roadtype, thisnet))
                    thisnet=[(True,)+tuple(p)]
            
        elif c==11:	# Network Chain 32
            (l,)=unpack('<B', h.read(1))
            if not wantnetwork:
                h.read(l*4)
                continue
            #print "\nChain32 %d" % l
            (d,)=unpack('<I', h.read(4))
            thisnet=[(True,)+tuple(po32[curpool][d])]
            for i in range(l-1):
                (d,)=unpack('<I', h.read(4))
                p=po32[curpool][d]
                thisnet.append((True,)+tuple(p))
                if p[3]:	# this is a junction
                    nets.append((roadtype, thisnet))
                    thisnet=[(True,)+tuple(p)]
            
        elif c==12:	# Polygon
            (param,l)=unpack('<HB', h.read(3))
            if not wantoverlay or l<2:
                h.read(l*2)
                continue
            winding=[]
            for i in range(l):
                (d,)=unpack('<H', h.read(2))
                p=pool[curpool][d]
                winding.append((True,)+tuple(p))
            placements.append(PolygonFactory(polygons[idx], param, [winding]))
            
        elif c==13:	# Polygon Range (DSF2Text uses this one)
            (param,first,last)=unpack('<HHH', h.read(6))
            if not wantoverlay or last-first<2: continue
            winding=[]
            for d in range(first, last):
                p=pool[curpool][d]
                winding.append((True,)+tuple(p))
            placements.append(PolygonFactory(polygons[idx], param, [winding]))
            
        elif c==14:	# Nested Polygon
            (param,n)=unpack('<HB', h.read(3))
            windings=[]
            for i in range(n):
                (l,)=unpack('<B', h.read(1))
                winding=[]
                for j in range(l):
                    (d,)=unpack('<H', h.read(2))
                    p=pool[curpool][d]
                    winding.append((True,)+tuple(p))
                windings.append(winding)
            if wantoverlay and n>0 and len(windings[0])>=2:
                placements.append(PolygonFactory(polygons[idx], param, windings))
                
        elif c==15:	# Nested Polygon Range (DSF2Text uses this one too)
            (param,n)=unpack('<HB', h.read(3))
            i=[]
            for j in range(n+1):
                (l,)=unpack('<H', h.read(2))
                i.append(l)
            if not wantoverlay: continue
            windings=[]
            for j in range(n):
                winding=[]
                for d in range(i[j],i[j+1]):
                    p=pool[curpool][d]
                    winding.append((True,)+tuple(p))
                windings.append(winding)
            placements.append(PolygonFactory(polygons[idx], param, windings))
            
        elif c==16:	# Terrain Patch
            if curpatch:
                newmesh=makemesh(flags,path,curter,curpatch,south,west,elev,elevwidth,elevheight,terrains,tercache)
                if newmesh: mesh.append(newmesh)
            curter=terrain[idx]
            curpatch=[]
            
        elif c==17:	# Terrain Patch w/ flags
            if curpatch:
                newmesh=makemesh(flags,path,curter,curpatch,south,west,elev,elevwidth,elevheight,terrains,tercache)
                if newmesh: mesh.append(newmesh)
            (flags,)=unpack('<B', h.read(1))
            curter=terrain[idx]
            curpatch=[]
            
        elif c==18:	# Terrain Patch w/ flags & LOD
            if curpatch:
                newmesh=makemesh(flags,path,curter,curpatch,south,west,elev,elevwidth,elevheight,terrains,tercache)
                if newmesh: mesh.append(newmesh)
            (flags,near,far)=unpack('<Bff', h.read(9))
            assert near==0	# We don't currently handle LOD
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
            
        elif c==26:	# Patch Triangle Strip (used by g2xpl and MeshTool)
            (l,)=unpack('<B', h.read(1))
            points=[]
            for i in range(l):
                (d,)=unpack('<H', h.read(2))
                points.append(pool[curpool][d])
            curpatch.extend(meshstrip(points))

        elif c==27:	# Patch Triangle Strip - cross-pool
            (l,)=unpack('<B', h.read(1))
            points=[]
            for i in range(l):
                (p,d)=unpack('<HH', h.read(4))
                points.append(pool[p][d])
            curpatch.extend(meshstrip(points))

        elif c==28:	# Patch Triangle Strip Range
            (first,last)=unpack('<HH', h.read(4))
            curpatch.extend(meshstrip(pool[curpool][first:last]))

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
        newmesh=makemesh(flags,path,curter,curpatch,south,west,elev,elevwidth,elevheight,terrains,tercache)
        if newmesh: mesh.append(newmesh)
    if __debug__: print "%6.3f time in CMDS atom" % (time.clock()-clock)

    h.close()
    return (south, west, placements, nets, mesh)


def meshstrip(points):
    tris=[]
    for i in range(len(points)-2):
        if i%2:
            tris.extend([points[i+2], points[i+1], points[i]])
        else:
            tris.extend([points[i],   points[i+1], points[i+2]])
    return tris

def meshfan(points):
    tris=[]
    for i in range(1,len(points)-1):
        tris.extend([points[0], points[i], points[i+1]])
    return tris

def makemesh(flags,path,ter,patch,south,west,elev,elevwidth,elevheight,terrains,tercache):

    def elevation(lat,lon,south,west,elev,elevwidth,elevheight):
        # elevation from raster data - see DEMGeo::value_linear in xptools
        x_fract=(lon-west)*elevwidth
        z_fract=(lat-south)*elevwidth
        x=int(x_fract)
        z=int(z_fract)
        x_fract-=x
        z_fract-=z
        v1=elev[z][x]
        if x>=elevwidth:
            v2=v1		# east boundary
            if z>=elevheight:
                v4=v3=v2=v1	# north east corner
            else:
                v4=v3=elev[z+1][x]
        elif z>=elevheight:
            v3=v1		# north boundary
            v4=v2=elev[z][x+1]
        else:
            v2=elev[z  ][x+1]
            v3=elev[z+1][x  ]
            v4=elev[z+1][x+1]
        w1=(1.0 - x_fract) * (1.0 - z_fract)
        w2=(      x_fract) * (1.0 - z_fract)
        w3=(1.0 - x_fract) * (      z_fract)
        w4=(      x_fract) * (      z_fract)
        return (v1 * w1 + v2 * w2 + v3 * w3 + v4 * w4) / (w1 + w2 + w3 + w4)

    # Get terrain info
    if ter in tercache:
        (texture, texflags, angle, xscale, zscale)=tercache[ter]
    else:
        texture=None
        texflags=8	# wrap
        angle=0
        xscale=zscale=0
        try:
            if ter in terrains:	# Library terrain
                phys=terrains[ter]
            else:		# Package-specific terrain
                phys=normpath(join(dirname(path), pardir, pardir, ter))
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
                    texflags=(c[0]=='BASE_TEX' and 8)
                    texture=line[len(c[0]):].strip()
                    texture=texture.replace(':', sep)
                    texture=texture.replace('/', sep)
                    texture=normpath(join(dirname(phys), texture))
                elif c[0]=='PROJECTED':
                    xscale=1/float(c[1])
                    zscale=1/float(c[2])
                elif c[0]=='PROJECT_ANGLE':
                    if float(c[1])==0 and float(c[2])==1 and float(c[3])==0:
                        # no idea what rotation about other axes means
                        angle=int(float(c[4]))
            h.close()
        except:
            if __debug__:
                print 'Failed to load terrain "%s"' % ter
                print_exc()
        tercache[ter]=(texture, texflags, angle, xscale, zscale)

    # Make mesh
    centrelat=south+0.5
    centrelon=west+0.5
    v=[]
    t=[]
    if flags&1 and (len(patch[0])<7 or xscale):	# hard and no st coords
        for p in patch:
            x=(p[0]-centrelon)*onedeg*cos(radians(p[1]))
            z=(centrelat-p[1])*onedeg
            if p[2]!=-32768:
                y=p[2]
            else:	# elevation from raster data
                y=elevation(p[1],p[0],south,west,elev,elevwidth,elevheight)
            v.append([x, y, z])
            if not angle:
                t.append([x*xscale, -z*zscale])
            elif angle==90:
                t.append([z*zscale, x*xscale])
            elif angle==180:
                t.append([-x*xscale, z*zscale])
            elif angle==270:
                t.append([-z*zscale, -x*xscale])
            else: # not square - ignore rotation
                t.append([x*xscale, -z*zscale])
    elif not (len(patch[0])<7 or xscale):	# st coords but not projected
        for p in patch:
            if p[2]!=-32768:
                y=p[2]
            else:	# elevation from raster data
                y=elevation(p[1],p[0],south,west,elev,elevwidth,elevheight)
            v.append([(p[0]-centrelon)*onedeg*cos(radians(p[1])),
                      y, (centrelat-p[1])*onedeg])
            t.append([p[5],p[6]])
    else:
        # skip not hard and no st coords - complicated blending required
        return None
    return (texture,flags|texflags,v,t)


def writeDSF(dsfdir, key, placements, netfile):
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
    if not (placements): return

    tmp=join(gettempdir(), "%+03d%+04d.txt" % (south,west))
    h=file(tmp, 'wt')
    h.write('I\n800\nDSF2TEXT\n\n')
    h.write('PROPERTY\tsim/planet\tearth\n')
    h.write('PROPERTY\tsim/overlay\t1\n')
    h.write('PROPERTY\tsim/require_object\t1/0\n')
    h.write('PROPERTY\tsim/require_facade\t1/0\n')
    h.write('PROPERTY\tsim/creation_agent\t%s %4.2f\n' % (appname, appversion))

    objects=[]
    polygons=[]
    for placement in placements:
        if isinstance(placement,Object):
            objects.append(placement)
        elif isinstance(placement,Exclude):
            for k in Exclude.NAMES:
                if Exclude.NAMES[k]==placement.name:
                    minlat=minlon=maxint
                    maxlat=maxlon=-maxint
                    for n in placement.nodes[0]:
                        minlon=min(minlon,n[0])
                        maxlon=max(maxlon,n[0])
                        minlat=min(minlat,n[1])
                        maxlat=max(maxlat,n[1])
                    h.write('PROPERTY\t%s\t%.6f/%.6f/%.6f/%.6f\n' % (
                        k, minlon, minlat, maxlon, maxlat))
                    break
        else:
            polygons.append(placement)

    # must be final properties
    h.write('PROPERTY\tsim/west\t%d\n' %   west)
    h.write('PROPERTY\tsim/east\t%d\n' %  (west+1))
    h.write('PROPERTY\tsim/north\t%d\n' % (south+1))
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
        if isinstance(poly, Network): continue
        if not poly.name in polydefs:
            polydefs.append(poly.name)
            h.write('POLYGON_DEF\t%s\n' % poly.name)
    if polydefs: h.write('\n')

    junctions={}
    for poly in polygons:
        if not isinstance(poly, Network): continue
        if not junctions: h.write('NETWORK_DEF\t%s\n\n' % netfile)
        for node in [poly.nodes[0][0], poly.nodes[0][-1]]:
            junctions[(node[0], node[1], node[2])]=True
    jnum=1
    for j in junctions.keys():
        junctions[j]=jnum
        jnum+=1

    for obj in objects:
        # DSFTool rounds down, so round up here first
        h.write('OBJECT\t%d\t%12.7f%13.7f%6.1f\n' % (
            objdefs.index(obj.name), min(west+1, obj.lon+minres/2), min(south+1, obj.lat+minres/2), round(obj.hdg,1)+minhdg/2))
    if objects: h.write('\n')
    
    for poly in polygons:
        if isinstance(poly, Network): continue
        h.write('BEGIN_POLYGON\t%d\t%d %d\n' % (
            polydefs.index(poly.name), poly.param, len(poly.nodes[0][0])))
        for w in poly.nodes:
            h.write('BEGIN_WINDING\n')
            for p in w:
                # DSFTool rounds down, so round up here first
                h.write('POLYGON_POINT\t%12.7f%13.7f' % (min(west+1, p[0]+minres/2), min(south+1, p[1]+minres/2)))
                if len(p)==4 and poly.param!=65535: # don't adjust UV coords
                    h.write('%13.7f%13.7f' % (min(west+1, p[2]+minres/2), min(south+1, p[3]+minres/2)))
                elif len(p)==5:
                    h.write('%13.7f%13.7f%13.7f' % (p[2], min(west+1, p[3]+minres/2), min(south+1, p[4]+minres/2)))
                elif len(p)==8:
                    h.write('%13.7f%13.7f%13.7f%13.7f%13.7f%13.7f' % (min(west+1, p[2]+minres/2), min(south+1, p[3]+minres/2), p[4], p[5], p[6], p[7]))
                else:
                    for n in range(3,len(p)):
                        h.write('%13.7f' % p[n])
                h.write('\n')
            h.write('END_WINDING\n')
        h.write('END_POLYGON\n')
    if polydefs: h.write('\n')

    for poly in polygons:
        if not isinstance(poly, Network): continue
        p=poly.nodes[0][0]
        h.write('BEGIN_SEGMENT\t%d %d\t%d\t%13.8f %13.8f %11.6f\n' % (
            0, poly.index, junctions[(p[0], p[1], p[2])],
            p[0], p[1], p[2]))
        for p in poly.nodes[0][1:-1]:
            h.write('SHAPE_POINT\t\t\t%13.8f %13.8f %11.6f\n' % (
                p[0], p[1], p[2]))
        p=poly.nodes[0][-1]
        h.write('END_SEGMENT\t\t%d\t%13.8f %13.8f %11.6f\n' % (
            junctions[(p[0], p[1], p[2])],
            p[0], p[1], p[2]))
    if junctions: h.write('\n')
    
    h.close()
    if platform=='win32':
        # Bug - how to suppress environment variable expansion?
        cmds='%s -text2dsf "%s" "%s.dsf"' % (dsftool, tmp, tilename) #.replace('%','%%'))
        if type(cmds)==types.UnicodeType:
            # commands must be MBCS encoded
            cmds=cmds.encode("mbcs")
    else:
        # See "QUOTING" in bash(1)
        cmds='%s -text2dsf "%s" "%s.dsf"' % (dsftool, tmp, tilename.replace('\\','\\\\').replace('"','\\"').replace("$", "\\$").replace("`", "\\`"))
    (i,o,e)=popen3(cmds)
    i.close()
    err=o.read()
    err+=e.read()
    o.close()
    e.close()
    if not __debug__: unlink(tmp)
    if not exists(tilename+'.dsf'):
        if exists(tilename+'.dsf.bak'):
            rename(tilename+'.dsf.bak', tilename+'.dsf')
        elif exists(tilename+'.DSF.BAK'):
            rename(tilename+'.DSF.BAK', tilename+'.DSF')
        if __debug__: print err
        err=err.strip().split('\n')
        if len(err)>1 and err[-1].startswith('('):
            err=err[-2].strip()	# DSF errors appear on penultimate line
        else:
            err=err[0].strip()
        raise IOError, (0, err)
