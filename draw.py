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
from sys import exit, platform, maxint, version
#import time
import wx
import wx.glcanvas

from files import VertexCache, sortfolded
from clutter import Polygon, resolution, maxres, round2res
from clutterdef import ClutterDef
from MessageBox import myMessageBox
from prefs import Prefs
from version import appname

onedeg=1852*60	# 1 degree of longitude at equator (60nm) [m]
d2r=pi/180.0
twopi=pi+pi
f2m=0.3041	# 1 foot [m] (not accurate, but what X-Plane appears to use)

sband=12	# width of mouse scroll band around edge of window

runwaycolour=(0.333,0.333,0.333)

debugapt=False	# XXX

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
        self.data=data		# [(layer, idx, placement)]

    def equals(self, other):
        # ignore placement details
        if self.tile!=other.tile or self.kind!=other.kind: return False
        if self.data==other.data==None: return True
        if not (self.data and other.data and len(self.data)==len(other.data)):
            return False
        for i in range(len(self.data)):
            if self.data[i][0]!=other.data[i][0] or self.data[i][1]!=other.data[i][1]:
                return False
        return True


class ClickModes:
    Undecided=1
    DragBox=2
    Drag=3
    DragNode=4
    Scroll=5
    

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
        self.airports={}	# [(lat,lon,hdg,length,width)] by code
        self.runways={}		# diplay list by tile
        self.navaids=[]		# (type, lat, lon, hdg)
        #self.objects={}		# [(name,lat,lon,hdg,height)] by tile
        #self.polygons={}	# [(name, parameter, [windings])] by tile
        self.lookup={}		# virtual name -> filename (may be duplicates)
        self.defs={}		# loaded ClutterDefs by filename
        self.placements={}	# [[Clutter]] by tile
        self.unsorted={}	# [Clutter] by tile
        self.clutterlist=0
        self.background=None
        self.meshlist=0
        
        self.mousenow=None	# Current position (used in timer and drag)
        self.picklist=0
        self.selected=[]	# selected placements
        self.clickmode=None
        self.clickpos=None	# Location of mouse down
        self.clickctrl=False	# Ctrl was held down
        self.selectednode=None	# Selected node
        self.selections=[]	# List for picking
        self.selectsaved=None	# Selection at start of ctrl drag box
        self.draginert=True
        self.dragx=wx.SystemSettings_GetMetric(wx.SYS_DRAG_X)
        self.dragy=wx.SystemSettings_GetMetric(wx.SYS_DRAG_Y)

        self.undostack=[]

        # Values during startup
        self.x=0
        self.y=0
        self.z=0
        self.h=0
        self.e=90
        self.d=3333.25
        self.cliprat=1000
        self.polyhack=# 1 #256	# XXX

        self.context=wx.glcanvas.GLContext

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
            # Failed - try with default depth buffer
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
        #print "Canvas Init"
        # Setup state. Under X must be called after window is shown
        self.SetCurrent()
        #glClearDepth(1.0)
        glDepthFunc(GL_LESS)
        glEnable(GL_DEPTH_TEST)
        glShadeModel(GL_SMOOTH)
        glEnable(GL_LINE_SMOOTH)
        glLineWidth(2.0)
        #if debugapt: glLineWidth(2.0)
        #glLineStipple(1, 0x0f0f)	# for selection drag
        glPointSize(4.0)		# for nodes
        glFrontFace(GL_CW)
        glCullFace(GL_BACK)
        glPixelStorei(GL_UNPACK_ALIGNMENT,1)	# byte aligned
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
        if self.clickmode:
            event.Skip()
        else:
            # Manually propagate
            self.frame.OnKeyDown(event)

    def OnMouseWheel(self, event):
        if self.clickmode:
            event.Skip()
        else:
            # Manually propagate
            self.frame.OnMouseWheel(event)

    def OnTimer(self, event):
        # mouse scroll - fake up a key event and pass it up
        size=self.GetClientSize()
        posx=self.mousenow[0]
        posy=self.mousenow[1]
        keyevent=wx.KeyEvent()
        keyevent.m_shiftDown=wx.GetKeyState(wx.WXK_SHIFT)
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
        self.mousenow=self.clickpos=[event.m_x,event.m_y]
        self.draginert=True
        self.clickctrl=event.m_controlDown
        self.CaptureMouse()
        size = self.GetClientSize()
        if event.m_x<sband or event.m_y<sband or size.x-event.m_x<sband or size.y-event.m_y<sband:
            # mouse scroll
            self.clickmode=ClickModes.Scroll
            self.timer.Start(50)
        else:
            self.clickmode=ClickModes.Undecided
            self.select()

    def OnLeftUp(self, event):
        print "up", ClickModes.DragNode
        if self.HasCapture(): self.ReleaseMouse()
        self.timer.Stop()
        if self.clickmode==ClickModes.DragNode:
            self.selectednode=self.selected[0].layout(self.tile, self.options, self.vertexcache, self.selectednode)
            self.trashlists(True)	# recompute obj and pick lists
            self.SetCursor(wx.NullCursor)
        elif self.clickmode==ClickModes.Drag:
            for thing in self.selected:
                thing.layout(self.tile, self.options, self.vertexcache)
            self.trashlists(True)	# recompute obj and pick lists
        elif self.clickmode==ClickModes.DragBox:
            self.trashlists()		# selection changed
        self.clickmode=None
        self.Refresh()	# get rid of drag box
        event.Skip()
            
    def OnIdle(self, event):
        if self.valid:	# can get Idles during reload under X
            if self.clickmode==ClickModes.DragNode:
                self.selectednode=self.selected[0].layout(self.tile, self.options, self.vertexcache, self.selectednode)
                self.Refresh()
            elif not self.clickmode and not self.picklist:
                # no update during node drag since will have to be recomputed
                self.prepareselect()
        event.Skip()

    def OnMouseMotion(self, event):
        if self.clickmode and not event.LeftIsDown():
            # Capture unreliable on Mac, so may have missed LeftUp event. See
            # https://sourceforge.net/tracker/?func=detail&atid=109863&aid=1489131&group_id=9863
            self.OnLeftUp(event)
            return

        if self.timer.IsRunning():
            # Continue mouse scroll
            self.mousenow=[event.m_x,event.m_y]		# not known in timer
            return

        if not self.clickmode:
            size = self.GetClientSize()
            
            # Change cursor if over a window border
            if event.m_x<sband or event.m_y<sband or size.x-event.m_x<sband or size.y-event.m_y<sband:
                self.SetCursor(self.movecursor)
                return

            # Change cursor if over a node
            if len(self.selected)==1 and isinstance(self.selected[0], Polygon):
                glViewport(0, 0, *size)
                glMatrixMode(GL_PROJECTION)
                glPushMatrix()
                glLoadIdentity()
                viewport=glGetIntegerv(GL_VIEWPORT)
                gluPickMatrix(event.m_x,
                              size[1]-1-event.m_y, 5,5,
                              (0, 0, size[0], size[1]))
                glOrtho(-self.d, self.d,
                        -self.d*size.y/size.x, self.d*size.y/size.x,
                        -self.d*self.cliprat, self.d*self.cliprat)
                glMatrixMode(GL_MODELVIEW)
                glSelectBuffer(65536)	# = 16384 selections?
                glRenderMode(GL_SELECT)
                glInitNames()
                glPushName(0)
                self.selected[0].picknodes()
                selections=glRenderMode(GL_RENDER)
                # Restore state for unproject
                glMatrixMode(GL_PROJECTION)
                glPopMatrix()	
                glMatrixMode(GL_MODELVIEW)
                if selections:
                    self.SetCursor(self.dragcursor)	# hovering over node
                    return
                
            self.SetCursor(wx.NullCursor)
            return

        assert (self.clickmode!=ClickModes.Undecided)

        if self.draginert and abs(event.m_x-self.clickpos[0])<self.dragx and abs(event.m_y-self.clickpos[1])<self.dragx:
            return
        else:
            self.draginert=False
            
        if self.clickmode==ClickModes.DragNode:
            # Start/continue node drag
            self.SetCursor(self.dragcursor)
            poly=self.selected[0]
            (lat,lon)=self.getworldloc(event.m_x, event.m_y)
            lat=max(self.tile[0], min(self.tile[0]+maxres, lat))
            lon=max(self.tile[1], min(self.tile[1]+maxres, lon))
            layer=poly.definition.layer
            newundo=UndoEntry(self.tile, UndoEntry.MOVE, [(layer, self.currentplacements()[layer].index(poly), poly.clone())])
            if not (self.undostack and self.undostack[-1].equals(newundo)):
                self.undostack.append(newundo)
                self.frame.toolbar.EnableTool(wx.ID_SAVE, True)
                self.frame.toolbar.EnableTool(wx.ID_UNDO, True)
                if self.frame.menubar:
                    self.frame.menubar.Enable(wx.ID_SAVE, True)
                    self.frame.menubar.Enable(wx.ID_UNDO, True)
            self.selectednode=poly.updatenode(self.selectednode, lat, lon, self.tile, self.options, self.vertexcache)
            self.Refresh()	# show updated node
            self.frame.ShowSel()
            return

        elif self.clickmode==ClickModes.Drag:
            # Continue move drag
            (lat,lon)=self.getworldloc(event.m_x, event.m_y)
            if (lat>self.tile[0] and lat<self.tile[0]+maxres and
                lon>self.tile[1] and lon<self.tile[1]+maxres):
                (oldlat,oldlon)=self.getworldloc(*self.mousenow)
                self.movesel(lat-oldlat, lon-oldlon, 0)
                self.frame.toolbar.EnableTool(wx.ID_SAVE, True)
                self.frame.toolbar.EnableTool(wx.ID_UNDO, True)
                if self.frame.menubar:
                    self.frame.menubar.Enable(wx.ID_SAVE, True)
                    self.frame.menubar.Enable(wx.ID_UNDO, True)
            
        elif self.clickmode==ClickModes.DragBox:
            self.select()

        self.mousenow=[event.m_x,event.m_y]		# not known in paint


    def OnPaint(self, event):
        #print "Canvas Paint"
        #print "paint", self.selected
        dc = wx.PaintDC(self)	# Tell the window system that we're on the case
        size = self.GetClientSize()
        if size.width<=0: return	# may be junk on startup
        self.SetCurrent()
        self.SetFocus()		# required for GTK
        
        glMatrixMode(GL_PROJECTION)
        glViewport(0, 0, size.width, size.height)
        glLoadIdentity()
	# try to minimise near offset to improve clipping
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
            glClearColor(0.5, 0.5, 1.0, 0.0)	# Sky
            glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT)
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

        self.vertexcache.realize(self)

        # Ground terrain
        if not self.meshlist:
            self.meshlist=glGenLists(1)
            glNewList(self.meshlist, GL_COMPILE)
            if debugapt: glPolygonMode(GL_FRONT, GL_LINE)
            glEnable(GL_DEPTH_TEST)
            glEnable(GL_CULL_FACE)
            glDepthMask(GL_TRUE)
            glDisable(GL_POLYGON_OFFSET_FILL)
            if not self.options&Prefs.ELEVATION:
                glPushMatrix()
                glScalef(1,0,1)		# Defeat elevation data
            glColor3f(0.8, 0.8, 0.8)	# Unpainted
            polystate=0
            for (base,number,texno,poly) in self.vertexcache.getMesh(self.tile,self.options):
                if poly:		# eg overlaid photoscenery
                    if polystate!=poly:
                        glDepthMask(GL_FALSE)	# offset mustn't update depth
                        glEnable(GL_POLYGON_OFFSET_FILL)
                        glPolygonOffset(-10*poly, -10*self.polyhack*poly)
                    polystate=poly
                else:
                    if polystate:
                        glDepthMask(GL_TRUE)
                        glDisable(GL_POLYGON_OFFSET_FILL)
                    polystate=0
                glBindTexture(GL_TEXTURE_2D, texno)
                glDrawArrays(GL_TRIANGLES, base, number)
            glDepthMask(GL_TRUE)
            if not self.options&Prefs.ELEVATION:
                glPopMatrix()
            if debugapt: glPolygonMode(GL_FRONT, GL_FILL)
            glEndList()
        glCallList(self.meshlist)

        # Objects and Polygons
        placements=self.currentplacements()
        if not self.clutterlist:
            print "list"
            self.clutterlist=glGenLists(1)
            glNewList(self.clutterlist, GL_COMPILE)
            glDisable(GL_POLYGON_OFFSET_FILL)

            # Generic polygons need to show through terrain
            #glDisable(GL_DEPTH_TEST)
            #print 0, placements[0]
            for placement in placements[0]:
                if self.clickmode==ClickModes.DragBox or not placement in self.selected:
                    placement.draw(False, False, None)

            glColor3f(0.8, 0.8, 0.8)	# Unpainted
            #glEnable(GL_DEPTH_TEST)
            for layer in range(1,ClutterDef.LAYERCOUNT):
                if layer==ClutterDef.RUNWAYSLAYER:
                    # Runways
                    key=(self.tile[0],self.tile[1],self.options&Prefs.ELEVATION)
                    if key in self.runways: glCallList(self.runways[key])

                #print layer, placements[layer]
                for placement in placements[layer]:
                    if self.clickmode==ClickModes.DragBox or not placement in self.selected:
                        placement.draw(False, False, None)

            glEndList()
        glCallList(self.clutterlist)

        # Overlays
        glDisable(GL_POLYGON_OFFSET_FILL)
        glDisable(GL_DEPTH_TEST)

        # Background
        if self.background:
            (image, lat, lon, hdg, width, length, opacity, height)=self.background
            if [int(floor(lat)),int(floor(lon))]==self.tile:
                texno=self.vertexcache.texcache.get(image, False, False, True)
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
        glColor3f(1.0, 0.5, 1.0)
        glDisable(GL_CULL_FACE)
        glEnable(GL_DEPTH_TEST)
        if len(self.selected)==1:
            selone=True
        else:
            selone=False
        for placement in self.selected:
            placement.draw(True, selone, self.selectednode)
        glEnable(GL_CULL_FACE)
        glEnable(GL_DEPTH_TEST)

	# drag box
        if self.clickmode==ClickModes.DragBox:
            #print "drag"
            glColor3f(0.25, 0.125, 0.25)
            glDisable(GL_TEXTURE_2D)
            glMatrixMode(GL_PROJECTION)
            glPushMatrix()
            glLoadIdentity()
            glMatrixMode(GL_MODELVIEW)
            glPushMatrix()
            glLoadIdentity()
            x0=float(self.clickpos[0]*2)/size.x-1
            y0=1-float(self.clickpos[1]*2)/size.y
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

        glClearColor(0.5, 0.5, 1.0, 0.0)	# Sky
        glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT)


    def prepareselect(self):
        # Pre-prepare selection list - assumes self.picklist==0
        print "prep"
        self.picklist=glGenLists(1)
        glNewList(self.picklist, GL_COMPILE)
        glInitNames()
        glPushName(0)
        glDisable(GL_TEXTURE_2D)
        glDisable(GL_DEPTH_TEST)
        glDisable(GL_CULL_FACE)
        placements=self.currentplacements()
        for i in range(len(placements)):
            for j in range(len(placements[i])):
                glLoadName((i<<24)+j)
                placements[i][j].draw(True, True, None)
        glEnable(GL_DEPTH_TEST)
        glEndList()

            
    def select(self):
        #print "sel", 
        #if not self.currentobjects():
        #    self.selections=[]	# Can't remember

        size = self.GetClientSize()
        glViewport(0, 0, *size)
        glMatrixMode(GL_PROJECTION)
        glPushMatrix()
        glLoadIdentity()
        viewport=glGetIntegerv(GL_VIEWPORT)
        if self.clickmode==ClickModes.DragBox:
            # maths goes wrong if zero-sized box
            if self.clickpos[0]==self.mousenow[0]: self.mousenow[0]+=1
            if self.clickpos[1]==self.mousenow[1]: self.mousenow[1]-=1
            gluPickMatrix((self.clickpos[0]+self.mousenow[0])/2,
                          size[1]-1-(self.clickpos[1]+self.mousenow[1])/2,
                          abs(self.clickpos[0]-self.mousenow[0]),
                          abs(self.clickpos[1]-self.mousenow[1]),
                          (0, 0, size[0], size[1]))
        else:	# at point
            gluPickMatrix(self.clickpos[0],
                          size[1]-1-self.clickpos[1], 5,5,
                          (0, 0, size[0], size[1]))
        glOrtho(-self.d, self.d,
                -self.d*size.y/size.x, self.d*size.y/size.x,
                -self.d*self.cliprat, self.d*self.cliprat)
        glMatrixMode(GL_MODELVIEW)

        placements=self.currentplacements()
        if not self.picklist: self.prepareselect()
        glSelectBuffer(65536)	# = 16384 selections?
        glRenderMode(GL_SELECT)
        glCallList(self.picklist)
        selections=[]
        try:
            for min_depth, max_depth, (names,) in glRenderMode(GL_RENDER):
                selections.append(placements[int(names)>>24][int(names)&0xffffff])
        except:	# overflow
            pass

        # Select poly node?
        self.selectednode=None
        if self.clickmode==ClickModes.Undecided:
            if len(self.selected)==1 and isinstance(self.selected[0], Polygon) and self.selected[0] in selections:
                trysel=self.selected[0]
            elif len(selections)==1 and isinstance(selections[0], Polygon):
                trysel=selections[0]
            else:
                trysel=None
            if trysel:
                print "selnodes",
                # First look for nodes in same polygon
                glSelectBuffer(65536)	# = 16384 selections?
                glRenderMode(GL_SELECT)
                glInitNames()
                glPushName(0)
                trysel.picknodes()
                selectnodes=[]
                try:
                    for min_depth, max_depth, (names,) in glRenderMode(GL_RENDER):
                        selectnodes.append((int(names)>>8, int(names)&0xff))
                except:	# overflow
                    pass
                print selectnodes
                if selectnodes:
                    self.clickmode=ClickModes.DragNode
                    self.selected=[trysel]
                    self.selectednode=selectnodes[0]
            
        # Restore state for unproject
        glMatrixMode(GL_PROJECTION)
        glPopMatrix()	
        glMatrixMode(GL_MODELVIEW)

        if self.selectednode:
            return

        if self.clickmode==ClickModes.DragBox:	# drag - add or remove all
            if self.clickctrl:
                self.selected=list(self.selectsaved)	# reset each time
                for i in selections:
                    if not i in self.selected:
                        self.selected.append(i)
                    else:
                        self.selected.remove(i)
            else:
                self.selected=list(selections)
        else:			# click - Add or remove one
            if not selections:
                self.clickmode=ClickModes.DragBox
                self.selectsaved=self.selected
            else:
                self.clickmode=ClickModes.Drag
            self.trashlists()	# selection changes
            if self.clickctrl:
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

    def currentplacements(self):
        return self.placements[(self.tile[0],self.tile[1])]
    
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
            wx.MessageBox("Can't read %s." % name, 'Cannot add this object.',
                          wx.ICON_ERROR|wx.OK, self.frame)
            return False
        self.trashlists(self.selected)
        thing=self.vertexcache.get(name)
        if self.selectednode!=None:
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
            (base,culled,nocull,texno,poly,bsize)=thing	# for poly
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

    def movesel(self, dlat, dlon, dhdg=0, dparam=0):
        # returns True if changed something
        if not self.selected: return False
        if not self.clickmode: self.trashlists(True)
        moved=[]
        for thing in self.selected:
            layer=thing.definition.layer
            moved.append((layer, self.currentplacements()[layer].index(thing), thing.clone()))
            if self.selectednode:
                self.selectednode=thing.movenode(self.selectednode, dlat, dlon, self.tile, self.options, self.vertexcache)
                assert self.selectednode
            else:
                thing.move(dlat, dlon, dhdg, dparam, self.tile, self.options, self.vertexcache)
        self.Refresh()
        self.frame.ShowSel()

        newundo=UndoEntry(self.tile, UndoEntry.MOVE, moved)
        if not (self.undostack and self.undostack[-1].equals(newundo)):
            self.undostack.append(newundo)

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
        self.trashlists(True)
        self.Refresh()
        self.frame.ShowSel()
        return True

    def undo(self):
        # returns True if undostack still not empty
        if not self.undostack: return False	# can't happen
        undo=self.undostack.pop()
        if (undo.tile[0],undo.tile[1]) in self.objects:
            objects=self.objects[undo.tile[0],undo.tile[1]]
        if (undo.tile[0],undo.tile[1]) in self.polygons:
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
        if self.selected:
            self.Refresh()
        self.selected=[]
        self.selectednode=None
        self.trashlists()	# selection changed

    def allsel(self, withctrl):
        # fake up mouse drag
        self.selectanchor=[0,0]
        self.selectctrl=withctrl
        size=self.GetClientSize()
        self.mousenow=[size.x-1,size.y-1]
        self.select()
        self.selectanchor=None
        self.trashlists()	# selection changed

    def nextsel(self, name, withctrl):
        loc=None
        self.trashlists()	# selection changed
        # we have 0 or more items of the same type selected
        if not self.vertexcache.load(name):
            thing=None	# can't load
        else:
            thing=self.vertexcache.get(name)
        if isinstance(thing, tuple) or not thing:
            objects=self.currentobjects()
            start=-1
            for i in self.selected:
                if not i&MSKSEL and objects[i].name==name: start=i
            for i in range(start+1, len(objects)+start+1):
                if objects[i%len(objects)].name==name:
                    i=i%len(objects)
                    if withctrl:
                        if i in self.selected:
                            self.selected.remove(i)
                        else:
                            self.selected.append(i)
                    else:
                        self.selected=[i]
                    loc=(objects[i].lat, objects[i].lon)
                    break
        else:
            polygons=self.currentpolygons()
            start=-1
            for i in self.selected:
                if polygons[i&MSKPOLY].name==name: start=i&MSKPOLY
            for i in range(start+1, len(polygons)+start+1):
                if polygons[i%len(polygons)].name==name:
                    i=i%len(polygons)
                    if withctrl:
                        if (i|MSKSEL) in self.selected:
                            self.selected.remove(i|MSKSEL)
                        else:
                            self.selected.append(i|MSKSEL)
                    else:
                        self.selected=[i|MSKSEL]
                    loc=(polygons[i].lat, polygons[i].lon)
                    break
        self.selectednode=None
        self.frame.ShowSel()
        return loc

    def getsel(self):
        # return current selection, or average
        if not self.selected: return ([], '', None, None, None)

        if len(self.selected)==1:
            thing=self.selected[0]
            if isinstance(thing, Polygon):
                return ([thing.name], thing.locationstr(self.selectednode), thing.lat, thing.lon, None)
            else:
                return ([thing.name], thing.locationstr(), thing.lat, thing.lon, thing.hdg)
        else:
            lat=lon=0
            names=[]
            for thing in self.selected:
                names.append(thing.name)
                (tlat,tlon)=thing.location()
                lat+=tlat
                lon+=tlon
            lat/=len(self.selected)
            lon/=len(self.selected)
            return (names, "Lat: %-10.6f  Lon: %-11.6f  (%d objects)" % (lat, lon, len(self.selected)), lat, lon, None)

    def getheight(self):
        # return current height
        return self.y

    def reload(self, reload, options, airports, navaids,
               lookup, placements,
               background, terrain, dsfdirs):
        self.valid=False
        self.options=options
        self.airports=airports	# [runways] by tile
        self.navaids=navaids
        self.lookup=lookup
        self.defs={}
        self.vertexcache.reset(terrain, dsfdirs)
        self.trashlists(True, True)
        self.tile=[0,999]	# force reload on next goto

        for key in self.runways.keys():	# need to re-layout runways
            glDeleteLists(self.runways.pop(key), 1)

        if placements!=None:
            self.placements={}
            self.unsorted=placements

        # force polygons to recompute XXX
        #for polygons in self.polygons.values():
        #    for poly in polygons:
        #        poly.points=[]

        if background:
            (image, lat, lon, hdg, width, length, opacity)=background
            self.background=(image, lat, lon, hdg, width, length, opacity,None)
        else:
            self.background=None
        self.undostack=[]	# layers might have changed
        self.selected=[]	# may not have same indices in new list
        self.selectednode=None

        if __debug__:
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
            # flush all array allocations
            for Def in self.defs.values(): Def.flush()
            self.selections=[]
            self.trashlists(True, True)

            progress=wx.ProgressDialog('Loading', 'Terrain', 17, self, wx.PD_APP_MODAL)
            self.vertexcache.loadMesh(newtile, options)

            progress.Update(1, 'Terrain textures')
            self.vertexcache.getMesh(newtile, options)	# allocates into array

            progress.Update(2, 'Mesh')
            self.vertexcache.getMeshdata(newtile, options)

            # Limit progress dialog to 10 updates
            #clock=time.clock()	# Processor time
            
            # load placements and assign to layers
            key=(newtile[0],newtile[1])
            if key in self.placements:
                placements=reduce(lambda x,y: x+y, self.placements.pop(key))
                if options!=self.options:
                    # invalidate all heights
                    for placement in placements:
                        placement.clearlayout()
            elif key in self.unsorted:
                placements=self.unsorted.pop(key)
            else:
                placements=[]
            self.options=options
            self.placements[key]=[[] for i in range(ClutterDef.LAYERCOUNT)]

            p=len(placements)/10+1
            n=0
            i=0
            for i in range(len(placements)):
                if i==n:
                    progress.Update(3+i/p, 'Objects')
                    n+=p
                placement=placements[i]

                # Silently correct virtual names' cases
                if placement.name not in self.lookup:
                    for existing in self.lookup.keys():
                        if placement.name.lower()==existing.lower():
                            placement.name=existing
                            break

                if not placement.load(self.lookup, self.defs, self.vertexcache, True):
                    errobjs.append(placement.name)
                placement.layout(newtile, options, self.vertexcache)
                self.placements[key][placement.definition.layer].append(placement)
            #print "%s CPU time" % (time.clock()-clock)

            # Lay out runways
            progress.Update(13, 'Runways')
            key=(newtile[0],newtile[1],options&Prefs.ELEVATION)
            if key not in self.runways:
                airports=[]
                pavements=[]
                # Find bounding boxes of airport runways in this tile
                if not (newtile[0],newtile[1]) in self.airports:
                    self.airports[(newtile[0],newtile[1])]=[]
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
                if debugapt:
                    glColor3f(0.5,0.5,0.5)
                else:
                    glColor3f(*runwaycolour)
                glDisable(GL_TEXTURE_2D)
                glPolygonOffset(-10, -100*self.polyhack)	# Stupid value cos not coplanar
                glEnable(GL_POLYGON_OFFSET_FILL)
                if debugapt: glPolygonMode(GL_FRONT, GL_LINE)
                glEnable(GL_CULL_FACE)
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
                    # gluTessProperty(tessObj, GLU_TESS_WINDING_RULE, GLU_TESS_WINDING_NONZERO)	# XXX
                    #if debugapt: gluTessProperty(tessObj,GLU_TESS_BOUNDARY_ONLY,GL_TRUE)
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
                            last=None
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
                                    points=[self.bez(cpoints, u/8.0) for u in range(8)]	# X-Plane stops at or before 8
                                for pt in points:
                                    if pt==last: continue
                                    last=pt
                                    (x,z)=self.latlon2m(*pt)
                                    y=self.vertexcache.height(newtile,options,x,z)
                                    pt3=[x,y,z]
                                    if debugapt and i:
                                        gluTessVertex(tessObj, pt3,
                                                      (pt3, (0,0,0)))
                                    else:
                                        gluTessVertex(tessObj, pt3,
                                                      (pt3, runwaycolour))
                            if not oldtess:
                                gluTessEndContour(tessObj)
                        if oldtess:
                            gluEndPolygon(tessObj)
                        else:
                            gluTessEndPolygon(tessObj)
                    except GLUerror, e:
                        pass
                gluDeleteTess(tessObj)
                if debugapt: glPolygonMode(GL_FRONT, GL_FILL)
                
                progress.Update(14, 'Navaids')
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
                      181:'lib/airport/beacons/beacon_airport.obj',
                      182:'lib/airport/beacons/beacon_seaport.obj',
                      183:'lib/airport/beacons/beacon_heliport.obj',
                      184:'lib/airport/beacons/beacon_mil.obj',
                      185:'lib/airport/beacons/beacon_airport.obj',
                      211:'lib/airport/lights/slow/VASI.obj',
                      212:'lib/airport/lights/slow/PAPI.obj',
                      213:'lib/airport/lights/slow/PAPI.obj',
                      214:'lib/airport/lights/slow/PAPI.obj',
                      215:'lib/airport/lights/slow/VASI3.obj',
                      216:'lib/airport/lights/slow/rway_guard.obj',
                      }
                #for name in objs.values():
                #    self.vertexcache.load(name, True)	# skip errors
                #self.vertexcache.realize(self)
                glDisable(GL_POLYGON_OFFSET_FILL)
                glDepthMask(GL_TRUE)
                glEnable(GL_CULL_FACE)
                cullstate=True
                glColor3f(0.8, 0.8, 0.8)	# Unpainted
                glEnable(GL_TEXTURE_2D)
                polystate=0
                if 0:#XXX for (i, lat, lon, hdg) in self.navaids:
                    if [int(floor(lat)),int(floor(lon))]==newtile and i in objs:
                        name=objs[i]
                        (base,culled,nocull,texno,poly,bsize)=self.vertexcache.get(name)
                        coshdg=cos(d2r*hdg)
                        sinhdg=sin(d2r*hdg)
                        (x,z)=self.latlon2m(lat,lon)
                        y=self.vertexcache.height(newtile,options,x,z)

                        glBindTexture(GL_TEXTURE_2D, texno)
                        if poly:
                            if polystate!=poly:
                                glPolygonOffset(-1*poly, -1*self.polyhack*poly)
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
            progress.Update(15, 'Done')
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
    
    def tessvertex(self, (vertex, colour)):
        glColor3f(*colour)
        if debugapt:
            glVertex3f(vertex[0], vertex[1]+0.1, vertex[2])
        else:
            glVertex3f(*vertex)

    def tesscombine(self, coords, vertex, weight):
        # vertex = array of (coords),(colour)
        #if not debugapt:
        #    return ((coords[0], coords[1], coords[2]), runwaycolour)

        if weight[2] or vertex[0][0][0]!=vertex[1][0][0] or vertex[0][0][2]!=vertex[1][0][2]:
            if debugapt:
                lat=self.centre[0]-coords[2]/onedeg
                lon=self.centre[1]+coords[0]/(onedeg*cos(d2r*lat))
                print "Combine %.6f %.6f" % (lat, lon)
                for i in range(len(weight)):
                    if not weight[i]: break
                    lat=self.centre[0]-vertex[i][0][2]/onedeg
                    lon=self.centre[1]+vertex[i][0][0]/(onedeg*cos(d2r*lat))
                    print "%.6f %.6f %5.3f" % (lat, lon, weight[i])
            return ((coords[0], coords[1], coords[2]),(1,0.333,0.333))
        else:	# Same point
            colour=[0,0,0]
            for i in range(len(weight)):
                if not weight[i]: break
                colour[0]+=vertex[i][1][0]*weight[i]
                colour[1]+=vertex[i][1][1]*weight[i]
                colour[2]+=vertex[i][1][2]*weight[i]
            return ((coords[0], coords[1], coords[2]),tuple(colour))

    def tessend(self):
        glEnd()

    def bez(self, p, mu):
        # http://local.wasp.uwa.edu.au/~pbourke/curves/bezier/index.html
        mum1=1-mu
        if len(p)==3:
            mu2  = mu*mu
            mum12= mum1*mum1
            return (round(p[0][0]*mum12 + 2*p[1][0]*mum1*mu + p[2][0]*mu2,6),
                    round(p[0][1]*mum12 + 2*p[1][1]*mum1*mu + p[2][1]*mu2,6))
        elif len(p)==4:
            mu3  = mu*mu*mu
            mum13= mum1*mum1*mum1
            return (round(p[0][0]*mum13 + 3*p[1][0]*mu*mum1*mum1 + 3*p[2][0]*mu*mu*mum1 + p[3][0]*mu3,6),
                    round(p[0][1]*mum13 + 3*p[1][1]*mu*mum1*mum1 + 3*p[2][1]*mu*mu*mum1 + p[3][1]*mu3,6))
        else:
            raise ArithmeticError
        
    def trashlists(self, picktoo=False, terraintoo=False):
        # Should be called when selection changed
        # - with picktoo if objects have changed
        # - with terraintoo if vertexcache has been flushed
        #print "i", objectstoo, runwaysandterraintoo
        if terraintoo:
            if self.meshlist: glDeleteLists(self.meshlist, 1)
            self.meshlist=0
        if picktoo:
            if self.picklist: glDeleteLists(self.picklist, 1)
            self.picklist=0
        if self.clutterlist: glDeleteLists(self.clutterlist, 1)
        self.clutterlist=0

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
        mz=glReadPixelsf(mx,my, 1,1, GL_DEPTH_COMPONENT)[0][0]
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

    def snapshot(self, name):
        if not self.vertexcache.load(name, 0): return None
        self.SetCurrent()
        glViewport(0, 0, 300, 300)
        glClearColor(0.3, 0.5, 0.6, 1.0)	# Preview colour
        glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT)
        self.vertexcache.realize(self)
        (base,culled,nocull,texno,poly,bsize)=self.vertexcache.get(name)
        glMatrixMode(GL_PROJECTION)
        glPushMatrix()
        glLoadIdentity()
        maxsize=1.2*bsize
        glOrtho(-maxsize, maxsize, -maxsize/2, maxsize*1.5, -2*maxsize, 2*maxsize)
        glMatrixMode(GL_MODELVIEW)
        glPushMatrix()
        glLoadIdentity()
        glRotatef( 30, 1,0,0)
        glRotatef(-30, 0,1,0)
        glColor3f(0.9, 0.9, 0.9)	# Unpainted
        glEnable(GL_TEXTURE_2D)
        glEnable(GL_DEPTH_TEST)
        glBindTexture(GL_TEXTURE_2D, texno)
        if culled:
            glEnable(GL_CULL_FACE)
            glDrawArrays(GL_TRIANGLES, base, culled)
        if nocull:
            glDisable(GL_CULL_FACE)
            glDrawArrays(GL_TRIANGLES, base+culled, nocull)
        #glFinish()	# redundant
        data=glReadPixels(0,0, 300,300, GL_RGB, GL_UNSIGNED_BYTE)
        img=wx.EmptyImage(300, 300, False)
        img.SetData(data)
        
        # Restore state for unproject & selection
        glPopMatrix()
        glMatrixMode(GL_PROJECTION)
        glPopMatrix()	
        glMatrixMode(GL_MODELVIEW)

        glClearColor(0.5, 0.5, 1.0, 0.0)	# Sky
        glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT)
        return img.Mirror(False)

