from math import fabs
from os import listdir
from os.path import abspath, dirname, exists, join, sep
from sys import maxint

from OpenGL.GL import *
import wx


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
# allocate -> (re)allocate into vertexcache
# flush -> discard vertexcache
#

def PolygonDefFactory(filename, vertexcache):
    "creates and initialises appropriate PolgonDef subclass based on file extension"
    # would like to have made this a 'static' method of PolygonDef
    if filename.startswith(PolygonDef.EXCLUDE):
        return ExcludeDef(filename, vertexcache)        
    ext=filename.lower()[-4:]
    if ext==PolygonDef.DRAPED:
        return DrapedDef(filename, vertexcache)
    elif ext==PolygonDef.FACADE:
        return FacadeDef(filename, vertexcache)
    elif ext==PolygonDef.FOREST:
        return ForestDef(filename, vertexcache)
    elif ext==ObjectDef.OBJECT:
        raise IOError		# not a polygon
    elif ext in SkipDefs:
        raise IOError		# what's this doing here?
    else:	# unknown polygon type
        return PolygonDef(filename, vertexcache)


class ClutterDef:
    LAYERNAMES=['terrain', 'beaches', 'shoulders', 'taxiways', 'runways', 'markings', 'roads', 'objects', 'light_objects', 'cars']
    LAYERCOUNT=len(LAYERNAMES)*11
    TERRAINLAYER=LAYERNAMES.index('terrain')*11+5
    BEACHESLAYER=LAYERNAMES.index('beaches')*11+5
    SHOULDERLAYER=LAYERNAMES.index('shoulders')*11+5
    TAXIWAYLAYER=LAYERNAMES.index('taxiways')*11+5
    RUNWAYSLAYER=LAYERNAMES.index('runways')*11+5
    OUTLINELAYER=LAYERNAMES.index('roads')*11+5	# for draped & exclusions
    DEFAULTLAYER=LAYERNAMES.index('objects')*11+5

    def __init__(self, filename, vertexcache):
        self.filename=filename
        if filename:
            if filename[0]=='*':	# this application's resource
                self.filename=join('Resources', filename[1:])
            co=sep+'custom objects'+sep
            if co in self.filename.lower():
                self.texpath=self.filename[:self.filename.lower().index(co)]
                for f in listdir(self.texpath):
                    if f.lower()=='custom object textures':
                        self.texpath=join(self.texpath,f)
                        break
            else:
                self.texpath=dirname(self.filename)        
        self.texture=0
        self.layer=ClutterDef.DEFAULTLAYER
        self.canpreview=True
        
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

class ObjectDef(ClutterDef):

    OBJECT='.obj'
    
    def __init__(self, filename, vertexcache):
        ClutterDef.__init__(self, filename, vertexcache)
        self.layer=None

        h=None
        culled=[]
        nocull=[]
        current=culled
        tculled=[]
        tnocull=[]
        tcurrent=tculled
        texture=None
        self.poly=0
        self.bbox=BBox()
        self.height=0.5	# musn't be 0
        h=file(self.filename, 'rU')
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
                tex=line.strip()
                if tex:
                    if '//' in tex: tex=tex[:tex.index('//')].strip()
                    tex=abspath(join(self.texpath, tex.replace(':', sep).replace('/', sep)))
                    break
            for ext in ['', '.png', '.PNG', '.bmp', '.BMP']:
                if exists(tex+ext):
                    texture=tex+ext
                    break
            else:
                texture=tex

        if version=='2':
            while True:
                line=h.readline()
                if not line: break
                c=line.split('//')[0].split()
                if not c: continue
                if c[0]=='99':
                    break
                if c[0]=='1':
                    h.readline()
                elif c[0]=='2':
                    h.readline()
                    h.readline()
                elif c[0] in ['6','7']:	# smoke
                    for i in range(4): h.readline()
                elif c[0]=='3':
                    # sst, clockwise, start with left top?
                    uv=[float(c[1]), float(c[2]), float(c[3]), float(c[4])]
                    v=[]
                    for i in range(3):
                        c=h.readline().split()
                        v.append([float(c[0]), float(c[1]), float(c[2])])
                        self.bbox.include(v[i][0], v[i][2])
                        self.height=max(self.height, v[i][1])
                    current.append(v[0])
                    tcurrent.append([uv[0],uv[3]])
                    current.append(v[1])
                    tcurrent.append([uv[1],uv[2]])
                    current.append(v[2])
                    tcurrent.append([uv[1],uv[3]])
                elif int(c[0]) < 0:	# strip
                    count=-int(c[0])
                    seq=[]
                    for i in range(0,count*2-2,2):
                        seq.extend([i,i+1,i+2,i+3,i+2,i+1])
                    v=[]
                    t=[]
                    for i in range(count):
                        c=h.readline().split()
                        v.append([float(c[0]), float(c[1]), float(c[2])])
                        self.bbox.include(v[-1][0], v[-1][2])
                        self.height=max(self.height, v[-1][1])
                        v.append([float(c[3]), float(c[4]), float(c[5])])
                        self.bbox.include(v[-1][0], v[-1][2])
                        self.height=max(self.height, v[-1][1])
                        t.append([float(c[6]), float(c[8])])
                        t.append([float(c[7]), float(c[9])])
                    for i in seq:
                        current.append(v[i])
                        tcurrent.append(t[i])
                else:	# quads: type 4, 5, 6, 7, 8
                    # sst, clockwise, start with right top
                    uv=[float(c[1]), float(c[2]), float(c[3]), float(c[4])]
                    v=[]
                    for i in range(4):
                        c=h.readline().split()
                        v.append([float(c[0]), float(c[1]), float(c[2])])
                        self.bbox.include(v[i][0], v[i][2])
                        self.height=max(self.height, v[i][1])
                    current.append(v[0])
                    tcurrent.append([uv[1],uv[3]])
                    current.append(v[1])
                    tcurrent.append([uv[1],uv[2]])
                    current.append(v[2])
                    tcurrent.append([uv[0],uv[2]])
                    current.append(v[0])
                    tcurrent.append([uv[1],uv[3]])
                    current.append(v[2])
                    tcurrent.append([uv[0],uv[2]])
                    current.append(v[3])
                    tcurrent.append([uv[0],uv[3]])
        elif version=='700':
            while True:
                line=h.readline()
                if not line: break
                c=line.split('//')[0].split()
                if not c: continue
                if c[0]=='end':
                    break
                elif c[0]=='ATTR_LOD':
                    if float(c[1])!=0: break
                elif c[0]=='ATTR_poly_os':
                    self.poly=max(self.poly,int(float(c[1])))
                elif c[0]=='ATTR_cull':
                    current=culled
                    tcurrent=tculled
                elif c[0]=='ATTR_no_cull':
                    current=nocull
                    tcurrent=tnocull
                elif c[0]=='ATTR_layer_group':
                    self.setlayer(c[1], int(c[2]))
                elif c[0] in ['tri', 'quad', 'quad_hard', 'polygon', 
                              'quad_strip', 'tri_strip', 'tri_fan',
                              'quad_movie']:
                    count=0
                    seq=[]
                    if c[0]=='tri':
                        count=3
                        seq=[0,1,2]
                    elif c[0]=='polygon':
                        count=int(c[1])
                        for i in range(1,count-1):
                            seq.extend([0,i,i+1])
                    elif c[0]=='quad_strip':
                        count=int(c[1])
                        for i in range(0,count-2,2):
                            seq.extend([i,i+1,i+2,i+3,i+2,i+1])
                    elif c[0]=='tri_strip':
                        count=int(c[1])
                        for i in range(0,count-2):
                            if i&1:
                                seq.extend([i+2,i+1,i])
                            else:
                                seq.extend([i,i+1,i+2])
                    elif c[0]=='tri_fan':
                        count=int(c[1])
                        for i in range(1,count-1):
                            seq.extend([0,i,i+1])
                    else:	# quad
                        count=4
                        seq=[0,1,2,0,2,3]
                    v=[]
                    t=[]
                    i=0
                    while i<count:
                        c=h.readline().split()
                        v.append([float(c[0]), float(c[1]), float(c[2])])
                        self.bbox.include(v[i][0], v[i][2])
                        self.height=max(self.height, v[i][1])
                        t.append([float(c[3]), float(c[4])])
                        if len(c)>5:	# Two per line
                            v.append([float(c[5]), float(c[6]), float(c[7])])
                            self.bbox.include(v[i+1][0], v[i+1][2])
                            self.height=max(self.height, v[i+1][1])
                            t.append([float(c[8]), float(c[9])])
                            i+=2
                        else:
                            i+=1
                    for i in seq:
                        current.append(v[i])
                        tcurrent.append(t[i])
        elif version=='800':
            vt=[]
            vtt=[]
            idx=[]
            anim=[]
            for line in h:
                c=line.split('#')[0].split('//')[0].split()
                if not c: continue
                if c[0]=='TEXTURE':
                    if len(c)>1:
                        tex=line[7:].strip()
                        if '//' in tex: tex=tex[:tex.index('//')].strip()
                        texture=abspath(join(self.texpath, tex.replace(':', sep).replace('/', sep)))
                elif c[0]=='VT':
                    x=float(c[1])
                    y=float(c[2])
                    z=float(c[3])
                    self.bbox.include(x,z)
                    self.height=max(self.height, y)
                    vt.append([x,y,z])
                    vtt.append([float(c[7]), float(c[8])])
                elif c[0]=='IDX':
                    idx.append(int(c[1]))
                elif c[0]=='IDX10':
                    idx.extend([int(c[i]) for i in range(1,11)])
                elif c[0]=='ATTR_LOD':
                    if float(c[1])!=0: break
                elif c[0]=='ATTR_poly_os':
                    self.poly=max(self.poly,int(float(c[1])))
                elif c[0]=='ATTR_cull':
                    current=culled
                    tcurrent=tculled
                elif c[0]=='ATTR_no_cull':
                    current=nocull
                    tcurrent=tnocull
                elif c[0]=='ATTR_layer_group':
                    self.setlayer(c[1], int(c[2]))
                elif c[0]=='ANIM_begin':
                    if anim:
                        anim.append(list(anim[-1]))
                    else:
                        anim=[[0,0,0]]
                elif c[0]=='ANIM_end':
                    anim.pop()
                elif c[0]=='ANIM_trans':
                    anim[-1]=[anim[-1][i]+float(c[i+1]) for i in range(3)]
                elif c[0]=='TRIS':
                    start=int(c[1])
                    new=int(c[2])
                    if anim:
                        current.extend([[vt[idx[i]][j]+anim[-1][j] for j in range (3)] for i in range(start, start+new)])
                    else:
                        current.extend([vt[idx[i]] for i in range(start, start+new)])
                    tcurrent.extend([vtt[idx[i]] for i in range(start, start+new)])
        h.close()

        if self.layer==None:
            if self.poly:
                self.layer=ClutterDef.DEFAULTLAYER-1	# implicit
            else:
                self.layer=ClutterDef.DEFAULTLAYER

        if not (len(culled)+len(nocull)):
            # show empty objects as placeholders otherwise can't edit
            fb=ObjectFallback(filename, vertexcache)
            (self.vdata, self.tdata, self.culled, self.nocull, self.poly, self.bbox, self.height, self.base, self.texture, self.canpreview)=(fb.vdata, fb.tdata, fb.culled, fb.nocull, fb.poly, fb.bbox, fb.height, fb.base, fb.texture, fb.canpreview)
            # re-use above allocation
        else:
            self.vdata=culled+nocull
            self.tdata=tculled+tnocull
            self.culled=len(culled)
            self.nocull=len(nocull)
            self.base=None
            self.texture=vertexcache.texcache.get(texture)
            self.allocate(vertexcache)

    def allocate(self, vertexcache):
        if self.base==None:
            self.base=vertexcache.allocate(self.vdata, self.tdata)

    def flush(self):
        self.base=None

    def preview(self, canvas, vertexcache):
        if not self.canpreview: return None
        self.allocate(vertexcache)
        vertexcache.realize(canvas)
        canvas.SetCurrent()
        glViewport(0, 0, 300, 300)
        glClearColor(0.3, 0.5, 0.6, 1.0)	# Preview colour
        glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT)
        glMatrixMode(GL_PROJECTION)
        glPushMatrix()
        glLoadIdentity()
        sizex=(self.bbox.maxx-self.bbox.minx)*0.5
        sizez=(self.bbox.maxz-self.bbox.minz)*0.5
        maxsize=max(self.height*0.7,		# height
                    sizex*0.9 + sizez*0.52,	# width at 30degrees
                    sizex*0.26  + sizez*0.45)	# depth at 30degrees / 2
        glOrtho(-maxsize, maxsize, -maxsize/2, maxsize*1.5, -2*maxsize, 2*maxsize)
        glMatrixMode(GL_MODELVIEW)
        glPushMatrix()
        glLoadIdentity()
        glRotatef( 30, 1,0,0)
        glRotatef(-30, 0,1,0)
        glTranslatef(sizex-self.bbox.maxx, 0, sizez-self.bbox.maxz)
        if __debug__:
            glColor3f(0.8, 0.8, 0.8)	# Unpainted
            glBindTexture(GL_TEXTURE_2D, 0)
            for height in [0, self.height]:
                glBegin(GL_LINE_LOOP)
                glVertex3f(self.bbox.minx, height, self.bbox.minz)
                glVertex3f(self.bbox.maxx, height, self.bbox.minz)
                glVertex3f(self.bbox.maxx, height, self.bbox.maxz)
                glVertex3f(self.bbox.minx, height, self.bbox.maxz)
                glEnd()
        glColor3f(1.0, 0.25, 0.25)	# Cursor
        glBegin(GL_POINTS)
        glVertex3f(0, 0, 0)
        glEnd()
        glColor3f(0.8, 0.8, 0.8)	# Unpainted
        glBindTexture(GL_TEXTURE_2D, self.texture)
        if self.culled:
            glDrawArrays(GL_TRIANGLES, self.base, self.culled)
        if self.nocull:
            glDisable(GL_CULL_FACE)
            glDrawArrays(GL_TRIANGLES, self.base+self.culled, self.nocull)
            glEnable(GL_CULL_FACE)
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
        canvas.Refresh()	# Mac draws from the back buffer w/out paint event
        return img.Mirror(False)
        

class ObjectFallback(ObjectDef):
    def __init__(self, filename, vertexcache):
        ClutterDef.__init__(self, filename, vertexcache)
        self.filename=filename
        self.texture=0
        self.layer=ClutterDef.DEFAULTLAYER
        self.canpreview=False
        self.vdata=[[-0.5, 1.0, 0.5], [-0.5, 1.0, -0.5], [0.5, 1.0, -0.5], [-0.5, 1.0, 0.5], [0.5, 1.0, -0.5], [0.5, 1.0, 0.5], [-0.5, 0.0, 0.5], [-0.5, 1.0, 0.5], [0.5, 1.0, 0.5], [-0.5, 0.0, 0.5], [0.5, 1.0, 0.5], [0.5, 0.0, 0.5], [-0.5, 0.0, -0.5], [-0.5, 1.0, -0.5], [-0.5, 1.0, 0.5], [-0.5, 0.0, -0.5], [-0.5, 1.0, 0.5], [-0.5, 0.0,0.5], [0.5, 0.0, -0.5], [0.5, 1.0, -0.5], [-0.5, 1.0, -0.5], [0.5, 0.0, -0.5], [-0.5, 1.0, -0.5], [-0.5, 0.0, -0.5], [0.5, 1.0, -0.5], [0.5, 0.0, -0.5], [0.5, 0.0, 0.5], [0.5, 1.0, -0.5], [0.5, 0.0, 0.5], [0.5, 1.0, 0.5]]
        self.tdata=[[0.0,0.0] for i in self.vdata]
        self.culled=len(self.vdata)
        self.nocull=0
        self.poly=0
        self.bbox=BBox(-0.5,0.5,-0.5,0.5)
        self.height=1.0
        self.base=None
        self.allocate(vertexcache)


class PolygonDef(ClutterDef):

    EXCLUDE='Exclude:'
    FACADE='.fac'
    FOREST='.for'
    DRAPED='.pol'
    BEACH='.bch'

    def __init__(self, filename, texcache):
        ClutterDef.__init__(self, filename, texcache)

    def preview(self, canvas, vertexcache, l=0, b=0, r=1, t=1):
        if not self.texture or not self.canpreview: return None
        canvas.SetCurrent()
        glViewport(0, 0, 300, 300)
        glClearColor(0.3, 0.5, 0.6, 1.0)	# Preview colour
        glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT)
        glMatrixMode(GL_PROJECTION)
        glPushMatrix()
        glLoadIdentity()
        glMatrixMode(GL_MODELVIEW)
        glPushMatrix()
        glLoadIdentity()
        glColor3f(1.0, 1.0, 1.0)
        glBindTexture(GL_TEXTURE_2D, self.texture)
        glBegin(GL_QUADS)
        glTexCoord2f(l,b)
        glVertex3f(-1,  1, 0)
        glTexCoord2f(r,b)
        glVertex3f( 1,  1, 0)
        glTexCoord2f(r,t)
        glVertex3f( 1, -1, 0)
        glTexCoord2f(l,t)
        glVertex3f(-1, -1, 0)
        glEnd()
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
        canvas.Refresh()	# Mac draws from the back buffer w/out paint event
        return img


class DrapedDef(PolygonDef):

    def __init__(self, filename, vertexcache):
        PolygonDef.__init__(self, filename, vertexcache)

        self.ortho=False
        self.hscale=100
        self.vscale=100
        alpha=True
        texture=None
    
        h=file(filename, 'rU')
        if not h.readline().strip()[0] in ['I','A']:
            raise IOError
        if not h.readline().split('#')[0].strip() in ['850']:
            raise IOError
        if not h.readline().strip() in ['DRAPED_POLYGON']:
            raise IOError
        while True:
            line=h.readline()
            if not line: break
            c=line.split('#')[0].split()
            if not c: continue
            if c[0] in ['TEXTURE', 'TEXTURE_NOWRAP']:
                if c[0]=='TEXTURE_NOWRAP': self.ortho=True
                texture=line[len(c[0]):].strip().replace(':', sep).replace('/', sep)
            elif c[0]=='SCALE':
                self.hscale=float(c[1]) or 1
                self.vscale=float(c[2]) or 1
            elif c[0]=='LAYER_GROUP':
                self.setlayer(c[1], int(c[2]))
            elif c[0]=='NO_ALPHA':
                alpha=False
        h.close()
        self.texture=vertexcache.texcache.get(abspath(join(self.texpath, texture)), not self.ortho, alpha)


class DrapedFallback(PolygonDef):
    def __init__(self, filename, vertexcache):
        self.filename=filename
        self.texture=0
        self.layer=ClutterDef.DEFAULTLAYER
        self.canpreview=False
        self.ortho=False
        self.hscale=100
        self.vscale=100
    

class ExcludeDef(PolygonDef):

    def __init__(self, filename, vertexcache):
        # PolygonDef.__init__(self, filename, vertexcache) - don't fanny about with tex paths
        self.filename=filename
        self.texture=0
        self.layer=ClutterDef.OUTLINELAYER
        self.canpreview=False


class FacadeDef(PolygonDef):
    def __init__(self, filename, vertexcache):
        PolygonDef.__init__(self, filename, vertexcache)

        # Only reads first wall in first LOD
        self.ring=0
        self.two_sided=False
        self.roof=[]
        # per-wall
        self.roof_slope=0
        self.hscale=100
        self.vscale=100
        self.horiz=[]
        self.vert=[]
        self.hends=[0,0]
        self.vends=[0,0]
    
        h=file(self.filename, 'rU')
        if not h.readline().strip()[0] in ['I','A']:
            raise IOError
        if not h.readline().split('#')[0].strip() in ['800']:
            raise IOError
        if not h.readline().strip() in ['FACADE']:
            raise IOError
        while True:
            line=h.readline()
            if not line: break
            c=line.split('#')[0].split()
            if not c: continue
            if c[0]=='TEXTURE' and len(c)>1:
                tex=abspath(join(self.texpath, line[7:].strip().replace(':', sep).replace('/', sep)))
                self.texture=vertexcache.texcache.get(tex)
            elif c[0]=='RING':
                self.ring=int(c[1])
            elif c[0]=='TWO_SIDED': self.two_sided=(int(c[1])!=0)
            elif c[0]=='LOD':
                # LOD
                roof=[]
                while True:
                    line=h.readline()
                    if not line: break
                    c=line.split('#')[0].split()
                    if not c: continue
                    if c[0]=='LOD': break	# stop after first LOD
                    elif c[0]=='ROOF':
                        roof.append((float(c[1]), float(c[2])))
                    elif c[0]=='WALL':
                        # WALL
                        if len(roof) in [0,4]:
                            self.roof=roof
                        else:
                            self.roof=[roof[0], roof[0], roof[0], roof[0]]
                        while True:
                            line=h.readline()
                            if not line: break
                            c=line.split('#')[0].split()
                            if not c: continue
                            if c[0] in ['LOD', 'WALL']: break
                            elif c[0]=='SCALE':
                                self.hscale=float(c[1])
                                self.vscale=float(c[2])
                            elif c[0]=='ROOF_SLOPE':
                                self.roof_slope=float(c[1])
                            elif c[0] in ['LEFT', 'CENTER', 'RIGHT']:
                                self.horiz.append((float(c[1]),float(c[2])))
                                if c[0]=='LEFT': self.hends[0]+=1
                                elif c[0]=='RIGHT': self.hends[1]+=1
                            elif c[0] in ['BOTTOM', 'MIDDLE', 'TOP']:
                                self.vert.append((float(c[1]),float(c[2])))
                                if c[0]=='BOTTOM': self.vends[0]+=1
                                elif c[0]=='TOP': self.vends[1]+=1
                        break # stop after first WALL
                break	# stop after first LOD
        h.close()
        if not self.horiz or not self.vert:
            raise IOError

    def preview(self, canvas, vertexcache):
        return PolygonDef.preview(self, canvas, vertexcache,
                                  self.horiz[0][0], self.vert[0][0],
                                  self.horiz[-1][1], self.vert[-1][1])


class FacadeFallback(PolygonDef):
    def __init__(self, filename, vertexcache):
        self.filename=filename
        self.texture=0
        self.layer=ClutterDef.DEFAULTLAYER
        self.canpreview=False
        self.ring=1
        self.two_sided=True
        self.roof=[]
        self.roof_slope=0
        self.hscale=1
        self.vscale=1
        self.horiz=[(0.0,1.0)]
        self.vert=[(0.0,1.0)]
        self.hends=[0,0]
        self.vends=[0,0]


class ForestDef(PolygonDef):

    def __init__(self, filename, vertexcache):
        PolygonDef.__init__(self, filename, vertexcache)
        self.layer=ClutterDef.OUTLINELAYER
        self.ortho=False	# cos Forest derives from Draped
        self.tree=None
        scalex=scaley=1
        best=0
        
        h=file(self.filename, 'rU')
        if not h.readline().strip()[0] in ['I','A']:
            raise IOError
        if not h.readline().split('#')[0].strip() in ['800']:
            raise IOError
        if not h.readline().strip() in ['FOREST']:
            raise IOError
        while True:
            line=h.readline()
            if not line: break
            c=line.split('#')[0].split()
            if not c: continue
            if c[0]=='TEXTURE' and len(c)>1:
                tex=abspath(join(self.texpath, line[7:].strip().replace(':', sep).replace('/', sep)))
                self.texture=vertexcache.texcache.get(tex)
            elif c[0]=='SCALE_X':
                scalex=float(c[1])
            elif c[0]=='SCALE_Y':
                scaley=float(c[1])
            elif c[0]=='TREE':
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


class ForestFallback(PolygonDef):
    def __init__(self, filename, vertexcache):
        self.filename=filename
        self.texture=0
        self.layer=ClutterDef.OUTLINELAYER
        self.canpreview=False

UnknownDefs=['.lin', '.str']	# Known unknowns
SkipDefs=['.bch', '.net']	# Ignore in library
KnownDefs=[ObjectDef.OBJECT, PolygonDef.FACADE, PolygonDef.FOREST, PolygonDef.DRAPED]+UnknownDefs
