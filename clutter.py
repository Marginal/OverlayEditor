# Virtual class for ground clutter - ie editable stuff
#
# Derived classes expected to have following members:
# __init__
# __str__
# clone -> make a new copy
# load -> read definition
# location -> returns (average) lat/lon
# layout -> fit to terrain
# clearlayout -> clear above
#

from math import atan2, cos, floor, hypot, pi, radians, sin
from OpenGL.GL import *
from OpenGL.GLU import *
try:
    # apparently older PyOpenGL version didn't define gluTessVertex
    gluTessVertex
except NameError:
    from OpenGL import GLU
    gluTessVertex = GLU._gluTessVertex

from clutterdef import ObjectDef, PolygonDef, DrapedDef, ExcludeDef, FacadeDef, ForestDef, DrapedFallback, FacadeFallback, SkipDefs
from prefs import Prefs

onedeg=1852*60	# 1 degree of longitude at equator (60nm) [m]
d2r=pi/180.0
resolution=8*65535
minres=1.0/resolution
maxres=1-minres

def round2res(x):
    i=floor(x)
    return i+round((x-i)*resolution,0)*minres


def PolygonFactory(name, param, nodes):
    "creates and initialises appropriate Polgon subclass based on file extension"
    # would like to have made this a 'static' method of Polygon
    if name.startswith(PolygonDef.EXCLUDE):
        return Exclude(name, param, nodes)
    ext=name.lower()[-4:]
    if ext==PolygonDef.DRAPED:
        return Draped(name, param, nodes)
    elif ext==PolygonDef.FACADE:
        return Facade(name, param, nodes)
    elif ext==PolygonDef.FOREST:
        return Forest(name, param, nodes)
    elif ext==PolygonDef.BEACH:
        return Beach(name, param, nodes)
    elif ext==ObjectDef.OBJECT:
        raise IOError		# not a polygon
    elif ext in SkipDefs:
        raise IOError		# what's this doing here?
    else:	# unknown polygon type
        return Polygon(name, param, nodes)


class Clutter:

    def __init__(self, name):
        self.name=name		# virtual name
        
    def position(self, lat, lon):
        # returns (x,z) position relative to centre of enclosing tile
        # z is positive south
        return (((lon%1)-0.5)*onedeg*cos(d2r*lat),
                (0.5-(lat%1))*onedeg)


class Object(Clutter):

    def __init__(self, name, lat, lon, hdg, y=None):
        Clutter.__init__(self, name)
        self.lat=lat
        self.lon=lon
        self.hdg=hdg
        self.definition=None
        self.x=self.z=None
        self.y=y

    def __str__(self):
        return '<"%s" %11.6f %10.6f %d %s>' % (
            self.name, self.lat, self.lon, self.hdg, self.y)

    def clone(self):
        return Object(self.name, self.lat, self.lon, self.hdg, self.y)

    def load(self, lookup, defs, vertexcache, usefallback=False):
        if 1:#XXX try:
            filename=lookup[self.name]
            if filename in defs:
                self.definition=defs[filename]
                self.definition.allocate(vertexcache)
            else:
                defs[filename]=self.definition=ObjectDef(filename, vertexcache)
            return True
        else:#except:
            # virtual name not found or can't load physical file
            if usefallback:
                filename=ObjectDef.FALLBACK
                if filename in defs:
                    self.definition=defs[filename]
                    self.definition.allocate(vertexcache)
                else:
                    defs[filename]=self.definition=ObjectDef(filename, vertexcache)
            return False
        
    def location(self):
        return [self.lat, self.lon]

    def locationstr(self, node=None):
        if self.y:
            return 'Lat: %-10.6f  Lon: %-11.6f  Hdg: %-3.0f  Elv: %-6.1f' % (self.lat, self.lon, self.hdg, self.y)
        else:
            return 'Lat: %-10.6f  Lon: %-11.6f  Hdg: %-3.0f' % (self.lat, self.lon, self.hdg)

    def draw(self, selected, withnodes, selectednode):
        obj=self.definition
        poly=obj.poly
        if selected: poly+=1
        if poly:
            glEnable(GL_POLYGON_OFFSET_FILL)
            glPolygonOffset(-1*poly, -1*poly)
            #glDepthMask(GL_FALSE)	# offset mustn't update depth
        glBindTexture(GL_TEXTURE_2D, obj.texture)
        glPushMatrix()
        glTranslatef(self.x, self.y, self.z)
        glRotatef(-self.hdg, 0.0,1.0,0.0)
        if selected:
            # cull face enabled
            glDrawArrays(GL_TRIANGLES, obj.base, obj.culled+obj.nocull)
        else:
            if obj.culled:
                glEnable(GL_CULL_FACE)
                glDrawArrays(GL_TRIANGLES, obj.base, obj.culled)
            if obj.nocull:
                glDisable(GL_CULL_FACE)
                glDrawArrays(GL_TRIANGLES, obj.base+obj.culled, obj.nocull)
        glPopMatrix()
        if poly:
            glDisable(GL_POLYGON_OFFSET_FILL)
            #glDepthMask(GL_TRUE)

    def clearlayout(self):
        self.x=self.y=self.z=None

    def layout(self, tile, options, vertexcache):
        (self.x,self.z)=self.position(self.lat, self.lon)
        self.y=vertexcache.height(tile,options,self.x,self.z)

    def move(self, dlat, dlon, dhdg, dparam, tile, options, vertexcache):
        self.lat=max(floor(self.lat), min(floor(self.lat)+maxres, self.lat+dlat))
        self.lon=max(floor(self.lon), min(floor(self.lon)+maxres, self.lon+dlon))
        self.hdg=(self.hdg+dhdg)%360
        self.layout(tile, options, vertexcache)
        

class Polygon(Clutter):

    def __init__(self, name, param, nodes):
        Clutter.__init__(self, name)
        self.lat=self.lon=0	# For centreing etc
        self.param=param
        self.nodes=nodes	# [[(lon,lat,...)]]
        self.definition=None
        self.lat=self.lon=None	# cached location
        self.points=[[]]	# list of windings in world space (x,y,z)

    def __str__(self):
        return '<"%s" %d %s>' % (self.name,self.param,self.points)

    def clone(self):
        return Polygon(self.name, self.param, [list(w) for w in self.nodes])

    def load(self, lookup, defs, vertexcache, usefallback=True):
        if self.name in lookup:
            filename=lookup[self.name]
        else:
            filename=None
        self.definition=PolygonDef(filename, vertexcache)
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

    def locationstr(self, node):
        if node:
            (i,j)=node
            if self.points[i][j]:
                return 'Lat: %-10.6f  Lon: %-11.6f  Elv: %-6.1f  Node %d' % (self.nodes[i][j][1], self.nodes[i][j][0], self.points[i][j][1], j)
            else:
                return 'Lat: %-10.6f  Lon: %-11.6f  Node %d' % (self.nodes[i][j][1], self.nodes[i][j][0], j)
        else:
            return 'Lat: %-10.6f  Lon: %-11.6f  Param: %-4d  (%d nodes)' % (self.lat, self.lon, self.param, len(self.nodes[0]))

    def draw(self, selected, withnodes, selectednode):
        # just draw lines
        if not selected: glColor3f(0.25, 0.25, 0.25)
        glBindTexture(GL_TEXTURE_2D, 0)
        if withnodes: glDisable(GL_DEPTH_TEST)
        for winding in self.points:
            glBegin(GL_LINE_LOOP)
            for p in winding:
                glVertex3f(p[0],p[1],p[2])
            glEnd()
        if withnodes:
            glBegin(GL_POINTS)
            for i in range(len(self.points)):
                for j in range(len(self.points[i])):
                    if selectednode==(i,j):
                        glColor3f(1.0, 1.0, 1.0)
                    else:
                        glColor3f(1.0, 0.5, 1.0)
                    glVertex3f(*self.points[i][j])
            glEnd()

    def clearlayout(self):
        self.points=[]

    def layout(self, tile, options, vertexcache, selectednode=None):

        self.lat=self.lon=0
        self.points=[]

        for i in range(len(self.nodes)):
            nodes=self.nodes[i]
            points=[]
            n=len(nodes)
            a=0
            for j in range(n):
                (x,z)=self.position(nodes[j][1], nodes[j][0])
                y=vertexcache.height(tile,options,x,z)
                points.append((x,y,z))
                if not i:
                    self.lon+=nodes[j][0]
                    self.lat+=nodes[j][1]
                a+=nodes[j][0]*nodes[(j+1)%n][1]-nodes[(j+1)%n][0]*nodes[j][1]
            if (not i and a<0) or (i and a>0):
                # Outer should be CCW, inner CW
                nodes.reverse()
                points.reverse()
                if selectednode and selectednode[0]==i: selectednode=(i,n-1-selectednode[1])
            self.points.append(points)

        self.lat=self.lat/len(self.nodes[0])
        self.lon=self.lon/len(self.nodes[0])
        if selectednode: return selectednode

    def move(self, dlat, dlon, dhdg, dparam, tile, options, vertexcache):
        for i in range(len(self.nodes)):
            for j in range(len(self.nodes[i])):
                self.movenode((i,j), dlat, dlon, tile, options, vertexcache)
        if dhdg:
            for i in range(len(self.nodes)):
                for j in range(len(self.nodes[i])):
                    h=atan2(self.nodes[i][j][0]-self.lon,
                            self.nodes[i][j][1]-self.lat)+radians(dhdg)
                    l=hypot(self.nodes[i][j][0]-self.lon,
                            self.nodes[i][j][1]-self.lat)
                    self.nodes[i][j]=(max(floor(self.nodes[i][j][0]), min(floor(self.nodes[i][j][0])+maxres, self.nodes[i][j][0]+round2res(cos(h)*l))),
                                      max(floor(self.nodes[i][j][1]), min(floor(self.nodes[i][j][1])+maxres, self.nodes[i][j][1]+round2res(sin(h)*l))))	# note trashes other values
        if dparam:
            self.param+=dparam
            if self.param<1: self.param=1
        elif self.param>65535: self.param=65535	# uint16
        self.layout(tile, options, vertexcache)
        
    def movenode(self, node, dlat, dlon, tile, options, vertexcache):
        # defer layout
        (i,j)=node
        self.nodes[i][j]=(max(floor(self.nodes[i][j][0]), min(floor(self.nodes[i][j][0])+maxres, self.nodes[i][j][0]+dlon)),
                          max(floor(self.nodes[i][j][1]), min(floor(self.nodes[i][j][1])+maxres, self.nodes[i][j][1]+dlat)))	# note trashes other values
        return self.layout(tile, options, vertexcache, node)
        
    def updatenode(self, node, lat, lon, tile, options, vertexcache):
        # update node height but defer full layout. Assumes lat,lon is valid
        (i,j)=node
        self.nodes[i][j]=(lon,lat)
        (x,z)=self.position(lat, lon)
        y=vertexcache.height(tile,options,x,z)
        self.points[i][j]=(x,y,z)
        return node

    def picknodes(self):
        for i in range(len(self.points)):
            for j in range(len(self.points[i])):
                glLoadName((i<<8)+j)
                glBegin(GL_POINTS)
                glVertex3f(*self.points[i][j])
                glEnd()


class Beach(Polygon):
    # Editing would zap extra vertex parameters, so make a dummy type
    # to prevent selection and therefore editing

    def __init__(self, name, param, nodes):
        Polygon.__init__(self, name, param, nodes)

    def load(self, lookup, defs, vertexcache, usefallback=True):
        Polygon.load(self, lookup, defs, vertexcache, usefallback=True)
        self.definition.layer=ClutterDef.BEACHESLAYER

    def draw(self, selected, withnodes, selectednode):
        # Don't draw selected so can't be picked
        if not selected: Polygon.draw(self, selected, withnodes, selectednode)
    

class Draped(Polygon):

    def __init__(self, name, param, nodes):
        Polygon.__init__(self, name, param, nodes)
        self.tris=[]	# tesellated tris

    def clone(self):
        return Draped(self.name, self.param, [list(w) for w in self.nodes])
        
    def load(self, lookup, defs, vertexcache, usefallback=False):
        if 1:#XXX try:
            filename=lookup[self.name]
            if filename in defs:
                self.definition=defs[filename]
            else:
                defs[filename]=self.definition=DrapedDef(filename, vertexcache)
            return True
        else:#except:
            if usefallback:
                # don't put in defs, so will get another error if
                # physical file is used again
                if self.name in lookup:
                    filename=lookup[self.name]
                else:
                    filename=None
                self.definition=DrapedFallback(filename, vertexcache)
            return False

    def locationstr(self, node):
        if node:
            return Polygon.locationstr(self, node)
        elif self.param==65535:
            return 'Lat: %-10.6f  Lon: %-11.6f  (%d nodes)' % (self.lat, self.lon, len(self.nodes[0]))
        else:
            return 'Lat: %-10.6f  Lon: %-11.6f  Tex hdg: %-3d  (%d nodes)' % (self.lat, self.lon, self.param, len(self.nodes[0]))

    def draw(self, selected, withnodes, selectednode):
        # XXX placeholder
        drp=self.definition
        glBindTexture(GL_TEXTURE_2D, drp.texture)
        glEnable(GL_POLYGON_OFFSET_FILL)
        if selected:
            glPolygonOffset(-3, -3)
        else:
            glPolygonOffset(-2, -2)
        #for winding in self.points:
        #    glBegin(GL_POLYGON)
        #    for p in winding:
        #        glVertex3f(p[0],p[1],p[2])
        #    glEnd()
        glBegin(GL_TRIANGLES)
        for i in range(len(self.tris)):
            glTexCoord2f(*self.tris[i][1])
            glVertex3f(*self.tris[i][0])
        glEnd()
        glDisable(GL_POLYGON_OFFSET_FILL)
        if selected:
            # Add lines & points
            Polygon.draw(self, selected, withnodes, selectednode)
        
    def move(self, dlat, dlon, dhdg, dparam, tile, options, vertexcache):
        if self.param==65535:
            # XXX Preserve node texture co-ords.
            # XXX rotate texture co-ords.
            pass
        else:
            # rotate texture
            self.param=(self.param+dparam+dhdg)%360
        Polygon.move(self, dlat, dlon, dhdg, 0, tile, options, vertexcache)

    def movenode(self, node, dlat, dlon, tile, options, vertexcache):
        # defer layout
        if self.param==65535:
            # Preserve node texture co-ords
            (i,j)=node
            if len(self.nodes[i][j])>=6:
                # Ben says: a bezier polygon has 8 coords (lon lat of point, lon lat of control, ST of point, ST of control)
                uv=self.nodes[i][j][4:6]
            else:
                uv=self.nodes[i][j][2:4]
            self.nodes[i][j]=(max(floor(self.nodes[i][j][0]), min(floor(self.nodes[i][j][0])+maxres, self.nodes[i][j][0]+dlon)),
                              max(floor(self.nodes[i][j][1]), min(floor(self.nodes[i][j][1])+maxres, self.nodes[i][j][1]+dlat)))+uv
            return self.layout(tile, options, vertexcache, node)
        else:
            return Polygon.movenode(self, node, dlat, dlon, tile, options, vertexcache)

    def layout(self, tile, options, vertexcache, selectednode=None):
        selectednode=Polygon.layout(self, tile, options, vertexcache, selectednode)
        self.tris=[]
        drp=self.definition
        tess=vertexcache.tess
        #gluTessCallback(tess, GLU_TESS_BEGIN_DATA,  self.tessbegin)
        gluTessCallback(tess, GLU_TESS_VERTEX_DATA, self.tessvertex)
        #gluTessCallback(tess, GLU_TESS_END_DATA,    self.tessend)
        gluTessCallback(tess, GLU_TESS_COMBINE,     self.tesscombine)
        gluTessBeginPolygon(tess, self.tris)
        if options&Prefs.ELEVATION:
            gluTessProperty(tess, GLU_TESS_WINDING_RULE, GLU_TESS_WINDING_ABS_GEQ_TWO)
            vertexcache.tessellate(tile, options)	# do terrain
        else:
            gluTessProperty(tess, GLU_TESS_WINDING_RULE, GLU_TESS_WINDING_NONZERO)
        for i in range(len(self.nodes)):
            #self.tris.append([])
            n=len(self.nodes[i])
            gluTessBeginContour(tess)
            if self.param!=65535:
                ub=self.points[i][0][0]/drp.hscale
                vb=self.points[i][0][2]/drp.hscale
            for j in range(n-1,-1,-1): # XXX n
                if self.param==65535:
                    if len(self.nodes[i][j])>=6:	# has beziers
                        uv=self.nodes[i][j][4:6]
                    else:
                        uv=self.nodes[i][j][2:4]
                else:
                    u=self.points[i][j][0]/drp.hscale-ub
                    v=-self.points[i][j][2]/drp.vscale+vb
                    h=radians(self.param)
                    uv=[u*cos(h)+v*sin(h),u*sin(h)+v*cos(h)]
                gluTessVertex(tess, [self.points[i][j][0], 0, self.points[i][j][2]], (self.points[i][j], uv))
                print self.points[i][j], uv
            gluTessEndContour(tess)
        gluTessEndPolygon(tess)

    def tesscombine(self, coords, vertex, weight):
        p1=p2=None
        y=0
        dump=((vertex[0] and vertex[0][1]) or (vertex[1] and vertex[1][1]) or (vertex[2] and vertex[2][1]) or (vertex[3] and vertex[3][1]))
        if dump: print '->', coords
        # interesting input points are those with uv data
        # linearly interpolate uv at coords
        # relies on undocumented assumption that vertices are supplied in pairs
        for i in range(4):
            if dump: print "%.2f" % weight[i], vertex[i]
            if weight[i]: y+=vertex[i][0][1]*weight[i]
        if weight[0] and vertex[0][1] and weight[1] and vertex[1][1]:
            p1=0
            p2=1
        elif weight[2] and vertex[2][1] and weight[3] and vertex[3][1]:
            p1=2
            p2=3
        else:
            uv=None #assert(0)
        if p2:
            ratio=(hypot(coords[0]-vertex[p1][0][0],
                         coords[2]-vertex[p1][0][2])/      
                   hypot(vertex[p2][0][0]-vertex[p1][0][0],
                         vertex[p2][0][2]-vertex[p1][0][2]))
            uv=[vertex[p1][1][0]+ratio*(vertex[p2][1][0]-vertex[p1][1][0]),
                vertex[p1][1][1]+ratio*(vertex[p2][1][1]-vertex[p1][1][1])]
        if dump: print '<-', [coords[0],y,coords[2]], uv
        return ([coords[0],y,coords[2]], uv)

    #def tessbegin(datatype, data):
    #    assert(datatype==GL_TRIANGLES)
    #    data[-1].append([])

    def tessvertex(self, vertex, data):
        data.append(vertex)

    def tessend(self, data):
        # check that this is an interesting triangle - ie has location
        print data
        for i in range(-3,0):
            if data[i] and data[i][0]:
                break
        else:	# not interesting
            data[-3:]=[]


class Exclude(Polygon):

    NAMES={'sim/exclude_bch': 'Exclude: Beaches',
           'sim/exclude_pol': 'Exclude: Draped polygons',
           'sim/exclude_fac': 'Exclude: Facades',
           'sim/exclude_for': 'Exclude: Forests',
           'sim/exclude_obj': 'Exclude: Objects',
           'sim/exclude_net': 'Exclude: Networks (Powerlines, Railways & Roads)',
           'sim/exclude_str': 'Exclude: Strings'}

    def __init__(self, name, param, nodes):
        Polygon.__init__(self, name, param, nodes)

    def clone(self):
        return Exclude(self.name, self.param, [list(w) for w in self.nodes])

    def load(self, lookup, defs, vertexcache, usefallback=False):
        self.definition=ExcludeDef(None, vertexcache)
        return True

    def locationstr(self, node):
        if node:
            (i,j)=node
            return 'Lat: %-10.6f  Lon: %-11.6f  Node %d' % (self.nodes[i][j][1], self.nodes[i][j][0], j)
            return Polygon.locationstr(self, node)
        else:
            return 'Lat: %-10.6f  Lon: %-11.6f' % (self.lat, self.lon)

    def updatenode(self, node, lat, lon, tile, options, vertexcache):
        (i,j)=node
        self.nodes[i][j]=(lon,lat)
        if j&1:
            self.nodes[i][(j-1)%4]=(self.nodes[i][(j-1)%4][0], lat)
            self.nodes[i][(j+1)%4]=(lon, self.nodes[i][(j+1)%4][1])
        else:
            self.nodes[i][(j+1)%4]=(self.nodes[i][(j+1)%4][0], lat)
            self.nodes[i][(j-1)%4]=(lon, self.nodes[i][(j-1)%4][1])
        # changed adjacenet nodes, so do full layout immediately
        return self.layout(tile, options, vertexcache, node)

    def draw(self, selected, withnodes, selectednode):
        if selected:
            Polygon.draw(self, selected, withnodes, selectednode)
        else:
            glBindTexture(GL_TEXTURE_2D, 0)
            glColor3f(0.5, 0.125, 0.125)
            glBegin(GL_LINE_LOOP)
            for p in self.points[0]:
                glVertex3f(p[0],p[1],p[2])
            glEnd()

    def move(self, dlat, dlon, dhdg, dparam, tile, options, vertexcache):
        # no rotation
        Polygon.move(self, dlat, dlon, 0, 0, tile, options, vertexcache)


class Facade(Polygon):

    def __init__(self, name, param, nodes):
        Polygon.__init__(self, name, param, nodes)
        self.quads=[]		# list of points (x,y,z,s,t)
        self.roof=[]		# list of points (x,y,z,s,t)

    def clone(self):
        return Facade(self.name, self.param, [list(w) for w in self.nodes])

    def load(self, lookup, defs, vertexcache, usefallback=False):
        if 1:#XXX try:
            filename=lookup[self.name]
            if filename in defs:
                self.definition=defs[filename]
            else:
                defs[filename]=self.definition=FacadeDef(filename, vertexcache)
            return True
        else:#except:
            if usefallback:
                # don't put in defs, so will get another error if
                # physical file is used again
                if self.name in lookup:
                    filename=lookup[self.name]
                else:
                    filename=None
                self.definition=FacadeFallback(filename, vertexcache)
            return False

    def locationstr(self, node):
        if node:
            return Polygon.locationstr(self, node)
        else:
            return 'Lat: %-10.6f  Lon: %-11.6f  Height: %-3d  (%d nodes)' % (self.lat, self.lon, self.param, len(self.nodes[0]))

    def draw(self, selected, withnodes, selectednode):
        if selected:
            glEnable(GL_POLYGON_OFFSET_FILL)
            glPolygonOffset(-1, -1)
            glDepthMask(GL_FALSE)	# offset mustn't update depth
        fac=self.definition
        glBindTexture(GL_TEXTURE_2D, fac.texture)
        if fac.two_sided:
            glDisable(GL_CULL_FACE)
        else:
            glEnable(GL_CULL_FACE)
        glBegin(GL_QUADS)
        for p in self.quads:
            glTexCoord2f(p[3],p[4])
            glVertex3f(p[0],p[1],p[2])
        glEnd()
        if self.roof:
            glBegin(GL_TRIANGLE_FAN)	# Better for concave
            for p in self.roof+[self.roof[1]]:
                glTexCoord2f(p[3],p[4])
                glVertex3f(p[0],p[1],p[2])
            glEnd()
        if selected:
            # Add lines & points
            glDisable(GL_POLYGON_OFFSET_FILL)
            glDepthMask(GL_TRUE)
            Polygon.draw(self, selected, withnodes, selectednode)
            
        
    # Helper for layout
    def subdiv(self, size, scale, divs, ends, isvert):
        trgsize=size/scale
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


    def layout(self, tile, options, vertexcache, selectednode=None):
        selectednode=Polygon.layout(self, tile, options, vertexcache, selectednode)

        self.quads=[]
        self.roof=[]

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
            dist=sin(d2r*fac.roof_slope)*fac.vscale*(fac.vert[vert[-1]][1]-fac.vert[vert[-1]][0])
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

        for wall in range(n-1+fac.ring):
            size=hypot(points[(wall+1)%n][0]-points[wall][0],
                       points[(wall+1)%n][2]-points[wall][2])
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
                    self.quads.append((points[wall][0]+h[0]*cumwidth,
                                       points[wall][1]+h[1]*cumwidth+cumheight,
                                       points[wall][2]+h[2]*cumwidth,
                                       fac.horiz[horiz[j]][0],
                                       fac.vert[vert[i]][0]))
                    self.quads.append((points[wall][0]+h[0]*cumwidth,
                                       points[wall][1]+h[1]*cumwidth+cumheight+heightinc,
                                       points[wall][2]+h[2]*cumwidth,
                                       fac.horiz[horiz[j]][0],
                                       fac.vert[vert[i]][1]))
                    self.quads.append((points[wall][0]+h[0]*(cumwidth+widthinc),
                                       points[wall][1]+h[1]*(cumwidth+widthinc)+cumheight+heightinc,
                                       points[wall][2]+h[2]*(cumwidth+widthinc),
                                       fac.horiz[horiz[j]][1],
                                       fac.vert[vert[i]][1]))
                    self.quads.append((points[wall][0]+h[0]*(cumwidth+widthinc),
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
                self.quads.append((points[wall][0]+h[0]*cumwidth,
                                   points[wall][1]+h[1]*cumwidth+cumheight,
                                   points[wall][2]+h[2]*cumwidth,
                                   fac.horiz[horiz[j]][0],
                                   fac.vert[vert[-1]][0]))
                self.quads.append((roofpts[wall][0]+r[0]*cumwidth,
                                   roofpts[wall][1]+r[1]*cumwidth,
                                   roofpts[wall][2]+r[2]*cumwidth,
                                   fac.horiz[horiz[j]][0],
                                   fac.vert[vert[-1]][1]))
                self.quads.append((roofpts[wall][0]+r[0]*(cumwidth+widthinc),
                                   roofpts[wall][1]+r[1]*(cumwidth+widthinc),
                                   roofpts[wall][2]+r[2]*(cumwidth+widthinc),
                                   fac.horiz[horiz[j]][1],
                                   fac.vert[vert[-1]][1]))
                self.quads.append((points[wall][0]+h[0]*(cumwidth+widthinc),
                                   points[wall][1]+h[1]*(cumwidth+widthinc)+cumheight,
                                   points[wall][2]+h[2]*(cumwidth+widthinc),
                                   fac.horiz[horiz[j]][1],
                                   fac.vert[vert[-1]][0]))
                cumwidth+=widthinc

        # roof
        if n<=2 or not fac.ring or not fac.roof: return selectednode
        minx=minz=maxint
        maxx=maxz=-maxint
        for i in roofpts:
            minx=min(minx,i[0])
            maxx=max(maxx,i[0])
            minz=min(minz,i[2])
            maxz=max(maxz,i[2])
        xscale=(fac.roof[2][0]-fac.roof[0][0])/(maxx-minx)
        zscale=(fac.roof[2][1]-fac.roof[0][1])/(maxz-minz)
        (x,z)=self.latlon2m(self.lat,self.lon)
        y=self.vertexcache.height(self.tile,self.options,x,z)+roofheight
        self.roof=[(x, y, z,
                    fac.roof[0][0] + (x-minx)*xscale,
                    fac.roof[0][1] + (z-minz)*zscale)]
        if n<=4:
            for i in range(len(roofpts)-1, -1, -1):
                self.roof.append((roofpts[i][0], roofpts[i][1], roofpts[i][2],
                                  fac.roof[3-i][0], fac.roof[3-i][1]))
            return
        for i in range(len(roofpts)-1, -1, -1):
            self.roof.append((roofpts[i][0], roofpts[i][1], roofpts[i][2],
                              fac.roof[0][0] + (roofpts[i][0]-minx)*xscale,
                              fac.roof[0][1] + (roofpts[i][2]-minz)*zscale))
        return selectednode


class Forest(Polygon):

    def __init__(self, name, param, nodes):
        Polygon.__init__(self, name, param, nodes)

    def clone(self):
        return Forest(self.name, self.param, [list(w) for w in self.nodes])

    def load(self, lookup, defs, vertexcache, usefallback=False):
        if 1:#XXX try:
            filename=lookup[self.name]
            if filename in defs:
                self.definition=defs[filename]
            else:
                defs[filename]=self.definition=ForestDef(filename, vertexcache)
            return True
        else:#except:
            if usefallback:
                # don't put in defs, so will get another error if
                # physical file is used again
                if self.name in lookup:
                    filename=lookup[self.name]
                else:
                    filename=None
                self.definition=ForestFallback(filename, vertexcache)
            return False

    def locationstr(self, node):
        if node:
            return Polygon.locationstr(self, node)
        else:
            return 'Lat: %-10.6f  Lon: %-11.6f  Density: %-4.1f%%  (%d nodes)' % (self.lat, self.lon, self.param/2.55, len(self.nodes[0]))

    def draw(self, selected, withnodes, selectednode):
        glBindTexture(GL_TEXTURE_2D, 0)
        glColor3f(0.125, 0.4, 0.125)
        if selected:
            # XXX fill interior
            # Add lines & points
            glColor3f(0.8, 0.8, 0.8)	# Unpainted
            Polygon.draw(self, selected, withnodes, selectednode)
        else:
            for winding in self.points:
                glBegin(GL_LINE_LOOP)
                for p in winding:
                    glVertex3f(p[0],p[1],p[2])
                glEnd()

    def move(self, dlat, dlon, dhdg, dparam, tile, options, vertexcache):
        Polygon.move(self, dlat, dlon, dhdg, dparam, tile, options, vertexcache)
        if self.param>255: self.param=255
