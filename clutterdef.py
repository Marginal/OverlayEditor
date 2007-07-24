from math import fabs
from os import listdir
from os.path import abspath, dirname, exists, join, sep

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
    LAYERCOUNT=len(LAYERNAMES)*11+1-5
    EXCLUDELAYER=0	# before terrain -5
    TERRAINLAYER=LAYERNAMES.index('terrain')*11+1
    BEACHESLAYER=LAYERNAMES.index('beaches')*11+1
    TAXIWAYLAYER=LAYERNAMES.index('taxiways')*11+1
    RUNWAYSLAYER=LAYERNAMES.index('runways')*11+1
    DEFAULTLAYER=LAYERNAMES.index('objects')*11+1

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
        
    def setlayer(self, layer, n):
        if not -5<=n<=5: raise IOError
        if layer=='airports':
            if n==0:
                layer='runways'	# undefined!
            elif n<0:
                layer='shoulders'
            elif n>0:
                layer='markings'
        self.layer=ClutterDef.LAYERNAMES.index(layer)*11+n
        if self.layer<=0 or self.layer>=ClutterDef.LAYERCOUNT: raise IOError

    def layername(self):
        return "%s %+d" % (ClutterDef.LAYERNAMES[self.layer/11],
                           (self.layer%11)-5)

    def allocate(self, vertexcache):
        pass

    def flush(self):
        pass

class ObjectDef(ClutterDef):

    OBJECT='.obj'
    FALLBACK='*default.obj'
    
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
        self.maxsize=0.1	# mustn't be 0
        self.poly=0
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
                    uv=[float(c[1]), float(c[2]), float(c[3]), float(c[4])]
                    v=[]
                    for i in range(3):
                        c=h.readline().split()
                        v.append([float(c[0]), float(c[1]), float(c[2])])
                        self.maxsize=max(self.maxsize, fabs(v[i][0]), 0.55*v[i][1], fabs(v[i][2]))	# ad-hoc
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
                        self.maxsize=max(self.maxsize, fabs(v[i][0]), 0.55*v[i][1], fabs(v[i][2]))	# ad-hoc
                        v.append([float(c[3]), float(c[4]), float(c[5])])
                        self.maxsize=max(self.maxsize, fabs(v[i][0]), 0.55*v[i][1], fabs(v[i][2]))	# ad-hoc
                        t.append([float(c[6]), float(c[8])])
                        t.append([float(c[7]), float(c[9])])
                    for i in seq:
                        current.append(v[i])
                        tcurrent.append(t[i])
                else:	# quads: type 4, 5, 6, 7, 8
                    uv=[float(c[1]), float(c[2]), float(c[3]), float(c[4])]
                    v=[]
                    for i in range(4):
                        c=h.readline().split()
                        v.append([float(c[0]), float(c[1]), float(c[2])])
                        self.maxsize=max(self.maxsize, fabs(v[i][0]), 0.55*v[i][1], fabs(v[i][2]))	# ad-hoc
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
                    tcurrent=self.tculled
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
                        self.maxsize=max(self.maxsize, fabs(v[i][0]), 0.55*v[i][1], fabs(v[i][2]))	# ad-hoc
                        t.append([float(c[3]), float(c[4])])
                        if len(c)>5:	# Two per line
                            v.append([float(c[5]), float(c[6]), float(c[7])])
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
            while True:
                line=h.readline()
                if not line: break
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
                        vt.append([x,y,z])
                        vtt.append([float(c[7]), float(c[8])])
                        self.maxsize=max(self.maxsize, fabs(x), 0.55*y, fabs(z))	# ad-hoc
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
            fb=ObjectDef(ObjectDef.FALLBACK, vertexcache)
            (self.vdata, self.tdata, self.culled, self.nocull, self.poly, self.maxsize, self.base, self.texture)=(fb.vdata, fb.tdata, fb.culled, fb.nocull, fb.poly, fb.maxsize, fb.base, fb.texture)
        else:
            self.vdata=culled+nocull
            self.tdata=tculled+tnocull
            self.culled=len(culled)
            self.nocull=len(nocull)
            self.base=None
            self.allocate(vertexcache)
            self.texture=vertexcache.texcache.get(texture)

    def allocate(self, vertexcache):
        if self.base==None:
            self.base=vertexcache.allocate(self.vdata, self.tdata)

    def flush(self):
        self.base=None


class PolygonDef(ClutterDef):

    EXCLUDE='Exclude:'
    FACADE='.fac'
    FOREST='.for'
    DRAPED='.pol'
    BEACH='.bch'

    def __init__(self, filename, texcache):
        ClutterDef.__init__(self, filename, texcache)


class DrapedDef(PolygonDef):

    def __init__(self, filename, vertexcache):
        PolygonDef.__init__(self, filename, vertexcache)

        self.ortho=False
        self.hscale=100
        self.vscale=100
    
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
                tex=abspath(join(self.texpath, line[len(c[0]):].strip().replace(':', sep).replace('/', sep)))
                self.texture=vertexcache.texcache.get(tex)
            elif c[0]=='SCALE':
                self.hscale=float(c[1])
                self.vscale=float(c[2])
            elif c[0]=='LAYER_GROUP':
                self.setlayer(c[1], int(c[2]))
            # XXX NO_ALPHA
        h.close()

class DrapedFallback(PolygonDef):
    def __init__(self, filename, vertexcache):
        self.filename=filename
        self.texture=0
        self.layer=ClutterDef.DEFAULTLAYER
        self.ortho=False
        self.hscale=100
        self.vscale=100
    

class ExcludeDef(PolygonDef):

    def __init__(self, filename, vertexcache):
        # PolygonDef.__init__(self, filename, vertexcache) - don't fanny about with tex paths
        self.filename=filename
        self.texture=0
        self.layer=ClutterDef.EXCLUDELAYER


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
        self.horiz=[(0,1.0)]
        self.vert=[(0,1.0)]
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
                            elif c[0] in ['HARD_ROOF', 'HARD_WALL']:
                                pass
                            else:
                                raise IOError
                        break # stop after first WALL
                    else:
                        raise IOError
                break	# stop after first LOD
        h.close()
        if not self.horiz or not self.vert:
            raise IOError

class FacadeFallback(PolygonDef):
    def __init__(self, filename, vertexcache):
        self.filename=filename
        self.texture=0
        self.layer=ClutterDef.DEFAULTLAYER
        self.ring=1
        self.two_sided=False
        self.roof=[]
        self.roof_slope=0
        self.hscale=100
        self.vscale=100
        self.horiz=[]
        self.vert=[]
        self.hends=[0,0]
        self.vends=[0,0]


class ForestDef(PolygonDef):

    def __init__(self, filename, vertexcache):
        PolygonDef.__init__(self, filename, vertexcache)
        # XXX parse for preview

class ForestFallback(PolygonDef):
    def __init__(self, filename, vertexcache):
        self.filename=filename
        self.texture=0
        self.layer=ClutterDef.DEFAULTLAYER

UnknownDefs=['.lin', '.str']	# Known unknowns
SkipDefs=['.bch', '.net']	# Ignore in library
KnownDefs=[ObjectDef.OBJECT, PolygonDef.FACADE, PolygonDef.FOREST, PolygonDef.DRAPED]+UnknownDefs
