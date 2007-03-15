from os import listdir
from os.path import abspath, dirname, sep

# Virtual class for ground clutter definitions
#
# Derived classes expected to have following members:
# __init__
# __str__
#

DefaultClutter=ObjectDef('*default.obj')

def PolygonDefFactory(filename, texcache):
    "creates and initialises appropriate PolgonDef subclass based on file extension"
    # would like to have made this a 'static' method of PolygonDef
    ext=filename.lower()[-4:]
    if ext==PolygonDef.FACADE:
        return FacadeDef(filename, texcache)
    elif ext==PolygonDef.FOREST:
        return ForestDef(filename, texcache)
    elif ext==PolygonDef.DRAPED:
        return DrapedDef(filename, texcache)
    elif ext=='.obj':
        raise IOError
    else:	# unknown type
        return PolygonDef(filename, texcache)


class ClutterDef:
    LAYERNAMES=['terrain', 'beaches', 'shoulders', 'taxiways', 'runways', 'markings', 'roads', 'objects', 'light_objects', 'cars']
    DEFAULTLAYER=LAYERNAMES.index('objects')*11+5

    def __init__(self, filename, texcache):
        self.filename=filename
        co=sep+'custom objects'+sep
        if co in filename.lower():
            self.texpath=filename[:filename.lower().index(co)]
            for f in listdir(self.texpath):
                if f.lower()=='custom object textures':
                    self.texpath=join(self.texpath,f)
                    break
        else:
            self.texpath=dirname(filename)        
        self.texture=0
        self.layer=ClutterDef.DEFAULTLAYER
        self.reload(texcache)

    def setlayer(self, layerstr):
        l=layerstr.split()
        if len(l)!=2: raise IOError
        n=int(l[2])
        if -5<=n<=5: raise IOError
        if l[0]=='airports':
            if n==0:
                l[0]='runways'	# undefined!
            elif n<0:
                l[0]='shoulders'
            elif n>0:
                l[0]='markings'
        self.layer=ClutterDef.LAYERNAMES.index(l[0])*11+5+n

    def layername(self):
        return "%s %+d" % (ClutterDef.LAYERNAMES[self.layer/11],
                           (self.layer%11)-5)

class PolygonDef(ClutterDef):
    FACADE='.fac'
    FOREST='.for'
    DRAPED='.pol'

    EXCLUDE_NAME={'sim/exclude_bch': 'Exclude: Beaches',
                  'sim/exclude_pol': 'Exclude: Draped',
                  'sim/exclude_fac': 'Exclude: Facades',
                  'sim/exclude_for': 'Exclude: Forests',
                  'sim/exclude_obj': 'Exclude: Objects',
                  'sim/exclude_net': 'Exclude: Roads',
                  'sim/exclude_str': 'Exclude: Strings'}

    def __init__(self, filename, texcache):
        ClutterDef.__init__(self, filename, texcache)

    def reload(self, texcache):
        # for unknown polygons
        pass


class ExcludeDef(PolygonDef):
    def __init__(self, filename, texcache):
        PolygonDef.__init__(self, filename, texcache)


class FacadeDef(PolygonDef):
    def __init__(self, filename, texcache):
        PolygonDef.__init__(self, filename, texcache)

    def reload(self, texcache):
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
                tex=line[7:].strip()
                tex=tex.replace(':', sep)
                tex=tex.replace('/', sep)
                tex=abspath(join(self.texpath,tex))
                if exists(tex):
                    self.texture=texcache.get(tex)
                elif debug: print 'Failed to find texture "%s"' % tex
            elif c[0]=='RING':
                if int(c[1]): self.ring=1
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


class ForestDef(PolygonDef):
    def __init__(self, filename, texcache):
        PolygonDef.__init__(self, filename, texcache)


class DrapedDef:

    def __init__(self, filename, texcache):
        PolygonDef.__init__(self, filename, texcache)

    def reload(self, texcache):
        self.texture=0
        self.ortho=False
        self.hscale=100
        self.vscale=100
        self.layer=None
    
        h=file(path, 'rU')
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
            if c[0] in ['TEXTURE', 'TEXTURE_NOWRAP'] and len(c)>1:
                if c[0]=='TEXTURE_NOWRAP':
                    self.ortho=True
                tex=line[7:].strip()
                tex=tex.replace(':', sep)
                tex=tex.replace('/', sep)
                tex=abspath(join(self.texpath,tex))
                if exists(tex):
                    self.texture=texcache.get(tex)
                elif debug: print 'Failed to find texture "%s"' % tex
            elif c[0]=='SCALE':
                self.hscale=float(c[1])
                self.vscale=float(c[2])
        h.close()


class ObjectDef(ClutterDef):
    def __init__(self, filename, texcache):
        ClutterDef.__init__(self, filename, texcache)

    def reload(self, texcache):
        h=None
        culled=[]
        nocull=[]
        current=culled
        tculled=[]
        tnocull=[]
        tcurrent=tculled
        texture=None
        maxsize=0.1	# mustn't be 0
        maxpoly=0
        h=file(self.filename, 'rU')
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
                    tex=tex.replace(':', sep)
                    tex=tex.replace('/', sep)
                    break
            tex=abspath(join(self.texpath,tex))
            for ext in ['', '.png', '.PNG', '.bmp', '.BMP']:
                if exists(tex+ext):
                    texture=tex+ext
                    break
            else:
                if debug: print 'Failed to find texture "%s"' % tex
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
                        maxsize=max(maxsize, fabs(v[i][0]), 0.55*v[i][1], fabs(v[i][2]))	# ad-hoc
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
                        maxsize=max(maxsize, fabs(v[i][0]), 0.55*v[i][1], fabs(v[i][2]))	# ad-hoc
                        v.append([float(c[3]), float(c[4]), float(c[5])])
                        maxsize=max(maxsize, fabs(v[i][0]), 0.55*v[i][1], fabs(v[i][2]))	# ad-hoc
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
                        maxsize=max(maxsize, fabs(v[i][0]), 0.55*v[i][1], fabs(v[i][2]))	# ad-hoc
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
                    maxpoly=max(maxpoly,int(float(c[1])))
                elif c[0]=='ATTR_cull':
                    current=culled
                    tcurrent=tculled
                elif c[0]=='ATTR_no_cull':
                    current=nocull
                    tcurrent=tnocull
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
                        maxsize=max(maxsize, fabs(v[i][0]), 0.55*v[i][1], fabs(v[i][2]))	# ad-hoc
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
            idx=[]
            anim=[[0,0,0]]
            while True:
                line=h.readline()
                if not line: break
                c=line.split('#')[0].split()
                if not c: continue
                if c[0]=='TEXTURE':
                    if len(c)>1:
                        tex=line[7:].strip()
                        if '//' in tex: tex=tex[:tex.index('//')].strip()
                        tex=tex.replace(':', sep)
                        tex=tex.replace('/', sep)
                        tex=abspath(join(self.texpath,tex))
                        for ext in ['', '.png', '.PNG', '.bmp', '.BMP']:
                            if exists(tex+ext):
                                texture=tex+ext
                                break
                        else:
                            if debug: print 'Failed to find texture "%s"' % tex
                elif c[0]=='VT':
                    vt.append([float(c[1]), float(c[2]), float(c[3]),
                               float(c[7]), float(c[8])])
                    maxsize=max(maxsize, fabs(vt[-1][0]), 0.55*vt[-1][1], fabs(vt[-1][2]))	# ad-hoc
                elif c[0]=='IDX':
                    idx.append(int(c[1]))
                elif c[0]=='IDX10':
                    idx.extend([int(c[1]), int(c[2]), int(c[3]), int(c[4]), int(c[5]), int(c[6]), int(c[7]), int(c[8]), int(c[9]), int(c[10])])
                elif c[0]=='ATTR_LOD':
                    if float(c[1])!=0: break
                elif c[0]=='ATTR_poly_os':
                    maxpoly=max(maxpoly,int(float(c[1])))
                elif c[0]=='ATTR_cull':
                    current=culled
                    tcurrent=tculled
                elif c[0]=='ATTR_no_cull':
                    current=nocull
                    tcurrent=tnocull
                elif c[0]=='ANIM_begin':
                    anim.append([anim[-1][0], anim[-1][1], anim[-1][2]])
                elif c[0]=='ANIM_end':
                    anim.pop()
                elif c[0]=='ANIM_trans':
                    anim[-1]=[anim[-1][0]+float(c[1]),
                              anim[-1][1]+float(c[2]),
                              anim[-1][2]+float(c[3])]
                elif c[0]=='TRIS':
                    for i in range(int(c[1]), int(c[1])+int(c[2])):
                        v=vt[idx[i]]
                        current.append([anim[-1][0]+v[0],
                                        anim[-1][1]+v[1],
                                        anim[-1][2]+v[2]])
                        tcurrent.append([v[3], v[4]])
        h.close()
        if not (len(culled)+len(nocull)):
            if usefallback!=0:
                # show empty objects as placeholders otherwise can't edit
                self.load('*default.obj')
                self.objcache[name]=self.idx[path]=self.get('*default.obj')
            else:
                return False
        else:
            self.geo[path]=(culled, nocull, tculled, tnocull, texture, maxpoly, maxsize)
            base=len(self.varray)
            self.varray.extend(culled)
            self.varray.extend(nocull)
            self.tarray.extend(tculled)
            self.tarray.extend(tnocull)
            texno=self.texcache.get(texture)
            self.objcache[name]=self.idx[path]=(base, len(culled), len(nocull), texno, maxpoly, maxsize)
            self.valid=False	# new geometry -> need to update OpenGL
            
