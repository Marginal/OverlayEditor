# Derived classes expected to have following members:
# __init__
# __str__
# clone -> make a new copy, minus layout
# copy -> make a new copy, minus layout, moved offset
# position -> returns (x,z) position relative to centre of enclosing tile
# load -> read definition
# location -> returns (average) lat/lon
# locationstr -> returns info suitable for display in status bar
# inside -> whether inside a lat,lon bounding box
# layout -> fit to terrain, allocate into VBO(s)
# clearlayout -> clear above
# flush -> clear dynamic VBO allocation (but retain layout) - note doesn't clear instance VBO allocation since def may be shared
# move -> move and layout
# movenode -> move - no layout
# updatenode -> move node - no layout
# updatehandle -> move node bezier control - no layout
# pick_dynamic -> pick geometry in dynamic VBO, including child geometry
# pick_nodes -> pick nodes of selected polygon
# draw_nodes -> draw highlighted
# bucket_dynamic -> callback to enumerate drawing data in dynamic VBO, *not* including children which get separate callbacks

# Clutter (except for DrapedImage) not in the current tile retain their layout, but not their VBO allocation.

import gc
from collections import defaultdict
from math import atan2, ceil, cos, degrees, floor, hypot, modf, pi, radians, sin, tan
import numpy
from numpy import array, array_equal, concatenate, dot, empty, nonzero, float32, float64
from os.path import join
from sys import maxint
if __debug__:
    import time
    from traceback import print_exc

from OpenGL.GL import *
from OpenGL.GLU import *
from OpenGL.extensions import alternate
from OpenGL.GL.ARB.occlusion_query import *
glBeginQuery = alternate(glBeginQuery, glBeginQueryARB)
glEndQuery = alternate(glEndQuery, glEndQueryARB)

from clutterdef import ClutterDef, ObjectDef, AutoGenPointDef, PolygonDef, DrapedDef, ExcludeDef, FacadeDef, ForestDef, LineDef, StringDef, NetworkDef, ObjectFallback, AutoGenFallback, DrapedFallback, FacadeFallback, ForestFallback, LineFallback, StringFallback, NetworkFallback, SkipDefs, COL_UNPAINTED, COL_POLYGON, COL_FOREST, COL_EXCLUDE, COL_NONSIMPLE, COL_SELECTED, COL_SELBEZ, COL_SELBEZHANDLE, COL_SELNODE
from elevation import BBox, onedeg, maxres, minres, minhdg, resolution, round2res, ElevationMeshBase
from nodes import Node, BezierNode, ParamNode, BezierParamNode, NetworkNode
from palette import PaletteEntry
from prefs import Prefs, prefs

f2m=0.3041	# 1 foot [m] (not accurate, but what X-Plane appears to use for airport layout)
twopi=pi*2
piby2=pi/2


class Clutter:

    def __init__(self, name, lat=None, lon=None):
        self.name=name.decode()	# virtual name ASCII only - may raise UnicodeError
        self.definition=None
        self.lat=lat		# For centreing etc
        self.lon=lon
        self.vertexcache = None	# link to global cache for allocating resources
        self.dynamic_data=None	# Data for inclusion in VBO
        self.base=None		# Offset when allocated in VBO
        self.parent = None	# parent if this is a child
        self.placements=[]	# child object placements
        self.bbox = None	# bounding box (x,z)
        
    @staticmethod
    def position(tile, lat, lon):
        # returns (x,z) position relative to centre of enclosing tile
        # z is positive south
        return ((lon-tile[1]-0.5)*onedeg*cos(radians(lat)),
                (0.5-(lat-tile[0]))*onedeg)

    @staticmethod
    def latlondisp(dms, lat, lon):
        if dms:
            sgnlat = lat>=0 and 'N' or 'S'
            abslat=abs(lat)
            mmlat=(abslat-int(abslat)) * 60.0
            sslat=(mmlat-int(mmlat)) * 60.0
            sgnlon = lon>=0 and 'E' or 'W'
            abslon=abs(lon)
            mmlon=(abslon-int(abslon)) * 60.0
            sslon=(mmlon-int(mmlon)) * 60.0
            return u'Lat: %s%02d\u00B0%02d\u2032%07.4f\u2033  Lon: %s%03d\u00B0%02d\u2032%07.4f\u2033' % (sgnlat, abslat, mmlat, sslat, sgnlon, abslon, mmlon, sslon)
        else:
            return "Lat: %.7f  Lon: %.7f" % (lat, lon)

    @staticmethod
    def distancedisp(imp, dist):
        if imp:
            (i,f) = modf(dist * (1/0.3048))
            return u'%d\u2032%d\u2033' % (f, round(i*12,0))
        else:
            return '%.2fm' % dist


class Object(Clutter):

    origin=array([0,0,0],float32)

    @staticmethod
    def factory(name, lat, lon, hdg):
        "creates and initialises appropriate Object subclass based on file extension"
        if name.lower()[-4:]==AutoGenPointDef.AGP:
            return AutoGenPoint(name, lat, lon, hdg)
        else:
            return Object(name, lat, lon, hdg)

    def __init__(self, name, lat, lon, hdg, parent=None):
        Clutter.__init__(self, name, lat, lon)
        self.parent = parent
        self.hdg=hdg
        self.y=0
        self.matrix=None

    def __str__(self):
        return '<Object "%s" %12.7f %11.7f %d %s>' % (
            self.name, self.lat, self.lon, self.hdg, self.y)

    def clone(self):
        return self.__class__(self.name, self.lat, self.lon, self.hdg)

    def copy(self, dlat, dlon):
        copy = self.clone()
        copy.lat -= dlat
        copy.lon -= dlon
        return copy

    def load(self, lookup, defs, vertexcache, usefallback=False, definition=None):
        self.vertexcache = vertexcache
        if definition:
            self.definition = definition	# for child objects that may not be in global namespace lookup
            return True
        try:
            if self.name.startswith('*'):	# this application's resource
                filename=join('Resources', self.name[1:])
            else:
                filename=lookup[self.name].file
            if filename in defs:
                self.definition=defs[filename]
            else:
                gc.disable()	# work round http://bugs.python.org/issue4074 on Python<2.7
                defs[filename]=self.definition=ObjectDef(filename, vertexcache, lookup, defs)
                gc.enable()
            return True
        except:
            # virtual name not found or can't load physical file
            gc.enable()
            if __debug__:
                print_exc()
            if usefallback:
                if self.name in lookup:
                    filename=lookup[self.name].file
                else:
                    filename=self.name
                    lookup[self.name]=PaletteEntry(self.name)
                if filename in defs:
                    self.definition=defs[filename]
                else:
                    defs[filename]=self.definition=ObjectFallback(filename, vertexcache, lookup, defs)
            return False
        
    def location(self):
        return [self.lat, self.lon]

    def locationstr(self, dms, imp, node=None):
        if self.y:
            return u'%s  Hdg: %.1f\u00B0  Elv: %s' % (self.latlondisp(dms, self.lat, self.lon), self.hdg, self.distancedisp(imp, self.y))
        else:
            return u'%s  Hdg: %.1f\u00B0' % (self.latlondisp(dms, self.lat, self.lon), self.hdg)

    def inside(self, bbox):
        return bbox.inside(self.lon, self.lat)

    def pick_dynamic(self, glstate, lookup):
        assert self.islaidout() and (self.dynamic_data is None or self.base is not None), self
        # assume for speed that children are all Objects and and don't have dynamic data that extends outside the footprint
        if __debug__:
            for p in self.placements: assert p.__class__ is Object, p
        if self.dynamic_data is None:
            return False
        elif glstate.occlusion_query:
            glBeginQuery(glstate.occlusion_query, glstate.queries[len(lookup)])
            glDrawArrays(GL_TRIANGLES, self.base, len(self.dynamic_data)/6)
            # no need to draw point at origin in case no fragments generated, since pick_instanced handles this for Objects
            glEndQuery(glstate.occlusion_query)
        else:
            glLoadName(len(lookup))
            glDrawArrays(GL_TRIANGLES, self.base, len(self.dynamic_data)/6)
        lookup.append(self)
        return True

    def draw_nodes(self, glstate, selectednode):
        pass

    def bucket_dynamic(self, base, buckets):
        self.base = base
        buckets.add(self.definition.layer, self.definition.texture_draped, base, len(self.dynamic_data)/6)
        if __debug__: # draw outline for debug
            for i in range(base, base+len(self.dynamic_data)/6, 3):
                buckets.add(ClutterDef.OUTLINELAYER, None, i, 3)
        return self.dynamic_data

    def clearlayout(self):
        self.matrix=None
        self.dynamic_data=None	# Can be removed from dynamic VBO
        self.flush()
        for p in self.placements:
            p.clearlayout()
        # number of children is fixed, so no need to delete and re-create them

    def islaidout(self):
        return self.matrix is not None

    def flush(self):
        self.vertexcache.allocate_dynamic(self, False)
        self.definition.instances.discard(self)
        self.definition.transform_valid=False
        for p in self.placements:
            p.flush()

    def layout(self, tile, x=None, y=None, z=None, hdg=None, meshtris=None, recalc=True):
        self.definition.instances.add(self)
        self.definition.transform_valid=False
        if self.islaidout() and not recalc:
            # just ensure allocated
            self.definition.allocate(self.vertexcache)
            if self.dynamic_data is not None: self.vertexcache.allocate_dynamic(self, True)
            for p in self.placements:
                p.layout(tile, recalc=False)
            return

        elev = self.vertexcache.getElevationMesh(tile)
        if not (x and z):
            x,z=self.position(tile, self.lat, self.lon)
        if meshtris is None:	# if meshtris are passed in then assume bbox has already been calculated
            self.bbox = BBox(x, x, z, z)
            meshtris = elev.getbox(self.bbox)
        if y is not None:
            self.y=y
        else:
            self.y = elev.height(x,z,meshtris)
        if hdg is not None:
            self.hdg=hdg
        h=radians(self.hdg)
        self.matrix = array([x,self.y,z,h],float32)
        self.definition.allocate(self.vertexcache)	# ensure allocated
        for p in self.placements:
            p.layout(tile, meshtris=meshtris)
        # draped & poly_os
        if not self.definition.draped: return
        coshdg=cos(h)
        sinhdg=sin(h)
        if self.definition.poly or elev.flat:	# poly_os
            self.dynamic_data=array([[x+v[0]*coshdg-v[2]*sinhdg,self.y+v[1],z+v[0]*sinhdg+v[2]*coshdg,v[3],v[4],0] for v in self.definition.draped], float32).flatten()
            self.vertexcache.allocate_dynamic(self, True)
        else:	# draped
            tris=[]
            for v in self.definition.draped:
                vx=x+v[0]*coshdg-v[2]*sinhdg
                vz=z+v[0]*sinhdg+v[2]*coshdg
                vy = elev.height(vx, vz, meshtris)
                tris.append([vx,vy,vz,v[3],v[4],0])
            tris = elev.drapetris(tris, meshtris)
            if tris:
                self.dynamic_data = concatenate(tris)
                self.vertexcache.allocate_dynamic(self, True)
            else:
                self.dynamic_data = None
                self.vertexcache.allocate_dynamic(self, False)

    def move(self, dlat, dlon, dhdg, dparam, loc, tile):
        self.lat=max(tile[0], min(tile[0]+maxres, self.lat+dlat))
        self.lon=max(tile[1], min(tile[1]+maxres, self.lon+dlon))
        if dhdg:
            h=atan2(self.lon-loc[1], self.lat-loc[0])+radians(dhdg)
            l=hypot(self.lon-loc[1], self.lat-loc[0])
            self.lat=max(tile[0], min(tile[0]+maxres, round2res(loc[0]+cos(h)*l)))
            self.lon=max(tile[1], min(tile[1]+maxres, round2res(loc[1]+sin(h)*l)))
            self.hdg=(self.hdg+dhdg)%360
        self.layout(tile)

    def write(self, idx, south, west):
        # DSFTool rounds down, so round up here first
        return 'OBJECT\t%d\t%14.9f %14.9f %5.1f\n' % (idx, min(west+1, self.lon+minres/4), min(south+1, self.lat+minres/4), round(self.hdg,1)+minhdg/4)
        

class AutoGenPoint(Object):

    def load(self, lookup, defs, vertexcache, usefallback=False, definition=None):
        self.vertexcache = vertexcache
        try:
            filename=lookup[self.name].file
            if filename in defs:
                self.definition=defs[filename]
            else:
                defs[filename]=self.definition=AutoGenPointDef(filename, vertexcache, lookup, defs)
        except:
            # virtual name not found or can't load physical file
            if __debug__:
                print_exc()
            if usefallback:
                if self.name in lookup:
                    filename=lookup[self.name].file
                else:
                    filename=self.name
                    lookup[self.name]=PaletteEntry(self.name)
                if filename in defs:
                    self.definition=defs[filename]
                else:
                    defs[filename]=self.definition=AutoGenFallback(filename, vertexcache, lookup, defs)
            return False

        # load children
        self.placements=[]	# might not be empty if e.g. we're re-loading after Undo
        for child in self.definition.children:
            (childname, definition, xdelta, zdelta, hdelta)=child
            assert definition.filename in defs	# Child Def should have been created when AutoGenPointDef was loaded
            placement = Object(childname, self.lat, self.lon, self.hdg, parent=self)
            placement.load(None, None, vertexcache, definition=definition)
            self.placements.append(placement)
        return True

    if __debug__:
        def layoutp(self, tile, recalc=True):
            try:
                from cProfile import runctx
                runctx('self.layout2(tile, recalc)', globals(), locals(), 'profile.dmp')
            except:
                print_exc()

    def layout(self, tile, recalc=True):
        if self.islaidout() and not recalc:
            # just ensure allocated
            Object.layout(self, tile, recalc=False)
            return

        # We're likely to be doing a lot of height testing and draping, so pre-compute relevant mesh
        # triangles on the assumption that all children are contained in .agp's "floorplan"
        x,z=self.position(tile, self.lat, self.lon)
        self.bbox = BBox(x, x, z, z)
        h=radians(self.hdg)
        coshdg=cos(h)
        sinhdg=sin(h)
        for v in self.definition.draped:
            self.bbox.include(x+v[0]*coshdg-v[2]*sinhdg, z+v[0]*sinhdg+v[2]*coshdg)
        elev = self.vertexcache.getElevationMesh(tile)
        if elev.flat:
            mymeshtris = None
        else:
            mymeshtris = elev.getbox(self.bbox)

        Object.layout(self, tile, x, None, z, self.hdg, mymeshtris)
        assert len(self.placements)==len(self.definition.children), "%s %s %s %s" % (self, len(self.placements), self.definition, len(self.definition.children))
        for i in range(len(self.placements)):
            (childname, definition, xdelta, zdelta, hdelta)=self.definition.children[i]
            childx=x+xdelta*coshdg-zdelta*sinhdg
            childz=z+xdelta*sinhdg+zdelta*coshdg
            self.placements[i].layout(tile, childx, None, childz, self.hdg+hdelta, mymeshtris)


class Polygon(Clutter):

    BEZPTS = 8		# X-Plane stops at or before 8?
    NETBEZPTS = 4	# X-Plane seems lazier about networks

    @staticmethod
    def factory(name, param, nodes, lon=None, size=None, hdg=None):
        "creates and initialises appropriate Polygon subclass based on file extension"
        if lon==None:
            nodes = [[Node(coords) for coords in winding] for winding in nodes]
        if name.startswith(PolygonDef.EXCLUDE):
            return Exclude(name, param, nodes, lon, size, hdg)
        ext=name.lower()[-4:]
        if ext==PolygonDef.DRAPED:
            return Draped(name, param, nodes, lon, size, hdg)
        elif ext==PolygonDef.FACADE:
            return Facade(name, param, nodes, lon, size, hdg)
        elif ext==PolygonDef.FOREST:
            return Forest(name, param, nodes, lon, size, hdg)
        elif ext==PolygonDef.LINE:
            return Line(name, param, nodes, lon, size, hdg)
        elif ext==PolygonDef.STRING:
            return String(name, param, nodes, lon, size, hdg)
        elif ext==PolygonDef.BEACH:
            return Beach(name, param, nodes, lon, size, hdg)
        elif ext==NetworkDef.NETWORK:
            return Network(name, param, nodes, lon, size, hdg)
        elif ext==ObjectDef.OBJECT:
            raise IOError		# not a polygon
        elif ext in SkipDefs:
            raise IOError		# what's this doing here?
        else:	# unknown polygon type
            return Polygon(name, param, nodes, lon, size, hdg)


    def __init__(self, name, param, nodes, lon=None, size=None, hdg=None):
        if param==None: param=0
        if lon==None:
            Clutter.__init__(self, name)
            assert isinstance(nodes[0][0], Node)
            self.nodes = nodes
        else:
            lat=nodes
            Clutter.__init__(self, name, lat, lon)
            h=radians(hdg)
            self.nodes=[[]]
            size=0.000007071*size
            for i in [h+5*pi/4, h+3*pi/4, h+pi/4, h+7*pi/4]:
                self.nodes[0].append(Node([max(floor(lon), min(floor(lon)+1, round2res(self.lon+sin(i)*size))),
                                           max(floor(lat), min(floor(lat)+1, round2res(self.lat+cos(i)*size)))]))
        self.param=param
        self.nonsimple=False	# True iff non-simple and the polygon type cares about it (i.e. not Facades)
        self.singlewinding = True	# most polygon types don't support additional windings
        self.fixednodes = False	# most polygon types support additional nodes
        self.canbezier = False	# support for bezier control points
        self.isbezier = False	# nodes are derived from BezierNode, not just Node
        self.closed=True	# Open or closed
        self.col=COL_POLYGON	# Outline colour
        self.points=[]		# list of windings in world space (x,y,z), including points generated by bezier curves
        self.bbox = None	# bounding box for above

    def __str__(self):
        return '<"%s" %d %s>' % (self.name,self.param,self.points)

    def clone(self):
        return self.__class__(self.name, self.param, [[p.clone() for p in w] for w in self.nodes])

    def copy(self, dlat, dlon):
        copy = self.clone()
        # move manually to avoid rounding etc and complications while not loaded
        for w in copy.nodes:
            for node in w:
                node.move(-dlat, -dlon, None)
        return copy

    def load(self, lookup, defs, vertexcache, usefallback=True):
        self.vertexcache = vertexcache
        if self.name in lookup:
            filename=lookup[self.name].file
        else:
            filename=None
        self.definition=PolygonDef(filename, vertexcache, lookup, defs)
        return True
        
    def location(self):
        if self.lat==None:
            self.lon = sum([node.lon for node in self.nodes[0]]) / len(self.nodes[0])
            self.lat = sum([node.lat for node in self.nodes[0]]) / len(self.nodes[0])
        return [self.lat, self.lon]

    # horizontal distance to adjacent node(s)
    def distancestr(self, imp, node):
        (i,j) = node
        pt = self.nodes[i][j].loc
        n = len(self.nodes[i])
        if j==0 and not self.closed:
            nxt = self.nodes[i][j+1].loc
            return u'\u2022%s' % self.distancedisp(imp, hypot(pt[0]-nxt[0], pt[2]-nxt[2]))
        elif j==n-1 and not self.closed:
            prv = self.nodes[i][j-1].loc
            return u'\u2022%s' % self.distancedisp(imp, hypot(pt[0]-prv[0], pt[2]-prv[2]))
        else:
            prv = self.nodes[i][(j-1)%n].loc
            nxt = self.nodes[i][(j+1)%n].loc
            return u'%s\u2022%s' % (self.distancedisp(imp, hypot(pt[0]-prv[0], pt[2]-prv[2])), self.distancedisp(imp, hypot(pt[0]-nxt[0], pt[2]-nxt[2])))

    def locationstr(self, dms, imp, node=None, extranodeinfo=None):
        if node:
            (i,j)=node
            hole=['', 'Hole '][i and 1]
            extra = extranodeinfo and '  '+extranodeinfo or ''
            if self.nodes[i][j].loc[1]:
                return '%s  Elv: %s  %sNode %d%s   %s' % (self.latlondisp(dms, self.nodes[i][j].lat, self.nodes[i][j].lon), self.distancedisp(imp, self.nodes[i][j].loc[1]), hole, j, extra, self.distancestr(imp, node))
            else:
                return '%s  %sNode %d%s   %s' % (self.latlondisp(dms, self.nodes[i][j].lat, self.nodes[i][j].lon), hole, j, extra, self.distancestr(imp, node))
        else:
            return u'%s  Param\u2195 %-3d  (%d nodes)' % (self.latlondisp(dms, self.lat, self.lon), self.param, len(self.nodes[0]))

    def inside(self, bbox):
        for w in self.nodes:
            for node in w:
                if bbox.inside(node.lon, node.lat):
                    return True
        return False

    def pick_dynamic(self, glstate, lookup):
        assert self.islaidout() and self.base is not None, self
        # assume for speed that children are all Objects and so don't have dynamic data
        if __debug__:
            for p in self.placements: assert p.__class__ is Object, p
        base=self.base
        if glstate.occlusion_query:
            glBeginQuery(glstate.occlusion_query, glstate.queries[len(lookup)])
            for winding in self.points:
                glDrawArrays(GL_LINE_STRIP, base, len(winding))
                base+=len(winding)
            glEndQuery(glstate.occlusion_query)
        else:
            glLoadName(len(lookup))
            for winding in self.points:
                glDrawArrays(GL_LINE_STRIP, base, len(winding))
                base+=len(winding)
        lookup.append(self)
        return True

    def draw_nodes(self, glstate, selectednode):
        # Just do it in immediate mode

        # bezier control handles
        if self.canbezier:
            glstate.set_color(COL_SELBEZ)
            glBegin(GL_LINES)
            for winding in self.nodes:
                for node in winding:
                    if node.bezier:
                        glVertex3f(*node.bezloc)
                        glVertex3f(*node.loc)
                        glVertex3f(*node.loc)
                        glVertex3f(*node.bz2loc)
            glEnd()
            glBegin(GL_POINTS)
            for winding in self.nodes:
                for node in winding:
                    if node.bezier:
                        glVertex3f(*node.bezloc)
                        glVertex3f(*node.bz2loc)
            glEnd()

        glstate.set_color(COL_SELECTED)
        for winding in self.points:
            glBegin(GL_LINE_STRIP)
            for p in winding:
                glVertex3f(*p)
            glEnd()
        glBegin(GL_POINTS)
        for winding in self.nodes:
            for node in winding:
                glVertex3f(*node.loc)
        glEnd()

        # draw selected on top
        if selectednode:
            (i,j) = selectednode
            node = self.nodes[i][j]
            if self.canbezier and node.bezier:
                glstate.set_color(COL_SELBEZHANDLE)
                glBegin(GL_LINES)
                glVertex3f(*node.bezloc)
                glVertex3f(*node.loc)
                glVertex3f(*node.loc)
                glVertex3f(*node.bz2loc)
                glEnd()
            glstate.set_color(COL_SELNODE)
            glBegin(GL_POINTS)
            glVertex3f(*node.loc)
            if self.canbezier and node.bezier:
                glVertex3f(*node.bezloc)
                glVertex3f(*node.bz2loc)
            glEnd()
        
    def bucket_dynamic(self, base, buckets):
        # allocate for drawing, assuming outlines
        self.base = base
        for winding in self.points:
            buckets.add(ClutterDef.OUTLINELAYER, None, base, len(winding))
            base += len(winding)
        return self.dynamic_data

    def clearlayout(self):
        self.points=[]
        self.dynamic_data=None	# Can be removed from VBO
        self.flush()
        for p in self.placements:
            p.clearlayout()
        self.placements=[]

    def islaidout(self):
        return self.dynamic_data is not None

    def flush(self):
        self.vertexcache.allocate_dynamic(self, False)
        for p in self.placements:
            p.flush()

    def layout_nodes(self, tile, selectednode):
        self.lat=self.lon=0
        self.points=[]
        self.bbox = BBox()
        self.nonsimple=False
        fittomesh=self.definition.fittomesh
        elev = self.vertexcache.getElevationMesh(tile)

        if not fittomesh:
            # elevation determined by mid-point of nodes 0 and 1
            if len(self.nodes[0])>1:
                self.lon=(self.nodes[0][0].lon+self.nodes[0][1].lon)/2
                self.lat=(self.nodes[0][0].lat+self.nodes[0][1].lat)/2
            else:	# shouldn't happen
                self.lon=self.nodes[0][0].lon
                self.lat=self.nodes[0][0].lat
            (x,z)=self.position(tile, self.lat, self.lon)
            y = elev.height(x,z)
        else:
            self.lon = sum([node.lon for node in self.nodes[0]]) / len(self.nodes[0])
            self.lat = sum([node.lat for node in self.nodes[0]]) / len(self.nodes[0])

        i = 0
        while i < len(self.nodes):
            nodes=self.nodes[i]
            n=len(nodes)
            a=0
            for j in range(n):
                node = nodes[j]
                (x,z) = self.position(tile, node.lat, node.lon)
                if fittomesh:
                    y = elev.height(x,z)
                node.setloc(x,y,z)
                if node.bezier:
                    (x,z) = self.position(tile, node.lat+node.bezlat, node.lon+node.bezlon)
                    node.setbezloc(x,y,z)
                    (x,z) = self.position(tile, node.lat+node.bz2lat, node.lon+node.bz2lon)
                    node.setbz2loc(x,y,z)
                a += node.lon * nodes[(j+1)%n].lat - nodes[(j+1)%n].lon * node.lat

            if self.closed and ((i==0 and a<0) or (i and a>0)):
                # Outer should be CCW, inner CW
                nodes.reverse()
                if selectednode and selectednode[0]==i: selectednode=(i,n-1-selectednode[1])
                if self.isbezier:
                    for node in nodes: node.swapbez()
                    continue	# re-do layout with updated beziers

            points=[]
            bezpts = Polygon.BEZPTS
            for j in range(n):
                node = nodes[j]
                nxt  = nodes[(j+1)%n]
                node.pointidx = len(points)	# which point corresponds to this node
                points.append(node.loc)
                if self.canbezier and (self.closed or j!=n-1) and (node.bezier or nxt.bezier):	# only do beziers from last point if closed
                    if fittomesh:
                        if isinstance(self, Network):	# limit number of bezier points for speed
                            size = hypot(nxt.loc[0] - node.loc[0], nxt.loc[2] - node.loc[2])
                            bezpts = min(Polygon.NETBEZPTS, max(2, int(1.414 * size / self.definition.width)))
                        for u in range(1,bezpts):
                            if node.bezier and nxt.bezier:
                                (bx,by,bz) = self.bez4([node.loc, node.bezloc, nxt.bz2loc, nxt.loc], float(u)/bezpts)
                            elif node.bezier:
                                (bx,by,bz) = self.bez3([node.loc, node.bezloc, nxt.loc], float(u)/bezpts)
                            else:
                                (bx,by,bz) = self.bez3([node.loc,  nxt.bz2loc, nxt.loc], float(u)/bezpts)
                            points.append((bx, elev.height(bx,bz), bz))
                    else:
                        if node.bezier and nxt.bezier:
                            points.extend([self.bez4([node.loc, node.bezloc, nxt.bz2loc, nxt.loc], float(u)/bezpts) for u in range(1,bezpts)])
                        elif node.bezier:
                            points.extend([self.bez3([node.loc, node.bezloc, nxt.loc], float(u)/bezpts) for u in range(1,bezpts)])
                        else:
                            points.extend([self.bez3([node.loc,  nxt.bz2loc, nxt.loc], float(u)/bezpts) for u in range(1,bezpts)])
            if self.closed: points.append(points[0]) # repeat first if closed
            self.points.append(points)
            i += 1

        for (x,y,z) in self.points[0]:
            self.bbox.include(x,z)

        return selectednode

    def layout(self, tile, selectednode=None, recalc=True):
        if self.islaidout() and not recalc:
            # just ensure allocated
            self.vertexcache.allocate_dynamic(self, True)
            for p in self.placements:
                p.layout(tile, recalc=False)
            return selectednode
        selectednode=self.layout_nodes(tile, selectednode)
        col=self.nonsimple and COL_NONSIMPLE or self.col
        self.dynamic_data=concatenate([array(p+col,float32) for w in self.points for p in w])
        self.vertexcache.allocate_dynamic(self, True)
        for p in self.placements:
            p.layout(tile)
        return selectednode

    def addnode(self, tile, selectednode, lat, lon, clockwise=False):
        if self.fixednodes: return False
        (i,j)=selectednode
        n=len(self.nodes[i])
        if n>=255: return False	# node count is encoded as uint8 in DSF
        if (not self.closed) and (j==0 or j==n-1):
            # Special handling for ends of open lines and facades - add new node at cursor
            if j:
                newnode=nextnode=j+1
            else:
                newnode=nextnode=0
            self.nodes[i].insert(newnode, self.nodes[0][0].__class__([lon, lat]))
        else:
            if (i and clockwise) or (not i and not clockwise):
                newnode=j+1
                nextnode=(j+1)%n
            else:
                newnode=j
                nextnode=(j-1)%n
            self.nodes[i].insert(newnode, self.nodes[0][0].__class__([round2res((self.nodes[i][j].lon + self.nodes[i][nextnode].lon)/2),
                                                                      round2res((self.nodes[i][j].lat + self.nodes[i][nextnode].lat)/2)]))
        return self.layout(tile, (i,newnode))

    def delnode(self, tile, selectednode, clockwise=False):
        if self.fixednodes: return False
        (i,j)=selectednode
        if len(self.nodes[i])<=(self.closed and 3 or 2):	# Open lines and facades can have just two nodes
            return self.delwinding(tile, selectednode)
        self.nodes[i].pop(j)
        if (i and clockwise) or (not i and not clockwise):
            selectednode=(i,(j-1)%len(self.nodes[i]))
        else:
            selectednode=(i,j%len(self.nodes[i]))
        self.layout(tile, selectednode)
        return selectednode

    def addwinding(self, tile, size, hdg):
        if self.singlewinding: return False
        minrad=0.000007071*size
        for j in self.nodes[0]:
            minrad=min(minrad, abs(self.lon-j.lon), abs(self.lat-j.lat))
        i=len(self.nodes)
        h=radians(hdg)
        self.nodes.append([])
        for j in [h+5*pi/4, h+7*pi/4, h+pi/4, h+3*pi/4]:
            self.nodes[i].append(self.nodes[0][0].__class__([round2res(self.lon+sin(j)*minrad), round2res(self.lat+cos(j)*minrad)]))
        return self.layout(tile, (i,0))

    def delwinding(self, tile, selectednode):
        (i,j)=selectednode
        if not i: return False	# don't delete outer winding
        self.nodes.pop(i)
        return self.layout(tile, (i-1,0))

    def togglebezier(self, tile, selectednode):
        # Add or delete bezier control points
        (i,j) = selectednode
        node = self.nodes[i][j]
        n = len(self.nodes[i])
        if not self.canbezier:
            return False
        elif node.bezier:
            node.bezier = False		# retain bezier co-ordinates in case user changes their mind
            node.split = False		# but unsplit
            node.bz2lon = -node.bezlon
            node.bz2lat = -node.bezlat
        elif self.isbezier and (node.bezlat or node.bezlon):
            node.bezier = True		# use retained co-ordinates
        else:
            if not self.isbezier:
                self.nodes = [[BezierNode(p) for p in w] for w in self.nodes]	# trashes layout
                self.isbezier = True
                node = self.nodes[i][j]
            node.bezier = True
            if not self.closed and j==0:
                (node.bezlon, node.bezlat) = ((self.nodes[i][j+1].lon - node.lon) / 2, (self.nodes[i][j+1].lat - node.lat) / 2)
                (node.bz2lon, node.bz2lat) = (-node.bezlon, -node.bezlat)
            elif not self.closed and j==n-1:
                (node.bz2lon, node.bz2lat) = ((self.nodes[i][j-1].lon - node.lon) / 2, (self.nodes[i][j-1].lat - node.lat) / 2)
                (node.bezlon, node.bezlat) = (-node.bz2lon, -node.bz2lat)
            else:
                (node.bezlon, node.bezlat) = ((self.nodes[i][(j+1)%n].lon - self.nodes[i][(j-1)%n].lon) / 4, (self.nodes[i][(j+1)%n].lat - self.nodes[i][(j-1)%n].lat) / 4)
                (node.bz2lon, node.bz2lat) = (-node.bezlon, -node.bezlat)
        return self.layout(tile, selectednode, True)

    def move(self, dlat, dlon, dhdg, dparam, loc, tile):
        if dlat or dlon:
            for i in range(len(self.nodes)):
                for j in range(len(self.nodes[i])):
                    self.movenode((i,j), dlat, dlon, 0, tile)
        if dhdg:
            for w in self.nodes:
                for p in w:
                    p.rotate(dhdg, loc, tile)
        if dparam:
            self.param+=dparam
            if self.param<0: self.param=0
            elif self.param>65535: self.param=65535	# uint16
        # do layout if changed
        if dlat or dlon or dhdg or dparam:
            self.layout(tile)

    def movenode(self, node, dlat, dlon, darg, tile, defer=True):
        # Most polygons don't have co-ordinate arguments other than lat/lon & beziers, so darg ignored here.
        if not self.canbezier:
            # Trash additional co-ordinates of unknown types, and of types (e.g. v8 Facades) that don't meaningfully support them
            self.nodes = [[Node(p) for p in w] for w in self.nodes]	# trashes layout
            self.isbezier = False
        (i,j)=node
        self.nodes[i][j].move(dlat, dlon, tile)
        if defer:
            return node
        else:
            return self.layout(tile, node)
        
    def updatenode(self, node, lat, lon, tile):
        # update node height but defer full layout. Assumes lat,lon is valid
        (i,j) = node
        p = self.nodes[i][j]
        p.lon = lon
        p.lat = lat
        (x,z) = self.position(tile, lat, lon)

        if not self.canbezier:
            # Trash additional co-ordinates of unknown types, and of types (e.g. v8 Facades) that don't meaningfully support them
            if self.isbezier:
                p.setloc(x, None, z)
                self.nodes = [[Node(p) for p in w] for w in self.nodes]	# trashes layout
                self.isbezier = False
                return self.layout(tile, node)
            else:
                for w in self.nodes:
                    for p in w:
                        p.rest = []

        if self.definition.fittomesh:
            p.setloc(x, self.vertexcache.getElevationMesh(tile).height(x,z), z)
        else:
            p.setloc(x, None, z)	# assumes elevation already correct
        if p.bezier:
            (x,z) = self.position(tile, p.lat+p.bezlat, p.lon+p.bezlon)
            p.setbezloc(x, None, z)
            (x,z) = self.position(tile, p.lat+p.bz2lat, p.lon+p.bz2lon)
            p.setbz2loc(x, None, z)
        return node

    def updatehandle(self, node, handle, split, lat, lon, tile):
        # Defer full layout
        assert handle in [1,2], handle
        assert self.isbezier and self.canbezier	# shouldn't be able to manipulate control handles on types we think shouldn't have them
        (i,j) = node
        p = self.nodes[i][j]
        assert p.bezier
        (x,z) = self.position(tile, lat, lon)
        if self.closed or (j>0 and j<len(self.nodes[i])-1):
            if split: p.split = True
        else:
            p.split = False	# meaningless to split first or last node of open poly
        if handle==1:
            (p.bezlon, p.bezlat) = (lon - p.lon, lat - p.lat)
            p.setbezloc(x, None, z)
            if not p.split:
                (p.bz2lon, p.bz2lat) = (-p.bezlon, -p.bezlat)
                (x,z) = self.position(tile, p.lat + p.bz2lat, p.lon + p.bz2lon)
                p.setbz2loc(x, None, z)
        else:
            (p.bz2lon, p.bz2lat) = (lon - p.lon, lat - p.lat)
            p.setbz2loc(x, None, z)
            if not p.split:
                (p.bezlon, p.bezlat) = (-p.bz2lon, -p.bz2lat)
                (x,z) = self.position(tile, p.lat + p.bezlat, p.lon + p.bezlon)
                p.setbezloc(x, None, z)
        return node

    def pick_nodes(self, projection, withhandles):
        # prefer inner windings over outer, and handles over node
        if withhandles and self.isbezier:
            for i in range(len(self.nodes)-1, -1, -1):
                nodes = self.nodes[i]
                points = empty((len(nodes) * 3, 4))
                points[:,:3] = array([node.bezier and node.bz2loc or node.loc for node in nodes] + [node.bezier and node.bezloc or node.loc for node in nodes] + [node.loc for node in nodes])
                points[:,3] = 1			# make homogenous
                projected = numpy.abs(dot(points, projection)[:,:2])	# |x|,|y| in NDC space
                inview = numpy.nonzero(numpy.all(projected <= 1, axis=1))[0]
                if len(inview):
                    j = inview[0] % len(nodes)
                    return ((i,j), nodes[j].bezier and (2 - inview[0]/len(nodes)) or 0)
        else:
            for i in range(len(self.nodes)-1, -1, -1):
                nodes = self.nodes[i]
                points = empty((len(nodes), 4))
                points[:,:3] = array([node.loc for node in nodes])
                points[:,3] = 1			# make homogenous
                projected = numpy.abs(dot(points, projection)[:,:2])	# |x|,|y| in NDC space
                inview = numpy.nonzero(numpy.all(projected <= 1, axis=1))[0]
                if len(inview):
                    return ((i,inview[0]), 0)
        return None

    def write(self, idx, south, west):
        # DSFTool rounds down, so round up here first
        s = 'BEGIN_POLYGON\t%d\t%d %d\n' % (idx, self.param, self.nodes[0][0].coordcount())
        for w in self.nodes:
            s += 'BEGIN_WINDING\n'
            for p in w:
                s += p.write(south,west)
            s += 'END_WINDING\n'
        s += 'END_POLYGON\n'
        return s

    def bez3(self, p, mu):
        # http://paulbourke.net/geometry/bezier/
        mum1 = 1-mu
        mu2  = mu*mu
        mum12= mum1*mum1
        return (p[0][0]*mum12 + 2*p[1][0]*mum1*mu + p[2][0]*mu2, p[0][1], p[0][2]*mum12 + 2*p[1][2]*mum1*mu + p[2][2]*mu2)

    def bez4(self, p, mu):
        # http://paulbourke.net/geometry/bezier/
        mum1 = 1-mu
        mu3  = mu*mu*mu
        mum13= mum1*mum1*mum1
        return (p[0][0]*mum13 + 3*p[1][0]*mu*mum1*mum1 + 3*p[2][0]*mu*mu*mum1 + p[3][0]*mu3, p[0][1], p[0][2]*mum13 + 3*p[1][2]*mu*mum1*mum1 + 3*p[2][2]*mu*mu*mum1 + p[3][2]*mu3)


class Beach(Polygon):
    # Editing would zap extra vertex parameters that we don't understand,
    # so make a dummy type to prevent selection and therefore editing

    def __init__(self, name, param, nodes, lon=None, size=None, hdg=None):
        Polygon.__init__(self, name, param, nodes, lon, size, hdg)

    def load(self, lookup, defs, vertexcache, usefallback=True):
        Polygon.load(self, lookup, defs, vertexcache, usefallback=True)
        self.definition.layer=ClutterDef.BEACHESLAYER

    def pick_dynamic(self, glstate, lookup):
        return False	# Don't draw so can't be picked


class Draped(Polygon):

    def tessvertex(vertex, data):
        data.append(vertex)

    def tessedge(flag):
        pass	# dummy

    tess=gluNewTess()
    gluTessNormal(tess, 0, -1, 0)
    gluTessProperty(tess, GLU_TESS_WINDING_RULE, GLU_TESS_WINDING_NEGATIVE)
    gluTessCallback(tess, GLU_TESS_VERTEX_DATA,  tessvertex)
    gluTessCallback(tess, GLU_TESS_EDGE_FLAG,    tessedge)	# no strips

    def __init__(self, name, param, nodes, lon=None, size=None, hdg=None):
        Polygon.__init__(self, name, param, nodes, lon, size, hdg)
        if self.param == 65535:
            self.fixednodes = True	# we don't support new nodes in orthos
            self.canbezier = False
            if len(self.nodes[0][0].rest)==6:	# Has bezier coords but DSFTool can't write them, so demote
                for w in self.nodes:
                    for p in w:
                        p.rest = p.rest[4:6]
        else:
            self.singlewinding = False	# Can have holes if not an orthophoto
            self.canbezier = True	# can have curves if not an orthophoto
            if len(self.nodes[0][0].rest)==2:	# Has bezier coords - promote
                self.nodes = BezierNode.fromNodes(self.nodes)
                self.isbezier = True
            elif isinstance(self.nodes[0][0], BezierNode):
                self.isbezier = True		# already promoted

    def load(self, lookup, defs, vertexcache, usefallback=False):
        self.vertexcache = vertexcache
        try:
            filename=lookup[self.name].file
            if filename in defs:
                self.definition=defs[filename]
            else:
                defs[filename]=self.definition=DrapedDef(filename, vertexcache, lookup, defs)
            return True
        except:
            if __debug__:
                print_exc()
            if usefallback:
                if self.name in lookup:
                    filename=lookup[self.name].file
                else:
                    filename=self.name
                    lookup[self.name]=PaletteEntry(self.name)
                if filename in defs:
                    self.definition=defs[filename]
                else:
                    defs[filename]=self.definition=DrapedFallback(filename, vertexcache, lookup, defs)
            return False

    def locationstr(self, dms, imp, node=None):
        if node:
            return Polygon.locationstr(self, dms, imp, node)
        elif self.param==65535:
            return '%s  (%d nodes)' % (self.latlondisp(dms, self.lat, self.lon), len(self.nodes[0]))
        else:
            return u'%s  Tex hdg\u2195 %d\u00B0  (%d nodes)' % (self.latlondisp(dms, self.lat, self.lon), self.param, len(self.nodes[0]))

    def pick_dynamic(self, glstate, lookup):
        assert self.islaidout() and self.base is not None, self
        if self.nonsimple:
            return Polygon.pick_dynamic(self, glstate, lookup)
        elif glstate.occlusion_query:
            glBeginQuery(glstate.occlusion_query, glstate.queries[len(lookup)])
            glDrawArrays(GL_TRIANGLES, self.base, len(self.dynamic_data)/6)
            glBegin(GL_POINTS)
            glVertex3f(*self.points[0][0])	# draw a point so selectable even if no fragments generated
            glEnd()
            glEndQuery(glstate.occlusion_query)
        else:
            glLoadName(len(lookup))
            glDrawArrays(GL_TRIANGLES, self.base, len(self.dynamic_data)/6)
        lookup.append(self)
        return True
        
    def bucket_dynamic(self, base, buckets):
        if self.nonsimple:
            return Polygon.bucket_dynamic(self, base, buckets)
        else:
            if __debug__: # draw outline for debug
                for i in range(base, base+len(self.dynamic_data)/6, 3):
                    buckets.add(ClutterDef.OUTLINELAYER, None, i, 3)
            self.base = base
            buckets.add(self.definition.layer, self.definition.texture, base, len(self.dynamic_data)/6)
            return self.dynamic_data

    def move(self, dlat, dlon, dhdg, dparam, loc, tile):
        if self.param==65535:
            n=len(self.nodes[0])
            if dparam>0:
                # rotate texture co-ords.
                uv0 = self.nodes[0][0].rest
                for j in range(n-1):
                    self.nodes[0][j].rest = self.nodes[0][j+1].rest
                self.nodes[0][n-1].rest = uv0
            elif dparam<0:
                uv0 = self.nodes[0][n-1].rest
                for j in range(n-1,0,-1):
                    self.nodes[0][j].rest = self.nodes[0][j].rest
                self.nodes[0][0].rest = uv0
        else:
            # rotate texture
            self.param = (self.param + dparam + dhdg) % 360
        if dlat or dlon or dhdg:
            Polygon.move(self, dlat,dlon,dhdg, 0, loc, tile)
        elif dparam:
            self.layout(tile)

    def movenode(self, node, dlat, dlon, darg, tile, defer=True):
        # Override super because it will trash ortho UV coords
        (i,j) = node
        self.nodes[i][j].move(dlat, dlon, tile)
        if defer:
            return node
        else:
            return self.layout(tile, node)

    def updatenode(self, node, lat, lon, tile):
        # Override super because it will trash ortho UV coords
        (i,j) = node
        p = self.nodes[i][j]
        p.lon = lon
        p.lat = lat
        (x,z) = self.position(tile, lat, lon)
        if self.definition.fittomesh:
            p.setloc(x, self.vertexcache.getElevationMesh(tile).height(x,z), z)
        else:
            p.setloc(x, None, z)	# assumes elevation already correct
        if p.bezier:
            (x,z) = self.position(tile, p.lat+p.bezlat, p.lon+p.bezlon)
            p.setbezloc(x, None, z)
            (x,z) = self.position(tile, p.lat+p.bz2lat, p.lon+p.bz2lon)
            p.setbz2loc(x, None, z)
        return node

    def layout(self, tile, selectednode=None, recalc=True, tls=None):
        if self.islaidout() and not recalc:
            # just ensure allocated
            return Polygon.layout(self, tile, selectednode, False)

        selectednode=self.layout_nodes(tile, selectednode)

        drp = self.definition
        tess = tls and tls.tess or Draped.tess
        elev = self.vertexcache.getElevationMesh(tile)

        # Tessellate to generate tri vertices with UV data, and check polygon is simple
        tris=[]
        try:
            if self.param!=65535:
                assert not tls, self	# code below only handles passed tessellator for orthos
                gluTessBeginPolygon(tess, tris)
                elev.tessellatepoly(tess, self.points, drp.hscale, drp.vscale, self.param)
                gluTessEndPolygon(tess)
            else:
                gluTessBeginPolygon(tess, tris)
                elev.tessellatenodes(tess, self.nodes)
                gluTessEndPolygon(tess)
            if __debug__:
                if not tris: print "Draped layout failed for %s - no tris" % self
        except:
            # Combine required -> not simple
            tris=[]
            if __debug__:
                print "Draped layout failed for %s:" % self
                print_exc()

        if tris and not elev.flat:
            # tessellate again, against terrain
            if self.param!=65535:
                tris = elev.drapepoly(self.points, drp.hscale, drp.vscale, self.param, self.bbox)
            else:
                tris = elev.drapetris(tris, self.bbox, tls and tls.csgt)
        if tris:
            self.dynamic_data = concatenate(tris)
            assert self.dynamic_data.dtype == float32
        else:
            self.nonsimple=True
            self.dynamic_data=concatenate([array(p+COL_NONSIMPLE,float32) for w in self.points for p in w])

        if not tls:	# defer allocation if called in thread context
            self.vertexcache.allocate_dynamic(self, True)
        for p in self.placements:
            p.layout(tile)
        return selectednode


# For draping a map image directly. name is the basename of image filename.
# Note isn't added to global defs, so has to be flushed separately.
class DrapedImage(Draped):

    def load(self, lookup, defs, vertexcache, usefallback=True):
        self.vertexcache = vertexcache
        self.definition=DrapedFallback(self.name, vertexcache, lookup, defs)
        self.definition.layer=ClutterDef.IMAGERYLAYER
        self.definition.texture=0
        self.definition.type=0	# override - we don't want this locked

    def islaidout(self):
        # DrapedImage texture is assigned *after* layout
        return self.dynamic_data is not None and self.definition.texture


class Exclude(Polygon):

    NAMES={'sim/exclude_bch': PolygonDef.EXCLUDE+'Beaches',
           'sim/exclude_pol': PolygonDef.EXCLUDE+'Draped polygons',
           'sim/exclude_fac': PolygonDef.EXCLUDE+'Facades',
           'sim/exclude_for': PolygonDef.EXCLUDE+'Forests',
           'sim/exclude_lin': PolygonDef.EXCLUDE+'Lines',
           'sim/exclude_obj': PolygonDef.EXCLUDE+'Objects',
           'sim/exclude_net': PolygonDef.EXCLUDE+ NetworkDef.TABNAME,
           'sim/exclude_str': PolygonDef.EXCLUDE+'Strings'}

    TYPES = {}	# Filled in later

    def __init__(self, name, param, nodes, lon=None, size=None, hdg=None):
        if lon==None:
            Polygon.__init__(self, name, param, nodes)
        else:
            lat=nodes
            Polygon.__init__(self, name, param, lat, lon, size, hdg)
            # Override default node placement
            self.nodes=[[]]
            size=0.000005*size
            for (lon,lat) in [(self.lon-size,self.lat-size),
                              (self.lon+size,self.lat-size),
                              (self.lon+size,self.lat+size),
                              (self.lon-size,self.lat+size)]:
                self.nodes[0].append(Node([max(floor(self.lon), min(floor(self.lon)+1, round2res(lon))),
                                           max(floor(self.lat), min(floor(self.lat)+1, round2res(lat)))]))
        self.fixednodes = True
        self.col=COL_EXCLUDE

    def load(self, lookup, defs, vertexcache, usefallback=False):
        self.vertexcache = vertexcache
        self.definition=ExcludeDef(self.name, vertexcache, lookup, defs)	# just create a new one
        return True

    def locationstr(self, dms, imp, node=None):
        # no elevation
        if node:
            (i,j)=node
            return '%s  Node %d  %s' % (self.latlondisp(dms, self.nodes[i][j].lat, self.nodes[i][j].lon), j, self.distancestr(imp, node))
        else:
            return '%s' % (self.latlondisp(dms, self.lat, self.lon))

    def move(self, dlat, dlon, dhdg, dparam, loc, tile):
        # no rotation or param
        if dlat or dlon:
            for i in range(len(self.nodes)):
                for j in range(len(self.nodes[i])):
                    Polygon.movenode(self, (i,j), dlat, dlon, 0, tile)	# use superclass to prevent complication
            self.layout(tile)

    def movenode(self, node, dlat, dlon, darg, tile, defer=False):
        # changes adjacent nodes, so always do full layout immediately
        (i,j) = node
        lon = max(tile[1], min(tile[1]+1, self.nodes[i][j].lon + dlon))
        lat = max(tile[0], min(tile[0]+1, self.nodes[i][j].lat + dlat))
        return self.updatenode(node, lat, lon, tile)

    def updatenode(self, node, lat, lon, tile):
        (i,j)=node
        self.nodes[i][j].lon = lon
        self.nodes[i][j].lat = lat
        if j&1:
            self.nodes[i][(j-1)%4].lon = self.nodes[i][(j-1)%4].lon
            self.nodes[i][(j-1)%4].lat = lat
            self.nodes[i][(j+1)%4].lon = lon
            self.nodes[i][(j+1)%4].lat = self.nodes[i][(j+1)%4].lat
        else:
            self.nodes[i][(j+1)%4].lon = self.nodes[i][(j+1)%4].lon
            self.nodes[i][(j+1)%4].lat = lat
            self.nodes[i][(j-1)%4].lon = lon
            self.nodes[i][(j-1)%4].lat = self.nodes[i][(j-1)%4].lat
        # changed adjacent nodes, so do full layout immediately
        return self.layout(tile, node)


class Facade(Polygon):

    def tessvertex(vertex, data):
        data.append(vertex)

    def tessedge(flag):
        pass	# dummy

    tess=gluNewTess()
    gluTessNormal(tess, 0, -1, 0)
    gluTessProperty(tess, GLU_TESS_WINDING_RULE, GLU_TESS_WINDING_NONZERO)
    gluTessCallback(tess, GLU_TESS_VERTEX_DATA,  tessvertex)
    gluTessCallback(tess, GLU_TESS_EDGE_FLAG,    tessedge)	# no strips

    def __init__(self, name, param, nodes, lon=None, size=None, hdg=None):
        Polygon.__init__(self, name, param, nodes, lon, size, hdg)
        self.floorno=0		# for v10 - must keep in sync with self.param
        self.datalen=0
        self.drapedlen=0
        self.rooflen=0

    def load(self, lookup, defs, vertexcache, usefallback=False):
        self.vertexcache = vertexcache
        try:
            filename=lookup[self.name].file
            if filename in defs:
                self.definition=defs[filename]
            else:
                defs[filename]=self.definition=FacadeDef(filename, vertexcache, lookup, defs)
            if self.definition.version>=1000:
                self.canbezier = True
                if isinstance(self.nodes[0][0], BezierParamNode):
                    self.isbezier = True	# already promoted
                elif isinstance(self.nodes[0][0], ParamNode):
                    pass	# already promoted
                elif len(self.nodes[0][0].rest)<2:
                    self.nodes = [[ParamNode(node) for node in w] for w in self.nodes]	# add wall type
                else:
                    self.nodes = BezierParamNode.fromNodes(self.nodes)
                    self.isbezier = True
                floors=self.definition.floors
                if self.param:
                    bestdelta=maxint
                    for i in range(len(floors)):
                        thisdelta=abs(floors[i].height-self.param)
                        if thisdelta<bestdelta:
                            bestdelta=thisdelta
                            self.floorno=i
                else:
                    self.param=min(65535, max(1, int(round(floors[self.floorno].height))))
            else:	# old-style
                self.canbezier = False
                if len(self.nodes[0][0].rest)>=2:
                    # WED can encode v8-style facades with wall type and beziers even though these have no meaning
                    self.nodes = BezierNode.fromNodes(self.nodes)	# drop wall type if present
                    self.isbezier = True
                elif isinstance(self.nodes[0][0], BezierNode):
                    self.isbezier = True	# already promoted
                if not self.param:
                    wall = self.definition.walls[0]	# just use first wall
                    vpanels = wall.vpanels
                    self.param = sum([p.width for p in vpanels[0]+vpanels[2]])		# all bottom & top panels
                    if not self.param: self.param = sum([p.width for p in vpanels[1]])	# else all middle panels
                    self.param = max(int(0.5 + self.param + wall.basement*wall.scale[1]), 1)
            self.closed=(self.definition.ring and True)
            return True
        except:
            if __debug__:
                print_exc()
            if not self.param:
                self.param=1
            self.closed=True
            if usefallback:
                if self.name in lookup:
                    filename=lookup[self.name].file
                else:
                    filename=self.name
                    lookup[self.name]=PaletteEntry(self.name)
                if filename in defs:
                    self.definition=defs[filename]
                else:
                    defs[filename]=self.definition=FacadeFallback(filename, vertexcache, lookup, defs)
            return False

    def locationstr(self, dms, imp, node=None):
        if self.definition.version>=1000:
            floor=self.definition.floors[self.floorno]
            if node:
                (i,j)=node
                if len(floor.walls)>1 and (self.closed or j<len(self.nodes[i])-1):
                    wallno = self.nodes[i][j].param
                    return Polygon.locationstr(self, dms, imp, node, u'  Wall\u2195 ' + (0<=wallno<len(floor.walls) and floor.walls[wallno].name or 'undefined'))
                else:	# Can't change wall type if only one wall, or if final node
                    return Polygon.locationstr(self, dms, imp, node)
            elif len(self.definition.floors)>1:
                return u'%s  Height\u2195 %s  (%d nodes)' % (self.latlondisp(dms, self.lat, self.lon), floor.name, len(self.nodes[0]))
            else:	# Can't change height if only one floor
                return u'%s  (%d nodes)' % (self.latlondisp(dms, self.lat, self.lon), len(self.nodes[0]))

        else:	# old-style
            if node:
                return Polygon.locationstr(self, dms, imp, node)
            else:
                return u'%s  Height\u2195 %-3dm  (%d nodes)' % (self.latlondisp(dms, self.lat, self.lon), self.param, len(self.nodes[0]))

    def pick_dynamic(self, glstate, lookup):
        assert self.islaidout() and self.base is not None, self
        # assume for speed that children are all Objects and so don't have dynamic data
        if __debug__:
            for p in self.placements: assert p.__class__ is Object, p
        if self.nonsimple:
            return Polygon.pick_dynamic(self, glstate, lookup)
        elif glstate.occlusion_query:
            glBeginQuery(glstate.occlusion_query, glstate.queries[len(lookup)])
            glDrawArrays(GL_TRIANGLES, self.base, len(self.dynamic_data)/6)
            glBegin(GL_POINTS)
            glVertex3f(*self.points[0][0])	# draw a point so selectable even if no fragments generated
            glEnd()
            glEndQuery(glstate.occlusion_query)
        else:
            glLoadName(len(lookup))
            glDrawArrays(GL_TRIANGLES, self.base, len(self.dynamic_data)/6)
        lookup.append(self)
        return True
        
    def draw_nodes(self, glstate, selectednode):
        # Draws wall baseline in white if wall type is editable
        Polygon.draw_nodes(self, glstate, selectednode)
        if self.definition.version>=1000 and selectednode:
            floor=self.definition.floors[self.floorno]
            (i,j)=selectednode
            n = len(self.nodes[i])
            if len(floor.walls)>1 and (self.closed or j<n-1):
                glstate.set_color(COL_SELNODE)
                glBegin(GL_LINE_STRIP)
                for k in range(self.nodes[i][j].pointidx, j<n-1 and (self.nodes[i][(j+1)].pointidx + 1) or (len(self.points) + 1)):
                    glVertex3f(*self.points[i][k])
                glEnd()
        
    def bucket_dynamic(self, base, buckets):
        if self.nonsimple:
            return Polygon.bucket_dynamic(self, base, buckets)
        else:
            self.base = base
            layer = self.definition.two_sided and ClutterDef.GEOMNOCULLLAYER or ClutterDef.GEOMCULLEDLAYER
            buckets.add(layer, self.definition.texture, self.base, self.datalen)
            if self.drapedlen:
                buckets.add(self.definition.layer, self.definition.texture_roof, self.base+self.datalen, self.drapedlen)
            if self.rooflen:
                buckets.add(layer, self.definition.texture_roof, self.base+self.datalen+self.drapedlen, self.rooflen)
            return self.dynamic_data

    def move(self, dlat, dlon, dhdg, dparam, loc, tile):
        if self.definition.version<1000:
            dparam=max(dparam, 1-self.param)	# can't have height 0
            Polygon.move(self, dlat, dlon, dhdg, dparam, loc, tile)
        else:
            if dparam:
                if dparam>0:
                    self.floorno=min(self.floorno+1, len(self.definition.floors)-1)
                else:
                    self.floorno=max(self.floorno-1, 0)
                self.param=min(65535, max(1, int(round(self.definition.floors[self.floorno].height))))
            if dlat or dlon or dhdg:
                Polygon.move(self, dlat,dlon,dhdg, 0, loc, tile)
            elif dparam:
                self.layout(tile)

    def movenode(self, node, dlat, dlon, darg, tile, defer=True):
        if self.definition.version<1000:
            return Polygon.movenode(self, node, dlat, dlon, darg, tile, defer)	# trashes any spurious coords
        else:
            (i,j) = node
            # set wall type
            floor = self.definition.floors[self.floorno]
            wallno= self.nodes[i][j].param
            if darg>0:
                self.nodes[i][j].param = min(len(floor.walls)-1, max(0, wallno+1))
            elif darg<0:
                self.nodes[i][j].param = min(len(floor.walls)-1, max(0, wallno-1))
            if dlat or dlon:
                return Polygon.movenode(self, node, dlat, dlon, 0, tile, defer)
            elif darg and not defer:
                return self.layout(tile, node)
            else:
                return node

    def addnode(self, tile, selectednode, lat, lon, clockwise=False):
        if self.fixednodes: return False
        if self.definition.version<1000:
            return Polygon.addnode(self, tile, selectednode, lat, lon, clockwise)
        (i,j)=selectednode
        n=len(self.nodes[i])
        if n>=255: return False	# node count is encoded as uint8 in DSF
        if (not self.closed) and (j==0 or j==n-1):
            # Special handling for ends of open lines and facades - add new node at cursor
            if j:
                newnode=nextnode=j+1
            else:
                newnode=nextnode=0
            self.nodes[i].insert(newnode, self.nodes[0][0].__class__([lon, lat, self.nodes[i][j].param]))	# inherit wall type
        else:
            if (i and clockwise) or (not i and not clockwise):
                newnode=j+1
                nextnode=(j+1)%n
            else:
                newnode=j
                nextnode=(j-1)%n
            self.nodes[i].insert(newnode, self.nodes[0][0].__class__([round2res((self.nodes[i][j].lon + self.nodes[i][nextnode].lon)/2),
                                                                      round2res((self.nodes[i][j].lat + self.nodes[i][nextnode].lat)/2),
                                                                      self.nodes[i][j].param]))	# inherit wall type
        return self.layout(tile, (i,newnode))

    def togglebezier(self, tile, selectednode):
        if not self.canbezier:
            return False	# old-style Facades don't support beziers
        elif not self.isbezier:
            self.nodes = [[BezierParamNode(p) for p in w] for w in self.nodes]	# trashes layout
            self.isbezier = True
        return Polygon.togglebezier(self, tile, selectednode)

    def clearlayout(self):
        Polygon.clearlayout(self)
        self.datalen=self.rooflen=0

    def layout(self, tile, selectednode=None, recalc=True):
        if self.islaidout() and not recalc:
            # just ensure allocated
            return Polygon.layout(self, tile, selectednode, False)

        selectednode=self.layout_nodes(tile, selectednode)
        if self.definition.version>=1000:
            return self.layout10(tile, selectednode)
        else:
            return self.layout8(tile, selectednode)

    def layout8(self, tile, selectednode):
        tris=[]
        roofpts=[]
        points=self.points[0]
        n=len(self.nodes[0])
        for node in range(self.closed and n or n-1):
            (x,y,z)=points[node]
            (tox,toy,toz)=points[(node+1)%n]
            size=hypot(tox-x, z-toz)		# target wall length
            if size<=0: continue
            # find a wall that encompasses the target size
            for w in self.definition.walls:
                if w.widths[0]<=size<=w.widths[1]:
                    wall=w
                    break
            else:
                wall=self.definition.walls[0]	# just pick the first one if no walls fit the target size

            # http://wiki.x-plane.com/Facade_Overview
            hgrid=[]
            vgrid=[]
            for (target,panels,scale,grid,is_horiz) in [(size,wall.hpanels,wall.scale[0],hgrid,True), (float(self.param),wall.vpanels,wall.scale[1],vgrid,False)]:	# horizontal then vertical
                width=0		# cumulative width
                ltex=None	# end tex coord for left panel(s)
                mltex=[]	# end tex coord for middle-left panel(s)
                mrtex=[]	# start tex coord for middle-right panel(s)
                rtex=None	# start tex coord for right panel(s)
                top=None	# top floor kept separate for sloping
                for i in range(max(len(panels[0]),len(panels[2]))):
                    if not is_horiz:		# different rules appear to apply for vertical bottom and tops
                        if width<=target:
                            if i<len(panels[0]):
                                panel=panels[0][i]
                                ltex=panel.texcoords[1]
                                width+=panel.width
                            if i<len(panels[2]):
                                panel=panels[2][-i-1]	# add from right
                                if wall.roofslope and i==0:
                                    top=panel.texcoords[0]	# need to keep top floor separate for sloping
                                else:
                                    rtex=panel.texcoords[0]
                                width+=panel.width
                        continue
                    for left in [False,True]:	# despite the documentation, X-Plane appears to fill from right
                        if left:
                            if i<len(panels[0]):
                                panel=panels[0][i]
                                if width+panel.width-target < target-width:
                                    ltex=panel.texcoords[1]
                                    width+=panel.width
                                else:
                                    break
                        else:
                            if i<len(panels[2]):
                                panel=panels[2][-i-1]	# add from right
                                if width+panel.width-target < target-width:
                                    rtex=panel.texcoords[0]
                                    width+=panel.width
                                else:
                                    break
                    else:
                        continue
                    break
                else:
                    # left and right panels have not filled the target
                    while panels[1]:
                        for i in range(len(panels[1])):
                            for left in [False,True]:
                                if left:
                                    panel=panels[1][i]
                                    if width+panel.width-target <= (is_horiz and target-width or 0):
                                        if i==0: mltex.append(0)
                                        mltex[-1]=panel.texcoords[1]
                                        width+=panel.width
                                    else:
                                        break
                                else:
                                    panel=panels[1][-i-1]
                                    if width+panel.width-target <= (is_horiz and target-width or 0):
                                        if i==0: mrtex.insert(0,0)
                                        mrtex[0]=panel.texcoords[0]
                                        width+=panel.width
                                    else:
                                        break
                            else:
                                continue
                            break
                        else:
                            continue
                        break

                if is_horiz and rtex is None and not mrtex:	# if nothing fits, just cram in rightmost panel
                    if panels[2]:
                        panel=panels[2][-1]
                        rtex=panel.texcoords[0]
                    elif panels[1]:
                        panel=panels[1][-1]
                        mrtex=[panel.texcoords[0]]
                    else:
                        panel=panels[0][0]
                        ltex=panel.texcoords[1]
                    width=panel.width
                if ltex is not None and mltex:
                    assert ltex==panels[1][0].texcoords[0]	# end of left panel is start of middle?
                    ltex=mltex.pop(0)	# optimisation - merge left with first middle-left
                if rtex is not None and mrtex:
                    assert rtex==panels[1][-1].texcoords[1]	# start of right panel is end of middle?
                    rtex=mrtex.pop()	# optimisation - merge last middle-right with right

                # make list of (offset[m], texcoord)
                texscale=scale*(is_horiz and target/width or 1)	# vertical doesn't stretch
                width=0			# cumulative width
                if ltex:
                    grid.append((0,panels[0][0].texcoords[0]))
                    width+=texscale*(ltex-panels[0][0].texcoords[0])
                    grid.append((width,ltex))
                for m in mltex:
                    grid.append((width,panels[1][0].texcoords[0]))
                    width+=texscale*(m-panels[1][0].texcoords[0])
                    grid.append((width,m))
                for m in mrtex:
                    grid.append((width,m))
                    width+=texscale*(panels[1][-1].texcoords[1]-m)
                    grid.append((width,panels[1][-1].texcoords[1]))
                if top:
                    if rtex:
                        grid.append((width,rtex))
                        width+=texscale*(top-rtex)
                        grid.append((width,top))
                    grid.append((width,top))
                    width+=texscale*(panels[2][-1].texcoords[1]-top)
                    grid.append((width,panels[2][-1].texcoords[1]))
                elif rtex:
                    grid.append((width,rtex))
                    width+=texscale*(panels[2][-1].texcoords[1]-rtex)
                    grid.append((width,panels[2][-1].texcoords[1]))

            # make tris
            if not (vgrid and hgrid): continue	# empty
            h=atan2(tox-x, z-toz) % twopi
            coshdg=cos(h)
            sinhdg=sin(h)
            vscale=(toy-y)/hgrid[-1][0]
            y-=wall.basement*wall.scale[1]	# basement offsets down and reduces height above ground level
            for j in range(0,len(vgrid),2):
                (voffset1,v1)=vgrid[j]
                (voffset2,v2)=vgrid[j+1]
                topfloor=(j==len(vgrid)-2)
                if topfloor and wall.roofslope:
                    rs=radians(wall.roofslope)
                    roofheight=voffset1+(voffset2-voffset1)*cos(rs)
                    sz=(voffset2-voffset1)*sin(rs)
                else:
                    roofheight=voffset2
                    sz=0
                for i in range(0,len(hgrid),2):
                    (hoffset1,u1)=hgrid[i]
                    (hoffset2,u2)=hgrid[i+1]
                    tris.append([x+hoffset2*sinhdg, y+hoffset2*vscale+voffset1, z-hoffset2*coshdg, u2,v1,0])
                    tris.append([x+hoffset1*sinhdg, y+hoffset1*vscale+voffset1, z-hoffset1*coshdg, u1,v1,0])
                    if topfloor and wall.roofslope:
                        if i==0 and (self.closed or node!=0):
                            # miter joint between first segment and previous wall
                            (prvx,prvy,prvz)=points[(node-1)%n]
                            sm=tan((atan2(prvx-x, z-prvz)%twopi + h)/2 - h+piby2)	# miter angle
                            vx=x+hoffset1*sinhdg-sz*coshdg+sm*sz*sinhdg
                            vy=y+hoffset1*vscale+roofheight
                            vz=z-hoffset1*coshdg-sz*sinhdg-sm*sz*coshdg
                            tris.append([vx,vy,vz,u1,v2,0])
                            tris.append([vx,vy,vz,u1,v2,0])
                            roofpts.append([vx,vy,vz])			# save top first point in each wall for later
                        else:
                            tris.append([x+hoffset1*sinhdg-sz*coshdg, y+hoffset1*vscale+roofheight, z-hoffset1*coshdg-sz*sinhdg, u1,v2,0])
                            tris.append([x+hoffset1*sinhdg-sz*coshdg, y+hoffset1*vscale+roofheight, z-hoffset1*coshdg-sz*sinhdg, u1,v2,0])
                            if i==0: roofpts.append(tris[-1][:3])	# save top first point in each wall for later

                        if i==len(hgrid)-2 and wall.roofslope and (self.closed or node!=n-2):
                            # miter joint between last segment and next wall
                            (nxtx,nxty,nxtz)=points[(node+2)%n]
                            sm=tan((atan2(nxtx-tox, toz-nxtz)%twopi + h-pi)/2 - h+piby2)	# miter angle
                            tris.append([x+hoffset2*sinhdg-sz*coshdg+sm*sz*sinhdg, y+hoffset2*vscale+roofheight, z-hoffset2*coshdg-sz*sinhdg-sm*sz*coshdg, u2,v2,0])
                        else:
                            tris.append([x+hoffset2*sinhdg-sz*coshdg, y+hoffset2*vscale+roofheight, z-hoffset2*coshdg-sz*sinhdg, u2,v2,0])

                    else:
                        tris.append([x+hoffset1*sinhdg, y+hoffset1*vscale+voffset2, z-hoffset1*coshdg, u1,v2,0])
                        if topfloor and i==0: roofpts.append(tris[-1][:3])	# save top first point in each wall for later
                        tris.append([x+hoffset1*sinhdg, y+hoffset1*vscale+voffset2, z-hoffset1*coshdg, u1,v2,0])
                        tris.append([x+hoffset2*sinhdg, y+hoffset2*vscale+voffset2, z-hoffset2*coshdg, u2,v2,0])
                    tris.append([x+hoffset2*sinhdg, y+hoffset2*vscale+voffset1, z-hoffset2*coshdg, u2,v1,0])

        if not tris:
            if __debug__: print "Facade layout failed for %s - no tris" % self
            self.nonsimple=True
            self.dynamic_data=concatenate([array(p+COL_NONSIMPLE,float32) for w in self.points for p in w])
            self.datalen=len(self.dynamic_data)/6
        elif self.definition.roof and self.closed:
            # Tessellate to generate tri vertices with UV data, and check polygon is simple
            try:
                n=len(roofpts)
                rooftris=[]
                (x,y,z)=roofpts[0]
                (tox,toy,toz)=roofpts[1]
                h=atan2(tox-x, z-toz) + piby2	# texture heading determined by nodes 0->1
                coshdg=cos(h)
                sinhdg=sin(h)
                # UV boundary taken from building footprint, not roof footprint
                minx = min([(p[0]*coshdg + p[2]*sinhdg) for p in points])
                maxx = max([(p[0]*coshdg + p[2]*sinhdg) for p in points])
                minz = min([(p[0]*sinhdg - p[2]*coshdg) for p in points])
                maxz = max([(p[0]*sinhdg - p[2]*coshdg) for p in points])
                # don't know what these numbers repreent, but 1st and 3rd pair look like tex coords
                minu=min(self.definition.roof[0][0], self.definition.roof[2][0])
                maxu=max(self.definition.roof[0][0], self.definition.roof[2][0])
                minv=min(self.definition.roof[0][1], self.definition.roof[2][1])
                maxv=max(self.definition.roof[0][1], self.definition.roof[2][1])
                gluTessBeginPolygon(Facade.tess, rooftris)
                gluTessBeginContour(Facade.tess)
                for j in range(n):
                    gluTessVertex(Facade.tess, array([roofpts[j][0], 0, roofpts[j][2]],float64), list(roofpts[j]) + [maxu-(roofpts[j][0]*coshdg+roofpts[j][2]*sinhdg-minx)*(maxu-minu)/(maxx-minx), minv+(roofpts[j][0]*sinhdg-roofpts[j][2]*coshdg-minz)*(maxv-minv)/(maxz-minz), 0])
                gluTessEndContour(Facade.tess)
                gluTessEndPolygon(Facade.tess)
                if __debug__:
                    if not rooftris: print "Facade roof layout failed for %s - no tris" % self
            except:
                # Combine required -> not simple
                if __debug__:
                    print "Facade roof layout failed:"
                    print_exc()
                    rooftris=[]

            if self.definition.texture_roof:
                self.rooflen=len(rooftris)
                self.datalen=len(tris)
            else:
                self.rooflen=0
                self.datalen=len(tris)+len(rooftris)
            self.dynamic_data=array(tris+rooftris, float32).flatten()
        else:
            self.rooflen=0
            self.datalen=len(tris)
            self.dynamic_data=array(tris, float32).flatten()

        self.vertexcache.allocate_dynamic(self, True)
        return selectednode

    def layout10(self, tile, selectednode):
        for p in self.placements:
            p.clearlayout()	# clear any dynamic allocation of children
        self.placements=[]
        tris=[]
        floor=self.definition.floors[self.floorno]
        nodes = self.nodes[0]
        n = len(nodes)
        # can't draw curved facades, so just draw straight
        for j in range(self.closed and n or n-1):
            (x,y,z) = nodes[j].loc
            (tox,toy,toz) = nodes[(j+1)%n].loc
            size=hypot(tox-x, z-toz)	# target wall length
            if size<=0: continue
            h=atan2(tox-x, z-toz) % twopi
            hdg=degrees(h)
            wallno = nodes[j].param
            wall=floor.walls[0<=wallno<len(floor.walls) and wallno or 0]

            # Work out minimum number of segments (actually spellings) needed to fill the wall.
            # This is like the Knapsack problem, where value~spelling.width, except that overfilling is OK.
            # But we're just using a simple greedy algorithm; this is only optimal where spelling widths are in geometric progression.
            segments=[]
            width=0
            left=False	# alternate adding to left and right
            fillsize=size+wall.spellings[-1].width/2	# can overfill up to half the smallest spelling
            while True:
                for spelling in wall.spellings:		# assumed to be in order of descending width
                    if width+spelling.width < fillsize:
                        width+=spelling.width
                        if left:
                            segments=spelling.segments+segments
                        else:
                            segments=segments+spelling.segments
                        left=not left
                        break	# start from the top again
                else:
                    break	# nothing fitted
            if not segments:	# if nothing fits, just cram in smallest spelling
                segments=wall.spellings[-1].segments
                width=wall.spellings[-1].width

            hscale=size/width
            vscale=(y-toy)/size

            # layout
            hoffset=0
            coshdg=cos(h)
            sinhdg=sin(h)
            s=len(segments)
            for segno in range(s):
                segment=segments[segno]
                if segno==0 and (self.closed or j!=0):
                    # miter joint between first segment and previous wall
                    (prvx,prvy,prvz) = nodes[(j-1)%n].loc
                    sm=tan((atan2(prvx-x, z-prvz)%twopi + h)/2 - h+piby2)	# miter angle
                    for v in segment.mesh:
                        sz=hoffset+v[2]*hscale+v[0]*sm*(1+v[2]/segment.width)
                        vx=x+v[0]*coshdg-sz*sinhdg
                        vy=y+v[1]+sz*vscale
                        vz=z+v[0]*sinhdg+sz*coshdg
                        tris.append([vx,vy,vz,v[3],v[4],0])
                elif segno==s-1 and (self.closed or j!=n-2):
                    # miter joint between last segment and next wall
                    (nxtx,nxty,nxtz) = nodes[(j+2)%n].loc
                    sm=tan((atan2(nxtx-tox, toz-nxtz)%twopi + h-pi)/2 - h+piby2)	# miter angle
                    for v in segment.mesh:
                        sz=hoffset+v[2]*hscale-v[0]*sm*(v[2]/segment.width)
                        vx=x+v[0]*coshdg-sz*sinhdg
                        vy=y+v[1]+sz*vscale
                        vz=z+v[0]*sinhdg+sz*coshdg
                        tris.append([vx,vy,vz,v[3],v[4],0])
                    sm=0
                else:
                    for v in segment.mesh:
                        sz=hoffset+v[2]*hscale	# scale z to fit
                        vx=x+v[0]*coshdg-sz*sinhdg
                        vy=y+v[1]+sz*vscale
                        vz=z+v[0]*sinhdg+sz*coshdg
                        tris.append([vx,vy,vz,v[3],v[4],0])
                    sm=0

                for child in segment.children:
                    (childname, definition, is_draped, xdelta, ydelta, zdelta, hdelta)=child
                    placement = Object(childname, self.lat, self.lon, hdg+hdelta, parent=self)
                    placement.load(None, None, self.vertexcache, definition=definition)	# Child Def should have been created when FacadeDef was loaded
                    sz=hoffset+zdelta*hscale+xdelta*sm*(1+zdelta/segment.width)		# scale z, allowing for miter if 1st segment 
                    childx=x+xdelta*coshdg-sz*sinhdg
                    childz=z+xdelta*sinhdg+sz*coshdg
                    if is_draped:
                        childy=None
                    else:
                        childy=y+ydelta
                    placement.layout(tile, childx, childy, childz)
                    self.placements.append(placement)

            	hoffset-=segment.width*hscale

        self.dynamic_data=array(tris, float32).flatten()
        self.datalen=len(self.dynamic_data)/6

        if floor.roofs:
            # Tessellate to generate tri vertices with UV data, and check polygon is simple
            try:
                (x,y,z) = nodes[0].loc
                (tox,toy,toz) = nodes[1].loc
                h=atan2(tox-x, z-toz) + piby2	# texture heading determined by nodes 0->1
                coshdg=cos(h)
                sinhdg=sin(h)
                s=self.definition.roofscale
                maxu = max([((node.loc[0]*coshdg + node.loc[2]*sinhdg) / s) for node in nodes])
                minv = min([((node.loc[0]*sinhdg - node.loc[2]*coshdg) / s) for node in nodes])
                if floor.roofs[0]==0:
                    # "Roof" at height 0 is special and always gets draped (irrespective of "GRADED" setting in .fac)
                    rooftris=[]
                    gluTessBeginPolygon(Facade.tess, rooftris)
                    gluTessBeginContour(Facade.tess)
                    if self.definition.fittomesh:
                        for j in range(n):
                            (x,y,z) = nodes[j].loc
                            gluTessVertex(Facade.tess, array([x, 0, z],float64), [x, y, z, (x*coshdg+z*sinhdg)/s-maxu, (x*sinhdg-z*coshdg)/s-minv, 0])
                    else:
                        # Facade as a whole isn't draped but this floor at height 0 should be, so find elevations
                        elev = self.vertexcache.getElevationMesh(tile)
                        for j in range(n):
                            (x,y,z) = nodes[j].loc
                            gluTessVertex(Facade.tess, array([x, 0, z],float64), [x, elev.height(x,z), z, (x*coshdg+z*sinhdg)/s-maxu, (x*sinhdg-z*coshdg)/s-minv, 0])
                    gluTessEndContour(Facade.tess)
                    gluTessEndPolygon(Facade.tess)
                    if __debug__:
                        if not rooftris: print "Facade draped layout failed - no tris"
                    if not elev.flat:
                        rooftris = elev.drapetris(rooftris, self.bbox)
                else:
                    rooftris=[]
                # Remaining roofs laid out at polygon point elevations
                tris=[]
                gluTessBeginPolygon(Facade.tess, tris)
                gluTessBeginContour(Facade.tess)
                for j in range(n):
                    (x,y,z) = nodes[j].loc
                    gluTessVertex(Facade.tess, array([x, 0, z],float64), [x, y, z, (x*coshdg+z*sinhdg)/s-maxu, (x*sinhdg-z*coshdg)/s-minv, 0])
                gluTessEndContour(Facade.tess)
                gluTessEndPolygon(Facade.tess)
                if __debug__:
                    if not tris: print "Facade roof layout failed - no tris"
            except:
                # Combine required -> not simple
                if __debug__:
                    print "Facade roof layout failed:"
                    print_exc()
                    tris=[]

            if not tris:
                self.drapedlen=self.rooflen=0
            else:
                # replicate tessellated triangles at each roof height (except height 0 which is already laid out above)
                self.drapedlen=len(rooftris)
                for roof in floor.roofs[rooftris and 1 or 0:]:
                    for tri in tris:
                        rooftris.append([tri[0],roof+tri[1]]+tri[2:6])
                roofdata=array(rooftris, float32).flatten()
                self.rooflen=len(roofdata)/6-self.drapedlen
                self.dynamic_data=concatenate((self.dynamic_data, roofdata))

        self.vertexcache.allocate_dynamic(self, True)
        return selectednode


class Forest(Polygon):

    def tessvertex(vertex, data):
        data.append(vertex)

    def tessedge(flag):
        pass	# dummy

    tess=gluNewTess()
    gluTessNormal(tess, 0, -1, 0)
    gluTessProperty(tess, GLU_TESS_WINDING_RULE, GLU_TESS_WINDING_NONZERO)
    gluTessCallback(tess, GLU_TESS_VERTEX_DATA,  tessvertex)
    gluTessCallback(tess, GLU_TESS_EDGE_FLAG,    tessedge)	# no strips

    def __init__(self, name, param, nodes, lon=None, size=None, hdg=None):
        if param==None: param=127
        Polygon.__init__(self, name, param, nodes, lon, size, hdg)
        self.singlewinding = False
        self.col=COL_FOREST

    def load(self, lookup, defs, vertexcache, usefallback=False):
        self.vertexcache = vertexcache
        try:
            filename=lookup[self.name].file
            if filename in defs:
                self.definition=defs[filename]
            else:
                defs[filename]=self.definition=ForestDef(filename, vertexcache, lookup, defs)
            return True
        except:
            if __debug__:
                print_exc()
            if usefallback:
                if self.name in lookup:
                    filename=lookup[self.name].file
                else:
                    filename=self.name
                    lookup[self.name]=PaletteEntry(self.name)
                if filename in defs:
                    self.definition=defs[filename]
                else:
                    defs[filename]=self.definition=ForestFallback(filename, vertexcache, lookup, defs)
            return False

    def locationstr(self, dms, imp, node=None):
        if node:
            return Polygon.locationstr(self, dms, imp, node)
        else:
            return u'%s  Density\u2195 %-4.1f%%  (%d nodes)' % (self.latlondisp(dms, self.lat, self.lon), self.param/2.55, len(self.nodes[0]))

    def move(self, dlat, dlon, dhdg, dparam, loc, tile):
        Polygon.move(self, dlat, dlon, dhdg, dparam, loc, tile)
        if self.param>255: self.param=255

    def layout(self, tile, selectednode=None, recalc=True):
        if self.islaidout() and not recalc:
            # just ensure allocated
            return Polygon.layout(self, tile, selectednode, False)

        selectednode=self.layout_nodes(tile, selectednode)

        # tessellate. This is just to check polygon is simple
        try:
            tris=[]
            gluTessBeginPolygon(Forest.tess, tris)
            for i in range(len(self.nodes)):
                gluTessBeginContour(Forest.tess)
                for j in range(len(self.nodes[i])):
                    gluTessVertex(Forest.tess, array([self.points[i][j][0], 0, self.points[i][j][2]],float64), self.points[i][j])
                gluTessEndContour(Forest.tess)
            gluTessEndPolygon(Forest.tess)
            if not tris:
                if __debug__: print "Forest layout failed"
                self.nonsimple=True
        except:
            # Combine required -> not simple
            if __debug__:
                print "Forest layout failed:"
                print_exc()
            self.nonsimple=True

        col=self.nonsimple and COL_NONSIMPLE or self.col
        self.dynamic_data=concatenate([array(p+col,float32) for w in self.points for p in w])
        self.vertexcache.allocate_dynamic(self, True)
        return selectednode


class Line(Polygon):

    MITRELIMIT = 0.987	# cos(angle) at which X-Plane appears to give up making a nice mitre between segments

    def __init__(self, name, param, nodes, lon=None, size=None, hdg=None):
        if lon==None:
            Polygon.__init__(self, name, param, nodes)
            if len(self.nodes[0][0].rest)==2:	# Has bezier coords - promote
                self.nodes = BezierNode.fromNodes(self.nodes)
                self.isbezier = True
            elif isinstance(self.nodes[0][0], BezierNode):
                self.isbezier = True		# already promoted
        else:
            lat=nodes
            Polygon.__init__(self, name, param, nodes, lon, size, hdg)
            # Override default node placement
            h=radians(hdg)
            self.nodes=[[]]
            size=0.000005*size
            for i,off in [(h-piby2,size), (h,0), (h+piby2,size)]:
                self.nodes[0].append(Node([max(floor(lon), min(floor(lon)+1, round2res(self.lon+sin(i)*off))),
                                           max(floor(lat), min(floor(lat)+1, round2res(self.lat+cos(i)*off)))]))
        self.canbezier = True
        self.outlinelen = 0
        self.drawdata=[]	# [(layer,texture,count)]

    def load(self, lookup, defs, vertexcache, usefallback=False):
        self.vertexcache = vertexcache
        try:
            filename=lookup[self.name].file
            if filename in defs:
                self.definition=defs[filename]
            else:
                defs[filename]=self.definition=LineDef(filename, vertexcache, lookup, defs)
            return True
        except:
            if __debug__:
                print_exc()
            if usefallback:
                if self.name in lookup:
                    filename=lookup[self.name].file
                else:
                    filename=self.name
                    lookup[self.name]=PaletteEntry(self.name)
                if filename in defs:
                    self.definition=defs[filename]
                else:
                    defs[filename]=self.definition=LineFallback(filename, vertexcache, lookup, defs)
            return False

    def locationstr(self, dms, imp, node=None):
        if node:
            return Polygon.locationstr(self, dms, imp, node)
        else:
            oc=self.closed and 'Closed' or 'Open'
            return u'%s  %s\u2195  (%d nodes)' % (self.latlondisp(dms, self.lat, self.lon), oc, len(self.nodes[0]))

    def layout(self, tile, selectednode=None, recalc=True):
        self.closed=(self.param and True)
        if self.islaidout() and not recalc:
            # just ensure allocated
            return Polygon.layout(self, tile, selectednode, False)

        selectednode=self.layout_nodes(tile, selectednode)

        # adjust bounding box since lines extend outside points
        self.bbox.maxx += self.definition.width; self.bbox.minx -= self.definition.width
        self.bbox.maxz += self.definition.width; self.bbox.minz -= self.definition.width

        points=self.points[0]
        n = self.closed and len(points)-1 or len(points)

        # may need to repeatedly drape, so pre-compute relevant mesh triangles
        elev = self.vertexcache.getElevationMesh(tile)
        mymeshtris = elev.getbox(self.bbox)

        nsegs = len(self.definition.segments)
        even = self.definition.even
        segtris = { self.definition.layer: [[]] * nsegs,	# accumulate tris by segment
                    ClutterDef.GEOMCULLEDLAYER: [[]] * nsegs }	# for raised things, eg barriers
        t1 = 0
        for node in range(self.closed and n or n-1):
            (x,y,z) = points[node]
            (tox,toy,toz) = points[(node+1)%n]

            size = hypot(tox-x, z-toz)
            if size<=0: continue	# shouldn't happen
            t2 = t1 + size / self.definition.length
            # FIXME: even distance should apply between nodes, not between bezier fragments
            #if even: t2 = max(t1+even, round(t2/even) * even)	# nearest but at least one chunk

            h = atan2(tox-x, z-toz) % twopi
            sx1 = sx2 = 1	# near far width scale
            h1 = h2 = h		# near far miter angle

            if self.closed or node!=0:
                # miter joint between this and previous edge
                (prvx,prvy,prvz) = points[(node-1)%n]
                prvh = atan2(x-prvx, prvz-z) % twopi
                sx1 = 1 / cos((h - prvh)/2)
                if cos(h - prvh) > -Line.MITRELIMIT:
                    h1 = (h + prvh) / 2
                else:
                    sx1 = 1	# too acute
            if self.closed or node!=n-2:
                # miter joint between this and next edge
                (nxtx,nxty,nxtz) = points[(node+2)%n]
                nxth = atan2(nxtx-tox, toz-nxtz) % twopi
                sx2 = 1 / cos((h - nxth)/2)
                if cos(nxth - h) > -Line.MITRELIMIT:
                    h2 = (h + nxth) / 2
                else:
                    sx2 = 1	# too acute

            # entire line may be long espcially if a road, so calculate bounding box per-edge
            bbox = BBox(min(x,tox)-self.definition.width, max(x,tox)+self.definition.width,
                        min(z,toz)-self.definition.width, max(z,toz)+self.definition.width)
            cosh1 = cos(h1) * sx1
            sinh1 = sin(h1) * sx1
            cosh2 = cos(h2) * sx2
            sinh2 = sin(h2) * sx2
            for i in range(nsegs):
                segment = self.definition.segments[i]
                # near
                vx = x + segment.x_right * cosh1
                vz = z + segment.x_right * sinh1
                v1 = [vx, elev.height(vx,vz,mymeshtris) + segment.y2, vz, segment.s_right, t1 * segment.t_ratio, 0]
                vx = x + segment.x_left  * cosh1
                vz = z + segment.x_left  * sinh1
                v2 = [vx, elev.height(vx,vz,mymeshtris) + segment.y1, vz, segment.s_left,  t1 * segment.t_ratio, 0]
                # far
                vx = tox + segment.x_left  * cosh2
                vz = toz + segment.x_left  * sinh2
                v3 = [vx, elev.height(vx,vz,mymeshtris) + segment.y1, vz, segment.s_left,  t2 * segment.t_ratio, 0]
                vx = tox + segment.x_right * cosh2
                vz = toz + segment.x_right * sinh2
                v4 = [vx, elev.height(vx,vz,mymeshtris) + segment.y2, vz, segment.s_right, t2 * segment.t_ratio, 0]
                tris = [v1,v2,v3, v4,v1,v3]
                # Have to drape each segment individually since UVs don't necessarily match
                if not elev.flat:
                    tris = elev.drapetris(tris, bbox)
                layer = (segment.y1 or segment.y2) and ClutterDef.GEOMCULLEDLAYER or self.definition.layer
                segtris[layer][i] = segtris[layer][i] + tris
            t1 = t2 % 1		# prevent UV coords growing without bound

        self.drawdata=[]	# [(layer,texture,count)]
        for layer, lsegtris in segtris.iteritems():
            for i in range(nsegs):
                if i and self.definition.segments[i].texture == self.drawdata[-1][1]:
                    # merge consecutive tris that use the same texture for drawing speed
                    self.drawdata[-1] = (layer, self.definition.segments[i].texture, self.drawdata[-1][2] + len(lsegtris[i]))
                else:
                    self.drawdata.append((layer, self.definition.segments[i].texture, len(lsegtris[i])))

        self.dynamic_data = concatenate([array(v, float32).flatten() for i in segtris.values() for v in i])	# relies on correspondence of iteritems() and values() - http://docs.python.org/2/library/stdtypes.html#dict.items
        if self.definition.color:	# Network line - prepend outline
            outlinedata = concatenate([array(p+self.definition.color,float32) for w in self.points for p in w])
            self.outlinelen = len(outlinedata)/6
            self.dynamic_data = concatenate((outlinedata, self.dynamic_data))
        self.vertexcache.allocate_dynamic(self, True)
        return selectednode

    def pick_dynamic(self, glstate, lookup):
        assert self.islaidout() and self.base is not None, self
        if glstate.occlusion_query:
            glBeginQuery(glstate.occlusion_query, glstate.queries[len(lookup)])
            glDrawArrays(GL_TRIANGLES, self.base + self.outlinelen, len(self.dynamic_data)/6 - self.outlinelen)
            glBegin(GL_POINTS)
            glVertex3f(*self.points[0][0])	# draw a point so selectable even if no fragments generated
            glEnd()
            glEndQuery(glstate.occlusion_query)
        else:
            glLoadName(len(lookup))
            glDrawArrays(GL_TRIANGLES, self.base + self.outlinelen, len(self.dynamic_data)/6 - self.outlinelen)
        # Skip overhead of drawing outline, on the assumption that the Line/Network segments cover the outline
        lookup.append(self)
        return True

    def bucket_dynamic(self, base, buckets):
        self.base = base
        if self.outlinelen:	# Network lines
            buckets.add(ClutterDef.OUTLINELAYER, None, self.base, self.outlinelen)	# can't have holes
            base += self.outlinelen
        for (layer, texture, ntris) in self.drawdata:
            buckets.add(layer, texture, base, ntris)
            if __debug__: # draw outline for debug
                for i in range(base, base+ntris, 3):
                    buckets.add(ClutterDef.OUTLINELAYER, None, i, 3)
            base += ntris
        assert base-self.base == len(self.dynamic_data)/6, "%s %s" % (base-self.base, len(self.dynamic_data)/6)
        return self.dynamic_data

    def move(self, dlat, dlon, dhdg, dparam, loc, tile):
        dparam = (dparam+self.param) % 2 - self.param	# toggle between 0 and 1
        Polygon.move(self, dlat, dlon, dhdg, dparam, loc, tile)
        assert self.param in [0,1]


class String(Polygon):

    def __init__(self, name, param, nodes, lon=None, size=None, hdg=None):
        if param is None: param=0	# midpoint spacing
        if lon==None:
            Polygon.__init__(self, name, param, nodes)
            if len(self.nodes[0][0].rest)==2:	# Has bezier coords - promote
                self.nodes = BezierNode.fromNodes(self.nodes)
                self.isbezier = True
            elif isinstance(self.nodes[0][0], BezierNode):
                self.isbezier = True		# already promoted
        else:
            lat=nodes
            Polygon.__init__(self, name, param, nodes, lon, size, hdg)
            # Override default node placement
            h=radians(hdg)
            self.nodes=[[]]
            size=0.000005*size
            for i,off in [(h-piby2,size), (h,0), (h+piby2,size)]:
                self.nodes[0].append(Node([max(floor(lon), min(floor(lon)+1, round2res(self.lon+sin(i)*off))),
                                           max(floor(lat), min(floor(lat)+1, round2res(self.lat+cos(i)*off)))]))
        self.closed=False
        self.canbezier = True

    def load(self, lookup, defs, vertexcache, usefallback=False):
        self.vertexcache = vertexcache
        try:
            filename=lookup[self.name].file
            if filename in defs:
                self.definition=defs[filename]
            else:
                defs[filename]=self.definition=StringDef(filename, vertexcache, lookup, defs)
            return True
        except:
            if __debug__: print_exc()
            if usefallback:
                if self.name in lookup:
                    filename=lookup[self.name].file
                else:
                    filename=self.name
                    lookup[self.name]=PaletteEntry(self.name)
                if filename in defs:
                    self.definition=defs[filename]
                else:
                    defs[filename]=self.definition=StringFallback(filename, vertexcache, lookup, defs)
            return False

    def locationstr(self, dms, imp, node=None):
        if node:
            return Polygon.locationstr(self, dms, imp, node)
        elif self.param:
            return u'%s  Spacing\u2195 %3dm  (%d nodes)' % (self.latlondisp(dms, self.lat, self.lon), self.param, len(self.nodes[0]))
        else:
            return u'%s  Spacing\u2195 Midpoint  (%d nodes)' % (self.latlondisp(dms, self.lat, self.lon), len(self.nodes[0]))

    def layout(self, tile, selectednode=None, recalc=True):
        if self.islaidout() and not recalc:
            # just ensure allocated
            return Polygon.layout(self, tile, selectednode, False)

        # allocate lines for picking and for display
        selectednode=self.layout_nodes(tile, selectednode)

        for p in self.placements:
            p.clearlayout()	# clear any dynamic allocation of children

        self.placements=[]
        points = self.points[0]
        n = len(points) - 1	# strings are always open

        if not self.definition.alternate:
            # Networks have placements at start and end, plus sometimes at ill-defined intervals which we don't simulate
            for (node,to) in [(0,1),(-1,-2)]:
                (x,y,z)=points[node]
                (tox,toy,toz)=points[to]
                h=atan2(tox-x, z-toz) % twopi
                coshdg=cos(h)
                sinhdg=sin(h)
                hdg=degrees(h)
                for p in self.definition.children:
                    placement = Object(p.name, self.lat, self.lon, hdg+p.hdelta, parent=self)
                    placement.load(None, None, self.vertexcache, definition=p.definition)		# Child Def should have been created when StringDef was loaded
                    placement.layout(tile, x + p.xdelta*coshdg, None, z + p.xdelta*sinhdg, hdg+p.hdelta)
                    self.placements.append(placement)
            self.dynamic_data=concatenate([array(p + (self.nonsimple and COL_NONSIMPLE or self.definition.color),float32) for w in self.points for p in w])
            self.vertexcache.allocate_dynamic(self, True)
            return selectednode

        if not self.param:
            # placements at half the straight-line distance between nodes along edge
            nodes = self.nodes[0]
            objno = 0	# object no.
            for i in range(1,len(nodes)-1):	# Strings are always open. For some reason first edge doesn't have a placement.
                sz = hypot(nodes[i+1].loc[0] - nodes[i].loc[0], nodes[i+1].loc[2] - nodes[i].loc[2]) / 2	# distance to next placement
                cumulative = 0	# cumulative length up to this point
                for j in range(nodes[i].pointidx,nodes[i+1].pointidx):
                    (x,y,z) = points[j]
                    (tox,toy,toz) = points[j+1]
                    size = hypot(tox-x, z-toz)
                    if sz < size:
                        break
                    else:
                        sz -= size
                h = atan2(tox-x, z-toz) % twopi
                coshdg=cos(h)
                sinhdg=sin(h)
                hdg=degrees(h)
                p = self.definition.children[objno]
                child = p.definition
                placement = Object(p.name, self.lat, self.lon, hdg+p.hdelta, parent=self)
                placement.load(None, None, self.vertexcache, definition=p.definition)		# Child Def should have been created when StringDef was loaded
                childx = x + p.xdelta*coshdg + sz*sinhdg
                childz = z + p.xdelta*sinhdg - sz*coshdg
                placement.layout(tile, childx, None, childz, hdg+p.hdelta)
                self.placements.append(placement)
                objno = (objno+1) % len(self.definition.children)
            self.nonsimple = not self.placements
            self.dynamic_data=concatenate([array(p + (self.nonsimple and COL_NONSIMPLE or self.definition.color),float32) for w in self.points for p in w])
            self.vertexcache.allocate_dynamic(self, True)
            return selectednode			# exit!

        # placements are repeated very param metres
        repeat = self.param
        size=0		# length of this edge
        cumulative = 0	# cumulative length up to this point
        objno=0	# object no.
        j = -1
        iteration = -0.261	# roughly what X-Plane appears to use!
        while True:
            iteration += 1
            sz = iteration*repeat - cumulative	# distance along this edge to next placement
            while True:
                if sz<size:
                    break	# will fit on this edge
                else:
                    j += 1
                    if j >= n:
                        self.nonsimple = not self.placements
                        self.dynamic_data=concatenate([array(p + (self.nonsimple and COL_NONSIMPLE or self.definition.color),float32) for w in self.points for p in w])
                        self.vertexcache.allocate_dynamic(self, True)
                        return selectednode			# exit!
                    cumulative += size
                    sz = iteration*repeat - cumulative
                (x,y,z)=points[j]
                (tox,toy,toz)=points[j+1]
                size=hypot(tox-x, z-toz)
                if size<=0: size=0	# shouldn't happen
                h=atan2(tox-x, z-toz) % twopi
                coshdg=cos(h)
                sinhdg=sin(h)
                hdg=degrees(h)

            p = self.definition.children[objno]
            child = p.definition
            placement = Object(p.name, self.lat, self.lon, hdg+p.hdelta, parent=self)
            placement.load(None, None, self.vertexcache, definition=p.definition)		# Child Def should have been created when StringDef was loaded
            childx = x + p.xdelta*coshdg + sz*sinhdg
            childz = z + p.xdelta*sinhdg - sz*coshdg
            placement.layout(tile, childx, None, childz, hdg+p.hdelta)
            self.placements.append(placement)
            objno = (objno+1) % len(self.definition.children)


class Network(String,Line):

    def __init__(self, name, param, nodes, lon=None, size=None, hdg=None):
        if lon==None:
            Polygon.__init__(self, name, param, nodes)
            if not isinstance(self.nodes[0][0], NetworkNode):	# Not already NetworkNodes?
                self.nodes = NetworkNode.fromNodes(self.nodes)
        else:
            lat=nodes
            Polygon.__init__(self, name, param, nodes, lon, size, hdg)
            # Override default node placement
            h=radians(hdg)
            self.nodes=[[]]
            size=0.000005*size
            for i,off in [(h-piby2,size), (h,0), (h+piby2,size)]:
                self.nodes[0].append(NetworkNode([max(floor(lon), min(floor(lon)+1, round2res(self.lon+sin(i)*off))),
                                                  max(floor(lat), min(floor(lat)+1, round2res(self.lat+cos(i)*off))), 0]))
        self.closed=False
        self.canbezier = True
        self.isbezier = True	# nodes always stored as bezier for simplicity
            
    def load(self, lookup, defs, vertexcache, usefallback=False):
        self.vertexcache = vertexcache
        # skip lookup, since defs is pre-populated with the valid NetworkDefs
        if self.name in defs:
            self.definition = defs[self.name]
            return True
        elif usefallback:
            defs[filename] = self.definition = NetworkFallback(self.name, vertexcache, lookup, defs)
            return False

    def locationstr(self, dms, imp, node=None):
        if node:
            (i,j)=node
            if j==0 or j==len(self.nodes[i])-1:
                return Polygon.locationstr(self, dms, imp, node, u'  Level\u2195 %s' % (self.nodes[i][j].param or 'Ground'))
            else:
                return Polygon.locationstr(self, dms, imp, node)
        else:
            return u'%s  (%d nodes)' % (self.latlondisp(dms, self.lat, self.lon), len(self.nodes[0]))

    def pick_dynamic(self, glstate, lookup):
        if self.definition.segments:
            return Line.pick_dynamic(self, glstate, lookup)
        else:
            return String.pick_dynamic(self, glstate, lookup)

    def bucket_dynamic(self, base, buckets):
        if self.definition.segments:
            return Line.bucket_dynamic(self, base, buckets)
        else:
            return String.bucket_dynamic(self, base, buckets)

    def move(self, dlat, dlon, dhdg, dparam, loc, tile):
        Polygon.move(self, dlat, dlon, dhdg, dparam, loc, tile)

    def movenode(self, node, dlat, dlon, darg, tile, defer=True):
        (i,j) = node
        if darg:
            # elevation
            self.nodes[i][j].param = (j==0 or j==len(self.nodes[i])-1) and min(max(self.nodes[i][j].param + darg, 0), 5) or 0	# level 5 is arbitrary
        if dlat or dlon:
            return Polygon.movenode(self, node, dlat, dlon, 0, tile, defer)
        elif darg and not defer:
            return self.layout(tile, node)
        else:
            return node

    def addnode(self, tile, selectednode, lat, lon, clockwise=False):
        if self.fixednodes: return False
        (i,j) = selectednode
        n = len(self.nodes[i])
        if n>=255: return False	# node count is encoded as uint8 in DSF
        if (not self.closed) and (j==0 or j==n-1):
            # Special handling for ends of open lines - add new node at cursor
            if j:
                newnode=nextnode=j+1
            else:
                newnode=nextnode=0
            level = self.nodes[i][j].param
            self.nodes[i][j].param = 0
            self.nodes[i].insert(newnode, NetworkNode([lon, lat, level]))	# inherit level
        else:
            if (i and clockwise) or (not i and not clockwise):
                newnode=j+1
                nextnode=(j+1)%n
            else:
                newnode=j
                nextnode=(j-1)%n
            self.nodes[i].insert(newnode, NetworkNode([round2res((self.nodes[i][j].lon + self.nodes[i][nextnode].lon)/2),
                                                       round2res((self.nodes[i][j].lat + self.nodes[i][nextnode].lat)/2), 0]))
        return self.layout(tile, (i,newnode))

    def layout(self, tile, selectednode=None, recalc=True):
        if self.definition.segments:
            return Line.layout(self, tile, selectednode, recalc)
        else:
            return String.layout(self, tile, selectednode, recalc)


# Have to do this after classes are defined. Yuck.
Exclude.TYPES={PolygonDef.EXCLUDE+'Beaches': Beach,
               PolygonDef.EXCLUDE+'Draped polygons': Draped,
               PolygonDef.EXCLUDE+'Facades': Facade,
               PolygonDef.EXCLUDE+'Forests': Forest,
               PolygonDef.EXCLUDE+'Lines': Line,
               PolygonDef.EXCLUDE+'Objects': Object,
               PolygonDef.EXCLUDE+ NetworkDef.TABNAME: Network,
               PolygonDef.EXCLUDE+'Strings': String}
if __debug__:	# check we have a type for every name
    for name in Exclude.NAMES.values(): assert name in Exclude.TYPES
