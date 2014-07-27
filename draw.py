import OpenGL	# for __version__
from OpenGL.GL import *
from OpenGL.GLU import *
from OpenGL.arrays import vbo
from OpenGL.extensions import alternate, hasGLExtension
from OpenGL.GL.shaders import compileShader, compileProgram
from OpenGL.GL.ARB.occlusion_query import *
glBeginQuery = alternate(glBeginQuery, glBeginQueryARB)
glDeleteQueries = alternate(glDeleteQueries, glDeleteQueriesARB)
glEndQuery = alternate(glEndQuery, glEndQueryARB)
glGenQueries = alternate(glGenQueries, glGenQueriesARB)
glGetQueryObjectuiv = alternate(glGetQueryObjectuiv, glGetQueryObjectuivARB)
GL_ANY_SAMPLES_PASSED=0x8C2F	# not in 3.0.1
from OpenGL.GL.ARB.instanced_arrays import glInitInstancedArraysARB, glVertexAttribDivisorARB
from OpenGL.GL.EXT.multi_draw_arrays import glMultiDrawArraysEXT
from OpenGL.GL.EXT.gpu_shader4 import glInitGpuShader4EXT
glMultiDrawArrays = alternate(glMultiDrawArrays, glMultiDrawArraysEXT)

import gc
from glob import glob
from math import atan2, cos, sin, floor, hypot, radians
from numpy import array, array_equal, concatenate, dot, identity, vstack, zeros, float32, float64, int32
import os
from os.path import basename, curdir, join
from struct import unpack
from sys import exc_info, exit, platform, version
from traceback import print_exc
import time
import wx
import wx.glcanvas

from apt import layoutApt
from files import VertexCache, sortfolded, glInitTextureCompressionS3TcEXT
from fixed8x13 import fixed8x13
from clutter import Clutter, Object, Polygon, Draped, DrapedImage, Facade, Network, Exclude
from clutterdef import ClutterDef, ObjectDef, AutoGenPointDef, NetworkDef, PolygonDef, COL_CURSOR, COL_SELECTED, COL_UNPAINTED, COL_DRAGBOX, COL_WHITE, fallbacktexture
from DSFLib import readDSF
from elevation import BBox, ElevationMesh, onedeg, round2res
from imagery import Imagery
from lock import Locked
from MessageBox import myMessageBox
from nodes import Node
from prefs import Prefs, prefs, gcustom, gnavdata
from version import appname

sband=16	# width of mouse scroll band around edge of window

debugapt   = __debug__ and False
log_glstate= __debug__ and True
log_load   = __debug__ and True
log_paint  = __debug__ and True

class UndoEntry:
    ADD=0
    DEL=1
    MODIFY=2
    MOVE=3
    SPLIT=4

    def __init__(self, tile, kind, data):
        self.tile=tile
        self.kind=kind
        self.data=data		# [(idx, placement)]

    def equals(self, other):
        # ignore placement details
        if self.tile!=other.tile or not (self.kind==other.kind==UndoEntry.MOVE): return False
        if self.data==other.data==None: return True
        if not (self.data and other.data and len(self.data)==len(other.data)):
            return False
        for i in range(len(self.data)):
            if self.data[i][0]!=other.data[i][0]:
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
        self.proj = identity(4, float64)	# projection matrix
        self.occlusion_query=None	# Will test for this later
        self.queries=[]
        self.multi_draw_arrays = bool(glMultiDrawArrays)
        glEnableClientState(GL_VERTEX_ARRAY)
        self.texture=0
        glEnableClientState(GL_TEXTURE_COORD_ARRAY)
        self.color=COL_UNPAINTED
        glColor3f(*COL_UNPAINTED)
        glDisableClientState(GL_COLOR_ARRAY)
        self.cull=True
        glEnable(GL_CULL_FACE)
        self.depthtest=True
        glDepthFunc(GL_LESS)
        self.poly=False
        glDisable(GL_POLYGON_OFFSET_FILL)
        glDepthMask(GL_TRUE)
        self.current_vbo=None
        self.instance_vbo=vbo.VBO(None, GL_STATIC_DRAW, size=0)	# explicit size for PyOpenGL_accelerate
        self.vector_vbo  =vbo.VBO(None, GL_STATIC_DRAW, size=0)
        self.dynamic_vbo =vbo.VBO(None, GL_STATIC_DRAW, size=0)
        self.selected_vbo=vbo.VBO(None, GL_STREAM_DRAW, size=0)
        # Use of GL_ARB_instanced_arrays requires a shader. Just duplicate fixed pipeline shaders.
        try:
            # MacOS 10.5 drivers are too flakey
            if platform=='darwin' and int(os.uname()[2].split('.')[0]) < 10: raise NotImplementedError
            vanilla   = open('Resources/vanilla.vs').read()
            instanced = open('Resources/instanced.vs').read()
            unlit     = open('Resources/unlit.fs').read()
            colorvs   = open('Resources/color.vs').read()
            colorfs   = open('Resources/color.fs').read()
            pointfs   = open('Resources/point.fs').read()
            self.textureshader = compileProgram(compileShader(vanilla, GL_VERTEX_SHADER),
                                                compileShader(unlit, GL_FRAGMENT_SHADER))
            if __debug__: print glGetProgramInfoLog(self.textureshader)
            self.transform_pos = glGetUniformLocation(self.textureshader, 'transform')
            self.colorshader   = compileProgram(compileShader(colorvs, GL_VERTEX_SHADER),
                                                compileShader(colorfs, GL_FRAGMENT_SHADER))
            if __debug__: print glGetProgramInfoLog(self.colorshader)
            assert glGetProgramiv(self.colorshader, GL_LINK_STATUS), glGetProgramInfoLog(self.colorshader)
            if platform=='win32' and glGetString(GL_VENDOR)=='Intel' and glGetString(GL_VERSION).startswith('2.'):
                # gl_PointCoord broken on Gen5 and older - http://lists.freedesktop.org/archives/mesa-commit/2012-March/036247.html
                self.pointshader = None
                glPointSize(5.0)
            else:
                self.pointshader   = compileProgram(compileShader(colorvs, GL_VERTEX_SHADER),
                                                    compileShader(pointfs, GL_FRAGMENT_SHADER))
                if __debug__: print glGetProgramInfoLog(self.pointshader)
                glEnable(GL_POINT_SPRITE)
            if glInitInstancedArraysARB():
                self.instancedshader = compileProgram(compileShader(instanced, GL_VERTEX_SHADER),
                                                      compileShader(unlit, GL_FRAGMENT_SHADER))
                if __debug__: print glGetProgramInfoLog(self.instancedshader)
                self.instanced_transform_pos = glGetAttribLocation(self.instancedshader, 'transform')
                self.instanced_selected_pos  = glGetAttribLocation(self.instancedshader, 'selected')
                self.instanced_arrays = True
            else:
                self.instancedshader = self.instanced_transform_pos = self.instanced_selected_pos = None
                self.instanced_arrays = False
            glUseProgram(self.textureshader)
            glUniform4f(self.transform_pos, *zeros(4,float32))
            self.shaders = True
        except:
            if __debug__: print_exc()
            self.instanced_arrays = self.shaders = False
            self.textureshader = self.colorshader = self.pointshader = self.instancedshader = None

    def set_texture(self, id):
        if self.texture!=id:
            if __debug__:
                if self.debug: print "set_texture", id
            if id is None:
                if __debug__:
                    if self.debug: print "set_texture disable GL_TEXTURE_COORD_ARRAY"
                glDisableClientState(GL_TEXTURE_COORD_ARRAY)
                if self.shaders: glUseProgram(self.colorshader)
                if self.texture!=0:
                    glBindTexture(GL_TEXTURE_2D, 0)
            else:
                if self.texture is None:
                    if __debug__:
                        if self.debug: print "set_texture enable GL_TEXTURE_COORD_ARRAY"
                    glEnableClientState(GL_TEXTURE_COORD_ARRAY)
                    if self.shaders: glUseProgram(self.textureshader)
                glBindTexture(GL_TEXTURE_2D, id)
            self.texture=id
        elif __debug__:
            if self.debug: print "set_texture already", id

    def set_color(self, color):
        if self.color!=color:
            if color is None:
                # Colors from VBO
                if __debug__:
                    if self.debug:
                        print "set_color None"
                        print "set_color enable GL_COLOR_ARRAY"
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
        # Occlusion query counts "the number of samples that pass the depth and stencil tests", which ATI interpret
        # as meaning that the depth test must be enabled. So control depth test via DepthFunc rather than glEnable.
        if self.depthtest!=depthtest:
            if __debug__:
                if self.debug: print "set_depthtest", depthtest
            self.depthtest=depthtest
            if depthtest:
                glDepthFunc(GL_LESS)
            else:
                glDepthFunc(GL_ALWAYS)
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

    def set_vector(self, vertexcache):
        if vertexcache.realize_vector(self.vector_vbo) or self.current_vbo!=self.vector_vbo:
            if __debug__:
                if self.debug: print "set_vector"
            self.vector_vbo.bind()
            vertexcache.realize_vector(self.vector_vbo)
            glColorPointer(3, GL_FLOAT, 24, self.vector_vbo+12)
            glVertexPointer(3, GL_FLOAT, 24, self.vector_vbo)
            self.current_vbo=self.vector_vbo
        elif __debug__:
            if self.debug: print "set_vector already vector_vbo"

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

    def set_attrib_selected(self, pos, selectflags):
        self.selected_vbo.set_array(selectflags)
        self.selected_vbo.bind()
        glVertexAttribPointer(pos, 1, GL_FLOAT, GL_FALSE, 4, self.selected_vbo)

    def alloc_queries(self, needed):
        if len(self.queries)<needed:
            if len(self.queries): glDeleteQueries(len(self.queries), self.queries)
            needed=(needed/256+1)*256	# round up
            self.queries=glGenQueries(needed)
            if __debug__:
                if self.debug: print "get_queries", self.queries

    def pickmatrix(self, x, y, width, height, viewx, viewy):
        # like gluPickMatrix, but doesn't actually load the resultant matrix into OpenGL
        width = width and float(width) or 1.0	# maths goes wrong if zero-sized box
        height = height and float(height) or 1.0
        sx = viewx / width
        sy = viewy / height
        tx = (viewx - 2 * x) / width
        ty = (viewy - 2 * y) / height
        m = array([[sx, 0, 0, 0], [0, sy, 0, 0], [0, 0, 1, 0], [tx, ty, 0, 1]], dtype=float64)
        return dot(self.proj, m)


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
        self.options = 0	# display options at last goto()
        self.tile=(0,999)	# [lat,lon] of SW
        self.centre=None	# [lat,lon] of centre
        self.airports={}	# [runways] by code
        self.runways={}		# [shoulder/taxiway/runway data] by tile
        self.aptdata = {}	# indices into vertexcache (base, len), by layer
        self.navaids=[]		# (type, lat, lon, hdg)
        self.navaidplacements={}	# navaid placements by tile
        self.codes={}		# [(code, loc)] by tile
        self.codeslist=0	# airport labels
        self.lookup={}		# virtual name -> filename (may be duplicates)
        self.defs={}		# loaded ClutterDefs by filename
        self.placements={}	# [Clutter] by tile
        self.unsorted={}	# [Clutter] by tile
        self.background=None
        
        self.mousenow=None	# Current position (used in timer and drag)
        self.locked=0		# locked object types
        self.selected=set()	# selected placements
        self.clickmode=None
        self.clickpos=None	# Location of mouse down
        self.clickctrl=False	# Ctrl was held down
        self.selectednode=None	# Selected node. Only if len(self.selected)==1
        self.selectedhandle=None	# Selected node control handle.
        self.selectedlayoutpending = False	# self.clickmode==ClickModes.DragNode and we need to do a full layout
        self.selections=set()	# Hits for cycling picking
        self.selectsaved=set()	# Selection at start of ctrl drag box
        self.snapnode = None	# (Polygon, idx) of node we snapped to in ClickModes.DragNode mode
        self.draginert=True
        self.dragx=wx.SystemSettings_GetMetric(wx.SYS_DRAG_X)
        self.dragy=wx.SystemSettings_GetMetric(wx.SYS_DRAG_Y)
        if self.dragx<=1 or self.dragx>8 or self.dragy<=1 or self.dragy>8:
            self.dragx=self.dragy=5	# Finder on Mac appears to use 5

        self.clipboard = set()
        self.undostack=[]

        # Values during startup
        self.x=0
        self.y=0
        self.z=0
        self.h=0
        self.e=45
        self.d=2048.0

        if __debug__: self.ei = self.ej = ElevationMesh.DIVISIONS/2-1	# for debugging elevation mesh

        # Must specify min sizes for glX? - see glXChooseVisual and GLXFBConfig
        try:
            # Ask for a large depth buffer.
            # wxGTK<=2.8 can't recover from a failure in glXChooseFBConfig so skip this - http://trac.wxwidgets.org/ticket/12479
            if platform.startswith('linux'): raise AssertionError
            # We're not using the stencil buffer so would prefer to specify a 32bit depth buffer, but this can cause e.g. Intel Windows drivers to fall back to 16 even though they support 24
            wx.glcanvas.GLCanvas.__init__(self, parent, style=wx.FULL_REPAINT_ON_RESIZE|wx.WANTS_CHARS,
                                          attribList=[wx.glcanvas.WX_GL_RGBA,wx.glcanvas.WX_GL_DOUBLEBUFFER,wx.glcanvas.WX_GL_DEPTH_SIZE, 24])
            if wx.VERSION >= (2,9):
                self.context = wx.glcanvas.GLContext(self)

        except:
            # Failed - try with safe 16bit depth buffer.
            try:
                if __debug__: print "Trying 16bit depth buffer"
                # wxGTK<=2.8 has no way to discover if this fails, so will segfault later
                wx.glcanvas.GLCanvas.__init__(self, parent, style=wx.FULL_REPAINT_ON_RESIZE|wx.WANTS_CHARS,
                                              attribList=[wx.glcanvas.WX_GL_RGBA,wx.glcanvas.WX_GL_DOUBLEBUFFER,wx.glcanvas.WX_GL_DEPTH_SIZE, 16])
                if wx.VERSION >= (2,9):
                    self.context = wx.glcanvas.GLContext(self)
            except:
                myMessageBox('Try updating the drivers for your graphics card.', "Can't initialise OpenGL.", wx.ICON_ERROR|wx.OK, frame)
                exit(1)

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
        # Setup state. Under X must be called after window is shown
        if wx.VERSION >= (2,9):
            self.SetCurrent(self.context)
        else:
            self.SetCurrent()
        if log_glstate: print "%s\n%s\n%s\nRGBA: %d%d%d%d, Depth: %d, Stencil: %d, Aux: %d, DoubleBuffer: %d" % (glGetString(GL_VENDOR), glGetString(GL_RENDERER), glGetString(GL_VERSION), glGetInteger(GL_RED_BITS), glGetInteger(GL_GREEN_BITS), glGetInteger(GL_BLUE_BITS), glGetInteger(GL_ALPHA_BITS), glGetInteger(GL_DEPTH_BITS), glGetInteger(GL_STENCIL_BITS), glGetInteger(GL_AUX_BUFFERS), glGetBoolean(GL_DOUBLEBUFFER))

        if not vbo.get_implementation():
            myMessageBox('This application requires the use of OpenGL Vertex Buffer Objects (VBOs) which are not supported by your graphics card.\nTry updating the drivers for your graphics card.',
                         "Can't initialise OpenGL.", wx.ICON_ERROR|wx.OK, self.frame)
            exit(1)
        if not glInitTextureCompressionS3TcEXT() and not __debug__:
            myMessageBox('This application requires the use of DXT texture compression which is not supported by your graphics card.\nTry updating the drivers for your graphics card.',
                         "Can't initialise OpenGL.", wx.ICON_ERROR|wx.OK, self.frame)
            exit(1)

        self.vertexcache=VertexCache()	# member so can free resources
        self.glstate=GLstate()
        self.imagery=Imagery(self)

        #glClearDepth(1.0)
        glClearColor(0.5, 0.5, 1.0, 0.0)	# Sky
        glEnable(GL_DEPTH_TEST)
        glShadeModel(GL_SMOOTH)
        glEnable(GL_LINE_SMOOTH)
        glPointSize(7.0)			# for nodes
        glHint(GL_POINT_SMOOTH_HINT, GL_NICEST)	# we can hope
        glFrontFace(GL_CW)
        glPolygonMode(GL_FRONT, GL_FILL)
        glPolygonOffset(-2, -2)
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
        glMatrixMode(GL_PROJECTION)		# We always leave the modelview matrix as identity and the active matrix mode as projection, except briefly when drawing objects via the non-shader path
        wx.EVT_PAINT(self, self.OnPaint)	# start generating paint events only now we're set up

        if log_glstate:
            try:
                import OpenGL_accelerate.formathandler	# for py2exe
                import OpenGL_accelerate.nones_formathandler	# for py2exe
                import OpenGL.acceleratesupport
                print 'PyOpenGL acceleration:\t\t%s' % (OpenGL.acceleratesupport.ACCELERATE_AVAILABLE and 'yes' or 'no')
            except:
                print 'PyOpenGL acceleration:\t\tnot supported'
            print 'max_texture_size:\t\t%d' % self.vertexcache.texcache.maxtexsize
            print 'texture_non_power_of_two:\t%s' % (self.vertexcache.texcache.npot and 'yes' or 'no')
            print 'texture_compression:\t\t%s' % (self.vertexcache.texcache.compress and 'yes' or 'no')
            print 'texture_compression_s3tc:\t%s' % (self.vertexcache.texcache.s3tc and 'yes' or 'no')
            print 'bgra:\t\t\t\t%s' % (self.vertexcache.texcache.bgra and 'yes' or 'no')
            print 'shaders:\t\t\t%s' % (self.glstate.shaders and 'yes' or 'no')
            print 'gpu_shader4:\t\t\t%s' % (glInitGpuShader4EXT() and 'yes' or 'no')
            print 'instanced_arrays:\t\t%s' % (self.glstate.instanced_arrays and 'yes' or 'no')
            print 'multi_draw_arrays:\t\t%s' % (self.glstate.multi_draw_arrays and 'yes' or 'no')


    def OnEraseBackground(self, event):
        # Prevent flicker when resizing / painting on MSW
        #if __debug__: print "OnEraseBackground"
        self.needclear=True	# ATI drivers require clear afer resize

    def OnKeyDown(self, event):
        if self.clickmode:
            event.Skip()
        else:
            # Manually propagate
            self.frame.OnKeyDown(event)

    def OnMouseWheel(self, event):
        # under wxMac 2.8 scroll events don't arrive in the main frame, so catch here and forward
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
        self.frame.canvas.SetFocus()	# otherwise focus goes to None under wxGTK
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
            if self.selectedlayoutpending:
                if __debug__: clock2 = time.clock()
                placement = list(self.selected)[0]
                self.selectednode = placement.layout(self.tile, self.selectednode)
                if __debug__: print "%6.3f time to layout %s" % (time.clock()-clock2, placement.name)
                self.selectedlayoutpending = False
                self.Refresh()
            if self.snapnode:
                # split segment at snapped-to node
                (poly,idx) = self.snapnode
                if idx!=0 and idx!=len(poly.nodes[0])-1:
                    poly2 = poly.clone()
                    poly2.load(self.lookup, self.defs, self.vertexcache)
                    placements = self.placements[self.tile]
                    self.undostack.append(UndoEntry(self.tile, UndoEntry.SPLIT, [(placements.index(poly), poly.clone()),
                                                                                 (len(placements), poly2)]))
                    placements.append(poly2)
                    poly.nodes[0] = poly.nodes[0][:idx+1]
                    poly.layout(self.tile, recalc=True)
                    poly2.nodes[0]= poly2.nodes[0][idx:]
                    poly2.layout(self.tile, recalc=True)
                    self.selected = set([poly,poly2])
                    self.selectednode = self.selectedhandle = None
                    self.Refresh()
                self.snapnode = None
        elif self.clickmode==ClickModes.Drag:
            for placement in self.selected:
                placement.layout(self.tile)
        elif self.clickmode==ClickModes.DragBox:
            self.Refresh()	# get rid of drag box
        self.clickmode=None
        self.frame.ShowSel()
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
                if self.selectedlayoutpending:
                    if __debug__: clock2 = time.clock()
                    placement = list(self.selected)[0]
                    self.selectednode = placement.layout(self.tile, self.selectednode)
                    if __debug__: print "%6.3f time to layout %s" % (time.clock()-clock2, placement.name)
                    assert self.selectednode
                    self.selectedlayoutpending = False
                self.Refresh()
            elif self.needrefresh:
                # Mouse motion with a selected polygon draws to the back buffer, which Mac uses as backing store. So refresh.
                self.Refresh()

    def OnMouseMotion(self, event):
        # Capture unreliable on Mac, so may have missed Up events. See
        # https://sourceforge.net/tracker/?func=detail&atid=109863&aid=1489131&group_id=9863
        #self.getworldloc(event.GetX(),event.GetY())	# debug
        assert self.valid
        if not self.valid: return
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
                if list(self.selected)[0].pick_nodes(self.glstate.pickmatrix(event.GetX(), size[1]-1-event.GetY(), 5,5, *size), True):
                    self.SetCursor(self.dragcursor)	# hovering over node
                    return

            self.SetCursor(wx.NullCursor)
            return

        assert (self.clickmode!=ClickModes.Undecided)

        if self.clickmode==ClickModes.Move:
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
            self.snapnode = None
            poly=list(self.selected)[0]

            if isinstance(poly, Network) and not self.selectedhandle and self.selectednode[1] in [0,len(poly.nodes[0])-1]:
                # snap end nodes to nodes in other network segments
                size = self.GetClientSize()
                proj = self.glstate.pickmatrix(event.GetX(), size[1]-1-event.GetY(), 13,13, *size)
                for p in self.placements[self.tile]:
                    if isinstance(p, Network) and p!=poly:
                        hit = p.pick_nodes(proj, False)
                        if hit:
                            self.snapnode = (p, hit[0][1])
                            break

            if self.snapnode:
                node = self.snapnode[0].nodes[0][self.snapnode[1]]
                (lon,lat) = (node.lon,node.lat)	# snap to matching network node location
            else:
                (lat,lon)=self.getworldloc(event.GetX(), event.GetY())
                lat=max(self.tile[0], min(self.tile[0]+1, lat))
                lon=max(self.tile[1], min(self.tile[1]+1, lon))
            if not self.frame.bkgd:	# No undo for background image
                newundo=UndoEntry(self.tile, UndoEntry.MOVE, [(self.placements[self.tile].index(poly), poly.clone())])
                if not (self.undostack and self.undostack[-1].equals(newundo)):
                    self.undostack.append(newundo)
                self.frame.toolbar.EnableTool(wx.ID_SAVE, True)
                self.frame.toolbar.EnableTool(wx.ID_UNDO, True)
                if self.frame.menubar:
                    self.frame.menubar.Enable(wx.ID_SAVE, True)
                    self.frame.menubar.Enable(wx.ID_UNDO, True)
            if self.selectedhandle:
                poly.updatehandle(self.selectednode, self.selectedhandle, event.CmdDown(), lat, lon, self.tile)
            else:
                poly.updatenode(self.selectednode, lat, lon, self.tile)
            self.selectedlayoutpending = True	# need to do full layout at some point
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
                if not self.frame.bkgd:	# No undo for background image
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

        if log_paint:
            clock=clock2=time.clock()

        glViewport(0, 0, *size)
        vd=self.d*size.y/size.x
        proj=array([[1.0/self.d,0,0,0], [0,1.0/vd,0,0], [0,0,(-1.0/30)/vd,0], [0,0,0,1]], float64)	# glOrtho(-self.d, self.d, -vd, vd, -30*vd, 30*vd)	# 30 ~= 1/sin(2), where 2 is minimal elevation angle        
        proj=dot(array([[1,0,0,0], [0,cos(radians(self.e)),sin(radians(self.e)),0], [0,-sin(radians(self.e)),cos(radians(self.e)),0], [0,0,0,1]], float64), proj)	# glRotatef(self.e, 1.0,0.0,0.0)
        proj=dot(array([[cos(radians(self.h)),0,-sin(radians(self.h)),0], [0,1,0,0], [sin(radians(self.h)),0,cos(radians(self.h)),0], [0,0,0,1]], float64), proj)	# glRotatef(self.h, 0.0,1.0,0.0)
        self.glstate.proj = dot(array([[1,0,0,0], [0,1,0,0], [0,0,1,0], [-self.x,-self.y,-self.z,1]], float64), proj)	# glTranslatef(-self.x, -self.y, -self.z)
        glLoadMatrixd(self.glstate.proj)

        # Workaround for buggy ATI drivers: Check that occlusion queries actually work
        if self.glstate.occlusion_query is None:
            if not bool(glGenQueries):
                if log_glstate: print 'occlusion_query:\t\tno'
                self.glstate.occlusion_query=False
            else:
                self.glstate.occlusion_query=hasGLExtension('GL_ARB_occlusion_query2') and GL_ANY_SAMPLES_PASSED or GL_SAMPLES_PASSED
            if self.glstate.occlusion_query:
                glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT)
                self.glstate.set_texture(self.vertexcache.texcache.get(fallbacktexture))	# ATI drivers don't like 0
                self.glstate.set_color(COL_WHITE)	# Ensure colour indexing off
                self.glstate.set_depthtest(False)	# Draw even if occluded
                self.glstate.set_poly(True)		# Disable writing to depth buffer
                self.glstate.set_cull(False)
                self.glstate.alloc_queries(1)
                glColorMask(GL_FALSE,GL_FALSE,GL_FALSE,GL_FALSE)
                glBeginQuery(self.glstate.occlusion_query, self.glstate.queries[0])
                glBegin(GL_QUADS)
                glVertex3f( 100, 0, -100)
                glVertex3f( 100, 0,  100)
                glVertex3f(-100, 0,  100)
                glVertex3f(-100, 0, -100)
                glEnd()
                glEndQuery(self.glstate.occlusion_query)
                if not glGetQueryObjectuiv(self.glstate.queries[0], GL_QUERY_RESULT):
                    self.glstate.occlusion_query=False
                    if log_glstate: print 'occlusion_query:\t\tbroken'
                else:
                    if log_glstate: print 'occlusion_query:\t\tyes (%s)' % (hasGLExtension('GL_ARB_occlusion_query2') and 'GL_ANY_SAMPLES_PASSED' or 'GL_SAMPLES_PASSED')
                glColorMask(GL_TRUE,GL_TRUE,GL_TRUE,GL_TRUE)

        # Ground terrain

        if not self.valid:
            # Sea
            glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT)
            self.glstate.set_color((0.25, 0.25, 0.50))
            if self.glstate.shaders:
                self.glstate.set_texture(None)	# ATI drivers don't like 0
            else:
                self.glstate.set_texture(0)
            glBegin(GL_QUADS)
            glVertex3f( onedeg*cos(radians(1+self.tile[0]))/2, 0, -onedeg/2)
            glVertex3f( onedeg*cos(radians(self.tile[0]))/2, 0,  onedeg/2)
            glVertex3f(-onedeg*cos(radians(self.tile[0]))/2, 0,  onedeg/2)
            glVertex3f(-onedeg*cos(radians(1+self.tile[0]))/2, 0, -onedeg/2)
            glEnd()
            self.SwapBuffers()
            glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT)
            self.needclear=False
            self.frame.canvas.SetFocus()	# under wxGTK need to manually set focus on startup
            return
        elif self.needclear:
            glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT)
            self.needclear=False
        
        # Map imagery & background
        imagery=self.imagery.placements(self.d, size)	# May allocate into dynamic VBO
        if log_paint:
            print "%6.3f time to get imagery" % (time.clock()-clock2)
            clock2=time.clock()
        if self.background and self.background.islaidout():
            imagery.append(self.background)
            if self.frame.bkgd:
                self.selected=set([self.background])	# Override selection while dialog is open
            elif self.background in self.selected:
                self.selected=set()
        elif self.frame.bkgd:
            self.selected=set()

        # Mesh and Nets
        self.glstate.set_instance(self.vertexcache)
        self.glstate.set_color(COL_UNPAINTED)
        self.glstate.set_cull(True)
        self.glstate.set_poly(False)
        if __debug__:
            elev = self.vertexcache.getElevationMesh(self.tile)
            if debugapt: glPolygonMode(GL_FRONT, GL_LINE)
            if debugapt and hasattr(elev, 'divwidth'):
                # show elevation mesh buckets
                self.glstate.set_depthtest(False)
                self.glstate.set_texture(None)
                self.glstate.set_color(COL_DRAGBOX)
                glBegin(GL_LINES)
                for i in range(-ElevationMesh.DIVISIONS/2, ElevationMesh.DIVISIONS/2+1):
                    glVertex3f( (ElevationMesh.DIVISIONS/2) * elev.divwidth, 0, i * elev.divheight)
                    glVertex3f(-(ElevationMesh.DIVISIONS/2) * elev.divwidth, 0, i * elev.divheight)
                for j in range(-ElevationMesh.DIVISIONS/2, ElevationMesh.DIVISIONS/2+1):
                    glVertex3f(j * elev.divwidth, 0,  (ElevationMesh.DIVISIONS/2) * elev.divheight)
                    glVertex3f(j * elev.divwidth, 0, -(ElevationMesh.DIVISIONS/2) * elev.divheight)
                glEnd()
                self.glstate.set_color(COL_SELECTED)
                glBegin(GL_LINE_LOOP)
                glVertex3f((self.ej-ElevationMesh.DIVISIONS/2)  *elev.divwidth, 0, (ElevationMesh.DIVISIONS/2  -self.ei)*elev.divheight)
                glVertex3f((self.ej-ElevationMesh.DIVISIONS/2+1)*elev.divwidth, 0, (ElevationMesh.DIVISIONS/2  -self.ei)*elev.divheight)
                glVertex3f((self.ej-ElevationMesh.DIVISIONS/2+1)*elev.divwidth, 0, (ElevationMesh.DIVISIONS/2-1-self.ei)*elev.divheight)
                glVertex3f((self.ej-ElevationMesh.DIVISIONS/2)  *elev.divwidth, 0, (ElevationMesh.DIVISIONS/2-1-self.ei)*elev.divheight)
                glEnd()
                self.glstate.set_color(COL_UNPAINTED)
                glBegin(GL_TRIANGLES)
                print (self.ei,self.ej), len(elev.buckets[self.ei][self.ej]), 'tris'
                for tri in elev.tris[elev.buckets[self.ei][self.ej]]:
                    glVertex3fv(tri['p1'])
                    glVertex3fv(tri['p2'])
                    glVertex3fv(tri['p3'])
                glEnd()
        self.glstate.set_depthtest(True)
        self.glstate.set_texture(0)	# texture shader
        if self.glstate.shaders:
            if not prefs.options&Prefs.ELEVATION:
                glUniform4f(self.glstate.transform_pos, 0, -1, 0, 0)	# Defeat elevation data
            else:
                glUniform4f(self.glstate.transform_pos, *zeros(4,float32))
        else:
            glMatrixMode(GL_MODELVIEW)
            glLoadIdentity()
            if not self.options&Prefs.ELEVATION:
                glScalef(1,0,1)		# Defeat elevation data:
        (mesh, netindices) = self.vertexcache.getMesh(self.tile)
        for (base,number,texno) in mesh:
            self.glstate.set_texture(texno)
            glDrawArrays(GL_TRIANGLES, base, number)
        if not self.options&Prefs.ELEVATION:
            if self.glstate.shaders:
                glUniform4f(self.glstate.transform_pos, *zeros(4,float32))
            else:
                glLoadIdentity()
        if __debug__:
            if debugapt: glPolygonMode(GL_FRONT, GL_FILL)
        if netindices is not None:
            self.glstate.set_vector(self.vertexcache)
            self.glstate.set_texture(None)
            self.glstate.set_color(None)
            self.glstate.set_depthtest(False)	# Need line to appear over terrain
            glDrawRangeElements(GL_LINES, netindices[0], netindices[-1], len(netindices), GL_UNSIGNED_INT, netindices)
        if log_paint:
            print "%6.3f time to draw mesh" % (time.clock()-clock2)
            clock2=time.clock()

        # Objects and Polygons
        placements=self.placements[self.tile]
        navaidplacements=self.navaidplacements[self.tile]

        self.glstate.set_dynamic(self.vertexcache)	# realize
        # Draw clutter with dynamic geometry
        self.vertexcache.buckets.draw(self.glstate, self.frame.bkgd and set() or self.selected, self.aptdata, imagery, prefs.imageryopacity)	# background image is always drawn with its own opacity setting
        if log_paint:
            print "%6.3f time to draw dynamic" % (time.clock()-clock2)
            clock2=time.clock()

        # Draw clutter with static geometry (ignoring layer ordering since it doesn't really matter so much for Objects)
        self.glstate.set_instance(self.vertexcache)
        self.glstate.set_poly(False)
        self.glstate.set_depthtest(True)
        if self.glstate.instanced_arrays:
            self.glstate.set_color(COL_UNPAINTED)
            self.glstate.set_texture(0)	# has side-effect so shader program won't be reset
            glUseProgram(self.glstate.instancedshader)
            glEnableVertexAttribArray(self.glstate.instanced_transform_pos)
            glVertexAttribDivisorARB(self.glstate.instanced_transform_pos, 1)
            assert type(self.selected)==set
            selected = self.selected.copy()
            if selected:
                glEnableVertexAttribArray(self.glstate.instanced_selected_pos)
                glVertexAttribDivisorARB(self.glstate.instanced_selected_pos, 1)
                for o in self.selected: selected.update(o.placements)	# include children
            else:
                glVertexAttrib1f(self.glstate.instanced_selected_pos, 0)
            for objdef in self.defs.values():	# benefit of sorting by texture would be marginal
                objdef.draw_instanced(self.glstate, selected)
            glDisableVertexAttribArray(self.glstate.instanced_transform_pos)
            glDisableVertexAttribArray(self.glstate.instanced_selected_pos)
        else:
            # Instancing not supported
            self.glstate.set_texture(0)	# load texture shader
            selected = self.selected.copy()
            if selected:
                for o in self.selected: selected.update(o.placements)	# include children
            for objdef in self.defs.values():	# benefit of sorting by texture would be marginal
                objdef.draw_instanced(self.glstate, selected)
            if self.glstate.shaders:
                glUniform4f(self.glstate.transform_pos, *zeros(4,float32))	# drawing Objects alters the matrix
            else:
                glLoadIdentity()	# Drawing Objects alters the matrix
                glMatrixMode(GL_PROJECTION)
        if log_paint:
            print "%6.3f time to draw static" % (time.clock()-clock2)
            clock2=time.clock()

        # Overlays
        self.glstate.set_texture(None)	# resets shader
        self.glstate.set_depthtest(False)
        self.glstate.set_poly(True)

        # Selected nodes - very last so overwrites everything
        if len(self.selected)==1:
            # don't bother setting VBO since this is done immediate
            list(self.selected)[0].draw_nodes(self.glstate, self.selectednode)

        # labels
        if self.codeslist and self.d>2000:	# arbitrary
            #if __debug__: print "labels"
            glCallList(self.codeslist)

        # Position centre
        #if __debug__: print "cursor"
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

        # 2D stuff
        if self.clickmode==ClickModes.DragBox or self.imagery.provider_logo:
            glLoadIdentity()

            # drag box
            if self.clickmode==ClickModes.DragBox:
                if __debug__: print "drag"
                self.glstate.set_color(COL_DRAGBOX)
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

            # imagery attribution
            if self.imagery.provider_logo:
                (filename,width,height)=self.imagery.provider_logo
                self.glstate.set_color(COL_UNPAINTED)
                self.glstate.set_texture(self.vertexcache.texcache.get(filename,wrap=False,fixsize=True))
                glBegin(GL_QUADS)
                glTexCoord2f(0,0)
                glVertex3f(-1,-1, -0.9)
                glTexCoord2f(0,1)
                glVertex3f(-1,-1+height*2.0/size.y, -0.9)
                glTexCoord2f(1,1)
                glVertex3f(-1+width*2.0/size.x,-1+height*2.0/size.y, -0.9)
                glTexCoord2f(1,0)
                glVertex3f(-1+width*2.0/size.x,-1, -0.9)
                glEnd()

        glLoadMatrixd(self.glstate.proj)	# Restore state for unproject
        self.glstate.set_poly(False)

        if log_paint: print "%6.3f time in OnPaint" % (time.clock()-clock)

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
        if self.clickmode==ClickModes.DragBox:
            proj = self.glstate.pickmatrix((self.clickpos[0]+self.mousenow[0])/2, size[1]-1-(self.clickpos[1]+self.mousenow[1])/2,
                                           abs(self.clickpos[0]-self.mousenow[0]), abs(self.clickpos[1]-self.mousenow[1]), *size)
        else:	# at point
            proj = self.glstate.pickmatrix(self.clickpos[0], size[1]-1-self.clickpos[1], 5,5, *size)

        if self.frame.bkgd:	# Don't allow selection of other objects while background dialog is open
            if self.background and self.background.islaidout():
                placements=[self.background]
            else:
                placements=[]
        else:
            placements=self.placements[self.tile]

        # Select poly node?
        if (self.clickmode==ClickModes.Undecided and len(self.selected)==1 and isinstance(list(self.selected)[0], Polygon)):
            selected = list(self.selected)[0].pick_nodes(proj, True)
            if selected:
                # No need to look further if user has clicked on a node or handle within selected polygon
                (self.selectednode, self.selectedhandle) = selected
                self.clickmode = ClickModes.DragNode
                self.selectedlayoutpending = False
                if __debug__: print "%6.3f time in select" %(time.clock()-clock)
                self.frame.ShowSel()
                return
        self.selectednode = self.selectedhandle = None

        # Select placements
        glLoadMatrixd(proj)
        self.glstate.set_texture(self.vertexcache.texcache.get(fallbacktexture))	# textured shader throughout. ATI drivers don't like 0
        self.glstate.set_color(COL_WHITE)		# Ensure colour indexing off
        self.glstate.set_depthtest(False)		# Make selectable even if occluded
        self.glstate.set_poly(True)			# Disable writing to depth buffer
        self.glstate.set_cull(False)			# Enable selection of "invisible" faces
        selections = set()
        lookup = []
        objdefs = (not self.locked&Locked.OBJ) and [objdef for objdef in self.defs.values() if isinstance(objdef,ObjectDef)] or []

        if self.glstate.occlusion_query:
            needed = sum([len(objdef.instances) for objdef in objdefs]) + len(placements)	# upper limit
            self.glstate.alloc_queries(needed)
            glColorMask(GL_FALSE,GL_FALSE,GL_FALSE,GL_FALSE)	# Don't want to update frame buffer either
        else:
            glSelectBuffer(len(placements)*8)	# Twice as many for two-phase drawing
            glRenderMode(GL_SELECT)
            glInitNames()
            glPushName(0)

        self.glstate.set_instance(self.vertexcache)
        if not self.glstate.shaders:
            glMatrixMode(GL_MODELVIEW)
        for objdef in objdefs:
            objdef.pick_instanced(self.glstate, proj, selections, lookup)
        if self.glstate.shaders:
            glUniform4f(self.glstate.transform_pos, *zeros(4,float32))	# drawing Objects alters the matrix
        else:
            glLoadIdentity()	# Drawing Objects alters the matrix
            glMatrixMode(GL_PROJECTION)
        if __debug__: print "%6.3f time to issue instance" %(time.clock()-clock)

        self.glstate.set_dynamic(self.vertexcache)
        for p in placements:
            if not p.definition.type & self.locked:
                p.pick_dynamic(self.glstate, lookup)
        if __debug__: print "%6.3f time to issue dynamic" %(time.clock()-clock)

        # Now check for selections
        if self.glstate.occlusion_query:
            for k in range(len(lookup)):
                if glGetQueryObjectuiv(self.glstate.queries[k], GL_QUERY_RESULT):
                    selections.add(lookup[k])
            glColorMask(GL_TRUE,GL_TRUE,GL_TRUE,GL_TRUE)
        else:
            try:
                for min_depth, max_depth, (name,) in glRenderMode(GL_RENDER):
                    selections.add(lookup[int(name)])
            except:	# overflow
                if __debug__: print_exc()
        if __debug__: print "%6.3f time to check queries" %(time.clock()-clock)

	# promote children and filter out navaids
        selections = set([placement.parent or placement for placement in selections]).difference(self.navaidplacements[self.tile])

        if self.frame.bkgd:	# Don't allow selection of other objects while background dialog is open
            if self.clickmode==ClickModes.Drag or self.background in selections:
                self.clickmode=ClickModes.Drag
            else:
                self.clickmode=ClickModes.DragBox	# Can't leave as ClickModes.Undecided
            self.Refresh()
            self.frame.ShowSel()
            return

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
        if __debug__: print "%6.3f time in select" %(time.clock()-clock)

        self.Refresh()
        self.frame.ShowSel()

    def latlon2m(self, lat, lon):
        return(((lon-self.centre[1])*onedeg*cos(radians(lat)),
                (self.centre[0]-lat)*onedeg))

    # create the background polygon. Defer layout to goto since can be called in reload() before location is known.
    def setbackground(self, prefs, loc=None, newfile=None, layoutnow=False):
        if newfile is None and prefs.package in prefs.packageprops:
            backgroundfile=prefs.packageprops[prefs.package][0]
        else:
            backgroundfile=newfile	# may be '' if just cleared

        if not backgroundfile:
            if self.background: self.background.clearlayout()
            self.background=None
            prefs.packageprops.pop(prefs.package,False)
            return
        elif not self.background or self.background.name!=backgroundfile:
            if backgroundfile[0]==curdir:
                backgroundfile = join(glob(join(prefs.xplane,gcustom,prefs.package))[0], backgroundfile[2:])
            try:
                texture = self.vertexcache.texcache.get(backgroundfile, wrap=False, downsample=False, fixsize=True)
            except:
                if __debug__: print_exc()
                texture=self.vertexcache.texcache.get(fallbacktexture)

        if not self.background:
            if prefs.package in prefs.packageprops:
                p=prefs.packageprops[prefs.package][1:]
                if len(p)==6:
                    # convert from pre 2.15 setting
                    (lat, lon, hdg, width, length, opacity)=p
                    x=width/(2*onedeg*cos(radians(lat)))
                    z=length/(2*onedeg)
                    l=hypot(x,z)
                    nodes=[(lon-x,lat-z),(lon+x,lat-z),(lon+x,lat+z),(lon-x,lat+z)]
                    if hdg:
                        for j in range(len(nodes)):
                            h=atan2(nodes[j][0]-lon, nodes[j][1]-lat)+radians(hdg)
                            l=hypot(nodes[j][0]-lon, nodes[j][1]-lat)
                            nodes[j] = Node([lon+sin(h)*l, lat+cos(h)*l])
                else:
                    nodes = [Node([p[i], p[i+1]]) for i in range(0, len(p), 2)]
                self.background=DrapedImage('*background', 65535, [nodes])
            else:	# new
                try:	# georeferenced
                    from osgeo import osr, gdal

                    ds = gdal.Open(backgroundfile.encode('utf8'))	# Needs to be utf8 for old versions on Linux!
                    gt = ds.GetGeoTransform()
                    width, height = ds.RasterXSize, ds.RasterYSize

                    old_cs= osr.SpatialReference()
                    old_cs.ImportFromWkt(ds.GetProjectionRef())

                    new_cs = osr.SpatialReference()
                    new_cs.SetWellKnownGeogCS('WGS84')

                    tr = osr.CoordinateTransformation(old_cs,new_cs)
                    nodes = [Node(tr.TransformPoint(gt[0],                              gt[3] + width*gt[4] + height*gt[5])),
                             Node(tr.TransformPoint(gt[0] + width*gt[1] + height*gt[2], gt[3] + width*gt[4] + height*gt[5])),
                             Node(tr.TransformPoint(gt[0] + width*gt[1] + height*gt[2], gt[3]                             )),
                             Node(tr.TransformPoint(gt[0],                              gt[3]                             ))]
                    self.background=DrapedImage('*background', 65535, [nodes])
                except:
                    if __debug__: print_exc()
                    self.background=DrapedImage('*background', 65535, loc[0], loc[1], self.d, self.h)

            self.background.load(self.lookup, self.defs, self.vertexcache)
            self.background.definition.layer = ClutterDef.IMAGEFILELAYER
            self.background.singlewinding = self.background.fixednodes = True
            self.background.canbezier = False
            for i in range(len(self.background.nodes[0])):
                self.background.nodes[0][i].rest = [(i+1)/2%2,i/2]	# assign UVs

        if self.background.name!=backgroundfile:
            self.background.name=backgroundfile
            self.background.definition.texture = texture
            self.background.flush()	# force layout with new texture

        if layoutnow:
            self.background.layout(self.tile)

    def add(self, name, lat, lon, hdg, size):
        # Add new clutter
        if not name:
            return False
        texerr=None
        try:
            if name.lower()[-4:] in [ObjectDef.OBJECT, AutoGenPointDef.AGP]:
                placement = Object.factory(name, lat, lon, hdg)
            else:
                placement = Polygon.factory(name, None, lat, lon, size, hdg)
        except UnicodeError:
            if __debug__: print_exc()
            myMessageBox('Filename "%s" uses non-ASCII characters' % name, 'Cannot add this object.', wx.ICON_ERROR|wx.OK, self.frame)
            return False
        except:
            if __debug__: print_exc()
            myMessageBox("Can't read " + name, 'Cannot add this object.', wx.ICON_ERROR|wx.OK, self.frame)
            return False
        if __debug__: print "add", placement
            
        if not placement.load(self.lookup, self.defs, self.vertexcache):
            myMessageBox("Can't read " + name, 'Cannot add this object.', wx.ICON_ERROR|wx.OK, self.frame)
            return False
        texerr=placement.definition.texerr
        placement.definition.texerr=None	# Don't report again

        # Hack! Can only decide nature of new draped polygon once we've loaded its definition
        if isinstance(placement, Draped):
            if placement.definition.ortho:
                placement.param = 65535
                placement.singlewinding = placement.fixednodes = True
                placement.canbezier = False
                for i in range(4):
                    placement.nodes[0][i].rest = [(i+1)/2%2, i/2]	# ST coords
            else:
                placement.canbezier = True
                
        placement.layout(self.tile)
        placements=self.placements[self.tile]
        self.undostack.append(UndoEntry(self.tile, UndoEntry.ADD, [(len(placements), placement)]))
        placements.append(placement)
        self.selected=set([placement])
        self.selectednode=None

        self.Refresh()
        self.frame.ShowSel()

        if texerr:
            myMessageBox(u"%s: %s" % texerr, "Can't read texture.", wx.ICON_INFORMATION|wx.OK, self.frame)

        return True


    def addnode(self, name, lat, lon, hdg, size):
        # Add new node/winding
        if len(self.selected)!=1 or not isinstance(list(self.selected)[0], Polygon) or self.frame.bkgd:	# No additional nodes for background image
            return False
        placement=list(self.selected)[0]
        newundo=UndoEntry(self.tile, UndoEntry.MODIFY, [(self.placements[self.tile].index(placement), placement.clone())])
        if self.selectednode:
            newnode=placement.addnode(self.tile, self.selectednode, lat, lon)
        else:
            newnode=placement.addwinding(self.tile, size, hdg)
        if not newnode:
            return False

        self.undostack.append(newundo)
        if not self.selectednode:
            self.selected=set([placement])
        self.selectednode=newnode

        self.Refresh()
        self.frame.ShowSel()
        return True


    def togglebezier(self):
        # Add new node/winding
        if len(self.selected)!=1 or not self.selectednode: return False
        placement = list(self.selected)[0]
        newundo = UndoEntry(self.tile, UndoEntry.MODIFY, [(self.placements[self.tile].index(placement), placement.clone())])
        newnode = placement.togglebezier(self.tile, self.selectednode)
        if not newnode:
            return False
        else:
            self.selectednode = newnode
        if not (self.undostack and self.undostack[-1].equals(newundo)):
            self.undostack.append(newundo)
        self.Refresh()
        self.frame.ShowSel()
        return True


    def movesel(self, dlat, dlon, dhdg=0, dparam=0, loc=None):
        # returns True if changed something
        if not self.selected: return False
        if self.selectednode:
            placement=list(self.selected)[0]
            if not self.frame.bkgd:	# No undo for background image
                newundo=UndoEntry(self.tile, UndoEntry.MOVE, [(self.placements[self.tile].index(placement), placement.clone())])
                if not (self.undostack and self.undostack[-1].equals(newundo)):
                    self.undostack.append(newundo)
            if __debug__: clock2 = time.clock()
            self.selectednode=placement.movenode(self.selectednode, dlat, dlon, dparam, self.tile, False)
            if __debug__: print "%6.3f time to layout %s" % (time.clock()-clock2, placement.name)
            assert self.selectednode
        else:
            moved=[]
            placements=self.placements[self.tile]
            for placement in self.selected:
                if not self.frame.bkgd:	# No undo for background image
                    moved.append((placements.index(placement), placement.clone()))
                if __debug__: clock2 = time.clock()
                placement.move(dlat, dlon, dhdg, dparam, loc, self.tile)
                if __debug__: print "%6.3f time to layout %s" % (time.clock()-clock2, placement.name)
            if moved:
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
        elif self.frame.bkgd:
            if self.selectednode:
                return False
            else:
                self.frame.bkgd.OnClear(None)	# Yuck!
        elif self.selectednode:
            # Delete node/winding
            placement=list(self.selected)[0]
            newundo=UndoEntry(self.tile, UndoEntry.MODIFY, [(self.placements[self.tile].index(placement), placement.clone())])
            if shift:
                newnode=placement.delwinding(self.tile, self.selectednode)
            else:
                newnode=placement.delnode(self.tile, self.selectednode)
            if newnode:
                self.undostack.append(newundo)
                self.selectednode=newnode
                assert self.selectednode
        else:
            deleted=[]
            placements=self.placements[self.tile]
            for placement in self.selected:
                placement.clearlayout()			# no point taking up space in vbo
                i=placements.index(placement)
                deleted.insert(0, (i, placement))	# LIFO
                placements.pop(i)
            self.undostack.append(UndoEntry(self.tile, UndoEntry.DEL, deleted))
            self.selected=set()

        self.Refresh()
        self.frame.ShowSel()
        return True


    def copysel(self):
        if self.selectednode or not self.selected: return None	# can't copy and paste nodes
        self.clipboard = set()
        avlat = sum([placement.location()[0] for placement in self.selected]) / len(self.selected)
        avlon = sum([placement.location()[1] for placement in self.selected]) / len(self.selected)
        for placement in self.selected:
            # Centre copied objects relative to average location
            self.clipboard.add(placement.copy(avlat, avlon))
        return (avlat,avlon)


    def paste(self, lat, lon):
        if not self.clipboard: return None
        newplacements = []
        for placement in self.clipboard:
            clone = placement.clone()
            clone.load(self.lookup, self.defs, self.vertexcache, True)
            clone.move(lat, lon, 0, 0, None, self.tile)
            newplacements.append(clone)
        placements = self.placements[self.tile]
        self.undostack.append(UndoEntry(self.tile, UndoEntry.ADD, [(len(placements), placement) for placement in newplacements]))
        placements.extend(newplacements)
        self.selected = set(newplacements)
        self.selectednode = None
        self.Refresh()
        self.frame.ShowSel()
        return (lat,lon)


    def importregion(self, dsfdirs, netdefs):
        if len(self.selected)!=1 or not isinstance(list(self.selected)[0], Exclude):
            return False

        exc = list(self.selected)[0]
        bbox = BBox()
        for node in exc.nodes[0]:
            bbox.include(node.lon, node.lat)

        dsfs = []
        for path in dsfdirs:
            if not glob(path): continue
            pathlen=len(glob(path)[0])+1
            thisdsfs=glob(join(path, '*', gnavdata, "%+02d0%+03d0" % (int(self.tile[0]/10), int(self.tile[1]/10)), "%+03d%+04d.[dD][sS][fF]" % (self.tile[0], self.tile[1])))
            # asciibetical, except global is last
            thisdsfs.sort(lambda x,y: ((x[pathlen:].lower().startswith('-global ') and 1) or
                                       (y[pathlen:].lower().startswith('-global ') and -1) or
                                       cmp(x,y)))
            dsfs += thisdsfs

        gc.disable()	# work round http://bugs.python.org/issue4074 on Python<2.7
        for dsf in dsfs:
            try:
                (lat, lon, newplacements, nets, mesh) = readDSF(dsf, netdefs, {}, bbox, Exclude.TYPES[exc.name])
                for placement in newplacements:
                    placement.load(self.lookup, self.defs, self.vertexcache, True)
                    placement.layout(self.tile)
                if newplacements:
                    placements = self.placements[self.tile]
                    self.undostack.append(UndoEntry(self.tile, UndoEntry.ADD, [(len(placements), placement) for placement in newplacements]))
                    placements.extend(newplacements)
                    self.selected = set(newplacements)
                    self.selectednode = None
                    self.Refresh()
                    gc.enable()
                    return True
            except:
                if __debug__: print_exc()
        gc.enable()
        return False


    def undo(self):
        # returns new location
        if not self.undostack: return False	# can't happen
        undo=self.undostack.pop()
        self.goto(undo.tile)	# force assignment of placements to layers
        avlat=0
        avlon=0
        self.selected=set()
        self.selectednode=None
        placements=self.placements[undo.tile]

        if undo.kind==UndoEntry.ADD:
            for (i, placement) in undo.data:
                placement.clearlayout()
                placements.pop(i)	# assumes all were added at the same index
                avlat+=placement.lat
                avlon+=placement.lon
        elif undo.kind==UndoEntry.DEL:
            for (i, placement) in undo.data:
                placement.load(self.lookup, self.defs, self.vertexcache, True)
                placement.layout(undo.tile)
                placements.insert(i, placement)
                avlat+=placement.lat
                avlon+=placement.lon
                self.selected.add(placement)
        elif undo.kind in [UndoEntry.MOVE, UndoEntry.MODIFY]:
            for (i, placement) in undo.data:
                placement.load(self.lookup, self.defs, self.vertexcache, True)
                placement.layout(undo.tile)
                placements[i].clearlayout()
                placements[i]=placement
                avlat+=placement.lat
                avlon+=placement.lon
                self.selected.add(placement)
        elif undo.kind==UndoEntry.SPLIT:
            # SPLIT is like a MOVE and ADD
            assert len(undo.data)==2
            (i, placement) = undo.data[0]
            placement.load(self.lookup, self.defs, self.vertexcache, True)
            placement.layout(undo.tile)
            placements[i].clearlayout()
            placements[i] = placement
            avlat = placement.lat*2	# Hack!
            avlon = placement.lon*2
            self.selected.add(placement)
            (i, placement) = undo.data[1]
            placement.clearlayout(self.vertexcache)
            placements.pop(i)
        else:
            assert False, undo.kind
        avlat/=len(undo.data)
        avlon/=len(undo.data)
        self.goto((avlat,avlon))
        return (avlat,avlon)
        
    def clearsel(self):
        if self.selected:
            self.Refresh()
        self.selected=set()
        self.selectednode=None

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

    def nextsel(self, name, withctrl, withshift):
        # returns new location or None
        # we have 0 or more items of the same type selected
        if name.startswith(PolygonDef.EXCLUDE) or not self.lookup[name].file in self.defs:
            return None	# Don't have an easy way of mapping to an ExcludeDef. Placement can't exist in this tile if not loaded.
        definition=self.defs[self.lookup[name].file]
        placements=self.placements[self.tile]
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
        self.selectednode=None
        self.frame.ShowSel()
        return (placement.lat, placement.lon)

    def getsel(self, dms=0, imp=0):
        # return current selection, or average: ([names], location_string, lat, lon, object_hdg)
        if not self.selected: return ([], '', None, None, None)

        if self.selectednode:
            placement=list(self.selected)[0]
            (i,j)=self.selectednode
            return ([placement.name], placement.locationstr(dms, imp, self.selectednode), placement.nodes[i][j].lat, placement.nodes[i][j].lon, None)
        elif len(self.selected)==1:
            placement=list(self.selected)[0]
            if isinstance(placement, Polygon):
                return ([placement.name], placement.locationstr(dms, imp), placement.lat, placement.lon, None)
            else:
                return ([placement.name], placement.locationstr(dms, imp), placement.lat, placement.lon, placement.hdg)
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
            return (names, "%s  (%d objects)" % (Clutter.latlondisp(dms, lat, lon), len(self.selected)), lat, lon, None)

    def getheight(self):
        # return current height
        return self.y

    def reload(self, prefs, airports, navaids, aptdatfile, netdefs, netfile, lookup, placements, terrain, dsfdirs):
        self.valid=False
        self.airports=airports	# [runways] by code
        self.runways={}		# need to re-layout airports
        self.navaids=navaids
        self.navaidplacements={}	# need to re-layout navaids
        self.aptdatfile=aptdatfile
        self.netdefs=netdefs
        self.netfile=netfile	# logical name of .net file used
        self.codes={}		# need to re-layout airports
        if self.codeslist: glDeleteLists(self.codeslist, 1)
        self.codeslist=0
        self.lookup=lookup
        self.defs={}
        self.vertexcache.reset(terrain, dsfdirs)
        self.imagery.reset()
        self.tile=(0,999)	# force reload on next goto

        # load networks - have to do this every reload since texcache has been reset
        if netdefs:
            for netdef in self.netdefs.values():
                self.defs[netdef.name] = NetworkDef(netdef, self.vertexcache, self.lookup, self.defs)

        if placements!=None:
            self.unsorted = placements
        else:
            # invalidate all allocations (note: navaids just get trashed and re-loaded as required)
            self.unsorted = self.placements
            for placements in self.placements.values():
                for placement in placements:
                    placement.clearlayout()
        self.placements={}

        self.background=None	# Force reload of texture in next line
        self.setbackground(prefs)
        self.clipboard = set()	# layers might have changed
        self.undostack=[]	# layers might have changed
        self.selected=set()	# may not have same indices in new list
        self.selectednode=None
        self.locked=0		# reset locked on loading new

        if __debug__:
            print "Frame:\t%s"  % self.frame.GetId()
            print "Toolb:\t%s"  % self.frame.toolbar.GetId()
            print "Parent:\t%s" % self.parent.GetId()
            print "Split:\t%s"  % self.frame.splitter.GetId()
            print "MyGL:\t%s"   % self.GetId()
            print "Palett:\t%s" % self.frame.palette.GetId()
            if 'GetChoiceCtrl' in dir(self.frame.palette):
                print "Choice:\t%s" %self.frame.palette.GetChoiceCtrl().GetId()


    def goto(self, latlon, hdg=None, elev=None, dist=None):
        if __debug__: print "goto", latlon
        if not self.valid: return	# Hack: can get spurious events on Mac during startup (progress dialogs aren't truly modal)
        errdsf=None
        errobjs=[]
        errtexs=[]
        newtile=(int(floor(latlon[0])),int(floor(latlon[1])))	# (lat,lon) of SW corner
        self.centre=[newtile[0]+0.5, newtile[1]+0.5]
        (self.x, self.z)=self.latlon2m(latlon[0],latlon[1])
        if hdg!=None: self.h=hdg
        if elev!=None: self.e=elev
        if dist!=None: self.d=dist

        if newtile!=self.tile or prefs.options&Prefs.REDRAW!=self.options&Prefs.REDRAW:
            if newtile!=self.tile:
                self.selected=set()
                self.selectednode=None
                self.frame.ShowSel()
            self.valid=False
            self.tile=newtile
            self.vertexcache.flush()	# clear VBOs
            # forget all instance VBO allocations
            for Def in self.defs.values(): Def.flush()
            self.selections=set()

            progress=wx.ProgressDialog('Loading', 'Terrain', 16, self.frame)
            progress.SetSize
            self.vertexcache.loadMesh(newtile, self.netdefs)

            progress.Update(1, 'Terrain textures')
            try:
                self.vertexcache.getMesh(newtile)	# allocates into VBO
            except EnvironmentError, e:
                if __debug__: print_exc()
                if e.filename:
                    errdsf=u"%s: %s" % (e.filename, e.strerror)
                else:
                    errdsf=unicode(e)
                self.vertexcache.loadFallbackMesh(newtile)
                self.vertexcache.getMesh(newtile)
            except:
                if __debug__: print_exc()
                errdsf=unicode(exc_info()[1])
                self.vertexcache.loadFallbackMesh(newtile)
                self.vertexcache.getMesh(newtile)

            progress.Update(2, 'Mesh')

            if prefs.options&Prefs.ELEVATION!=self.options&Prefs.ELEVATION:
                # Elevation preference chaged - clear all layout (other than airports)
                for placements in self.placements.values() + self.navaidplacements.values():
                    for placement in placements:
                        placement.clearlayout()
            else:
                # Just a new tile - forget all dynamic VBO allocation
                for placements in self.placements.values() + self.navaidplacements.values():
                    for placement in placements:
                        placement.flush()
                
            # load placements
            progress.Update(3, 'Objects')
            if newtile in self.unsorted:
                if log_load: clock=time.clock()	# Processor time
                placements = self.placements[newtile] = self.unsorted.pop(newtile)
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
                        s=u"%s: %s" % placement.definition.texerr
                        if not s in errtexs: errtexs.append(s)
                        
                    if not placement.islaidout():
                        if __debug__: clock2 = time.clock()
                        placement.layout(newtile)
                        if __debug__: print "%6.3f time to layout %s" % (time.clock()-clock2, placement.name)
                if log_load: print "%6.3f time in load&layout" % (time.clock()-clock)
            elif newtile not in self.placements:
                self.placements[newtile]=[]
            else:
                # This tile has been previously viewed - placements are already loaded
                for placement in self.placements[newtile]:
                    placement.layout(newtile, recalc=False)	# ensure allocated

            # Lay out runways
            progress.Update(13, 'Airports')
            key=(newtile[0],newtile[1],prefs.options&Prefs.ELEVATION)
            if key not in self.runways:
                if log_load: clock=time.clock()	# Processor time
                (self.runways[key], self.codes[newtile]) = layoutApt(newtile, self.aptdatfile, self.airports, self.vertexcache.getElevationMesh(newtile))
                if log_load: print "%6.3f time in runways" % (time.clock()-clock)
            (varray,shoulderlen,taxiwaylen,runwaylen,marray,mindices) = self.runways[key]
            self.aptdata = {}
            if shoulderlen:
                self.aptdata[ClutterDef.SHOULDERLAYER] = (self.vertexcache.instance_count, shoulderlen)
            if taxiwaylen:
                self.aptdata[ClutterDef.TAXIWAYLAYER]  = (self.vertexcache.instance_count+shoulderlen, taxiwaylen)
            if runwaylen:
                self.aptdata[ClutterDef.RUNWAYSLAYER]  = (self.vertexcache.instance_count+shoulderlen+taxiwaylen, runwaylen)
            if len(varray):
                if __debug__:
                    for p in varray: assert p.dtype==float32 and len(p)==6, p
                self.vertexcache.allocate_instance(vstack(varray)[:,:5].flatten())	# instance VBO has 5 coords
            if marray:
                if __debug__:
                    for p in marray: assert p.dtype==float32 and p.shape[1]==6, p
                base = self.vertexcache.allocate_vector(vstack(marray).flatten())
                self.aptdata[ClutterDef.MARKINGSLAYER] = (base + mindices)

            progress.Update(14, 'Navaids')
            assert self.tile==newtile
            if self.tile not in self.navaidplacements:
                if __debug__: clock=time.clock()	# Processor time
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
                placements=[]
                for (i, lat, lon, hdg) in self.navaids:
                    if (int(floor(lat)),int(floor(lon)))==self.tile:
                        if i in objs:
                            coshdg=cos(radians(hdg))
                            sinhdg=sin(radians(hdg))
                            if i==211:
                                seq=[(1,75),(-1,75),(1,-75),(-1,-75)]
                            elif i in range(212,215):
                                seq=[(12,0),(4,0),(-4,0),(-12,0)]
                            else:
                                seq=[(0,0)]
                            for (xinc,zinc) in seq:
                                placement=Object(objs[i], lat, lon, hdg)
                                if not placement.load(self.lookup, self.defs, self.vertexcache, False):
                                    if __debug__: print "Missing navaid %s" % objs[i]
                                else:
                                    if __debug__: clock2 = time.clock()
                                    x,z=placement.position(self.tile, lat, lon)
                                    placement.layout(self.tile, x+xinc*coshdg-zinc*sinhdg, None, z+xinc*sinhdg+zinc*coshdg)
                                    if __debug__: print "%6.3f time to layout %s" % (time.clock()-clock2, placement.name)
                                    placements.append(placement)
                        elif __debug__: print "Missing navaid type %d" % i
                self.navaidplacements[self.tile]=placements
                if __debug__: print "%6.3f time in navaids" % (time.clock()-clock)
            else:
                # This tile has been previously viewed - placements are already loaded
                for placement in self.navaidplacements[newtile]:
                    placement.layout(newtile, recalc=False)	# ensure allocated

            # labels
            progress.Update(15, 'Layout')
            if self.codeslist:
                glDeleteLists(self.codeslist, 1)
                self.codeslist=0
            if __debug__ and platform=='win32':
                pass	# hacky workaround for https://www.virtualbox.org/ticket/8666
            elif self.codes[self.tile]:
                elev = self.vertexcache.getElevationMesh(self.tile)
                self.codeslist=glGenLists(1)
                glNewList(self.codeslist, GL_COMPILE)
                glColor3f(1.0, 0.25, 0.25)	# Labels are pink
                glBindTexture(GL_TEXTURE_2D, 0)
                for (code, (lat,lon)) in self.codes[self.tile]:
                    (x,z)=self.latlon2m(lat,lon)
                    glRasterPos3f(x, elev.height(x,z), z)
                    code=code.encode('latin1', 'replace')
                    for c in code:
                        glBitmap(8,13, 16,6, 8,0, fixed8x13[ord(c)])
                glEndList()

            # Background image - always recalc since may span multiple tiles
            if self.background:
                nodes=self.background.nodes[0]
                for i in range(len(nodes)):
                    if (int(floor(nodes[i].lat)),int(floor(nodes[i].lon)))==newtile:
                        self.background.layout(newtile)
                        break
                else:
                    self.background.clearlayout()
            self.imagery.reset()	# Always recalc

            # Done
            progress.Update(16, 'Done')
            progress.Destroy()
            self.valid=True

        self.options = prefs.options

        # cursor position
        self.y = self.vertexcache.getElevationMesh(self.tile).height(self.x, self.z)

        # initiate imagery load. Does layout so must be after getMeshdata.
        # Python isn't really multithreaded so don't delay reload by initiating this earlier
        self.imagery.goto(prefs.imageryprovider, latlon, self.d, self.GetClientSize())

        # Redraw can happen under MessageBox, so do this last
        if errdsf:
            myMessageBox(errdsf, "Can't load terrain.", wx.ICON_EXCLAMATION|wx.OK, self.frame)

        if errobjs:
            sortfolded(errobjs)
            if len(errobjs)>11: errobjs=errobjs[:10]+['and %d more objects' % (len(errobjs)-10)]
            myMessageBox('\n'.join(errobjs), "Can't read one or more objects.", wx.ICON_EXCLAMATION|wx.OK, self.frame)

        if errtexs:
            sortfolded(errtexs)
            if len(errtexs)>11: errtexs=errtexs[:10]+['and %d more textures' % (len(errtexs)-10)]
            myMessageBox('\n'.join(errtexs), "Can't read one or more textures.", wx.ICON_INFORMATION|wx.OK, self.frame)

        self.Refresh()

    def exit(self):
        # closing down
        self.imagery.exit()

    def getlocalloc(self, mx, my):
        if not self.valid: raise Exception        # MouseWheel can happen under MessageBox
        if wx.VERSION >= (2,9):
            self.SetCurrent(self.context)
        else:
            self.SetCurrent()
        size = self.GetClientSize()
        mx=max(0, min(size[0]-1, mx))
        my=max(0, min(size[1]-1, size[1]-1-my))
        self.glstate.set_instance(self.vertexcache)
        self.glstate.set_texture(self.vertexcache.texcache.get(fallbacktexture))	# textured shader. ATI drivers don't like 0
        self.glstate.set_depthtest(True)
        self.glstate.set_poly(False)	# DepthMask=True
        glColorMask(GL_FALSE,GL_FALSE,GL_FALSE,GL_FALSE)
        if prefs.options&Prefs.ELEVATION:
            for (base,number,texno) in self.vertexcache.getMesh(self.tile)[0]:
                glDrawArrays(GL_TRIANGLES, base, number)
        else:
            glBegin(GL_QUADS)
            glVertex3f( onedeg*cos(radians(1+self.tile[0]))/2, 0, -onedeg/2)
            glVertex3f( onedeg*cos(radians(self.tile[0]))/2, 0,  onedeg/2)
            glVertex3f(-onedeg*cos(radians(self.tile[0]))/2, 0,  onedeg/2)
            glVertex3f(-onedeg*cos(radians(1+self.tile[0]))/2, 0, -onedeg/2)
            glEnd()
        mz=glReadPixelsf(mx,my, 1,1, GL_DEPTH_COMPONENT)[0][0]
        if mz==1.0: mz=0.5	# treat off the tile edge as sea level
        (x,y,z)=gluUnProject(mx,my,mz, identity(4, float64), self.glstate.proj, array([0,0,size[0],size[1]], GLint))
        glColorMask(GL_TRUE,GL_TRUE,GL_TRUE,GL_TRUE)
        #self.SwapBuffers()	# debug
        glClear(GL_DEPTH_BUFFER_BIT)
        #if __debug__: print "%3d %3d %.6f, %5d %5.1f %5d" % (mx,my,mz, x,y,z)
        return (x,y,z)

    def xz2latlon(self, x, z):
        lat=round2res(self.centre[0]-z/onedeg)
        lon=round2res(self.centre[1]+x/(onedeg*cos(radians(lat))))
        #if __debug__: print "%11.7f %12.7f" % (lat,lon)
        return (lat,lon)

    def getworldloc(self, mx, my):
        (x,y,z)=self.getlocalloc(mx, my)
        return self.xz2latlon(x,z)


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

