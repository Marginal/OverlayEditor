import codecs
from math import fabs
from numpy import array, concatenate, float32
from operator import itemgetter, attrgetter
from os import listdir
from os.path import basename, dirname, exists, join, normpath, sep
from sys import exc_info, maxint

from OpenGL.GL import *
import wx
if __debug__:
    import time
    from traceback import print_exc

from lock import Locked

COL_WHITE    =(1.0, 1.0, 1.0)
COL_UNPAINTED=(1.0, 1.0, 1.0)
COL_POLYGON  =(0.75,0.75,0.75)
COL_FOREST   =(0.25,0.75,0.25)
COL_EXCLUDE  =(0.75,0.25,0.25)
COL_NONSIMPLE=(1.0, 0.25,0.25)
COL_SELECTED =(1.0, 0.5, 1.0)
COL_DRAGBOX  =(0.75,0.325,0.75)
COL_SELNODE  =(1.0, 1.0, 1.0)
COL_CURSOR   =(1.0, 0.25,0.25)

fallbacktexture='Resources/fallback.png'

class BBox:

    def __init__(self, minx=maxint, maxx=-maxint, minz=maxint, maxz=-maxint):
        self.minx=minx
        self.maxx=maxx
        self.minz=minz
        self.maxz=maxz

    def intersects(self, other):
        return ((self.minx <= other.maxx) and (self.maxx > other.minx) and
                (self.minz <= other.maxz) and (self.maxz > other.minz))

    def inside(self, x, z):
        return ((self.minx <= x < self.maxx) and
                (self.minz <= z < self.maxz))

    def include(self, x, z):
        self.maxx=max(self.maxx, x)
        self.minx=min(self.minx, x)
        self.maxz=max(self.maxz, z)
        self.minz=min(self.minz, z)

    def __str__(self):
        return '<x:%s,%s z:%s,%s>' % (self.minx,self.maxx,self.minz,self.maxz)


# Virtual class for ground clutter definitions
#
# Derived classes expected to have following members:
# __init__
# __str__
# layername
# setlayer
# allocate -> (re)allocate into instance VBO
# flush -> forget instance VBO allocation
#

def ClutterDefFactory(filename, vertexcache, lookup, defs):
    "creates and initialises appropriate PolgonDef subclass based on file extension"
    # would like to have made this a 'static' method of PolygonDef
    if filename.startswith(PolygonDef.EXCLUDE):
        return ExcludeDef(filename, vertexcache, lookup, defs)
    ext=filename.lower()[-4:]
    if ext==ObjectDef.OBJECT:
        return ObjectDef(filename, vertexcache, lookup, defs)
    elif ext==AutoGenPointDef.AGP:
        return AutoGenPointDef(filename, vertexcache, lookup, defs)
    elif ext==PolygonDef.DRAPED:
        return DrapedDef(filename, vertexcache, lookup, defs)
    elif ext==PolygonDef.FACADE:
        return FacadeDef(filename, vertexcache, lookup, defs)
    elif ext==PolygonDef.FOREST:
        return ForestDef(filename, vertexcache, lookup, defs)
    elif ext==PolygonDef.LINE:
        return LineDef(filename, vertexcache, lookup, defs)
    elif ext in SkipDefs:
        raise IOError		# what's this doing here?
    else:	# unknown polygon type
        return PolygonDef(filename, vertexcache, lookup, defs)


class ClutterDef:
    LAYERNAMES=['terrain', 'beaches', 'shoulders', 'taxiways', 'runways', 'markings', 'roads', 'objects', 'light_objects', 'cars']
    LAYERCOUNT=len(LAYERNAMES)*11
    TERRAINLAYER=LAYERNAMES.index('terrain')*11+5
    BEACHESLAYER=LAYERNAMES.index('beaches')*11+5
    SHOULDERLAYER=LAYERNAMES.index('shoulders')*11+5
    TAXIWAYLAYER=LAYERNAMES.index('taxiways')*11+5
    RUNWAYSLAYER=LAYERNAMES.index('runways')*11+5
    MARKINGLAYER=LAYERNAMES.index('markings')*11+5
    NETWORKLAYER=LAYERNAMES.index('roads')*11+5
    OUTLINELAYER=LAYERNAMES.index('roads')*11+5	# for polygons
    DRAPEDLAYER=LAYERNAMES.index('objects')*11	# for draped geometry
    DEFAULTLAYER=LAYERNAMES.index('objects')*11+5
    PREVIEWSIZE=400	# size of image in preview window

    def __init__(self, filename, vertexcache, lookup, defs):
        self.filename=filename
        if filename and vertexcache:
            self.texpath=dirname(self.filename)        
            co=sep+'custom objects'+sep
            if co in self.filename.lower():
                base=self.filename[:self.filename.lower().index(co)]
                for f in listdir(base):
                    if f.lower()=='custom object textures':
                        self.texpath=join(base,f)
                        break
            self.texture=vertexcache.texcache.get(fallbacktexture)
        else:
            self.texture=0
        self.texerr=None	# (filename, errorstring)
        self.layer=ClutterDef.DEFAULTLAYER
        self.canpreview=False
        self.type=0	# for locking
        
    def __str__(self):
        return '<%s>' % (self.filename)

    def setlayer(self, layer, n):
        if not -5<=n<=5: raise IOError
        if layer=='airports':
            if n==0:
                layer='runways'	# undefined behaviour!
            elif n<0:
                layer='shoulders'
            elif n>0:
                layer='markings'
        self.layer=ClutterDef.LAYERNAMES.index(layer)*11+5+n
        if self.layer<0 or self.layer>=ClutterDef.LAYERCOUNT: raise IOError

    def layername(self):
        return "%s %+d" % (ClutterDef.LAYERNAMES[self.layer/11],
                           (self.layer%11)-5)

    def allocate(self, vertexcache):
        pass

    def flush(self):
        pass

    # Normalise path, replacing : / and \ with os-specific separator, eliminating .. etc
    def cleanpath(self, path):
        # relies on normpath on win replacing '/' with '\\'
        return normpath(join(self.texpath, path.decode('latin1').replace(':', sep).replace('\\', sep)))


class ObjectDef(ClutterDef):

    OBJECT='.obj'
    
    def __init__(self, filename, vertexcache, lookup, defs, make_editable=True):
        ClutterDef.__init__(self, filename, vertexcache, lookup, defs)
        self.canpreview=True
        self.type=Locked.OBJ
        self.poly=0
        self.bbox=BBox()
        self.height=0.5	# musn't be 0
        self.base=None
        self.draped=[]
        self.texture_draped=0

        h=None
        culled=[]
        nocull=[]
        draped=[]
        last=current=culled
        texture=None
        texture_draped=None
        if __debug__: clock=time.clock()	# Processor time
        h=open(self.filename, 'rU')
        if filename[0]=='*': self.filename=None
        if not h.readline().strip()[0] in ['I','A']:
            raise IOError
        version=h.readline().split()[0]
        if not version in ['2', '700','800']:
            raise IOError
        if version!='2' and not h.readline().split()[0]=='OBJ':
            raise IOError
        if version in ['2','700']:
            while True:
                line=h.readline()
                if not line: raise IOError
                tex=line.split('//')[0].strip()
                if tex and tex.lower()!='none':
                    texture=self.cleanpath(tex)
                    break

        if version=='2':
            for line in h:
                c=line.split()
                if not c: continue
                id=c[0]
                if id=='99':
                    break
                elif id=='1':
                    h.next()
                elif id=='2':
                    h.next()
                    h.next()
                elif id in ['6','7']:	# smoke
                    for i in range(4): h.next()
                elif id=='3':
                    # sst, clockwise, start with left top?
                    uv=[float(c[1]), float(c[2]), float(c[3]), float(c[4])]
                    v=[]
                    for i in range(3):
                        c=h.next().split()
                        v.append([float(c[0]), float(c[1]), float(c[2])])
                        self.bbox.include(v[i][0], v[i][2])
                        self.height=max(self.height, v[i][1])
                    current.append(v[0]+[uv[0],uv[3]])
                    current.append(v[1]+[uv[1],uv[2]])
                    current.append(v[2]+[uv[1],uv[3]])
                elif int(id) < 0:	# strip
                    count=-int(id)
                    seq=[]
                    for i in range(0,count*2-2,2):
                        seq.extend([i,i+1,i+2,i+3,i+2,i+1])
                    v=[]
                    t=[]
                    for i in range(count):
                        c=h.next().split()
                        v.append([float(c[0]), float(c[1]), float(c[2]), float(c[6]), float(c[8])])
                        self.bbox.include(v[-1][0], v[-1][2])
                        self.height=max(self.height, v[-1][1])
                        v.append([float(c[3]), float(c[4]), float(c[5]), float(c[7]), float(c[9])])
                        self.bbox.include(v[-1][0], v[-1][2])
                        self.height=max(self.height, v[-1][1])
                    for i in seq:
                        current.append(v[i])
                else:	# quads: type 4, 5, 6, 7, 8
                    # sst, clockwise, start with right top
                    uv=[float(c[1]), float(c[2]), float(c[3]), float(c[4])]
                    v=[]
                    for i in range(4):
                        c=h.next().split()
                        v.append([float(c[0]), float(c[1]), float(c[2])])
                        self.bbox.include(v[i][0], v[i][2])
                        self.height=max(self.height, v[i][1])
                    current.append(v[0]+[uv[1],uv[3]])
                    current.append(v[1]+[uv[1],uv[2]])
                    current.append(v[2]+[uv[0],uv[2]])
                    current.append(v[0]+[uv[1],uv[3]])
                    current.append(v[2]+[uv[0],uv[2]])
                    current.append(v[3]+[uv[0],uv[3]])

        elif version=='700':
            for line in h:
                c=line.split()
                if not c: continue
                id=c[0]
                if id in ['tri', 'quad', 'quad_hard', 'polygon', 
                          'quad_strip', 'tri_strip', 'tri_fan',
                          'quad_movie']:
                    count=0
                    seq=[]
                    if id=='tri':
                        count=3
                        seq=[0,1,2]
                    elif id=='polygon':
                        count=int(c[1])
                        for i in range(1,count-1):
                            seq.extend([0,i,i+1])
                    elif id=='quad_strip':
                        count=int(c[1])
                        for i in range(0,count-2,2):
                            seq.extend([i,i+1,i+2,i+3,i+2,i+1])
                    elif id=='tri_strip':
                        count=int(c[1])
                        for i in range(0,count-2):
                            if i&1:
                                seq.extend([i+2,i+1,i])
                            else:
                                seq.extend([i,i+1,i+2])
                    elif id=='tri_fan':
                        count=int(c[1])
                        for i in range(1,count-1):
                            seq.extend([0,i,i+1])
                    else:	# quad
                        count=4
                        seq=[0,1,2,0,2,3]
                    v=[]
                    i=0
                    while i<count:
                        c=h.next().split()
                        v.append([float(c[0]), float(c[1]), float(c[2]), float(c[3]), float(c[4])])
                        self.bbox.include(v[i][0], v[i][2])
                        self.height=max(self.height, v[i][1])
                        if len(c)>5:	# Two per line
                            v.append([float(c[5]), float(c[6]), float(c[7]), float(c[8]), float(c[9])])
                            self.bbox.include(v[i+1][0], v[i+1][2])
                            self.height=max(self.height, v[i+1][1])
                            i+=2
                        else:
                            i+=1
                    for i in seq:
                        current.append(v[i])
                elif id=='ATTR_LOD':
                    if float(c[1])!=0: break
                    current=last=culled	# State is reset per LOD
                elif id=='ATTR_poly_os':
                    self.poly=max(self.poly,int(float(c[1])))
                elif id=='ATTR_cull':
                    current=culled
                elif id=='ATTR_no_cull':
                    current=nocull
                elif id=='ATTR_layer_group':
                    self.setlayer(c[1], int(c[2]))
                elif id=='end':
                    break

        elif version=='800':
            vt=[]
            idx=[]
            anim=[]
            for line in h:
                c=line.split()
                if not c: continue
                id=c[0]
                if id=='VT':
                    x=float(c[1])
                    y=float(c[2])
                    z=float(c[3])
                    self.bbox.include(x,z)	# ~10% of load time
                    self.height=max(self.height, y)
                    vt.append([x,y,z, float(c[7]),float(c[8])])
                elif id=='IDX10':
                    #idx.extend([int(c[i]) for i in range(1,11)])
                    idx.extend(map(int,c[1:11])) # slightly faster under 2.3
                elif id=='IDX':
                    idx.append(int(c[1]))
                elif id=='TEXTURE':
                    if len(c)>1 and c[1].lower()!='none':
                        texture=self.cleanpath(c[1])
                elif id=='TEXTURE_DRAPED':
                    if len(c)>1 and c[1].lower()!='none':
                        texture_draped=self.cleanpath(c[1])
                        # FIXME: Should have different layers for static and dynamic content
                        self.layer=ClutterDef.DRAPEDLAYER
                elif id=='ATTR_LOD':
                    if float(c[1])!=0: break
                    current=last=culled	# State is reset per LOD
                elif id=='ATTR_poly_os':
                    if not texture_draped:	# Ignore ATTR_poly_os if obj uses ATTR_draped
                        self.poly=max(self.poly,int(float(c[1])))
                        if float(c[1]):
                            last=current
                            current=draped
                        else:
                            current=last
                elif id=='ATTR_cull':
                    if current==draped:
                        last=culled
                    else:
                        current=culled
                elif id=='ATTR_no_cull':
                    if current==draped:
                        last=nocull
                    else:
                        current=nocull
                elif id=='ATTR_draped':
                    last=current
                    current=draped
                elif id=='ATTR_no_draped':
                    current=last
                elif id in ['ATTR_layer_group', 'ATTR_layer_group_draped']:
                    # FIXME: Should have different layers for static and dynamic content
                    self.setlayer(c[1], int(c[2]))
                elif id=='ANIM_begin':
                    if anim:
                        anim.append(list(anim[-1]))
                    else:
                        anim=[[0,0,0]]
                elif id=='ANIM_end':
                    anim.pop()
                elif id=='ANIM_trans':
                    anim[-1]=[anim[-1][i]+float(c[i+1]) for i in range(3)]
                elif id=='TRIS':
                    start=int(c[1])
                    new=int(c[2])
                    if anim:
                        current.extend([[vt[idx[i]][j]+anim[-1][j] for j in range (3)] + [vt[idx[i]][3],vt[idx[i]][4]] for i in range(start, start+new)])
                    else:
                        current.extend(itemgetter(*idx[start:start+new])(vt))	#current.extend([vt[idx[i]] for i in range(start, start+new)])
        h.close()
        if __debug__:
            if self.filename: print "%6.3f" % (time.clock()-clock), basename(self.filename)

        if not (len(culled)+len(nocull)+len(draped)):
            # show empty objects as placeholders otherwise can't edit
            if not make_editable: raise IOError
            fb=ObjectFallback(filename, vertexcache, lookup, defs)
            (self.vdata, self.culled, self.nocull, self.poly, self.bbox, self.height, self.base, self.canpreview)=(fb.vdata, fb.culled, fb.nocull, fb.poly, fb.bbox, fb.height, fb.base, fb.canpreview)	# skip texture
            # re-use above allocation
        else:
            self.vdata=array(culled+nocull, float32).flatten()
            self.culled=len(culled)
            self.nocull=len(nocull)
            if texture_draped:	# can be None
                try:
                    self.texture_draped=vertexcache.texcache.get(texture_draped)
                except EnvironmentError, e:
                    self.texerr=(texture_draped, e.strerror)
                except:
                    self.texerr=(texture_draped, unicode(exc_info()[1]))
            if texture:	# can be None
                try:
                    self.texture=vertexcache.texcache.get(texture)
                except EnvironmentError, e:
                    self.texerr=(texture, e.strerror)
                except:
                    self.texerr=(texture, unicode(exc_info()[1]))
                if self.poly:
                    self.texture_draped=self.texture
            self.draped=draped

    def allocate(self, vertexcache):
        if self.base==None and self.vdata is not None:
            self.base=vertexcache.allocate_instance(self.vdata)

    def flush(self):
        self.base=None

    def preview(self, canvas, vertexcache):
        if not self.canpreview: return None
        if isinstance(self,AutoGenPointDef):
            children=self.children
        else:
            children=[]
        self.allocate(vertexcache)
        canvas.glstate.set_instance(vertexcache)
        xoff=canvas.GetClientSize()[0]-ClutterDef.PREVIEWSIZE
        glViewport(xoff, 0, ClutterDef.PREVIEWSIZE, ClutterDef.PREVIEWSIZE)
        glClearColor(0.3, 0.5, 0.6, 1.0)	# Preview colour
        glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT)
        glMatrixMode(GL_PROJECTION)
        glPushMatrix()
        glLoadIdentity()
        sizex=(self.bbox.maxx-self.bbox.minx)*0.5
        sizez=(self.bbox.maxz-self.bbox.minz)*0.5
        maxsize=max(self.height*0.7,		# height
                    sizez*0.88  + sizex*0.51,	# width at 30degrees
                    sizez*0.255 + sizex*0.44)	# depth at 30degrees / 2
        glOrtho(-maxsize, maxsize, -maxsize/2, maxsize*1.5, -2*maxsize, 2*maxsize)
        glMatrixMode(GL_MODELVIEW)
        glLoadIdentity()
        glRotatef( 30, 1,0,0)
        glRotatef(120, 0,1,0)
        glTranslatef(sizex-self.bbox.maxx, 0, sizez-self.bbox.maxz)
        if __debug__ and False:
            canvas.glstate.set_texture(0)
            canvas.glstate.set_color(COL_UNPAINTED)
            for height in [0, self.height]:
                glBegin(GL_LINE_LOOP)
                glVertex3f(self.bbox.minx, height, self.bbox.minz)
                glVertex3f(self.bbox.maxx, height, self.bbox.minz)
                glVertex3f(self.bbox.maxx, height, self.bbox.maxz)
                glVertex3f(self.bbox.minx, height, self.bbox.maxz)
                glEnd()
        canvas.glstate.set_texture(0)
        canvas.glstate.set_color(COL_CURSOR)
        glBegin(GL_POINTS)
        glVertex3f(0, 0, 0)
        glEnd()
        canvas.glstate.set_color(COL_UNPAINTED)
        canvas.glstate.set_depthtest(True)
        canvas.glstate.set_poly(True)
        canvas.glstate.set_cull(True)
        if self.draped:
            canvas.glstate.set_texture(self.texture_draped)
            glBegin(GL_TRIANGLES)
            for i in range(0,len(self.draped),3):
                for j in range(3):
                    v=self.draped[i+j]
                    glTexCoord2f(v[3],v[4])
                    glVertex3f(v[0],v[1],v[2])
            glEnd()
        for p in children:
            child=p[1]
            if child.draped:
                canvas.glstate.set_texture(child.texture_draped)
                glPushMatrix()
                glTranslatef(p[2],0,p[3])
                glRotatef(p[4], 0,1,0)
                glBegin(GL_TRIANGLES)
                for i in range(0,len(child.draped),3):
                    for j in range(3):
                        v=child.draped[i+j]
                        glTexCoord2f(v[3],v[4])
                        glVertex3f(v[0],v[1],v[2])
                glEnd()
                glPopMatrix()

        canvas.glstate.set_poly(False)
        if self.vdata is not None:
            canvas.glstate.set_texture(self.texture)
            if self.culled:
                glDrawArrays(GL_TRIANGLES, self.base, self.culled)
            if self.nocull:
                canvas.glstate.set_cull(False)
                glDrawArrays(GL_TRIANGLES, self.base+self.culled, self.nocull)
        for p in children:
            child=p[1]
            if child.vdata is not None:
                canvas.glstate.set_texture(child.texture)
                glPushMatrix()
                glTranslatef(p[2],0,p[3])
                glRotatef(p[4], 0,1,0)
                if child.culled:
                    canvas.glstate.set_cull(True)
                    glDrawArrays(GL_TRIANGLES, child.base, child.culled)
                if child.nocull:
                    canvas.glstate.set_cull(False)
                    glDrawArrays(GL_TRIANGLES, child.base+child.culled, child.nocull)
                glPopMatrix()
        data=glReadPixels(xoff,0, ClutterDef.PREVIEWSIZE,ClutterDef.PREVIEWSIZE, GL_RGB, GL_UNSIGNED_BYTE)
        img=wx.EmptyImage(ClutterDef.PREVIEWSIZE, ClutterDef.PREVIEWSIZE, False)
        img.SetData(data)
        
        # Restore state for unproject & selection
        glMatrixMode(GL_PROJECTION)
        glPopMatrix()	
        glMatrixMode(GL_MODELVIEW)

        glClearColor(0.5, 0.5, 1.0, 0.0)	# Sky
        glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT)
        canvas.Refresh()	# Mac draws from the back buffer w/out paint event
        return img.Mirror(False)
        

class ObjectFallback(ObjectDef):
    def __init__(self, filename, vertexcache, lookup, defs):
        ClutterDef.__init__(self, filename, vertexcache, lookup, defs)
        self.layer=ClutterDef.DEFAULTLAYER
        self.type=Locked.OBJ
        self.vdata=array([0.5,1.0,-0.5, 1.0,1.0,
                          -0.5,1.0,0.5, 0.0,0.0,
                          -0.5,1.0,-0.5, 0.0,1.0,
                          0.5,1.0,0.5, 1.0,0.0,
                          -0.5,1.0,0.5, 0.0,0.0,
                          0.5,1.0,-0.5, 1.0,1.0,
                          0.0,0.0,0.0, 0.5,0.0,
                          -0.5,1.0,0.5, 0.0,0.0,
                          0.5,1.0,0.5, 1.0,0.0,
                          0.0,0.0,0.0, 0.0,0.5,
                          -0.5,1.0,-0.5, 0.0,1.0,
                          -0.5,1.0,0.5, 0.0,0.0,
                          0.0,0.0,0.0, 0.5,1.0,
                          0.5,1.0,-0.5, 1.0,1.0,
                          -0.5,1.0,-0.5, 0.0,1.0,
                          0.5,1.0,-0.5, 1.0,1.0,
                          0.0,0.0,0.0, 1.0,0.5,
                          0.5,1.0,0.5, 1.0,0.0],float32)
        self.culled=len(self.vdata)
        self.nocull=0
        self.poly=0
        self.bbox=BBox(-0.5,0.5,-0.5,0.5)
        self.height=1.0
        self.base=None
        self.draped=[]
        self.texture_draped=0


class AutoGenPointDef(ObjectDef):

    AGP='.agp'

    def __init__(self, filename, vertexcache, lookup, defs):
        ClutterDef.__init__(self, filename, vertexcache, lookup, defs)
        self.layer=ClutterDef.DRAPEDLAYER	# For the draped texture
        self.canpreview=True
        self.type=Locked.OBJ
        self.vdata=None
        self.poly=0
        self.bbox=BBox()
        self.height=0.5	# musn't be 0
        self.base=None
        self.draped=[]
        self.texture_draped=0
        self.children=[]	# [name, ObjectDef, xdelta, zdelta, hdelta]

        hscale=vscale=width=hanchor=vanchor=crop=texture_draped=None
        objects=[]
        placements=[]
        h=open(self.filename, 'rU')
        if not h.readline().strip()[0] in ['I','A']:
            raise IOError
        if not h.readline().split('#')[0].strip() in ['1000']:
            raise IOError
        if not h.readline().strip() in ['AG_POINT']:
            raise IOError
        for line in h:
            c=line.split()
            if not c: continue
            id=c[0]
            if id=='TEXTURE':
                texture_draped=self.cleanpath(c[1])
            elif id=='TEXTURE_SCALE':
                hscale=float(c[1])
                vscale=float(c[2])
            elif id=='TEXTURE_WIDTH':
                width=float(c[1])
            elif id=='CROP_POLY':
                if crop: raise IOError	# We don't support multiple draped textures
                if len(c)!=9: raise IOError	# We only support rectangles
                crop=[(float(c[1]),float(c[2])), (float(c[3]),float(c[4])), (float(c[5]),float(c[6])), (float(c[7]),float(c[8]))]
            elif id=='OBJECT':
                objects.append(c[1][:-4].replace(':', '/').replace('\\','/')+c[1][-4:].lower())
            elif id=='OBJ_DRAPED':
                placements.append((float(c[1]),float(c[2]),float(c[3]),int(c[4])))
            elif id=='TILE':
                if hanchor is None:
                    hanchor=(float(c[1])+float(c[3]))/2
                    vanchor=(float(c[2])+float(c[4]))/2
            elif id=='ANCHOR_PT':
                hanchor=float(c[1])
                vanchor=float(c[2])
        h.close()
        if not (hscale and vscale and width and hanchor and vanchor): raise IOError	# Don't know defaults
        scale=width/hscale
        if crop:
            if texture_draped:	# texture can be none?
                try:
                    self.texture_draped=vertexcache.texcache.get(texture_draped)
                except EnvironmentError, e:
                    self.texerr=(texture_draped, e.strerror)
                except:
                    self.texerr=(texture_draped, unicode(exc_info()[1]))
            assert len(crop)==4, crop
            # rescale
            vt=[[(crop[i][0]-hanchor)*scale, 0, (vanchor-crop[i][1])*scale,
                 crop[i][0]/hscale, crop[i][1]/vscale] for i in range(len(crop))]
            for v in vt:
                self.bbox.include(v[0], v[2])
            self.draped=[vt[0],vt[3],vt[2],vt[2],vt[1],vt[0]]	# assumes crop specified *anti*-clockwise
        for p in placements:
            childname=objects[p[3]]
            if childname in lookup:
                childfilename=lookup[childname].file
            else:
                childfilename=join(dirname(filename),childname)	# names are relative to this .agp so may not be in global lookup
            if childfilename in defs:
                definition=defs[childfilename]
            else:
                try:
                    defs[childfilename]=definition=ObjectDef(childfilename, vertexcache, lookup, defs, make_editable=False)
                except:
                    if __debug__:
                        print_exc()
                    defs[childfilename]=definition=ObjectFallback(childfilename, vertexcache, lookup, defs)
            if isinstance(definition, ObjectFallback):	# skip fallbacks
                continue
            self.children.append([childname, definition, (p[0]-hanchor)*scale, (vanchor-p[1])*scale, p[2]])
            self.height=max(self.height,definition.height)

    def allocate(self, vertexcache):
        ObjectDef.allocate(self, vertexcache)
        for p in self.children:
            p[1].allocate(vertexcache)

    def flush(self):
        ObjectDef.flush(self)
        for p in self.children:
            p[1].flush()


class PolygonDef(ClutterDef):

    EXCLUDE='Exclude:'
    FACADE='.fac'
    FOREST='.for'
    LINE='.lin'
    DRAPED='.pol'
    BEACH='.bch'

    def __init__(self, filename, vertexcache, lookup, defs):
        ClutterDef.__init__(self, filename, vertexcache, lookup, defs)
        self.fittomesh=True	# nodes laid out at mesh elevation
        self.type=Locked.UNKNOWN

    def preview(self, canvas, vertexcache, l=0, b=0, r=1, t=1, hscale=1):
        if not self.texture or not self.canpreview: return None
        glViewport(0, 0, ClutterDef.PREVIEWSIZE, ClutterDef.PREVIEWSIZE)
        glClearColor(0.3, 0.5, 0.6, 1.0)	# Preview colour
        glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT)
        glMatrixMode(GL_PROJECTION)
        glPushMatrix()
        glLoadIdentity()
        glMatrixMode(GL_MODELVIEW)
        glLoadIdentity()
        canvas.glstate.set_texture(self.texture)
        canvas.glstate.set_color(COL_WHITE)
        glBegin(GL_QUADS)
        glTexCoord2f(l,b)
        glVertex3f(-hscale,  1, 0)
        glTexCoord2f(r,b)
        glVertex3f( hscale,  1, 0)
        glTexCoord2f(r,t)
        glVertex3f( hscale, -1, 0)
        glTexCoord2f(l,t)
        glVertex3f(-hscale, -1, 0)
        glEnd()
        data=glReadPixels(0,0, ClutterDef.PREVIEWSIZE,ClutterDef.PREVIEWSIZE, GL_RGB, GL_UNSIGNED_BYTE)
        img=wx.EmptyImage(ClutterDef.PREVIEWSIZE, ClutterDef.PREVIEWSIZE, False)
        img.SetData(data)
        
        # Restore state for unproject & selection
        glMatrixMode(GL_PROJECTION)
        glPopMatrix()	
        glMatrixMode(GL_MODELVIEW)

        glClearColor(0.5, 0.5, 1.0, 0.0)	# Sky
        glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT)
        canvas.Refresh()	# Mac draws from the back buffer w/out paint event
        return img


class DrapedDef(PolygonDef):

    def __init__(self, filename, vertexcache, lookup, defs):
        PolygonDef.__init__(self, filename, vertexcache, lookup, defs)
        self.canpreview=True
        self.type=Locked.POL
        self.ortho=False
        self.hscale=100
        self.vscale=100
        alpha=True
        texture=None
    
        h=open(self.filename, 'rU')
        if not h.readline().strip()[0] in ['I','A']:
            raise IOError
        if not h.readline().split('#')[0].strip() in ['850']:
            raise IOError
        if not h.readline().strip() in ['DRAPED_POLYGON']:
            raise IOError
        for line in h:
            c=line.split()
            if not c: continue
            id=c[0]
            if id in ['TEXTURE', 'TEXTURE_NOWRAP']:
                if id=='TEXTURE_NOWRAP':
                    self.ortho=True
                    self.type=Locked.ORTHO
                texture=self.cleanpath(c[1])
            elif id=='SCALE':
                self.hscale=float(c[1]) or 1
                self.vscale=float(c[2]) or 1
            elif id=='LAYER_GROUP':
                self.setlayer(c[1], int(c[2]))
            elif id=='NO_ALPHA':
                alpha=False
        h.close()
        try:
            self.texture=vertexcache.texcache.get(texture, not self.ortho, alpha)
        except EnvironmentError, e:
            self.texerr=(texture, e.strerror)
        except:
            self.texerr=(texture, unicode(exc_info()[1]))


class DrapedFallback(DrapedDef):
    def __init__(self, filename, vertexcache, lookup, defs):
        PolygonDef.__init__(self, filename, vertexcache, lookup, defs)
        self.type=Locked.POL
        self.ortho=True
        self.hscale=10
        self.vscale=10
    

class ExcludeDef(PolygonDef):
    TABNAME='Exclusions'

    def __init__(self, filename, vertexcache, lookup, defs):
        PolygonDef.__init__(self, filename, vertexcache, lookup, defs)
        self.layer=ClutterDef.OUTLINELAYER
        self.type=Locked.EXCLUSION


class FacadeDef(PolygonDef):

    class Floor:
        def __init__(self, name):
            self.name=name
            self.height=0
            self.roofs=[]
            self.walls=[]

    class Wall:
        def __init__(self, name):
            self.name=name
            self.spellings=[]

    class Spelling:
        def __init__(self, segments, idx):
            self.width=0
            self.segments=[]
            for i in idx:
                self.width+=segments[i].width
                self.segments.append(segments[i])

    class Segment:
        def __init__(self):
            self.width=0
            self.mesh=[]
            self.children=[]	# [name, definition, is_draped, xdelta, ydelta, zdelta, hdelta]

    class v8Wall:
        def __init__(self):
            self.widths=[0,1]
            self.scale=[1,1]
            self.hpanels=[[],[],[]]	# left, center, right u coords
            self.vpanels=[[],[],[]]	# bottom, middle, top v coords
            self.basement=0		# basement depth v coords
            self.roofslope=0		# 0=vertical (no slope)
        def __repr__(self):
            return str(vars(self))

    class v8Panel:
        def __init__(self):
            self.width=1		# width or height
            self.texcoords=(0,1)	# (start, end)
        def __repr__(self):
            return str(vars(self))

    def __init__(self, filename, vertexcache, lookup, defs):
        PolygonDef.__init__(self, filename, vertexcache, lookup, defs)
        self.canpreview=True
        self.type=Locked.FAC

        self.ring=1
        self.two_sided=False
        self.texture_roof=0		# separate texture for roof
        self.walls=[]	# v8 facade
        self.roof=[]	# v8 facade
        self.floors=[]	# v10 facade
        self.version=800

        activelod=False
        currentfloor=currentsegment=currentwall=None
        rooftex=False
        texsize=(1,1)	# default values in v8
        objects=[]
        placements=[]
        segments=[]
        vt=[]
        h=open(self.filename, 'rU')
        if not h.readline().strip()[0] in ['I','A']:
            raise IOError
        version=h.readline().split('#')[0].strip()
        if not version in ['800', '1000']:
            raise IOError
        self.version=int(version)
        if not h.readline().strip() in ['FACADE']:
            raise IOError
        while True:
            line=h.readline()
            if not line: break
            c=line.split()
            if not c: continue
            id=c[0]
            if id=='TEXTURE':
                texture=self.cleanpath(c[1])
                try:
                    if rooftex:
                        self.texture_roof=vertexcache.texcache.get(texture)
                    else:
                        self.texture=vertexcache.texcache.get(texture)
                except EnvironmentError, e:
                    self.texerr=(texture, e.strerror)
                except:
                    self.texerr=(texture, unicode(exc_info()[1]))
            elif id=='RING':
                self.ring=int(c[1])
            elif id=='TWO_SIDED':
                self.two_sided=(int(c[1])!=0)
            elif id=='GRADED':
                self.fittomesh=False

            # v8
            elif id=='LOD':
                currentwall=None
                activelod=not float(c[1])	# Only do LOD with visibility starting at 0
            elif id=='TEX_SIZE' and activelod:	# Not sure if this is per-LOD. Definitely not per-wall.
                texsize=(float(c[1]), float(c[2]))
            elif id=='ROOF' and activelod:
                self.roof.append((float(c[1])/texsize[0], float(c[2])/texsize[1]))
            elif id=='ROOF_SCALE' and activelod:# v10 extension to v8 format
                self.roof=[(float(c[i])/texsize[0], float(c[i+1])/texsize[1]) for i in [1,3,5,7]]

            elif id=='WALL' and activelod:
                currentwall=FacadeDef.v8Wall()
                currentwall.widths=(float(c[1]),float(c[2]))
                self.walls.append(currentwall)
            elif id=='SCALE' and activelod:
                currentwall.scale=(float(c[1]),float(c[2]))
            elif id=='ROOF_SLOPE' and activelod:
                currentwall.roofslope=float(c[1])
            elif id=='BASEMENT_DEPTH' and activelod:
                currentwall.basement=float(c[1])/texsize[1]
            elif id in ['LEFT','CENTER','RIGHT'] and activelod:
                panel=FacadeDef.v8Panel()
                panel.texcoords=(float(c[1])/texsize[0],float(c[2])/texsize[0])
                panel.width=(panel.texcoords[1]-panel.texcoords[0])*currentwall.scale[0]
                currentwall.hpanels[['LEFT','CENTER','RIGHT'].index(id)].append(panel)
            elif id in ['BOTTOM','MIDDLE','TOP'] and activelod:
                panel=FacadeDef.v8Panel()
                panel.texcoords=(float(c[1])/texsize[1],float(c[2])/texsize[1])
                panel.width=(panel.texcoords[1]-panel.texcoords[0])*currentwall.scale[1]
                currentwall.vpanels[['BOTTOM','MIDDLE','TOP'].index(id)].append(panel)

            # v10
            elif id in ['SHADER_WALL','SHADER_ROOF']:
                rooftex=(id=='SHADER_ROOF')
            elif id=='ROOF_SCALE':
                self.roofscale=float(c[1])
            elif id=='OBJ':
                childname=c[1][:-4].replace(':', '/').replace('\\','/')+c[1][-4:].lower()
                if childname in lookup:
                    childfilename=lookup[childname].file
                else:
                    childfilename=join(dirname(filename),childname)	# names are relative to this .fac so may not be in global lookup
                if childfilename in defs:
                    definition=defs[childfilename]
                else:
                    try:
                        defs[childfilename]=definition=ObjectDef(childfilename, vertexcache, lookup, defs, make_editable=False)
                    except:
                        if __debug__:
                            print_exc()
                        defs[childfilename]=definition=ObjectFallback(childfilename, vertexcache, lookup, defs)
                objects.append((childname,definition))

            elif id=='FLOOR':
                currentfloor=FacadeDef.Floor(c[1])
                segments=[]
                currentsegment=None
                currentwall=None
                self.floors.append(currentfloor)
            elif id=='ROOF_HEIGHT':
                currentfloor.roofs.append(float(c[1]))
                currentfloor.height=max(currentfloor.height, float(c[1]))

            elif id=='SEGMENT':
                assert len(segments)==int(c[1])	# Assume segements are in order
                currentsegment=FacadeDef.Segment()
                segments.append(currentsegment)
                currentswall=None
            elif id=='SEGMENT_CURVED':
                currentsegment=None	# just skip it
            elif id=='MESH':		# priority? LOD_far? curved points? #vt #idx
                vt=[]			# note can have multiple meshes see lib/airport/Modern_Airports/Facades/modern1.fac:145
            elif id=='VERTEX' and currentsegment:
                x=float(c[1])
                y=float(c[2])
                z=float(c[3])
                currentsegment.width=max(currentsegment.width,-z)
                vt.append([x,y,z, float(c[7]),float(c[8])])
            elif id=='IDX' and currentsegment:
                currentsegment.mesh.extend(itemgetter(*map(int,c[1:7]))(vt))
            elif id in ['ATTACH_DRAPED', 'ATTACH_GRADED'] and currentsegment:
                (childname, definition)=objects[int(c[1])]
                if not isinstance(definition, ObjectFallback):	# skip fallbacks
                    currentsegment.children.append([childname, definition, id=='ATTACH_DRAPED', float(c[2]), float(c[3]), float(c[4]), float(c[5])])

            elif id=='WALL':		# LOD_near? LOD_far? ??? ??? name
                currentsegment=None
                currentwall=FacadeDef.Wall(c[5])
                currentfloor.walls.append(currentwall)

            elif id=='SPELLING':	# LOD_near? LOD_far? ??? ??? name
                currentwall.spellings.append(FacadeDef.Spelling(segments, map(int,c[1:])))

        if self.version>=1000:
            if not self.floors: raise IOError
            self.floors.sort(key=attrgetter('height'))		# layout code assumes floors are in ascending height
            for floor in self.floors:
                floor.roofs.sort(reverse=True)			# drawing marginally faster if we draw the top roof first
                if not floor.walls: raise IOError
                for wall in floor.walls:
                    if not wall.spellings: raise IOError
                    wall.spellings.sort(key=attrgetter('width'), reverse=True)	# layout code assumes spellings are in descending width
                    for spelling in wall.spellings:
                        if not spelling.width: raise IOError	# Can't handle zero-width segments
        else:	# v8
            if not self.walls: raise IOError
            for wall in self.walls:
                if not sum([p.width for panels in wall.hpanels for p in panels]): raise IOError	# must have some panels
                if not sum([p.width for panels in wall.vpanels for p in panels]): raise IOError	# must have some panels
            if self.roof and len(self.roof)!=4:
                self.roof=[self.roof[0], self.roof[0], self.roof[0], self.roof[0]]	# roof needs zero or four points

        h.close()

    # Skip allocation/deallocation of children - assumed that they're allocated on layout and flushed globally
    #def allocate(self, vertexcache):
    #    PolygonDef.allocate(self, vertexcache)
    #    for p in self.children:
    #        p[1].allocate(vertexcache)
    #
    #def flush(self):
    #    PolygonDef.flush(self)
    #    for p in self.children:
    #        p[1].flush()

    def preview(self, canvas, vertexcache):
        if self.version>=1000:
            return self.preview10(canvas, vertexcache)
        else:
            return self.preview8(canvas, vertexcache)

    def preview8(self, canvas, vertexcache):
        width=0
        wall=self.walls[0]		# just use first wall
        hpanels=wall.hpanels
        l=min([p.texcoords[0] for p in hpanels[0]+hpanels[1]+hpanels[2]])
        r=max([p.texcoords[1] for p in hpanels[0]+hpanels[1]+hpanels[2]])
        vpanels=wall.vpanels
        b=min([p.texcoords[0] for p in vpanels[0]+vpanels[1]+vpanels[2]])
        t=max([p.texcoords[1] for p in vpanels[0]+vpanels[1]+vpanels[2]])
        return PolygonDef.preview(self, canvas, vertexcache, l, b+wall.basement, r, t)

    def preview10(self, canvas, vertexcache):
        floor=self.floors[-1]		# highest floor
        wall=floor.walls[0]		# default wall
        maxsize=floor.height*1.5 or 4	# 4 chosen to make standard fence and jet blast shield look OK
        spelling=wall.spellings[0]	# longest spelling
        for s in wall.spellings:	# find smallest spelling that is larger than height
            if s.width>=maxsize: spelling=s
        maxsize=max(spelling.width, maxsize)
        pad=(maxsize-spelling.width)/2
        xoff=canvas.GetClientSize()[0]-ClutterDef.PREVIEWSIZE
        glViewport(xoff, 0, ClutterDef.PREVIEWSIZE, ClutterDef.PREVIEWSIZE)
        glClearColor(0.3, 0.5, 0.6, 1.0)	# Preview colour
        glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT)
        glMatrixMode(GL_PROJECTION)
        glPushMatrix()
        glLoadIdentity()
        glOrtho(-pad, maxsize-pad, 0, maxsize, -maxsize, maxsize)
        glMatrixMode(GL_MODELVIEW)
        glLoadIdentity()
        glRotatef(-90, 0,1,0)
        #glTranslatef(sizex-self.bbox.maxx, 0, sizez-self.bbox.maxz)
        canvas.glstate.set_color(COL_UNPAINTED)
        canvas.glstate.set_depthtest(True)
        canvas.glstate.set_poly(False)
        canvas.glstate.set_cull(True)
        canvas.glstate.set_texture(self.texture)
        glBegin(GL_TRIANGLES)
        hoffset=0
        for segment in spelling.segments:
            for v in segment.mesh:
                glTexCoord2f(v[3],v[4])
                glVertex3f(v[0],v[1],hoffset+v[2])
            hoffset-=segment.width
        glEnd()
        hoffset=0
        for segment in spelling.segments:
            for child in segment.children:
                (childname, definition, is_draped, xdelta, ydelta, zdelta, hdelta)=child
                definition.allocate(vertexcache)
        canvas.glstate.set_instance(vertexcache)
        for segment in spelling.segments:
            for child in segment.children:
                (childname, definition, is_draped, xdelta, ydelta, zdelta, hdelta)=child
                if definition.vdata is not None:
                    canvas.glstate.set_texture(definition.texture)
                    glPushMatrix()
                    glTranslatef(xdelta,ydelta,hoffset+zdelta)
                    glRotatef(hdelta, 0,1,0)
                    if definition.culled:
                        canvas.glstate.set_cull(True)
                        glDrawArrays(GL_TRIANGLES, definition.base, definition.culled)
                    if definition.nocull:
                        canvas.glstate.set_cull(False)
                        glDrawArrays(GL_TRIANGLES, definition.base+definition.culled, definition.nocull)
                    glPopMatrix()
            hoffset-=segment.width
        data=glReadPixels(xoff,0, ClutterDef.PREVIEWSIZE,ClutterDef.PREVIEWSIZE, GL_RGB, GL_UNSIGNED_BYTE)
        img=wx.EmptyImage(ClutterDef.PREVIEWSIZE, ClutterDef.PREVIEWSIZE, False)
        img.SetData(data)

        # Restore state for unproject & selection
        glMatrixMode(GL_PROJECTION)
        glPopMatrix()
        glMatrixMode(GL_MODELVIEW)

        glClearColor(0.5, 0.5, 1.0, 0.0)	# Sky
        glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT)
        canvas.Refresh()	# Mac draws from the back buffer w/out paint event
        return img.Mirror(False)


class FacadeFallback(FacadeDef):
    def __init__(self, filename, vertexcache, lookup, defs):
        PolygonDef.__init__(self, filename, vertexcache, lookup, defs)
        self.type=Locked.FAC
        self.ring=1
        self.version=800
        self.two_sided=True
        self.texture_roof=0
        self.roof=[]
        wall=FacadeDef.v8Wall()
        wall.scale=[10,10]
        panel=FacadeDef.v8Panel()
        panel.width=wall.scale[0]
        wall.hpanels[1]=wall.vpanels[0]=[panel]
        self.walls=[wall]


class ForestDef(PolygonDef):

    def __init__(self, filename, vertexcache, lookup, defs):
        PolygonDef.__init__(self, filename, vertexcache, lookup, defs)
        self.layer=ClutterDef.OUTLINELAYER
        self.canpreview=True
        self.type=Locked.FOR
        self.tree=None
        scalex=scaley=1
        best=0
        
        h=open(self.filename, 'rU')
        if not h.readline().strip()[0] in ['I','A']:
            raise IOError
        if not h.readline().split('#')[0].strip() in ['800']:
            raise IOError
        if not h.readline().strip() in ['FOREST']:
            raise IOError
        for line in h:
            c=line.split()
            if not c: continue
            id=c[0]
            if id=='TEXTURE':
                texture=self.cleanpath(c[1])
                try:
                    self.texture=vertexcache.texcache.get(texture)
                except EnvironmentError, e:
                    self.texerr=(texture, e.strerror)
                except:
                    self.texerr=(texture, unicode(exc_info()[1]))
            elif id=='SCALE_X':
                scalex=float(c[1])
            elif id=='SCALE_Y':
                scaley=float(c[1])
            elif id=='TREE':
                if len(c)>10 and float(c[6])>best and float(c[3])/scalex>.02 and float(c[4])/scaley>.02:
                    # choose most popular, unless it's tiny (placeholder)
                    best=float(c[6])
                    self.tree=(float(c[1])/scalex, float(c[2])/scaley,
                               (float(c[1])+float(c[3]))/scalex,
                               (float(c[2])+float(c[4]))/scaley)
        h.close()
        if not self.tree:
            raise IOError
                
    def preview(self, canvas, vertexcache):
        return PolygonDef.preview(self, canvas, vertexcache, *self.tree)


class ForestFallback(ForestDef):
    def __init__(self, filename, vertexcache, lookup, defs):
        PolygonDef.__init__(self, filename, vertexcache, lookup, defs)
        self.layer=ClutterDef.OUTLINELAYER
        self.type=Locked.FOR
        self.tree=None


class LineDef(PolygonDef):

    def __init__(self, filename, vertexcache, lookup, defs):
        PolygonDef.__init__(self, filename, vertexcache, lookup, defs)
        self.layer=ClutterDef.MARKINGLAYER
        self.canpreview=True
        self.type=Locked.UNKNOWN
        self.offsets=[]
        self.hscale=self.vscale=1
        width=1
        
        h=open(self.filename, 'rU')
        if not h.readline().strip()[0] in ['I','A']:
            raise IOError
        if not h.readline().split('#')[0].strip() in ['850']:
            raise IOError
        if not h.readline().strip() in ['LINE_PAINT']:
            raise IOError
        for line in h:
            c=line.split()
            if not c: continue
            id=c[0]
            if id=='TEXTURE':
                texture=self.cleanpath(c[1])
                try:
                    self.texture=vertexcache.texcache.get(texture)
                except EnvironmentError, e:
                    self.texerr=(texture, e.strerror)
                except:
                    self.texerr=(texture, unicode(exc_info()[1]))
            elif id=='SCALE':
                self.hscale=float(c[1])
                self.vscale=float(c[2])
            elif id=='TEX_WIDTH':
                width=float(c[1])
            elif id=='S_OFFSET':
                offsets=[float(c[2]), float(c[3]), float(c[4])]
            elif id=='LAYER_GROUP':
                self.setlayer(c[1], int(c[2]))
        h.close()
        self.offsets=[offsets[0]/width, offsets[1]/width, offsets[2]/width]
                
    def preview(self, canvas, vertexcache):
        return PolygonDef.preview(self, canvas, vertexcache,
                                  self.offsets[0], 0, self.offsets[2], 1,
                                  self.vscale/self.hscale)
        

class LineFallback(LineDef):
    def __init__(self, filename, vertexcache, lookup, defs):
        PolygonDef.__init__(self, filename, vertexcache, lookup, defs)
        self.layer=ClutterDef.MARKINGLAYER
        self.type=Locked.LIN


class NetworkDef(PolygonDef):
    TABNAME='Roads, Railways & Powerlines'
    DEFAULTFILE='lib/g8/roads.net'

    def __init__(self, filename, name, index, width, length, texture, poly, color):
        PolygonDef.__init__(self, filename, None)
        self.layer=ClutterDef.NETWORKLAYER
        self.canpreview=True
        self.type=Locked.NET
        self.name=name
        self.index=index
        self.width=width
        self.length=length
        self.height=None	# (min,max) height
        self.texname=texture
        self.poly=poly
        self.color=color
        self.even=False
        self.objs=[]		# (filename, lateral, onground, freq, offset)
        self.objdefs=[]
        self.segments=[]	# (lateral, vertical, s, lateral, vertical, s)
        
    def __str__(self):
        return '<%s %s>' % (self.filename, self.name)

    def allocate(self, vertexcache):
        # load texture and objects
        if not self.texture:
            try:
                self.texture=vertexcache.texcache.get(normpath(join(self.texpath, self.texname)))
            except EnvironmentError, e:
                self.texerr=(normpath(join(self.texpath, self.texname)), e.strerror)
            except:
                self.texerr=(normpath(join(self.texpath, self.texname)), unicode(exc_info()[1]))
        if self.objdefs:
            for o in self.objdefs:
                o.allocate(vertexcache)
        else:
            height=0
            for i in range(len(self.objs)):
                (filename, lateral, onground, freq, offset)=self.objs[i]
                if filename in defs:
                    defn=defs[filename]
                    defn.allocate(vertexcache)
                else:
                    defs[filename]=defn=ObjectDef(filename, vertexcache, lookup, defs)
                self.objdefs.append(defn)
                # Calculate height from objects
                if self.height:
                    pass
                elif onground:
                    for (x,y,z) in defn.vdata:
                        height=max(height,y)
                else:
                    for (x,y,z) in defn.vdata:
                        height=min(height,y)
            if height:
                if onground:
                    self.height=(0,round(height,1))
                else:
                    self.height=(0,round(-height,1))
                if __debug__: print "New height", self.height[1]

        # Calculate height from segments eg LocalRoadBridge
        if not self.objs:
            height=0
            for (lat1, vert1, s1, lat2, vert2, s2) in self.segments:
                height=min(height,vert1,vert2)
            if height<-2:	# arbitrary - allow for foundations
                self.height=(0,round(-height,1))
                if __debug__: print "New height", self.height[1]

        self.fittomesh=(self.height!=None)
            
    def flush(self):
        self.base=None
        for o in self.objdefs:
            o.flush()
        
    def preview(self, canvas, vertexcache):
        if __debug__: print "Preview", self.name, self.width, self.length, self.height
        self.allocate(vertexcache)
        canvas.glstate.set_instance(veretxcache)
        glViewport(0, 0, ClutterDef.PREVIEWSIZE, ClutterDef.PREVIEWSIZE)
        glClearColor(0.3, 0.5, 0.6, 1.0)	# Preview colour
        glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT)
        glMatrixMode(GL_PROJECTION)
        glPushMatrix()
        glLoadIdentity()
        if self.height:
            height=self.height[1]
        else:
            height=0
        maxsize=max(height*0.7,
                    self.length*2+self.width/4)	# eg PrimaryDividedWithSidewalksBridge
        glOrtho(-maxsize, maxsize, -maxsize/2, maxsize*1.5, -2*maxsize, 2*maxsize)
        glMatrixMode(GL_MODELVIEW)
        glLoadIdentity()
        glRotatef( 30, 1,0,0)
        glRotatef(120, 0,1,0)
        glTranslatef(0, height, -self.length*2)
        canvas.glstate.set_texture(self.texture)
        canvas.glstate.set_color(COL_UNPAINTED)
        canvas.glstate.set_cull(False)
        glBegin(GL_QUADS)
        for (lat1, vert1, s1, lat2, vert2, s2) in self.segments:
            #print lat1, vert1, s1, lat2, vert2, s2
            # repeat 4 times to get pylons
            length=0
            for l in range(4):
                glTexCoord2f(s1, 0)
                glVertex3f(lat1, vert1, length)
                glTexCoord2f(s2, 0)
                glVertex3f(lat2, vert2, length)
                length+=self.length
                glTexCoord2f(s2, 1)
                glVertex3f(lat2, vert2, length)
                glTexCoord2f(s1, 1)
                glVertex3f(lat1, vert1, length)
        glEnd()
        
        canvas.glstate.set_cull(True)
        for i in range(len(self.objs)):
            (filename, lateral, onground, freq, offset)=self.objs[i]
            #print lateral, freq, offset, filename
            obj=self.objdefs[i]
            if not freq: freq=self.length*4
            glPushMatrix()
            glTranslatef(lateral, -height*onground, offset)
            dist=offset
            while dist<=self.length*4:
                glBindTexture(GL_TEXTURE_2D, obj.texture)
                if obj.culled:
                    glDrawArrays(GL_TRIANGLES, obj.base, obj.culled+obj.nocull)
                glTranslatef(0, 0, freq)
                dist+=freq
            glPopMatrix()

        #glFinish()	# redundant
        data=glReadPixels(0,0, ClutterDef.PREVIEWSIZE,ClutterDef.PREVIEWSIZE, GL_RGB, GL_UNSIGNED_BYTE)
        img=wx.EmptyImage(ClutterDef.PREVIEWSIZE, ClutterDef.PREVIEWSIZE, False)
        img.SetData(data)
        
        # Restore state for unproject & selection
        glMatrixMode(GL_PROJECTION)
        glPopMatrix()	
        glMatrixMode(GL_MODELVIEW)

        glClearColor(0.5, 0.5, 1.0, 0.0)	# Sky
        glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT)
        canvas.Refresh()	# Mac draws from the back buffer w/out paint event
        return img.Mirror(False)        


class NetworkFallback(NetworkDef):
    def __init__(self, filename, name, index):
        PolygonDef.__init__(self, filename, None)
        self.layer=ClutterDef.NETWORKLAYER
        self.canpreview=False
        self.type=Locked.NET
        self.name=name
        self.index=index
        self.width=1
        self.length=1
        self.height=None	# (min,max) height
        self.color=(1.0,0.0,0.0)
        self.even=False


UnknownDefs=['.lin','.str','.agb','.ags']	# Known unknowns
SkipDefs=['.bch','.net']			# Ignore in library
KnownDefs=[ObjectDef.OBJECT, AutoGenPointDef.AGP, PolygonDef.FACADE, PolygonDef.FOREST, PolygonDef.DRAPED]+UnknownDefs
