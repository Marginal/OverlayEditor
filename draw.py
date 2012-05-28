import OpenGL	# for __version__
from OpenGL.GL import *
from OpenGL.GLU import *
from OpenGL.arrays import vbo
from OpenGL.extensions import alternate
from OpenGL.GL.ARB.occlusion_query import *
glBeginQuery = alternate(glBeginQuery, glBeginQueryARB)
glDeleteQueries = alternate(glDeleteQueries, glDeleteQueriesARB)
glEndQuery = alternate(glEndQuery, glEndQueryARB)
glGenQueries = alternate(glGenQueries, glGenQueriesARB)
glGetQueryObjectuiv = alternate(glGetQueryObjectiv, glGetQueryObjectuivARB)

from math import acos, atan2, cos, sin, floor, hypot, pi, radians
from numpy import array, array_equal, empty, identity, float32, float64, int32
from os.path import basename, join
from struct import unpack
from sys import exit, platform, version
import time
import wx
import wx.glcanvas

if __debug__:
    from traceback import print_exc

from files import VertexCache, sortfolded, readApt, glInitTextureCompressionS3tcEXT
from fixed8x13 import fixed8x13
from clutter import ObjectFactory, PolygonFactory, Draped, Facade, Object, Polygon, Network, Exclude, resolution, round2res, latlondisp
from clutterdef import BBox, ClutterDef, ObjectDef, AutoGenPointDef, COL_CURSOR, COL_SELECTED, COL_UNPAINTED, COL_DRAGBOX, COL_WHITE
from MessageBox import myMessageBox
from prefs import Prefs
from version import appname

onedeg=1852*60	# 1 degree of longitude at equator (60nm) [m]
f2m=0.3041	# 1 foot [m] (not accurate, but what X-Plane appears to use)

sband=16	# width of mouse scroll band around edge of window

debugapt=__debug__ and False


class UndoEntry:
    ADD=0
    DEL=1
    MODIFY=2
    MOVE=3
    def __init__(self, tile, kind, data):
        self.tile=tile
        self.kind=kind
        self.data=data		# [(layer, idx, placement)]

    def equals(self, other):
        # ignore placement details
        if self.tile!=other.tile or not (self.kind==other.kind==UndoEntry.MOVE): return False
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
    Move=6
    

# OpenGL state
class GLstate():
    def __init__(self):
        self.debug=__debug__ and False
        self.use_occlusion_query=bool(glGenQueries)
        self.queries=[]
        glEnableClientState(GL_VERTEX_ARRAY)
        self.texture=0
        glEnableClientState(GL_TEXTURE_COORD_ARRAY)
        self.color=COL_UNPAINTED
        glColor3f(*COL_UNPAINTED)
        glDisableClientState(GL_COLOR_ARRAY)
        self.cull=True
        glEnable(GL_CULL_FACE)
        self.depthtest=True
        glEnable(GL_DEPTH_TEST)
        self.poly=False
        glDisable(GL_POLYGON_OFFSET_FILL)
        glDepthMask(GL_TRUE)
        self.current_vbo=None
        self.instance_vbo=vbo.VBO(None, GL_STATIC_DRAW_ARB)
        self.dynamic_vbo=vbo.VBO(None, GL_STATIC_DRAW_ARB)

    def set_texture(self, id):
        if self.texture!=id:
            if __debug__:
                if self.debug: print "set_texture", id
            if id is None:
                if self.texture is not None:
                    if __debug__:
                        if self.debug: print "set_texture disable GL_TEXTURE_COORD_ARRAY"
                    glDisableClientState(GL_TEXTURE_COORD_ARRAY)
                if self.texture!=0:
                    glBindTexture(GL_TEXTURE_2D, 0)
            else:
                if self.texture is None:
                    if __debug__:
                        if self.debug: print "set_texture enable GL_TEXTURE_COORD_ARRAY"
                    glEnableClientState(GL_TEXTURE_COORD_ARRAY)
                glBindTexture(GL_TEXTURE_2D, id)
            self.texture=id
        elif __debug__:
            if self.debug: print "set_texture already", id

    def set_color(self, color):
        if self.color!=color:
            if color is None:
                # Colors from VBO
                if __debug__:
                    if self.debug: print "set_color None"
                if self.color is not None:
                    if __debug__:
                        if self.debug: print "set_color enable GL_COLOR_ARRAY"
                    glEnableClientState(GL_COLOR_ARRAY)
            else:
                # Color specified explicitly
                if __debug__:
                    if self.debug: print "set_color (%.3f, %.3f. %.3f)" % color
                if self.color is None:
                    if __debug__:
                        if self.debug: print "set_color disable GL_COLOR_ARRAY"
                    glDisableClientState(GL_COLOR_ARRAY)
                glColor3f(*color)
            self.color=color
        elif __debug__:
            if self.debug:
                if self.color is None:
                    print "set_color already None"
                else:
                    print "set_color already (%.3f, %.3f. %.3f)" % color

    def set_depthtest(self, depthtest):
        if self.depthtest!=depthtest:
            if __debug__:
                if self.debug: print "set_depthtest", depthtest
            self.depthtest=depthtest
            if depthtest:
                glEnable(GL_DEPTH_TEST)
            else:
                glDisable(GL_DEPTH_TEST)
        elif __debug__:
            if self.debug: print "set_depthtest already", depthtest

    def set_cull(self, cull):
        if self.cull!=cull:
            if __debug__:
                if self.debug: print "set_cull", cull
            self.cull=cull
            if cull:
                glEnable(GL_CULL_FACE)
            else:
                glDisable(GL_CULL_FACE)
        elif __debug__:
            if self.debug: print "set_cull already", cull

    def set_poly(self, poly):
        if self.poly!=poly:
            if __debug__:
                if self.debug: print "set_poly", poly
            self.poly=poly
            if poly:
                glEnable(GL_POLYGON_OFFSET_FILL)
                glDepthMask(GL_FALSE)	# offset mustn't update depth
            else:
                glDisable(GL_POLYGON_OFFSET_FILL)
                glDepthMask(GL_TRUE)
        elif __debug__:
            if self.debug: print "set_poly already", poly

    def set_instance(self, vertexcache):
        if vertexcache.realize_instance(self.instance_vbo) or self.current_vbo!=self.instance_vbo:
            if __debug__:
                if self.debug: print "set_instance"
            self.instance_vbo.bind()
            vertexcache.realize_instance(self.instance_vbo)
            glTexCoordPointer(2, GL_FLOAT, 20, self.instance_vbo+12)
            glVertexPointer(3, GL_FLOAT, 20, self.instance_vbo)
            self.current_vbo=self.instance_vbo
        elif __debug__:
            if self.debug: print "set_instance already instance_vbo"

    def set_dynamic(self, vertexcache):
        if vertexcache.realize_dynamic(self.dynamic_vbo) or self.current_vbo!=self.dynamic_vbo:
            if __debug__:
                if self.debug: print "set_dynamic"
            self.dynamic_vbo.bind()
            glColorPointer(3, GL_FLOAT, 24, self.dynamic_vbo+12)
            glTexCoordPointer(2, GL_FLOAT, 24, self.dynamic_vbo+12)
            glVertexPointer(3, GL_FLOAT, 24, self.dynamic_vbo)
            self.current_vbo=self.dynamic_vbo
        elif __debug__:
            if self.debug: print "set_dynamic already dynamic_vbo"

    def alloc_queries(self, needed):
        if len(self.queries)<needed:
            if len(self.queries): glDeleteQueries(len(self.queries), self.queries)
            needed=(needed/256+1)*256	# round up
            self.queries=glGenQueries(needed)
            if __debug__:
                if self.debug: print "get_queries", self.queries


# OpenGL Window
class MyGL(wx.glcanvas.GLCanvas):
    def __init__(self, parent, frame):

        self.parent=parent
        self.frame=frame
        self.movecursor=wx.StockCursor(wx.CURSOR_SIZING)
        self.scrollcursor=wx.StockCursor(wx.CURSOR_HAND)
        self.dragcursor=wx.StockCursor(wx.CURSOR_CROSS)

        self.valid=False	# do we have valid data for a redraw?
        self.needclear=False	# pending clear
        self.needrefesh=False	# pending refresh
        self.options=0		# display options
        self.tile=(0,999)	# [lat,lon] of SW
        self.centre=None	# [lat,lon] of centre
        self.airports={}	# [runways] by code
        self.runways={}		# [shoulder/taxiway/runway data] by tile
        self.shoulderdata=None	# indices into cache (base, len)
        self.taxiwaydata=None	# indices into cache (base, len)
        self.runwaysdata=None	# indices into cache (base, len)
        self.navaids=[]		# (type, lat, lon, hdg)
        self.codes={}		# [(code, loc)] by tile
        self.codeslist=0	# airport labels
        self.lookup={}		# virtual name -> filename (may be duplicates)
        self.defs={}		# loaded ClutterDefs by filename
        self.placements={}	# [Clutter] by layer and tile
        self.unsorted={}	# [Clutter] by tile
        self.background=None
        self.meshlist=0
        
        self.mousenow=None	# Current position (used in timer and drag)
        self.locked=0		# locked object types
        self.selected=set()	# selected placements
        self.clickmode=None
        self.clickpos=None	# Location of mouse down
        self.clickctrl=False	# Ctrl was held down
        self.selectednode=None	# Selected node. Only if len(self.selected)==1
        self.selections=set()	# Hits for cycling picking
        self.selectsaved=set()	# Selection at start of ctrl drag box
        self.selectmax=4096	# max 1024 names
        self.draginert=True
        self.dragx=wx.SystemSettings_GetMetric(wx.SYS_DRAG_X)
        self.dragy=wx.SystemSettings_GetMetric(wx.SYS_DRAG_Y)
        if self.dragx<=1 or self.dragx>8 or self.dragy<=1 or self.dragy>8:
            self.dragx=self.dragy=5	# Finder on Mac appears to use 5

        self.clipboard=[]
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

        # Can't use polygon offset in display list on OSX 10.3 or early
        # versions of 10.4. 10.4.8 (Darwin 8.8.1) onwards is OK?
        # Note 10.4 Intel 950 drivers ship with OGL 1.2
        if platform=='darwin':
            from os import uname	# not defined in win32 builds
            ver=uname()[2].split('.')
            self.nopolyosinlist=(int(ver[0])<8 or (int(ver[0])==8 and int(ver[1])<8))
        else:
            self.nopolyosinlist=False

        if wx.VERSION >= (2,9):
            self.context = wx.glcanvas.GLContext(self)

        # Allocate this stuff in glInit
        self.glstate=None
        self.vertexcache=None

        wx.EVT_ERASE_BACKGROUND(self, self.OnEraseBackground)
        wx.EVT_KEY_DOWN(self, self.OnKeyDown)
        wx.EVT_MOUSEWHEEL(self, self.OnMouseWheel)
        wx.EVT_MOTION(self, self.OnMouseMotion)
        wx.EVT_LEFT_DOWN(self, self.OnLeftDown)
        wx.EVT_LEFT_UP(self, self.OnLeftUp)
        wx.EVT_MIDDLE_DOWN(self, self.OnMiddleDown)
        wx.EVT_MIDDLE_UP(self, self.OnMiddleUp)
        wx.EVT_IDLE(self, self.OnIdle)
        #wx.EVT_KILL_FOCUS(self, self.OnKill)	# debug
        
        self.timer=wx.Timer(self, wx.ID_ANY)
        wx.EVT_TIMER(self, self.timer.GetId(), self.OnTimer)

    def glInit(self):
        #print "Canvas Init"
        # Setup state. Under X must be called after window is shown
        if wx.VERSION >= (2,9):
            self.SetCurrent(self.context)
        else:
            self.SetCurrent()

        if not vbo.get_implementation():
            myMessageBox('This application requires the use of OpenGL Vertex Buffer Objects (VBOs) which are not supported by your graphics card.\nTry updating the drivers for your graphics card.',
                         "Can't initialise OpenGL.",
                         wx.ICON_ERROR|wx.OK, self)
            exit(1)
        if not glInitTextureCompressionS3tcEXT():
            myMessageBox('This application requires the use of DXT texture compression which is not supported by your graphics card.\nTry updating the drivers for your graphics card.',
                         "Can't initialise OpenGL.",
                         wx.ICON_ERROR|wx.OK, self)
            exit(1)

        self.vertexcache=VertexCache()	# member so can free resources
        self.glstate=GLstate()

        #glClearDepth(1.0)
        glClearColor(0.5, 0.5, 1.0, 0.0)	# Sky
        glEnable(GL_DEPTH_TEST)
        glDepthFunc(GL_LESS)
        glShadeModel(GL_SMOOTH)
        glEnable(GL_LINE_SMOOTH)
        if debugapt: glLineWidth(2.0)
        #glLineStipple(1, 0x0f0f)		# for selection drag
        glPointSize(4.0)			# for nodes
        glFrontFace(GL_CW)
        glPolygonMode(GL_FRONT, GL_FILL)
        glPolygonOffset(-1, -1)
        glCullFace(GL_BACK)
        glPixelStorei(GL_UNPACK_ALIGNMENT,1)	# byte aligned glBitmap
        glPixelStorei(GL_PACK_ALIGNMENT,1)	# byte aligned glReadPixels
        glReadBuffer(GL_BACK)			# for unproject
        #glPixelStorei(GL_UNPACK_LSB_FIRST,1)
        glEnable(GL_TEXTURE_2D)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        glEnable(GL_BLEND)
        glAlphaFunc(GL_GREATER, 1.0/256)	# discard wholly transparent
        glEnable(GL_ALPHA_TEST)
        glMatrixMode(GL_TEXTURE)
        glTranslatef(0, 1, 0)
        glScalef(1, -1, 1)			# OpenGL textures are backwards
        glMatrixMode(GL_MODELVIEW)
        wx.EVT_PAINT(self, self.OnPaint)	# start generating paint events only now we're set up

    def OnEraseBackground(self, event):
        # Prevent flicker when resizing / painting on MSW
        if __debug__: print "OnEraseBackground"
        self.needclear=True	# ATI drivers require clear afer resize

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
        keyevent.m_controlDown=wx.GetKeyState(wx.WXK_CONTROL)
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
        if self.clickmode==ClickModes.Move: return
        #event.Skip(False)	# don't change focus
        self.mousenow=self.clickpos=[event.GetX(),event.GetY()]
        self.clickctrl=event.CmdDown()
        self.CaptureMouse()
        size = self.GetClientSize()
        if event.GetX()<sband or event.GetY()<sband or size.x-event.GetX()<sband or size.y-event.GetY()<sband:
            # mouse scroll
            self.clickmode=ClickModes.Scroll
            self.timer.Start(50)
        else:
            self.clickmode=ClickModes.Undecided
            self.select()
            self.draginert=True # was (self.clickmode!=ClickModes.DragNode)

    def OnLeftUp(self, event):
        #print "up", ClickModes.DragNode
        if self.HasCapture(): self.ReleaseMouse()
        self.timer.Stop()
        if self.clickmode==ClickModes.DragNode:
            assert len(self.selected)==1
            self.selectednode=list(self.selected)[0].layout(self.tile, self.options, self.vertexcache, self.selectednode)
            self.trashlists(True)	# recompute obj and pick lists
        elif self.clickmode==ClickModes.Drag:
            for placement in self.selected:
                placement.layout(self.tile, self.options, self.vertexcache)
            self.trashlists(True)	# recompute obj and pick lists
        elif self.clickmode==ClickModes.DragBox:
            self.trashlists()		# selection changed
        self.clickmode=None
        self.Refresh()	# get rid of drag box
        event.Skip()

    def OnMiddleDown(self, event):
        if self.clickmode: return
        self.clickmode=ClickModes.Move
        self.mousenow=self.clickpos=[event.GetX(),event.GetY()]
        self.CaptureMouse()
        self.SetCursor(self.movecursor)
        
    def OnMiddleUp(self, event):
        if self.HasCapture(): self.ReleaseMouse()
        self.SetCursor(wx.NullCursor)
        self.clickmode=None
        event.Skip()

    def OnIdle(self, event):
        if self.valid:	# can get Idles during reload under X
            if self.clickmode==ClickModes.DragNode:
                assert len(self.selected)==1
                self.selectednode=list(self.selected)[0].layout(self.tile, self.options, self.vertexcache, self.selectednode)
                assert self.selectednode
                self.Refresh()
            elif self.needrefresh:
                # Mouse motion with a selected polygon draws to the back buffer, which Mac uses as backing store. So refresh.
                self.Refresh()

    def OnMouseMotion(self, event):
        # Capture unreliable on Mac, so may have missed Up events. See
        # https://sourceforge.net/tracker/?func=detail&atid=109863&aid=1489131&group_id=9863
        if self.clickmode==ClickModes.Move:
            if not event.MiddleIsDown():
                self.OnMiddleUp(event)
                return
        elif self.clickmode and not event.LeftIsDown():
            self.OnLeftUp(event)
            return

        if self.timer.IsRunning():
            # Continue mouse scroll
            self.mousenow=[event.GetX(),event.GetY()]		# not known in timer
            return

        if not self.clickmode:
            size = self.GetClientSize()
            
            # Change cursor if over a window border
            if event.GetX()<sband or event.GetY()<sband or size.x-event.GetX()<sband or size.y-event.GetY()<sband:
                self.SetCursor(self.scrollcursor)
                return

            # Change cursor if over a node
            if len(self.selected)==1 and isinstance(list(self.selected)[0], Polygon):
                poly=list(self.selected)[0]
                glMatrixMode(GL_MODELVIEW)
                glLoadIdentity()
                glMatrixMode(GL_PROJECTION)
                glPushMatrix()
                glLoadIdentity()
                gluPickMatrix(event.GetX(),
                              size[1]-1-event.GetY(), 5,5,
                              array([0.0, 0.0, size[0], size[1]],int32))
                glOrtho(-self.d, self.d,
                        -self.d*size.y/size.x, self.d*size.y/size.x,
                        -self.d*self.cliprat, self.d*self.cliprat)
                glRotatef(self.e, 1.0,0.0,0.0)
                glRotatef(self.h, 0.0,1.0,0.0)
                glTranslatef(-self.x, -self.y, -self.z)
                self.glstate.set_texture(0)
                self.glstate.set_color(COL_WHITE)	# Ensure colour indexing off
                self.glstate.set_depthtest(False)	# Don't want to update depth buffer
                self.glstate.set_poly(False)		# Not strictly necessary, but possibly will avoid any driver issues
                if self.glstate.use_occlusion_query:
                    self.glstate.alloc_queries(len([item for sublist in poly.points for item in sublist]))
                    selections=False
                    glColorMask(GL_FALSE,GL_FALSE,GL_FALSE,GL_FALSE)	# Don't want to update frame buffer either
                    poly.pick_nodes(self.glstate)
                    for queryidx in range(len([item for sublist in poly.points for item in sublist])):
                        if glGetQueryObjectuiv(self.glstate.queries[queryidx], GL_QUERY_RESULT):
                            selections=True
                            break
                    glColorMask(GL_TRUE,GL_TRUE,GL_TRUE,GL_TRUE)
                else:
                    glSelectBuffer(self.selectmax)
                    glRenderMode(GL_SELECT)
                    glInitNames()
                    glPushName(0)
                    poly.pick_nodes(self.glstate)
                    selections=glRenderMode(GL_RENDER)

                glPopMatrix()	# Restore state for unproject
                self.needrefresh=True
                if selections:
                    self.SetCursor(self.dragcursor)	# hovering over node
                    return
                
            self.SetCursor(wx.NullCursor)
            return

        assert (self.clickmode!=ClickModes.Undecided)

        if self.clickmode==ClickModes.Move:
            if not self.valid: return
            (oldlat,oldlon)=self.getworldloc(*self.mousenow)
            self.mousenow=[event.GetX(),event.GetY()]
            (lat,lon)=self.getworldloc(*self.mousenow)
            self.frame.loc=(self.frame.loc[0]-lat+oldlat, self.frame.loc[1]-lon+oldlon)
            self.goto(self.frame.loc)
            self.frame.ShowLoc()
            return

        if self.draginert and abs(event.GetX()-self.clickpos[0])<self.dragx and abs(event.GetY()-self.clickpos[1])<self.dragx:
            return
        else:
            self.draginert=False
            
        if self.clickmode==ClickModes.DragNode:
            # Start/continue node drag
            self.SetCursor(self.dragcursor)
            poly=list(self.selected)[0]
            (lat,lon)=self.getworldloc(event.GetX(), event.GetY())
            lat=max(self.tile[0], min(self.tile[0]+1, lat))
            lon=max(self.tile[1], min(self.tile[1]+1, lon))
            layer=poly.definition.layer
            newundo=UndoEntry(self.tile, UndoEntry.MOVE, [(layer, self.placements[self.tile][layer].index(poly), poly.clone())])
            if not (self.undostack and self.undostack[-1].equals(newundo)):
                self.undostack.append(newundo)
                self.frame.toolbar.EnableTool(wx.ID_SAVE, True)
                self.frame.toolbar.EnableTool(wx.ID_UNDO, True)
                if self.frame.menubar:
                    self.frame.menubar.Enable(wx.ID_SAVE, True)
                    self.frame.menubar.Enable(wx.ID_UNDO, True)
            poly.updatenode(self.selectednode, lat, lon, self.tile, self.options, self.vertexcache)
            self.Refresh()	# show updated node
            self.frame.ShowSel()
            return

        elif self.clickmode==ClickModes.Drag:
            # Continue move drag
            (lat,lon)=self.getworldloc(event.GetX(), event.GetY())
            if (lat>self.tile[0] and lat<self.tile[0]+1 and
                lon>self.tile[1] and lon<self.tile[1]+1):
                (oldlat,oldlon)=self.getworldloc(*self.mousenow)
                self.movesel(lat-oldlat, lon-oldlon)
                self.frame.toolbar.EnableTool(wx.ID_SAVE, True)
                self.frame.toolbar.EnableTool(wx.ID_UNDO, True)
                if self.frame.menubar:
                    self.frame.menubar.Enable(wx.ID_SAVE, True)
                    self.frame.menubar.Enable(wx.ID_UNDO, True)
            
        elif self.clickmode==ClickModes.DragBox:
            self.select()

        self.mousenow=[event.GetX(),event.GetY()]		# not known in paint


    def OnPaint(self, event):
        if event: wx.PaintDC(self)	# Tell the window system that we're on the case
        self.needrefresh=False
        size = self.GetClientSize()
        #print "pt", size
        if size.width<=0: return	# may be junk on startup
        if wx.VERSION >= (2,9):
            self.SetCurrent(self.context)
        else:
            self.SetCurrent()
        self.SetFocus()			# required for GTK

        if __debug__: print "OnPaint"

        glMatrixMode(GL_PROJECTION)
        glViewport(0, 0, *size)
        glLoadIdentity()
	# try to minimise near offset to improve clipping
        glOrtho(-self.d, self.d,
                -self.d*size.y/size.x, self.d*size.y/size.x,
                -self.d*self.cliprat, self.d*self.cliprat)
        glRotatef(self.e, 1.0,0.0,0.0)
        glRotatef(self.h, 0.0,1.0,0.0)
        glTranslatef(-self.x, -self.y, -self.z)

        glMatrixMode(GL_MODELVIEW)
        glLoadIdentity()

        # Ground terrain

        if not self.valid:
            # Sea
            glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT)
            glColor3f(0.25, 0.25, 0.50)
            glBindTexture(GL_TEXTURE_2D, 0)
            glBegin(GL_QUADS)
            glVertex3f( onedeg*cos(radians(1+self.tile[0]))/2, 0, -onedeg/2)
            glVertex3f( onedeg*cos(radians(self.tile[0]))/2, 0,  onedeg/2)
            glVertex3f(-onedeg*cos(radians(self.tile[0]))/2, 0,  onedeg/2)
            glVertex3f(-onedeg*cos(radians(1+self.tile[0]))/2, 0, -onedeg/2)
            glEnd()
            self.SwapBuffers()
            glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT)
            self.needclear=False
            return
        elif self.needclear:
            glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT)
            self.needclear=False
        
        if __debug__: clock=time.clock()

        # Static stuff: mesh, networks, navaids
        self.glstate.set_instance(self.vertexcache)
        self.glstate.set_texture(0)
        self.glstate.set_color(COL_UNPAINTED)
        self.glstate.set_cull(True)
        self.glstate.set_depthtest(True)
        self.glstate.set_poly(False)
        glCallList(self.meshlist)

        # Objects and Polygons
        placements=self.placements[self.tile]

        for layer in range(ClutterDef.LAYERCOUNT):
            if placements[layer]:
                self.glstate.set_dynamic(self.vertexcache)
            for placement in placements[layer]:	# XXX Sort by texture / color?
                if not placement in self.selected:
                    placement.draw_dynamic(self.glstate, False, False)
            # pavements
            if layer in [ClutterDef.SHOULDERLAYER, ClutterDef.TAXIWAYLAYER, ClutterDef.RUNWAYSLAYER]:
                data={ClutterDef.SHOULDERLAYER:self.shoulderdata,
                      ClutterDef.TAXIWAYLAYER: self.taxiwaydata,
                      ClutterDef.RUNWAYSLAYER: self.runwaysdata}[layer]
                if data:
                    self.glstate.set_instance(self.vertexcache)
                    (base, length)=data
                    self.glstate.set_texture(self.vertexcache.texcache.get('Resources/surfaces.png'))
                    self.glstate.set_color(COL_UNPAINTED)
                    self.glstate.set_depthtest(True)
                    self.glstate.set_poly(True)
                    if __debug__:
                        if debugapt: glPolygonMode(GL_FRONT, GL_LINE)
                    glDrawArrays(GL_TRIANGLES, base, length)
                    if __debug__:
                        if debugapt: glPolygonMode(GL_FRONT, GL_FILL)

        # Selected dynamic - last so overwrites
        if self.selected:
            self.glstate.set_dynamic(self.vertexcache)
            self.glstate.set_color(COL_SELECTED)
            for layer in range(ClutterDef.LAYERCOUNT):
                for placement in placements[layer]:	# XXX Sort by texture / color?
                    if placement in self.selected:
                        placement.draw_dynamic(self.glstate, True, False)
            if len(self.selected)==1:
                list(self.selected)[0].draw_nodes(self.glstate, self.selectednode)

        # List of clutter with static geometry and sorted by texture (ignoring layer ordering since it doesn't really matter so much for Objects)
        objs=sorted(filter(lambda obj: isinstance(obj, Object), [obj for l in placements for obj in l]), key=lambda obj: obj.definition.texture)
        self.glstate.set_instance(self.vertexcache)
        self.glstate.set_poly(False)
        self.glstate.set_depthtest(True)
        for obj in objs: obj.draw_instance(self.glstate, obj in self.selected, False)

        if __debug__: print "%6.3f time to draw" % (time.clock()-clock)

        # Overlays
        self.glstate.set_poly(False)
        self.glstate.set_depthtest(False)
        self.glstate.set_poly(True)
        glLoadIdentity()	# Drawing Objects alters the matrix

        # Background
        if self.background:
            (image, lat, lon, hdg, width, length, opacity, height)=self.background
            if (int(floor(lat)),int(floor(lon)))==self.tile:
                try:
                    texno=self.vertexcache.texcache.get(image, False, True, False, True)
                    (x,z)=self.latlon2m(lat, lon)
                    glTranslatef(x, height, z)
                    glRotatef(-hdg, 0.0,1.0,0.0)
                    self.glstate.set_texture(texno)
                    glColor4f(1.0, 1.0, 1.0, opacity/100.0)
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
                        self.glstate.set_texture(0)
                        self.glstate.set_color(COL_WHITE)	# ugh force color change
                        self.glstate.set_color(COL_SELECTED)
                        glBegin(GL_LINE_LOOP)
                        glVertex3f(-width/2, 0, length/2)
                        glVertex3f(-width/2, 0,-length/2)
                        glVertex3f( width/2, 0,-length/2)
                        glVertex3f( width/2, 0, length/2)
                        glEnd()
                except:
                    self.setbackground(None)

        # labels
        if self.d>2000:	# arbitrary
            if __debug__: print "labels"
            glCallList(self.codeslist)

        # Position centre
        #if __debug__: print "cursor"
        self.glstate.set_texture(0)
        self.glstate.set_color(COL_CURSOR)
        glTranslatef(self.x, self.y, self.z)
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

	# drag box
        if self.clickmode==ClickModes.DragBox:
            if __debug__: print "drag"
            self.glstate.set_color(COL_DRAGBOX)
            glLoadIdentity()
            glMatrixMode(GL_PROJECTION)
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

        self.glstate.set_poly(False)

        # Display
        self.SwapBuffers()

        glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT)
        self.needclear=False


    def select(self):
        if __debug__: print "sel"
        #if not self.currentobjects():
        #    self.selections=[]	# Can't remember
        if __debug__: clock=time.clock()
        size = self.GetClientSize()
        glMatrixMode(GL_PROJECTION)
        glPushMatrix()
        glLoadIdentity()
        if self.clickmode==ClickModes.DragBox:
            # maths goes wrong if zero-sized box
            if self.clickpos[0]==self.mousenow[0]: self.mousenow[0]+=1
            if self.clickpos[1]==self.mousenow[1]: self.mousenow[1]-=1
            gluPickMatrix((self.clickpos[0]+self.mousenow[0])/2,
                          size[1]-1-(self.clickpos[1]+self.mousenow[1])/2,
                          abs(self.clickpos[0]-self.mousenow[0]),
                          abs(self.clickpos[1]-self.mousenow[1]),
                          array([0.0, 0.0, size[0], size[1]],int32))
        else:	# at point
            gluPickMatrix(self.clickpos[0],
                          size[1]-1-self.clickpos[1], 5,5,
                          array([0.0, 0.0, size[0], size[1]],int32))
        glOrtho(-self.d, self.d,
                 -self.d*size.y/size.x, self.d*size.y/size.x,
                 -self.d*self.cliprat, self.d*self.cliprat)
        glRotatef(self.e, 1.0,0.0,0.0)
        glRotatef(self.h, 0.0,1.0,0.0)
        glTranslatef(-self.x, -self.y, -self.z)
        glMatrixMode(GL_MODELVIEW)
        glLoadIdentity()

        self.glstate.set_texture(0)
        self.glstate.set_color(COL_WHITE)		# Ensure colour indexing off
        self.glstate.set_depthtest(False)		# Don't want to update depth buffer
        self.glstate.set_poly(False)			# Not strictly necessary, but possibly will avoid any driver issues
        self.glstate.set_cull(False)			# Enable selection of "invisible" faces
        placements=self.placements[self.tile]
        checkpolynode=(self.clickmode==ClickModes.Undecided and len(self.selected)==1 and isinstance(list(self.selected)[0], Polygon)) and list(self.selected)[0]

        if self.glstate.use_occlusion_query:
            if checkpolynode:
                queryidx=len([item for sublist in checkpolynode.points for item in sublist])
            else:
                queryidx=0
            needed=queryidx + len([item for sublist in placements for item in sublist])*2	# Twice as many for two-phase drawing
            self.glstate.alloc_queries(needed)
            glColorMask(GL_FALSE,GL_FALSE,GL_FALSE,GL_FALSE)	# Don't want to update frame buffer either

        # Select poly node?
        if checkpolynode:
            #print "selnodes",
            if self.glstate.use_occlusion_query:
                checkpolynode.pick_nodes(self.glstate)
                # We'll check on the status later
            else:
                glSelectBuffer(self.selectmax)
                glRenderMode(GL_SELECT)
                glInitNames()
                glPushName(0)
                checkpolynode.pick_nodes(self.glstate)
                selectnodes=[]
                try:
                    for min_depth, max_depth, (name,) in glRenderMode(GL_RENDER):
                        selectnodes.append((int(name)>>24, int(name)&0xffffff))
                except:	# overflow
                    if __debug__: print_exc()
                if selectnodes:
                    # No need to look further if user has clicked on a node within selected polygon
                    self.clickmode=ClickModes.DragNode
                    self.selectednode=selectnodes[0]

                    # Restore state for unproject
                    glMatrixMode(GL_PROJECTION)
                    glPopMatrix()

                    self.trashlists()	# selection changes
                    self.Refresh()
                    self.frame.ShowSel()
                    return
                else:
                    self.selectednode=None

        # Select placements
        if self.glstate.use_occlusion_query:
            self.glstate.set_instance(self.vertexcache)
            for i in range(len(placements)-1,-1,-1):	# favour higher layers
                for j in range(len(placements[i])):
                    if not placements[i][j].definition.type & self.locked:
                        glBeginQuery(GL_SAMPLES_PASSED, self.glstate.queries[queryidx])
                        placements[i][j].draw_instance(self.glstate, False, True)
                        glEndQuery(GL_SAMPLES_PASSED)
                        queryidx+=1
            self.glstate.set_dynamic(self.vertexcache)
            glLoadIdentity()
            for i in range(len(placements)-1,-1,-1):	# favour higher layers
                for j in range(len(placements[i])):
                    if not placements[i][j].definition.type & self.locked:
                        glBeginQuery(GL_SAMPLES_PASSED, self.glstate.queries[queryidx])
                        placements[i][j].draw_dynamic(self.glstate, False, True)
                        glEndQuery(GL_SAMPLES_PASSED)
                        queryidx+=1

            # First check poly node status
            queryidx=0
            if checkpolynode:
                for i in range(len(checkpolynode.points)):
                    for j in range(len(checkpolynode.points[i])):
                        if not glGetQueryObjectuiv(self.glstate.queries[queryidx], GL_QUERY_RESULT):
                            queryidx+=1
                        else:
                            # No need to look further if user has clicked on a node within selected polygon
                            self.clickmode=ClickModes.DragNode
                            self.selectednode=(i,j)

                            # Restore state for unproject
                            glColorMask(GL_TRUE,GL_TRUE,GL_TRUE,GL_TRUE)
                            glMatrixMode(GL_PROJECTION)
                            glPopMatrix()

                            self.trashlists()	# selection changes
                            self.Refresh()
                            self.frame.ShowSel()
                            return		# Just abandon remaining queries

            # Now check for selections
            self.selectednode=None
            selections=set()
            for k in range(2):
                for i in range(len(placements)-1,-1,-1):
                    for j in range(len(placements[i])):
                        if not placements[i][j].definition.type & self.locked:
                            if placements[i][j] not in selections and glGetQueryObjectuiv(self.glstate.queries[queryidx], GL_QUERY_RESULT):
                                selections.add(placements[i][j])
                            queryidx+=1                            
            glColorMask(GL_TRUE,GL_TRUE,GL_TRUE,GL_TRUE)

        else:	# not self.glstate.use_occlusion_query
            glSelectBuffer(self.selectmax)
            glRenderMode(GL_SELECT)
            glInitNames()
            glPushName(0)

            self.glstate.set_instance(self.vertexcache)
            for i in range(len(placements)-1,-1,-1):	# favour higher layers
                for j in range(len(placements[i])):
                    if not placements[i][j].definition.type & self.locked:
                        glLoadName((i<<24)+j)
                        placements[i][j].draw_instance(self.glstate, False, True)
            self.glstate.set_dynamic(self.vertexcache)
            glLoadIdentity()
            for i in range(len(placements)-1,-1,-1):	# favour higher layers
                for j in range(len(placements[i])):
                    if not placements[i][j].definition.type & self.locked:
                        glLoadName((i<<24)+j)
                        placements[i][j].draw_dynamic(self.glstate, False, True)
            # Now check for selections
            selections=set()
            try:
                for min_depth, max_depth, (name,) in glRenderMode(GL_RENDER):
                    selections.add(placements[int(name)>>24][int(name)&0xffffff])
            except:	# overflow
                if __debug__: print_exc()

        # Restore state for unproject
        glMatrixMode(GL_PROJECTION)
        glPopMatrix()	

        if self.clickmode==ClickModes.DragBox:		# drag box - add or remove all selections
            if self.clickctrl:
                self.selected=self.selectsaved.copy()	# reset each time
                for i in selections:
                    if i in self.selected:
                        self.selected.remove(i)
                    else:
                        self.selected.add(i)
            else:
                self.selected=selections.copy()
        else:			# click - Add or remove one
            if not selections:
                # Start drag box
                self.clickmode=ClickModes.DragBox
                self.selectsaved=self.selected
            else:
                self.clickmode=ClickModes.Drag
            self.trashlists()	# selection changes
            if self.clickctrl:
                for i in selections:
                    if i not in self.selected:
                        self.selected.add(i)
                        break
                else:	# all selected - remove one
                    for i in self.selected:
                        if i in selections:
                            self.selected.remove(i)
                            break
            else:
                if not selections:
                    self.selected=set()
                elif selections==self.selections and len(self.selected)==1 and list(self.selected)[0] in self.selections:
                    # cycle through selections by improvising an ordering on the set
                    ordered=list(selections)
                    idx=ordered.index(list(self.selected)[0])
                    self.selected=set([ordered[(idx+1)%len(ordered)]])
                else:
                    self.selected=set(list(selections)[:1])
        self.selections=selections
        #if __debug__:
        #    for selection in self.selected:
        #        print basename(selection.definition.filename), selection.definition.layer
        if __debug__: print "%6.3f time in select" %(time.clock()-clock)

        self.Refresh()
        self.frame.ShowSel()

    def latlon2m(self, lat, lon):
        return(((lon-self.centre[1])*onedeg*cos(radians(lat)),
                (self.centre[0]-lat)*onedeg))

    def aptlatlon2m(self, lat, lon):
        # version of the above with fudge factors for runways/taxiways
        return(((lon-self.centre[1])*(onedeg+8)*cos(radians(lat)),
                (self.centre[0]-lat)*(onedeg-2)))

    def setbackground(self, background):
        if background:
            (image, lat, lon, hdg, width, length, opacity, height)=background
            if (int(floor(lat)),int(floor(lon)))==self.tile:
                (x,z)=self.latlon2m(lat,lon)
                height=self.vertexcache.height(self.tile,self.options,x,z)
            else:
                height=None
            self.background=(image, lat, lon, hdg, width, length, opacity, height)
        else:
            self.background=None
        self.Refresh()


    def add(self, name, lat, lon, hdg, size):
        # Add new clutter
        if not name:
            return False
        texerr=None
        if name.lower()[-4:] in [ObjectDef.OBJECT, AutoGenPointDef.AGP]:
            placement=ObjectFactory(name, lat, lon, hdg)
        else:
            placement=PolygonFactory(name, None, lat, lon, size, hdg)
        if __debug__: print "add", placement
            
        if not placement.load(self.lookup, self.defs, self.vertexcache):
            myMessageBox("Can't read " + name, 'Cannot add this object.', wx.ICON_ERROR|wx.OK, self.frame)
            return False
        texerr=placement.definition.texerr
        placement.definition.texerr=None	# Don't report again

        if isinstance(placement, Draped) and placement.definition.ortho:
            placement.param=65535
            for i in range(4):
                placement.nodes[0][i]+=((i+1)/2%2,i/2)
                
        placement.layout(self.tile, self.options, self.vertexcache)
        layer=placement.definition.layer
        placements=self.placements[self.tile][layer]
        self.undostack.append(UndoEntry(self.tile, UndoEntry.ADD, [(layer, len(placements), placement)]))
        placements.append(placement)
        self.selected=set([placement])
        self.selectednode=None

        self.trashlists(True)	# selection changes
        self.Refresh()
        self.frame.ShowSel()

        if texerr:
            myMessageBox(texerr.strerror.decode('utf-8'), "Can't read texture " + texerr.filename, wx.ICON_INFORMATION|wx.OK, self.frame)

        return True


    def addnode(self, name, lat, lon, hdg, size):
        # Add new node/winding
        if len(self.selected)!=1 or not isinstance(list(self.selected)[0], Polygon):
            return False
        placement=list(self.selected)[0]
        layer=placement.definition.layer
        newundo=UndoEntry(self.tile, UndoEntry.MODIFY, [(layer, self.placements[self.tile][layer].index(placement), placement.clone())])
        if self.selectednode:
            newnode=placement.addnode(self.tile, self.options, self.vertexcache, self.selectednode, lat, lon)
        else:
            newnode=placement.addwinding(self.tile, self.options, self.vertexcache, size, hdg)
        if not newnode:
            return False

        self.undostack.append(newundo)
        if not self.selectednode:
            self.selected=[placement]
        self.selectednode=newnode

        self.Refresh()
        self.frame.ShowSel()
        return True


    def movesel(self, dlat, dlon, dhdg=0, dparam=0, loc=None):
        # returns True if changed something
        if not self.selected: return False
        if self.selectednode:
            placement=list(self.selected)[0]
            layer=placement.definition.layer
            newundo=UndoEntry(self.tile, UndoEntry.MOVE, [(layer, self.placements[self.tile][layer].index(placement), placement.clone())])
            if not (self.undostack and self.undostack[-1].equals(newundo)):
                self.undostack.append(newundo)
            self.selectednode=placement.movenode(self.selectednode, dlat, dlon, self.tile, self.options, self.vertexcache, False)
            assert self.selectednode
        else:
            moved=[]
            placements=self.placements[self.tile]
            for placement in self.selected:
                layer=placement.definition.layer
                moved.append((layer, placements[layer].index(placement), placement.clone()))
                placement.move(dlat, dlon, dhdg, dparam, loc, self.tile, self.options, self.vertexcache)
            newundo=UndoEntry(self.tile, UndoEntry.MOVE, moved)
            if not (self.undostack and self.undostack[-1].equals(newundo)):
                self.undostack.append(newundo)

        self.Refresh()
        self.frame.ShowSel()
        return True


    def delsel(self, shift):
        # returns True if deleted something
        if not self.selected:
            return False
        elif self.selectednode:
            # Delete node/winding
            placement=list(self.selected)[0]
            layer=placement.definition.layer
            newundo=UndoEntry(self.tile, UndoEntry.MODIFY, [(layer, self.placements[self.tile][layer].index(placement), placement.clone())])
            if shift:
                newnode=placement.delwinding(self.tile, self.options, self.vertexcache, self.selectednode)
            else:
                newnode=placement.delnode(self.tile, self.options, self.vertexcache, self.selectednode)
            if newnode:
                self.undostack.append(newundo)
                self.selectednode=newnode
                assert self.selectednode
        else:
            deleted=[]
            placements=self.placements[self.tile]
            for placement in self.selected:
                placement.clearlayout(self.vertexcache)	# no point taking up space in vbo
                layer=placement.definition.layer
                i=placements[layer].index(placement)
                deleted.insert(0,(layer, i, placement))	# LIFO
                placements[layer].pop(i)
            self.undostack.append(UndoEntry(self.tile, UndoEntry.DEL, deleted))
            self.selected=set()

        self.trashlists(True)	# selection changes
        self.Refresh()
        self.frame.ShowSel()
        return True


    def undo(self):
        # returns new location
        if not self.undostack: return False	# can't happen
        undo=self.undostack.pop()
        self.trashlists(True)
        self.goto(undo.tile)	# force assignment of placements to layers
        avlat=0
        avlon=0
        self.selected=set()
        self.selectednode=None
        placements=self.placements[undo.tile]

        if undo.kind==UndoEntry.ADD:
            assert len(undo.data)==1	# Naieve pop only works if just one item
            (layer,i,placement)=undo.data[0]
            placement.clearlayout(self.vertexcache)
            placements[layer].pop(i)
            avlat+=placement.lat
            avlon+=placement.lon
        elif undo.kind==UndoEntry.DEL:
            for (layer, i, placement) in undo.data:
                placement.load(self.lookup, self.defs, self.vertexcache, True)
                placement.layout(undo.tile, self.options, self.vertexcache)
                placements[layer].insert(i, placement)
                avlat+=placement.lat
                avlon+=placement.lon
                self.selected.add(placement)
        else:
            for (layer, i, placement) in undo.data:
                placement.load(self.lookup, self.defs, self.vertexcache, True)
                placement.layout(undo.tile, self.options, self.vertexcache)
                placements[layer][i].clearlayout(self.vertexcache)
                placements[layer][i]=placement
                avlat+=placement.lat
                avlon+=placement.lon
                self.selected.add(placement)
        avlat/=len(undo.data)
        avlon/=len(undo.data)
        self.goto((avlat,avlon))
        return (avlat,avlon)
        
    def clearsel(self):
        if self.selected:
            self.Refresh()
        self.selected=set()
        self.selectednode=None
        self.trashlists()	# selection changed

    def allsel(self, withctrl):
        # fake up mouse drag
        self.clickmode=ClickModes.DragBox
        self.clickpos=[0,0]
        self.clickctrl=withctrl
        size=self.GetClientSize()
        self.mousenow=[size.x-1,size.y-1]
        self.select()
        self.clickmode=None
        self.clickpos=None
        self.trashlists()	# selection changed

    def nextsel(self, name, withctrl, withshift):
        # returns new location or None
        # we have 0 or more items of the same type selected
        if not self.lookup[name].file in self.defs:
            return None	# can't exist in this tile if not loaded
        definition=self.defs[self.lookup[name].file]
        placements=self.placements[self.tile][definition.layer]
        if withctrl and withshift:
            self.selected=set()
            for placement in placements:
                if placement.definition==definition:
                    self.selected.add(placement)
            if not self.selected: return None
            placement=list(self.selected)[0]	# for position
        elif withctrl:
            for placement in placements:
                if placement.definition==definition and placement not in self.selected:
                    self.selected.add(placement)
                    break
            else:
                return None
        else:
            start=-1
            for placement in self.selected:
                start=max(start,placements.index(placement))
            for i in range(start+1, len(placements)+start+1):
                placement=placements[i%len(placements)]
                if placement.definition==definition:
                    self.selected=set([placement])
                    break
            else:
                return None
        self.trashlists(True)	# selection changes
        self.selectednode=None
        self.frame.ShowSel()
        return (placement.lat, placement.lon)

    def getsel(self, dms):
        # return current selection, or average: ([names], location_string, lat, lon, object_hdg)
        if not self.selected: return ([], '', None, None, None)

        if self.selectednode:
            placement=list(self.selected)[0]
            (i,j)=self.selectednode
            return ([placement.name], placement.locationstr(dms, self.selectednode), placement.nodes[i][j][1], placement.nodes[i][j][0], None)
        elif len(self.selected)==1:
            placement=list(self.selected)[0]
            if isinstance(placement, Polygon):
                return ([placement.name], placement.locationstr(dms), placement.lat, placement.lon, None)
            else:
                return ([placement.name], placement.locationstr(dms), placement.lat, placement.lon, placement.hdg)
        else:
            lat=lon=0
            names=[]
            for placement in self.selected:
                names.append(placement.name)
                (tlat,tlon)=placement.location()
                lat+=tlat
                lon+=tlon
            lat/=len(self.selected)
            lon/=len(self.selected)
            return (names, "%s  (%d objects)" % (latlondisp(dms, lat, lon), len(self.selected)), lat, lon, None)

    def getheight(self):
        # return current height
        return self.y

    def reload(self, options, airports, navaids, aptdatfile,
               netdefs, netfile,
               lookup, placements, networks,
               background, terrain, dsfdirs):
        self.valid=False
        self.options=options
        self.airports=airports	# [runways] by code
        self.runways={}		# need to re-layout airports
        self.navaids=navaids
        self.aptdatfile=aptdatfile
        self.netdefs=netdefs
        self.netfile=netfile	# logical name of .net file used
        self.codes={}		# need to re-layout airports
        self.lookup=lookup
        self.defs=dict([(x.name, x) for x in netdefs[1:] if x])
        self.vertexcache.reset(terrain, dsfdirs)
        self.trashlists(True, True)
        self.tile=(0,999)	# force reload on next goto

        if placements!=None:
            self.placements={}
            self.unsorted=placements
            # turn networks into placements
            for key in networks.keys():
                for (road, points) in networks[key]:
                    if road and road<len(netdefs) and netdefs[road]:
                        name=netdefs[road].name
                    else:
                        name='Network #%03d    ' % road	# fallback
                    self.unsorted[key].append(Network(name, road, [points]))
            self.locked=0	# reset locked on loading new
        else:
            # clear layers
            for key in self.placements.keys():
                placements=reduce(lambda x,y: x+y, self.placements.pop(key))
                self.unsorted[key]=placements
                # invalidate all heights
                for placement in placements:
                    placement.clearlayout(self.vertexcache)
                    if isinstance(placement, Network):
                        if placement.index and placement.index<len(netdefs) and netdefs[placement.index]:
                            placement.name=netdefs[placement.index].name
                        else:
                            placement.name='Network #%03d    ' % placement.index	# fallback

        if background:
            (image, lat, lon, hdg, width, length, opacity)=background
            self.background=(image, lat, lon, hdg, width, length, opacity,None)
        else:
            self.background=None
        self.clipboard=[]	# layers might have changed
        self.undostack=[]	# layers might have changed
        self.selected=set()	# may not have same indices in new list
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


    def goto(self, loc, hdg=None, elev=None, dist=None, options=None):
        #print "goto", loc
        errobjs=[]
        errtexs=[]
        newtile=(int(floor(loc[0])),int(floor(loc[1])))
        self.centre=[newtile[0]+0.5, newtile[1]+0.5]
        (self.x, self.z)=self.latlon2m(loc[0],loc[1])
        if hdg!=None: self.h=hdg
        if elev!=None: self.e=elev
        if dist!=None: self.d=dist
        if options==None: options=self.options

        if newtile!=self.tile or options&Prefs.REDRAW!=self.options&Prefs.REDRAW:
            if newtile!=self.tile:
                self.selected=set()
                self.selectednode=None
                self.frame.ShowSel()
            self.valid=False
            self.tile=newtile
            self.vertexcache.flush()
            # flush all array allocations
            for Def in self.defs.values(): Def.flush()
            self.selections=set()
            self.trashlists(True, True)

            progress=wx.ProgressDialog('Loading', 'Terrain', 16, self.frame)
            progress.SetSize
            self.vertexcache.loadMesh(newtile, options)

            progress.Update(1, 'Terrain textures')
            self.vertexcache.getMesh(newtile, options)	# allocates into array

            progress.Update(2, 'Mesh')
            self.vertexcache.getMeshdata(newtile, options)

            if options&Prefs.ELEVATION!=self.options&Prefs.ELEVATION:
                # clear layers
                for key in self.placements.keys():
                    placements=reduce(lambda x,y:x+y, self.placements.pop(key))
                    self.unsorted[key]=placements
                    # invalidate all heights
                    for placement in placements:
                        placement.clearlayout(self.vertexcache)
                
            # load placements and assign to layers
            if not newtile in self.placements:
                self.placements[newtile]=[[] for i in range(ClutterDef.LAYERCOUNT)]
            if newtile in self.unsorted:
                if __debug__: clock=time.clock()	# Processor time
                placements=self.unsorted.pop(newtile)
                # Limit progress dialog to 10 updates
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

                    #if __debug__: print placement.name
                    if not placement.load(self.lookup, self.defs, self.vertexcache, True) and placement.name not in errobjs:
                        if __debug__: print "Bad", placement.name
                        errobjs.append(placement.name)
                        self.frame.palette.markbad(placement.name)

                    if placement.definition.texerr:
                        s=u"%s: %s" % (placement.definition.texerr.filename, placement.definition.texerr.strerror.decode('utf-8'))
                        if not s in errtexs: errtexs.append(s)
                        
                    if not placement.islaidout():
                        placement.layout(newtile, options, self.vertexcache)
                    self.placements[newtile][placement.definition.layer].append(placement)
                if __debug__: print "%6.3f time in load&layout" % (time.clock()-clock)
            else:
                for placements in self.placements[newtile]:
                    for placement in placements:
                        placement.definition.allocate(self.vertexcache, self.defs)
            self.options=options

            # Lay out runways
            progress.Update(13, 'Airports')
            surfaces={0:  [0.125, 0.125],	# unknown
                      1:  [0.375, 0.125],	# asphalt
                      2:  [0.625, 0.125],	# concrete
                      3:  [0.875, 0.125],	# grass
                      4:  [0.125, 0.375],	# dirt,
                      5:  [0.375, 0.375],	# gravel
                      12: [0.125, 0.875],	# lakebed
                      13: [0.375, 0.875],	# water
                      14: [0.625, 0.875],	# ice
                      15: [0.875, 0.875]}	# transparent
            key=(newtile[0],newtile[1],options&Prefs.ELEVATION)
            if key not in self.runways:
                if __debug__: clock=time.clock()	# Processor time
                self.runways[key]=[]
                self.codes[newtile]=[]
                svarray=[]
                tvarray=[]
                rvarray=[]
                area=BBox(newtile[0]-0.05, newtile[0]+1.1,
                          newtile[1]-0.1, newtile[1]+1.2)
                tile=BBox(newtile[0], newtile[0]+1,
                          newtile[1], newtile[1]+1)
                for code, (name, loc, apt) in self.airports.iteritems():
                    if not area.inside(*loc):
                        continue
                    if tile.inside(*loc):
                        self.codes[newtile].append((code,loc))
                    runways=[]
                    taxiways=[]
                    shoulders=[]
                    thisarea=BBox()
                    if isinstance(apt, long):
                        try:
                            thisapt=readApt(self.aptdatfile, apt)
                            self.airports[code]=(name, loc, thisapt)
                        except:
                            thisapt=[]
                    else:
                        thisapt=list(apt)
                    thisapt.reverse()	# draw in reverse order
                    newthing=None
                    for thing in thisapt:
                        if isinstance(thing, tuple):
                            # convert to pavement style
                            if not isinstance(thing[0], tuple):
                                # old pre-850 style or 850 style helipad
                                (lat,lon,h,length,width,stop1,stop2,surface,shoulder,isrunway)=thing
                                if isrunway:
                                    kind=runways
                                else:
                                    kind=taxiways
                                (cx,cz)=self.aptlatlon2m(lat,lon)
                                length1=length/2+stop1
                                length2=length/2+stop2
                                h=radians(h)
                                coshdg=cos(h)
                                sinhdg=sin(h)
                                p1=[cx-length1*sinhdg, cz+length1*coshdg]
                                p2=[cx+length2*sinhdg, cz-length2*coshdg]
                                # Special handling for helipads, of which
                                # there are loads
                                if len(thisapt)==1 and length+stop1+stop2<61 and width<61:	# 200ft
                                    if not tile.inside(lat,lon):
                                        continue
                                    #if __debug__: print code, "small"
                                    if surface in surfaces:
                                        col=surfaces[surface]
                                    else:
                                        col=surfaces[0]
                                    xinc=width/2*coshdg
                                    zinc=width/2*sinhdg
                                    rvarray.extend([[p1[0]+xinc, self.vertexcache.height(newtile,options, p1[0]+xinc, p1[1]+zinc), p1[1]+zinc] + col,
                                                    [p1[0]-xinc, self.vertexcache.height(newtile,options, p1[0]-xinc, p1[1]-zinc), p1[1]-zinc] + col,
                                                    [p2[0]-xinc, self.vertexcache.height(newtile,options, p2[0]-xinc, p2[1]-zinc), p2[1]-zinc] + col,
                                                    [p1[0]+xinc, self.vertexcache.height(newtile,options, p1[0]+xinc, p1[1]+zinc), p1[1]+zinc] + col,
                                                    [p2[0]-xinc, self.vertexcache.height(newtile,options, p2[0]-xinc, p2[1]-zinc), p2[1]-zinc] + col,
                                                    [p2[0]+xinc, self.vertexcache.height(newtile,options, p2[0]+xinc, p2[1]+zinc), p2[1]+zinc] + col])
                                    continue
                            else:
                                # new 850 style runway
                                ((lat1,lon1),(lat2,lon2),width,stop1,stop2,surface,shoulder)=thing
                                kind=runways
                                (x1,z1)=self.latlon2m(lat1,lon1)
                                (x2,z2)=self.latlon2m(lat2,lon2)
                                h=-atan2(x1-x2,z1-z2)
                                coshdg=cos(h)
                                sinhdg=sin(h)
                                p1=[x1-stop1*sinhdg, z1+stop1*coshdg]
                                p2=[x2+stop2*sinhdg, z2-stop2*coshdg]
                            xinc=width/2*coshdg
                            zinc=width/2*sinhdg
                            newthing=[surface,
                                      [[p1[0]+xinc, p1[1]+zinc],
                                       [p1[0]-xinc, p1[1]-zinc],
                                       [p2[0]-xinc, p2[1]-zinc],
                                       [p2[0]+xinc, p2[1]+zinc]]]
                            kind.append(newthing)
                            if shoulder:
                                xinc=width*0.75*coshdg
                                zinc=width*0.75*sinhdg
                                newthing=[shoulder,
                                          [[p1[0]+xinc, p1[1]+zinc],
                                           [p1[0]-xinc, p1[1]-zinc],
                                           [p2[0]-xinc, p2[1]-zinc],
                                           [p2[0]+xinc, p2[1]+zinc]]]
                                shoulders.append(newthing)
                            for i in range(4):
                                thisarea.include(*newthing[1][i])
                        else:
                            # new 850 style taxiway
                            newthing=[thing[0]]
                            for i in range(1,len(thing)):
                                winding=[]
                                for pt in thing[i]:
                                    (x,z)=self.latlon2m(pt[0],pt[1])
                                    thisarea.include(x,z)
                                    if len(pt)<4:
                                        winding.append([x,z])
                                    else:
                                        (xb,zb)=self.latlon2m(pt[2],pt[3])
                                        thisarea.include(xb,zb)
                                        winding.append([x,z,xb,zb])
                                newthing.append(winding)
                            taxiways.append(newthing)

                    if not runways and not taxiways:
                        continue	# didn't add anything (except helipads)
                    
                    # Find patches under this airport
                    #if __debug__: print code, len(taxiways), len(runways),
                    meshtris=[]
                    for (bbox, tris) in self.vertexcache.getMeshdata(newtile,options):
                        if thisarea.intersects(bbox):
                            # tesselator is expensive - minimise mesh triangles
                            for tri in tris:
                                (pt, coeffs)=tri
                                tbox=BBox()
                                for i in range(3):
                                    tbox.include(pt[i][0], pt[i][2])
                                if thisarea.intersects(tbox):
                                    meshtris.append(tri)
                    if not meshtris:
                        #if __debug__: print 0
                        continue	# airport is wholly outside this tile
                    #if __debug__: print len(meshtris),

                    for (kind,varray) in [(shoulders, svarray),
                                          (taxiways,  tvarray),
                                          (runways,   rvarray)]:
                        lastcol=None
                        pavements=[]
                        for pave in kind:
                            # tessellate similar surfaces together
                            if pave[0] in surfaces:
                                col=surfaces[pave[0]]
                            else:
                                col=surfaces[0]
                            if col!=lastcol:
                                if lastcol:
                                    gluTessEndPolygon(tess)
                                if pavements:
                                    # tessellate existing against terrain
                                    gluTessBeginPolygon(csgt, varray)
                                    for i in range(0,len(pavements),3):
                                        gluTessBeginContour(csgt)
                                        for j in range(i,i+3):
                                            #assert len(pavements[j])==3 and len(pavements[j][0])==3 and type(pavements[j][1])==bool and len(pavements[j][2])==2, pavements[j]
                                            gluTessVertex(csgt, array([pavements[j][0][0],0,pavements[j][0][2]],float64), pavements[j])
                                        gluTessEndContour(csgt)
                                    for meshtri in meshtris:
                                        (meshpt, coeffs)=meshtri
                                        gluTessBeginContour(csgt)
                                        for m in range(3):
                                            x=meshpt[m][0]
                                            z=meshpt[m][2]
                                            #assert len(meshpt[m])==3, meshpt[m]
                                            gluTessVertex(csgt, array([x,0,z],float64), (meshpt[m],True, lastcol))
                                        gluTessEndContour(csgt)
                                    gluTessEndPolygon(csgt)
                                lastcol=col
                                pavements=[]
                                gluTessBeginPolygon(tess, pavements)

                            # generate tris in pavements
                            for i in range(1,len(pave)):
                                gluTessBeginContour(tess)
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
                                        points=[self.bez(cpoints, u/4.0) for u in range(4)]	# X-Plane stops at or before 8
                                    for pt in points:
                                        if pt==last: continue
                                        last=pt
                                        (x,z)=pt
                                        y=self.vertexcache.height(newtile,options,x,z,meshtris)
                                        gluTessVertex(tess, array([x,0,z],float64), ([x,y,z], False, col))
                                gluTessEndContour(tess)

                        # tessellate last against terrain
                        if lastcol:
                            gluTessEndPolygon(tess)
                        if pavements:	# may have no taxiways
                            gluTessBeginPolygon(csgt, varray)
                            for i in range(0,len(pavements),3):
                                gluTessBeginContour(csgt)
                                for j in range(i,i+3):
                                    #assert len(pavements[j])==3 and len(pavements[j][0])==3 and type(pavements[j][1])==bool and len(pavements[j][2])==2, pavements[j]
                                    gluTessVertex(csgt, array([pavements[j][0][0],0,pavements[j][0][2]],float64), pavements[j])
                                gluTessEndContour(csgt)
                            for meshtri in meshtris:
                                (meshpt, coeffs)=meshtri
                                gluTessBeginContour(csgt)
                                for m in range(3):
                                    x=meshpt[m][0]
                                    z=meshpt[m][2]
                                    #assert len(meshpt[m])==3, meshpt[m]
                                    gluTessVertex(csgt, array([x,0,z],float64), (meshpt[m],True, lastcol))
                                gluTessEndContour(csgt)
                            gluTessEndPolygon(csgt)

                    #if __debug__: print ' '

                varray=svarray+tvarray+rvarray
                shoulderlen=len(svarray)
                taxiwaylen=len(tvarray)
                runwaylen=len(rvarray)
                self.runways[key]=(varray,shoulderlen,taxiwaylen,runwaylen)
                if __debug__: print "%6.3f time in runways" % (time.clock()-clock)
            else:
                (varray,shoulderlen,taxiwaylen,runwaylen)=self.runways[key]
            if shoulderlen:
                self.shoulderdata=(self.vertexcache.instance_count, shoulderlen)
            else:
                self.shoulderdata=None
            if taxiwaylen:
                self.taxiwaydata=(self.vertexcache.instance_count+shoulderlen, taxiwaylen)
            else:
                self.taxiwaydata=None
            if runwaylen:
                self.runwaysdata=(self.vertexcache.instance_count+shoulderlen+taxiwaylen, runwaylen)
            else:
                self.runwaysdata=None
            if len(varray):
                self.vertexcache.allocate_instance(array(varray,float32).flatten())

            progress.Update(14, 'Navaids')
            objs={2:  'lib/airport/NAVAIDS/NDB_3.obj',
                  3:  'lib/airport/NAVAIDS/VOR.obj',
                  4:  'lib/airport/NAVAIDS/ILS.obj',
                  5:  'lib/airport/NAVAIDS/ILS.obj',
                  6:  'lib/airport/NAVAIDS/glideslope.obj',
                  7:  'lib/airport/NAVAIDS/Marker1.obj',
                  8:  'lib/airport/NAVAIDS/Marker2.obj',
                  9:  'lib/airport/NAVAIDS/Marker2.obj',
                  19: '*windsock.obj',
                  181:'lib/airport/landscape/beacon1.obj',
                  182:'lib/airport/beacons/beacon_seaport.obj',
                  183:'lib/airport/beacons/beacon_heliport.obj',
                  184:'lib/airport/landscape/beacon2.obj',
                  185:'lib/airport/landscape/beacon1.obj',
                  211:'lib/airport/lights/slow/VASI.obj',
                  212:'lib/airport/lights/slow/PAPI.obj',
                  213:'lib/airport/lights/slow/PAPI.obj',
                  214:'lib/airport/lights/slow/PAPI.obj',
                  215:'lib/airport/lights/slow/VASI3.obj',
                  216:'lib/airport/lights/slow/rway_guard.obj',
                  }
            for name in objs.values():
                try:
                    if name[0]=='*':
                        filename=name
                    else:
                        filename=self.lookup[name].file
                    if filename in self.defs:
                        self.defs[filename].allocate(self.vertexcache, self.defs)
                    else:
                        self.defs[filename]=ObjectDef(filename, self.vertexcache)
                except:
                    # Older versions of X-Plane don't have eg beacon_seaport
                    if __debug__: print_exc()
                
            # Prepare static stuff: mesh, networks, navaids
            progress.Update(15, 'Layout')
            self.glstate.set_instance(self.vertexcache)
            self.glstate.set_texture(0)
            self.glstate.set_color(COL_UNPAINTED)
            self.glstate.set_cull(True)
            self.glstate.set_depthtest(True)
            self.glstate.set_poly(False)

            # Display list assumes instance_vbo is bound
            self.meshlist=glGenLists(1)
            glNewList(self.meshlist, GL_COMPILE)
            glColor3f(*COL_UNPAINTED)
            polystate=0
            if __debug__:
                if debugapt: glPolygonMode(GL_FRONT, GL_LINE)
            if not self.options&Prefs.ELEVATION:
                glPushMatrix()
                glScalef(1,0,1)		# Defeat elevation data
            for (base,number,texno,poly) in self.vertexcache.getMesh(self.tile,self.options):
                if poly:		# eg overlaid photoscenery
                    # Can't use polygon offset in display list on OSX<10.4.8?
                    # or ATI drivers>7.11? on Windows.
                    if polystate!=poly:
                        glDisable(GL_DEPTH_TEST)
                        polystate=poly
                else:
                    if polystate:
                        glEnable(GL_DEPTH_TEST)
                        polystate=0
                glBindTexture(GL_TEXTURE_2D, texno)
                glDrawArrays(GL_TRIANGLES, base, number)
            if not self.options&Prefs.ELEVATION:
                glPopMatrix()
            if __debug__:
                if debugapt: glPolygonMode(GL_FRONT, GL_FILL)

            # networks
            glBindTexture(GL_TEXTURE_2D, 0)
            glDisable(GL_DEPTH_TEST)
            for (roadtype, points) in self.vertexcache.getNets(self.tile,self.options):
                if roadtype<=len(self.defnetdefs) and self.defnetdefs[roadtype].color:
                    glColor3f(*self.defnetdefs[roadtype].color)
                else:
                    glColor3f(0.5,0.5,0.5)
                glBegin(GL_LINE_STRIP)
                for (x,y,z) in points:
                    glVertex3f(x,y,z)
                glEnd()

            # navaids
            glColor3f(*COL_UNPAINTED)
            glEnable(GL_DEPTH_TEST)
            for (i, lat, lon, hdg) in self.navaids:
                if (int(floor(lat)),int(floor(lon)))==self.tile and i in objs:
                    if objs[i][0]=='*':
                        definition=self.defs[objs[i]]
                    elif objs[i] not in self.lookup:
                        if __debug__: print "Missing navaid %s" % objs[i]
                        continue	# missing in this version of X-Plane
                    else:
                        definition=self.defs[self.lookup[objs[i]].file]
                    coshdg=cos(radians(hdg))
                    sinhdg=sin(radians(hdg))
                    (x,z)=self.latlon2m(lat,lon)
                    y=self.vertexcache.height(self.tile,self.options,x,z)
                    glBindTexture(GL_TEXTURE_2D, definition.texture)
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
                        if definition.culled:
                            glDrawArrays(GL_TRIANGLES, definition.base, definition.culled)
                        if definition.nocull:
                            glDisable(GL_CULL_FACE)
                            glDrawArrays(GL_TRIANGLES, definition.base+definition.culled, definition.nocull)
                            glEnable(GL_CULL_FACE)
                        glPopMatrix()
            glEndList()

            # labels
            self.codeslist=glGenLists(1)
            glNewList(self.codeslist, GL_COMPILE)
            glColor3f(1.0, 0.25, 0.25)	# Labels are pink
            glBindTexture(GL_TEXTURE_2D, 0)
            for (code, (lat,lon)) in self.codes[self.tile]:
                (x,z)=self.latlon2m(lat,lon)
                y=self.vertexcache.height(self.tile,self.options,x,z)
                glRasterPos3f(x, y, z)
                code=code.encode('latin1', 'replace')
                for c in code:
                    glBitmap(8,13, 16,6, 8,0, fixed8x13[ord(c)])
            glEndList()

            # Done
            self.setbackground(self.background)
            progress.Update(16, 'Done')
            progress.Destroy()
            self.valid=True

        # cursor position
        self.options=options
        self.y=self.vertexcache.height(self.tile,self.options,self.x,self.z)

        # Redraw can happen under MessageBox, so do this last
        if errobjs:
            sortfolded(errobjs)
            if len(errobjs)>11: errobjs=errobjs[:10]+['and %d more objects' % (len(errobjs)-10)]
            myMessageBox('\n'.join(errobjs), "Can't read one or more objects.", wx.ICON_EXCLAMATION|wx.OK, self.frame)

        if errtexs:
            sortfolded(errtexs)
            if len(errtexs)>11: errtexs=errtexs[:10]+['and %d more textures' % (len(errtexs)-10)]
            myMessageBox('\n'.join(errtexs), "Can't read one or more textures.", wx.ICON_INFORMATION|wx.OK, self.frame)

        self.Refresh()

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
            if self.codeslist: glDeleteLists(self.codeslist, 1)
            self.codeslist=0

    def getworldloc(self, mx, my):
        if wx.VERSION >= (2,9):
            self.SetCurrent(self.context)
        else:
            self.SetCurrent()
        size = self.GetClientSize()
        mx=max(0, min(size[0]-1, mx))
        my=max(0, min(size[1]-1, size[1]-1-my))
        self.glstate.set_depthtest(True)
        self.glstate.set_poly(False)	# DepthMask=True
        glColorMask(GL_FALSE,GL_FALSE,GL_FALSE,GL_FALSE)
        glCallList(self.meshlist)	# Terrain only
        #glFinish()	# redundant
        dz=glReadPixelsf(mx,my, 1,1, GL_DEPTH_COMPONENT)[0][0]
        if dz==0.0 or dz==1.0:
            mz=0.5	# treat off the tile edge as sea level
        else:
            mz=dz
        (x,y,z)=gluUnProject(mx,my,mz, model=identity(4,float64), view=array([0,0,size[0],size[1]], int32))
        glColorMask(GL_TRUE,GL_TRUE,GL_TRUE,GL_TRUE)
        glClear(GL_DEPTH_BUFFER_BIT)
        lat=round2res(self.centre[0]-z/onedeg)
        lon=round2res(self.centre[1]+x/(onedeg*cos(radians(lat))))
        if __debug__: print "%3d %3d %.6f, %5d %5.1f %5d, %10.6f %11.6f" % (mx,my,mz, x,y,z, lat,lon)
        return (lat,lon)


# runway tessellators

def tessvertex(vertex, data):
    data.append(vertex)

def tesscombine(coords, vertex, weight):
    # Linearly interp height from vertices (location, ismesh, uv)
    p1=vertex[0]
    p2=vertex[1]
    d=hypot(p2[0][0]-p1[0][0], p2[0][2]-p1[0][2])
    if not d:
        return p1	# p1 and p2 are colocated
    else:
        ratio=hypot(coords[0]-p1[0][0], coords[2]-p1[0][2])/d
        y=p1[0][1]+ratio*(p2[0][1]-p1[0][1])
        return ([coords[0],y,coords[2]], False, p1[2])
    
def tessedge(flag):
    pass	# dummy

tess=gluNewTess()
gluTessNormal(tess, 0, -1, 0)
gluTessProperty(tess, GLU_TESS_WINDING_RULE, GLU_TESS_WINDING_NONZERO)
gluTessCallback(tess, GLU_TESS_VERTEX_DATA,  tessvertex)
gluTessCallback(tess, GLU_TESS_COMBINE,      tesscombine)
gluTessCallback(tess, GLU_TESS_EDGE_FLAG,    tessedge)	# no strips


def csgtvertex((location,ismesh,uv), varray):
    #assert len(location)==3, location
    #assert len(uv)==2, uv
    varray.append(location+uv)

def csgtcombine(coords, vertex, weight):
    # vertex = [(location, ismesh, uv)]
    # check for just two adjacent mesh triangles
    if array_equal(vertex[0][0],vertex[1][0]) and vertex[0][1]==vertex[1][1] and vertex[0][2]==vertex[1][2]:
        # common case
        return vertex[0]
    elif vertex[0][0][0]==vertex[1][0][0] and vertex[0][0][2]==vertex[1][0][2] and vertex[0][1]:
        # Height discontinuity in terrain mesh - eg LIEE - wtf!
        #assert vertex[0][1]!=vertex[1][1]
        assert not weight[2] and not vertex[2] and not weight[3] and not vertex[3] and vertex[1][1]
        return vertex[0]

    # intersection of two lines - use terrain mesh line for height
    elif vertex[0][1]:
        #assert weight[0] and weight[1] and weight[2] and weight[3] and vertex[1][1]
        p1=vertex[0]
        p2=vertex[1]
        p3=vertex[2]
    else:
        #assert weight[0] and weight[1] and weight[2] and weight[3]	# not sure why we would assert this
        p1=vertex[2]
        p2=vertex[3]
        p3=vertex[0]

    # height
    d=hypot(p2[0][0]-p1[0][0], p2[0][2]-p1[0][2])
    if not d:
        y=p1[0][1]
    else:
        ratio=(hypot(coords[0]-p1[0][0], coords[2]-p1[0][2])/d)
        y=p1[0][1]+ratio*(p2[0][1]-p1[0][1])
    return ([coords[0],y,coords[2]], True, p3[2] or p1[2])

def csgtedge(flag):
    pass	# dummy

csgt = gluNewTess()
gluTessNormal(csgt, 0, -1, 0)
gluTessProperty(csgt, GLU_TESS_WINDING_RULE, GLU_TESS_WINDING_ABS_GEQ_TWO)
gluTessCallback(csgt, GLU_TESS_VERTEX_DATA,  csgtvertex)
gluTessCallback(csgt, GLU_TESS_COMBINE,      csgtcombine)
gluTessCallback(csgt, GLU_TESS_EDGE_FLAG,    csgtedge)	# no strips

