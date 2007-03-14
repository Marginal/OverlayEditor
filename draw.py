from math import cos, sin, floor, pi
from OpenGL.GL import *
from OpenGL.GLU import *
from os.path import join
from sys import platform
import wx.glcanvas

from files import appname, ObjCache, sortfolded

onedeg=1852*60	# 1 degree of longitude at equator (60nm) [m]
d2r=pi/180.0
f2m=0.3048	# 1 foot [m]

sband=12	# width of mouse scroll band around edge of window

UNDOADD=0
UNDODEL=1
UNDOMOVE=2


# OpenGL Window
class MyGL(wx.glcanvas.GLCanvas):
    def __init__(self, parent, frame):

        self.parent=parent
        self.frame=frame
        self.movecursor=wx.StockCursor(wx.CURSOR_HAND)
        self.dragcursor=wx.StockCursor(wx.CURSOR_CROSS)

        self.tile=[999,999]	# [lat,lon] of SW
        self.centre=None	# [lat,lon] of centre
        self.runways={}		# (lat,lon,hdg,length,width) by code
        self.runwayslist=0
        self.placements={}	# [(name,lat,lon,hdg)] by tile
        self.objectslist=0
        self.baggage={}		# (props, other) by tile

        self.objcache=ObjCache()	# member so can free resources

        self.selected=[]	# Indices into placements[self.tile]
        self.selections=[]	# List for picking
        self.selectctrl=False	# Ctrl/Cmd was held down
        self.selectanchor=None	# Start of drag
        self.selectsaved=None	# Selection at start of drag        
        self.mousenow=None	# Current position

        self.undostack=[]
        
        self.x=0
        self.z=0
        self.h=0
        self.e=1
        self.d=1
        
        wx.glcanvas.GLCanvas.__init__(self, parent, style=GL_RGBA|GL_DOUBLEBUFFER|GL_DEPTH|wx.FULL_REPAINT_ON_RESIZE)
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
        glClearDepth(1.0)
        glDepthFunc(GL_LESS)
        glFrontFace(GL_CW)
        glShadeModel(GL_FLAT)
        #glLineStipple(1, 0x0f0f)	# for selection drag
        glCullFace(GL_BACK)
        glPixelStorei(GL_UNPACK_ALIGNMENT,1)
        glEnable(GL_TEXTURE_2D)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
        glEnable(GL_BLEND)
	glEnableClientState(GL_VERTEX_ARRAY)
	glEnableClientState(GL_TEXTURE_COORD_ARRAY)
        glLoadIdentity()

    def OnPaint(self, event):
        dc = wx.PaintDC(self)	# Tell the window system that we're on the case
        self.SetCurrent()
        glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT)
        self.redraw(GL_RENDER)

    def OnEraseBackground(self, event):
        pass	# Prevent flicker when resizing / painting

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

    def OnKill(self, event):
        if event.GetWindow():
            print "kill -> %s" % event.GetWindow().GetId(),
        else:
            print "kill -> None"
        self.OnLeftUp(event)
        
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


    def select(self):
        glSelectBuffer(65536)	# numer of objects appears to be this/4
        glRenderMode(GL_SELECT)

        self.redraw(GL_SELECT)

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
        
    def redraw(self, mode):
        glMatrixMode(GL_PROJECTION)
        size = self.GetClientSize()
        glViewport(0, 0, *size)
        glLoadIdentity()
        if mode==GL_SELECT:
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
        glTranslatef(-self.x, 0.0, -self.z)

        placement=self.currentplacements()

        # Ground
        if mode!=GL_SELECT:
            if not self.runwayslist:
                self.runwayslist=glGenLists(1)
                glNewList(self.runwayslist, GL_COMPILE)
                # Ground
                glBindTexture(GL_TEXTURE_2D, 0)
                glDisable(GL_DEPTH_TEST)
                glEnable(GL_CULL_FACE)
                glColor3f(0.25, 0.5, 0.25)
                glBegin(GL_QUADS)
                glVertex3f( onedeg*cos(d2r*(1+self.tile[0]))/2, 0, -onedeg/2)
                glVertex3f( onedeg*cos(d2r*self.tile[0])/2, 0,  onedeg/2)
                glVertex3f(-onedeg*cos(d2r*self.tile[0])/2, 0,  onedeg/2)
                glVertex3f(-onedeg*cos(d2r*(1+self.tile[0]))/2, 0, -onedeg/2)
                glEnd()
                # Runways
                glColor3f(0.333,0.333,0.333)
                glBegin(GL_QUADS)
                for apt in self.runways.values():
                    (lat,lon,hdg,length,width)=apt[0]
                    if [int(floor(lat)),int(floor(lon))]==self.tile:
                        for (lat,lon,hdg,length,width) in apt:
                            #print (lat,lon,hdg,length,width)
                            #glColor3f(hdg/360,hdg/360,hdg/360)	# test
                            (cx,cz)=self.latlon2m(lat,lon)
                            hdg=d2r*hdg
                            coshdg=cos(hdg)
                            sinhdg=sin(hdg)
                            length=f2m*length/2
                            width=f2m*width/2
                            glVertex3f(cx+width*coshdg-length*sinhdg, 0,
                                       cz+width*sinhdg+length*coshdg)
                            glVertex3f(cx-width*coshdg-length*sinhdg, 0,
                                       cz-width*sinhdg+length*coshdg)
                            glVertex3f(cx-width*coshdg+length*sinhdg, 0,
                                       cz-width*sinhdg-length*coshdg)
                            glVertex3f(cx+width*coshdg+length*sinhdg, 0,
                                       cz+width*sinhdg-length*coshdg)
                glEnd()
                glEndList()
            glCallList(self.runwayslist)

            # Position centre
            glPushMatrix()
            glLoadIdentity()
            glRotatef(self.e, 1.0,0.0,0.0)
            glRotatef(self.h, 0.0,1.0,0.0)
            glColor3f(1.0, 0.25, 0.25)	# Cursor
            glBegin(GL_LINES)
            glVertex3f(-0.5,0,0)
            glVertex3f( 0.5,0,0)
            glVertex3f(0,0,-0.5)
            glVertex3f(0,0, 0.5)
            glEnd()
            glPopMatrix()

            # Selection centres
            glColor3f(1.0, 0.5, 1.0)
            for i in self.selected:
                (obj, lat, lon, hdg)=placement[i]
                (x,z)=self.latlon2m(lat, lon)
                glPushMatrix()
                glTranslatef(x, 0.0, z)
                glRotatef(-hdg, 0.0,1.0,0.0)
                glBegin(GL_LINES)
                glVertex3f(-0.5,0,0)
                glVertex3f( 0.5,0,0)
                glVertex3f(0,0,-0.5)
                glVertex3f(0,0, 0.5)
                glEnd()
                glPopMatrix()

        # Objects
        if not placement:
            # early exit
            glFlush()
            self.SwapBuffers()
            return

        if not self.objectslist:
            self.objcache.realize()
            self.objectslist=glGenLists(1)
            glNewList(self.objectslist, GL_COMPILE)
            glInitNames()
            glPushName(0)
            glColor3f(0.75, 0.75, 0.75)	# Unpainted
            glEnable(GL_DEPTH_TEST)
            glEnable(GL_CULL_FACE)
            cullstate=True
            lat=lon=hdg=999
            for i in range(len(placement)):
                (obj, lat, lon, hdg)=placement[i]
                glLoadName(i)
                (x,z)=self.latlon2m(lat, lon)
                (base,culled,nocull,texno,poly)=self.objcache.get(obj)
                #print obj, lat, lon, hdg, x, z, base,culled,nocull,texno,poly
                glPushMatrix()
                glTranslatef(x, 0.0, z)
                glRotatef(-hdg, 0.0,1.0,0.0)
                glBindTexture(GL_TEXTURE_2D, texno)
                if culled:
                    if not cullstate:
                        glEnable(GL_CULL_FACE)
                        cullstate=True
                    glDrawArrays(GL_TRIANGLES, base, culled)
                if nocull:
                    if cullstate:
                        glDisable(GL_CULL_FACE)
                        cullstate=False
                    glDrawArrays(GL_TRIANGLES, base+culled, nocull)
                glPopMatrix()
            glEndList()
        glCallList(self.objectslist)

        if mode==GL_SELECT:
            return

        # Selections
        glColor3f(1.0, 0.5, 1.0)
        glPolygonOffset(0, -10)
        glEnable(GL_POLYGON_OFFSET_FILL)
        glEnable(GL_CULL_FACE)
        cullstate=True
        for i in self.selected:
            # assumes cache is already properly set up
            (obj, lat, lon, hdg)=placement[i]
            (x,z)=self.latlon2m(lat, lon)
            (base,culled,nocull,texno,poly)=self.objcache.get(obj)
            glPushMatrix()
            glTranslatef(x, 0.0, z)
            glRotatef(-hdg, 0.0,1.0,0.0)
            glBindTexture(GL_TEXTURE_2D, texno)
            if culled:
                if not cullstate:
                    glEnable(GL_CULL_FACE)
                    cullstate=True
                glDrawArrays(GL_TRIANGLES, base, culled)
            if nocull:
                if cullstate:
                    glDisable(GL_CULL_FACE)
                    cullstate=False
                glDrawArrays(GL_TRIANGLES, base+culled, nocull)
            glPopMatrix()
        glDisable(GL_POLYGON_OFFSET_FILL)

	# drag box
        if self.selectanchor:
            glColor3f(0.25, 0.125, 0.25)
            glBindTexture(GL_TEXTURE_2D, 0)
            glMatrixMode(GL_PROJECTION)
            glLoadIdentity()
            glMatrixMode(GL_MODELVIEW)
            glLoadIdentity()
            glDisable(GL_CULL_FACE)
            #glEnable(GL_LINE_STIPPLE)
            glPolygonMode(GL_FRONT_AND_BACK, GL_LINE)
            x0=float(self.selectanchor[0]*2)/size.x-1
            y0=1-float(self.selectanchor[1]*2)/size.y
            x1=float(self.mousenow[0]*2)/size.x-1
            y1=1-float(self.mousenow[1]*2)/size.y
            glBegin(GL_QUADS)
            glVertex3f(x0, y0, -0.9)
            glVertex3f(x0, y1, -0.9)
            glVertex3f(x1, y1, -0.9)
            glVertex3f(x1, y0, -0.9)
            glEnd()
            glPolygonMode(GL_FRONT, GL_FILL)
            
        glFlush()
        self.SwapBuffers()

    def latlon2m(self, lat, lon):
        return(((lon-self.centre[1])*onedeg*cos(d2r*lat),
                (self.centre[0]-lat)*onedeg))

    def currentplacements(self):
        key=(self.tile[0],self.tile[1])
        if key in self.placements:
            return self.placements[key]
        else:
            return []
    
    def reload(self, runways, objects, placements, baggage):
        self.runways=runways
        self.objcache.flush(objects)
        if placements!=None:
            self.placements=placements
            self.baggage=baggage

        missing=[]
        errobjs=[]
        for placement in self.placements.values():
            for (obj, lat, lon, hdg) in placement:
                if not self.objcache.load(obj, True):
                    if not obj in objects:
                        if not obj in missing: missing.append(obj)
                    else: 
                        errobjs.append(obj)

        if self.runwayslist: glDeleteLists(self.runwayslist, 1)
        self.runwayslist=0
        if self.objectslist: glDeleteLists(self.objectslist, 1)
        self.objectslist=0

        self.selected=[]	# may not have same indices in new list
        self.undostack=[]

        # Redraw can happen under MessageBox, so do this last
        if errobjs:
            sortfolded(errobjs)
            if platform=='darwin':
                wx.MessageBox(str('\n'.join(errobjs)), 'One or more objects could not be read.', wx.ICON_QUESTION|wx.OK, self.frame)
            else:
                wx.MessageBox("One or more objects could not be read:\n\n  %s" % '\n  '.join(errobjs), appname, wx.ICON_EXCLAMATION|wx.OK, self.frame)
        if missing:
            sortfolded(missing)
            if platform=='darwin':
                wx.MessageBox(str('\n'.join(missing)), 'Package references missing objects.', wx.ICON_QUESTION|wx.OK, self.frame)
            else:
                wx.MessageBox("Package references missing objects:\n\n  %s" % '  \n'.join(missing), appname, wx.ICON_EXCLAMATION|wx.OK, self.frame)

        if 0:	# debug
            print "Frame:\t%s"  % self.frame.GetId()
            print "Toolb:\t%s"  % self.frame.toolbar.GetId()
            print "Parent:\t%s" % self.parent.GetId()
            print "Split:\t%s"  % self.frame.splitter.GetId()
            print "MyGL:\t%s"   % self.GetId()
            print "Palett:\t%s" % self.frame.palette.GetId()
            if 'GetChoiceCtrl' in dir(self.frame.palette):
                print "Choice:\t%s" %self.frame.palette.GetChoiceCtrl().GetId()


    def add(self, obj, lat, lon, hdg):
        if not self.objcache.load(obj):
            if platform=='darwin':
                wx.MessageBox('%s cannot be read.' % obj, 'Cannot add this object.', wx.ICON_QUESTION|wx.OK, self.frame)
            else:
                wx.MessageBox("Cannot add this object.\n\n%s cannot be read." % obj, appname, wx.ICON_HAND|wx.OK, self.frame)
            return False
        if self.objectslist: glDeleteLists(self.objectslist, 1)
        self.objectslist=0
        (base,culled,nocull,texno,poly)=self.objcache.get(obj)
        placement=self.currentplacements()
        if poly:
            placement.insert(0, (obj, lat, lon, hdg))
            self.selected=[0]
        else:
            self.selected=[len(placement)]
            placement.append((obj, lat, lon, hdg))
        self.placements[(self.tile[0],self.tile[1])]=placement
        self.Refresh()
        self.frame.ShowSel()
        return True

    def movesel(self, dlat, dlon, dhdg):
        # returns True if changed something
        if not self.selected: return False
        if self.objectslist: glDeleteLists(self.objectslist, 1)
        self.objectslist=0
        placement=self.currentplacements()
        for i in self.selected:
            (obj, lat, lon, hdg)=placement[i]
            lat=round(lat+dlat,6)
            lon=round(lon+dlon,6)
            hdg=round(hdg+dhdg,0)%360
            placement[i]=(obj, lat, lon, hdg)
        self.placements[(self.tile[0],self.tile[1])]=placement
        self.Refresh()
        self.frame.ShowSel()
        return True

    def clearsel(self):
        self.selected=[]
        self.Refresh()

    def allsel(self, withctrl):
        # fake up mouse drag
        self.selectanchor=[0,0]
        self.selectctrl=withctrl
        size=self.GetClientSize()
        self.mousenow=[size.x,size.y]
        self.select()
        self.selectanchor=None

    def delsel(self):
        # returns True if deleted something
        if not self.selected: return False
        if self.objectslist: glDeleteLists(self.objectslist, 1)
        self.objectslist=0
        placement=self.currentplacements()
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
            (obj1, lat1, lon1, hdg)=placement[i]
            obj.append(obj1)
            lat+=lat1
            lon+=lon1
        return ((obj, lat/len(self.selected), lon/len(self.selected), hdg))

    def goto(self, loc, hdg, elev, dist):
        newtile=[int(floor(loc[0])),int(floor(loc[1]))]
        if newtile!=self.tile:
            if self.runwayslist: glDeleteLists(self.runwayslist, 1)
            self.runwayslist=0
            if self.objectslist: glDeleteLists(self.objectslist, 1)
            self.objectslist=0
            self.selected=[]
            self.frame.ShowSel()
        self.tile=newtile
        self.centre=[self.tile[0]+0.5, self.tile[1]+0.5]
        (self.x, self.z)=self.latlon2m(loc[0],loc[1])
        self.h=hdg
        self.e=elev
        self.d=dist
        self.Refresh()

