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

#
# 3 draw modes: normal, selected, picking:
#
# normal:
#   called in display list
#   GL_TEXTURE_2D enabled
#   CULL_FACE enabled
#   GL_POLYGON_OFFSET_FILL disabled
#   can use PolygonOffset -1 (unless MacOS 10.3)
#   GL_DEPTH_TEST: enabled
#   glDepthMask enabled
#   glColor3f(unpainted colour)
#
# selected / drawnodes:
#   NOT called in display list
#   GL_TEXTURE_2D enabled
#   CULL_FACE enabled
#   GL_POLYGON_OFFSET_FILL enabled
#   PolygonOffset -2 (so overwrites in drag select)
#   GL_DEPTH_TEST: enabled
#   glDepthMask enabled
#   glColor3f(selected colour)
#
# picking:
#   called in display list
#   GL_TEXTURE_2D disabled
#   CULL_FACE disabled (so can select reverse)
#   GL_POLYGON_OFFSET_FILL disabled
#   don't use PolygonOffset
#   GL_DEPTH_TEST: enabled
#   glDepthMask enabled
#


from math import atan2, ceil, cos, floor, hypot, pi, radians, sin
from OpenGL.GL import *
from OpenGL.GLU import *
from sys import maxint
if __debug__:
    from traceback import print_exc

try:
    # apparently older PyOpenGL version didn't define gluTessVertex
    gluTessVertex
except NameError:
    from OpenGL import GLU
    gluTessVertex = GLU._gluTessVertex

from clutterdef import ObjectDef, PolygonDef, DrapedDef, ExcludeDef, FacadeDef, ForestDef, LineDef, NetworkDef, NetworkFallback, ObjectFallback, DrapedFallback, FacadeFallback, ForestFallback, LineFallback, SkipDefs, BBox
from prefs import Prefs

onedeg=1852*60	# 1 degree of longitude at equator (60nm) [m]
resolution=8*65535
minres=1.0/resolution
maxres=1-minres
minhdg=360.0/65535


def round2res(x):
    i=floor(x)
    return i+round((x-i)*resolution,0)*minres


def PolygonFactory(name, param, nodes, lon=None, size=None, hdg=None):
    "creates and initialises appropriate Polgon subclass based on file extension"
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
        self.x=self.z=None
        self.y=y

    def __str__(self):
        return '<"%s" %11.6f %10.6f %d %s>' % (
            self.name, self.lat, self.lon, self.hdg, self.y)

    def clone(self):
        return Object(self.name, self.lat, self.lon, self.hdg, self.y)

    def load(self, lookup, defs, vertexcache, usefallback=False):
        try:
            filename=lookup[self.name]
            if filename in defs:
                self.definition=defs[filename]
                self.definition.allocate(vertexcache, defs)	# ensure allocated
            else:
                defs[filename]=self.definition=ObjectDef(filename, vertexcache)
            return True
        except:
            # virtual name not found or can't load physical file
            if usefallback:
                if self.name in lookup:
                    filename=lookup[self.name]
                else:
                    filename=lookup[self.name]=self.name
                if filename in defs:
                    self.definition=defs[filename]
                    self.definition.allocate(vertexcache, defs)	# ensure allocated
                else:
                    defs[filename]=self.definition=ObjectFallback(filename, vertexcache)
            return False
        
    def location(self):
        return [self.lat, self.lon]

    def locationstr(self, dms, node=None):
        if self.y:
            return '%s  Hdg: %-5.1f  Elv: %-6.1f' % (latlondisp(dms, self.lat, self.lon), self.hdg, self.y)
        else:
            return '%s  Hdg: %-5.1f' % (latlondisp(dms, self.lat, self.lon), self.hdg)

    def draw(self, selected, picking):
        obj=self.definition
        glPushMatrix()
        glTranslatef(self.x, self.y, self.z)
        if self.hdg: glRotatef(-self.hdg, 0.0,1.0,0.0)
        if picking:
            # cull face disabled
            glDrawArrays(GL_TRIANGLES, obj.base, obj.culled+obj.nocull)
        else:
            glBindTexture(GL_TEXTURE_2D, obj.texture)
            if obj.poly and not selected:
                #glDepthMask(GL_FALSE) - doesn't work with inwards facing faces
                glEnable(GL_POLYGON_OFFSET_FILL)
            if obj.culled:
                glEnable(GL_CULL_FACE)
                glDrawArrays(GL_TRIANGLES, obj.base, obj.culled)
            if obj.nocull:
                glDisable(GL_CULL_FACE)
                glDrawArrays(GL_TRIANGLES, obj.base+obj.culled, obj.nocull)
                glEnable(GL_CULL_FACE)
            if obj.poly and not selected:
                #glDepthMask(GL_TRUE)
                glDisable(GL_POLYGON_OFFSET_FILL)
        glPopMatrix()

    def drawnodes(self, selectednode):
        pass

    def clearlayout(self):
        self.x=self.y=self.z=None

    def islaidout(self):
        return self.x!=None

    def layout(self, tile, options, vertexcache):
        (self.x,self.z)=self.position(tile, self.lat, self.lon)
        self.y=vertexcache.height(tile,options,self.x,self.z)

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
                                      (max(floor(lat), min(floor(lat)+1, round2res(self.lat+cos(i)*size))))))
        self.param=param
        self.points=[]		# list of windings in world space (x,y,z)
        self.nonsimple=False

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

    def locationstr(self, dms, node=None):
        if node:
            (i,j)=node
            hole=['', 'Hole '][i and 1]
            if self.points[i][j][1]:
                return '%s  Elv: %-6.1f  %sNode %d' % (latlondisp(dms, self.nodes[i][j][1], self.nodes[i][j][0]), self.points[i][j][1], hole, j)
            else:
                return '%s  %sNode %d' % (latlondisp(dms, self.nodes[i][j][1], self.nodes[i][j][0]), hole, j)
        else:
            return '%s  Param: %-3d  (%d nodes)' % (latlondisp(dms, self.lat, self.lon), self.param, len(self.nodes[0]))

    def draw(self, selected, picking, col=(0.25, 0.25, 0.25)):
        # just draw outline
        if not picking:
            glBindTexture(GL_TEXTURE_2D, 0)
            if not selected:
                if self.nonsimple:
                    glColor3f(1.0,0.25,0.25)	# override colour if nonsimple
                else:
                    glColor3f(*col)
        glDisable(GL_DEPTH_TEST)
        for winding in self.points:
            glBegin(GL_LINE_LOOP)
            for p in winding:
                glVertex3f(p[0],p[1],p[2])
            glEnd()
        glEnable(GL_DEPTH_TEST)
        if not selected and not picking:
            glColor3f(0.8, 0.8, 0.8)	# restore

    def drawnodes(self, selectednode):
        Polygon.draw(self, True, False)	# draw lines
        glBindTexture(GL_TEXTURE_2D, 0)
        glDisable(GL_DEPTH_TEST)
        glBegin(GL_POINTS)
        for i in range(len(self.points)):
            for j in range(len(self.points[i])):
                if selectednode==(i,j):
                    glColor3f(1.0, 1.0, 1.0)
                else:
                    glColor3f(1.0, 0.5, 1.0)
                glVertex3f(*self.points[i][j])
        glEnd()
        glEnable(GL_DEPTH_TEST)        
        
    def clearlayout(self):
        self.points=[]

    def islaidout(self):
        return self.points and True

    def layout(self, tile, options, vertexcache, selectednode=None):
        global tess
        self.lat=self.lon=0
        self.points=[]
        self.nonsimple=False

        for i in range(len(self.nodes)):
            nodes=self.nodes[i]
            points=[]
            n=len(nodes)
            a=0
            for j in range(n):
                (x,z)=self.position(tile, nodes[j][1], nodes[j][0])
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

        if isinstance(self, Draped):
            return selectednode	# Draped does its own tesselation

        # tessellate. This is just to check polygon is simple
        try:
            tris=[]
            gluTessBeginPolygon(tess, tris)
            for i in range(len(self.nodes)):
                gluTessBeginContour(tess)
                for j in range(len(self.nodes[i])):
                    gluTessVertex(tess, [self.points[i][j][0], 0, self.points[i][j][2]], (self.points[i][j], False, None))
                gluTessEndContour(tess)
            gluTessEndPolygon(tess)
            if not tris:
                if __debug__: print "Polygon layout failed"
                self.nonsimple=True
        except:
            # Combine required -> not simple
            if __debug__: print "Polygon layout failed"
            self.nonsimple=True
        
        return selectednode

    def addnode(self, tile, options, vertexcache, selectednode, clockwise):
        (i,j)=selectednode
        n=len(self.nodes[i])
        if (i and clockwise) or (not i and not clockwise):
            newnode=nextnode=(j+1)%n
        else:
            newnode=j
            nextnode=(j-1)%n
        selectednode=(i,newnode)
        self.nodes[i].insert(newnode,
                             (round2res((self.nodes[i][j][0]+self.nodes[i][nextnode][0])/2),
                              round2res((self.nodes[i][j][1]+self.nodes[i][nextnode][1])/2)))
        self.layout(tile, options, vertexcache, selectednode)
        return selectednode

    def delnode(self, tile, options, vertexcache, selectednode, clockwise):
        (i,j)=selectednode
        if len(self.nodes[i])<4:
            return False
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
                self.movenode((i,j), dlat, dlon, tile, options, vertexcache)
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
        
    def movenode(self, node, dlat, dlon, tile, options, vertexcache, defer=True):
        # defer layout
        (i,j)=node
        # points can be on upper boundary of tile
        self.nodes[i][j]=(max(tile[1], min(tile[1]+1, self.nodes[i][j][0]+dlon)),
                          max(tile[0], min(tile[0]+1, self.nodes[i][j][1]+dlat)))	# trashes other parameters
        if defer:
            return node
        else:
            return self.layout(tile, options, vertexcache, node)
        
    def updatenode(self, node, lat, lon, tile, options, vertexcache):
        # update node height but defer full layout. Assumes lat,lon is valid
        (i,j)=node
        self.nodes[i][j]=(lon,lat)	# trashes other parameters
        (x,z)=self.position(tile, lat, lon)
        y=vertexcache.height(tile,options,x,z)
        self.points[i][j]=(x,y,z)
        return node

    def picknodes(self):
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

    def draw(self, selected, picking):
        # Don't draw selected so can't be picked
        if not picking: Polygon.draw(self, selected, picking)


class Draped(Polygon):

    def __init__(self, name, param, nodes, lon=None, size=None, hdg=None):
        Polygon.__init__(self, name, param, nodes, lon, size, hdg)
        self.tris=[]	# tesellated tris

    def clone(self):
        return Draped(self.name, self.param, [list(w) for w in self.nodes])
        
    def load(self, lookup, defs, vertexcache, usefallback=False):
        try:
            filename=lookup[self.name]
            if filename in defs:
                self.definition=defs[filename]
            else:
                defs[filename]=self.definition=DrapedDef(filename, vertexcache)
            return True
        except:
            if usefallback:
                if self.name in lookup:
                    filename=lookup[self.name]
                else:
                    filename=lookup[self.name]=self.name
                if filename in defs:
                    self.definition=defs[filename]
                else:
                    defs[filename]=self.definition=DrapedFallback(filename, vertexcache)
            return False

    def locationstr(self, dms, node=None):
        if node:
            return Polygon.locationstr(self, dms, node)
        elif self.param==65535:
            return '%s  (%d nodes)' % (latlondisp(dms, self.lat, self.lon), len(self.nodes[0]))
        else:
            return '%s  Tex hdg: %-3d  (%d nodes)' % (latlondisp(dms, self.lat, self.lon), self.param, len(self.nodes[0]))

    def draw(self, selected, picking):
        drp=self.definition
        if self.nonsimple:
            Polygon.draw(self, selected, picking)
            return
        elif picking:
            Polygon.draw(self, selected, picking)	# for outline
        else:
            glBindTexture(GL_TEXTURE_2D, drp.texture)
        if not (selected or picking):
            glDepthMask(GL_FALSE)	# offset mustn't update depth
            glEnable(GL_POLYGON_OFFSET_FILL)
        glBegin(GL_TRIANGLES)
        if picking:
            for t in self.tris:
                glVertex3f(*t[0])
        else:
            for t in self.tris:
                glTexCoord2f(*t[2])
                glVertex3f(*t[0])
        glEnd()
        if not (selected or picking):
            glDepthMask(GL_TRUE)
            glDisable(GL_POLYGON_OFFSET_FILL)
        
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

    def movenode(self, node, dlat, dlon, tile, options, vertexcache, defer=True):
        # defer layout
        if self.param==65535:
            # Preserve node texture co-ords
            (i,j)=node
            if len(self.nodes[i][j])>=6:
                # Ben says: a bezier polygon has 8 coords (lon lat of point, lon lat of control, ST of point, ST of control)
                uv=self.nodes[i][j][4:6]
            else:
                uv=self.nodes[i][j][2:4]
            self.nodes[i][j]=(max(tile[1], min(tile[1]+1, self.nodes[i][j][0]+dlon)),
                              max(tile[0], min(tile[0]+1, self.nodes[i][j][1]+dlat)))+uv
            if defer:
                return node
            else:
                return self.layout(tile, options, vertexcache, node)
        else:
            return Polygon.movenode(self, node, dlat, dlon, tile, options, vertexcache, defer)

    def updatenode(self, node, lat, lon, tile, options, vertexcache):
        # update node height but defer full layout. Assumes lat,lon is valid
        if self.param==65535:
            # Preserve node texture co-ords
            (i,j)=node
            if len(self.nodes[i][j])>=6:
                # Ben says: a bezier polygon has 8 coords (lon lat of point, lon lat of control, ST of point, ST of control)
                uv=self.nodes[i][j][4:6]
            else:
                uv=self.nodes[i][j][2:4]
            self.nodes[i][j]=(lon,lat)+uv
            (x,z)=self.position(tile, lat, lon)
            y=vertexcache.height(tile,options,x,z)
            self.points[i][j]=(x,y,z)
            return node
        else:
            return Polygon.updatenode(self, node, lat, lon, tile, options, vertexcache)

    def layout(self, tile, options, vertexcache, selectednode=None):
        global tess, csgt
        self.nonsimple=False
        selectednode=Polygon.layout(self, tile, options, vertexcache, selectednode)
        # tessellate. This is just to get UV data and check polygon is simple
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
                            uv=self.nodes[i][j][4:6]
                        else:
                            uv=self.nodes[i][j][2:4]
                    else:
                        uv=((self.points[i][j][0]*ch+self.points[i][j][2]*sh)/drp.hscale,
                            (self.points[i][j][0]*sh-self.points[i][j][2]*ch)/drp.vscale)
                    gluTessVertex(tess, [self.points[i][j][0], 0, self.points[i][j][2]], (self.points[i][j], False, uv))
                gluTessEndContour(tess)
            gluTessEndPolygon(tess)

            if not tris:
                if __debug__: print "Draped layout failed:"
                self.nonsimple=True
                return selectednode

            if not options&Prefs.ELEVATION:
                self.tris=tris
                return selectednode
        except:
            # Combine required -> not simple
            if __debug__: print "Draped layout failed:"
            self.nonsimple=True
            return selectednode

        # tessellate again, this time in CSG mode against terrain
        minx=minz=maxint
        maxx=maxz=-maxint
        self.tris=[]
        gluTessBeginPolygon(csgt, self.tris)
        for i in range(len(self.nodes)):
            n=len(self.nodes[i])
            gluTessBeginContour(csgt)
            for j in range(n-1,-1,-1): # why not n?
                if not i:
                    minx=min(minx, self.points[i][j][0])
                    maxx=max(maxx, self.points[i][j][0])
                    minz=min(minz, self.points[i][j][2])
                    maxz=max(maxz, self.points[i][j][2])
                if self.param==65535:
                    if len(self.nodes[i][j])>=6:
                        uv=self.nodes[i][j][4:6]
                    else:
                        uv=self.nodes[i][j][2:4]
                else:
                    uv=((self.points[i][j][0]*ch+self.points[i][j][2]*sh)/drp.hscale,
                        (self.points[i][j][0]*sh-self.points[i][j][2]*ch)/drp.vscale)
                gluTessVertex(csgt, [self.points[i][j][0], 0, self.points[i][j][2]], (self.points[i][j], False, uv))
            gluTessEndContour(csgt)
        abox=BBox(minx, maxx, minz, maxz)

        for (bbox, meshtris) in vertexcache.getMeshdata(tile,options):
            if not abox.intersects(bbox): continue
            for meshtri in meshtris:
                (meshpt, coeffs)=meshtri
                # tesselator is expensive - minimise mesh triangles
                tbox=BBox()
                for m in range(3):
                    tbox.include(meshpt[m][0], meshpt[m][2])
                if not abox.intersects(tbox):
                    continue
                gluTessBeginContour(csgt)
                for m in range(3):
                    x=meshpt[m][0]
                    z=meshpt[m][2]
                    # check if mesh point is inside a polygon triangle
                    # in which case calculate a uv position
                    # http://astronomy.swin.edu.au/~pbourke/geometry/insidepoly
                    for t in range(0,len(tris),3):
                        inside=False
                        ptj=tris[t+2][0]
                        for i in range(t,t+3):
                            pti=tris[i][0]
                            if z==pti[2]==ptj[2] and x <= max(pti[0],ptj[0]) and x >= min(pti[0],ptj[0]):
                                inside = True	# on the line
                                break
                            elif (((pti[2] <= z and z < ptj[2]) or
                                   (ptj[2] <= z and z < pti[2])) and
                                  (x < (ptj[0]-pti[0]) * (z - pti[2]) / (ptj[2] - pti[2]) + pti[0])):
                                inside = not inside
                            ptj=pti
                        if inside:	# inside polygon triange tris[t:t+3]
                            x0=tris[t][0][0]
                            z0=tris[t][0][2]
                            x1=tris[t+1][0][0]-x0
                            z1=tris[t+1][0][2]-z0
                            x2=tris[t+2][0][0]-x0
                            z2=tris[t+2][0][2]-z0
                            xp=x-x0
                            zp=z-z0
                            a=(xp*z2-x2*zp)/(x1*z2-x2*z1)
                            b=(xp*z1-x1*zp)/(x2*z1-x1*z2)
                            uv=(tris[t][2][0]+a*(tris[t+1][2][0]-tris[t][2][0])+b*(tris[t+2][2][0]-tris[t][2][0]),
                                tris[t][2][1]+a*(tris[t+1][2][1]-tris[t][2][1])+b*(tris[t+2][2][1]-tris[t][2][1]))
                            break
                    else:
                        uv=None
                    gluTessVertex(csgt, [x,0,z], (meshpt[m],True, uv))
                gluTessEndContour(csgt)

        gluTessEndPolygon(csgt)
        return selectednode

    def addnode(self, tile, options, vertexcache, selectednode, clockwise):
        if self.param==65535:
            return False	# we don't support new nodes in orthos
        return Polygon.addnode(self, tile, options, vertexcache, selectednode, clockwise)

    def delnode(self, tile, options, vertexcache, selectednode, clockwise):
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


class Exclude(Polygon):

    NAMES={'sim/exclude_bch': 'Exclude: Beaches',
           'sim/exclude_pol': 'Exclude: Draped polygons',
           'sim/exclude_fac': 'Exclude: Facades',
           'sim/exclude_for': 'Exclude: Forests',
           'sim/exclude_obj': 'Exclude: Objects',
           'sim/exclude_net': 'Exclude: '+NetworkDef.TABNAME,
           'sim/exclude_str': 'Exclude: Strings'}

    def __init__(self, name, param, nodes, lon=None, size=None, hdg=None):
        if lon==None:
            Clutter.__init__(self, name)
            self.nodes=nodes		# [[(lon,lat,...)]]
        else:
            lat=nodes
            Clutter.__init__(self, name, lat, lon)
            self.nodes=[[]]
            size=0.000005*size
            for (lon,lat) in [(self.lon-size,self.lat-size),
                              (self.lon+size,self.lat-size),
                              (self.lon+size,self.lat+size),
                              (self.lon-size,self.lat+size)]:
                self.nodes[0].append((max(floor(self.lon), min(floor(self.lon)+1, round2res(lon))),
                                      (max(floor(self.lat), min(floor(self.lat)+1, round2res(lat))))))
        self.param=param
        self.points=[]		# list of windings in world space (x,y,z)

    def clone(self):
        return Exclude(self.name, self.param, [list(w) for w in self.nodes])

    def load(self, lookup, defs, vertexcache, usefallback=False):
        self.definition=ExcludeDef(self.name, vertexcache)
        return True

    def locationstr(self, dms, node=None):
        # no elevation
        if node:
            (i,j)=node
            return '%s  Node %d' % (latlondisp(dms, self.nodes[i][j][1], self.nodes[i][j][0]), j)
        else:
            return '%s' % (latlondisp(dms, self.lat, self.lon))

    def addnode(self, tile, options, vertexcache, selectednode, clockwise):
        return False

    def delnode(self, tile, options, vertexcache, selectednode, clockwise):
        return False

    def move(self, dlat, dlon, dhdg, dparam, loc, tile, options, vertexcache):
        # no rotation
        Polygon.move(self, dlat, dlon, 0, 0, loc, tile, options, vertexcache)

    def movenode(self, node, dlat, dlon, tile, options, vertexcache, defer=False):
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

    def draw(self, selected, picking):
        Polygon.draw(self, selected, picking, (0.75, 0.25, 0.25))


class Facade(Polygon):

    def __init__(self, name, param, nodes, lon=None, size=None, hdg=None):
        Polygon.__init__(self, name, param, nodes, lon, size, hdg)
        self.quads=[]		# list of points (x,y,z,s,t)
        self.roof=[]		# list of points (x,y,z,s,t)

    def clone(self):
        return Facade(self.name, self.param, [list(w) for w in self.nodes])

    def load(self, lookup, defs, vertexcache, usefallback=False):
        try:
            filename=lookup[self.name]
            if filename in defs:
                self.definition=defs[filename]
            else:
                defs[filename]=self.definition=FacadeDef(filename, vertexcache)
            if not self.param:
                self.param=maxint
                for (a,b) in self.definition.horiz:
                    self.param=min(self.param, int(ceil(self.definition.hscale * (b-a))))
                self.param=max(self.param,1)
            return True
        except:
            if not self.param:
                self.param=1
            if usefallback:
                if self.name in lookup:
                    filename=lookup[self.name]
                else:
                    filename=lookup[self.name]=self.name
                if filename in defs:
                    self.definition=defs[filename]
                else:
                    defs[filename]=self.definition=FacadeFallback(filename, vertexcache)
            return False

    def locationstr(self, dms, node=None):
        if node:
            return Polygon.locationstr(self, dms, node)
        else:
            return '%s  Height: %-3d  (%d nodes)' % (latlondisp(dms, self.lat, self.lon), self.param, len(self.nodes[0]))

    def draw(self, selected, picking):
        fac=self.definition
        if self.nonsimple or (not self.quads and not self.roof):
            Polygon.draw(self, selected, picking)
            return
        elif picking:
            Polygon.draw(self, selected, picking)
        else:
            glBindTexture(GL_TEXTURE_2D, fac.texture)
            if fac.two_sided:
                glDisable(GL_CULL_FACE)
        if self.quads:
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
        if not picking and fac.two_sided:
            glEnable(GL_CULL_FACE)
        
    def move(self, dlat, dlon, dhdg, dparam, loc, tile, options, vertexcache):
        dparam=max(dparam, 1-self.param)	# can't have height 0
        Polygon.move(self, dlat, dlon, dhdg, dparam, loc, tile, options, vertexcache)
        
    def layout(self, tile, options, vertexcache, selectednode=None):
        selectednode=Polygon.layout(self, tile, options, vertexcache, selectednode)
        self.quads=[]
        self.roof=[]
        try:
            self.layoutquads(tile, options, vertexcache)
        except:
            # layout error
            if __debug__:
                print "Facade layout failed:"
                print_exc()
            self.quads=[]
            self.roof=[]
        return selectednode
        
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


    # Helper for layout
    def layoutquads(self, tile, options, vertexcache):
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
        if n<=2 or not fac.ring or not fac.roof: return
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
        return


class Forest(Polygon):

    def __init__(self, name, param, nodes, lon=None, size=None, hdg=None):
        if param==None: param=127
        Polygon.__init__(self, name, param, nodes, lon, size, hdg)

    def clone(self):
        return Forest(self.name, self.param, [list(w) for w in self.nodes])

    def load(self, lookup, defs, vertexcache, usefallback=False):
        try:
            filename=lookup[self.name]
            if filename in defs:
                self.definition=defs[filename]
            else:
                defs[filename]=self.definition=ForestDef(filename, vertexcache)
            return True
        except:
            if usefallback:
                if self.name in lookup:
                    filename=lookup[self.name]
                else:
                    filename=lookup[self.name]=self.name
                if filename in defs:
                    self.definition=defs[filename]
                else:
                    defs[filename]=self.definition=ForestFallback(filename, vertexcache)
            return False

    def locationstr(self, dms, node=None):
        if node:
            return Polygon.locationstr(self, dms, node)
        else:
            return '%s  Density: %-4.1f%%  (%d nodes)' % (latlondisp(dms, self.lat, self.lon), self.param/2.55, len(self.nodes[0]))

    def draw(self, selected, picking):
        Polygon.draw(self, selected, picking, (0.25,0.75,0.25))

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


class Line(Polygon):

    def __init__(self, name, param, nodes, lon=None, size=None, hdg=None):
        Polygon.__init__(self, name, param, nodes, lon, size, hdg)
        self.lines=[]	# tesellated lines

    def clone(self):
        return Line(self.name, self.param, [list(w) for w in self.nodes])

    def load(self, lookup, defs, vertexcache, usefallback=False):
        try:
            filename=lookup[self.name]
            if filename in defs:
                self.definition=defs[filename]
            else:
                defs[filename]=self.definition=LineDef(filename, vertexcache)
            return True
        except:
            if usefallback:
                if self.name in lookup:
                    filename=lookup[self.name]
                else:
                    filename=lookup[self.name]=self.name
                if filename in defs:
                    self.definition=defs[filename]
                else:
                    defs[filename]=self.definition=LineFallback(filename, vertexcache)
            return False

    def locationstr(self, dms, node=None):
        if node:
            return Polygon.locationstr(self, dms, node)
        else:
            if self.param:
                oc='Closed'
            else:
                oc='Open'
            return '%s  %s  (%d nodes)' % (latlondisp(dms, self.lat, self.lon), oc, len(self.nodes[0]))

    def draw(self, selected, picking):
        drp=self.definition
        if self.nonsimple:
            Polygon.draw(self, selected, picking)
            return
        elif picking:
            Polygon.draw(self, selected, picking)	# for outline
        else:
            glBindTexture(GL_TEXTURE_2D, drp.texture)
        if not (selected or picking):
            glDepthMask(GL_FALSE)	# offset mustn't update depth
            glEnable(GL_POLYGON_OFFSET_FILL)
        glBegin(GL_TRIANGLES)
        if picking:
            for t in self.tris:
                glVertex3f(*t[0])
        else:
            for t in self.tris:
                glTexCoord2f(*t[2])
                glVertex3f(*t[0])
        glEnd()
        if not (selected or picking):
            glDepthMask(GL_TRUE)
            glDisable(GL_POLYGON_OFFSET_FILL)
        
    def move(self, dlat, dlon, dhdg, dparam, loc, tile, options, vertexcache):
        dparam=min(dparam, 1-self.param)	# max 1
        if dhdg:
            self.nodes[0].reverse()		# flip direction ccw?
        if dlat or dlon or dparam:
            Polygon.move(self, dlat, dlon, 0, dparam, loc, tile, options, vertexcache)
        elif dhdg:
            self.layout(tile, options, vertexcache)


class Network(Polygon):

    def __init__(self, name, index, nodes, lon=None, size=None, hdg=None):
        self.index=index
        if lon==None:
            Clutter.__init__(self, name)
            self.nodes=nodes	# [[(lon,lat,elv,iscontrolnode)]] - this is what gets saved to file
            self.points=[]	# in x,y,z space at ground level. Difference between y and elv is the height AGL
        else:
            lat=nodes
            Clutter.__init__(self, name, lat, lon)
            h=radians(hdg)
            self.nodes=[[]]
            size=0.000007071*size
            for i in [h+5*pi/4, h+3*pi/4, h+pi/4, h+7*pi/4]:
                self.nodes[0].append((max(floor(lon), min(floor(lon)+1, round2res(self.lon+sin(i)*size))),
                                      (max(floor(lat), min(floor(lat)+1, round2res(self.lat+cos(i)*size))))))
        self.laidoutwithelevation=False
            
    def __str__(self):
        return '<"%s" %d %s>' % (self.name,self.index,self.nodes)

    def clone(self):
        return Network(self.name, self.index, [list(w) for w in self.nodes])

    def load(self, lookup, defs, vertexcache, usefallback=False):
        # XXX disable networks
        self.definition=NetworkFallback(None, None, self.index)
        return True

    	print "load", self.definition.name, len(self.nodes[0])
        try:
            if not self.name: raise IOError	# not in roads.net
            self.definition=defs[self.name]
            self.definition.allocate(vertexcache, defs)	# ensure allocated
            notfallback=True
        except:
            if usefallback:
                self.definition=NetworkFallback(None, None, self.index)
                self.definition.allocate(vertexcache, defs)	# ensure allocated
            notfallback=False

        if self.definition.height==None:
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
        else:
            # all nodes are control nodes
            self.nodes[0]=[i[:3]+[True] for i in self.nodes[0]]
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

    def draw(self, selected, picking):
        return	# XXX disable networks
        # just draw outline
        if picking:
            # Can't pick if no elevation
            if not self.laidoutwithelevation: return
        else:
            glBindTexture(GL_TEXTURE_2D, 0)
            if not selected: glColor3f(*self.definition.color)
        glDisable(GL_DEPTH_TEST)
        glBegin(GL_LINE_STRIP)
        for p in self.points[0]:
            glVertex3f(p[0],p[1],p[2])
        glEnd()
        glEnable(GL_DEPTH_TEST)
        if not (selected or picking):
            glColor3f(0.8, 0.8, 0.8)	# restore

    def drawnodes(self, selectednode):
        glBindTexture(GL_TEXTURE_2D, 0)
        glDisable(GL_DEPTH_TEST)
        glBegin(GL_POINTS)
        for j in range(len(self.points[0])):
            if self.nodes[0][j][3]:	# iscontrolnode
                if selectednode==(0,j):
                    glColor3f(1.0, 1.0, 1.0)
                else:
                    glColor3f(1.0, 0.5, 1.0)
                glVertex3f(*self.points[0][j])
        glEnd()
        glEnable(GL_DEPTH_TEST)        

    def clearlayout(self):
        self.laidoutwithelevation=False
        self.points=[]

    def islaidout(self):
        return self.points and True

    def layout(self, tile, options, vertexcache, selectednode=None):

        return selectednode	# XXX disable networks

        self.laidoutwithelevation=options&Prefs.ELEVATION
        controlnodes=[i for i in self.nodes[0] if i[3]]

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

def tesscombine(coords, vertex, weight):
    # Linearly interp height & uv from vertices (location, ismesh, uv)
    # Will only be called if polygon is not simple (and therefore illegal)
    p1=vertex[0]
    p2=vertex[1]
    d=hypot(p2[0][0]-p1[0][0], p2[0][2]-p1[0][2])
    if not d:
        return p1	# p1 and p2 are colocated
    else:
        ratio=hypot(coords[0]-p1[0][0], coords[2]-p1[0][2])/d
        y=p1[0][1]+ratio*(p2[0][1]-p1[0][1])
        if p1[2]:
            return ([coords[0],y,coords[2]], False, (p1[2][0]+ratio*(p2[2][0]-p1[2][0]), (p1[2][1]+ratio*(p2[2][1]-p1[2][1]))))
        else:
            return ([coords[0],y,coords[2]], False, None)	# forest
    
def tessedge(flag):
    pass	# dummy

tess=gluNewTess()
gluTessNormal(tess, 0, -1, 0)
gluTessProperty(tess, GLU_TESS_WINDING_RULE, GLU_TESS_WINDING_NONZERO)
gluTessCallback(tess, GLU_TESS_VERTEX_DATA,  tessvertex)
gluTessCallback(tess, GLU_TESS_EDGE_FLAG,    tessedge)	# no strips


def csgtvertex(vertex, data):
    #assert(vertex[2])
    data.append(vertex)

def csgtcombine(coords, vertex, weight):
    # interp height & UV at coords from vertices (location, ismesh, uv)

    #print vertex[0], weight[0]
    #print vertex[1], weight[1]
    #print vertex[2], weight[2]
    #print vertex[3], weight[3]

    # check for just two adjacent mesh triangles
    if vertex[0]==vertex[1]:
        # common case, or non-simple
        #assert not weight[2] and not vertex[2] and not weight[3] and not vertex[3] and vertex[1][1]
        #print vertex[0], " ->"
        return vertex[0]
    elif vertex[0][0][0]==vertex[1][0][0] and vertex[0][0][2]==vertex[1][0][2] and vertex[0][1]:
        # Height discontinuity in terrain mesh - eg LIEE - wtf!
        #assert not weight[2] and not vertex[2] and not weight[3] and not vertex[3] and vertex[1][1]
        #print vertex[0], " ->"
        return vertex[0]

    # intersection of two lines - use terrain mesh line for height
    elif vertex[0][1]:
        #assert weight[0] and weight[1] and weight[2] and weight[3] and vertex[1][1]
        p1=vertex[0]
        p2=vertex[1]
        p3=vertex[2]
        p4=vertex[3]
    else:
        #assert weight[0] and weight[1] and weight[2] and weight[3]
        p1=vertex[2]
        p2=vertex[3]
        p3=vertex[0]
        p4=vertex[1]

    # height
    d=hypot(p2[0][0]-p1[0][0], p2[0][2]-p1[0][2])
    if not d:
        y=p1[0][1]
    else:
        ratio=(hypot(coords[0]-p1[0][0], coords[2]-p1[0][2])/d)
        y=p1[0][1]+ratio*(p2[0][1]-p1[0][1])

    # UV
    if not p3[2]:
        uv=None
    else:
        d=hypot(p4[0][0]-p3[0][0], p4[0][2]-p3[0][2])
        if not d:
            uv=p3[2]
        else:
            ratio=(hypot(coords[0]-p3[0][0], coords[2]-p3[0][2])/d)
            uv=(p3[2][0]+ratio*(p4[2][0]-p3[2][0]),
                p3[2][1]+ratio*(p4[2][1]-p3[2][1]))

    #print ([coords[0],y,coords[2]], True, uv), " ->"
    #assert(uv)	# only if draped
    return ([coords[0],y,coords[2]], True, uv)

def csgtedge(flag):
    pass	# dummy

csgt=gluNewTess()
gluTessNormal(csgt, 0, -1, 0)
gluTessProperty(csgt, GLU_TESS_WINDING_RULE, GLU_TESS_WINDING_ABS_GEQ_TWO)
gluTessCallback(csgt, GLU_TESS_VERTEX_DATA,  csgtvertex)
gluTessCallback(csgt, GLU_TESS_COMBINE,      csgtcombine)
gluTessCallback(csgt, GLU_TESS_EDGE_FLAG,    csgtedge)	# no strips


def csglvertex(vertex, data):
    data.append(vertex)

def csglcombine(coords, vertex, weight):
    # interp height & UV at coords from vertices (location, ismesh, uv)
    
    # check for just two adjacent mesh triangles
    if vertex[0]==vertex[1]:
        # common case, or non-simple
        #assert not weight[2] and not vertex[2] and not weight[3] and not vertex[3] and vertex[1][1]
        return vertex[0]
    elif vertex[0][0][0]==vertex[1][0][0] and vertex[0][0][2]==vertex[1][0][2] and vertex[0][1]:
        # Height discontinuity in terrain mesh - eg LIEE - wtf!
        assert not weight[2] and not vertex[2] and not weight[3] and not vertex[3] and vertex[1][1]
        return vertex[0]

    # intersection of two lines - use terrain mesh line for height
    elif vertex[0][1]:
        #assert weight[0] and weight[1] and weight[2] and weight[3] and vertex[1][1]
        p1=vertex[0]
        p2=vertex[1]
        p3=vertex[2]
        p4=vertex[3]
    else:
        assert weight[0] and weight[1] and weight[2] and weight[3]
        p1=vertex[2]
        p2=vertex[3]
        p3=vertex[0]
        p4=vertex[1]

    # height
    d=hypot(p2[0][0]-p1[0][0], p2[0][2]-p1[0][2])
    if not d:
        y=p1[0][1]
    else:
        ratio=(hypot(coords[0]-p1[0][0], coords[2]-p1[0][2])/d)
        y=p1[0][1]+ratio*(p2[0][1]-p1[0][1])

    # UV
    if not p3[2]:
        uv=None
    else:
        d=hypot(p4[0][0]-p3[0][0], p4[0][2]-p3[0][2])
        if not d:
            uv=p3[2]
        else:
            ratio=(hypot(coords[0]-p3[0][0], coords[2]-p3[0][2])/d)
            uv=(p3[2][0]+ratio*(p4[2][0]-p3[2][0]),
                p3[2][1]+ratio*(p4[2][1]-p3[2][1]))
    
    return ([coords[0],y,coords[2]], True, uv)

csgl=gluNewTess()
gluTessNormal(csgl, 0, -1, 0)
gluTessProperty(csgl, GLU_TESS_WINDING_RULE, GLU_TESS_WINDING_ABS_GEQ_TWO)
gluTessProperty(csgl, GLU_TESS_BOUNDARY_ONLY,GL_TRUE)
gluTessCallback(csgl, GLU_TESS_VERTEX_DATA,  csglvertex)
gluTessCallback(csgl, GLU_TESS_COMBINE,      csglcombine)

