#
# operations on the terrain mesh: finding the elevation at a point and draping polygons over terrain.
#
# tessellation is slow, and calling the GLU tessellator from Python is very slow. So we implement a number
# of specialised draping functions to try and minimise a) the number of invovations of the GLU tessellator;
# and b) the number of contours fed into each invocation.
#

import gc
from collections import defaultdict	# Requires Python 2.5
from math import sin, cos, floor, radians
from sys import exc_info, maxint
import time
import numpy
from numpy import ndarray, array, array_equal, choose, empty, logical_and, reciprocal, vstack, int32, float32, float64
if __debug__:
    from traceback import print_exc

from OpenGL.GLU import *


DSFdivisions = 32	# WED 1.1 and DSFTool encode at 8. WED 1.2 encodes at 32
resolution = DSFdivisions * 65535
minres = 1.0/resolution
maxres = 1-minres
minhdg=360.0/65535

onedeg = 111320.0	# approx 1 degree of longitude at equator (60nm) [m]. Radius from sim/physics/earth_radius_m


def round2res(x):
    i=floor(x)
    return i+round((x-i)*resolution,0)*minres


class BBox:

    def __init__(self, minx=maxint, maxx=-maxint, minz=maxint, maxz=-maxint):
        self.minx=minx
        self.maxx=maxx
        self.minz=minz
        self.maxz=maxz

    def intersects(self, other):
        return ((self.minx <= other.maxx) and (self.maxx > other.minx) and
                (self.minz <= other.maxz) and (self.maxz > other.minz))

    def inside(self, x, z):
        return ((self.minx <= x < self.maxx) and
                (self.minz <= z < self.maxz))

    def include(self, x, z):
        self.maxx=max(self.maxx, x)
        self.minx=min(self.minx, x)
        self.maxz=max(self.maxz, z)
        self.minz=min(self.minz, z)

    def __str__(self):
        return '<x:%s,%s z:%s,%s>' % (self.minx,self.maxx,self.minz,self.maxz)


# abstract base class used as a container for common functionality
class ElevationMeshBase:

    BADHEIGHT = 1.0	# Flag to indicate that tri vertex elevation comes from polygon not mesh
    BADUV = -1.0	# Flag to indicate that tri vertex UV is invalid

    # Tessellators for draped polygons

    @staticmethod
    def tessvertex(vertex, data):
        data.append(vertex)

    @staticmethod
    def tessedge(flag):
        pass	# dummy


    # for feeding a polygon with assigned UVs into a GLU tessellator
    def tessellatenodes(self, tess, nodes):

        # assign UV coordinates
        points = array([p.loc for w in nodes for p in w], float64)
        texturedpoints = empty((len(points), 6), float32)
        texturedpoints[:,0:3] = points
        texturedpoints[:,3] = [p.rest[0] for w in nodes for p in w]
        texturedpoints[:,4] = [p.rest[1] for w in nodes for p in w]
        texturedpoints[:,5] = ElevationMeshBase.BADHEIGHT

        # Tessellate
        i = 0
        for w in nodes:
            gluTessBeginContour(tess)
            for p in w:
                gluTessVertex(tess, points[i], texturedpoints[i])
                i += 1
            gluTessEndContour(tess)

    @staticmethod
    def tesscombinetris(coords, vertex, weight):

        if vertex[2] is None:
            # common case - two co-located corners of adjacent mesh or polygon triangles
            return vertex[0]

        # since we're draping over a mesh we want to take elevation from the mesh
        if vertex[2][5]==ElevationMeshBase.BADHEIGHT or vertex[3][5]==ElevationMeshBase.BADHEIGHT:
            height = (weight[0]*vertex[0][1] + weight[1]*vertex[1][1]) / (weight[0] + weight[1])
            # draped tris in objs can be self-intersecting, in which case propagate the BADHEIGHT flag
            heightflag = (vertex[0][5]==ElevationMeshBase.BADHEIGHT or vertex[1][5]==ElevationMeshBase.BADHEIGHT) and ElevationMeshBase.BADHEIGHT or 0
        else:
            height = (weight[2]*vertex[2][1] + weight[3]*vertex[3][1]) / (weight[2] + weight[3])
            heightflag = 0

        # take UVs from polygon edge
        if vertex[2][5]==ElevationMeshBase.BADUV or vertex[3][5]==ElevationMeshBase.BADUV:
            invweight = 1 / (weight[0] + weight[1])
            # g2xpl-generated meshes can be self-intersecting in which case propagate the BADUV flag (and in preference to the BADHEIGHT flag)
            return array([coords[0], height, coords[2],
                          (weight[0]*vertex[0][3] + weight[1]*vertex[1][3]) * invweight,
                          (weight[0]*vertex[0][4] + weight[1]*vertex[1][4]) * invweight,
                          (vertex[0][5]==ElevationMeshBase.BADUV or vertex[1][5]==ElevationMeshBase.BADUV) and ElevationMeshBase.BADUV or heightflag], float32)
        else:
            invweight = 1 / (weight[2] + weight[3])
            return array([coords[0], height, coords[2],
                          (weight[2]*vertex[2][3] + weight[3]*vertex[3][3]) * invweight,
                          (weight[2]*vertex[2][4] + weight[3]*vertex[3][4]) * invweight, heightflag], float32)

    @staticmethod
    def tesscombinetrisd(coords, vertex, weight):
        try:
            if vertex[2] is None:
                # assert array_equal(vertex[0], vertex[1]), vertex	# can have small discontinuities due to limits of float32
                return vertex[0]
            else:
                # print weight.tolist()
                # for v in vertex: print v.tolist()
                r = ElevationMeshBase.tesscombinetris(coords, vertex, weight)
                # print r.tolist(), '->'
                # print
                return r
        except:
            print_exc()


    # for feeding a draped polygon with scaled UV and potentially holes into a GLU tessellator
    def tessellatepoly(self, tess, poly, hscale, vscale, hdg):

        # project UV coordinates over the polygon
        points = array([p for w in poly for p in w], float64)
        ch = cos(radians(hdg))
        sh = sin(radians(hdg))
        texturedpoints = empty((len(points), 6), float32)
        texturedpoints[:,0:3] = points
        texturedpoints[:,3] = (texturedpoints[:,0] * ch + texturedpoints[:,2] * sh) / hscale
        texturedpoints[:,4] = (texturedpoints[:,0] * sh - texturedpoints[:,2] * ch) / vscale
        texturedpoints[:,5] = ElevationMeshBase.BADHEIGHT

        # Tessellate
        i = 0
        for w in poly:
            gluTessBeginContour(tess)
            for p in w:
                gluTessVertex(tess, points[i], texturedpoints[i])
                i += 1
            gluTessEndContour(tess)

    @staticmethod
    def tesscombinepoly(coords, vertex, weight):

        if vertex[2] is None:
            # common case - two co-located corners of adjacent mesh triangles
            return vertex[0]

        # since we're draping over a mesh we want to take elevation from the mesh
        if vertex[2][5] or vertex[3][5]:	# BADHEIGHT
            assert not vertex[0][5] and not vertex[1][5], vertex
            invweight = 1 / (weight[0] + weight[1])
            return array([coords[0],
                          (weight[0]*vertex[0][1] + weight[1]*vertex[1][1]) * invweight,
                          coords[2],
                          (weight[0]*vertex[0][3] + weight[1]*vertex[1][3]) * invweight,
                          (weight[0]*vertex[0][4] + weight[1]*vertex[1][4]) * invweight, 0], float32)
        else:
            invweight = 1 / (weight[2] + weight[3])
            return array([coords[0],
                          (weight[2]*vertex[2][1] + weight[3]*vertex[3][1]) * invweight,
                          coords[2],
                          (weight[2]*vertex[2][3] + weight[3]*vertex[3][3]) * invweight,
                          (weight[2]*vertex[2][4] + weight[3]*vertex[3][4]) * invweight, 0], float32)


    # like tesellatepoly, but multiple polys at once, goes in instance VBO so 5 coords, and with constant UV
    def tessellateapt(self, tess, polys, u, v):

        # assign UV coordinates to the polygon(s)
        # if __debug__: clock=time.clock()	# Processor time
        points = array([p for w in polys for p in w], float64)
        texturedpoints = empty((len(points), 6), float32)
        texturedpoints[:,0:3] = points
        texturedpoints[:,3] = u
        texturedpoints[:,4] = v
        texturedpoints[:,5] = ElevationMeshBase.BADHEIGHT
        # if __debug__: print "%6.3f time in setup" % (time.clock()-clock)

        # Tessellate
        # if __debug__: clock=time.clock()	# Processor time
        i = 0
        for w in polys:
            gluTessBeginContour(tess)
            for p in w:
                gluTessVertex(tess, points[i], texturedpoints[i])
                i += 1
            gluTessEndContour(tess)
        # if __debug__: print "%6.3f time in contours" % (time.clock()-clock)

    @staticmethod
    def tesscombineapt(coords, vertex, weight):

        if vertex[2] is None:
            # common case - two co-located corners of adjacent mesh triangles
            return vertex[0]

        # since we're draping over a mesh we want to take elevation from the mesh
        if vertex[2][5] or vertex[3][5]:	# BADHEIGHT
            # airport polygons can intersect, so sometimes neither edge will have good data
            return array([coords[0],
                          (weight[0]*vertex[0][1] + weight[1]*vertex[1][1]) / (weight[0] + weight[1]),
                          coords[2], vertex[0][3], vertex[0][4], (vertex[0][5] or vertex[1][5]) and ElevationMeshBase.BADHEIGHT or 0], float32)
        else:
            return array([coords[0],
                          (weight[2]*vertex[2][1] + weight[3]*vertex[3][1]) / (weight[2] + weight[3]),
                          coords[2], vertex[0][3], vertex[0][4], 0], float32)


# for when no terrain
class DummyElevationMesh(ElevationMeshBase):

    def __init__(self, tile):

        self.flat = True	# no elevation data

        self.polytess = gluNewTess()
        gluTessNormal(self.polytess, 0, -1, 0)
        gluTessProperty(self.polytess, GLU_TESS_WINDING_RULE, GLU_TESS_WINDING_NEGATIVE)
        gluTessCallback(self.polytess, GLU_TESS_VERTEX_DATA,  self.tessvertex)
        gluTessCallback(self.polytess, GLU_TESS_COMBINE,      self.tesscombinepoly)
        gluTessCallback(self.polytess, GLU_TESS_EDGE_FLAG,    self.tessedge)	# no strips

        self.tristess = gluNewTess()
        gluTessNormal(self.tristess, 0, -1, 0)
        gluTessProperty(self.tristess, GLU_TESS_WINDING_RULE, GLU_TESS_WINDING_NEGATIVE)
        gluTessCallback(self.tristess, GLU_TESS_VERTEX_DATA,  self.tessvertex)
        if __debug__:
            gluTessCallback(self.tristess, GLU_TESS_COMBINE,  self.tesscombinetrisd)
        else:
            gluTessCallback(self.tristess, GLU_TESS_COMBINE,  self.tesscombinetris)
        gluTessCallback(self.tristess, GLU_TESS_EDGE_FLAG,    self.tessedge)	# no strips

        self.apttess = gluNewTess()
        gluTessNormal(self.apttess, 0, -1, 0)
        gluTessProperty(self.apttess,  GLU_TESS_WINDING_RULE, GLU_TESS_WINDING_NEGATIVE)
        gluTessCallback(self.apttess,  GLU_TESS_VERTEX_DATA,  self.tessvertex)
        gluTessCallback(self.apttess,  GLU_TESS_COMBINE,      self.tesscombineapt)
        gluTessCallback(self.apttess,  GLU_TESS_EDGE_FLAG,    self.tessedge)	# no strips

    def getbox(self, abox):
        return None

    def height(self, x, z, meshtris=None):
        return 0

    def drapeapt(self, polys, u, v, box):
        outtris=[]
        gluTessBeginPolygon(self.apttess, outtris)
        self.tessellateapt(self.apttess, polys, u, v)
        gluTessEndPolygon(self.apttess)
        return outtris


class ElevationMesh(ElevationMeshBase):

    DIVISIONS = 256	# arbitrary - diminishing returns after this with smaller buckets

    def __init__(self, tile, tris):

        self.flat = False	# Have elevation mesh data
        self.lasttri = None

        self.polytess = gluNewTess()
        gluTessNormal(self.polytess, 0, -1, 0)
        gluTessProperty(self.polytess, GLU_TESS_WINDING_RULE, GLU_TESS_WINDING_ABS_GEQ_TWO)
        gluTessCallback(self.polytess, GLU_TESS_VERTEX_DATA,  self.tessvertex)
        gluTessCallback(self.polytess, GLU_TESS_COMBINE,      self.tesscombinepoly)
        gluTessCallback(self.polytess, GLU_TESS_EDGE_FLAG,    self.tessedge)	# no strips

        self.tristess = gluNewTess()
        gluTessNormal(self.tristess, 0, -1, 0)
        gluTessProperty(self.tristess, GLU_TESS_WINDING_RULE, GLU_TESS_WINDING_ABS_GEQ_TWO)
        gluTessCallback(self.tristess, GLU_TESS_VERTEX_DATA,  self.tessvertex)
        if __debug__:
            gluTessCallback(self.tristess, GLU_TESS_COMBINE,  self.tesscombinetrisd)
        else:
            gluTessCallback(self.tristess, GLU_TESS_COMBINE,  self.tesscombinetris)
        gluTessCallback(self.tristess, GLU_TESS_EDGE_FLAG,    self.tessedge)	# no strips

        self.apttess = gluNewTess()
        gluTessNormal(self.apttess, 0, -1, 0)
        gluTessProperty(self.apttess,  GLU_TESS_WINDING_RULE, GLU_TESS_WINDING_ABS_GEQ_TWO)
        gluTessCallback(self.apttess,  GLU_TESS_VERTEX_DATA,  self.tessvertex)
        gluTessCallback(self.apttess,  GLU_TESS_COMBINE,      self.tesscombineapt)
        gluTessCallback(self.apttess,  GLU_TESS_EDGE_FLAG,    self.tessedge)	# no strips

        (south, west) = tile
        self.divheight = onedeg/ElevationMesh.DIVISIONS
        self.divwidth  =(onedeg/ElevationMesh.DIVISIONS) * cos(radians(floor(abs(south+0.5))))

        # tris is an array of points [x,y,z,u,v], where every 3 points makes a triangle
        assert tris.shape[1] == 5 and not tris.shape[0] % 3, tris.shape

        if __debug__: clock=time.clock()	# Processor time

        # Find 2D barycentric vectors, centred on p1 (A) - http://www.blackpawn.com/texts/pointinpoly/
        self.tris = empty(len(tris)/3, dtype=[('p1',float32,(3,)), ('p2',float32,(3,)), ('p3',float32,(3,)),
                                              ('v0',float32,(2,)), ('v1',float32,(2,)),
                                              ('dot00',float32), ('dot01',float32), ('dot11',float32), ('invDenom',float32)])
        self.tris['p1'] = tris[0::3,:3]	# drop uv
        self.tris['p2'] = tris[1::3,:3]
        self.tris['p3'] = tris[2::3,:3]
        self.tris['v0'] = v0 = self.tris['p3'][:,::2] - self.tris['p1'][:,::2]	# C - A
        self.tris['v1'] = v1 = self.tris['p2'][:,::2] - self.tris['p1'][:,::2]	# B - A
        self.tris['dot00'] = numpy.sum(v0*v0, axis=1)		# v0.v0
        self.tris['dot01'] = numpy.sum(v0*v1, axis=1)		# v0.v1
        self.tris['dot11'] = numpy.sum(v1*v1, axis=1)		# v1.v1
        self.tris['invDenom'] = self.tris['dot00'] * self.tris['dot11'] - self.tris['dot01'] * self.tris['dot01']
        if not numpy.all(self.tris['invDenom']):
            self.tris = self.tris[self.tris['invDenom'] != 0]	# filter out degenerate triangles e.g. KSEA Demo Terrain
        self.tris['invDenom'] = reciprocal(self.tris['invDenom'])

        # Find grid buckets
        n = len(self.tris)
        tris = self.tris.view(float32).reshape((n,-1))	# filtered coords
        x = (tris[:,0:9:3] / self.divwidth + ElevationMesh.DIVISIONS/2).astype(int)
        z = (tris[:,2:9:3] / self.divheight+ ElevationMesh.DIVISIONS/2).astype(int)
        xr = empty((n,2),int)	# [min,max+1]
        zr = empty((n,2),int)	# [min,max+1]
        xr[:,0] = numpy.minimum(numpy.minimum(x[:,0], x[:,1]), x[:,2])
        zr[:,0] = numpy.minimum(numpy.minimum(z[:,0], z[:,1]), z[:,2])
        # points lying exactly on top left grid boundary are rounded down
        xr[:,1] = numpy.minimum(numpy.maximum(numpy.maximum(x[:,0], x[:,1]), x[:,2]) + 1, ElevationMesh.DIVISIONS)
        zr[:,1] = numpy.minimum(numpy.maximum(numpy.maximum(z[:,0], z[:,1]), z[:,2]) + 1, ElevationMesh.DIVISIONS)
        if __debug__:
            print "%6.3f time to calculate mesh " % (time.clock()-clock)
            for i in range(n):
                assert xr[i,0] >= 0 and xr[i,1] <= ElevationMesh.DIVISIONS, "%d %s %s" % (i, xr[i], tris[i])
                assert zr[i,0] >= 0 and zr[i,1] <= ElevationMesh.DIVISIONS, "%d %s %s" % (i, zr[i], tris[i])

        self.buckets = [[list() for i in range(ElevationMesh.DIVISIONS)] for j in range(ElevationMesh.DIVISIONS)]

        gc.disable()
        # assign indices to buckets
        for i in range(n):
            for x in range(*xr[i]):
                for z in range(*zr[i]):
                    self.buckets[z][x].append(i)
        gc.enable()

        # if __debug__:
        #     for i in range(ElevationMesh.DIVISIONS):
        #         print [len(self.buckets[i][j]) for j in range(ElevationMesh.DIVISIONS)]

        if __debug__: print "%6.3f time in ElevationMesh" % (time.clock()-clock)

    def height(self, x, z, meshtris=None):

        if __debug__: clock=time.clock()	# Processor time
        if self.lasttri:
            tri = self.lasttri
            v2 = (x-tri['p1'][0], z-tri['p1'][2])
            dot02 = tri['v0'][0] * v2[0] + tri['v0'][1] * v2[1]
            dot12 = tri['v1'][0] * v2[0] + tri['v1'][1] * v2[1]
            u = (tri['dot11'] * dot02 - tri['dot01'] * dot12) * tri['invDenom']
            v = (tri['dot00'] * dot12 - tri['dot01'] * dot02) * tri['invDenom']
            if u>=0 and v>=0 and u+v<=1:
                #if __debug__: print "%6.3f time in height (lasttri)" % (time.clock()-clock)
                return tri['p1'][1] + u * (tri['p3'][1] - tri['p1'][1]) + v * (tri['p2'][1] - tri['p1'][1])	# P = A + u * (C - A) + v * (B - A)

        if meshtris is None:
            i = int(z/self.divheight + ElevationMesh.DIVISIONS/2)
            j = int(x/self.divwidth  + ElevationMesh.DIVISIONS/2)
            if not (0<=i<ElevationMesh.DIVISIONS and 0<=j<ElevationMesh.DIVISIONS):
                #if __debug__: print "%6.3f time in height (outside)" % (time.clock()-clock)
                return 0
            tris = self.tris[self.buckets[i][j]]
        else:
            tris = meshtris

        # 2D Barycentric vectors, centred on p1 (A) - http://www.blackpawn.com/texts/pointinpoly/
        v2 = array([x,z], float32) - tris['p1'][:,::2]	# P - A

        # dot products
        dot02 = numpy.sum(tris['v0'] * v2, axis=1)
        dot12 = numpy.sum(tris['v1'] * v2, axis=1)

        result = empty((len(tris)), dtype=[('u',float32), ('v',float32)])
        result['u'] = (tris['dot11'] * dot02 - tris['dot01'] * dot12) * tris['invDenom']
        result['v'] = (tris['dot00'] * dot12 - tris['dot01'] * dot02) * tris['invDenom']

        # Check if point is in any triangle
        hits = logical_and(logical_and(result['u'] >= 0, result['v'] >= 0), result['u'] + result['v'] <= 1)

        if hits.any():
            # Take the first hit
            (u,v) = result[hits][0]
            self.lasttri = tri = tris[hits][0]
            #if __debug__: print "%6.3f time in height" % (time.clock()-clock)
            return tri['p1'][1] + u * (tri['p3'][1] - tri['p1'][1]) + v * (tri['p2'][1] - tri['p1'][1])	# P = A + u * (C - A) + v * (B - A)
        else:
            return 0	# shouldn't happen

    # get the tris in the grid buckets under a bounding box
    def getbox(self, abox):

        if __debug__: clock=time.clock()	# Processor time
        minx = max(int(floor(abox.minx / self.divwidth))  + ElevationMesh.DIVISIONS/2, 0)
        maxx = min(int(floor(abox.maxx / self.divwidth))  + ElevationMesh.DIVISIONS/2 + 1, ElevationMesh.DIVISIONS)
        minz = max(int(floor(abox.minz / self.divheight)) + ElevationMesh.DIVISIONS/2, 0)
        maxz = min(int(floor(abox.maxz / self.divheight)) + ElevationMesh.DIVISIONS/2 + 1, ElevationMesh.DIVISIONS)

        if minx>=ElevationMesh.DIVISIONS or maxx<=0 or minz>=ElevationMesh.DIVISIONS or maxz<=0:
            return empty((9,),float32)	# all off mesh
        elif minx+1==maxx and minz+1==maxz:	# common case: just one box
            indices = self.buckets[minz][minx]
        else:
            indices = set()
            for z in range(minz,maxz):
                for x in range(minx,maxx):
                    indices.update(self.buckets[z][x])
            indices = list(indices)
        if indices:
            tris = self.tris[indices]
            #if __debug__: print "%6.3f time in getbox" % (time.clock()-clock)
        else:
            tris = empty((9,),float32)	# shouldn't happen
            if __debug__: print "%6.3f time in getbox (no tris)" % (time.clock()-clock)
        return tris


    # tesselator for draping an polygon with potentially multiple windings, with scaled UVs
    def drapepoly(self, poly, hscale, vscale, hdg, box):

        tess = self.polytess

        # tesselator is expensive - minimise mesh triangles
        if isinstance(box,BBox):
            meshtris = self.getbox(box)
        else:
            assert isinstance(box, ndarray), box
            meshtris = box

        # just the points, in reverse order since polygons are winded negatively
        meshtris = meshtris.view(float32).reshape((len(meshtris),-1))[:,:9].reshape((-1,3))[::-1]

        # project UV coordinates over the mesh
        ch = cos(radians(hdg))
        sh = sin(radians(hdg))
        coords = meshtris.astype(float64)
        texturedtris = empty((len(meshtris), 6), float32)
        texturedtris[:,0:3] = meshtris
        texturedtris[:,3] = (texturedtris[:,0] * ch + texturedtris[:,2] * sh) / hscale
        texturedtris[:,4] = (texturedtris[:,0] * sh - texturedtris[:,2] * ch) / vscale
        texturedtris[:,5] = 0

        # Tessellate
        outtris=[]
        gluTessBeginPolygon(tess, outtris)
        for i in range(0,len(meshtris),3):
            gluTessBeginContour(tess)
            for j in range(i,i+3):
                gluTessVertex(tess, coords[j], texturedtris[j])
            gluTessEndContour(tess)
        self.tessellatepoly(tess, poly, hscale, vscale, hdg)
        gluTessEndPolygon(tess)
        return outtris


    # tesselator for draping a set of tris with assigned UVs
    # performance relies on assumption that there are only a few (typically 2) input tris (but up to 100s of mesh tris)
    def drapetris(self, tris, box, tess=None):

        tess = tess or self.tristess	# use tls tessellator if supplied

        # tesselator is expensive - minimise mesh triangles
        if isinstance(box,BBox):
            meshtris = self.getbox(box)
        else:
            assert isinstance(box, ndarray), box
            meshtris = box

        # just the points
        meshtris = meshtris.view(float32).reshape((len(meshtris),-1))[:,:9].reshape((-1,3))
        meshcoords = meshtris.astype(float64)
        texturedtris = empty((len(meshtris), 6), float32)
        texturedtris[:,0:3] = meshtris
        texturedtris[:,3:5] = 0.5		# in case of error supply something vaguely sensible for UV
        texturedtris[:,5] = ElevationMeshBase.BADUV	# outside of the input polygon

        # Assign UV coordinates to those mesh vertices that fall into each input triangle
        # tris is an array or list of points [x,y,z,u,v,0], where every 3 points makes a triangle
        i=0
        while i < len(tris):
            # Find 2D barycentric vectors, centred on p1 (A) - http://www.blackpawn.com/texts/pointinpoly/
            (x1,y1,z1,s1,t1,d) = tris[i]
            (x2,y2,z2,s2,t2,d) = tris[i+1]
            (x3,y3,z3,s3,t3,d) = tris[i+2]
            v0 = (x3-x1, z3-z1)			# C - A
            v1 = (x2-x1, z2-z1)			# B - A
            dot00 = v0[0]*v0[0] + v0[1]*v0[1]	# v0.v0
            dot01 = v0[0]*v1[0] + v0[1]*v1[1]	# v0.v1
            dot11 = v1[0]*v1[0] + v1[1]*v1[1]	# v1.v1
            denom = dot00 * dot11 - dot01 * dot01
            if not denom:	# tessellator can occasionally produce degenerate triangles - skip them
                if __debug__: print 'degenerate:', tris[i:i+3]
                tris.pop(i); tris.pop(i); tris.pop(i)
                continue
            invDenom = 1/denom
            i += 3

            # Determine which mesh vertices fall into this polygon triangle and assign UVs to them
            # Note: if a mesh triangle falls within this polygon triangle, so will at least 5 others from adjacent mesh triangles
            v2 = meshtris[:,::2] - (x1, z1)	# P - A
            dot02 = numpy.sum(v0 * v2, axis=1)	# v0.v2
            dot12 = numpy.sum(v1 * v2, axis=1)	# v1.v2
            # confusingly, u & v here are parameters, not UV coordinates
            u = (dot11 * dot02 - dot01 * dot12) * invDenom
            v = (dot00 * dot12 - dot01 * dot02) * invDenom
            hits = logical_and(logical_and(u >= 0, v >= 0), u + v <= 1)
            texturedtris[:,3:][hits] = (s1, t1, 0) + u[hits].reshape((-1,1)) * (s3-s1, t3-t1, 0) + v[hits].reshape((-1,1)) * (s2-s1, t2-t1, 0)	# P = A + u * (C - A) + v * (B - A)

        if not len(tris): return []	# all degenerate
        tris = array(tris, dtype=float32)
        tris[:,5] = ElevationMeshBase.BADHEIGHT
        pointcoords = tris[:,0:3].astype(float64)

        outtris=[]
        gluTessBeginPolygon(tess, outtris)
        # mesh
        for i in range(0,len(meshtris),3):
            gluTessBeginContour(tess)
            for j in range(i,i+3):
                gluTessVertex(tess, meshcoords[j], texturedtris[j])
            gluTessEndContour(tess)
        # polygon
        for i in range(0,len(tris),3):
            gluTessBeginContour(tess)
            for j in range(i,i+3):
                gluTessVertex(tess, pointcoords[j], tris[j])
            gluTessEndContour(tess)
        gluTessEndPolygon(tess)
        return outtris


    # like drape, but multiple polys at once, with constant UV
    def drapeapt(self, polys, u, v, box):

        tess = self.apttess

        # tesselator is expensive - minimise mesh triangles
        if isinstance(box,BBox):
            meshtris = self.getbox(box)
        else:
            assert isinstance(box, ndarray), box
            meshtris = box

        # just the points, in reverse order since polygons are winded negatively
        meshtris = meshtris.view(float32).reshape((len(meshtris),-1))[:,:9].reshape((-1,3))[::-1]

        # assign UV coordinates to the mesh
        coords = meshtris.astype(float64)
        texturedtris = empty((len(meshtris), 6), float32)
        texturedtris[:,0:3] = meshtris
        texturedtris[:,3] = u
        texturedtris[:,4] = v
        texturedtris[:,5] = 0

        # Tessellate
        outtris=[]
        gluTessBeginPolygon(tess, outtris)
        for i in range(0,len(meshtris),3):
            gluTessBeginContour(tess)
            for j in range(i,i+3):
                gluTessVertex(tess, coords[j], texturedtris[j])
            gluTessEndContour(tess)
        self.tessellateapt(tess, polys, u, v)
        gluTessEndPolygon(tess)
        return outtris

