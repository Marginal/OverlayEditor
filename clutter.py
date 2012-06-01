# Derived classes expected to have following members:
# __init__
# __str__
# clone -> make a new copy, minus layout
# load -> read definition
# location -> returns (average) lat/lon
# layout -> fit to terrain
# clearlayout -> clear above
# move -> move and layout
# movenode -> move - no layout
# updatenode -> move node - no layout

from math import atan2, ceil, cos, degrees, floor, hypot, pi, radians, sin, tan
from numpy import array, array_equal, concatenate, empty, float32, float64
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
        self.dynamic_data=None	# Above laid out as array for inclusion in VBO
        self.base=None		# Offset in VBO

    def __str__(self):
        return '<Object "%s" %11.6f %10.6f %d %s>' % (
            self.name, self.lat, self.lon, self.hdg, self.y)

    def clone(self):
        return Object(self.name, self.lat, self.lon, self.hdg, self.y)

    def load(self, lookup, defs, vertexcache, usefallback=False):
        try:
            filename=lookup[self.name].file
            if filename in defs:
                self.definition=defs[filename]
                self.definition.allocate(vertexcache)	# ensure allocated
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
                    self.definition.allocate(vertexcache)	# ensure allocated
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
        if obj.vdata is None: return
        glLoadMatrixf(self.matrix)
        if picking:
            assert not glstate.cull
            # glstate.poly doesn't affect selection
            glDrawArrays(GL_TRIANGLES, obj.base, obj.culled+obj.nocull)
        else:
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
        glDrawArrays(GL_TRIANGLES, self.base, len(self.dynamic_data)/6)

    def draw_nodes(self, glstate, selectednode):
        pass

    def clearlayout(self, vertexcache):
        self.matrix=None
        self.dynamic_data=None	# Can be removed from VBO
        vertexcache.allocate_dynamic(self)

    def islaidout(self):
        return self.matrix is not None

    def layout(self, tile, options, vertexcache, x=None, y=None, z=None, hdg=None, meshtris=None):
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
        vertexcache.allocate_dynamic(self)

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
                self.definition.allocate(vertexcache)	# ensure allocated
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
                    self.definition.allocate(vertexcache)	# ensure allocated
                else:
                    defs[filename]=self.definition=ObjectFallback(filename, vertexcache, lookup, defs)
            return False

        # load children
        for child in self.definition.children:
            (childname, definition, xdelta, zdelta, hdelta)=child
            assert definition.filename in defs	# Child Def should have been created when AutoGenPointDef was loaded
            placement=Object(childname, self.lat, self.lon, self.hdg)
            placement.definition=definition
            placement.definition.allocate(vertexcache)	# ensure allocated
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

    if __debug__:
        def layoutp(self, tile, options, vertexcache):
            try:
                from cProfile import runctx
                runctx('self.layout2(tile, options, vertexcache)', globals(), locals(), 'profile.dmp')
            except:
                print_exc()

    def layout(self, tile, options, vertexcache):
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
        self.dynamic_data=None	# Above laid out as array for inclusion in VBO
        self.base=None		# Offset in VBO

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
        if not picking:
            glstate.set_texture(None)
            glstate.set_color(selected and COL_SELECTED or None)
            glstate.set_depthtest(False)	# Need line to appear over terrain
        else:
            assert not glstate.texture
            assert glstate.color
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
        vertexcache.allocate_dynamic(self)

    def islaidout(self):
        return self.points and True or False

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

    def layout(self, tile, options, vertexcache, selectednode=None):
        selectednode=self.layout_nodes(tile, options, vertexcache, selectednode)
        col=self.nonsimple and COL_NONSIMPLE or self.col
        self.dynamic_data=concatenate([array(p+col,float32) for w in self.points for p in w])
        vertexcache.allocate_dynamic(self)
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

    def layout(self, tile, options, vertexcache, selectednode=None):
        # insert intermediate nodes XXX
        return Polygon.layout(self, tile, options, vertexcache, selectednode)


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

    def __init__(self, name, param, nodes, lon=None, size=None, hdg=None):
        Polygon.__init__(self, name, param, nodes, lon, size, hdg)

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
        if self.nonsimple:
            Polygon.draw_dynamic(self, glstate, selected, picking)
            return
        elif not picking:
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

    def layout(self, tile, options, vertexcache, selectednode=None):
        selectednode=self.layout_nodes(tile, options, vertexcache, selectednode)
        # Tessellate to generate tri vertices with UV data, and check polygon is simple
        if __debug__: clock=time.clock()
        if self.param!=65535:
            drp=self.definition
            ch=cos(radians(self.param))
            sh=sin(radians(self.param))
        try:
            tris=[]
            gluTessBeginPolygon(Draped.tess, tris)
            for i in range(len(self.nodes)):
                gluTessBeginContour(Draped.tess)
                for j in range(len(self.nodes[i])):
                    if self.param==65535:
                        if len(self.nodes[i][j])>=6:
                            gluTessVertex(Draped.tess, array([self.points[i][j][0], 0, self.points[i][j][2]],float64), list(self.points[i][j]) + [self.nodes[i][j][4], self.nodes[i][j][5], 0])
                        else:
                            gluTessVertex(Draped.tess, array([self.points[i][j][0], 0, self.points[i][j][2]],float64), list(self.points[i][j]) + [self.nodes[i][j][2], self.nodes[i][j][3], 0])
                    else:	# projected
                        gluTessVertex(Draped.tess, array([self.points[i][j][0], 0, self.points[i][j][2]],float64), list(self.points[i][j]) + [(self.points[i][j][0]*ch+self.points[i][j][2]*sh)/drp.hscale, (self.points[i][j][0]*sh-self.points[i][j][2]*ch)/drp.vscale, 0])
                gluTessEndContour(Draped.tess)
            gluTessEndPolygon(Draped.tess)

            if __debug__:
                if not tris: print "Draped layout failed - no tris"

        except:
            # Combine required -> not simple
            if __debug__:
                print "Draped layout failed:"
                print_exc()
                tris=[]
        if __debug__: print "%6.3f time to tessellate" % (time.clock()-clock)

        if not tris:
            self.nonsimple=True
            self.dynamic_data=concatenate([array(p+COL_NONSIMPLE,float32) for w in self.points for p in w])
        elif not options&Prefs.ELEVATION:
            self.dynamic_data=array(tris, float32).flatten()
        else:
            self.dynamic_data=array(drape(tris, tile, options, vertexcache), float32).flatten()
        vertexcache.allocate_dynamic(self)
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
                self.param=maxint
                for (a,b) in self.definition.horiz:
                    self.param=min(self.param, int(ceil(self.definition.hscale * (b-a))))
                self.param=max(self.param,1)
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

    # Helper for layout
    def subdiv(self, size, scale, divs, ends, isvert):
        trgsize=size/scale
        #print size, scale, divs, ends, isvert, trgsize
        cumsize=0
        if ends[0]+ends[1]>=len(divs):
            points=range(len(divs))
            for i in points: cumsize+=divs[i][1]-divs[i][0]
            if cumsize==0: return (points,1)
            return (points,size/cumsize)

        if isvert:
            points1=range(ends[0])
            points2=range(len(divs)-ends[1], len(divs))
        else:
            points1=range(len(divs)-ends[1])
            points2=range(ends[0],len(divs))
        for i in points1+points2: cumsize+=divs[i][1]-divs[i][0]
        if cumsize<trgsize or isvert:
            points=range(ends[0], len(divs)-ends[1])
            extsize=0
            for i in points: extsize+=divs[i][1]-divs[i][0]
            i=int((trgsize-cumsize)/extsize)
            cumsize+=extsize*i
            points=points1 + points*i
            for i in range(ends[0], len(divs)-ends[1]):
                if cumsize+divs[i][1]-divs[i][0] > trgsize: break
                cumsize+=divs[i][1]-divs[i][0]
                points.append(i)
            points.extend(points2)
        else:
            points=points1+points2
            while cumsize>trgsize and (isvert or len(points)>1):
                i=max(0,min((len(points)-1+ends[0]-ends[1])/2, len(points)-1))
                cumsize-=(divs[points[i]][1]-divs[points[i]][0])
                points.pop(i)
        if isvert:
            #if points: points[-1]=len(divs)-1	# always end with roof
            return (points,scale)
        else:
            return (points,size/cumsize)

    def clearlayout(self, vertexcache):
        Polygon.clearlayout(self, vertexcache)
        self.datalen=self.rooflen=0
        for p in self.placements:
            p.clearlayout(vertexcache)

    def layout(self, tile, options, vertexcache, selectednode=None):
        selectednode=self.layout_nodes(tile, options, vertexcache, selectednode)
        if self.definition.version>=1000:
            return self.layout10(tile, options, vertexcache, selectednode)
        else:
            return self.layout8(tile, options, vertexcache, selectednode)

    def layout8(self, tile, options, vertexcache, selectednode):
        try:
            fac=self.definition
            points=self.points[0]
            n=len(points)
            (vert,vscale)=self.subdiv(self.param, fac.vscale, fac.vert,fac.vends, True)
            roofheight=0
            for i in range(len(vert)):
                roofheight+=(fac.vert[vert[i]][1]-fac.vert[vert[i]][0])
            roofheight*=fac.vscale	# not scaled to fit

            if fac.roof_slope:
                roofpts=[]
                dist=sin(radians(fac.roof_slope))*fac.vscale*(fac.vert[vert[-1]][1]-fac.vert[vert[-1]][0])
                for i in range(n):
                    if i==n-1 and not fac.ring:
                        tonext=(points[i][0]-points[i-1][0],
                                points[i][2]-points[i-1][2])
                    else:
                        tonext=(points[(i+1)%n][0]-points[i][0],
                                points[(i+1)%n][2]-points[i][2])
                    m=hypot(*tonext)
                    tonext=(tonext[0]/m, tonext[1]/m)
                    toprev=(points[(i-1)%n][0]-points[i][0],
                            points[(i-1)%n][2]-points[i][2])
                    m=hypot(*toprev)
                    toprev=(toprev[0]/m, toprev[1]/m)
                    d=toprev[0]*tonext[1]-toprev[1]*tonext[0]
                    if n==2 or d==0 or (not fac.ring and (i==0 or i==n-1)):
                        roofpts.append((points[i][0]+dist*tonext[1],
                                        points[i][1]+roofheight,
                                        points[i][2]-dist*tonext[0]))
                    else:
                        # http://astronomy.swin.edu.au/~pbourke/geometry/lineline2d
                        u=(toprev[0]*(dist*tonext[0]+dist*toprev[0])+
                           toprev[1]*(dist*tonext[1]+dist*toprev[1]))/d
                        roofpts.append((points[i][0]+dist*tonext[1]+u*tonext[0],
                                        points[i][1]+roofheight,
                                        points[i][2]-dist*tonext[0]+u*tonext[1]))
            else:
                roofpts=[(points[i][0], points[i][1]+roofheight, points[i][2]) for i in range(n)]

            data=[]
            quads=[]
            for wall in range(n-1+fac.ring):
                size=hypot(points[(wall+1)%n][0]-points[wall][0],
                           points[(wall+1)%n][2]-points[wall][2])
                if size==0: continue
                h=((points[(wall+1)%n][0]-points[wall][0])/size,
                   (points[(wall+1)%n][1]-points[wall][1])/size,
                   (points[(wall+1)%n][2]-points[wall][2])/size)
                r=((roofpts[(wall+1)%n][0]-roofpts[wall][0])/size,
                   (roofpts[(wall+1)%n][1]-roofpts[wall][1])/size,
                   (roofpts[(wall+1)%n][2]-roofpts[wall][2])/size)
                (horiz,hscale)=self.subdiv(size, fac.hscale, fac.horiz, fac.hends,False)
                cumheight=0
                for i in range(len(vert)-1):
                    heightinc=fac.vscale*(fac.vert[vert[i]][1]-fac.vert[vert[i]][0])
                    cumwidth=0
                    for j in range(len(horiz)):
                        widthinc=hscale*(fac.horiz[horiz[j]][1]-fac.horiz[horiz[j]][0])
                        quads.append((points[wall][0]+h[0]*cumwidth,
                                      points[wall][1]+h[1]*cumwidth+cumheight,
                                      points[wall][2]+h[2]*cumwidth,
                                      fac.horiz[horiz[j]][0],
                                      fac.vert[vert[i]][0]))
                        quads.append((points[wall][0]+h[0]*cumwidth,
                                      points[wall][1]+h[1]*cumwidth+cumheight+heightinc,
                                      points[wall][2]+h[2]*cumwidth,
                                      fac.horiz[horiz[j]][0],
                                      fac.vert[vert[i]][1]))
                        quads.append((points[wall][0]+h[0]*(cumwidth+widthinc),
                                      points[wall][1]+h[1]*(cumwidth+widthinc)+cumheight+heightinc,
                                      points[wall][2]+h[2]*(cumwidth+widthinc),
                                      fac.horiz[horiz[j]][1],
                                      fac.vert[vert[i]][1]))
                        quads.append((points[wall][0]+h[0]*(cumwidth+widthinc),
                                      points[wall][1]+h[1]*(cumwidth+widthinc)+cumheight,
                                      points[wall][2]+h[2]*(cumwidth+widthinc),
                                      fac.horiz[horiz[j]][1],
                                      fac.vert[vert[i]][0]))
                        cumwidth+=widthinc
                    cumheight+=heightinc
                # penthouse
                cumwidth=0
                for j in range(len(horiz)):
                    if not len(vert): continue
                    widthinc=hscale*(fac.horiz[horiz[j]][1]-fac.horiz[horiz[j]][0])
                    quads.append((points[wall][0]+h[0]*cumwidth,
                                  points[wall][1]+h[1]*cumwidth+cumheight,
                                  points[wall][2]+h[2]*cumwidth,
                                  fac.horiz[horiz[j]][0],
                                  fac.vert[vert[-1]][0]))
                    quads.append((roofpts[wall][0]+r[0]*cumwidth,
                                  roofpts[wall][1]+r[1]*cumwidth,
                                  roofpts[wall][2]+r[2]*cumwidth,
                                  fac.horiz[horiz[j]][0],
                                  fac.vert[vert[-1]][1]))
                    quads.append((roofpts[wall][0]+r[0]*(cumwidth+widthinc),
                                  roofpts[wall][1]+r[1]*(cumwidth+widthinc),
                                  roofpts[wall][2]+r[2]*(cumwidth+widthinc),
                                  fac.horiz[horiz[j]][1],
                                  fac.vert[vert[-1]][1]))
                    quads.append((points[wall][0]+h[0]*(cumwidth+widthinc),
                                  points[wall][1]+h[1]*(cumwidth+widthinc)+cumheight,
                                  points[wall][2]+h[2]*(cumwidth+widthinc),
                                  fac.horiz[horiz[j]][1],
                                  fac.vert[vert[-1]][0]))
                    cumwidth+=widthinc

            for i in range(0,len(quads),4):
                data.extend([array(quads[i  ]+(0,),float32),
                             array(quads[i+1]+(0,),float32),
                             array(quads[i+2]+(0,),float32),
                             array(quads[i  ]+(0,),float32),
                             array(quads[i+2]+(0,),float32),
                             array(quads[i+3]+(0,),float32)])
            
            # roof
            root=[]
            if n>2 and fac.ring and fac.roof:
                minx=minz=maxint
                maxx=maxz=-maxint
                for i in roofpts:
                    minx=min(minx,i[0])
                    maxx=max(maxx,i[0])
                    minz=min(minz,i[2])
                    maxz=max(maxz,i[2])
                xscale=(fac.roof[2][0]-fac.roof[0][0])/(maxx-minx)
                zscale=(fac.roof[2][1]-fac.roof[0][1])/(maxz-minz)
                (x,z)=self.position(tile, self.lat,self.lon)
                y=vertexcache.height(tile,options,x,z)+roofheight
                roof=[(x, y, z,
                       fac.roof[0][0] + (x-minx)*xscale,
                       fac.roof[0][1] + (z-minz)*zscale)]
                if n<=4:
                    for i in range(len(roofpts)-1, -1, -1):
                        roof.append((roofpts[i][0], roofpts[i][1], roofpts[i][2],
                                     fac.roof[3-i][0], fac.roof[3-i][1]))
                else:
                    for i in range(len(roofpts)-1, -1, -1):
                        roof.append((roofpts[i][0], roofpts[i][1], roofpts[i][2],
                                     fac.roof[0][0] + (roofpts[i][0]-minx)*xscale,
                                     fac.roof[0][1] + (roofpts[i][2]-minz)*zscale))
                for i in range(1,len(roofpts)-1):
                    data.extend([array(roof[0  ]+(0,),float32),
                                 array(roof[i]+(0,),float32),
                                 array(roof[i+1]+(0,),float32)])

            if not data: raise AssertionError	# wtf
            self.dynamic_data=concatenate(data)

        except:
            # layout error
            if __debug__:
                print "Facade layout failed:"
                print_exc()
            self.nonsimple=True
            self.dynamic_data=concatenate([array(p+COL_NONSIMPLE,float32) for w in self.points for p in w])

        self.datalen=len(self.dynamic_data)/6
        vertexcache.allocate_dynamic(self)
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
                    placement.definition.allocate(vertexcache)	# ensure allocated
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
                for i in range(len(self.nodes)):
                    gluTessBeginContour(Facade.tess)
                    for j in range(len(self.nodes[i])):
                        gluTessVertex(Facade.tess, array([self.points[i][j][0], 0, self.points[i][j][2]],float64), list(self.points[i][j]) + [(self.points[i][j][0]*coshdg+self.points[i][j][2]*sinhdg)/s-maxu, (self.points[i][j][0]*sinhdg-self.points[i][j][2]*coshdg)/s-minv, 0])
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

        vertexcache.allocate_dynamic(self)
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

    def layout(self, tile, options, vertexcache, selectednode=None):
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
        vertexcache.allocate_dynamic(self)
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

    def layout(self, tile, options, vertexcache, selectednode=None):
        self.closed=(self.param and True)
        return Polygon.layout(self, tile, options, vertexcache, selectednode)

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
            self.definition.allocate(vertexcache)	# ensure allocated
            notfallback=True
        except:
            if __debug__:
                print_exc()
            if usefallback:
                self.definition=NetworkFallback('None', None, self.index)
                self.definition.allocate(vertexcache)	# ensure allocated
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
        vertexcache.allocate_dynamic(self)

    def islaidout(self):
        return self.points and True or False

    def layout(self, tile, options, vertexcache, selectednode=None):
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

tess=gluNewTess()
gluTessNormal(tess, 0, -1, 0)
gluTessProperty(tess, GLU_TESS_WINDING_RULE, GLU_TESS_WINDING_NONZERO)
gluTessCallback(tess, GLU_TESS_VERTEX_DATA,  tessvertex)
gluTessCallback(tess, GLU_TESS_EDGE_FLAG,    tessedge)	# no strips


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

csgt=gluNewTess()
gluTessNormal(csgt, 0, -1, 0)
gluTessProperty(csgt, GLU_TESS_WINDING_RULE, GLU_TESS_WINDING_ABS_GEQ_TWO)
gluTessCallback(csgt, GLU_TESS_VERTEX_DATA,  csgtvertex)
if __debug__:
    gluTessCallback(csgt, GLU_TESS_COMBINE,  csgtcombined)
else:
    gluTessCallback(csgt, GLU_TESS_COMBINE,  csgtcombine)
gluTessCallback(csgt, GLU_TESS_EDGE_FLAG,    csgtedge)	# no strips

# Helper to drape polygons across terrain
# Input - list of tri vertices [x,y,z,u,v,w]
# Output - list of tri vertices draped across terrain - [x,y,z,u,v,w]
def drape(tris, tile, options, vertexcache, meshtris=None):
    global csgt

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
