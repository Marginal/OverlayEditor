# Derived classes expected to have following members:
# __init__
# __str__
# clone -> make a new copy, minus layout
# load -> read definition
# location -> returns (average) lat/lon
# layout -> fit to terrain, allocate into VBO(s)
# clearlayout -> clear above
# flush -> clear dynamic VBO allocation (but retain layout) - note doesn't clear instance VBO allocation since def may be shared
# move -> move and layout
# movenode -> move - no layout
# updatenode -> move node - no layout

# Clutter (except for DrapedImage) not in the current tile retain their layout, but not their VBO allocation.

from math import atan2, ceil, cos, degrees, floor, hypot, pi, radians, sin, tan
from numpy import array, array_equal, concatenate, float32, float64
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

from clutterdef import ObjectDef, AutoGenPointDef, PolygonDef, DrapedDef, ExcludeDef, FacadeDef, ForestDef, LineDef, NetworkDef, NetworkFallback, ObjectFallback, DrapedFallback, FacadeFallback, ForestFallback, LineFallback, SkipDefs, BBox, COL_UNPAINTED, COL_POLYGON, COL_FOREST, COL_EXCLUDE, COL_NONSIMPLE, COL_SELECTED, COL_SELNODE

from palette import PaletteEntry
from prefs import Prefs

twopi=pi*2
piby2=pi/2
onedeg=1852*60	# 1 degree of longitude at equator (60nm) [m]
resolution=8*65535
minres=1.0/resolution
maxres=1-minres
minhdg=360.0/65535

def round2res(x):
    i=floor(x)
    return i+round((x-i)*resolution,0)*minres


def ObjectFactory(name, lat, lon, hdg, y=None):
    "creates and initialises appropriate Object subclass based on file extension"
    if name.lower()[-4:]==AutoGenPointDef.AGP:
        return AutoGenPoint(name, lat, lon, hdg, y)
    else:
        return Object(name, lat, lon, hdg, y)


def PolygonFactory(name, param, nodes, lon=None, size=None, hdg=None):
    "creates and initialises appropriate Polygon subclass based on file extension"
    # would like to have made this a 'static' method of Polygon
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
    elif ext==PolygonDef.BEACH:
        return Beach(name, param, nodes, lon, size, hdg)
    elif ext==ObjectDef.OBJECT:
        raise IOError		# not a polygon
    elif ext in SkipDefs:
        raise IOError		# what's this doing here?
    else:	# unknown polygon type
        return Polygon(name, param, nodes, lon, size, hdg)


class Clutter:

    def __init__(self, name, lat=None, lon=None):
        self.name=name		# virtual name
        self.definition=None
        self.lat=lat		# For centreing etc
        self.lon=lon
        self.dynamic_data=None	# Data for inclusion in VBO
        self.base=None		# Offset when allocated in VBO
        
    def position(self, tile, lat, lon):
        # returns (x,z) position relative to centre of enclosing tile
        # z is positive south
        return ((lon-tile[1]-0.5)*onedeg*cos(radians(lat)),
                (0.5-(lat-tile[0]))*onedeg)


class Object(Clutter):

    def __init__(self, name, lat, lon, hdg, y=None):
        Clutter.__init__(self, name, lat, lon)
        self.hdg=hdg
        self.y=y
        self.matrix=None

    def __str__(self):
        return '<Object "%s" %11.6f %10.6f %d %s>' % (
            self.name, self.lat, self.lon, self.hdg, self.y)

    def clone(self):
        return Object(self.name, self.lat, self.lon, self.hdg, self.y)

    def load(self, lookup, defs, vertexcache, usefallback=False):
        try:
            if self.name.startswith('*'):	# this application's resource
                filename=join('Resources', self.name[1:])
            else:
                filename=lookup[self.name].file
            if filename in defs:
                self.definition=defs[filename]
            else:
                defs[filename]=self.definition=ObjectDef(filename, vertexcache, lookup, defs)
            return True
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
                    defs[filename]=self.definition=ObjectFallback(filename, vertexcache, lookup, defs)
            return False
        
    def location(self):
        return [self.lat, self.lon]

    def locationstr(self, dms, node=None):
        if self.y:
            return '%s  Hdg: %-5.1f  Elv: %-6.1f' % (latlondisp(dms, self.lat, self.lon), self.hdg, self.y)
        else:
            return '%s  Hdg: %-5.1f' % (latlondisp(dms, self.lat, self.lon), self.hdg)

    def draw_instance(self, glstate, selected, picking):
        obj=self.definition
        glLoadMatrixf(self.matrix)
        if picking:
            assert self.islaidout(), self
            assert not glstate.cull
            # glstate.poly doesn't affect selection
            if obj.vdata is not None:
                glDrawArrays(GL_TRIANGLES, obj.base, obj.culled+obj.nocull)
            glBegin(GL_POINTS)
            glVertex3f(0.0,0.0,0.0)	# draw point at object origin so selectable even if not visible
            glEnd()
        elif obj.vdata is not None:	# .agp base has no vertex data
            assert self.islaidout() and obj.base is not None, self
            glstate.set_texture(obj.texture)
            glstate.set_color(selected and COL_SELECTED or COL_UNPAINTED)
            assert not glstate.poly
            assert glstate.depthtest
            if selected:	# draw rear side of selected "invisible" faces
                glstate.set_cull(False)
                glDrawArrays(GL_TRIANGLES, obj.base, obj.culled+obj.nocull)
            else:
                if obj.culled:
                    glstate.set_cull(True)
                    glDrawArrays(GL_TRIANGLES, obj.base, obj.culled)
                if obj.nocull:
                    glstate.set_cull(False)
                    glDrawArrays(GL_TRIANGLES, obj.base+obj.culled, obj.nocull)

    def draw_dynamic(self, glstate, selected, picking):
        if self.dynamic_data is None:
            return
        elif not picking:
            glstate.set_texture(self.definition.texture_draped)
            glstate.set_color(selected and COL_SELECTED or COL_UNPAINTED)
            glstate.set_cull(True)
            glstate.set_poly(True)
            glstate.set_depthtest(True)
        assert self.islaidout() and self.base is not None, self
        glDrawArrays(GL_TRIANGLES, self.base, len(self.dynamic_data)/6)

    def draw_nodes(self, glstate, selectednode):
        pass

    def clearlayout(self, vertexcache):
        self.matrix=None
        self.dynamic_data=None	# Can be removed from dynamic VBO
        self.flush(vertexcache)

    def islaidout(self):
        return self.matrix is not None

    def flush(self, vertexcache):
        vertexcache.allocate_dynamic(self, False)

    def layout(self, tile, options, vertexcache, x=None, y=None, z=None, hdg=None, meshtris=None, recalc=True):
        if self.islaidout() and not recalc:
            # just ensure allocated
            self.definition.allocate(vertexcache)
            if self.dynamic_data is not None: vertexcache.allocate_dynamic(self, True)
            return

        if not (x and z):
            x,z=self.position(tile, self.lat, self.lon)
        if y is not None:
            self.y=y
        else:
            self.y=vertexcache.height(tile,options,x,z,meshtris)
        if hdg is not None:
            self.hdg=hdg
        h=radians(self.hdg)
        self.matrix=array([cos(h),0.0,sin(h),0.0, 0.0,1.0,0.0,0.0, -sin(h),0.0,cos(h),0.0, x,self.y,z,1.0],float32)
        self.definition.allocate(vertexcache)	# ensure allocated
        # draped & poly_os
        if not self.definition.draped: return
        coshdg=cos(h)
        sinhdg=sin(h)
        if self.definition.poly or not options&Prefs.ELEVATION:	# poly_os
            self.dynamic_data=array([[x+v[0]*coshdg-v[2]*sinhdg,self.y+v[1],z+v[0]*sinhdg+v[2]*coshdg,v[3],v[4],0] for v in self.definition.draped], float32).flatten()
        else:	# draped
            tris=[]
            for v in self.definition.draped:
                vx=x+v[0]*coshdg-v[2]*sinhdg
                vz=z+v[0]*sinhdg+v[2]*coshdg
                vy=vertexcache.height(tile,options, vx, vz, meshtris)
                tris.append([vx,vy,vz,v[3],v[4],0])
            self.dynamic_data=array(drape(tris, tile, options, vertexcache, meshtris), float32).flatten()
        vertexcache.allocate_dynamic(self, True)

    def move(self, dlat, dlon, dhdg, dparam, loc, tile, options, vertexcache):
        self.lat=max(tile[0], min(tile[0]+maxres, self.lat+dlat))
        self.lon=max(tile[1], min(tile[1]+maxres, self.lon+dlon))
        if dhdg:
            h=atan2(self.lon-loc[1], self.lat-loc[0])+radians(dhdg)
            l=hypot(self.lon-loc[1], self.lat-loc[0])
            self.lat=max(tile[0], min(tile[0]+maxres, round2res(loc[0]+cos(h)*l)))
            self.lon=max(tile[1], min(tile[1]+maxres, round2res(loc[1]+sin(h)*l)))
            self.hdg=(self.hdg+dhdg)%360
        self.layout(tile, options, vertexcache)
        

class AutoGenPoint(Object):

    def __init__(self, name, lat, lon, hdg, y=None):
        Object.__init__(self, name, lat, lon, hdg, y)
        self.placements=[]	# [Object, xdelta, zdelta, hdelta]

    def clone(self):
        return AutoGenPoint(self.name, self.lat, self.lon, self.hdg, self.y)

    def load(self, lookup, defs, vertexcache, usefallback=False):
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
                    defs[filename]=self.definition=ObjectFallback(filename, vertexcache, lookup, defs)
            return False

        # load children
        for child in self.definition.children:
            (childname, definition, xdelta, zdelta, hdelta)=child
            assert definition.filename in defs	# Child Def should have been created when AutoGenPointDef was loaded
            placement=Object(childname, self.lat, self.lon, self.hdg)
            placement.definition=definition
            self.placements.append([placement, xdelta, zdelta, hdelta])
        return True

    def draw_instance(self, glstate, selected, picking):
        Object.draw_instance(self, glstate, selected, picking)
        for p in self.placements:
            p[0].draw_instance(glstate, selected, picking)

    def draw_dynamic(self, glstate, selected, picking):
        Object.draw_dynamic(self, glstate, selected, picking)
        for p in self.placements:
            p[0].draw_dynamic(glstate, selected, picking)

    def clearlayout(self, vertexcache):
        Object.clearlayout(self, vertexcache)
        for p in self.placements:
            p[0].clearlayout(vertexcache)

    def flush(self, vertexcache):
        Object.flush(self, vertexcache)
        for p in self.placements:
            p[0].flush(vertexcache)

    if __debug__:
        def layoutp(self, tile, options, vertexcache, recalc=True):
            try:
                from cProfile import runctx
                runctx('self.layout2(tile, options, vertexcache, recalc)', globals(), locals(), 'profile.dmp')
            except:
                print_exc()

    def layout(self, tile, options, vertexcache, recalc=True):
        if self.islaidout() and not recalc:
            # just ensure allocated
            Object.layout(self, tile, options, vertexcache, recalc=False)
            for p in self.placements:
                p[0].layout(tile, options, vertexcache, recalc=False)
            return

        # We're likely to be doing a lot of height testing and draping, so pre-compute relevant mesh
        # triangles on the assumption that all children are contained in .agp's "floorplan"
        x,z=self.position(tile, self.lat, self.lon)
        abox=BBox()
        mymeshtris=[]
        h=radians(self.hdg)
        coshdg=cos(h)
        sinhdg=sin(h)
        for v in self.definition.draped:
            abox.include(x+v[0]*coshdg-v[2]*sinhdg, z+v[0]*sinhdg+v[2]*coshdg)
        for (bbox, meshtris) in vertexcache.getMeshdata(tile,options):
            if not abox.intersects(bbox): continue
            for meshtri in meshtris:
                (meshpt, coeffs)=meshtri
                (m0,m1,m2)=meshpt
                minx=min(m0[0], m1[0], m2[0])
                maxx=max(m0[0], m1[0], m2[0])
                minz=min(m0[2], m1[2], m2[2])
                maxz=max(m0[2], m1[2], m2[2])
                if abox.intersects(BBox(minx, maxx, minz, maxz)):
                    mymeshtris.append(meshtri)

        Object.layout(self, tile, options, vertexcache, x, None, z, self.hdg, mymeshtris)
        h=radians(self.hdg)
        coshdg=cos(h)
        sinhdg=sin(h)
        for p in self.placements:
            (child, xdelta, zdelta, hdelta)=p
            childx=x+xdelta*coshdg-zdelta*sinhdg
            childz=z+xdelta*sinhdg+zdelta*coshdg
            child.layout(tile, options, vertexcache, childx, None, childz, self.hdg+hdelta, mymeshtris)


class Polygon(Clutter):

    def __init__(self, name, param, nodes, lon=None, size=None, hdg=None):
        if param==None: param=0
        if lon==None:
            Clutter.__init__(self, name)
            self.nodes=nodes		# [[(lon,lat,...)]]
        else:
            lat=nodes
            Clutter.__init__(self, name, lat, lon)
            h=radians(hdg)
            self.nodes=[[]]
            size=0.000007071*size
            for i in [h+5*pi/4, h+3*pi/4, h+pi/4, h+7*pi/4]:
                self.nodes[0].append((max(floor(lon), min(floor(lon)+1, round2res(self.lon+sin(i)*size))),
                                      max(floor(lat), min(floor(lat)+1, round2res(self.lat+cos(i)*size)))))
        self.param=param
        self.nonsimple=False	# True iff non-simple and the polygon type cares about it (i.e. not Facades)
        self.closed=True	# Open or closed
        self.col=COL_POLYGON	# Outline colour
        self.points=[]		# list of windings in world space (x,y,z)

    def __str__(self):
        return '<"%s" %d %s>' % (self.name,self.param,self.points)

    def clone(self):
        return Polygon(self.name, self.param, [list(w) for w in self.nodes])

    def load(self, lookup, defs, vertexcache, usefallback=True):
        if self.name in lookup:
            filename=lookup[self.name].file
        else:
            filename=None
        self.definition=PolygonDef(filename, vertexcache, lookup, defs)
        return True
        
    def location(self):
        if self.lat==None:
            self.lat=self.lon=0
            n=len(self.nodes[0])
            for i in range(n):
                self.lon+=self.nodes[0][i][0]
                self.lat+=self.nodes[0][i][1]
            self.lat=self.lat/n
            self.lon=self.lon/n
        return [self.lat, self.lon]

    def locationstr(self, dms, node=None):
        if node:
            (i,j)=node
            hole=['', 'Hole '][i and 1]
            if self.points[i][j][1]:
                return '%s  Elv: %-6.1f  %sNode %d' % (latlondisp(dms, self.nodes[i][j][1], self.nodes[i][j][0]), self.points[i][j][1], hole, j)
            else:
                return '%s  %sNode %d' % (latlondisp(dms, self.nodes[i][j][1], self.nodes[i][j][0]), hole, j)
        else:
            return u'%s  Param\u2195 %-3d  (%d nodes)' % (latlondisp(dms, self.lat, self.lon), self.param, len(self.nodes[0]))

    def draw_instance(self, glstate, selected, picking):
        pass

    def draw_dynamic(self, glstate, selected, picking):
        assert self.islaidout() and self.base is not None, self
        if picking:
            assert not glstate.texture
            assert glstate.color
            glBegin(GL_POINTS)
            glVertex3f(*self.points[0][0])	# draw point at first node so selectable even if not visible
            glEnd()
        else:
            glstate.set_texture(None)
            glstate.set_color(selected and COL_SELECTED or None)
            glstate.set_depthtest(False)	# Need line to appear over terrain
        base=self.base
        if self.closed:
            for winding in self.points:
                glDrawArrays(GL_LINE_LOOP, base, len(winding))
                base+=len(winding)
        else:
            for winding in self.points:
                glDrawArrays(GL_LINE_STRIP, base, len(winding))
                base+=len(winding)

    def draw_nodes(self, glstate, selectednode):
        # Just do it in immediate mode
        glstate.set_texture(0)
        assert glstate.color==COL_SELECTED
        glstate.set_depthtest(False)
        for winding in self.points:
            if self.closed:
                glBegin(GL_LINE_LOOP)
            else:
                glBegin(GL_LINE_STRIP)
            for p in winding:
                glVertex3f(p[0],p[1],p[2])
            glEnd()
        glBegin(GL_POINTS)
        for i in range(len(self.points)):
            for j in range(len(self.points[i])):
                if selectednode==(i,j):
                    glstate.set_color(COL_SELNODE)
                else:
                    glstate.set_color(COL_SELECTED)
                glVertex3f(*self.points[i][j])
        glEnd()
        
    def clearlayout(self, vertexcache):
        self.points=[]
        self.dynamic_data=None	# Can be removed from VBO
        self.flush(vertexcache)

    def islaidout(self):
        return self.dynamic_data is not None

    def flush(self, vertexcache):
        vertexcache.allocate_dynamic(self, False)

    def layout_nodes(self, tile, options, vertexcache, selectednode):
        self.lat=self.lon=0
        self.points=[]
        self.nonsimple=False
        fittomesh=self.definition.fittomesh

        if not fittomesh:
            # elevation determined by mid-point of nodes 0 and 1
            if len(self.nodes[0])>1:
                self.lon=(self.nodes[0][0][0]+self.nodes[0][1][0])/2
                self.lat=(self.nodes[0][0][1]+self.nodes[0][1][1])/2
            else:	# shouldn't happen
                self.lon=self.nodes[0][0][0]
                self.lat=self.nodes[0][0][1]
            (x,z)=self.position(tile, self.lat, self.lon)
            y=vertexcache.height(tile,options,x,z)

        for i in range(len(self.nodes)):
            nodes=self.nodes[i]
            points=[]
            n=len(nodes)
            a=0
            for j in range(n):
                (x,z)=self.position(tile, nodes[j][1], nodes[j][0])
                if fittomesh:
                    y=vertexcache.height(tile,options,x,z)
                    if i==0:
                        self.lon+=nodes[j][0]
                        self.lat+=nodes[j][1]
                points.append((x,y,z))
                a+=nodes[j][0]*nodes[(j+1)%n][1]-nodes[(j+1)%n][0]*nodes[j][1]
            if self.closed and ((i==0 and a<0) or (i and a>0)):
                # Outer should be CCW, inner CW
                nodes.reverse()
                points.reverse()
                if selectednode and selectednode[0]==i: selectednode=(i,n-1-selectednode[1])
            self.points.append(points)

        if fittomesh:
            self.lat=self.lat/len(self.nodes[0])
            self.lon=self.lon/len(self.nodes[0])

        return selectednode

    def layout(self, tile, options, vertexcache, selectednode=None, recalc=True):
        if self.islaidout() and not recalc:
            # just ensure allocated
            vertexcache.allocate_dynamic(self, True)
            return selectednode
        selectednode=self.layout_nodes(tile, options, vertexcache, selectednode)
        col=self.nonsimple and COL_NONSIMPLE or self.col
        self.dynamic_data=concatenate([array(p+col,float32) for w in self.points for p in w])
        vertexcache.allocate_dynamic(self, True)
        return selectednode

    def addnode(self, tile, options, vertexcache, selectednode, lat, lon, clockwise=False):
        (i,j)=selectednode
        n=len(self.nodes[i])
        if (not self.closed) and (j==0 or j==n-1):
            # Special handling for ends of open lines and facades - add new node at cursor
            if j:
                newnode=nextnode=j+1
            else:
                newnode=nextnode=0
            self.nodes[i].insert(newnode, (lon, lat))
        else:
            if (i and clockwise) or (not i and not clockwise):
                newnode=j+1
                nextnode=(j+1)%n
            else:
                newnode=j
                nextnode=(j-1)%n
            self.nodes[i].insert(newnode,
                                 (round2res((self.nodes[i][j][0]+self.nodes[i][nextnode][0])/2),
                                  round2res((self.nodes[i][j][1]+self.nodes[i][nextnode][1])/2)))
        return self.layout(tile, options, vertexcache, (i,newnode))

    def delnode(self, tile, options, vertexcache, selectednode, clockwise=False):
        (i,j)=selectednode
        if len(self.nodes[i])<=(self.closed and 3 or 2):	# Open lines and facades can have just two nodes
            return self.delwinding(tile, options, vertexcache, selectednode)
        self.nodes[i].pop(j)
        if (i and clockwise) or (not i and not clockwise):
            selectednode=(i,(j-1)%len(self.nodes[i]))
        else:
            selectednode=(i,j%len(self.nodes[i]))
        self.layout(tile, options, vertexcache, selectednode)
        return selectednode

    def addwinding(self, tile, options, vertexcache, size, hdg):
        return False	# most polygon types don't support additional windings
        
    def delwinding(self, tile, options, vertexcache, selectednode):
        return False	# most polygon types don't support additional windings

    def move(self, dlat, dlon, dhdg, dparam, loc, tile, options, vertexcache):
        # do layout if changed
        for i in range(len(self.nodes)):
            for j in range(len(self.nodes[i])):
                self.movenode((i,j), dlat, dlon, 0, tile, options, vertexcache)
        if dhdg:
            for i in range(len(self.nodes)):
                for j in range(len(self.nodes[i])):
                    h=atan2(self.nodes[i][j][0]-loc[1],
                            self.nodes[i][j][1]-loc[0])+radians(dhdg)
                    l=hypot(self.nodes[i][j][0]-loc[1],
                            self.nodes[i][j][1]-loc[0])
                    self.nodes[i][j]=(max(tile[1], min(tile[1]+1, round2res(loc[1]+sin(h)*l))),
                                      max(tile[0], min(tile[0]+1, round2res(loc[0]+cos(h)*l))))	# trashes other parameters
        if dparam:
            self.param+=dparam
            if self.param<0: self.param=0
            elif self.param>65535: self.param=65535	# uint16
        if dlat or dlon or dhdg or dparam:
            self.layout(tile, options, vertexcache)

    def movenode(self, node, dlat, dlon, darg, tile, options, vertexcache, defer=True):
        # defer layout
        # Most polygons don't have co-ordinate arguments other than lat/lon & beziers, so darg ignored.
        if len(self.nodes[0][0])!=2:
            # Number of coordinates must be the same for all nodes in the polygon. Trash other coordinates e.g. bezier
            for i in range(len(self.nodes)):
                for j in range(len(self.nodes[i])):
                    self.nodes[i][j]=self.nodes[i][j][:2]
        (i,j)=node
        # points can be on upper boundary of tile
        self.nodes[i][j]=(max(tile[1], min(tile[1]+1, self.nodes[i][j][0]+dlon)),
                          max(tile[0], min(tile[0]+1, self.nodes[i][j][1]+dlat)))
        if defer:
            return node
        else:
            return self.layout(tile, options, vertexcache, node)
        
    def updatenode(self, node, lat, lon, tile, options, vertexcache):
        # update node height but defer full layout. Assumes lat,lon is valid
        if len(self.nodes[0][0])!=2:
            # Number of coordinates must be the same for all nodes in the polygon. Trash other coordinates e.g. bezier
            for i in range(len(self.nodes)):
                for j in range(len(self.nodes[i])):
                    self.nodes[i][j]=self.nodes[i][j][:2]
        (i,j)=node
        self.nodes[i][j]=(lon,lat)	# trashes other parameters
        (x,z)=self.position(tile, lat, lon)
        if self.definition.fittomesh:
            y=vertexcache.height(tile,options,x,z)
        else:
            y=self.points[i][j][1]	# assumes elevation already correct
        self.points[i][j]=(x,y,z)
        return node

    def pick_nodes(self, glstate):
        if glstate.occlusion_query:
            queryidx=0
            for i in range(len(self.points)):
                for j in range(len(self.points[i])):
                    glBeginQuery(glstate.occlusion_query, glstate.queries[queryidx])
                    glBegin(GL_POINTS)
                    glVertex3f(*self.points[i][j])
                    glEnd()
                    glEndQuery(glstate.occlusion_query)
                    queryidx+=1
        else:
            for i in range(len(self.points)):
                for j in range(len(self.points[i])):
                    glLoadName((i<<24)+j)
                    glBegin(GL_POINTS)
                    glVertex3f(*self.points[i][j])
                    glEnd()


class Beach(Polygon):
    # Editing would zap extra vertex parameters that we don't understand,
    # so make a dummy type to prevent selection and therefore editing

    def __init__(self, name, param, nodes, lon=None, size=None, hdg=None):
        Polygon.__init__(self, name, param, nodes, lon, size, hdg)

    def load(self, lookup, defs, vertexcache, usefallback=True):
        Polygon.load(self, lookup, defs, vertexcache, usefallback=True)
        self.definition.layer=ClutterDef.BEACHESLAYER

    def draw_dynamic(self, glstate, selected, picking):
        # Don't draw so can't be picked
        if not picking: Polygon.draw_dynamic(self, glstate, selected, picking)


# Like Draped, but for lines
class Fitted(Polygon):

    def __init__(self, name, param, nodes, lon=None, size=None, hdg=None):
        Polygon.__init__(self, name, param, nodes, lon, size, hdg)

    def layout(self, tile, options, vertexcache, selectednode=None, recalc=True):
        # insert intermediate nodes XXX
        return Polygon.layout(self, tile, options, vertexcache, selectednode, recalc)


class Draped(Polygon):

    def tessvertex(vertex, data):
        data.append(vertex)

    def tessedge(flag):
        pass	# dummy

    tess=gluNewTess()
    gluTessNormal(tess, 0, -1, 0)
    gluTessProperty(tess, GLU_TESS_WINDING_RULE, GLU_TESS_WINDING_NONZERO)
    gluTessCallback(tess, GLU_TESS_VERTEX_DATA,  tessvertex)
    gluTessCallback(tess, GLU_TESS_EDGE_FLAG,    tessedge)	# no strips

    def clone(self):
        return Draped(self.name, self.param, [list(w) for w in self.nodes])
        
    def load(self, lookup, defs, vertexcache, usefallback=False):
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

    def locationstr(self, dms, node=None):
        if node:
            return Polygon.locationstr(self, dms, node)
        elif self.param==65535:
            return '%s  (%d nodes)' % (latlondisp(dms, self.lat, self.lon), len(self.nodes[0]))
        else:
            return u'%s  Tex hdg\u2195 %-3d  (%d nodes)' % (latlondisp(dms, self.lat, self.lon), self.param, len(self.nodes[0]))

    def draw_dynamic(self, glstate, selected, picking):
        assert self.islaidout() and self.base is not None, self
        if self.nonsimple:
            Polygon.draw_dynamic(self, glstate, selected, picking)
            return
        elif picking:
            glBegin(GL_POINTS)
            glVertex3f(*self.points[0][0])	# draw point at first node so selectable even if not visible
            glEnd()
        else:
            glstate.set_texture(self.definition.texture)
            glstate.set_color(selected and COL_SELECTED or COL_UNPAINTED)
            glstate.set_cull(True)
            glstate.set_poly(True)
            glstate.set_depthtest(True)
        glDrawArrays(GL_TRIANGLES, self.base, len(self.dynamic_data)/6)
        
    def move(self, dlat, dlon, dhdg, dparam, loc, tile, options, vertexcache):
        if self.param==65535:
            n=len(self.nodes[0])
            if dparam>0:
                # rotate texture co-ords.
                if len(self.nodes[0][0])>=6:
                    uv0=self.nodes[0][0][4:6]
                else:
                    uv0=self.nodes[0][0][2:4]
                for j in range(n-1):
                    if len(self.nodes[0][j+1])>=6:
                        uv=self.nodes[0][j+1][4:6]
                    else:
                        uv=self.nodes[0][j+1][2:4]
                    self.nodes[0][j]=self.nodes[0][j][:2]+uv
                self.nodes[0][n-1]=self.nodes[0][n-1][:2]+uv0
            elif dparam<0:
                if len(self.nodes[0][n-1])>=6:
                    uv0=self.nodes[0][n-1][4:6]
                else:
                    uv0=self.nodes[0][n-1][2:4]
                for j in range(n-1,0,-1):
                    if len(self.nodes[0][j-1])>=6:
                        uv=self.nodes[0][j-1][4:6]
                    else:
                        uv=self.nodes[0][j-1][2:4]
                    self.nodes[0][j]=self.nodes[0][j][:2]+uv
                self.nodes[0][0]=self.nodes[0][0][:2]+uv0
        else:
            # rotate texture
            self.param=(self.param+dparam+dhdg)%360
        if dhdg:
            # preserve textures
            for i in range(len(self.nodes)):
                for j in range(len(self.nodes[i])):
                    if len(self.nodes[i][j])>=6:
                        # Ben says: a bezier polygon has 8 coords (lon lat of point, lon lat of control, ST of point, ST of control)
                        uv=self.nodes[i][j][4:6]
                    else:
                        uv=self.nodes[i][j][2:4]
                    h=atan2(self.nodes[i][j][0]-loc[1],
                            self.nodes[i][j][1]-loc[0])+radians(dhdg)
                    l=hypot(self.nodes[i][j][0]-loc[1],
                            self.nodes[i][j][1]-loc[0])
                    self.nodes[i][j]=(max(tile[1], min(tile[1]+1, round2res(loc[1]+sin(h)*l))),
                                      max(tile[0], min(tile[0]+1, round2res(loc[0]+cos(h)*l))))+uv
        if dlat or dlon:
            Polygon.move(self, dlat,dlon, 0,0, loc, tile, options, vertexcache)
        elif dhdg or dparam:
            self.layout(tile, options, vertexcache)

    def movenode(self, node, dlat, dlon, darg, tile, options, vertexcache, defer=True):
        # defer layout
        if self.param==65535:
            # Preserve node texture co-ords
            if len(self.nodes[0][0])!=4:
                # Number of coordinates must be the same for all nodes in the polygon. Trash other coordinates e.g. bezier
                for i in range(len(self.nodes)):
                    for j in range(len(self.nodes[i])):
                        self.nodes[i][j]=self.nodes[i][j][:2]+self.nodes[i][j][4:6]
            (i,j)=node
            self.nodes[i][j]=(max(tile[1], min(tile[1]+1, self.nodes[i][j][0]+dlon)),
                              max(tile[0], min(tile[0]+1, self.nodes[i][j][1]+dlat)))+self.nodes[i][j][2:4]
            if defer:
                return node
            else:
                return self.layout(tile, options, vertexcache, node)
        else:
            return Polygon.movenode(self, node, dlat, dlon, darg, tile, options, vertexcache, defer)

    def updatenode(self, node, lat, lon, tile, options, vertexcache):
        # update node height but defer full layout. Assumes lat,lon is valid
        if self.param==65535:
            # Preserve node texture co-ords
            (i,j)=node
            if len(self.nodes[0][0])!=4:
                # Number of coordinates must be the same for all nodes in the polygon. Trash other coordinates e.g. bezier
                for i in range(len(self.nodes)):
                    for j in range(len(self.nodes[i])):
                        self.nodes[i][j]=self.nodes[i][j][:2]+self.nodes[i][j][4:6]
            self.nodes[i][j]=(lon,lat)+self.nodes[i][j][2:4]
            (x,z)=self.position(tile, lat, lon)
            if self.definition.fittomesh:
                y=vertexcache.height(tile,options,x,z)
            else:
                y=self.points[i][j][1]	# assumes elevation already correct
            self.points[i][j]=(x,y,z)
            return node
        else:
            return Polygon.updatenode(self, node, lat, lon, tile, options, vertexcache)

    def layout(self, tile, options, vertexcache, selectednode=None, recalc=True, tls=None):
        if self.islaidout() and not recalc:
            # just ensure allocated
            vertexcache.allocate_dynamic(self, True)
            return selectednode
        tess=tls and tls.tess or Draped.tess
        selectednode=self.layout_nodes(tile, options, vertexcache, selectednode)
        # Tessellate to generate tri vertices with UV data, and check polygon is simple
        if self.param!=65535:
            drp=self.definition
            ch=cos(radians(self.param))
            sh=sin(radians(self.param))
        try:
            tris=[]
            gluTessBeginPolygon(tess, tris)
            for i in range(len(self.nodes)):
                gluTessBeginContour(tess)
                for j in range(len(self.nodes[i])):
                    if self.param==65535:
                        if len(self.nodes[i][j])>=6:
                            gluTessVertex(tess, array([self.points[i][j][0], 0, self.points[i][j][2]],float64), list(self.points[i][j]) + [self.nodes[i][j][4], self.nodes[i][j][5], 0])
                        else:
                            gluTessVertex(tess, array([self.points[i][j][0], 0, self.points[i][j][2]],float64), list(self.points[i][j]) + [self.nodes[i][j][2], self.nodes[i][j][3], 0])
                    else:	# projected
                        gluTessVertex(tess, array([self.points[i][j][0], 0, self.points[i][j][2]],float64), list(self.points[i][j]) + [(self.points[i][j][0]*ch+self.points[i][j][2]*sh)/drp.hscale, (self.points[i][j][0]*sh-self.points[i][j][2]*ch)/drp.vscale, 0])
                gluTessEndContour(tess)
            gluTessEndPolygon(tess)

            if __debug__:
                if not tris: print "Draped layout failed for %s - no tris" % self

        except:
            # Combine required -> not simple
            if __debug__:
                print "Draped layout failed for %s:" % self
                print_exc()
                tris=[]

        if not tris:
            self.nonsimple=True
            self.dynamic_data=concatenate([array(p+COL_NONSIMPLE,float32) for w in self.points for p in w])
        elif not options&Prefs.ELEVATION:
            self.dynamic_data=array(tris, float32).flatten()
        else:
            self.dynamic_data=array(drape(tris, tile, options, vertexcache, csgt=tls and tls.csgt), float32).flatten()
        if not tls:	# defer allocation if called in thread context
            vertexcache.allocate_dynamic(self, True)
        return selectednode


    def addnode(self, tile, options, vertexcache, selectednode, lat, lon, clockwise=False):
        if self.param==65535:
            return False	# we don't support new nodes in orthos
        return Polygon.addnode(self, tile, options, vertexcache, selectednode, lat, lon, clockwise)

    def delnode(self, tile, options, vertexcache, selectednode, clockwise=False):
        if self.param==65535:
            return False	# we don't support new nodes in orthos
        return Polygon.delnode(self, tile, options, vertexcache, selectednode, clockwise)

    def addwinding(self, tile, options, vertexcache, size, hdg):
        if self.param==65535:
            return False	# we don't support holes in orthos
        minrad=0.000007071*size
        for j in self.nodes[0]:
            minrad=min(minrad, abs(self.lon-j[0]), abs(self.lat-j[1]))
        i=len(self.nodes)
        h=radians(hdg)
        self.nodes.append([])
        for j in [h+5*pi/4, h+7*pi/4, h+pi/4, h+3*pi/4]:
            self.nodes[i].append((round2res(self.lon+sin(j)*minrad),
                                  round2res(self.lat+cos(j)*minrad)))
        return self.layout(tile, options, vertexcache, (i,0))

    def delwinding(self, tile, options, vertexcache, selectednode):
        (i,j)=selectednode
        if not i: return False	# don't delete outer winding
        self.nodes.pop(i)
        return self.layout(tile, options, vertexcache, (i-1,0))


# For draping a map image directly. name is the basename of image filename.
# Note isn't added to global defs, so has to be flushed separately.
class DrapedImage(Draped):

    def load(self, lookup, defs, vertexcache, usefallback=True):
        self.definition=DrapedFallback(self.name, vertexcache, lookup, defs)
        self.definition.texture=0
        self.definition.type=0	# override - we don't want this locked

    def islaidout(self):
        # DrapedImage texture is assigned *after* layout
        return self.dynamic_data is not None and self.definition.texture

    def draw_dynamic(self, glstate, selected, picking):
        # same as Draped, but don't set color since this is set in OnPaint() and may include opacity
        assert self.islaidout() and self.base is not None, self
        if self.nonsimple:
            Polygon.draw_dynamic(self, glstate, selected, picking)
            return
        elif not picking:
            glstate.set_texture(self.definition.texture)
            glstate.set_cull(True)
            glstate.set_poly(True)
            glstate.set_depthtest(True)
        glDrawArrays(GL_TRIANGLES, self.base, len(self.dynamic_data)/6)

class Exclude(Fitted):

    NAMES={'sim/exclude_bch': 'Exclude: Beaches',
           'sim/exclude_pol': 'Exclude: Draped polygons',
           'sim/exclude_fac': 'Exclude: Facades',
           'sim/exclude_for': 'Exclude: Forests',
           'sim/exclude_obj': 'Exclude: Objects',
           'sim/exclude_net': 'Exclude: '+NetworkDef.TABNAME,
           'sim/exclude_str': 'Exclude: Strings'}

    def __init__(self, name, param, nodes, lon=None, size=None, hdg=None):
        if lon==None:
            Fitted.__init__(self, name, param, nodes)
        else:
            lat=nodes
            Fitted.__init__(self, name, param, lat, lon, size, hdg)
            # Override default node placement
            self.nodes=[[]]
            size=0.000005*size
            for (lon,lat) in [(self.lon-size,self.lat-size),
                              (self.lon+size,self.lat-size),
                              (self.lon+size,self.lat+size),
                              (self.lon-size,self.lat+size)]:
                self.nodes[0].append((max(floor(self.lon), min(floor(self.lon)+1, round2res(lon))),
                                      max(floor(self.lat), min(floor(self.lat)+1, round2res(lat)))))
        self.col=COL_EXCLUDE

    def clone(self):
        return Exclude(self.name, self.param, [list(w) for w in self.nodes])

    def load(self, lookup, defs, vertexcache, usefallback=False):
        self.definition=ExcludeDef(self.name, vertexcache, lookup, defs)
        return True

    def locationstr(self, dms, node=None):
        # no elevation
        if node:
            (i,j)=node
            return '%s  Node %d' % (latlondisp(dms, self.nodes[i][j][1], self.nodes[i][j][0]), j)
        else:
            return '%s' % (latlondisp(dms, self.lat, self.lon))

    def addnode(self, tile, options, vertexcache, selectednode, lat, lon, clockwise=False):
        return False

    def delnode(self, tile, options, vertexcache, selectednode, lat, lon, clockwise=False):
        return False

    def move(self, dlat, dlon, dhdg, dparam, loc, tile, options, vertexcache):
        # no rotation
        Polygon.move(self, dlat, dlon, 0, 0, loc, tile, options, vertexcache)

    def movenode(self, node, dlat, dlon, darg, tile, options, vertexcache, defer=False):
        # changes adjacent nodes, so always do full layout immediately
        (i,j)=node
        lon=max(tile[1], min(tile[1]+1, self.nodes[i][j][0]+dlon))
        lat=max(tile[0], min(tile[0]+1, self.nodes[i][j][1]+dlat))
        return self.updatenode(node, lat, lon, tile, options, vertexcache)

    def updatenode(self, node, lat, lon, tile, options, vertexcache):
        (i,j)=node
        self.nodes[i][j]=(lon,lat)
        if j&1:
            self.nodes[i][(j-1)%4]=(self.nodes[i][(j-1)%4][0], lat)
            self.nodes[i][(j+1)%4]=(lon, self.nodes[i][(j+1)%4][1])
        else:
            self.nodes[i][(j+1)%4]=(self.nodes[i][(j+1)%4][0], lat)
            self.nodes[i][(j-1)%4]=(lon, self.nodes[i][(j-1)%4][1])
        # changed adjacent nodes, so do full layout immediately
        return self.layout(tile, options, vertexcache, node)


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
        if param==None:	# New placement - add wall type
            for j in range(len(self.nodes[0])):
                self.nodes[0][j]+=(0,)
        self.floorno=0		# for v10 - must keep in sync with self.param
        self.placements=[]	# child object placements
        self.datalen=0
        self.rooflen=0

    def clone(self):
        return Facade(self.name, self.param, [list(w) for w in self.nodes])

    def load(self, lookup, defs, vertexcache, usefallback=False):
        try:
            filename=lookup[self.name].file
            if filename in defs:
                self.definition=defs[filename]
            else:
                defs[filename]=self.definition=FacadeDef(filename, vertexcache, lookup, defs)
            if self.definition.version>=1000:
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
            elif not self.param:	# old-style
                wall=self.definition.walls[0]	# just use first wall
                vpanels=wall.vpanels
                self.param=sum([p.width for p in vpanels[0]+vpanels[2]])		# all bottom & top panels
                if not self.param: self.param=sum([p.width for p in vpanels[1]])	# else all middle panels
                self.param=max(int(0.5+self.param+wall.basement*wall.scale[1]),1)
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

    def locationstr(self, dms, node=None):
        if self.definition.version>=1000:
            floor=self.definition.floors[self.floorno]
            if node:
                (i,j)=node
                if len(floor.walls)>1 and (self.closed or j<len(self.nodes[i])-1):
                    wallno=len(self.nodes[i][j]) not in [3,5] and -1 or int(self.nodes[i][j][2])
                    return Polygon.locationstr(self, dms, node) + u'  Wall\u2195 ' + (0<=wallno<len(floor.walls) and floor.walls[wallno].name or 'undefined')
                else:	# Can't change wall type if only one wall, or if final node
                    return Polygon.locationstr(self, dms, node)
            elif len(self.definition.floors)>1:
                return u'%s  Height\u2195 %s  (%d nodes)' % (latlondisp(dms, self.lat, self.lon), floor.name, len(self.nodes[0]))
            else:	# Can't change height if only one floor
                return u'%s  (%d nodes)' % (latlondisp(dms, self.lat, self.lon), len(self.nodes[0]))

        else:	# old-style
            if node:
                return Polygon.locationstr(self, dms, node)
            else:
                return u'%s  Height\u2195 %-3d  (%d nodes)' % (latlondisp(dms, self.lat, self.lon), self.param, len(self.nodes[0]))

    def draw_instance(self, glstate, selected, picking):
        for p in self.placements:
            p.draw_instance(glstate, selected, picking)

    def draw_dynamic(self, glstate, selected, picking):
        assert self.islaidout() and self.base is not None, self
        fac=self.definition
        if self.nonsimple:
            Polygon.draw_dynamic(self, glstate, selected, picking)
        elif picking:
            Polygon.draw_dynamic(self, glstate, selected, picking)	# for outline
            glDrawArrays(GL_TRIANGLES, self.base, len(self.dynamic_data)/6)
            if self.rooflen:
                glDrawArrays(GL_TRIANGLES, self.base+self.datalen, self.rooflen)
        else:
            glstate.set_texture(fac.texture)
            glstate.set_color(selected and COL_SELECTED or COL_UNPAINTED)
            glstate.set_cull(not fac.two_sided)
            glstate.set_poly(False)
            glstate.set_depthtest(True)
            glDrawArrays(GL_TRIANGLES, self.base, self.datalen)
            if self.rooflen:
                glstate.set_texture(fac.texture_roof)
                glDrawArrays(GL_TRIANGLES, self.base+self.datalen, self.rooflen)
        for p in self.placements:
            p.draw_dynamic(glstate, selected, picking)
        
    def draw_nodes(self, glstate, selectednode):
        # Draws wall baseline in white if wall type is editable
        Polygon.draw_nodes(self, glstate, selectednode)
        if self.definition.version>=1000 and selectednode:
            floor=self.definition.floors[self.floorno]
            (i,j)=selectednode
            if len(floor.walls)>1 and (self.closed or j<len(self.nodes[i])-1):
                glstate.set_color(COL_SELNODE)
                glBegin(GL_LINES)
                glVertex3f(*self.points[i][j])
                glVertex3f(*self.points[i][(j+1)%len(self.nodes[i])])
                glEnd()
        
    def move(self, dlat, dlon, dhdg, dparam, loc, tile, options, vertexcache):
        if self.definition.version<1000:
            dparam=max(dparam, 1-self.param)	# can't have height 0
            Polygon.move(self, dlat, dlon, dhdg, dparam, loc, tile, options, vertexcache)
        else:
            if dhdg:
                # preserve wall type
                for i in range(len(self.nodes)):
                    for j in range(len(self.nodes[i])):
                        h=atan2(self.nodes[i][j][0]-loc[1],
                                self.nodes[i][j][1]-loc[0])+radians(dhdg)
                        l=hypot(self.nodes[i][j][0]-loc[1],
                                self.nodes[i][j][1]-loc[0])
                        self.nodes[i][j]=(max(tile[1], min(tile[1]+1, round2res(loc[1]+sin(h)*l))),
                                          max(tile[0], min(tile[0]+1, round2res(loc[0]+cos(h)*l))),
                                          len(self.nodes[i][j]) in [3,5] and int(self.nodes[i][j][2]) or 0)
            if dparam:
                if dparam>0:
                    self.floorno=min(self.floorno+1, len(self.definition.floors)-1)
                else:
                    self.floorno=max(self.floorno-1, 0)
                self.param=min(65535, max(1, int(round(self.definition.floors[self.floorno].height))))
            if dlat or dlon:
                Polygon.move(self, dlat,dlon, 0,0, loc, tile, options, vertexcache)
            elif dhdg or dparam:
                self.layout(tile, options, vertexcache)

    def movenode(self, node, dlat, dlon, darg, tile, options, vertexcache, defer=True):
        # defer layout
        if self.definition.version<1000:
            return Polygon.movenode(self, node, dlat, dlon, darg, tile, options, vertexcache, defer)
        else:
            if len(self.nodes[0][0])==5:
                # Number of coordinates must be the same for all nodes in the polygon. Trash other coordinates e.g. bezier
                for i in range(len(self.nodes)):
                    for j in range(len(self.nodes[i])):
                        self.nodes[i][j]=self.nodes[i][j][:3]
            elif len(self.nodes[0][0])!=3:
                # Number of coordinates must be the same for all nodes in the polygon. Add a wall type
                for i in range(len(self.nodes)):
                    for j in range(len(self.nodes[i])):
                        self.nodes[i][j]=self.nodes[i][j][:2]+(0,)
            # preserve/set wall type
            (i,j)=node
            floor=self.definition.floors[self.floorno]
            wallno=int(self.nodes[i][j][2])
            if darg>0:
                wallno=min(len(floor.walls)-1, max(0, wallno+1))
            elif darg<0:
                wallno=min(len(floor.walls)-1, max(0, wallno-1))
            self.nodes[i][j]=(max(tile[1], min(tile[1]+1, self.nodes[i][j][0]+dlon)),
                              max(tile[0], min(tile[0]+1, self.nodes[i][j][1]+dlat)),
                              wallno)
            if defer:
                return node
            else:
                return self.layout(tile, options, vertexcache, node)

    def updatenode(self, node, lat, lon, tile, options, vertexcache):
        # update node height but defer full layout. Assumes lat,lon is valid
        if self.definition.version<1000:
            return Polygon.updatenode(self, node, lat, lon, tile, options, vertexcache)
        else:
            if len(self.nodes[0][0])==5:
                # Number of coordinates must be the same for all nodes in the polygon. Trash other coordinates e.g. bezier
                for i in range(len(self.nodes)):
                    for j in range(len(self.nodes[i])):
                        self.nodes[i][j]=self.nodes[i][j][:3]
            elif len(self.nodes[0][0])!=3:
                # Number of coordinates must be the same for all nodes in the polygon. Add a wall type
                for i in range(len(self.nodes)):
                    for j in range(len(self.nodes[i])):
                        self.nodes[i][j]=self.nodes[i][j][:2]+(0,)
            # preserve wall type
            (i,j)=node
            self.nodes[i][j]=(lon,lat,self.nodes[i][j][2])
            (x,z)=self.position(tile, lat, lon)
            if self.definition.fittomesh:
                y=vertexcache.height(tile,options,x,z)
            else:
                y=self.points[i][j][1]	# assumes elevation already correct
            self.points[i][j]=(x,y,z)
            return node

    def addnode(self, tile, options, vertexcache, selectednode, lat, lon, clockwise=False):
        if self.definition.version<1000:
            return Polygon.addnode(self, tile, options, vertexcache, selectednode, lat, lon, clockwise)
        else:
            if len(self.nodes[0][0])==5:
                # Number of coordinates must be the same for all nodes in the polygon. Trash other coordinates e.g. bezier
                for i in range(len(self.nodes)):
                    for j in range(len(self.nodes[i])):
                        self.nodes[i][j]=self.nodes[i][j][:3]
            elif len(self.nodes[0][0])!=3:
                # Number of coordinates must be the same for all nodes in the polygon. Add a wall type
                for i in range(len(self.nodes)):
                    for j in range(len(self.nodes[i])):
                        self.nodes[i][j]=self.nodes[i][j][:2]+(0,)
            # preserve/set wall type
            (i,j)=selectednode
            n=len(self.nodes[i])
            if (not self.closed) and (j==0 or j==n-1):
                # Special handling for ends of open lines and facades - add new node at cursor
                if j:
                    newnode=nextnode=j+1
                else:
                    newnode=nextnode=0
                self.nodes[i].insert(newnode, (lon, lat, self.nodes[i][j][2]))	# inherit wall type
            else:
                if (i and clockwise) or (not i and not clockwise):
                    newnode=j+1
                    nextnode=(j+1)%n
                else:
                    newnode=j
                    nextnode=(j-1)%n
                self.nodes[i].insert(newnode,
                                     (round2res((self.nodes[i][j][0]+self.nodes[i][nextnode][0])/2),
                                      round2res((self.nodes[i][j][1]+self.nodes[i][nextnode][1])/2),
                                      self.nodes[i][j][2]))	# inherit wall type
        return self.layout(tile, options, vertexcache, (i,newnode))

    def clearlayout(self, vertexcache):
        Polygon.clearlayout(self, vertexcache)
        self.datalen=self.rooflen=0
        for p in self.placements:
            p.clearlayout(vertexcache)
        self.placements=[]

    def flush(self, vertexcache):
        Polygon.flush(self, vertexcache)
        for p in self.placements:
            p.flush(vertexcache)

    def layout(self, tile, options, vertexcache, selectednode=None, recalc=True):
        if self.islaidout() and not recalc:
            # just ensure allocated
            for p in self.placements:
                p.layout(tile, options, vertexcache, recalc=False)
            return Polygon.layout(self, tile, options, vertexcache, selectednode, False)

        selectednode=self.layout_nodes(tile, options, vertexcache, selectednode)
        if self.definition.version>=1000:
            return self.layout10(tile, options, vertexcache, selectednode)
        else:
            return self.layout8(tile, options, vertexcache, selectednode)

    def layout8(self, tile, options, vertexcache, selectednode):
        tris=[]
        roofpts=[]
        points=self.points[0]
        n=len(points)
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
                minx=minz=maxint
                maxx=maxz=-maxint
                for j in range(n):
                    # UV boundary taken from building footprint, not roof footprint
                    minx=min(minx, (points[j][0]*coshdg+points[j][2]*sinhdg))
                    maxx=max(maxx, (points[j][0]*coshdg+points[j][2]*sinhdg))
                    minz=min(minz, (points[j][0]*sinhdg-points[j][2]*coshdg))
                    maxz=max(maxz, (points[j][0]*sinhdg-points[j][2]*coshdg))
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
                    if not rooftris: print "Facade roof layout failed - no tris"
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

        vertexcache.allocate_dynamic(self, True)
        return selectednode

    def layout10(self, tile, options, vertexcache, selectednode):
        for p in self.placements:
            p.clearlayout(vertexcache)	# clear any dynamic allocation of children
        self.placements=[]
        tris=[]
        floor=self.definition.floors[self.floorno]
        points=self.points[0]
        n=len(points)
        for node in range(self.closed and n or n-1):
            (x,y,z)=points[node]
            (tox,toy,toz)=points[(node+1)%n]
            size=hypot(tox-x, z-toz)	# target wall length
            if size<=0: continue
            h=atan2(tox-x, z-toz) % twopi
            hdg=degrees(h)
            wallno=len(self.nodes[0][node]) in [3,5] and int(self.nodes[0][node][2]) or 0
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
                if segno==0 and (self.closed or node!=0):
                    # miter joint between first segment and previous wall
                    (prvx,prvy,prvz)=points[(node-1)%n]
                    sm=tan((atan2(prvx-x, z-prvz)%twopi + h)/2 - h+piby2)	# miter angle
                    for v in segment.mesh:
                        sz=hoffset+v[2]*hscale+v[0]*sm*(1+v[2]/segment.width)
                        vx=x+v[0]*coshdg-sz*sinhdg
                        vy=y+v[1]+sz*vscale
                        vz=z+v[0]*sinhdg+sz*coshdg
                        tris.append([vx,vy,vz,v[3],v[4],0])
                elif segno==s-1 and (self.closed or node!=n-2):
                    # miter joint between last segment and next wall
                    (nxtx,nxty,nxtz)=points[(node+2)%n]
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
                    placement=Object(childname, self.lat, self.lon, hdg+hdelta)
                    placement.definition=definition		# Child Def should have been created when FacadeDef was loaded
                    sz=hoffset+zdelta*hscale+xdelta*sm*(1+zdelta/segment.width)		# scale z, allowing for miter if 1st segment 
                    childx=x+xdelta*coshdg-sz*sinhdg
                    childz=z+xdelta*sinhdg+sz*coshdg
                    if is_draped:
                        childy=None
                    else:
                        childy=y+ydelta
                    placement.layout(tile, options, vertexcache, childx, childy, childz)
                    self.placements.append(placement)

            	hoffset-=segment.width*hscale

        self.dynamic_data=array(tris, float32).flatten()
        self.datalen=len(self.dynamic_data)/6

        if floor.roofs:
            # Tessellate to generate tri vertices with UV data, and check polygon is simple
            try:
                tris=[]
                (x,y,z)=points[0]
                (tox,toy,toz)=points[1]
                h=atan2(tox-x, z-toz) + piby2	# texture heading determined by nodes 0->1
                coshdg=cos(h)
                sinhdg=sin(h)
                s=self.definition.roofscale
                maxu=-maxint
                minv=maxint
                for j in range(n):
                    maxu=max(maxu, (points[j][0]*coshdg+points[j][2]*sinhdg)/s)
                    minv=min(minv, (points[j][0]*sinhdg-points[j][2]*coshdg)/s)
                gluTessBeginPolygon(Facade.tess, tris)
                gluTessBeginContour(Facade.tess)
                for j in range(n):
                    gluTessVertex(Facade.tess, array([points[j][0], 0, points[j][2]],float64), list(points[j]) + [(points[j][0]*coshdg+points[j][2]*sinhdg)/s-maxu, (points[j][0]*sinhdg-points[j][2]*coshdg)/s-minv, 0])
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
                self.rooflen=0
            else:
                rooftris=[]
                for roof in floor.roofs:
                    for tri in tris:
                        rooftris.append([tri[0],roof+tri[1]]+tri[2:6])
                roofdata=array(rooftris, float32).flatten()
                self.rooflen=len(roofdata)/6
                self.dynamic_data=concatenate((self.dynamic_data, roofdata))

        vertexcache.allocate_dynamic(self, True)
        return selectednode


class Forest(Fitted):

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
        Fitted.__init__(self, name, param, nodes, lon, size, hdg)
        self.col=COL_FOREST

    def clone(self):
        return Forest(self.name, self.param, [list(w) for w in self.nodes])

    def load(self, lookup, defs, vertexcache, usefallback=False):
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

    def locationstr(self, dms, node=None):
        if node:
            return Polygon.locationstr(self, dms, node)
        else:
            return u'%s  Density\u2195 %-4.1f%%  (%d nodes)' % (latlondisp(dms, self.lat, self.lon), self.param/2.55, len(self.nodes[0]))

    def move(self, dlat, dlon, dhdg, dparam, loc, tile, options, vertexcache):
        Polygon.move(self, dlat, dlon, dhdg, dparam, loc, tile, options, vertexcache)
        if self.param>255: self.param=255

    def addwinding(self, tile, options, vertexcache, size, hdg):
        minrad=0.000007071*size
        for j in self.nodes[0]:
            minrad=min(minrad, abs(self.lon-j[0]), abs(self.lat-j[1]))
        i=len(self.nodes)
        h=radians(hdg)
        self.nodes.append([])
        for j in [h+5*pi/4, h+7*pi/4, h+pi/4, h+3*pi/4]:
            self.nodes[i].append((round2res(self.lon+sin(j)*minrad),
                                  round2res(self.lat+cos(j)*minrad)))
        return self.layout(tile, options, vertexcache, (i,0))

    def delwinding(self, tile, options, vertexcache, selectednode):
        (i,j)=selectednode
        if not i: return False	# don't delete outer winding
        self.nodes.pop(i)
        return self.layout(tile, options, vertexcache, (i-1,0))

    def layout(self, tile, options, vertexcache, selectednode=None, recalc=True):
        if self.islaidout() and not recalc:
            # just ensure allocated
            return Polygon.layout(self, tile, options, vertexcache, selectednode, False)

        selectednode=self.layout_nodes(tile, options, vertexcache, selectednode)

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
        vertexcache.allocate_dynamic(self, True)
        return selectednode


class Line(Polygon):

    def __init__(self, name, param, nodes, lon=None, size=None, hdg=None):
        if lon==None:
            Polygon.__init__(self, name, param, nodes)
        else:
            lat=nodes
            Polygon.__init__(self, name, param, nodes, lon, size, hdg)
            # Override default node placement
            h=radians(hdg)
            self.nodes=[[]]
            size=0.000005*size
            for i in [h-piby2, h+piby2]:
                self.nodes[0].append((max(floor(lon), min(floor(lon)+1, round2res(self.lon+sin(i)*size))),
                                      max(floor(lat), min(floor(lat)+1, round2res(self.lat+cos(i)*size)))))

    def clone(self):
        return Line(self.name, self.param, [list(w) for w in self.nodes])

    def load(self, lookup, defs, vertexcache, usefallback=False):
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

    def locationstr(self, dms, node=None):
        if node:
            return Polygon.locationstr(self, dms, node)
        else:
            oc=self.closed and 'Closed' or 'Open'
            return u'%s  %s\u2195  (%d nodes)' % (latlondisp(dms, self.lat, self.lon), oc, len(self.nodes[0]))

    def layout(self, tile, options, vertexcache, selectednode=None, recalc=True):
        self.closed=(self.param and True)
        return Polygon.layout(self, tile, options, vertexcache, selectednode, recalc)

    def move(self, dlat, dlon, dhdg, dparam, loc, tile, options, vertexcache):
        dparam=min(dparam, 1-self.param)	# max 1
        Polygon.move(self, dlat, dlon, dhdg, dparam, loc, tile, options, vertexcache)


class Network(Fitted):

    def __init__(self, name, param, nodes, lon=None, size=None, hdg=None):
        self.index=param
        if lon!=None:
            # override default new nodes
            lat=nodes
            h=radians(hdg)
            self.nodes=[[]]
            size=0.000007071*size
            for i in [h, h+pi]:
                self.nodes[0].append((max(floor(lon), min(floor(lon)+1, round2res(self.lon+sin(i)*size))),
                                      max(floor(lat), min(floor(lat)+1, round2res(self.lat+cos(i)*size)))))	# note no elevation - filled in later
            Fitted.__init__(self, name, param, self.nodes)
        else:
            Fitted.__init__(self, name, param, nodes, lon, size, hdg)
            
    def __str__(self):
        return '<"%s" %d %s>' % (self.name,self.index,self.nodes)

    def clone(self):
        return Network(self.name, self.index, [list(w) for w in self.nodes])

    def load(self, lookup, defs, vertexcache, usefallback=False):
        try:
            if not self.name: raise IOError	# not in roads.net
            self.definition=defs[self.name]
            notfallback=True
        except:
            if __debug__:
                print_exc()
            if usefallback:
                self.definition=NetworkFallback('None', None, self.index)
            notfallback=False

        if False:#XXXself.definition.height==None:
            # remove intermediate nodes
            self.nodes[0][0]=self.nodes[0][0][:3]+[True]
            self.nodes[0][-1]=self.nodes[0][-1][:3]+[True]
            i=1
            while i<len(self.nodes[0])-1:
                if self.definition.height==None and abs(atan2(self.nodes[0][i-1][0]-self.nodes[0][i][0], self.nodes[0][i-1][1]-self.nodes[0][i][1]) - atan2(self.nodes[0][i][0]-self.nodes[0][i+1][0], self.nodes[0][i][1]-self.nodes[0][i+1][1])) < (pi/180):	# arbitrary - 1 degree
                    self.nodes[0].pop(i)
                else:
                    self.nodes[0][i]=self.nodes[0][i][:3]+[True]
                    print abs(atan2(self.nodes[0][i-1][0]-self.nodes[0][i][0], self.nodes[0][i-1][1]-self.nodes[0][i][1]) - atan2(self.nodes[0][i][0]-self.nodes[0][i+1][0], self.nodes[0][i][1]-self.nodes[0][i+1][1])) * 180/pi, min(hypot(self.nodes[0][i-1][0]-self.nodes[0][i][0], self.nodes[0][i-1][1]-self.nodes[0][i][1]), hypot(self.nodes[0][i][0]-self.nodes[0][i+1][0], self.nodes[0][i][1]-self.nodes[0][i+1][1]))
                    i+=1
        #else:
        #    # all nodes are control nodes
        #    self.nodes[0]=[i[:3]+[True] for i in self.nodes[0]]
        return notfallback

    def locationstr(self, dms, node=None):
        if node:
            (i,j)=node
            if self.definition.height!=None:
                return '%s  Elv: %-6.1f  Height: %-6.1f  Node %d' % (latlondisp(dms, self.nodes[i][j][1], self.nodes[i][j][0]), self.points[i][j][1], self.nodes[i][j][2]-self.points[i][j][1], j)
            else:
                return '%s  Elv: %-6.1f  Node %d' % (latlondisp(dms, self.nodes[i][j][1], self.nodes[i][j][0]), self.points[i][j][1], j)                
        else:
            return '%s  (%d nodes)' % (latlondisp(dms, self.lat, self.lon), len(self.nodes))

    def draw_instance(self, glstate, selected, picking):
        pass

    def draw_dynamic(self, glstate, selected, picking):
        # just draw outline
        if picking:
            # Can't pick if no elevation
            if not self.laidoutwithelevation: return
        else:
            glstate.set_texture(None)
            if selected:
                glstate.set_color(COL_SELECTED)
            else:
                glstate.set_color(self.definition.color)
        glstate.set_depthtest(False)
        glBegin(GL_LINE_STRIP)
        for p in self.points[0]:
            glVertex3f(p[0],p[1],p[2])
        glEnd()

    def draw_nodes(self, glstate, selectednode):
        glstate.set_texture(0)
        glstate.set_depthtest(False)
        glBegin(GL_POINTS)
        for j in range(len(self.points[0])):
            if selectednode==(0,j):
                glstate.set_color(COL_SELNODE)
            else:
                glstate.set_color(COL_SELECTED)
            glVertex3f(*self.points[0][j])
        glEnd()

    def clearlayout(self, vertexcache):
        self.laidoutwithelevation=False
        self.points=[]
        self.dynamic_data=None	# Can be removed from VBO
        vertexcache.allocate_dynamic(self, False)

    def islaidout(self):
        return self.dynamic_data is not None

    def layout(self, tile, options, vertexcache, selectednode=None, recalc=True):
        # XXX handle new
        self.laidoutwithelevation=options&Prefs.ELEVATION
        controlnodes=[i for i in self.nodes[0] if i[0]]

        self.lat=self.lon=0
        self.nodes=[[]]
        self.points=[[]]

        n=len(controlnodes)
        for j in range(n):
            self.lon+=controlnodes[j][0]
            self.lat+=controlnodes[j][1]
            (xj,zj)=self.position(tile, controlnodes[j][1], controlnodes[j][0])
            yj=vertexcache.height(tile,options,xj,zj)
            if j and self.definition.height==None:
                # XXX insert intermediate nodes
                pass
            x=xj
            y=yj
            z=zj
            self.nodes[0].append(controlnodes[j])
            self.points[0].append((x,y,z))

        self.lat=self.lat/n
        self.lon=self.lon/n
        return selectednode


def latlondisp(dms, lat, lon):
    if dms:
        if lat>=0:
            sgnlat='N'
        else:
            sgnlat='S'
        abslat=abs(lat)
        mmlat=(abslat-int(abslat)) * 60.0
        sslat=(mmlat-int(mmlat)) * 60.0
        if lon>=0:
            sgnlon='E'
        else:
            sgnlon='W'
        abslon=abs(lon)
        mmlon=(abslon-int(abslon)) * 60.0
        sslon=(mmlon-int(mmlon)) * 60.0
        return u'Lat: %s%02d\u00B0%02d\'%06.3f"  Lon: %s%03d\u00B0%02d\'%06.3f"' % (sgnlat, abslat, mmlat, sslat, sgnlon, abslon, mmlon, sslon)
    else:
        return "Lat: %.6f  Lon: %.6f" % (lat, lon)



# Tessellators for draped polygons

def tessvertex(vertex, data):
    data.append(vertex)

def tessedge(flag):
    pass	# dummy

def csgtvertex(vertex, data):
    data.append(vertex[0])

def csgtcombined(coords, vertex, weight):
    try:
        return csgtcombine(coords, vertex, weight)
    except:
        print_exc()

def csgtcombine(coords, vertex, weight):
    # interp height & UV at coords from vertices ([x,y,z,u,v,w], ismesh)
    #print
    #print vertex[0], weight[0]
    #print vertex[1], weight[1]
    #print vertex[2], weight[2]
    #print vertex[3], weight[3]

    # check for just two adjacent mesh triangles
    if vertex[0]==vertex[1]:
        # common case
        return vertex[0]
    elif vertex[0][0][0]==vertex[1][0][0] and vertex[0][0][2]==vertex[1][0][2] and vertex[0][1]:
        # Height discontinuity in terrain mesh - eg LIEE - wtf!
        #assert not weight[2] and not vertex[2] and not weight[3] and not vertex[3] and vertex[1][1]
        #print vertex[0], " ->"
        return vertex[0]

    # intersection of two lines - use terrain mesh line for height
    elif vertex[0][1]:
        # p1 and p2 have mesh height, p3 and p4 have uv
        assert weight[0] and weight[1] and weight[2] and weight[3] and vertex[1][1]
        p1=vertex[0][0]
        p2=vertex[1][0]
        p3=vertex[2][0]
        p4=vertex[3][0]
    else:
        # p1 and p2 have mesh height, p3 and p4 have uv
        assert weight[0] and weight[1] and weight[2] and weight[3] and vertex[2][1] and vertex[3][1]
        p1=vertex[2][0]
        p2=vertex[3][0]
        p3=vertex[0][0]
        p4=vertex[1][0]

    # height
    d=hypot(p2[0]-p1[0], p2[2]-p1[2])
    if not d:
        y=p1[1]
    else:
        ratio=(hypot(coords[0]-p1[0], coords[2]-p1[2])/d)
        y=p1[1]+ratio*(p2[1]-p1[1])

    # UV
    d=hypot(p4[0]-p3[0], p4[2]-p3[2])
    if not d:
        uv=p3[3:]
    else:
        ratio=(hypot(coords[0]-p3[0], coords[2]-p3[2])/d)
        uv=[p3[3]+ratio*(p4[3]-p3[3]),
            p3[4]+ratio*(p4[4]-p3[4]),
            p3[5]+ratio*(p4[5]-p3[5])]

    #print ([coords[0],y,coords[2]], True, uv), " ->"
    return ([coords[0],y,coords[2]]+uv, True)

def csgtedge(flag):
    pass	# dummy

# Helper to drape polygons across terrain
# Input - list of tri vertices [x,y,z,u,v,w]
# Output - list of tri vertices draped across terrain - [x,y,z,u,v,w]
def drape(tris, tile, options, vertexcache, meshtris=None, csgt=None):
    if not csgt: csgt=drape.csgt
    #if __debug__: clock=time.clock()
    # tesselator is expensive - minimise mesh triangles
    if not meshtris:
        abox=BBox()
        meshtris=[]
        for tri in tris:
            abox.include(tri[0],tri[2])
        for (bbox, bmeshtris) in vertexcache.getMeshdata(tile,options):
            if not abox.intersects(bbox): continue
            # This loop dominates execution time for the typical case of a small area
            for meshtri in bmeshtris:
                (meshpt, coeffs)=meshtri
                (m0,m1,m2)=meshpt
                # following code is unwrapped below for speed
                #tbox=BBox()
                #for m in meshpt:
                #    tbox.include(m[0],m[2])
                minx=min(m0[0], m1[0], m2[0])
                maxx=max(m0[0], m1[0], m2[0])
                minz=min(m0[2], m1[2], m2[2])
                maxz=max(m0[2], m1[2], m2[2])
                if abox.intersects(BBox(minx, maxx, minz, maxz)):
                    meshtris.append(meshtri)
    #if __debug__: clock2=time.clock()-clock

    csgttris=[]
    for i in range(0,len(tris),3):
        gluTessBeginPolygon(csgt, csgttris)
        gluTessBeginContour(csgt)
        tbox=BBox()
        for tri in tris[i:i+3]:
            tbox.include(tri[0],tri[2])
            gluTessVertex(csgt, array([tri[0],0,tri[2]],float64), (tri,False))
        gluTessEndContour(csgt)

        for meshtri in meshtris:
            gluTessBeginContour(csgt)
            (meshpt, coeffs)=meshtri
            (m0,m1,m2)=meshpt
            minx=min(m0[0], m1[0], m2[0])
            maxx=max(m0[0], m1[0], m2[0])
            minz=min(m0[2], m1[2], m2[2])
            maxz=max(m0[2], m1[2], m2[2])
            if not tbox.intersects(BBox(minx, maxx, minz, maxz)):
                continue
            for m in meshpt:
                x=m[0]
                z=m[2]
                # calculate a uv position
                (tri0,tri1,tri2)=tris[i:i+3]
                x0=tri0[0]
                z0=tri0[2]
                x1=tri1[0]-x0
                z1=tri1[2]-z0
                x2=tri2[0]-x0
                z2=tri2[2]-z0
                xp=x-x0
                zp=z-z0
                ah=x1*z2-x2*z1
                bh=x2*z1-x1*z2
                a=ah and (xp*z2-x2*zp)/ah
                b=bh and (xp*z1-x1*zp)/bh
                gluTessVertex(csgt, array([x,0,z],float64),
                              (m+[tri0[3]+a*(tri1[3]-tri0[3])+b*(tri2[3]-tri0[3]),
                                  tri0[4]+a*(tri1[4]-tri0[4])+b*(tri2[4]-tri0[4]),
                                  tri0[5]+a*(tri1[5]-tri0[5])+b*(tri2[5]-tri0[5])], True))
            gluTessEndContour(csgt)
        gluTessEndPolygon(csgt)

    #if __debug__: print "%6.3f time to drape %d tris against %d meshtris\n%6.3f of that in BBox" % (time.clock()-clock, len(tris)/3, len(meshtris), clock2)
    return csgttris

drape.csgt=gluNewTess()
gluTessNormal(drape.csgt, 0, -1, 0)
gluTessProperty(drape.csgt, GLU_TESS_WINDING_RULE, GLU_TESS_WINDING_ABS_GEQ_TWO)
gluTessCallback(drape.csgt, GLU_TESS_VERTEX_DATA,  csgtvertex)
if __debug__:
    gluTessCallback(drape.csgt, GLU_TESS_COMBINE,  csgtcombined)
else:
    gluTessCallback(drape.csgt, GLU_TESS_COMBINE,  csgtcombine)
gluTessCallback(drape.csgt, GLU_TESS_EDGE_FLAG,    csgtedge)	# no strips
