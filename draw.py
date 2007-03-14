from math import cos, sin, floor, pi
from OpenGL.GL import *
from OpenGL.GLU import *
import wx.glcanvas

from files import readObj, TexCache

onedeg=1852*60	# 1 degree of longitude at equator (60nm) [m]
d2r=pi/180.0
f2m=0.3048	# 1 foot [m]



# OpenGL Window
class MyGL(wx.glcanvas.GLCanvas):
    def __init__(self, parent):

        self.parent=parent

        self.tile=[0,0]		# [lat,lon] of SW
        self.centre=None	# [lat,lon] of centre
        self.runways={}		# (lat,lon,hdg,length,width) by code
        self.runwayslist=0
        self.objects={}		# (list, path, poly) by name
        self.placements={}	# [(name,lat,lon,hdg)] by tile
        self.objectslist=0
        self.baggage={}		# (props, other) by tile
        self.texcache=TexCache()

        self.varray=[]
        self.tarray=[]

        self.selections=[]
        self.selected=None
        
        self.x=0
        self.z=0
        self.h=0
        self.e=1
        self.d=1
        
        wx.glcanvas.GLCanvas.__init__(self, parent, style=GL_RGBA|GL_DOUBLEBUFFER|GL_DEPTH|wx.FULL_REPAINT_ON_RESIZE)
        wx.EVT_PAINT(self, self.OnPaint)
        wx.EVT_ERASE_BACKGROUND(self, self.OnEraseBackground)
        wx.EVT_KEY_DOWN(self, self.OnKeyDown)
        wx.EVT_LEFT_DOWN(self, self.OnLeftDown)
        
        glClearColor(0.5, 0.5, 1.0, 0.0)	# Sky
        glClearDepth(1.0)
        glDepthFunc(GL_LESS)
        glLineWidth(2.0)
        glFrontFace(GL_CW)
        glShadeModel(GL_FLAT)
        glLoadIdentity()
        glCullFace(GL_BACK)
        glPixelStorei(GL_UNPACK_ALIGNMENT,1)
        glEnable(GL_TEXTURE_2D)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
        glEnable(GL_BLEND)
	glEnableClientState(GL_VERTEX_ARRAY)
	glEnableClientState(GL_TEXTURE_COORD_ARRAY)

    def OnEraseBackground(self, event):
        pass	# Prevent flicker when resizing / painting

    def OnKeyDown(self, event):
        # Manually propagate
        self.parent.OnKeyDown(event)

    def OnLeftDown(self, event):
        event.Skip()	# focus change
        glSelectBuffer(64)
        glRenderMode(GL_SELECT)
        self.redraw(GL_SELECT, event)
        selections=[]
        try:
            for min_depth, max_depth, (names,) in glRenderMode(GL_RENDER):
                selections.append(int(names))
        except:	# overflow
            pass

        if not selections:
            self.selected=None
        elif selections==self.selections and self.selected!=None and self.selected in self.selections:
            # cycle through selections
            self.selected=selections[(selections.index(self.selected)+1)%len(selections)]
        else:
            self.selected=selections[0]
        self.selections=selections

        if self.selected!=None:
            self.parent.ShowSel(self.currentplacements()[self.selected])
        else:
            self.parent.ShowSel(None)
        self.Refresh()
        
    def OnPaint(self, event):
        dc = wx.PaintDC(self)	# Tell the window system that we're on the case
        self.SetCurrent()
        glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT)
        self.redraw(GL_RENDER)

    def redraw(self, mode, event=None):
        glMatrixMode(GL_PROJECTION)
        size = self.GetClientSize()
        glViewport(0, 0, *size)
        glLoadIdentity()
        if mode==GL_SELECT:
            viewport=glGetIntegerv(GL_VIEWPORT)
            gluPickMatrix(event.m_x, viewport[3]-event.m_y, 3,3, viewport)
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
        if mode!=GL_SELECT and not self.runwayslist:
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

        if mode!=GL_SELECT:
            glCallList(self.runwayslist)

            # Cursor
            glPushMatrix()
            glLoadIdentity()
            glRotatef(self.e, 1.0,0.0,0.0)	#self.e
            glRotatef(self.h, 0.0,1.0,0.0)
            glColor3f(1.0, 0.25, 0.25)	# Cursor
            glBegin(GL_LINES)
            glVertex3f(-0.5,0,0)
            glVertex3f( 0.5,0,0)
            glVertex3f(0,0,-0.5)
            glVertex3f(0,0, 0.5)
            glEnd()
            glPopMatrix()

            if self.selected!=None:
                (obj, lat, lon, hdg)=placement[self.selected]
                (x,z)=self.latlon2m(lat, lon)
                glPushMatrix()
                glTranslatef(x, 0.0, z)
                glRotatef(-hdg, 0.0,1.0,0.0)
                glColor3f(1.0, 0.5, 1.0)
                glBegin(GL_LINES)
                glVertex3f(-0.5,0,0)
                glVertex3f( 0.5,0,0)
                glVertex3f(0,0,-0.5)
                glVertex3f(0,0, 0.5)
                glEnd()
                glPopMatrix()

        # Objects
        if not placement:
            glFlush()
            self.SwapBuffers()
            return

        if mode==GL_SELECT or not self.objectslist:
            if mode==GL_RENDER:
                self.objectslist=glGenLists(1)
                glNewList(self.objectslist, GL_COMPILE)
            else:
                glInitNames()
                glPushName(0)
            glColor3f(0.75, 0.75, 0.75)	# Unpainted
            glEnable(GL_DEPTH_TEST)
            glEnable(GL_CULL_FACE)
            cullstate=True
            lat=lon=hdg=999
            for i in range(len(placement)):
                (obj, lat, lon, hdg)=placement[i]
                if obj in self.objects:
                    glLoadName(i)
                    (x,z)=self.latlon2m(lat, lon)
                    (base,culled,nocull,texno,poly)=self.objects[obj]
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
            if mode==GL_RENDER:
                glEndList()   

        if mode==GL_SELECT:
            return

        if self.objectslist:
            glCallList(self.objectslist)

        if self.selected!=None:
            (obj, lat, lon, hdg)=placement[self.selected]
            (x,z)=self.latlon2m(lat, lon)
            (base,culled,nocull,texno,poly)=self.objects[obj]
            glTranslatef(x, 0.0, z)
            glRotatef(-hdg, 0.0,1.0,0.0)
            glBindTexture(GL_TEXTURE_2D, texno)
            glColor3f(1.0, 0.5, 1.0)
            glPolygonOffset(0, -10)
            glEnable(GL_POLYGON_OFFSET_FILL)
            if culled:
                glEnable(GL_CULL_FACE)
                glDrawArrays(GL_TRIANGLES, base, culled)
            if nocull:
                glDisable(GL_CULL_FACE)
                cullstate=False
                glDrawArrays(GL_TRIANGLES, base+culled, nocull)
            glDisable(GL_POLYGON_OFFSET_FILL)
            # Also show as line in case object has poly_os
            #glEnable(GL_POLYGON_OFFSET_LINE)
            #glPolygonMode(GL_FRONT, GL_LINE)
            #if culled:
            #    glEnable(GL_CULL_FACE)
            #    glDrawArrays(GL_TRIANGLES, base, culled)
            #if nocull:
            #    glDisable(GL_CULL_FACE)
            #    cullstate=False
            #    glDrawArrays(GL_TRIANGLES, base+culled, nocull)
            #glPolygonMode(GL_FRONT, GL_FILL)
            #glDisable(GL_POLYGON_OFFSET_LINE)
            
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
        self.tile=[999,999]	# force invalidation of dlists on next goto
        self.runways=runways
        self.texcache.flush()
        self.objects={}
        self.varray=[]
        self.tarray=[]
        for name, path in objects.iteritems():
            (culled, nocull, tculled, tnocull, texno, poly)=readObj(path, self.texcache)
            base=len(self.varray)
            self.varray.extend(culled)
            self.varray.extend(nocull)
            self.tarray.extend(tculled)
            self.tarray.extend(tnocull)
            self.objects[name]=(base, len(culled), len(nocull), texno, poly)
        if self.varray:
            glVertexPointerf(self.varray)
            glTexCoordPointerf(self.tarray)
        else:
            # need something
            glVertexPointerf([[0,0,0],[0,0,0],[0,0,0]])
            glTexCoordPointerf([[0,0],[0,0]])
        if placements!=None:
            self.placements=placements
            self.baggage=baggage
        missing=[]
        for placement in self.placements.values():
            for (obj, lat, lon, hdg) in placement:
                if not obj in self.objects and not obj in missing:
                    missing.append(obj)
        if missing:
            wx.MessageBox("Package references missing objects:\n%s" % '\n'.join(missing), 'Warning', wx.ICON_INFORMATION|wx.OK, self.parent)

    def add(self, obj, lat, lon, hdg):
        if self.objectslist: glDeleteLists(self.objectslist, 1)
        self.objectslist=0
        (base,culled,nocull,texno,poly)=self.objects[obj]
        placement=self.currentplacements()
        if poly:
            placement.insert(0, (obj, lat, lon, hdg))
            self.selected=0
        else:
            self.selected=len(placement)
            placement.append((obj, lat, lon, hdg))
        self.placements[(self.tile[0],self.tile[1])]=placement
        self.Refresh()
        self.parent.ShowSel((obj, lat, lon, hdg))

    def movesel(self, dlat, dlon, dhdg):
        if self.selected==None:
            return
        if self.objectslist: glDeleteLists(self.objectslist, 1)
        self.objectslist=0
        placement=self.currentplacements()
        (obj, lat, lon, hdg)=placement[self.selected]
        lat=round(lat+dlat,6)
        lon=round(lon+dlon,6)
        hdg=round(hdg+dhdg,0)%360
        placement[self.selected]=(obj, lat, lon, hdg)
        self.placements[(self.tile[0],self.tile[1])]=placement
        self.Refresh()
        self.parent.ShowSel((obj, lat, lon, hdg))

    def clearsel(self):
        if self.selected!=None:
            self.selected=None
            self.Refresh()

    def delsel(self):
        if self.selected==None: return None
        if self.objectslist: glDeleteLists(self.objectslist, 1)
        self.objectslist=0
        placement=self.currentplacements()
        placement.pop(self.selected)
        self.placements[(self.tile[0],self.tile[1])]=placement
        self.selected=None
        self.Refresh()
        self.parent.ShowSel(None)

    def getsel(self):
        if self.selected==None: return None
        placement=self.currentplacements()
        (obj, lat, lon, hdg)=placement[self.selected]
        return ((obj, lat, lon, hdg))

    def goto(self, loc, hdg, elev, dist):
        newtile=[int(floor(loc[0])),int(floor(loc[1]))]
        if newtile!=self.tile:
            if self.runwayslist: glDeleteLists(self.runwayslist, 1)
            self.runwayslist=0
            if self.objectslist: glDeleteLists(self.objectslist, 1)
            self.objectslist=0
            if self.selected!=None:
                self.selected=None	# May not be the same index in new list
                self.parent.ShowSel(None)
        self.tile=newtile
        self.centre=[self.tile[0]+0.5, self.tile[1]+0.5]
        (self.x, self.z)=self.latlon2m(loc[0],loc[1])
        self.h=hdg
        self.e=elev
        self.d=dist
        self.Refresh()

