from math import cos, sin, floor, pi
from OpenGL.GL import *
from OpenGL.GLU import *
from os.path import join
from struct import unpack
from sys import platform, maxint
import wx.glcanvas

from files import appname, VertexCache, sortfolded

onedeg=1852*60	# 1 degree of longitude at equator (60nm) [m]
d2r=pi/180.0
f2m=0.3048	# 1 foot [m]

sband=12	# width of mouse scroll band around edge of window

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
        self.tile=[0,999]	# [lat,lon] of SW
        self.centre=None	# [lat,lon] of centre
        self.airports={}	# (lat,lon,hdg,length,width) by code
        self.runways={}		# (bbox,  [points], xwidth, zwidth) by tile
        self.runwayslist=0
        self.placements={}	# [(name,lat,lon,hdg,height)] by tile
        self.objectslist=0
        self.baggage={}		# (props, other) by tile
        self.background=None
        self.meshlist=0
        self.meshpicklist=0
        
        self.selected=[]	# Indices into placements[self.tile]
        self.selections=[]	# List for picking
        self.selectlist=0
        self.selectctrl=False	# Ctrl/Cmd was held down
        self.selectanchor=None	# Start of drag
        self.selectsaved=None	# Selection at start of drag        
        self.mousenow=None	# Current position

        self.undostack=[]

        # Values during startup
        self.x=0
        self.y=0
        self.z=0
        self.h=0
        self.e=90
        self.d=3333.25

        # Must specify min sizes for glX - see glXChooseVisual and GLXFBConfig
        wx.glcanvas.GLCanvas.__init__(self, parent,
                                      style=GL_RGBA|GL_DOUBLEBUFFER|GL_DEPTH|wx.FULL_REPAINT_ON_RESIZE, attribList=[
            wx.glcanvas.WX_GL_RGBA,
            wx.glcanvas.WX_GL_DOUBLEBUFFER,
            wx.glcanvas.WX_GL_MIN_RED, 4,
            wx.glcanvas.WX_GL_MIN_GREEN, 4,
            wx.glcanvas.WX_GL_MIN_BLUE, 4,
            wx.glcanvas.WX_GL_MIN_ALPHA, 4,
            wx.glcanvas.WX_GL_DEPTH_SIZE, 32])	# 32bit depth buffer must be specified for ATI on Mac 

        # Must be after init
        if glGetString(GL_VERSION) >= '1.2':
            clampmode=0x812F	# GL_CLAMP_TO_EDGE
        else:
            clampmode=GL_REPEAT
        self.vertexcache=VertexCache(clampmode)	# member so can free resources

        wx.EVT_PAINT(self, self.OnPaint)
        wx.EVT_ERASE_BACKGROUND(self, self.OnEraseBackground)
        wx.EVT_KEY_DOWN(self, self.OnKeyDown)
        wx.EVT_MOUSEWHEEL(self, self.OnMouseWheel)
        wx.EVT_MOTION(self, self.OnMouseMotion)
        wx.EVT_LEFT_DOWN(self, self.OnLeftDown)
        wx.EVT_LEFT_UP(self, self.OnLeftUp)
        #wx.EVT_KILL_FOCUS(self, self.OnKill)	# debug
        
        self.timer=wx.Timer(self, wx.ID_ANY)
        wx.EVT_TIMER(self, self.timer.GetId(), self.OnTimer)

        glClearColor(0.5, 0.5, 1.0, 0.0)	# Sky
        #glClearDepth(1.0)
        glDepthFunc(GL_LESS)
        glEnable(GL_DEPTH_TEST)
        glFrontFace(GL_CW)
        glShadeModel(GL_FLAT)
        #glLineStipple(1, 0x0f0f)	# for selection drag
        glCullFace(GL_BACK)
        glPixelStorei(GL_UNPACK_ALIGNMENT,1)
        #glPixelStorei(GL_UNPACK_LSB_FIRST,1)
        glEnable(GL_TEXTURE_2D)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
        glEnable(GL_BLEND)
	glEnableClientState(GL_VERTEX_ARRAY)
	glEnableClientState(GL_TEXTURE_COORD_ARRAY)
        glLoadIdentity()


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
        event.Skip()	# do focus change
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
        if self.selectanchor:
            self.selectanchor=None
            self.Refresh()	# get rid of drag box
        else:
            self.timer.Stop()
        self.SetCursor(wx.NullCursor)
        event.Skip()
            
    def OnMouseMotion(self, event):
        if (self.timer.IsRunning() or self.selectanchor) and not event.LeftIsDown():
            # Capture unreliable on Mac, so may have missed LeftUp event. See
            # https://sourceforge.net/tracker/?func=detail&atid=109863&aid=1489131&group_id=9863
            self.OnLeftUp(event)
            return

        if self.timer.IsRunning():
            # Continue mouse scroll
            self.mousenow=[event.m_x,event.m_y]	# not known in timer and paint
            return

        if event.LeftIsDown() and not self.selectanchor:
            # Start selection drag
            self.SetCursor(self.dragcursor)
            self.selectanchor=self.mousenow		# location of LeftDown
            self.selectsaved=self.selected
            
        if self.selectanchor:
            # Continue selection drag            
            self.mousenow=[event.m_x,event.m_y]	# not known in timer and paint
            self.selected=list(self.selectsaved)	# reset each time
            self.select()
        else:
            size = self.GetClientSize()
            if event.m_x<sband or event.m_y<sband or size.x-event.m_x<sband or size.y-event.m_y<sband:
                self.SetCursor(self.movecursor)
            else:
                self.SetCursor(wx.NullCursor)

    def OnPaint(self, event):
        dc = wx.PaintDC(self)	# Tell the window system that we're on the case
        self.SetCurrent()
        glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT)

        glMatrixMode(GL_PROJECTION)
        size = self.GetClientSize()
        glViewport(0, 0, size.width, size.height)
        glLoadIdentity()
	# try to minimise near offset to improve clipping
        glOrtho(-self.d, self.d,
                -self.d*size.y/size.x, self.d*size.y/size.x,
                -max(10000,onedeg*(self.d/3333.25)), onedeg)
        
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
            return

        placement=self.currentplacements()

        #glPolygonMode(GL_FRONT, GL_LINE)	# XXX
        #glDisable(GL_CULL_FACE)	# XXX
        
        # Ground
        if not self.meshlist:
            self.vertexcache.realize()
            self.meshlist=glGenLists(1)
            glNewList(self.meshlist, GL_COMPILE)
            glEnable(GL_DEPTH_TEST)
            glColor3f(0.75, 0.75, 0.75)	# Unpainted
            for (base,culled,texno) in self.vertexcache.getMesh(self.tile):
                glBindTexture(GL_TEXTURE_2D, texno)
                glDrawArrays(GL_TRIANGLES, base, culled)
            glEndList()
        glCallList(self.meshlist)

        # Runways
        if not self.runwayslist:
            self.runwayslist=glGenLists(1)
            glNewList(self.runwayslist, GL_COMPILE)
            glDisable(GL_TEXTURE_2D)
            glPolygonOffset(-10, -100)	# Stupid value cos not co-planar
            glEnable(GL_POLYGON_OFFSET_FILL)
            glDepthMask(GL_FALSE)	# Don't let poly offset update depth
            # Runways
            glColor3f(0.333,0.333,0.333)
            for (runway, xinc, zinc) in self.runways[(self.tile[0],self.tile[1])]:
                glBegin(GL_QUAD_STRIP)
                for p in runway:
                    glVertex3f(p[0]+xinc, p[1], p[2]+zinc)
                    glVertex3f(p[0]-xinc, p[1], p[2]-zinc)
                glEnd()
            glEndList()
        glCallList(self.runwayslist)

        # Objects
        if not self.objectslist:
            self.vertexcache.realize()
            self.objectslist=glGenLists(1)
            glNewList(self.objectslist, GL_COMPILE)
            glColor3f(0.75, 0.75, 0.75)	# Unpainted
            glEnable(GL_TEXTURE_2D)
            glEnable(GL_CULL_FACE)
            glEnable(GL_DEPTH_TEST)
            glDepthMask(GL_TRUE)
            glDisable(GL_POLYGON_OFFSET_FILL)
            cullstate=True
            polystate=0
            for i in range(len(placement)):
                (obj, lat, lon, hdg,height)=placement[i]
                (x,z)=self.latlon2m(lat, lon)
                (base,culled,nocull,texno,poly)=self.vertexcache.getObj(obj)
                if poly:
                    if polystate!=poly:
                        glPolygonOffset(-1*poly, -1*poly)
                        glEnable(GL_POLYGON_OFFSET_FILL)
                    polystate=poly
                else:
                    if polystate: glDisable(GL_POLYGON_OFFSET_FILL)
                    polystate=0
                glPushMatrix()
                glTranslatef(x, height, z)
                glRotatef(-hdg, 0.0,1.0,0.0)
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
        glDisable(GL_DEPTH_TEST)

        # Background
        if self.background:
            (image, lat, lon, hdg, width, length, opacity, height)=self.background
            if [int(floor(lat)),int(floor(lon))]==self.tile:
                texno=self.vertexcache.texcache.get(image)
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
        glPushMatrix()
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
        glPopMatrix()

        # Selections
        if not self.frame.bkgd:
            # Don't show if setting background image
            glColor3f(1.0, 0.5, 1.0)
            glDisable(GL_CULL_FACE)
            glEnable(GL_DEPTH_TEST)
            glEnable(GL_POLYGON_OFFSET_FILL)
            glPolygonOffset(-5, -5)
            for i in self.selected:
                # assumes cache is already properly set up
                (obj, lat, lon, hdg, height)=placement[i]
                (x,z)=self.latlon2m(lat, lon)
                (base,culled,nocull,texno,poly)=self.vertexcache.getObj(obj)
                glPushMatrix()
                glTranslatef(x, height, z)
                glRotatef(-hdg, 0.0,1.0,0.0)
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

	# drag box
        if self.selectanchor:
            glPushMatrix()
            glColor3f(0.25, 0.125, 0.25)
            glDisable(GL_TEXTURE_2D)
            glMatrixMode(GL_PROJECTION)
            glLoadIdentity()
            glMatrixMode(GL_MODELVIEW)
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

        glDisable(GL_POLYGON_OFFSET_FILL)	# needed

        # Display
        self.SwapBuffers()

        # Pre-prepare selection list
        if not self.selectlist:
            self.selectlist=glGenLists(1)
            glNewList(self.selectlist, GL_COMPILE)
            glInitNames()
            glPushName(0)
            glDisable(GL_TEXTURE_2D)
            glDisable(GL_DEPTH_TEST)
            glDisable(GL_CULL_FACE)
            for i in range(len(placement)):
                (obj, lat, lon, hdg, height)=placement[i]
                glLoadName(i)
                (x,z)=self.latlon2m(lat, lon)
                (base,culled,nocull,texno,poly)=self.vertexcache.getObj(obj)
                glPushMatrix()
                glTranslatef(x, height, z)
                glRotatef(-hdg, 0.0,1.0,0.0)
                glDrawArrays(GL_TRIANGLES, base, culled+nocull)
                glPopMatrix()
            glEndList()
        

    def select(self):
        if not self.currentplacements():
            self.selections=[]	# Can't remember

        glSelectBuffer(65536)	# number of objects appears to be this/4
        glRenderMode(GL_SELECT)

        glMatrixMode(GL_PROJECTION)
        size = self.GetClientSize()
        glViewport(0, 0, *size)
        glLoadIdentity()
        viewport=glGetIntegerv(GL_VIEWPORT)
        if self.selectanchor:	# drag
            # maths goes wrong if zero-sized box
            if self.selectanchor[0]==self.mousenow[0]: self.mousenow[0]+=1
            if self.selectanchor[1]==self.mousenow[1]: self.mousenow[1]+=1
            gluPickMatrix((self.selectanchor[0]+self.mousenow[0])/2,
                          viewport[3]-(self.selectanchor[1]+self.mousenow[1])/2,
                          abs(self.selectanchor[0]-self.mousenow[0]),
                          abs(self.selectanchor[1]-self.mousenow[1]),
                          viewport)
        else:	# click
            gluPickMatrix(self.mousenow[0],
                          viewport[3]-self.mousenow[1], 3,3, viewport)
        glOrtho(-self.d, self.d,
                -self.d*size.y/size.x, self.d*size.y/size.x,
                -onedeg, onedeg)
        
        glMatrixMode(GL_MODELVIEW)
        glLoadIdentity()
        glRotatef(self.e, 1.0,0.0,0.0)
        glRotatef(self.h, 0.0,1.0,0.0)
        glTranslatef(-self.x, -self.y, -self.z)

        glCallList(self.selectlist)

        selections=[]
        try:
            for min_depth, max_depth, (names,) in glRenderMode(GL_RENDER):
                selections.append(int(names))
        except:	# overflow
            pass

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

    def currentplacements(self):
        key=(self.tile[0],self.tile[1])
        if key in self.placements:
            return self.placements[key]
        else:
            return []
    
    def setbackground(self, background):
        if background:
            (image, lat, lon, hdg, width, length, opacity)=background
            if [int(floor(lat)),int(floor(lon))]==self.tile:
                (x,z)=self.latlon2m(lat,lon)
                height=self.vertexcache.height(self.tile,x,z)
            else:
                height=None
            self.background=(image, lat, lon, hdg, width, length, opacity, height)
        else:
            self.background=None
        self.Refresh()

    def add(self, obj, lat, lon, hdg):
        if not self.vertexcache.loadObj(obj):
            if platform=='darwin':
                wx.MessageBox("Can't read %s." % obj, 'Cannot add this object.', wx.ICON_QUESTION|wx.OK, self.frame)
            else:
                wx.MessageBox("Cannot add this object.\n\nCan't read %s." % obj, appname, wx.ICON_HAND|wx.OK, self.frame)
            return False
        self.trashlists(False)
        (base,culled,nocull,texno,poly)=self.vertexcache.getObj(obj)	# for poly
        (x,z)=self.latlon2m(lat,lon)
        height=self.vertexcache.height(self.tile,x,z)
        placement=self.currentplacements()
        if poly:
            self.selected=[0]
            placement.insert(0, (obj, lat, lon, hdg, height))
        else:
            self.selected=[len(placement)]
            placement.append((obj, lat, lon, hdg, height))
        self.undostack.append(UndoEntry(self.tile, UndoEntry.ADD,
                                        self.selected))
        self.Refresh()
        self.frame.ShowSel()
        return True

    def movesel(self, dlat, dlon, dhdg):
        # returns True if changed something
        if not self.selected: return False
        self.trashlists(False)
        placement=self.currentplacements()        
        moved=[]
        for i in self.selected:
            moved.append((i, placement[i]))
            (obj, lat, lon, hdg, height)=placement[i]
            lat=round(lat+dlat,6)
            lon=round(lon+dlon,6)
            hdg=round(hdg+dhdg,0)%360
            (x,z)=self.latlon2m(lat,lon)
            height=self.vertexcache.height(self.tile,x,z)
            placement[i]=(obj, lat, lon, hdg, height)
        self.placements[(self.tile[0],self.tile[1])]=placement
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

    def clearsel(self):
        self.selected=[]
        self.Refresh()

    def allsel(self, withctrl):
        # fake up mouse drag
        self.selectanchor=[0,0]
        self.selectctrl=withctrl
        size=self.GetClientSize()
        self.mousenow=[size.x-1,size.y-1]
        self.select()
        self.selectanchor=None

    def delsel(self):
        # returns True if deleted something
        if not self.selected: return False
        self.trashlists(False)
        placement=self.currentplacements()
        deleted=[]
        for i in self.selected:
            deleted.append((i, placement[i]))
        self.undostack.append(UndoEntry(self.tile, UndoEntry.DEL, deleted))
        newplace=[]
        for i in range(len(placement)):
            if not i in self.selected:
                newplace.append(placement[i])
        self.placements[(self.tile[0],self.tile[1])]=newplace
        self.selected=[]
        self.Refresh()
        self.frame.ShowSel()
        return True

    def getsel(self):
        # return current selection, or average
        if not self.selected: return None
        placement=self.currentplacements()
        lat=lon=0
        obj=[]
        for i in self.selected:
            (obj1, lat1, lon1, hdg, height)=placement[i]
            obj.append(obj1)
            lat+=lat1
            lon+=lon1
        return ((obj, lat/len(self.selected), lon/len(self.selected), hdg, height))

    def reload(self, reload, airports, objects, placements, baggage,
               background, terrain, dsfdir):
        self.valid=False
        self.airports=airports
        self.vertexcache.flushObjs(objects, terrain, dsfdir)
        self.tile=[0,999]	# force reload
        if placements!=None:
            self.placements=placements
            self.baggage=baggage
        if background:
            (image, lat, lon, hdg, width, length, opacity)=background
            self.background=(image, lat, lon, hdg, width, length, opacity,None)
        else:
            self.background=None
        self.trashlists(True)	# need to re-layout runways
        self.runways={}
        self.selected=[]	# may not have same indices in new list
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

    def undo(self):
        # returns True if undostack still not empty
        if not self.undostack: return False	# can't happen
        undo=self.undostack.pop()
        placement=self.placements[undo.tile[0],undo.tile[1]]
        avlat=0
        avlon=0
        self.trashlists(False)
        self.selected=[]
        if undo.kind==UndoEntry.ADD:
            for i in undo.data:
                (obj, lat, lon, hdg, height)=placement[i]
                avlat+=lat
                avlon+=lon
                placement.pop(i)
        elif undo.kind==UndoEntry.DEL:
            for (i, p) in undo.data:
                (obj, lat, lon, hdg, height)=p
                if not self.vertexcache.loadObj(obj, True):	# may have reloaded
                    if platform=='darwin':
                        wx.MessageBox("Can't read %s." % obj, 'Using a placeholder object.', wx.ICON_QUESTION|wx.OK, self.frame)
                    else:
                        wx.MessageBox("Using a placeholder object.\n\nCan't read %s." % obj, appname, wx.ICON_EXCLAMATION|wx.OK, self.frame)
                avlat+=lat
                avlon+=lon
                placement.insert(i, p)
                self.selected.append(i)
        elif undo.kind==UndoEntry.MOVE:
            for (i, p) in undo.data:
                (obj, lat, lon, hdg, height)=p
                avlat+=lat
                avlon+=lon
                placement[i]=p
                self.selected.append(i)
        avlat/=len(undo.data)
        avlon/=len(undo.data)
        self.goto([avlat,avlon])
        self.frame.loc=[avlat,avlon]
        self.frame.ShowLoc()
        self.frame.ShowSel()
        return self.undostack!=[]
        
    def goto(self, loc, hdg=None, elev=None, dist=None):
        errobjs=[]
        newtile=[int(floor(loc[0])),int(floor(loc[1]))]
        self.centre=[newtile[0]+0.5, newtile[1]+0.5]
        (self.x, self.z)=self.latlon2m(loc[0],loc[1])
        if hdg!=None: self.h=hdg
        if elev!=None: self.e=elev
        if dist!=None: self.d=dist

        if newtile!=self.tile:
            self.frame.ShowSel()
            self.valid=False
            self.tile=newtile
            self.vertexcache.flush()
            self.trashlists(True, True)
            self.selected=[]
            key=(newtile[0],newtile[1])
            progress=wx.ProgressDialog('Loading', 'Terrain', 17, self, wx.PD_APP_MODAL)
            self.vertexcache.loadMesh(newtile)

            progress.Update(1, 'Terrain textures')
            self.vertexcache.getMesh(newtile)	# allocates into array

            progress.Update(2, 'Mesh')
            self.vertexcache.getMeshdata(newtile)
                
            # Limit progress dialog to 10 updates
            placement=self.currentplacements()
            p=len(placement)/10+1
            n=0
            i=0
            for i in range(len(placement)):
                if i==n:
                    progress.Update(3+i/p, 'Objects')
                    n+=p
                (obj, lat, lon, h, height)=placement[i]
                if not self.vertexcache.loadObj(obj,True) and not obj in errobjs:
                    errobjs.append(obj)
                if height==None:
                    (x,z)=self.latlon2m(lat,lon)
                    placement[i]=(obj, lat, lon, h,
                                  self.vertexcache.height(newtile,x,z))

            # Lay out runways
            progress.Update(13, 'Placing runways')
            if key not in self.runways:
                airports=[]
                for apt in self.airports.values():
                    (lat,lon,h,length,width)=apt[0]
                    if [int(floor(lat)),int(floor(lon))]!=newtile: continue
                    minx=minz=maxint
                    maxx=maxz=-maxint
                    runways=[]
                    for (lat,lon,h,length,width) in apt:
                        (cx,cz)=self.latlon2m(lat,lon)
                        length=f2m*length/2
                        width=f2m*width/2
                        h=d2r*h
                        coshdg=cos(h)
                        sinhdg=sin(h)
                        p1=[cx-length*sinhdg, 0, cz+length*coshdg]
                        p2=[cx+length*sinhdg, 0, cz-length*coshdg]
                        minx=min(minx, p1[0], p2[0])
                        maxx=max(maxx, p1[0], p2[0])
                        minz=min(minz, p1[2], p2[2])
                        maxz=max(maxz, p1[2], p2[2])
                        runways.append((p1,p2, width*coshdg,width*sinhdg, {}))
                    airports.append(([minx, maxx, minz, maxz], runways))
    
                for (bbox, tris) in self.vertexcache.getMeshdata(newtile):
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
                                    p1[1]=self.vertexcache.height(newtile,p1[0],p1[2],tri)
                                if i2:	# p2 is enclosed by this tri
                                    p2[1]=self.vertexcache.height(newtile,p2[0],p2[2],tri)
                # strip out bounding box and add cuts
                points=[]
                for (abox, runways) in airports:
                    for (p1, p2, xinc, zinc, cuts) in runways:
                        a=cuts.keys()
                        a.sort()
                        r=[p1]
                        if len(a) and a[0]>0.01: r.append(cuts[a[0]])
                        for i in range(1, len(a)):
                            if a[i]-a[i-1]>0.01: r.append(cuts[a[i]])
                        r.append(p2)
                        points.append((r, xinc, zinc))
                self.runways[key]=points
            
            # Done
            if self.background:
                (image, lat, lon, hdg, width, length, opacity, height)=self.background
                if [int(floor(lat)),int(floor(lon))]==self.tile:
                    (x,z)=self.latlon2m(lat,lon)
                    height=self.vertexcache.height(self.tile,x,z)
                else:
                    height=None
                self.background=(image, lat, lon, hdg, width, length, opacity, height)
            progress.Destroy()
            self.valid=True

        # cursor position
        self.y=self.vertexcache.height(self.tile,self.x,self.z)

        # Redraw can happen under MessageBox, so do this last
        if errobjs:
            sortfolded(errobjs)
            if platform=='darwin':
                wx.MessageBox(str('\n'.join(errobjs)), "Can't read one or more objects.", wx.ICON_QUESTION|wx.OK, self.frame)
            else:
                wx.MessageBox("Can't read one or more objects:\n\n  %s" % '\n  '.join(errobjs), appname, wx.ICON_EXCLAMATION|wx.OK, self.frame)

        self.Refresh()

    def trashlists(self, runwaystoo, terraintoo=False):
        if terraintoo:
            if self.meshpicklist: glDeleteLists(self.meshpicklist, 1)
            self.meshpicklist=0
        if runwaystoo:
            if self.runwayslist: glDeleteLists(self.runwayslist, 1)
            self.runwayslist=0
        if self.objectslist: glDeleteLists(self.objectslist, 1)
        self.objectslist=0
        if self.selectlist: glDeleteLists(self.selectlist, 1)
        self.selectlist=0
        if self.meshlist: glDeleteLists(self.meshlist, 1)
        self.meshlist=0
