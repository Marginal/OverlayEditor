from collections import defaultdict	# Requires Python 2.5
from math import cos, floor, pi, radians
from numpy import ndarray, array, arange, concatenate, choose, cumsum, empty, fromstring, insert, logical_and, logical_or, repeat, roll, unique, vstack, where, zeros, float32, uint16, uint32
from os import mkdir, popen3, rename, unlink, SEEK_CUR, SEEK_END
from os.path import basename, curdir, dirname, exists, expanduser, isdir, join, normpath, pardir, sep
from struct import unpack
from sys import platform, getfilesystemencoding
from tempfile import gettempdir
from OpenGL.GL import GLuint
import numpy
import types
import time
try:
    from py7zlib import Archive7z
    from cStringIO import StringIO
except:
    Archive7z=False	# not available packaged in most Linux distros
if __debug__:
    from traceback import print_exc

if not hasattr(numpy,'radians'):
    # numpy 1.0.1 on MacOS 10.5 doesn't have radians
    def npradians(x, out=None):
        if out:
            out[:] = x * (pi/180)
            return out
        else:
            return x * (pi/180)
    numpy.radians = npradians

from elevation import DSFdivisions, onedeg
from nodes import Node
from clutter import Object, AutoGenBlock, AutoGenString, Polygon, Exclude, Network
from clutterdef import NetworkDef, COL_NETWORK
from version import appname, appversion

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
# If terrains is defined,  assume loading terrain and discard clutter
# If terrains not defined, assume looking for an overlay DSF
#
def readDSF(path, netdefs, terrains, bbox=None, bytype=None):
    wantoverlay = not terrains
    wantmesh = not wantoverlay
    baddsf=(0, "Invalid DSF file", path)

    if __debug__: print path.encode(getfilesystemencoding() or 'utf-8')
    h=file(path, 'rb')
    sig=h.read(8)
    if sig.startswith('7z\xBC\xAF\x27\x1C'):	# X-Plane 10 compressed
        if __debug__: clock=time.clock()
        if Archive7z:
            h.seek(0)
            data=Archive7z(h).getmember(basename(path)).read()
            h.close()
            h=StringIO(data)
        else:
            h.close()
            cmds=exists('/usr/bin/7zr') and '/usr/bin/7zr' or '/usr/bin/7za'
            cmds='%s e "%s" -o"%s" -y' % (cmds, path, gettempdir())
            (i,o,e)=popen3(cmds)
            i.close()
            err=o.read()
            err+=e.read()
            o.close()
            e.close()
            h=file(join(gettempdir(), basename(path)), 'rb')
        if __debug__: print "%6.3f time in decompression" % (time.clock()-clock)
        sig=h.read(8)
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
    if __debug__: print table
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
    nets = defaultdict(list)
    mesh = defaultdict(list)
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
            placements.append(Exclude(Exclude.NAMES[c[i]], 0, [[Node([v[0],v[1]]), Node([v[2],v[1]]), Node([v[2],v[3]]), Node([v[0],v[3]])]]))
    if wantoverlay and not overlay and not bbox:
        # Not an Overlay DSF - bail early
        h.close()
        raise IOError (0, "%s is not an overlay." % basename(path))
    if overlay and (bbox or wantmesh):
        # only interested in mesh data - bail early
        h.close()
        return (south, west, placements, nets, mesh)
        
    h.seek(headend)

    # Definitions Atom
    h.seek(table['NFED'])
    (l,)=unpack('<I', h.read(4))
    defnend=h.tell()+l-8
    terrain=objects=polygons=networks=rasternames=[]
    while h.tell()<defnend:
        c=h.read(4)
        (l,)=unpack('<I', h.read(4))
        if l==8:
            pass	# empty
        elif c=='TRET':
            terrain=h.read(l-9).replace('\\','/').replace(':','/').split('\0')
            h.read(1)
        elif c=='TJBO':
            objects=[x.decode() for x in h.read(l-9).replace('\\','/').replace(':','/').split('\0')]	# X-Plane only supports ASCII
            h.read(1)
        elif c=='YLOP':
            polygons=[x.decode() for x in h.read(l-9).replace('\\','/').replace(':','/').split('\0')]	# X-Plane only supports ASCII
            h.read(1)
        elif c=='WTEN':
            networks=h.read(l-9).replace('\\','/').replace(':','/').split('\0')
            h.read(1)
        elif c=='NMED':
            rasternames=h.read(l-9).replace('\\','/').replace(':','/').split('\0')
            h.read(1)
        else:
            h.seek(l-8, 1)

    # We only understand a limited set of v10-style networks
    if networks and networks!=[NetworkDef.DEFAULTFILE]:
        if wantoverlay and not bbox:
            raise IOError, (0, 'Unsupported network: %s' % ', '.join(networks))
        else:
            skipnetworks = True
    else:
        skipnetworks = False

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
        if skipnetworks and c in ['23OP','23CS']:
            h.seek(l-8, 1)	# Skip network data
        elif c in ['LOOP','23OP']:
            if c=='LOOP':
                poolkind=pool
                fmt='<H'
                ifmt=uint16
                size=2
            else:
                poolkind=po32
                fmt='<I'
                ifmt=uint32
                size=4
            (n,p)=unpack('<IB', h.read(5))
            #if __debug__: print c,n,p
            thispool = empty((n,p), ifmt)
            # Pool data is supplied in column order (by "plane"), so use numpy slicing to assign
            for i in range(p):
                (e,)=unpack('<B', h.read(1))	# encoding type - default DSFs use e=3
                if e&2:		# RLE
                    offset = 0
                    while offset<n:
                        (r,)=unpack('<B', h.read(1))
                        if (r&128):	# repeat
                            (d,)=unpack(fmt, h.read(size))
                            thispool[offset:offset+(r&127),i] = d
                            offset += (r&127)
                        else:		# non-repeat
                            thispool[offset:offset+r,i] = fromstring(h.read(r*size), fmt)
                            offset += r
                else:		# raw
                    thispool[:,i] = fromstring(h.read(n*size), fmt)
                if e&1:		# differenced
                    thispool[:,i] = cumsum(thispool[:,i], dtype=ifmt)
            poolkind.append(thispool)
        elif c=='LACS':
            scal.append(fromstring(h.read(l-8), '<f').reshape(-1,2))
            #if __debug__: print c,scal[-1]
        elif c=='23CS':
            sc32.append(fromstring(h.read(l-8), '<f').reshape(-1,2))
            #if __debug__: print c,sc32[-1]
        else:
            h.seek(l-8, 1)
    if __debug__: print "%6.3f time in GEOD atom" % (time.clock()-clock)
    
    # Rescale pools
    if __debug__: clock=time.clock()			# Processor time
    for i in range(len(pool)):				# number of pools
        curpool = pool[i]
        curscale= scal[i]
        newpool = empty(curpool.shape, float)		# need double precision for placements
        for plane in range(len(curscale)):		# number of planes in this pool
            (scale,offset) = curscale[plane]
            if scale:
                newpool[:,plane] = curpool[:,plane] * (scale/0xffff) + float(offset)
            else:
                newpool[:,plane] = curpool[:,plane] + float(offset)
        # numpy doesn't work efficiently skipping around the variable sized pools, so don't consolidate
        pool[i] = newpool

    # if __debug__:	# Dump pools
    #     for p in pool:
    #         for x in p:
    #             for y in x:
    #                 print "%.5f" % y,
    #             print
    #         print

    # Rescale network pool
    while po32 and not len(po32[-1]): po32.pop()	# v10 DSFs have a bogus zero-dimensioned pool at the end
    if po32:
        if len(po32)!=1 or sc32[0].shape!=(4,2):
            raise IOError, baddsf			# code below is optimized for one big pool
        if wantoverlay:
            newpool = empty((len(po32[0]),3), float)	# Drop junction IDs. Need double precision for placements
            for plane in range(3):
                (scale,offset) = sc32[0][plane]
                newpool[:,plane] = po32[0][:,plane] * (scale/0xffffffffL) + float(offset)
            po32 = newpool
        else:
            # convert to local coords if we just want network lines. Do calculations in double, store result as single.
            centrelat = south+0.5
            centrelon = west+0.5
            newpool = empty((len(po32[0]),6), float32)	# drop junction IDs, add space for color
            lat = po32[0][:,1] * (sc32[0][1][0]/0xffffffffL) + float(sc32[0][1][1])	# double
            newpool[:,0] =(po32[0][:,0] * onedeg*(sc32[0][0][0]/0xffffffffL) + onedeg*(sc32[0][0][1] - centrelon)) * numpy.cos(numpy.radians(lat))	# lon -> x
            newpool[:,1] = po32[0][:,2] * (sc32[0][2][0]/0xffffffffL) + float(sc32[0][2][1])	# y
            newpool[:,2] = onedeg*centrelat - onedeg*lat	# lat -> z
            if __debug__:
                assert not sc32[0][3].any()		# Junction IDs are unscaled
                newpool[:,3] = po32[0][:,3]		# Junction ID for splitting (will be overwritten at consolidation stage)
            po32 = newpool

    if __debug__:
        print "%6.3f time in rescale" % (time.clock()-clock)
        total = 0
        longest = 0
        for p in pool:
            total += len(p)
            longest = max(longest, len(p))
        print 'pool:', len(pool), 'Avg:', total/(len(pool) or 1), 'Max:', longest
        print 'po32:', len(po32)

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
            data = fromstring(h.read(bpp*width*height), '<'+fmt).reshape(width,height)
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
    netcolor = COL_NETWORK
    netname = '#000' + NetworkDef.NETWORK
    idx=0
    near=0
    far=-1
    flags=0	# 1=physical, 2=overlay
    roadtype=0
    curter='terrain_Water'
    curpatch=[]
    tercache={'terrain_Water':(join('Resources','Sea01.png'), True, 0, 0.001,0.001)}
    stripindices = MakeStripIndices()
    fanindices   = MakeFanIndices()

    if __debug__: cmds = defaultdict(int)
    while h.tell()<cmdsend:
        (c,)=unpack('<B', h.read(1))
        if __debug__: cmds[c] += 1
        #if __debug__: print "%08x %d" % (h.tell()-1, c)

        # Commands in rough order of frequency of use
        if c==10:	# Network Chain Range (used by g2xpl and MeshTool)
            (first,last)=unpack('<HH', h.read(4))
            #print "\nChain Range %d %d" % (first,last)
            if skipnetworks or last-first<2:
                pass
            elif wantoverlay:
                assert curpool==0, curpool
                placements.append(Network(netname, 0, [[Node(p) for p in po32[netbase+first:netbase+last]]]))
            else:
                assert curpool==0, curpool
                #assert not nodes[1:-2,3].any(), nodes	# Only handle single complete chain
                nets[netcolor].append(po32[netbase+first:netbase+last])

        elif c==9:	# Network Chain (KSEA demo terrain uses this one)
            (l,)=unpack('<B', h.read(1))
            #print "\nChain %d" % l
            if skipnetworks:
                h.read(l*2)
            elif wantoverlay:
                assert curpool==0, curpool
                placements.append(Network(netname, 0, [[Node(p) for p in po32[netbase+fromstring(h.read(l*2), '<H').astype(int)]]]))
            else:
                assert curpool==0, curpool
                #assert not nodes[1:-2,3].any(), nodes	# Only handle single complete chain
                nets[netcolor].append(po32[netbase+fromstring(h.read(l*2), '<H').astype(int)])

        elif c==11:	# Network Chain 32 (KSEA demo terrain uses this one too)
            (l,)=unpack('<B', h.read(1))
            #print "\nChain32 %d" % l
            if skipnetworks:
                h.read(l*4)
            elif wantoverlay:
                assert curpool==0, curpool
                placements.append(Network(netname, 0, [[Node(p) for p in po32[fromstring(h.read(l*4), '<I')]]]))
            else:
                assert curpool==0, curpool
                #assert not nodes[1:-2,3].any(), nodes	# Only handle single complete chain
                nets[netcolor].append(po32[fromstring(h.read(l*4), '<I')])

        elif c==13:	# Polygon Range (DSF2Text uses this one)
            (param,first,last)=unpack('<HHH', h.read(6))
            if not wantoverlay or last-first<2: continue
            winding=[]
            for d in range(first, last):
                p=pool[curpool][d]
                winding.append(p.tolist())
            placements.append(Polygon.factory(polygons[idx], param, [winding]))

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
                    winding.append(p.tolist())
                windings.append(winding)
            placements.append(Polygon.factory(polygons[idx], param, windings))

        elif c==27:	# Patch Triangle Strip - cross-pool (KSEA demo terrain uses this one)
            (l,)=unpack('<B', h.read(1))
            #if __debug__: print '27: Triangle strip %d' % l
            if flags&1 and wantmesh:
                curpatch.append(array([pool[p][d] for (p,d) in fromstring(h.read(l*4), '<H').reshape(-1,2)])[stripindices[l]])
                assert len(curpatch[-1]) == 3*(l-2), len(curpatch[-1])
            else:
                h.seek(l*4, 1)

        elif c==28:	# Patch Triangle Strip Range (KSEA demo terrain uses this one too)
            (first,last)=unpack('<HH', h.read(4))
            #if __debug__: print '28: Triangle strip %d' % (last-first)
            if flags&1 and wantmesh:
                curpatch.append(pool[curpool][first:][stripindices[last-first]])
                assert len(curpatch[-1]) == 3*(last-first-2), len(curpatch[-1])

        elif c==1:	# Coordinate Pool Select
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
            netcolor = roadtype in netdefs and netdefs[roadtype].color or COL_NETWORK
            netname  = roadtype in netdefs and netdefs[roadtype].name or '#%03d%s' % (roadtype, NetworkDef.NETWORK)
            #print "\nRoad type %d" % roadtype
            
        elif c==7:	# Object
            (d,)=unpack('<H', h.read(2))
            p=pool[curpool][d]
            if wantoverlay:
                placements.append(Object.factory(objects[idx], p[1],p[0], round(p[2],1)))
                
        elif c==8:	# Object Range
            (first,last)=unpack('<HH', h.read(4))
            if wantoverlay:
                for d in range(first, last):
                    p=pool[curpool][d]
                    placements.append(Object.factory(objects[idx], p[1],p[0], round(p[2],1)))

        elif c==12:	# Polygon
            (param,l)=unpack('<HB', h.read(3))
            if not wantoverlay or l<2:
                h.read(l*2)
                continue
            winding=[]
            for i in range(l):
                (d,)=unpack('<H', h.read(2))
                p=pool[curpool][d]
                winding.append(p.tolist())
            placements.append(Polygon,factory(polygons[idx], param, [winding]))
            
        elif c==14:	# Nested Polygon
            (param,n)=unpack('<HB', h.read(3))
            windings=[]
            for i in range(n):
                (l,)=unpack('<B', h.read(1))
                winding=[]
                for j in range(l):
                    (d,)=unpack('<H', h.read(2))
                    p=pool[curpool][d]
                    winding.append(p.tolist())
                windings.append(winding)
            if wantoverlay and n>0 and len(windings[0])>=2:
                placements.append(Polygon.factory(polygons[idx], param, windings))
                
        elif c==16:	# Terrain Patch
            makemesh(mesh,path,curter,curpatch,south,west,elev,elevwidth,elevheight,terrains,tercache)
            #if __debug__: print '\n16: Patch, flags=%d' % flags
            curter=terrain[idx]
            curpatch=[]
            
        elif c==17:	# Terrain Patch w/ flags
            makemesh(mesh,path,curter,curpatch,south,west,elev,elevwidth,elevheight,terrains,tercache)
            (flags,)=unpack('<B', h.read(1))
            #if __debug__: print '\n17: Patch, flags=%d' % flags
            curter=terrain[idx]
            curpatch=[]
            
        elif c==18:	# Terrain Patch w/ flags & LOD
            makemesh(mesh,path,curter,curpatch,south,west,elev,elevwidth,elevheight,terrains,tercache)
            (flags,near,far)=unpack('<Bff', h.read(9))
            #if __debug__: print '18: Patch, flags=%d, lod=%d,%d' % (flags, near,far)
            assert near==0	# We don't currently handle LOD
            curter=terrain[idx]
            curpatch=[]

        elif c==23:	# Patch Triangle
            (l,)=unpack('<B', h.read(1))
            #if __debug__: print '23: Triangles %d' % l
            if flags&1 and wantmesh:
                curpatch.append(pool[curpool][fromstring(h.read(l*2), '<H')])
                assert len(curpatch[-1]) == l, len(curpatch[-1])
            else:
                h.seek(l*2, 1)

        elif c==24:	# Patch Triangle - cross-pool
            (l,)=unpack('<B', h.read(1))
            #if __debug__: print '24: Triangles %d' % l
            if flags&1 and wantmesh:
                curpatch.append(array([pool[p][d] for (p,d) in fromstring(h.read(l*4), '<H').reshape(-1,2)]))
                assert len(curpatch[-1]) == l, len(curpatch[-1])
            else:
                h.seek(l*4, 1)

        elif c==25:	# Patch Triangle Range
            (first,last)=unpack('<HH', h.read(4))
            #if __debug__: print '25: Triangles %d' % (last-first)
            if flags&1 and wantmesh:
                curpatch.append(pool[curpool][first:last])
                assert len(curpatch[-1]) == last-first, len(curpatch[-1])

        elif c==26:	# Patch Triangle Strip (used by g2xpl and MeshTool)
            (l,)=unpack('<B', h.read(1))
            #if __debug__: print '26: Triangle strip %d' % l
            if flags&1 and wantmesh:
                curpatch.append(pool[curpool][fromstring(h.read(l*2), '<H')[stripindices[l]]])
                assert len(curpatch[-1]) == 3*(l-2), len(curpatch[-1])
            else:
                h.seek(l*2, 1)

        elif c==29:	# Patch Triangle Fan
            (l,)=unpack('<B', h.read(1))
            #if __debug__: print '29: Triangle fan %d' % l
            if flags&1 and wantmesh:
                curpatch.append(pool[curpool][fromstring(h.read(l*2), '<H')[fanindices[l]]])
                assert len(curpatch[-1]) == 3*(l-2), len(curpatch[-1])
            else:
                h.seek(l*2, 1)

        elif c==30:	# Patch Triangle Fan - cross-pool
            (l,)=unpack('<B', h.read(1))
            #if __debug__: print '30: Triangle fan %d' % l
            if flags&1 and wantmesh:
                curpatch.append(array([pool[p][d] for (p,d) in fromstring(h.read(l*4), '<H').reshape(-1,2)])[fanindices[l]])
                assert len(curpatch[-1]) == 3*(l-2), len(curpatch[-1])
            else:
                h.seek(l*4, 1)

        elif c==31:	# Patch Triangle Fan Range
            (first,last)=unpack('<HH', h.read(4))
            #if __debug__: print '31: Triangle fan %d' % (last-first)
            if flags&1 and wantmesh:
                curpatch.append(pool[curpool][first:][fanindices[last-first]])
                assert len(curpatch[-1]) == 3*(last-first-2), len(curpatch[-1])

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
            if __debug__: print "Unrecognised command (%d) at %x" % (c, h.tell()-1)
            raise IOError, (c, "Unrecognised command (%d)" % c, path)

    # Last one
    makemesh(mesh,path,curter,curpatch,south,west,elev,elevwidth,elevheight,terrains,tercache)

    if __debug__:
        print "%6.3f time in CMDS atom" % (time.clock()-clock)
        print 'Stats:'
        for cmd in sorted(cmds.keys()): print cmd, cmds[cmd]
        if not wantoverlay: print "%d patches, avg subsize %s" % (makemesh.count, makemesh.total/makemesh.count)
    h.close()

    # consolidate mesh
    for k,v in mesh.iteritems():
        mesh[k] = concatenate(v)

    if len(terrain)>1 and 'g2xpl' in terrain[1]:
        # Post-processing for g2xpl-generated meshes. This is slow so only do it if a g2xpl texture is used.
        if __debug__: clock=time.clock()
        for k,v in mesh.iteritems():
            # sort vertices of each triangle
            dtype = [('x1',float32), ('y1',float32), ('z1',float32), ('u1',float32), ('v1',float32),
                     ('x2',float32), ('y2',float32), ('z2',float32), ('u2',float32), ('v2',float32),
                     ('x3',float32), ('y3',float32), ('z3',float32), ('u3',float32), ('v3',float32)]
            v = v.reshape((-1,15))
            v1 = v.view(dtype)
            v2 = roll(v, -5, axis=1).view(dtype)
            v3 = roll(v, -10, axis=1).view(dtype)
            v12= where(logical_or(v2['x1'] > v1['x1'], logical_and(v2['x1'] == v1['x1'], v2['z1'] > v1['z1'])), v2, v1)
            v  = where(logical_or(v3['x1'] >v12['x1'], logical_and(v3['x1'] ==v12['x1'], v3['z1'] >v12['z1'])), v3, v12)

            # remove negatives - calculate cross product at middle point p2
            # http://paulbourke.net/geometry/polygonmesh/ "... vertices ordered clockwise or counterclockwise"
            v = v[(v['x2']-v['x1']) * (v['z3']-v['z2']) - (v['z2']-v['z1']) * (v['x3']-v['x2']) > 0]

            # Remove dupes. numpy.unique() only works on 1D arrays -
            # http://mail.scipy.org/pipermail/numpy-discussion/2010-September/052877.html
            v = unique(v)
            mesh[k] = v.view(float32).reshape((-1,5))
        if __debug__: print "%6.3f time in g2xpl post-processing" % (time.clock()-clock)

    # apply colors to network points, consolidate and create indices for drawing
    # FIXME: speed this up
    if nets:
        counts = []	# points in each chain
        newnets = []
        for color, cnets in nets.iteritems():
            counts.extend([len(chain) for chain in cnets])
            cnets = vstack(cnets)
            cnets[:,3:6] = color	# apply color across all points
            newnets.append(cnets)
        newnets = vstack(newnets)
        counts = array(counts, int)
        start  = cumsum(concatenate((zeros((1,), int), counts)))[:-1]
        end    = start + counts - 1
        indices= concatenate([repeat(arange(start[i],end[i],1,GLuint), 2) for i in range(len(counts))])
        indices[1::2] += 1
        assert (len(indices) == (sum(counts)-len(counts))*2)
        nets = (newnets, indices)
    else:
        nets = None

    if bbox:	# filter to bounding box
        if bytype is Object:
            placements = [p for p in placements if p.inside(bbox) and (isinstance(p, Object) or isinstance(p, AutoGenBlock) or isinstance(p, AutoGenString))]	# filter by type, including AutoGenPoints
        elif bytype:
            placements = [p for p in placements if p.inside(bbox) and p.__class__ is bytype]	# filter by type, excluding derived
    else:
        if bytype is Object:
            placements = [p for p in placements if isinstance(p, Object) or isinstance(p, AutoGenBlock) or isinstance(p, AutoGenString)]	# filter by type, including AutoGenPoints
        elif bytype:
            placements = [p for p in placements if p.__class__ is bytype]	# filter by type, excluding derived

    return (south, west, placements, nets, mesh)


# Indices for making n-2 triangles out of n vertices of a tri strip
class MakeStripIndices(dict):
    def __missing__(self, n):
        a = concatenate([i%2 and [i, i+2, i+1] or [i, i+1, i+2] for i in range(n-2)])
        assert len(a) == 3*(n-2), a
        self[n] = a
        return a

# Indices for making n-2 triangles out of n vertices of a tri fan
class MakeFanIndices(dict):
    def __missing__(self, n):
        a = zeros(3*(n-2), int)
        a[1:n*3:3] += arange(1,n-1)
        a[2:n*3:3] += arange(2,n)
        assert len(a) == 3*(n-2), a
        self[n] = a
        return a


def makemesh(mesh,path,ter,patch,south,west,elev,elevwidth,elevheight,terrains,tercache):

    if not patch: return

    if __debug__:
        if "count" not in makemesh.__dict__: makemesh.count = makemesh.total = 0
        makemesh.count += 1
        makemesh.total += sum([len(p) for p in patch])

    # Get terrain info
    if ter in tercache:
        (texture, wrap, angle, xscale, zscale)=tercache[ter]
    else:
        texture=None
        wrap=True	# wrap
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
                    wrap = (c[0]=='BASE_TEX')
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
        tercache[ter]=(texture, wrap, angle, xscale, zscale)

    # Make mesh
    centrelat=south+0.5
    centrelon=west+0.5
    v = vstack(patch)[:,:7].astype(float32)	# down to single precision for OpenGL

    heights = v[:,2].copy()
    e = (heights == -32768)	# indices of points that take elevation from raster data
    if e.any():
        # vectorised version of elevation from raster data - see DEMGeo::value_linear in xptools
        n = (numpy.sum(e),)
        x = empty(n, int)
        x_frac = empty(n, float32)
        z = empty(n, int)
        z_frac = empty(n, float32)
        try:
            numpy.modf((v[:,0][e] - west)  * elevwidth,  x_frac, x, casting='unsafe')	# We need x as int for indexing
            numpy.modf((v[:,1][e] - south) * elevheight, z_frac, z, casting='unsafe')	# We need z as int for indexing
        except:	# pre numpy 1.6
            numpy.modf((v[:,0][e] - west)  * elevwidth,  x_frac, x)
            numpy.modf((v[:,1][e] - south) * elevheight, z_frac, z)
        x1 = numpy.where(x < elevwidth-1,  x+1, elevwidth-1)
        z1 = numpy.where(z < elevheight-1, z+1, elevheight-1)
        v1 = elev[z,  x ]
        v2 = elev[z,  x1]
        v3 = elev[z1, x ]
        v4 = elev[z1, x1]
        w1 = (1-x_frac) * (1-z_frac)
        w2 = (  x_frac) * (1-z_frac)
        w3 = (1-x_frac) * (  z_frac)
        w4 = (  x_frac) * (  z_frac)
        v[:,0] = (onedeg*v[:,0] - onedeg*centrelon) * numpy.cos(numpy.radians(v[:,1]))	# lon -> x
        v[:,2] = onedeg*centrelat - onedeg*v[:,1]	# lat -> z
        v[:,1] = heights
        v[:,1][e] = (v1 * w1 + v2 * w2 + v3 * w3 + v4 * w4) / (w1 + w2 + w3 + w4)	# y
    else:
        v[:,0] = (onedeg*v[:,0] - onedeg*centrelon) * numpy.cos(numpy.radians(v[:,1]))	# lon -> x
        v[:,2] = onedeg*centrelat - onedeg*v[:,1]	# lat -> z
        v[:,1] = heights

    #if __debug__:
    #    for i in range(len(patch)): assert -onedeg/2<=v[i][0]<=onedeg/2 and -onedeg/2<=v[i][2]<=onedeg/2, "%d\n%s\n%s" % (i, patch[i], v[i])
    if xscale:	# projected
        if not angle:
            v[:,3] = v[:,0] *  xscale
            v[:,4] = v[:,2] * -zscale
        elif angle==90:
            v[:,3] = v[:,2] *  zscale
            v[:,4] = v[:,0] *  xscale
        elif angle==180:
            v[:,3] = v[:,0] * -xscale
            v[:,4] = v[:,2] *  zscale
        elif angle==270:
            v[:,3] = v[:,2] * -zscale
            v[:,4] = v[:,0] * -xscale
        else: # not square - ignore rotation
            v[:,3] = v[:,0] *  xscale
            v[:,4] = v[:,2] * -zscale
    else:	# explicit st co-ords
        v[:,3:5] = v[:,5:7]

    # if __debug__:	# dump mesh
    #     print basename(texture), wrap
    #     for x in v[:,:5]:
    #         for y in x:
    #             print "%.2f" % y,
    #         print
    #     assert len(v) == sum([len(p) for p in patch]), "%d %d" % (len(v), sum([len(p) for p in patch]))
    #     print

    mesh[(texture,wrap)].append(v[:,:5])


def writeDSF(dsfdir, key, placements, netfile):
    (south,west)=key
    tiledir=join(dsfdir, "%+02d0%+03d0" % (int(south/10), int(west/10)))
    tilename=join(tiledir, "%+03d%+04d" % (south,west))
    if exists(tilename+'.dsf'):
        if exists(tilename+'.dsf.bak'): unlink(tilename+'.dsf.bak')
        rename(tilename+'.dsf', tilename+'.dsf.bak')
    if exists(tilename+'.DSF'):
        if exists(tilename+'.DSF.BAK'): unlink(tilename+'.DSF.BAK')
        rename(tilename+'.DSF', tilename+'.DSF.BAK')
    if not (placements): return
    if not isdir(tiledir): mkdir(tiledir)

    tmp=join(gettempdir(), "%+03d%+04d.txt" % (south,west))
    h=file(tmp, 'wt')
    h.write('I\n800\nDSF2TEXT\n\n')
    h.write('PROPERTY\tsim/planet\tearth\n')
    h.write('PROPERTY\tsim/overlay\t1\n')
    h.write('PROPERTY\tsim/require_agpoint\t1/0\n')
    h.write('PROPERTY\tsim/require_object\t1/0\n')
    h.write('PROPERTY\tsim/require_facade\t1/0\n')
    h.write('PROPERTY\tsim/creation_agent\t%s %4.2f\n' % (appname, appversion))

    objects=[]
    polygons=[]
    excludetoken = dict((v,k) for k,v in Exclude.NAMES.iteritems())
    for placement in placements:
        if isinstance(placement,Object):
            objects.append(placement)
        elif isinstance(placement,Exclude):
            minlon = min([node.lon for node in placement.nodes[0]])
            maxlon = max([node.lon for node in placement.nodes[0]])
            minlat = min([node.lat for node in placement.nodes[0]])
            maxlat = max([node.lat for node in placement.nodes[0]])
            h.write('PROPERTY\t%s\t%.8f/%.8f/%.8f/%.8f\n' % (excludetoken[placement.name], minlon, minlat, maxlon, maxlat))
        else:
            polygons.append(placement)

    # must be final properties
    h.write('PROPERTY\tsim/west\t%d\n' %   west)
    h.write('PROPERTY\tsim/east\t%d\n' %  (west+1))
    h.write('PROPERTY\tsim/north\t%d\n' % (south+1))
    h.write('PROPERTY\tsim/south\t%d\n' %  south)
    h.write('\n')
    h.write('DIVISIONS\t%d\n' % DSFdivisions)
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
            junctions[(node.lon, node.lat)]=True
    jnum=1
    for j in junctions.keys():
        junctions[j]=jnum
        jnum+=1

    for obj in objects:
        h.write(obj.write(objdefs.index(obj.name), south, west))
    if objects: h.write('\n')
    
    for poly in polygons:
        if not isinstance(poly, Network):
            h.write(poly.write(polydefs.index(poly.name), south, west))
    if polydefs: h.write('\n')

    for poly in polygons:
        if not isinstance(poly, Network): continue
        p=poly.nodes[0][0]
        h.write(p.write(poly.definition.type_id, junctions[(p.lon, p.lat)]))
        for p in poly.nodes[0][1:-1]:
            h.write(p.write(0, 0))
        p=poly.nodes[0][-1]
        h.write(p.write(0, junctions[(p.lon, p.lat)]))
    if junctions: h.write('\n')
    
    h.close()
    if platform=='win32':
        # No reliable way to encode non-ASCII pathnames, so use tempdir which appears safe. This is apparently fixed in Python 3.
        tmp2=join(gettempdir(), "%+03d%+04d.dsf" % (south,west))
        cmds=('%s -text2dsf "%s" "%s"' % (dsftool, tmp, tmp2)).encode('mbcs')
    else:
        # See "QUOTING" in bash(1)
        cmds='%s -text2dsf "%s" "%s.dsf"' % (dsftool, tmp, tilename.replace('\\','\\\\').replace('"','\\"').replace("$", "\\$").replace("`", "\\`"))
    if __debug__: print cmds
    (i,o,e)=popen3(cmds)
    i.close()
    err=o.read()
    err+=e.read()
    o.close()
    e.close()
    if platform=='win32' and exists(join(gettempdir(), "%+03d%+04d.dsf" % (south,west))):
        rename(tmp2, tilename+'.dsf')
    if not exists(tilename+'.dsf'):
        if exists(tilename+'.dsf.bak'):
            rename(tilename+'.dsf.bak', tilename+'.dsf')
        elif exists(tilename+'.DSF.BAK'):
            rename(tilename+'.DSF.BAK', tilename+'.DSF')
        if __debug__: print err
        err=err.strip().split('\n')
        coords=''
        for line in err:
            if line.lower().startswith('error'):	# first error line seems to be the most/only useful
                err=line+'\n'+coords			# previous line holds polygon point co-ords
                break
            else:
                coords=line
        else:
            if len(err)>1 and err[-1].startswith('('):
                err=err[-2].strip()	# last line reports line number within source code - not useful
            else:
                err=err[0].strip()	# only one line - report it
        raise IOError, (0, err)
    if not __debug__: unlink(tmp)	# Delete temp file if successful. TODO mail this file
