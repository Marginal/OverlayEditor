from OpenGL.GL import *
from OpenGL.GLU import *
try:
    # apparently older PyOpenGL version didn't define gluTessVertex
    gluTessVertex
except NameError:
    from OpenGL import GLU
    gluTessVertex = GLU._gluTessVertex

from math import acos, atan2, cos, sin, floor, hypot, pi
from os.path import join
from struct import unpack
from sys import exit, platform, maxint, version
import wx.glcanvas

from files import VertexCache, sortfolded, Prefs, ExcludeDef, FacadeDef, ForestDef
from DSFLib import Object, Polygon, resolution, maxres, round2res
from MessageBox import myMessageBox
from version import appname, dofacades

onedeg=1852*60	# 1 degree of longitude at equator (60nm) [m]
d2r=pi/180.0
twopi=pi+pi
f2m=0.3041	# 1 foot [m] (not accurate, but what X-Plane appears to use)

sband=12	# width of mouse scroll band around edge of window

# Handle int/long change between 2.3 & 2.4
if version>'2.4':
    MSKSEL =0x40000000
    MSKNODE=0x20000000
    MSKPOLY=0x0fffffff
else:
    MSKSEL =0x40000000L
    MSKNODE=0x20000000L
    MSKPOLY=0x0fffffffL


class UndoEntry:
    ADD=0
    DEL=1
    MOVE=2
    def __init__(self, tile, kind, data):
        self.tile=tile
        self.kind=kind
        self.data=data


# OpenGL Window
class MyGL(wx.glcanvas.GLCanvas):
    def __init__(self, parent, frame):

        self.parent=parent
        self.frame=frame
        self.movecursor=wx.StockCursor(wx.CURSOR_HAND)
        self.dragcursor=wx.StockCursor(wx.CURSOR_CROSS)

        self.valid=False	# do we have valid data for a redraw?
        self.options=0		# display options
        self.tile=[0,999]	# [lat,lon] of SW
        self.centre=None	# [lat,lon] of centre
        self.airports={}	# (lat,lon,hdg,length,width) by code
        self.runways={}		# diplay list by tile
        self.navaids=[]		# (type, lat, lon, hdg)
        self.objects={}		# [(name,lat,lon,hdg,height)] by tile
        self.polygons={}	# [(name, parameter, [windings])] by tile
        self.objectslist=0
        self.background=None
        self.meshlist=0
        
        self.selected=[]	# Indices into self.objects[self.tile]
        self.selections=[]	# List for picking
        self.selectlist=0
        self.selectctrl=False	# Ctrl/Cmd was held down
        self.selectanchor=None	# Drag mode: Start of drag
        self.selectsaved=None	# Selection at start of drag
        self.selectnode=False	# Polygon selection mode
        self.selectednode=None	# Selected node
        self.selectmove=None	# Move mode
        self.mousenow=None	# Current position

        self.undostack=[]

        # Values during startup
        self.x=0
        self.y=0
        self.z=0
        self.h=0
        self.e=90
        self.d=3333.25
        self.cliprat=1000

        # Must specify min sizes for glX? - see glXChooseVisual and GLXFBConfig
        wx.glcanvas.GLCanvas.__init__(self, parent,
                                      style=GL_RGBA|GL_DOUBLEBUFFER|GL_DEPTH|wx.FULL_REPAINT_ON_RESIZE,
                                      attribList=[
            wx.glcanvas.WX_GL_RGBA,
            wx.glcanvas.WX_GL_DOUBLEBUFFER,
            #wx.glcanvas.WX_GL_MIN_RED, 4,
            #wx.glcanvas.WX_GL_MIN_GREEN, 4,
            #wx.glcanvas.WX_GL_MIN_BLUE, 4,
            #wx.glcanvas.WX_GL_MIN_ALPHA, 4,
            wx.glcanvas.WX_GL_DEPTH_SIZE, 24])	# ATI on Mac defaults to 16
        if self.GetId()==-1:
            # Failed - try with smaller depth buffer
            wx.glcanvas.GLCanvas.__init__(self, parent,
                                          style=GL_RGBA|GL_DOUBLEBUFFER|GL_DEPTH|wx.FULL_REPAINT_ON_RESIZE,
                                          attribList=[wx.glcanvas.WX_GL_RGBA,wx.glcanvas.WX_GL_DOUBLEBUFFER])
            self.cliprat=100
        if self.GetId()==-1:
            myMessageBox('Try updating the drivers for your graphics card.',
                         "Can't initialise OpenGL.",
                         wx.ICON_ERROR|wx.OK, self)
            exit(1)

        self.vertexcache=VertexCache()	# member so can free resources

        wx.EVT_PAINT(self, self.OnPaint)
        wx.EVT_ERASE_BACKGROUND(self, self.OnEraseBackground)
        wx.EVT_KEY_DOWN(self, self.OnKeyDown)
        wx.EVT_MOUSEWHEEL(self, self.OnMouseWheel)
        wx.EVT_MOTION(self, self.OnMouseMotion)
        wx.EVT_LEFT_DOWN(self, self.OnLeftDown)
        wx.EVT_LEFT_UP(self, self.OnLeftUp)
        wx.EVT_IDLE(self, self.OnIdle)
        #wx.EVT_KILL_FOCUS(self, self.OnKill)	# debug
        
        self.timer=wx.Timer(self, wx.ID_ANY)
        wx.EVT_TIMER(self, self.timer.GetId(), self.OnTimer)

    def glInit(self):
        # Setup state. Under X must be called after window is shown
        self.SetCurrent()
        glClearColor(0.5, 0.5, 1.0, 0.0)	# Sky
        #glClearDepth(1.0)
        glDepthFunc(GL_LESS)
        glEnable(GL_DEPTH_TEST)
        glShadeModel(GL_FLAT)
        #glLineStipple(1, 0x0f0f)	# for selection drag
        glPointSize(3.0)		# for nodes
        glFrontFace(GL_CW)
        glCullFace(GL_BACK)
        glPixelStorei(GL_UNPACK_ALIGNMENT,1)
        glReadBuffer(GL_BACK)	# for unproject
        #glPixelStorei(GL_UNPACK_LSB_FIRST,1)
        glEnable(GL_TEXTURE_2D)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
        glEnable(GL_BLEND)
        glEnableClientState(GL_VERTEX_ARRAY)
        glEnableClientState(GL_TEXTURE_COORD_ARRAY)


    def OnEraseBackground(self, event):
        pass	# Prevent flicker when resizing / painting on MSW

    def OnKeyDown(self, event):
        # Manually propagate
        self.frame.OnKeyDown(event)

    def OnMouseWheel(self, event):
        # Manually propagate
        self.frame.OnMouseWheel(event)

    def OnTimer(self, event):
        # mouse scroll - fake up a key event and pass it up
        size=self.GetClientSize()
        posx=self.mousenow[0]
        posy=self.mousenow[1]
        keyevent=wx.KeyEvent()
        keyevent.m_controlDown=keyevent.m_metaDown=self.selectctrl
        if posx<sband:
            keyevent.m_keyCode=wx.WXK_LEFT
        elif posy<sband:
            keyevent.m_keyCode=wx.WXK_UP
        elif size.x-posx<sband:
            keyevent.m_keyCode=wx.WXK_RIGHT
        elif size.y-posy<sband:
            keyevent.m_keyCode=wx.WXK_DOWN
        if keyevent.m_keyCode:
            self.frame.OnKeyDown(keyevent)
        
    def OnLeftDown(self, event):
        #event.Skip(False)	# don't change focus
        self.mousenow=[event.m_x,event.m_y]
        self.selectctrl=event.m_controlDown or event.m_metaDown
        self.CaptureMouse()
        size = self.GetClientSize()
        if event.m_x<sband or event.m_y<sband or size.x-event.m_x<sband or size.y-event.m_y<sband:
            # mouse scroll
            self.timer.Start(50)
        else:
            self.select()

    def OnLeftUp(self, event):
        if self.HasCapture(): self.ReleaseMouse()
        if self.selectnode:
            self.updatepoly(self.currentpolygons()[self.selected[0]&MSKPOLY])
        self.trashlists(True)	# recompute obj and select lists
        self.selectanchor=None
        self.selectnode=None
        self.selectmove=None
        self.timer.Stop()
        self.SetCursor(wx.NullCursor)
        self.Refresh()	# get rid of drag box
        event.Skip()
            
    def OnIdle(self, event):
        if self.selectnode:
            self.updatepoly(self.currentpolygons()[self.selected[0]&MSKPOLY])
            self.Refresh()
        event.Skip()

    def OnMouseMotion(self, event):
        if (self.timer.IsRunning() or self.selectanchor or self.selectnode or self.selectmove) and not event.LeftIsDown():
            # Capture unreliable on Mac, so may have missed LeftUp event. See
            # https://sourceforge.net/tracker/?func=detail&atid=109863&aid=1489131&group_id=9863
            self.OnLeftUp(event)
            return

        if self.timer.IsRunning():
            # Continue mouse scroll
            self.mousenow=[event.m_x,event.m_y]		# not known in timer
            return

        if event.LeftIsDown() and self.mousenow and (abs(event.m_x-self.mousenow[0])>1 or abs(event.m_y-self.mousenow[1])>1):
            # Drag/node/move
            if self.selectednode!=None:
                # Start/continue node drag
                self.SetCursor(self.dragcursor)
                self.selectnode=True
                poly=self.currentpolygons()[self.selected[0]&MSKPOLY]
                (lat,lon)=self.getworldloc(event.m_x, event.m_y)
                lat=max(self.tile[0], min(self.tile[0]+maxres, lat))
                lon=max(self.tile[1], min(self.tile[1]+maxres, lon))
                if not (self.undostack and self.undostack[-1].kind==UndoEntry.MOVE and self.undostack[-1].tile==self.tile and len(self.undostack[-1].data)==1 and self.undostack[-1].data[0][0]==self.selected[0]):
                    self.undostack.append(UndoEntry(self.tile, UndoEntry.MOVE, [(self.selected[0], poly.clone())]))
                    self.frame.toolbar.EnableTool(wx.ID_SAVE, True)
                    self.frame.toolbar.EnableTool(wx.ID_UNDO, True)
                poly.nodes=[poly.nodes[0]]	# Destroy other windings
                poly.nodes[0][self.selectednode]=(lon,lat)
                if poly.kind==Polygon.EXCLUDE:
                    if self.selectednode&1:
                        poly.nodes[0][(self.selectednode-1)%4]=(poly.nodes[0][(self.selectednode-1)%4][0], lat)
                        poly.nodes[0][(self.selectednode+1)%4]=(lon, poly.nodes[0][(self.selectednode+1)%4][1])
                    else:
                        poly.nodes[0][(self.selectednode+1)%4]=(poly.nodes[0][(self.selectednode+1)%4][0], lat)
                        poly.nodes[0][(self.selectednode-1)%4]=(lon, poly.nodes[0][(self.selectednode-1)%4][1])
                    self.updatepoly(poly)
                else:	# just do this point - postpone update to Idle/Leftup
                    (x,z)=self.latlon2m(poly.nodes[0][self.selectednode][1],
                                        poly.nodes[0][self.selectednode][0])
                    y=self.vertexcache.height(self.tile,self.options,x,z)
                    poly.points[self.selectednode]=(x,y,z)
                    
                self.Refresh()	# show updated node
                self.frame.ShowSel()
                    
            elif not self.selectanchor and not self.selectmove and self.selected and not self.selectctrl:
                # Start move drag
                self.selectmove=self.getworldloc(self.mousenow[0],self.mousenow[1])		# location of LeftDown

            elif not self.selectanchor and not self.selectmove:
                # Start selection drag
                self.selectanchor=self.mousenow		# location of LeftDown
                self.selectsaved=self.selected
                self.trashlists(True)	# Recompute everything
            
        if self.selectmove:
            # Continue move drag
            (lat,lon)=self.getworldloc(event.m_x, event.m_y)
            if (lat>self.tile[0] and lat<self.tile[0]+maxres and
                lon>self.tile[1] and lon<self.tile[1]+maxres):
                self.movesel(lat-self.selectmove[0], lon-self.selectmove[1], 0)
                self.frame.toolbar.EnableTool(wx.ID_SAVE, True)
                self.frame.toolbar.EnableTool(wx.ID_UNDO, True)
                self.selectmove=(lat,lon)
            
        elif self.selectanchor:
            # Continue selection drag
            self.mousenow=[event.m_x,event.m_y]		# not known in paint
            self.selected=list(self.selectsaved)	# reset each time
            self.select()
            
        else:
            size = self.GetClientSize()
            if event.m_x<sband or event.m_y<sband or size.x-event.m_x<sband or size.y-event.m_y<sband:
                self.SetCursor(self.movecursor)
            else:
                self.SetCursor(wx.NullCursor)

    def OnPaint(self, event):
        #print "paint", self.selected
        dc = wx.PaintDC(self)	# Tell the window system that we're on the case
        self.SetCurrent()
        self.SetFocus()		# required for GTK
        #glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT)

        glMatrixMode(GL_PROJECTION)
        size = self.GetClientSize()
        glViewport(0, 0, size.width, size.height)
        glLoadIdentity()
	# try to minimise near offset to improve clipping
        if size.x:	# may be 0 on startup
            glOrtho(-self.d, self.d,
                    -self.d*size.y/size.x, self.d*size.y/size.x,
                    -self.d*self.cliprat, self.d*self.cliprat)
        
        glMatrixMode(GL_MODELVIEW)
        glLoadIdentity()
        glRotatef(self.e, 1.0,0.0,0.0)
        glRotatef(self.h, 0.0,1.0,0.0)
        glTranslatef(-self.x, -self.y, -self.z)

        glEnable(GL_TEXTURE_2D)
        glEnable(GL_CULL_FACE)
        glDisable(GL_DEPTH_TEST)

        if not self.valid:
            # Sea
            glColor3f(0.25, 0.25, 0.50)
            glBindTexture(GL_TEXTURE_2D, 0)
            glBegin(GL_QUADS)
            glVertex3f( onedeg*cos(d2r*(1+self.tile[0]))/2, 0, -onedeg/2)
            glVertex3f( onedeg*cos(d2r*self.tile[0])/2, 0,  onedeg/2)
            glVertex3f(-onedeg*cos(d2r*self.tile[0])/2, 0,  onedeg/2)
            glVertex3f(-onedeg*cos(d2r*(1+self.tile[0]))/2, 0, -onedeg/2)
            glEnd()
            self.SwapBuffers()
            glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT)
            return

        self.vertexcache.realize()
        objects=self.currentobjects()
        polygons=self.currentpolygons()

        # Ground
        if not self.meshlist:
            self.meshlist=glGenLists(1)
            glNewList(self.meshlist, GL_COMPILE)
            glEnable(GL_DEPTH_TEST)
            glPushMatrix()
            if not self.options&Prefs.ELEVATION:
                glScalef(1,0,1)		# Defeat elevation data
            glColor3f(0.75, 0.75, 0.75)	# Unpainted
            for (base,culled,texno) in self.vertexcache.getMesh(self.tile,self.options):
                glBindTexture(GL_TEXTURE_2D, texno)
                glDrawArrays(GL_TRIANGLES, base, culled)
            glPopMatrix()
            glEndList()
        glCallList(self.meshlist)

        # Runways
        key=(self.tile[0],self.tile[1],self.options&Prefs.ELEVATION)
        if key in self.runways: glCallList(self.runways[key])

        # Objects and Polygons
        if not self.objectslist:
            self.objectslist=glGenLists(1)
            glNewList(self.objectslist, GL_COMPILE)

            glEnable(GL_CULL_FACE)
            cullstate=True
            glEnable(GL_TEXTURE_2D)
            glDisable(GL_POLYGON_OFFSET_FILL)
            for i in range(len(polygons)):
                if (i|MSKSEL) in self.selected and not self.selectanchor:
                    continue	# don't have to recompute on move
                poly=polygons[i]
                if poly.kind==Polygon.FACADE and dofacades:
                    fac=self.vertexcache.get(poly.name)
                    glBindTexture(GL_TEXTURE_2D, fac.texture)
                    glColor3f(0.75, 0.75, 0.75)	# Unpainted
                    glEnable(GL_DEPTH_TEST)
                    if fac.two_sided:
                        if cullstate: glDisable(GL_CULL_FACE)
                        cullstate=False
                    else:
                        if not cullstate: glEnable(GL_CULL_FACE)
                        cullstate=True
                    glBegin(GL_QUADS)
                    for p in poly.quads:
                        glTexCoord2f(p[3],p[4])
                        glVertex3f(p[0],p[1],p[2])
                    glEnd()
                    if poly.roof:
                        glBegin(GL_TRIANGLE_FAN)	# Better for concave
                        for p in poly.roof+[poly.roof[1]]:
                            glTexCoord2f(p[3],p[4])
                            glVertex3f(p[0],p[1],p[2])
                        glEnd()
                else:
                    if poly.kind==Polygon.EXCLUDE:
                        glColor3f(0.5, 0.125, 0.125)
                    elif poly.kind==Polygon.FOREST:
                        glColor3f(0.125, 0.4, 0.125)
                    else:
                        glColor3f(0.25, 0.25, 0.25)	# Unknown
                    glBindTexture(GL_TEXTURE_2D, 0)
                    glDisable(GL_DEPTH_TEST)
                    glBegin(GL_LINE_LOOP)
                    for p in poly.points:
                        glVertex3f(p[0],p[1],p[2])
                    glEnd()
            glColor3f(0.75, 0.75, 0.75)	# Unpainted
            glEnable(GL_DEPTH_TEST)
            polystate=0
            for i in range(len(objects)):
                if i in self.selected and not self.selectanchor:
                    continue	# don't have to recompute on move
                obj=objects[i]
                (x,z)=self.latlon2m(obj.lat, obj.lon)
                (base,culled,nocull,texno,poly)=self.vertexcache.get(obj.name)
                if poly:
                    if polystate!=poly:
                        glPolygonOffset(-1*poly, -1*poly)
                        glEnable(GL_POLYGON_OFFSET_FILL)
                    polystate=poly
                else:
                    if polystate: glDisable(GL_POLYGON_OFFSET_FILL)
                    polystate=0
                glPushMatrix()
                glTranslatef(x, obj.height, z)
                glRotatef(-obj.hdg, 0.0,1.0,0.0)
                glBindTexture(GL_TEXTURE_2D, texno)
                if culled:
                    if not cullstate: glEnable(GL_CULL_FACE)
                    cullstate=True
                    glDrawArrays(GL_TRIANGLES, base, culled)
                if nocull:
                    if cullstate: glDisable(GL_CULL_FACE)
                    cullstate=False
                    glDrawArrays(GL_TRIANGLES, base+culled, nocull)
                glPopMatrix()
            glEndList()
        glCallList(self.objectslist)

        # Overlays
        glDisable(GL_POLYGON_OFFSET_FILL)
        glDisable(GL_DEPTH_TEST)

        # Background
        if self.background:
            (image, lat, lon, hdg, width, length, opacity, height)=self.background
            if [int(floor(lat)),int(floor(lon))]==self.tile:
                texno=self.vertexcache.texcache.get(image, False, True)
                (x,z)=self.latlon2m(lat, lon)
                glPushMatrix()
                glTranslatef(x, height, z)
                glRotatef(-hdg, 0.0,1.0,0.0)
                glColor4f(1.0, 1.0, 1.0, opacity/100.0)
                glBindTexture(GL_TEXTURE_2D, texno)
                glBegin(GL_QUADS)
                glTexCoord2f(0,0)
                glVertex3f(-width/2, 0, length/2)
                glTexCoord2f(0,1)
                glVertex3f(-width/2, 0,-length/2)
                glTexCoord2f(1,1)
                glVertex3f( width/2, 0,-length/2)
                glTexCoord2f(1,0)
                glVertex3f( width/2, 0, length/2)
                glEnd()
                if self.frame.bkgd:
                    # Setting background image
                    glColor3f(1.0, 0.5, 1.0)
                    glBindTexture(GL_TEXTURE_2D, 0)
                    glBegin(GL_LINE_LOOP)
                    glVertex3f(-width/2, 0, length/2)
                    glVertex3f(-width/2, 0,-length/2)
                    glVertex3f( width/2, 0,-length/2)
                    glVertex3f( width/2, 0, length/2)
                    glEnd()
                glPopMatrix()

        # Position centre
        glColor3f(1.0, 0.25, 0.25)	# Cursor
        glLoadIdentity()
        glRotatef(self.e, 1.0,0.0,0.0)
        glRotatef(self.h, 0.0,1.0,0.0)
        glBindTexture(GL_TEXTURE_2D, 0)
        glBegin(GL_LINES)
        glVertex3f(-0.5,0,0)
        glVertex3f( 0.5,0,0)
        glVertex3f(0,0,-0.5)
        glVertex3f(0,0, 0.5)
        glVertex3f(0,0,-0.5)
        glVertex3f(0.125,0,-0.375)
        glVertex3f(0,0,-0.5)
        glVertex3f(-0.125,0,-0.375)
        glEnd()
        glTranslatef(-self.x, -self.y, -self.z)	# set up for picking

        # Selections
        if self.frame.bkgd:
            # Don't show if setting background image
            glColor3f(0.75, 0.75, 0.75)	# Unpainted
        else:
            glColor3f(1.0, 0.5, 1.0)

        #glPolygonMode(GL_FRONT_AND_BACK, GL_LINE)	# XXX
        glDisable(GL_CULL_FACE)
        glEnable(GL_DEPTH_TEST)
        glPolygonOffset(-3, -3)
        glEnable(GL_POLYGON_OFFSET_FILL)
        for i in self.selected:
            if i&MSKSEL:
                poly=polygons[i&MSKPOLY]
                if poly.kind==Polygon.FACADE:
                    if not dofacades: continue
                    fac=self.vertexcache.get(poly.name)
                    glBindTexture(GL_TEXTURE_2D, fac.texture)
                    glBegin(GL_QUADS)
                    for p in poly.quads:
                        glTexCoord2f(p[3],p[4])
                        glVertex3f(p[0],p[1],p[2])
                    glEnd()
                    if poly.roof:
                        glBegin(GL_TRIANGLE_FAN)	# Better for concave
                        for p in poly.roof+[poly.roof[1]]:
                            glTexCoord2f(p[3],p[4])
                            glVertex3f(p[0],p[1],p[2])
                        glEnd()
                else:
                    glBindTexture(GL_TEXTURE_2D, 0)
                    glDisable(GL_DEPTH_TEST)
                    glBegin(GL_LINE_LOOP)
                    for p in poly.points:
                        glVertex3f(p[0],p[1],p[2])
                    glEnd()
                    glEnable(GL_DEPTH_TEST)
            else:
                # assumes cache is already properly set up
                obj=objects[i]
                (x,z)=self.latlon2m(obj.lat, obj.lon)
                (base,culled,nocull,texno,poly)=self.vertexcache.get(obj.name)
                glPushMatrix()
                glTranslatef(x, obj.height, z)
                glRotatef(-obj.hdg, 0.0,1.0,0.0)
                glBindTexture(GL_TEXTURE_2D, texno)
                glDrawArrays(GL_TRIANGLES, base, culled+nocull)
                glBindTexture(GL_TEXTURE_2D, 0)
                glBegin(GL_LINES)
                glVertex3f(-0.5,0,0)
                glVertex3f( 0.5,0,0)
                glVertex3f(0,0,-0.5)
                glVertex3f(0,0, 0.5)
                glVertex3f(0,0,-0.5)
                glVertex3f(0.125,0,-0.375)
                glVertex3f(0,0,-0.5)
                glVertex3f(-0.125,0,-0.375)
                glEnd()
                glPopMatrix()
        if len(self.selected)==1 and self.selected[0]&MSKSEL:
            poly=polygons[self.selected[0]&MSKPOLY]
            glDisable(GL_DEPTH_TEST)
            glBindTexture(GL_TEXTURE_2D, 0)
            glBegin(GL_LINE_LOOP)
            for p in poly.points:
                glVertex3f(p[0],p[1],p[2])
            glEnd()
            glBegin(GL_POINTS)
            for i in range(len(poly.points)):
                if self.selectednode!=None and i==self.selectednode:
                    glColor3f(1.0, 1.0, 1.0)
                else:
                    glColor3f(1.0, 0.5, 1.0)
                glVertex3f(poly.points[i][0], poly.points[i][1], poly.points[i][2])
            glEnd()
        glDisable(GL_POLYGON_OFFSET_FILL)
        #glPolygonMode(GL_FRONT_AND_BACK, GL_FILL)	# XXX

	# drag box
        if self.selectanchor:
            #print "drag"
            glColor3f(0.25, 0.125, 0.25)
            glDisable(GL_TEXTURE_2D)
            glMatrixMode(GL_PROJECTION)
            glPushMatrix()
            glLoadIdentity()
            glMatrixMode(GL_MODELVIEW)
            glPushMatrix()
            glLoadIdentity()
            x0=float(self.selectanchor[0]*2)/size.x-1
            y0=1-float(self.selectanchor[1]*2)/size.y
            x1=float(self.mousenow[0]*2)/size.x-1
            y1=1-float(self.mousenow[1]*2)/size.y
            glBegin(GL_LINE_LOOP)
            glVertex3f(x0, y0, -0.9)
            glVertex3f(x0, y1, -0.9)
            glVertex3f(x1, y1, -0.9)
            glVertex3f(x1, y0, -0.9)
            glEnd()
            glPopMatrix()
            glMatrixMode(GL_PROJECTION)
            glPopMatrix()
            glMatrixMode(GL_MODELVIEW)

        # Display
        self.SwapBuffers()

        glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT)
        # Pre-prepare selection list
        if not self.selectlist:
            self.selectlist=glGenLists(1)
            glNewList(self.selectlist, GL_COMPILE)
            glInitNames()
            glPushName(0)
            glDisable(GL_TEXTURE_2D)
            glDisable(GL_DEPTH_TEST)
            glDisable(GL_CULL_FACE)
            for i in range(len(objects)):
                glLoadName(i)
                obj=objects[i]
                (x,z)=self.latlon2m(obj.lat, obj.lon)
                (base,culled,nocull,texno,poly)=self.vertexcache.get(obj.name)
                glPushMatrix()
                glTranslatef(x, obj.height, z)
                glRotatef(-obj.hdg, 0.0,1.0,0.0)
                glDrawArrays(GL_TRIANGLES, base, culled+nocull)
                glPopMatrix()
            for i in range(len(polygons)):
                poly=polygons[i]
                if poly.kind not in [Polygon.EXCLUDE, Polygon.FACADE, Polygon.FOREST]: continue
                glLoadName(i|MSKSEL)
                glBegin(GL_LINE_LOOP)
                for p in poly.points:
                    glVertex3f(p[0],p[1],p[2])
                glEnd()
                if poly.kind==Polygon.FACADE and dofacades:
                    glBegin(GL_QUADS)
                    for p in poly.quads:
                        glTexCoord2f(p[3],p[4])
                        glVertex3f(p[0],p[1],p[2])
                    glEnd()
                    if poly.roof:
                        glBegin(GL_TRIANGLE_FAN)	# Better for concave
                        for p in poly.roof+[poly.roof[1]]:
                            glTexCoord2f(p[3],p[4])
                            glVertex3f(p[0],p[1],p[2])
                        glEnd()
            glEnable(GL_DEPTH_TEST)
            glEndList()
            
    def select(self):
        #print "sel"
        if not self.currentobjects():
            self.selections=[]	# Can't remember

        glSelectBuffer(65536)	# number of objects appears to be this/4
        glRenderMode(GL_SELECT)

        size = self.GetClientSize()
        glViewport(0, 0, *size)
        glMatrixMode(GL_PROJECTION)
        glPushMatrix()
        glLoadIdentity()
        viewport=glGetIntegerv(GL_VIEWPORT)
        if self.selectanchor:	# drag
            # maths goes wrong if zero-sized box
            if self.selectanchor[0]==self.mousenow[0]: self.mousenow[0]+=1
            if self.selectanchor[1]==self.mousenow[1]: self.mousenow[1]+=1
            gluPickMatrix((self.selectanchor[0]+self.mousenow[0])/2,
                          size[1]-1-(self.selectanchor[1]+self.mousenow[1])/2,
                          abs(self.selectanchor[0]-self.mousenow[0]),
                          abs(self.selectanchor[1]-self.mousenow[1]),
                          (0, 0, size[0], size[1]))
        else:	# click
            gluPickMatrix(self.mousenow[0],
                          size[1]-1-self.mousenow[1], 5,5,
                          (0, 0, size[0], size[1]))
        glOrtho(-self.d, self.d,
                -self.d*size.y/size.x, self.d*size.y/size.x,
                -self.d*self.cliprat, self.d*self.cliprat)
        glMatrixMode(GL_MODELVIEW)
        
        glCallList(self.selectlist)

        # Select poly node?
        if not self.selectanchor and len(self.selected)==1 and self.selected[0]&MSKSEL:
            poly=self.currentpolygons()[self.selected[0]&MSKPOLY]
            for i in range(len(poly.points)):
                glLoadName(i|MSKNODE)
                glBegin(GL_POINTS)
                glVertex3f(poly.points[i][0], poly.points[i][1], poly.points[i][2])
                glEnd()

        selections=[]
        try:
            for min_depth, max_depth, (names,) in glRenderMode(GL_RENDER):
                selections.append(int(names))
        except:	# overflow
            pass
        # Restore state for unproject
        glMatrixMode(GL_PROJECTION)
        glPopMatrix()	
        glMatrixMode(GL_MODELVIEW)

        # Select poly node?
        if not self.selectanchor and len(selections)==1 and selections[0]&MSKSEL and self.selected!=selections:
            # selected a poly, now try again for a node
            self.selected=[selections[0]]
            self.select()
            self.trashlists(True)	# Manually draw just this object
            self.Refresh()
            return
        for i in selections:
            if i&MSKNODE:
                self.selectednode=i&MSKPOLY
                self.frame.ShowSel()
                return
        else:
            self.selectednode=None
            
        if self.selectanchor:	# drag - add or remove all
            if self.selectctrl:
                for i in selections:
                    if not i in self.selected:
                        self.selected.append(i)
                    else:
                        self.selected.remove(i)
            else:
                self.selected=list(selections)
        else:			# click - Add or remove one
            self.trashlists(True)	# recompute obj and select lists
            if self.selectctrl:
                for i in selections:
                    if not i in self.selected:
                        self.selected.append(i)
                        break
                else:	# all selected - remove one
                    for i in self.selected:
                        if i in selections:
                            self.selected.remove(i)
                            break
            else:
                if not selections:
                    self.selected=[]
                elif selections==self.selections and len(self.selected)==1 and self.selected[0] in self.selections:
                    # cycle through selections
                    self.selected=[selections[(selections.index(self.selected[0])+1)%len(selections)]]
                else:
                    self.selected=[selections[0]]
        self.selections=selections

        self.Refresh()
        self.frame.ShowSel()
        
    def latlon2m(self, lat, lon):
        return(((lon-self.centre[1])*onedeg*cos(d2r*lat),
                (self.centre[0]-lat)*onedeg))

    def aptlatlon2m(self, lat, lon):
        # version of the above with fudge factors for runways/taxiways
        return(((lon-self.centre[1])*(onedeg+8)*cos(d2r*lat),
                (self.centre[0]-lat)*(onedeg-2)))

    def currentobjects(self):
        key=(self.tile[0],self.tile[1])
        if key in self.objects:
            return self.objects[key]
        else:
            return []
    
    def currentpolygons(self):
        key=(self.tile[0],self.tile[1])
        if key in self.polygons:
            return self.polygons[key]
        else:
            return []
    
    def setbackground(self, background):
        if background:
            (image, lat, lon, hdg, width, length, opacity)=background
            if [int(floor(lat)),int(floor(lon))]==self.tile:
                (x,z)=self.latlon2m(lat,lon)
                height=self.vertexcache.height(self.tile,self.options,x,z)
            else:
                height=None
            self.background=(image, lat, lon, hdg, width, length, opacity, height)
        else:
            self.background=None
        self.Refresh()

    def add(self, name, lat, lon, hdg):
        if not self.vertexcache.load(name):
            wx.MessageBox("Can't read %s." % name, 'Cannot add this object or facade.', wx.ICON_ERROR|wx.OK, self.frame)
            return False
        self.trashlists(self.selected)
        thing=self.vertexcache.get(name)
        if self.selectednode!=None:
            #print "node"
            poly=self.currentpolygons()[self.selected[0]&MSKPOLY]
            if poly.kind==Polygon.EXCLUDE: return False
            if not (self.undostack and self.undostack[-1].kind==UndoEntry.MOVE and self.undostack[-1].tile==self.tile and len(self.undostack[-1].data)==1 and self.undostack[-1].data[0][0]==self.selected[0]):
                self.undostack.append(UndoEntry(self.tile, UndoEntry.MOVE, [(self.selected[0], poly.clone())]))
            n=len(poly.nodes[0])
            self.selectednode+=1
            poly.nodes=[poly.nodes[0]]	# Destroy other windings
            poly.nodes[0].insert(self.selectednode,
                                 (round2res((poly.nodes[0][self.selectednode-1][0]+poly.nodes[0][(self.selectednode)%n][0])/2),
                                  round2res((poly.nodes[0][self.selectednode-1][1]+poly.nodes[0][(self.selectednode)%n][1])/2)))
            self.updatepoly(poly)
        elif isinstance(thing,ExcludeDef):
            #print "polygon"
            polygons=self.currentpolygons()
            poly=Polygon(name, Polygon.EXCLUDE, 0,
                         [[(lon-0.001,lat-0.001), (lon+0.001,lat-0.001),
                           (lon+0.001,lat+0.001), (lon-0.001,lat+0.001)]])
            self.updatepoly(poly)
            self.selected=[MSKSEL]
            self.selectednode=None
            polygons.insert(0, poly)
            self.polygons[(self.tile[0],self.tile[1])]=polygons
            self.undostack.append(UndoEntry(self.tile, UndoEntry.ADD,
                                            self.selected))
        elif isinstance(thing,FacadeDef):
            #print "facade"
            polygons=self.currentpolygons()
            poly=Polygon(name, Polygon.FACADE, 10, [[]])
            h=d2r*hdg
            for i in [h+5*pi/4, h+3*pi/4, h+pi/4, h+7*pi/4]:
                poly.nodes[0].append((round2res(lon+sin(i)*0.00014142),
                                      round2res(lat+cos(i)*0.00014142)))
            self.updatepoly(poly)
            self.selected=[len(polygons)|MSKSEL]
            self.selectednode=None
            polygons.append(poly)
            self.polygons[(self.tile[0],self.tile[1])]=polygons
            self.undostack.append(UndoEntry(self.tile, UndoEntry.ADD,
                                            self.selected))
        elif isinstance(thing,ForestDef):
            #print "facade"
            polygons=self.currentpolygons()
            poly=Polygon(name, Polygon.FOREST, 128, [[]])
            h=d2r*hdg
            for i in [h+5*pi/4, h+3*pi/4, h+pi/4, h+7*pi/4]:
                poly.nodes[0].append((round2res(lon+sin(i)*0.0014142),
                                      round2res(lat+cos(i)*0.0014142)))
            self.updatepoly(poly)
            self.selected=[len(polygons)|MSKSEL]
            self.selectednode=None
            polygons.append(poly)
            self.polygons[(self.tile[0],self.tile[1])]=polygons
            self.undostack.append(UndoEntry(self.tile, UndoEntry.ADD,
                                            self.selected))
        else:
            (base,culled,nocull,texno,poly)=thing	# for poly
            (x,z)=self.latlon2m(lat,lon)
            height=self.vertexcache.height(self.tile,self.options,x,z)
            objects=self.currentobjects()
            if poly:
                self.selected=[0]
                objects.insert(0, Object(name, lat, lon, hdg, height))
            else:
                self.selected=[len(objects)]
                objects.append(Object(name, lat, lon, hdg, height))
            self.selectednode=None
            self.objects[(self.tile[0],self.tile[1])]=objects
            self.undostack.append(UndoEntry(self.tile, UndoEntry.ADD,
                                            self.selected))
        self.Refresh()
        self.frame.ShowSel()
        return True

    def movesel(self, dlat, dlon, dhdg=0, dheight=0):
        # returns True if changed something
        if not self.selected: return False
        if not self.selectmove: self.trashlists()
        objects=self.currentobjects()
        polygons=self.currentpolygons()
        moved=[]
        for i in self.selected:
            if i&MSKSEL:
                thing=polygons[i&MSKPOLY]
                moved.append((i, thing.clone()))
                thing.param+=dheight
                if thing.param<1: thing.param=1
                elif thing.kind==Polygon.FACADE and thing.param>32767:
                    thing.param=32767	# unit16
                elif thing.kind==Polygon.FOREST and thing.param>255:
                    thing.param=255
                thing.nodes=[thing.nodes[0]]	# Destroy other windings
                if self.selectednode!=None:
                    thing.nodes[0][self.selectednode]=(max(self.tile[1], min(self.tile[1]+maxres, thing.nodes[0][self.selectednode][0]+dlon)),
                                                       max(self.tile[0], min(self.tile[0]+maxres, thing.nodes[0][self.selectednode][1]+dlat)))
                    
                    if thing.kind==Polygon.EXCLUDE:
                        if self.selectednode&1:
                            thing.nodes[0][(self.selectednode-1)%4]=(thing.nodes[0][(self.selectednode-1)%4][0], thing.nodes[0][self.selectednode][1])
                            thing.nodes[0][(self.selectednode+1)%4]=(thing.nodes[0][self.selectednode][0], thing.nodes[0][(self.selectednode+1)%4][1])
                        else:
                            thing.nodes[0][(self.selectednode+1)%4]=(thing.nodes[0][(self.selectednode+1)%4][0], thing.nodes[0][self.selectednode][1])
                            thing.nodes[0][(self.selectednode-1)%4]=(thing.nodes[0][self.selectednode][0], thing.nodes[0][(self.selectednode-1)%4][1])
                else:
                    for n in range(len(thing.nodes[0])):
                        if dhdg and thing.kind!=Polygon.EXCLUDE:
                            h=atan2(thing.nodes[0][n][0]-thing.lon,
                                    thing.nodes[0][n][1]-thing.lat)+d2r*dhdg
                            l=hypot(thing.nodes[0][n][0]-thing.lon,
                                    thing.nodes[0][n][1]-thing.lat)
                            thing.nodes[0][n]=(round2res(thing.lon+sin(h)*l),
                                               round2res(thing.lat+cos(h)*l))
                        thing.nodes[0][n]=(max(self.tile[1], min(self.tile[1]+maxres, thing.nodes[0][n][0]+dlon)),
                                           max(self.tile[0], min(self.tile[0]+maxres, thing.nodes[0][n][1]+dlat)))
                self.updatepoly(thing)
            else:
                thing=objects[i]
                moved.append((i, thing.clone()))
                thing.lat=max(self.tile[0], min(self.tile[0]+maxres, thing.lat+dlat))
                thing.lon=max(self.tile[1], min(self.tile[1]+maxres, thing.lon+dlon))
                thing.hdg=(thing.hdg+dhdg)%360
                (x,z)=self.latlon2m(thing.lat,thing.lon)
                thing.height=self.vertexcache.height(self.tile,self.options,x,z)
        self.Refresh()
        self.frame.ShowSel()
        if self.undostack and self.undostack[-1].kind==UndoEntry.MOVE and self.undostack[-1].tile==self.tile and len(self.undostack[-1].data)==len(self.selected):
            for j in range(len(self.selected)):
                (i, p)=self.undostack[-1].data[j]
                if self.selected[j]!=i:
                    break
            else:
                return True
        self.undostack.append(UndoEntry(self.tile, UndoEntry.MOVE, moved))
        return True

    def delsel(self):
        # returns True if deleted something
        if not self.selected: return False
        objects=self.currentobjects()
        polygons=self.currentpolygons()
        if self.selectednode!=None:
            #print "node"
            poly=polygons[self.selected[0]&MSKPOLY]
            if poly.kind==Polygon.EXCLUDE or len(poly.nodes[0])<=2:
                return False
            if not (self.undostack and self.undostack[-1].kind==UndoEntry.MOVE and self.undostack[-1].tile==self.tile and len(self.undostack[-1].data)==1 and self.undostack[-1].data[0][0]==self.selected[0]):
                self.undostack.append(UndoEntry(self.tile, UndoEntry.MOVE, [(self.selected[0], poly.clone())]))
            poly.nodes=[poly.nodes[0]]	# Destroy other windings
            poly.nodes[0].pop(self.selectednode)
            self.selectednode=self.selectednode%len(poly.nodes[0])
            self.updatepoly(poly)
        else:
            newobjects=[]
            newpolygons=[]
            deleted=[]
            for i in range(len(objects)):
                if not i in self.selected:
                    newobjects.append(objects[i])
                else:
                    deleted.append((i, objects[i]))
            for i in range(len(polygons)):
                if not i|MSKSEL in self.selected:
                    newpolygons.append(polygons[i])
                else:
                    deleted.append((i|MSKSEL, polygons[i]))
            self.objects[(self.tile[0],self.tile[1])]=newobjects
            self.polygons[(self.tile[0],self.tile[1])]=newpolygons
            self.undostack.append(UndoEntry(self.tile, UndoEntry.DEL, deleted))
            self.selected=[]
        self.trashlists()
        self.Refresh()
        self.frame.ShowSel()
        return True

    def undo(self):
        # returns True if undostack still not empty
        if not self.undostack: return False	# can't happen
        undo=self.undostack.pop()
        objects=self.objects[undo.tile[0],undo.tile[1]]
        polygons=self.polygons[undo.tile[0],undo.tile[1]]
        avlat=0
        avlon=0
        self.trashlists(True)
        self.selected=[]
        self.selectednode=None
        if undo.kind==UndoEntry.ADD:
            for i in undo.data:
                if i&MSKSEL:
                    thing=polygons[i&MSKPOLY]
                    polygons.pop(i&MSKPOLY)	# Only works if just one item
                else:
                    thing=objects[i]
                    objects.pop(i)		# Only works if just one item
                avlat+=thing.lat
                avlon+=thing.lon
        elif undo.kind==UndoEntry.DEL:
            for (i, thing) in undo.data:
                if not self.vertexcache.load(thing.name, True):	# may have reloaded
                    myMessageBox("Can't read %s." % thing.name, 'Using a placeholder.', wx.ICON_EXCLAMATION|wx.OK, self.frame)
                if i&MSKSEL:
                    self.updatepoly(thing)
                    polygons.insert(i&MSKPOLY, thing)
                else:
                    (x,z)=self.latlon2m(thing.lat, thing.lon)
                    thing.height=self.vertexcache.height(self.tile,self.options,x,z)
                    objects.insert(i, thing)
                avlat+=thing.lat
                avlon+=thing.lon
                self.selected.append(i)
        elif undo.kind==UndoEntry.MOVE:
            for (i, thing) in undo.data:
                if i&MSKSEL:
                    self.updatepoly(thing)
                    polygons[i&MSKPOLY]=thing
                else:
                    (x,z)=self.latlon2m(thing.lat, thing.lon)
                    thing.height=self.vertexcache.height(self.tile,self.options,x,z)
                    objects[i]=thing
                avlat+=thing.lat
                avlon+=thing.lon
                self.selected.append(i)
        avlat/=len(undo.data)
        avlon/=len(undo.data)
        self.goto([avlat,avlon])
        self.frame.loc=[avlat,avlon]
        self.frame.ShowLoc()
        self.frame.ShowSel()
        return self.undostack!=[]
        
    def clearsel(self):
        self.selected=[]
        self.selectednode=None
        self.trashlists(True)
        self.Refresh()

    def allsel(self, withctrl):
        # fake up mouse drag
        self.selectanchor=[0,0]
        self.selectctrl=withctrl
        size=self.GetClientSize()
        self.mousenow=[size.x-1,size.y-1]
        self.select()
        self.selectanchor=None
        self.trashlists(True)	# recompute obj and select lists

    def getsel(self):
        # return current selection, or average
        if not self.selected: return ([], '', None, None, None)
        objects=self.currentobjects()
        polygons=self.currentpolygons()
        lat=lon=0
        names=[]
        for i in self.selected:
            if i&MSKSEL:
                thing=polygons[i&MSKPOLY]
            else:
                thing=objects[i]
            names.append(thing.name)
            lat+=thing.lat
            lon+=thing.lon

        if len(self.selected)==1:
            if self.selected[0]&MSKSEL:
                if self.selectednode!=None:
                    (lon,lat)=thing.nodes[0][self.selectednode]
                    if self.options&Prefs.ELEVATION and thing.kind!=Polygon.EXCLUDE:
                        return (names, "Lat: %-10.6f  Lon: %-11.6f  Elv: %-6.1f  Node %d" % (lat, lon, thing.points[self.selectednode][1], self.selectednode), lat, lon, None)
                    else:
                        return (names, "Lat: %-10.6f  Lon: %-11.6f  Node %d" % (lat, lon, self.selectednode), lat, lon, None)
                else:
                    if thing.kind==Polygon.FACADE:
                        return (names, 'Lat: %-10.6f  Lon: %-11.6f  Height: %-4d  (%d nodes)' % (lat, lon, thing.param, len(thing.points)), lat, lon, None)
                    elif thing.kind==Polygon.FOREST:
                        return (names, 'Lat: %-10.6f  Lon: %-11.6f  Density: %-4.1f%%  (%d nodes)' % (lat, lon, thing.param/2.55, len(thing.points)), lat, lon, None)
                    else:
                        return (names, 'Lat: %-10.6f  Lon: %-11.6f  (%d nodes)' % (lat, lon, len(thing.points)), lat, lon, None)
            else:
                if self.options&Prefs.ELEVATION:
                    return (names, "Lat: %-10.6f  Lon: %-11.6f  Hdg: %-3.0f  Elv: %-6.1f" % (lat, lon, thing.hdg, thing.height), lat, lon, thing.hdg)
                else:
                    return (names, "Lat: %-10.6f  Lon: %-11.6f  Hdg: %-3.0f" % (lat, lon, thing.hdg), lat, lon, thing.hdg)
        else:
            lat/=len(self.selected)
            lon/=len(self.selected)
            return (names, "Lat: %-10.6f  Lon: %-11.6f  (%d objects)" % (lat, lon, len(self.selected)), lat, lon, None)

    def getheight(self):
        # return current height
        return self.y

    def reload(self, reload, options, airports, navaids,
               objectmap, objects, polygons,
               background, terrain, dsfdirs):
        self.valid=False
        self.options=options
        self.airports=airports	# [runways] by tile
        self.navaids=navaids
        self.vertexcache.flushObjs(objectmap, terrain, dsfdirs)
        self.trashlists(True, True)
        self.tile=[0,999]	# force reload
        for key in self.runways.keys():	# need to re-layout runways
            glDeleteLists(self.runways.pop(key), 1)
        if objects!=None:
            self.objects=objects
            self.polygons=polygons
        for polygons in self.polygons.values():
            for poly in polygons:
                poly.points=[]		# force update
        if background:
            (image, lat, lon, hdg, width, length, opacity)=background
            self.background=(image, lat, lon, hdg, width, length, opacity,None)
        else:
            self.background=None
        self.selected=[]	# may not have same indices in new list
        self.selectednode=None
        if not reload:
            self.undostack=[]

        if 0:	# debug
            print "Frame:\t%s"  % self.frame.GetId()
            print "Toolb:\t%s"  % self.frame.toolbar.GetId()
            print "Parent:\t%s" % self.parent.GetId()
            print "Split:\t%s"  % self.frame.splitter.GetId()
            print "MyGL:\t%s"   % self.GetId()
            print "Palett:\t%s" % self.frame.palette.GetId()
            if 'GetChoiceCtrl' in dir(self.frame.palette):
                print "Choice:\t%s" %self.frame.palette.GetChoiceCtrl().GetId()

    def goto(self, loc=None, hdg=None, elev=None, dist=None, options=None):
        errobjs=[]
        if loc!=None:
            newtile=[int(floor(loc[0])),int(floor(loc[1]))]
            self.centre=[newtile[0]+0.5, newtile[1]+0.5]
            (self.x, self.z)=self.latlon2m(loc[0],loc[1])
        else:
            newtile=self.tile
        if hdg!=None: self.h=hdg
        if elev!=None: self.e=elev
        if dist!=None: self.d=dist
        if options==None: options=self.options

        if newtile!=self.tile or options!=self.options:
            if newtile!=self.tile:
                self.selected=[]
                self.selectednode=None
                self.frame.ShowSel()
            self.valid=False
            self.tile=newtile
            self.vertexcache.flush()
            self.trashlists(True, True)
            progress=wx.ProgressDialog('Loading', 'Terrain', 18, self, wx.PD_APP_MODAL)
            self.vertexcache.loadMesh(newtile, options)

            progress.Update(1, 'Terrain textures')
            self.vertexcache.getMesh(newtile, options)	# allocates into array

            progress.Update(2, 'Mesh')
            self.vertexcache.getMeshdata(newtile, options)

            if options!=self.options:
                # invalidate all heights
                for objects in self.objects.values():
                    for obj in objects:
                        obj.height=None
                for polygons in self.polygons.values():
                    for poly in polygons:
                        poly.points=[]
            self.options=options

            # Limit progress dialog to 10 updates
            objects=self.currentobjects()
            p=len(objects)/10+1
            n=0
            i=0
            for i in range(len(objects)):
                obj=objects[i]
                if i==n:
                    progress.Update(3+i/p, 'Objects')
                    n+=p
                if not self.vertexcache.load(obj.name,True) and not obj.name in errobjs:
                    errobjs.append(obj.name)
                if obj.height==None:
                    (x,z)=self.latlon2m(obj.lat, obj.lon)
                    obj.height=self.vertexcache.height(newtile,options,x,z)

            progress.Update(13, 'Polygons')
            polygons=self.currentpolygons()
            for poly in polygons:
                if poly.kind in [Polygon.EXCLUDE, Polygon.FACADE, Polygon.FOREST]:
                    if not self.vertexcache.load(poly.name,True) and not poly.name in errobjs:
                        errobjs.append(poly.name)
                if not poly.points:
                    self.updatepoly(poly)

            # Lay out runways
            progress.Update(14, 'Runways')
            key=(newtile[0],newtile[1],options&Prefs.ELEVATION)
            if key not in self.runways:
                airports=[]
                pavements=[]
                # Find bounding boxes of airport runways in this tile
                for apt in self.airports[(newtile[0],newtile[1])]:
                    minx=minz=maxint
                    maxx=maxz=-maxint
                    runways=[]
                    for thing in apt:
                        if isinstance(thing, tuple):
                            if not isinstance(thing[0], tuple):
                                (lat,lon,h,length,width,stop1,stop2,surf)=thing
                                (cx,cz)=self.aptlatlon2m(lat,lon)
                                length1=length/2+stop1
                                length2=length/2+stop2
                                h=d2r*h
                                coshdg=cos(h)
                                sinhdg=sin(h)
                                p1=[cx-length1*sinhdg, 0, cz+length1*coshdg]
                                p2=[cx+length2*sinhdg, 0, cz-length2*coshdg]
                            else:
                                ((lat1,lon1),(lat2,lon2),width,stop1,stop2,surf)=thing
                                (x1,z1)=self.latlon2m(lat1,lon1)
                                (x2,z2)=self.latlon2m(lat2,lon2)
                                h=-atan2(x1-x2,z1-z2) #%twopi
                                coshdg=cos(h)
                                sinhdg=sin(h)
                                p1=[x1-stop1*sinhdg, 0, z1+stop1*coshdg]
                                p2=[x2+stop2*sinhdg, 0, z2-stop2*coshdg]
                            minx=min(minx, p1[0], p2[0])
                            maxx=max(maxx, p1[0], p2[0])
                            minz=min(minz, p1[2], p2[2])
                            maxz=max(maxz, p1[2], p2[2])
                            runways.append((p1,p2, width/2*coshdg,width/2*sinhdg, {}))
                        else:
                            pavements.append(thing)
                    airports.append(([minx, maxx, minz, maxz], runways))
    
                self.runways[key]=glGenLists(1)
                glNewList(self.runways[key], GL_COMPILE)
                glColor3f(0.333,0.333,0.333)
                glDisable(GL_TEXTURE_2D)
                glPolygonOffset(-10, -100)	# Stupid value cos not coplanar
                glEnable(GL_POLYGON_OFFSET_FILL)
                glDepthMask(GL_FALSE)	# offset mustn't update depth

                for (bbox, tris) in self.vertexcache.getMeshdata(newtile,options):
                    for (abox, runways) in airports:
                        if (bbox[0] >= abox[1] or bbox[2] >= abox[3] or bbox[1] <= abox[0] or bbox[3] <= abox[2]):
                            continue
                        for tri in tris:
                            for (p1, p2, xinc, zinc, cuts) in runways:
                                (pt, coeffs)=tri
                                i1=i2=False
                                for j in range(3):
                                    #http://astronomy.swin.edu.au/~pbourke/geometry/lineline2d
                                    p3=pt[j]
                                    p4=pt[(j+1)%3]
                                    d=(p4[2]-p3[2])*(p2[0]-p1[0])-(p4[0]-p3[0])*(p2[2]-p1[2])
                                    if d==0: continue	# parallel
                                    b=((p2[0]-p1[0])*(p1[2]-p3[2])-(p2[2]-p1[2])*(p1[0]-p3[0]))/d
                                    if b<=0 or b>=1: continue	# no intersect
                                    a=((p4[0]-p3[0])*(p1[2]-p3[2])-(p4[2]-p3[2])*(p1[0]-p3[0]))/d
                                    if a>=0: i1 = not i1
                                    if a<=1: i2 = not i2
                                    if a<0 or a>1: continue	# no intersection
                                    cuts[a]=([p1[0]+a*(p2[0]-p1[0]),
                                              p3[1]+b*(p4[1]-p3[1]),
                                              p1[2]+a*(p2[2]-p1[2])])
                                    
                                if i1:	# p1 is enclosed by this tri
                                    p1[1]=self.vertexcache.height(newtile,options,p1[0],p1[2],tri)
                                if i2:	# p2 is enclosed by this tri
                                    p2[1]=self.vertexcache.height(newtile,options,p2[0],p2[2],tri)
                # strip out bounding box and add cuts
                for (abox, runways) in airports:
                    for (p1, p2, xinc, zinc, cuts) in runways:
                        glBegin(GL_QUAD_STRIP)
                        a=cuts.keys()
                        a.sort()
                        glVertex3f(p1[0]+xinc, p1[1], p1[2]+zinc)
                        glVertex3f(p1[0]-xinc, p1[1], p1[2]-zinc)
                        if len(a) and a[0]>0.01:
                            glVertex3f(cuts[a[0]][0]+xinc, cuts[a[0]][1], cuts[a[0]][2]+zinc)
                            glVertex3f(cuts[a[0]][0]-xinc, cuts[a[0]][1], cuts[a[0]][2]-zinc)
                        for i in range(1, len(a)):
                            if a[i]-a[i-1]>0.01:
                                glVertex3f(cuts[a[i]][0]+xinc, cuts[a[i]][1], cuts[a[i]][2]+zinc)
                                glVertex3f(cuts[a[i]][0]-xinc, cuts[a[i]][1], cuts[a[i]][2]-zinc)
                        glVertex3f(p2[0]+xinc, p2[1], p2[2]+zinc)
                        glVertex3f(p2[0]-xinc, p2[1], p2[2]-zinc)
                        glEnd()

                # Pavements
                oldtess=True
                try:
                    if gluGetString(GLU_VERSION) >= '1.2' and GLU_VERSION_1_2:
                        oldtess=False
                except:
                    pass
                
                tessObj = gluNewTess()
                if oldtess:
                    # untested
                    gluTessCallback(tessObj, GLU_BEGIN,  self.tessbegin)
                    gluTessCallback(tessObj, GLU_VERTEX, self.tessvertex)
                    gluTessCallback(tessObj, GLU_END,    self.tessend)
                else:
                    gluTessNormal(tessObj, 0, -1, 0)
                    gluTessCallback(tessObj, GLU_TESS_BEGIN,  self.tessbegin)
                    gluTessCallback(tessObj, GLU_TESS_VERTEX, self.tessvertex)
                    gluTessCallback(tessObj, GLU_TESS_END,    self.tessend)
                    gluTessCallback(tessObj, GLU_TESS_COMBINE,self.tesscombine)
                for pave in pavements:
                    try:
                        if oldtess:
                            gluBeginPolygon(tessObj)
                        else:
                            gluTessBeginPolygon(tessObj, None)
                        for i in range(len(pave)):
                            if oldtess:
                                if i:
                                    gluNextContour(tessObj, GLU_CW)
                                else:
                                    gluNextContour(tessObj, GLU_CCW)
                            else:
                                gluTessBeginContour(tessObj)
                            edge=pave[i]
                            n=len(edge)
                            for j in range(n):
                                if len(edge[j])==len(edge[(j+1)%n])==2:
                                    points=[edge[j]]
                                else:
                                    cpoints=[(edge[j][0],edge[j][1])]
                                    if len(edge[j])!=2:
                                        cpoints.append((edge[j][2],edge[j][3]))
                                    if len(edge[(j+1)%n])!=2:
                                        cpoints.append((2*edge[(j+1)%n][0]-edge[(j+1)%n][2],2*edge[(j+1)%n][1]-edge[(j+1)%n][3]))
                                            
                                    cpoints.append((edge[(j+1)%n][0],edge[(j+1)%n][1]))
                                    points=[self.bez(cpoints, u/10.0) for u in range(10)]
                                for (lat,lon) in points:
                                    (x,z)=self.latlon2m(lat,lon)
                                    y=self.vertexcache.height(newtile,options,x,z)
                                    pt3=[x,y,z]
                                    gluTessVertex(tessObj, pt3, pt3)
                            if not oldtess:
                                gluTessEndContour(tessObj)
                        if oldtess:
                            gluEndPolygon(tessObj)
                        else:
                            gluTessEndPolygon(tessObj)
                    except GLUerror, e:
                        pass
                gluDeleteTess(tessObj)
                        
                progress.Update(15, 'Navaids')
                objs={2:  'lib/airport/NAVAIDS/NDB_3.obj',
                      3:  'lib/airport/NAVAIDS/VOR.obj',
                      4:  'lib/airport/NAVAIDS/ILS.obj',
                      5:  'lib/airport/NAVAIDS/ILS.obj',
                      6:  'lib/airport/NAVAIDS/glideslope.obj',
                      7:  'lib/airport/NAVAIDS/Marker1.obj',
                      8:  'lib/airport/NAVAIDS/Marker2.obj',
                      9:  'lib/airport/NAVAIDS/Marker2.obj',
                      18: 'lib/airport/landscape/beacon2.obj',
                      19: '*windsock.obj',
                      181:'lib/airport/lights/beacon_airport.obj',
                      182:'lib/airport/lights/beacon_seaport.obj',
                      183:'lib/airport/lights/beacon_heliport.obj',
                      184:'lib/airport/lights/beacon_mil.obj',
                      185:'lib/airport/lights/beacon_airport.obj',
                      211:'lib/airport/lights/VASI.obj',
                      212:'lib/airport/lights/PAPI.obj',
                      213:'lib/airport/lights/PAPI.obj',
                      214:'lib/airport/lights/PAPI.obj',
                      215:'lib/airport/lights/VASI3.obj',
                      216:'lib/airport/lights/rway_guard.obj',
                      }
                for name in objs.values():
                    self.vertexcache.load(name, True)	# skip errors
                self.vertexcache.realize()
                glDepthMask(GL_TRUE)
                glEnable(GL_CULL_FACE)
                cullstate=True
                glColor3f(0.75, 0.75, 0.75)	# Unpainted
                glEnable(GL_TEXTURE_2D)
                glDisable(GL_POLYGON_OFFSET_FILL)
                polystate=0
                for (i, lat, lon, hdg) in self.navaids:
                    if [int(floor(lat)),int(floor(lon))]==newtile and i in objs:
                        name=objs[i]
                        (base,culled,nocull,texno,poly)=self.vertexcache.get(name)
                        coshdg=cos(d2r*hdg)
                        sinhdg=sin(d2r*hdg)
                        (x,z)=self.latlon2m(lat,lon)
                        y=self.vertexcache.height(newtile,options,x,z)

                        glBindTexture(GL_TEXTURE_2D, texno)
                        if poly:
                            if polystate!=poly:
                                glPolygonOffset(-1*poly, -1*poly)
                                glEnable(GL_POLYGON_OFFSET_FILL)
                            polystate=poly
                        else:
                            if polystate: glDisable(GL_POLYGON_OFFSET_FILL)
                            polystate=0
                        
                        if i==211:
                            seq=[(1,75),(-1,75),(1,-75),(-1,-75)]
                        elif i in range(212,215):
                            seq=[(12,0),(4,0),(-4,0),(-12,0)]
                        else:
                            seq=[(0,0)]
                        for (xinc,zinc) in seq:
                            glPushMatrix()
                            glTranslatef(x+xinc*coshdg-zinc*sinhdg, y,
                                         z+xinc*sinhdg+zinc*coshdg)
                            glRotatef(-hdg, 0.0,1.0,0.0)
                            if culled:
                                if not cullstate: glEnable(GL_CULL_FACE)
                                cullstate=True
                                glDrawArrays(GL_TRIANGLES, base, culled)
                            if nocull:
                                if cullstate: glDisable(GL_CULL_FACE)
                                cullstate=False
                                glDrawArrays(GL_TRIANGLES, base+culled, nocull)
                            glPopMatrix()

                glEndList()

            # Done
            progress.Update(16, 'Done')
            if self.background:
                (image, lat, lon, hdg, width, length, opacity, height)=self.background
                if [int(floor(lat)),int(floor(lon))]==self.tile:
                    (x,z)=self.latlon2m(lat,lon)
                    height=self.vertexcache.height(self.tile,options,x,z)
                else:
                    height=None
                self.background=(image, lat, lon, hdg, width, length, opacity, height)
            progress.Destroy()
            self.valid=True

        # cursor position
        self.y=self.vertexcache.height(self.tile,self.options,self.x,self.z)

        # Redraw can happen under MessageBox, so do this last
        if errobjs:
            sortfolded(errobjs)
            myMessageBox(str('\n'.join(errobjs)), "Can't read one or more objects.", wx.ICON_EXCLAMATION|wx.OK, self.frame)

        self.Refresh()

    def tessbegin(self, datatype):
        glBegin(datatype)
    
    def tessvertex(self, vertex):
        glVertex3f(*vertex)

    def tesscombine(self, coords, vertex, weight):
        return (coords[0], coords[1], coords[2])

    def tessend(self):
        glEnd()

    def bez(self, p, mu):
        # http://local.wasp.uwa.edu.au/~pbourke/curves/bezier/index.html
        mum1=1-mu
        if len(p)==3:
            mu2  = mu*mu
            mum12= mum1*mum1
            return (p[0][0]*mum12 + 2*p[1][0]*mum1*mu + p[2][0]*mu2,
                    p[0][1]*mum12 + 2*p[1][1]*mum1*mu + p[2][1]*mu2)
        elif len(p)==4:
            mu3  = mu*mu*mu
            mum13= mum1*mum1*mum1
            return (p[0][0]*mum13 + 3*p[1][0]*mu*mum1*mum1 + 3*p[2][0]*mu*mu*mum1 + p[3][0]*mu3,
                    p[0][1]*mum13 + 3*p[1][1]*mu*mum1*mum1 + 3*p[2][1]*mu*mu*mum1 + p[3][1]*mu3)
        else:
            raise ArithmeticError
        
    def trashlists(self, objectstoo=False, terraintoo=False):
        #print "i", objectstoo, runwaysandterraintoo
        if terraintoo:
            if self.meshlist: glDeleteLists(self.meshlist, 1)
            self.meshlist=0
        if objectstoo:
            if self.objectslist: glDeleteLists(self.objectslist, 1)
            self.objectslist=0
        if self.selectlist: glDeleteLists(self.selectlist, 1)
        self.selectlist=0

    def setopts(self, options):
        self.goto(options=options)
        self.frame.ShowLoc()
        self.frame.ShowSel()

    def getworldloc(self, mx, my):
        self.SetCurrent()
        size = self.GetClientSize()
        mx=max(0, min(size[0]-1, mx))
        my=max(0, min(size[1]-1, size[1]-1-my))
        glDisable(GL_TEXTURE_2D)
        glColorMask(GL_FALSE,GL_FALSE,GL_FALSE,GL_FALSE)
        glEnable(GL_CULL_FACE)
        glEnable(GL_DEPTH_TEST)
        glCallList(self.meshlist)	# Terrain only
        #glFinish()	# redundant
        (mz,)=unpack('f',glReadPixels(mx,my, 1,1, GL_DEPTH_COMPONENT,GL_FLOAT))
        (x,y,z)=gluUnProject(mx,my,mz,
                             glGetDoublev(GL_MODELVIEW_MATRIX),
                             glGetDoublev(GL_PROJECTION_MATRIX),
                             (0, 0, size[0], size[1]))
        glColorMask(GL_TRUE,GL_TRUE,GL_TRUE,GL_TRUE)
        glClear(GL_DEPTH_BUFFER_BIT)
        lat=round2res(self.centre[0]-z/onedeg)
        lon=round2res(self.centre[1]+x/(onedeg*cos(d2r*lat)))
        #print "%3d %3d %5.3f, %5d %5.1f %5d, %10.6f %11.6f" % (mx,my,mz, x,y,z, lat,lon)
        return (lat,lon)


    def updatepoly(self, poly, bailearly=False):

        def subdiv(size, scale, divs, ends, isvert):
            trgsize=size/scale
            cumsize=0
            if ends[0]+ends[1]>=len(divs):
                points=range(len(divs))
                for i in points: cumsize+=divs[i][1]-divs[i][0]
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


        poly.lat=poly.lon=count=0
        poly.points=[]

        n=len(poly.nodes[0])
        a=0
        for i in range(n):
            (x,z)=self.latlon2m(poly.nodes[0][i][1], poly.nodes[0][i][0])
            y=self.vertexcache.height(self.tile,self.options,x,z)
            poly.points.append((x,y,z))
            poly.lon+=poly.nodes[0][i][0]
            poly.lat+=poly.nodes[0][i][1]
            a+=poly.nodes[0][i][0]*poly.nodes[0][(i+1)%n][1]-poly.nodes[0][(i+1)%n][0]*poly.nodes[0][i][1]
        poly.lat=round2res(poly.lat/len(poly.nodes[0]))
        poly.lon=round2res(poly.lon/len(poly.nodes[0]))

        if a<0:
            # Nodes are clockwise, should be ccw
            poly.nodes[0].reverse()
            poly.points.reverse()
            if self.selectednode!=None: self.selectednode=n-1-self.selectednode

        # Show secondary windings
        for j in range(1,len(poly.nodes)):
            for i in range(len(poly.nodes[j])):
                (x,z)=self.latlon2m(poly.nodes[j][i][1], poly.nodes[j][i][0])
                y=self.vertexcache.height(self.tile,self.options,x,z)
                poly.points.append((x,y,z))

        if poly.kind!=Polygon.FACADE: return
        fac=self.vertexcache.get(poly.name)
        if not isinstance(fac, FacadeDef): return	# unknown

        n=len(poly.points)

        if bailearly:
            # rough estimate of number of quads
            pts=0
            for i in range(n-1+fac.ring):
                pts+=(hypot(poly.points[i][0]-poly.points[(i+1)%n][0],
                            poly.points[i][0]-poly.points[(i+1)%n][0])*len(fac.horiz))/(hscale*(fac.horiz[-1][1]-fac.horiz[0][0]))
            if pts*(1+int((poly.param*len(fac.vert))/(fac.vscale*(fac.vert[-1][1]-fac.vert[0][0]))))>1000:
                return

        poly.quads=[]
        poly.roof=[]
        (vert,vscale)=subdiv(poly.param, fac.vscale, fac.vert,fac.vends, True)

        roofheight=0
        for i in range(len(vert)):
            roofheight+=(fac.vert[vert[i]][1]-fac.vert[vert[i]][0])
        roofheight*=fac.vscale	# not scaled to fit
        
        if fac.roof_slope:
            roofpts=[]
            dist=sin(d2r*fac.roof_slope)*fac.vscale*(fac.vert[vert[-1]][1]-fac.vert[vert[-1]][0])
            for i in range(n):
                if i==n-1 and not fac.ring:
                    tonext=(poly.points[i][0]-poly.points[i-1][0],
                            poly.points[i][2]-poly.points[i-1][2])
                else:
                    tonext=(poly.points[(i+1)%n][0]-poly.points[i][0],
                            poly.points[(i+1)%n][2]-poly.points[i][2])
                m=hypot(*tonext)
                tonext=(tonext[0]/m, tonext[1]/m)
                toprev=(poly.points[(i-1)%n][0]-poly.points[i][0],
                        poly.points[(i-1)%n][2]-poly.points[i][2])
                m=hypot(*toprev)
                toprev=(toprev[0]/m, toprev[1]/m)
                d=toprev[0]*tonext[1]-toprev[1]*tonext[0]
                if n==2 or d==0 or (not fac.ring and (i==0 or i==n-1)):
                    roofpts.append((poly.points[i][0]+dist*tonext[1],
                                    poly.points[i][1]+roofheight,
                                    poly.points[i][2]-dist*tonext[0]))
                else:
                    # http://astronomy.swin.edu.au/~pbourke/geometry/lineline2d
                    u=(toprev[0]*(dist*tonext[0]+dist*toprev[0])+
                       toprev[1]*(dist*tonext[1]+dist*toprev[1]))/d
                    roofpts.append((poly.points[i][0]+dist*tonext[1]+u*tonext[0],
                                    poly.points[i][1]+roofheight,
                                    poly.points[i][2]-dist*tonext[0]+u*tonext[1]))
        else:
            roofpts=[(poly.points[i][0], poly.points[i][1]+roofheight, poly.points[i][2]) for i in range(n)]

        for wall in range(n-1+fac.ring):
            size=hypot(poly.points[(wall+1)%n][0]-poly.points[wall][0],
                       poly.points[(wall+1)%n][2]-poly.points[wall][2])
            h=((poly.points[(wall+1)%n][0]-poly.points[wall][0])/size,
               (poly.points[(wall+1)%n][1]-poly.points[wall][1])/size,
               (poly.points[(wall+1)%n][2]-poly.points[wall][2])/size)
            r=((roofpts[(wall+1)%n][0]-roofpts[wall][0])/size,
               (roofpts[(wall+1)%n][1]-roofpts[wall][1])/size,
               (roofpts[(wall+1)%n][2]-roofpts[wall][2])/size)
            (horiz,hscale)=subdiv(size, fac.hscale, fac.horiz, fac.hends,False)
            cumheight=0
            for i in range(len(vert)-1):
                heightinc=fac.vscale*(fac.vert[vert[i]][1]-fac.vert[vert[i]][0])
                cumwidth=0
                for j in range(len(horiz)):
                    widthinc=hscale*(fac.horiz[horiz[j]][1]-fac.horiz[horiz[j]][0])
                    poly.quads.append((poly.points[wall][0]+h[0]*cumwidth,
                                       poly.points[wall][1]+h[1]*cumwidth+cumheight,
                                       poly.points[wall][2]+h[2]*cumwidth,
                                       fac.horiz[horiz[j]][0],
                                       fac.vert[vert[i]][0]))
                    poly.quads.append((poly.points[wall][0]+h[0]*cumwidth,
                                       poly.points[wall][1]+h[1]*cumwidth+cumheight+heightinc,
                                       poly.points[wall][2]+h[2]*cumwidth,
                                       fac.horiz[horiz[j]][0],
                                       fac.vert[vert[i]][1]))
                    poly.quads.append((poly.points[wall][0]+h[0]*(cumwidth+widthinc),
                                       poly.points[wall][1]+h[1]*(cumwidth+widthinc)+cumheight+heightinc,
                                       poly.points[wall][2]+h[2]*(cumwidth+widthinc),
                                       fac.horiz[horiz[j]][1],
                                       fac.vert[vert[i]][1]))
                    poly.quads.append((poly.points[wall][0]+h[0]*(cumwidth+widthinc),
                                       poly.points[wall][1]+h[1]*(cumwidth+widthinc)+cumheight,
                                       poly.points[wall][2]+h[2]*(cumwidth+widthinc),
                                       fac.horiz[horiz[j]][1],
                                       fac.vert[vert[i]][0]))
                    cumwidth+=widthinc
                cumheight+=heightinc
            # penthouse
            cumwidth=0
            for j in range(len(horiz)):
                if not len(vert): continue
                widthinc=hscale*(fac.horiz[horiz[j]][1]-fac.horiz[horiz[j]][0])
                poly.quads.append((poly.points[wall][0]+h[0]*cumwidth,
                                   poly.points[wall][1]+h[1]*cumwidth+cumheight,
                                   poly.points[wall][2]+h[2]*cumwidth,
                                   fac.horiz[horiz[j]][0],
                                   fac.vert[vert[-1]][0]))
                poly.quads.append((roofpts[wall][0]+r[0]*cumwidth,
                                   roofpts[wall][1]+r[1]*cumwidth,
                                   roofpts[wall][2]+r[2]*cumwidth,
                                   fac.horiz[horiz[j]][0],
                                   fac.vert[vert[-1]][1]))
                poly.quads.append((roofpts[wall][0]+r[0]*(cumwidth+widthinc),
                                   roofpts[wall][1]+r[1]*(cumwidth+widthinc),
                                   roofpts[wall][2]+r[2]*(cumwidth+widthinc),
                                   fac.horiz[horiz[j]][1],
                                   fac.vert[vert[-1]][1]))
                poly.quads.append((poly.points[wall][0]+h[0]*(cumwidth+widthinc),
                                   poly.points[wall][1]+h[1]*(cumwidth+widthinc)+cumheight,
                                   poly.points[wall][2]+h[2]*(cumwidth+widthinc),
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
        (x,z)=self.latlon2m(poly.lat,poly.lon)
        y=self.vertexcache.height(self.tile,self.options,x,z)+roofheight
        poly.roof=[(x, y, z,
                    fac.roof[0][0] + (x-minx)*xscale,
                    fac.roof[0][1] + (z-minz)*zscale)]
        if n<=4:
            for i in range(len(roofpts)-1, -1, -1):
                poly.roof.append((roofpts[i][0], roofpts[i][1], roofpts[i][2],
                                  fac.roof[3-i][0], fac.roof[3-i][1]))
            return
        for i in range(len(roofpts)-1, -1, -1):
            poly.roof.append((roofpts[i][0], roofpts[i][1], roofpts[i][2],
                              fac.roof[0][0] + (roofpts[i][0]-minx)*xscale,
                              fac.roof[0][1] + (roofpts[i][2]-minz)*zscale))
            

