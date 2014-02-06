import gc
from math import cos, fabs, pi, radians, sin
import numpy
from numpy import array, array_equal, concatenate, copy, diag, dot, identity, logical_and, outer, vstack, zeros, float32
from operator import itemgetter, attrgetter
from os import listdir
from os.path import basename, dirname, exists, join, normpath, sep
from sys import maxint, exc_info

from OpenGL.GL import *
from OpenGL.arrays import vbo
from OpenGL.extensions import alternate
from OpenGL.GL.ARB.instanced_arrays import glVertexAttribDivisorARB
from OpenGL.GL.ARB.draw_instanced import glDrawArraysInstancedARB
glDrawArraysInstanced = alternate(glDrawArraysInstanced, glDrawArraysInstancedARB, platform.createExtensionFunction('glDrawArraysInstancedARB', dll=platform.GL, extension='GL_ARB_instanced_arrays', argTypes=(constants.GLenum,constants.GLint,constants.GLsizei,constants.GLsizei)))	# Handle systems that support GL_ARB_instanced_arrays but not GL_ARB_draw_instanced

from elevation import BBox

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
COL_SELBEZ   =(0.75,0.325,0.75)
COL_DRAGBOX  =(0.75,0.325,0.75)
COL_SELNODE  =(1.0, 1.0, 1.0)
COL_SELBEZHANDLE   =(1.0, 0.75, 1.0)
COL_CURSOR   =(1.0, 0.25,0.25)
COL_NETWORK  =(0.5, 0.5, 0.5)

fallbacktexture='Resources/fallback.png'


# Virtual class for ground clutter definitions
#
# Derived classes expected to have following members:
# __init__
# __str__
# layername
# setlayer
# allocate -> (re)allocate into instance VBO (including any children needed for preview)
# flush -> forget instance VBO allocation
#

class ClutterDef:

    LAYERNAMES=['terrain', 'beaches', 'shoulders', 'taxiways', 'runways', 'markings', 'roads', 'objects', 'light_objects', 'cars']
    BEACHESLAYER  = LAYERNAMES.index('beaches')*11+5
    SHOULDERLAYER = LAYERNAMES.index('shoulders')*11+5
    TAXIWAYLAYER  = LAYERNAMES.index('taxiways')*11+5
    RUNWAYSLAYER  = LAYERNAMES.index('runways')*11+5
    MARKINGSLAYER = LAYERNAMES.index('markings')*11+5
    NETWORKLAYER  = LAYERNAMES.index('roads')*11+5
    DRAPEDLAYER   = LAYERNAMES.index('objects')*11	# objects -5 for draped geometry
    OBJECTLAYER   = LAYERNAMES.index('objects')*11+5
    LAYERCOUNT      = len(LAYERNAMES)*11		# assignable X-Plane layers
    OUTLINELAYER    = LAYERCOUNT			# for polygons
    GEOMCULLEDLAYER = LAYERCOUNT+1			# for non-draped dynamic geometry (i.e. Facades)
    GEOMNOCULLLAYER = LAYERCOUNT+2			# for non-draped dynamic geometry (i.e. Facades)
    IMAGERYLAYER    = LAYERCOUNT+3			# for background imagery (actually drawn earlier)
    DRAWLAYERCOUNT  = LAYERCOUNT+4			# including stuff lifted out of the X-Plane layers

    PREVIEWSIZE=400	# size of image in preview window

    @staticmethod
    def factory(filename, vertexcache, lookup, defs):
        "creates and initialises appropriate PolgonDef subclass based on file extension"
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
        elif ext==PolygonDef.STRING:
            return StringDef(filename, vertexcache, lookup, defs)
        elif ext in SkipDefs:
            assert False, filename
            raise IOError		# what's this doing here?
        else:	# unknown polygon type
            return PolygonDef(filename, vertexcache, lookup, defs)

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
        self.layer=ClutterDef.OUTLINELAYER
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

    def draw_instanced(self, glstate, selected):
        pass

    def pick_instanced(self, glstate, proj, selections, lookup):
        pass

    # Normalise path, replacing : / and \ with os-specific separator, eliminating .. etc
    def cleanpath(self, path):
        # relies on normpath on win replacing '/' with '\\'
        return normpath(join(self.texpath, path.decode('latin1').replace(':', sep).replace('\\', sep)))


class ObjectDef(ClutterDef):

    OBJECT='.obj'
    
    def __init__(self, filename, vertexcache, lookup, defs, make_editable=True):
        ClutterDef.__init__(self, filename, vertexcache, lookup, defs)
        self.layer=ClutterDef.OBJECTLAYER
        self.canpreview=True
        self.type=Locked.OBJ
        self.vdata=None
        self.poly=0
        self.bbox=BBox()
        self.height=1.0		# musn't be 0
        self.radius=1.0
        self.base=None
        self.draped=[]
        self.texture_draped=0
        # For instancing
        self.instances=set()	# Objects in current tile
        self.transform_valid=False
        self.transform_vbo=vbo.VBO(None, GL_DYNAMIC_DRAW)

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
            # Note: using numpy arrays to construct vt and idx would be ~50% slower!
            vt=[]
            idx=[]
            anim=[]
            done_anim_t=False
            done_anim_r=False
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
                        self.layer=ClutterDef.DRAPEDLAYER
                elif id=='ATTR_LOD':
                    if float(c[1])!=0: break
                    current=last=culled	# State is reset per LOD
                elif id=='ATTR_poly_os':
                    self.poly=max(self.poly,int(float(c[1])))
                    if float(c[1]):
                        if current is not draped: last = current
                        current=draped
                    else:
                        current=last
                elif id=='ATTR_cull':
                    if current is draped:
                        last=culled
                    else:
                        current=culled
                elif id=='ATTR_no_cull':
                    if current is draped:
                        last=nocull
                    else:
                        current=nocull
                elif id=='ATTR_draped':
                    self.poly = 0	# SketchUp outputs poly_os 2 before draped for backwards compatibility
                    if current is not draped: last = current
                    current=draped
                elif id=='ATTR_no_draped':
                    current=last
                elif id in ['ATTR_layer_group', 'ATTR_layer_group_draped']:
                    # FIXME: Should have different layers for static and dynamic content
                    self.setlayer(c[1], int(c[2]))
                elif id=='ANIM_begin':
                    if anim:
                        anim.append(copy(anim[-1]))
                    else:
                        anim=[identity(4)]
                    done_anim_t=False
                    done_anim_r=False
                elif id=='ANIM_end':
                    anim.pop()
                elif id=='ANIM_trans':
                    t=identity(4)
                    t[3,:3] = [float(c[i]) for i in range(1,4)]
                    anim[-1]=dot(t,anim[-1])
                    done_anim_t=True
                elif id=='ANIM_trans_key':
                    if not done_anim_t:
                        t=identity(4)
                        t[3,:3] = [float(c[i]) for i in range(2,5)]
                        anim[-1]=dot(t,anim[-1])
                    done_anim_t=True
                elif id=='ANIM_rotate_begin':
                    anim_axis = [float(c[i]) for i in range(1,4)]
                elif id in ['ANIM_rotate', 'ANIM_rotate_key']:
                    if id=='ANIM_rotate':
                        angle=radians(float(c[4]))
                        anim_axis = [float(c[i]) for i in range(1,4)]
                    else:
                        angle=radians(float(c[2]))
                    if angle and not done_anim_r:
                        sina = sin(angle)
                        cosa = cos(angle)
                        d = array(anim_axis, float32)
                        r = diag([cosa, cosa, cosa]) + outer(d,d)*(1.0-cosa)
                        d *= sina
                        r += array([[  0.0,  d[2], -d[1]],
                                    [-d[2],  0.0,   d[0]],
                                    [ d[1], -d[0],  0.0]], float32)
                        m = identity(4, float32)
                        m[:3,:3] = r
                        anim[-1] = dot(m,anim[-1])
                    done_anim_r=True
                elif id=='TRIS':
                    start=int(c[1])
                    new=int(c[2])
                    if anim:
                        if array_equal(anim[-1][:3,:3], identity(3)):
                            # Special case for translation only
                            off=list(anim[-1][3])	# translation vector
                            current.extend([[vt[idx[i]][j]+off[j] for j in range (3)] + vt[idx[i]][3:] for i in range(start, start+new)])
                        else:
                            # This is slow!
                            v=dot([vt[idx[i]][:3]+[1.0] for i in range(start, start+new)], anim[-1])
                            current.extend([list(v[i])[:3] + vt[idx[start+i]][3:] for i in range(new)])
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
            self.culled=len(culled)
            self.nocull=len(nocull)
            if self.culled+self.nocull:	# can be empty in draped-only objects
                self.vdata=array(culled+nocull, float32).flatten()
            if texture_draped:	# can be None
                try:
                    self.texture_draped=vertexcache.texcache.get(texture_draped)
                except EnvironmentError, e:
                    self.texerr=(texture_draped, unicode(e.strerror or e.message))
                except:
                    self.texerr=(texture_draped, unicode(exc_info()[1]))
            if texture:	# can be None
                try:
                    self.texture=vertexcache.texcache.get(texture)
                except EnvironmentError, e:
                    self.texerr=(texture, unicode(e.strerror or e.message))
                except:
                    self.texerr=(texture, unicode(exc_info()[1]))
                if draped and not texture_draped:
                    self.texture_draped=self.texture
            self.draped=draped
            self.radius = max(self.bbox.maxx, -self.bbox.minx, self.bbox.maxz, -self.bbox.minz) * 2	# clip radius

    def allocate(self, vertexcache):
        if self.base==None and self.vdata is not None:
            self.base=vertexcache.allocate_instance(self.vdata)

    def flush(self):
        self.base=None

    def draw_instanced(self, glstate, selected):
        if self.vdata is None or not self.instances:
            #if __debug__: print "No data for instancing %s" % self
            return

        if not self.transform_valid:
            if __debug__:
                for o in self.instances: assert o.matrix is not None, "Empty matrix %s" % o
            if glstate.instanced_arrays:
                self.transform_vbo.set_array(concatenate([o.matrix for o in self.instances]))
            else:
                self.transform_vbo = vstack([o.matrix for o in self.instances])	# not actually a VBO
                self.transform_vbo[:,3] = 1		# drop rotation and make homogenous
            self.transform_valid = True

        glstate.set_texture(self.texture)
        if glstate.instanced_arrays:
            if selected:
                glstate.set_attrib_selected(glstate.instanced_selected_pos, array([o in selected for o in self.instances],float32))
            self.transform_vbo.bind()
            glVertexAttribPointer(glstate.instanced_transform_pos, 4, GL_FLOAT, GL_FALSE, 16, self.transform_vbo)
            if self.culled:
                glstate.set_cull(True)
                glDrawArraysInstanced(GL_TRIANGLES, self.base, self.culled, len(self.instances))
            if self.nocull:
                glstate.set_cull(False)
                glDrawArraysInstanced(GL_TRIANGLES, self.base+self.culled, self.nocull, len(self.instances))
        else:
            pos = glstate.transform_pos
            projected = numpy.abs(dot(self.transform_vbo, glstate.proj)[:,:2])	# |x|,|y| in NDC space
            clip = 1 + numpy.max(numpy.abs(dot(array([[self.radius, 0, self.radius, 0], [self.radius, self.height, self.radius, 0]]), glstate.proj)[:,:2]))	# add largest dimension of bounding cylinder in NDC space
            instances = set([item for (item,inview) in zip(self.instances, numpy.all(projected <= clip, axis=1)) if inview])	# filter to those in view
            selected = instances.intersection(selected)	# subset of selected that are instances of this def
            unselected = instances.difference(selected)
            if unselected:
                glstate.set_color(COL_UNPAINTED)
                for obj in unselected:
                    glUniform4f(pos, *obj.matrix)
                    if self.culled:
                        glstate.set_cull(True)
                        glDrawArrays(GL_TRIANGLES, self.base, self.culled)
                    if self.nocull:
                        glstate.set_cull(False)
                        glDrawArrays(GL_TRIANGLES, self.base+self.culled, self.nocull)
            if selected:
                glstate.set_color(COL_SELECTED)
                glstate.set_cull(False)		# draw rear side of "invisible" faces when selected
                for obj in selected:
                    glUniform4f(pos, *obj.matrix)
                    glDrawArrays(GL_TRIANGLES, self.base, self.culled+self.nocull)

    def pick_instanced(self, glstate, proj, selections, lookup):
        if not self.instances:
            return

        if not self.transform_valid:	# won't be valid for AGPs since they are not drawn instanced
            if __debug__:
                for o in self.instances: assert o.matrix is not None, "Empty matrix %s" % o
            if glstate.instanced_arrays:
                self.transform_vbo.set_array(concatenate([o.matrix for o in self.instances]))
            else:
                self.transform_vbo = vstack([o.matrix for o in self.instances])	# not actually a VBO
                self.transform_vbo[:,3] = 1		# drop rotation and make homogenous
            self.transform_valid = True

        if glstate.instanced_arrays:
            transform = array(self.transform_vbo.data, copy=True).reshape((-1,4))
            transform[:,3] = 1		# drop rotation and make homogenous
        else:
            transform = self.transform_vbo
        projected = numpy.abs(dot(transform, proj)[:,:2])	# |x|,|y| in NDC space

        # add those with centre in view directly to selections cos we don't need to query them,
        # and in case we're so zoomed out that drawing the object wouldn't produce any fragments
        selections.update([item for (item,inview) in zip(self.instances, numpy.all(projected <= 1, axis=1)) if inview])

        if self.vdata is None: return	# don't have to do anything else for AGPs

	# query those with bounding cylinder in view (but not those with centre in view)
        pos = glstate.transform_pos
        clip = 1 + numpy.max(numpy.abs(dot(array([[self.radius, 0, self.radius, 0], [self.radius, self.height, self.radius, 0]]), proj)[:,:2]))	# add largest dimension of bounding cylinder in NDC space
        instances = [item for (item,inview) in zip(self.instances, logical_and(numpy.all(projected <= clip, axis=1), numpy.any(projected > 1, axis=1))) if inview]

        queryidx = len(lookup)
        lookup.extend(instances)
        if glstate.occlusion_query:
            for obj in instances:
                glBeginQuery(glstate.occlusion_query, glstate.queries[queryidx])
                glUniform4f(pos, *obj.matrix)
                glDrawArrays(GL_TRIANGLES, self.base, self.culled+self.nocull)
                glEndQuery(glstate.occlusion_query)
                queryidx += 1
        else:
            for obj in instances:
                glLoadName(queryidx)
                glUniform4f(pos, *obj.matrix)
                glDrawArrays(GL_TRIANGLES, self.base, self.culled+self.nocull)
                queryidx += 1

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
        glLoadIdentity()
        sizex=(self.bbox.maxx-self.bbox.minx)*0.5
        sizez=(self.bbox.maxz-self.bbox.minz)*0.5
        maxsize=max(self.height*0.7,		# height
                    sizez*0.88  + sizex*0.51,	# width at 30degrees
                    sizez*0.255 + sizex*0.44)	# depth at 30degrees / 2
        glOrtho(-maxsize, maxsize, -maxsize/2, maxsize*1.5, -2*maxsize, 2*maxsize)
        glRotatef( 30, 1,0,0)
        glRotatef(120, 0,1,0)

        canvas.glstate.set_color(COL_UNPAINTED)
        canvas.glstate.set_depthtest(False)
        canvas.glstate.set_cull(True)
        if self.draped:
            canvas.glstate.set_texture(self.texture_draped)
            glUniform4f(canvas.glstate.transform_pos, sizex-self.bbox.maxx, 0, sizez-self.bbox.maxz, 0)
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
                glUniform4f(canvas.glstate.transform_pos, p[2] + sizex-self.bbox.maxx, 0, p[3] + sizez-self.bbox.maxz, radians(p[4]))
                glBegin(GL_TRIANGLES)
                for i in range(0,len(child.draped),3):
                    for j in range(3):
                        v=child.draped[i+j]
                        glTexCoord2f(v[3],v[4])
                        glVertex3f(v[0],v[1],v[2])
                glEnd()

        canvas.glstate.set_texture(None)
        canvas.glstate.set_color(COL_CURSOR)
        glBegin(GL_POINTS)
        glVertex3f(sizex-self.bbox.maxx, 0, sizez-self.bbox.maxz)
        glEnd()

        canvas.glstate.set_color(COL_UNPAINTED)
        canvas.glstate.set_depthtest(True)
        canvas.glstate.set_poly(False)
        if self.vdata is not None:
            canvas.glstate.set_texture(self.texture)
            glUniform4f(canvas.glstate.transform_pos, sizex-self.bbox.maxx, 0, sizez-self.bbox.maxz, 0)
            if self.culled:
                glDrawArrays(GL_TRIANGLES, self.base, self.culled)
            if self.nocull:
                canvas.glstate.set_cull(False)
                glDrawArrays(GL_TRIANGLES, self.base+self.culled, self.nocull)
        for p in children:
            child=p[1]
            if child.vdata is not None:
                canvas.glstate.set_texture(child.texture)
                glUniform4f(canvas.glstate.transform_pos, p[2] + sizex-self.bbox.maxx, 0, p[3] + sizez-self.bbox.maxz, radians(p[4]))
                if child.culled:
                    canvas.glstate.set_cull(True)
                    glDrawArrays(GL_TRIANGLES, child.base, child.culled)
                if child.nocull:
                    canvas.glstate.set_cull(False)
                    glDrawArrays(GL_TRIANGLES, child.base+child.culled, child.nocull)
        data=glReadPixels(xoff,0, ClutterDef.PREVIEWSIZE,ClutterDef.PREVIEWSIZE, GL_RGB, GL_UNSIGNED_BYTE)
        img=wx.EmptyImage(ClutterDef.PREVIEWSIZE, ClutterDef.PREVIEWSIZE, False)
        img.SetData(data)
        
        glLoadMatrixd(canvas.glstate.proj)	# Restore state for unproject
        glClearColor(0.5, 0.5, 1.0, 0.0)	# Sky
        glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT)
        canvas.Refresh()	# Mac draws from the back buffer w/out paint event
        return img.Mirror(False)
        

class ObjectFallback(ObjectDef):

    def __init__(self, filename, vertexcache, lookup, defs):
        ClutterDef.__init__(self, filename, vertexcache, lookup, defs)
        self.layer=ClutterDef.OBJECTLAYER
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
        self.culled = len(self.vdata)/5
        self.nocull=0
        self.poly=0
        self.bbox=BBox(-0.5,0.5,-0.5,0.5)
        self.height=1.0
        self.radius=1.0
        self.base=None
        self.draped=[]
        self.texture_draped=0
        # For instancing
        self.instances=set()	# Objects in current tile
        self.transform_valid=False
        self.transform_vbo=vbo.VBO(None, GL_DYNAMIC_DRAW)


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
        # For instancing
        self.instances=set()		# Objects in current tile
        self.transform_valid=False
        self.transform_vbo=vbo.VBO(None, GL_DYNAMIC_DRAW)

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
        # TODO: OBJ_GRADED, OBJ_SCRAPER, OBJ_DELTA, GROUND_PT
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
                    self.texerr=(texture_draped, unicode(e.strerror or e.message))
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
                    gc.disable()	# work round http://bugs.python.org/issue4074 on Python<2.7
                    defs[childfilename]=definition=ObjectDef(childfilename, vertexcache, lookup, defs, make_editable=False)
                    gc.enable()
                except:
                    gc.enable()
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

    def draw_instanced(self, glstate, selected):
        assert self.vdata is None	# we're just a container


class AutoGenFallback(ObjectFallback):

    def __init__(self, filename, vertexcache, lookup, defs):
        ObjectFallback.__init__(self, filename, vertexcache, lookup, defs)
        self.children=[]


class PolygonDef(ClutterDef):

    EXCLUDE='Exclude: '
    FACADE='.fac'
    FOREST='.for'
    LINE='.lin'
    STRING='.str'
    DRAPED='.pol'
    BEACH='.bch'

    def __init__(self, filename, vertexcache, lookup, defs):
        ClutterDef.__init__(self, filename, vertexcache, lookup, defs)
        self.layer=ClutterDef.OUTLINELAYER
        self.fittomesh=True	# nodes laid out at mesh elevation
        self.type=Locked.UNKNOWN

    def preview(self, canvas, vertexcache, l=0, b=0, r=1, t=1, hscale=1):
        if not self.texture or not self.canpreview: return None
        glViewport(0, 0, ClutterDef.PREVIEWSIZE, ClutterDef.PREVIEWSIZE)
        glClearColor(0.3, 0.5, 0.6, 1.0)	# Preview colour
        glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT)
        glLoadIdentity()
        canvas.glstate.set_color(COL_WHITE)
        canvas.glstate.set_texture(self.texture)
        glUniform4f(canvas.glstate.transform_pos, *zeros(4,float32))
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
        
        glLoadMatrixd(canvas.glstate.proj)	# Restore state for unproject
        glClearColor(0.5, 0.5, 1.0, 0.0)	# Sky
        glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT)
        canvas.Refresh()	# Mac draws from the back buffer w/out paint event
        return img


class DrapedDef(PolygonDef):

    def __init__(self, filename, vertexcache, lookup, defs):
        PolygonDef.__init__(self, filename, vertexcache, lookup, defs)
        self.layer=ClutterDef.DRAPEDLAYER
        self.canpreview=True
        self.type=Locked.POL
        self.ortho=False
        self.hscale=None
        self.vscale=None
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
        if not (self.hscale and self.vscale): raise IOError	# Required even for orthos
        try:
            self.texture=vertexcache.texcache.get(texture, not self.ortho, alpha)
        except EnvironmentError, e:
            self.texerr=(texture, unicode(e.strerror or e.message))
        except:
            self.texerr=(texture, unicode(exc_info()[1]))


class DrapedFallback(DrapedDef):

    def __init__(self, filename, vertexcache, lookup, defs):
        PolygonDef.__init__(self, filename, vertexcache, lookup, defs)
        self.layer=ClutterDef.DRAPEDLAYER
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
        self.layer=ClutterDef.DRAPEDLAYER
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
                    self.texerr=(texture, unicode(e.strerror or e.message))
                except:
                    self.texerr=(texture, unicode(exc_info()[1]))
            elif id=='RING':
                self.ring=int(c[1])
            elif id in ['TWO_SIDED', 'DOUBLED']:
                self.two_sided=(int(c[1])!=0)
            elif id=='GRADED':
                self.fittomesh=False
            elif id=='ATTR_layer_group_draped':
                self.setlayer(c[1], int(c[2]))

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
            # TODO: ROOF_OBJ
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
                        gc.disable()	# work round http://bugs.python.org/issue4074 on Python<2.7
                        defs[childfilename]=definition=ObjectDef(childfilename, vertexcache, lookup, defs, make_editable=False)
                        gc.enable()
                    except:
                        gc.enable()
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
                floor.roofs.sort()				# draw roofs in ascending height due to poly_os on height 0
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
        glLoadIdentity()
        glOrtho(-pad, maxsize-pad, 0, maxsize, -maxsize, maxsize)
        glRotatef(-90, 0,1,0)
        canvas.glstate.set_color(COL_UNPAINTED)
        canvas.glstate.set_depthtest(True)
        canvas.glstate.set_poly(False)
        canvas.glstate.set_cull(True)
        canvas.glstate.set_texture(self.texture)
        glUniform4f(canvas.glstate.transform_pos, *zeros(4,float32))
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
                    glUniform4f(canvas.glstate.transform_pos, xdelta, ydelta, hoffset+zdelta, radians(hdelta))
                    if definition.culled:
                        canvas.glstate.set_cull(True)
                        glDrawArrays(GL_TRIANGLES, definition.base, definition.culled)
                    if definition.nocull:
                        canvas.glstate.set_cull(False)
                        glDrawArrays(GL_TRIANGLES, definition.base+definition.culled, definition.nocull)
            hoffset-=segment.width
        data=glReadPixels(xoff,0, ClutterDef.PREVIEWSIZE,ClutterDef.PREVIEWSIZE, GL_RGB, GL_UNSIGNED_BYTE)
        img=wx.EmptyImage(ClutterDef.PREVIEWSIZE, ClutterDef.PREVIEWSIZE, False)
        img.SetData(data)

        glLoadMatrixd(canvas.glstate.proj)	# Restore state for unproject
        glClearColor(0.5, 0.5, 1.0, 0.0)	# Sky
        glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT)
        canvas.Refresh()	# Mac draws from the back buffer w/out paint event
        return img.Mirror(False)


class FacadeFallback(FacadeDef):

    def __init__(self, filename, vertexcache, lookup, defs):
        PolygonDef.__init__(self, filename, vertexcache, lookup, defs)
        self.layer=ClutterDef.OUTLINELAYER
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
                    self.texerr=(texture, unicode(e.strerror or e.message))
                except:
                    self.texerr=(texture, unicode(exc_info()[1]))
            elif id=='SCALE_X':
                scalex=float(c[1])
            elif id=='SCALE_Y':
                scaley=float(c[1])
            elif id=='TREE':
                freq = float(c[6].replace(',','.'))	# workaround for error in e.g. v10 sparse_vhot_dry.for
                if len(c)>10 and freq>best and float(c[3])/scalex>.02 and float(c[4])/scaley>.02:
                    # choose most popular, unless it's tiny (placeholder)
                    best = freq
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

    class Segment:
        def __init__(self, texture, t_ratio, x_left, y1, s_left, x_right, y2, s_right):
            self.texture = texture
            self.t_ratio = t_ratio
            self.x_left  = x_left
            self.y1      = y1
            self.s_left  = s_left
            self.x_right = x_right
            self.y2      = y2
            self.s_right = s_right

    def __init__(self, filename, vertexcache, lookup, defs):
        PolygonDef.__init__(self, filename, vertexcache, lookup, defs)
        self.layer=ClutterDef.DRAPEDLAYER
        self.canpreview=True
        self.width=0
        self.length=0
        self.segments=[]	# [Segment]
        self.color = None
        self.even = False
        hscale = 0
        width = 1
        texno = 0
        offsets = []
        
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
                    texno=vertexcache.texcache.get(texture)
                except EnvironmentError, e:
                    self.texerr=(texture, unicode(e.strerror or e.message))
                except:
                    self.texerr=(texture, unicode(exc_info()[1]))
            elif id=='SCALE':
                hscale = float(c[1])
                self.length = float(c[2])
            elif id=='TEX_WIDTH':
                width=float(c[1])
            elif id=='S_OFFSET':
                offsets.append((int(c[1]), float(c[2]), float(c[3]), float(c[4])))
            elif id=='LAYER_GROUP':
                self.setlayer(c[1], int(c[2]))
        h.close()
        if not offsets or not self.length: raise IOError	# Empty
        offsets.sort(key=lambda x: x[0])	# display in layer order
        for (layer, s1, sm, s2) in offsets:
            self.segments.append(LineDef.Segment(texno, 1, hscale*(s1-sm)/width, 0, s1/width, hscale*(s2-sm)/width, 0, s2/width))
            self.width=max(self.width, -self.segments[-1].x_left, self.segments[-1].x_right)	# semi-width
        self.width *= 2
                
    def preview(self, canvas, vertexcache):
        if not self.canpreview: return None
        self.allocate(vertexcache)
        glViewport(0, 0, ClutterDef.PREVIEWSIZE, ClutterDef.PREVIEWSIZE)
        glClearColor(0.3, 0.5, 0.6, 1.0)	# Preview colour
        glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT)
        glLoadIdentity()
        canvas.glstate.set_color(COL_WHITE)
        canvas.glstate.set_poly(True)
        # canvas.glstate.set_cull(True)	# don't care
        if self.even:
            scale = 2.0 / (self.length * self.even)
        else:
            scale = 2.0 / self.length
        for segment in self.segments:
            canvas.glstate.set_texture(segment.texture)
            glUniform4f(canvas.glstate.transform_pos, *zeros(4,float32))
            glBegin(GL_QUADS)
            glTexCoord2f(segment.s_left, segment.t_ratio)
            glVertex3f(segment.x_left*scale,  -self.length*scale*0.5, segment.y1)
            glTexCoord2f(segment.s_left, 0)
            glVertex3f(segment.x_left*scale,   self.length*scale*0.5, segment.y1)
            glTexCoord2f(segment.s_right, 0)
            glVertex3f(segment.x_right*scale,  self.length*scale*0.5, segment.y2)
            glTexCoord2f(segment.s_right, segment.t_ratio)
            glVertex3f(segment.x_right*scale, -self.length*scale*0.5, segment.y2)
            glEnd()
        data=glReadPixels(0,0, ClutterDef.PREVIEWSIZE,ClutterDef.PREVIEWSIZE, GL_RGB, GL_UNSIGNED_BYTE)
        img=wx.EmptyImage(ClutterDef.PREVIEWSIZE, ClutterDef.PREVIEWSIZE, False)
        img.SetData(data)

        glLoadMatrixd(canvas.glstate.proj)	# Restore state for unproject
        glClearColor(0.5, 0.5, 1.0, 0.0)	# Sky
        glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT)
        canvas.Refresh()	# Mac draws from the back buffer w/out paint event
        return img
        

class LineFallback(LineDef):

    def __init__(self, filename, vertexcache, lookup, defs):
        PolygonDef.__init__(self, filename, vertexcache, lookup, defs)
        self.layer=ClutterDef.DRAPEDLAYER
        self.width=1
        self.length=8.0
        self.segments=[LineDef.Segment(vertexcache.texcache.get(fallbacktexture), 8.0, -0.5, 0, 0, 0.5, 0, 1)]
        self.color = None
        self.even = 0.125


class StringDef(PolygonDef):

    class StringObj:
        def __init__(self, name, definition, xdelta, hdelta):
            self.name=name
            self.definition=definition
            self.xdelta=xdelta
            self.hdelta=hdelta

    def __init__(self, filename, vertexcache, lookup, defs):
        PolygonDef.__init__(self, filename, vertexcache, lookup, defs)
        self.canpreview=True
        self.color = COL_POLYGON
        self.children=[]	# [StringObj]
        self.alternate=True	# Whether to cycle through children (Strings) or superimpose (Networks)

        offset = 0
        children = []
        h=open(self.filename, 'rU')
        if not h.readline().strip()[0] in ['I','A']:
            raise IOError
        if not h.readline().split('#')[0].strip() in ['850']:
            raise IOError
        if not h.readline().strip() in ['OBJECT_STRING']:
            raise IOError
        for line in h:
            c=line.split()
            if not c: continue
            id=c[0]
            if id=='OFFSET':
                offset = float(c[1])
            elif id=='OBJECT':
                childname=c[3][:-4].replace(':', '/').replace('\\','/')+c[3][-4:].lower()
                if childname in lookup:
                    childfilename=lookup[childname].file
                else:
                    childfilename=join(dirname(filename),childname)	# names are relative to this .str so may not be in global lookup
                if childfilename in defs:
                    definition=defs[childfilename]
                else:
                    try:
                        gc.disable()	# work round http://bugs.python.org/issue4074 on Python<2.7
                        defs[childfilename]=definition=ObjectDef(childfilename, vertexcache, lookup, defs, make_editable=False)
                        gc.enable()
                    except:
                        gc.enable()
                        if __debug__: print_exc()
                        self.canpreview=False	# e.g. for lib/airport/lights/fast/*.str
                        defs[childfilename]=definition=ObjectFallback(childfilename, vertexcache, lookup, defs)
                children.append((childname, definition, (float(c[1])+float(c[2]))/2))
        h.close()
        if not children: raise IOError	# Empty!
        for (childname,definition,hdelta) in children:
            self.children.append(StringDef.StringObj(childname, definition, offset, hdelta))	# offset can be defined after objects

    def allocate(self, vertexcache):
        for p in self.children:
            p.definition.allocate(vertexcache)

    def preview(self, canvas, vertexcache):
        if not self.canpreview: return None
        self.allocate(vertexcache)
        canvas.glstate.set_instance(vertexcache)
        glViewport(0, 0, ClutterDef.PREVIEWSIZE, ClutterDef.PREVIEWSIZE)
        glClearColor(0.3, 0.5, 0.6, 1.0)	# Preview colour
        glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT)
        glLoadIdentity()
        defn = self.children[0].definition	# Hack - just use first child for sizing
        sizex=(defn.bbox.maxx-defn.bbox.minx)*0.5
        sizez=(defn.bbox.maxz-defn.bbox.minz)*0.5
        maxsize=max(defn.height*0.7,		# height
                    sizez*0.88  + sizex*0.51,	# width at 30degrees
                    sizez*0.255 + sizex*0.44)	# depth at 30degrees / 2
        glOrtho(-maxsize, maxsize, -maxsize/2, maxsize*1.5, -2*maxsize, 2*maxsize)
        glRotatef( 30, 1,0,0)
        glRotatef(120, 0,1,0)

        canvas.glstate.set_color(COL_UNPAINTED)
        canvas.glstate.set_depthtest(False)
        canvas.glstate.set_cull(True)
        for p in self.children:
            child = p.definition
            if child.draped:
                canvas.glstate.set_texture(child.texture_draped)
                glUniform4f(canvas.glstate.transform_pos, sizex-defn.bbox.maxx, 0, sizez-defn.bbox.maxz, radians(p.hdelta))
                glBegin(GL_TRIANGLES)
                for i in range(0,len(child.draped),3):
                    for j in range(3):
                        v=child.draped[i+j]
                        glTexCoord2f(v[3],v[4])
                        glVertex3f(v[0],v[1],v[2])
                glEnd()

        canvas.glstate.set_depthtest(True)
        canvas.glstate.set_poly(False)
        for p in self.children:
            child = p.definition
            if child.vdata is not None:
                canvas.glstate.set_texture(child.texture)
                glUniform4f(canvas.glstate.transform_pos, sizex-defn.bbox.maxx, 0, sizez-defn.bbox.maxz, radians(p.hdelta))
                if child.culled:
                    glDrawArrays(GL_TRIANGLES, child.base, child.culled)
                if child.nocull:
                    canvas.glstate.set_cull(False)
                    glDrawArrays(GL_TRIANGLES, child.base+child.culled, child.nocull)
            if self.alternate: break	# just do the first one

        data=glReadPixels(0,0, ClutterDef.PREVIEWSIZE,ClutterDef.PREVIEWSIZE, GL_RGB, GL_UNSIGNED_BYTE)
        img=wx.EmptyImage(ClutterDef.PREVIEWSIZE, ClutterDef.PREVIEWSIZE, False)
        img.SetData(data)

        glLoadMatrixd(canvas.glstate.proj)	# Restore state for unproject
        glClearColor(0.5, 0.5, 1.0, 0.0)	# Sky
        glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT)
        canvas.Refresh()	# Mac draws from the back buffer w/out paint event
        return img.Mirror(False)

class StringFallback(StringDef):

    OBJ='*stringfallback.obj'

    def __init__(self, filename, vertexcache, lookup, defs):
        PolygonDef.__init__(self, filename, vertexcache, lookup, defs)
        if StringFallback.OBJ in defs:
            fb = defs[StringFallback.OBJ]
        else:
            fb = defs[StringFallback.OBJ] = ObjectFallback(StringFallback.OBJ, vertexcache, lookup, defs)
        self.color = COL_NONSIMPLE
        self.children = [StringDef.StringObj(StringFallback.OBJ, fb, 0, 0)]
        self.alternate = True


class NetworkDef(StringDef,LineDef):

    TABNAME='Roads, Railways & Powerlines'
    NETWORK='.net'
    DEFAULTFILE='lib/g10/roads.net'

    def __init__(self, netdef, vertexcache, lookup, defs):
        PolygonDef.__init__(self, netdef.name, vertexcache, lookup, defs)
        self.layer = ClutterDef.NETWORKLAYER
        self.canpreview = True
        self.type = Locked.NET
        self.type_id = netdef.type_id
        self.width = netdef.width
        self.length = netdef.length
        self.color = netdef.color
        self.even = False
        self.alternate = False
        self.children = []	# [StringDef.StringObj]
        self.segments = []	# [LineDef.Segment]

        center = self.width/2
        scale = 1
        lines=[]		# [(shader#, tex_filename, t_ratio, lateral, vertical, s, lateral, vertical, s)]
        h=open(netdef.filename, 'rU')
        h.seek(netdef.offset)
        for line in h:
            c=line.split()
            if not c: continue
            id=c[0]
            if id=='ROAD_CENTER':
                center = float(c[1])
            elif id=='SCALE':
                scale=float(c[1])
            elif id=='REQUIRE_EVEN':
                self.even = len(c)>=2 and float(c[1]) or 1.0
            elif id=='SEGMENT_DRAPED':	# texno lod_lo lod_hi t_ratio x_left    u_left x_right    u_right [surface]
                if not float(c[2]):	# 0 LOD
                    lines.append((int(c[1]), netdef.texs[int(c[1])], round(float(c[4]),4), round(float(c[5])-center,4), 0, float(c[6])/scale, round(float(c[7])-center,4), 0, float(c[8])/scale))
            elif id=='SEGMENT_GRADED':	# texno lod_lo lod_hi t_ratio x_left y1 u_left x_right y2 u_right [surface]
                if not float(c[2]):	# 0 LOD
                    lines.append((int(c[1]), netdef.texs[int(c[1])], round(float(c[4]),4), round(float(c[5])-center,4), round(float(c[6]),4), float(c[7])/scale, round(float(c[8])-center,4), round(float(c[9]),4), float(c[10])/scale))
            elif id=='OBJECT_GRADED':	# mode lat_offset? lat_offset? rot rot repeat_len repeat_len offsets?
                if c[1]=='VERT':	# only support this mode
                    assert float(c[7]) == float(c[8]) == self.length, self.name	# only handle repeat == length
                    childname = c[2]
                    if childname in lookup:
                        childfilename = lookup[childname].file
                    else:
                        childfilename = join(dirname(netdef.filename),childname)	# names are relative to this .net so may not be in global lookup
                    if childfilename in defs:
                        definition = defs[childfilename]
                    else:
                        try:
                            defs[childfilename] = definition = ObjectDef(childfilename, vertexcache, lookup, defs, make_editable=False)
                        except:
                            if __debug__: print_exc()
                            defs[childfilename] = definition = ObjectFallback(childfilename, vertexcache, lookup, defs)
                    self.children.append(StringDef.StringObj(childname[:-4], definition, round((float(c[3])+float(c[4]))/2-center,4), (float(c[5])+float(c[6]))/2))
            elif id in ['ROAD_TYPE', 'JUNC_SHADER']:
                break
        h.close()

        lines.sort(key=lambda x: x[0])	# display in shader# order
        for (shader, texname, t2, lat1, vert1, s1, lat2, vert2, s2) in lines:
            texture = 0
            try:
                texture = vertexcache.texcache.get(texname)
            except EnvironmentError, e:
                if __debug__: print_exc()
                self.texerr=(texname, unicode(e.strerror or e.message))
            except:
                if __debug__: print_exc()
                self.texerr=(texname, unicode(exc_info()[1]))
            self.segments.append(LineDef.Segment(texture, t2, lat1, vert1, s1, lat2, vert2, s2))

    def allocate(self, vertexcache):
        StringDef.allocate(self, vertexcache)	# Don't have anything ourselves

    def preview(self, canvas, vertexcache):
        if not self.canpreview:
            return None
        elif self.segments:
            return LineDef.preview(self, canvas, vertexcache)
        elif self.children:
            return StringDef.preview(self, canvas, vertexcache)
        else:
            return None

class NetworkFallback(NetworkDef):

    def __init__(self, name, vertexcache, lookup, defs):
        PolygonDef.__init__(self, name, vertexcache, lookup, defs)
        self.layer = ClutterDef.NETWORKLAYER
        self.canpreview = False
        self.type = Locked.NET
        self.type_id = name
        self.width = 16.0
        self.length = 128.0
        self.color = COL_NONSIMPLE
        self.even = self.width/self.length
        self.alternate = False
        self.children = []
        self.segments = [LineDef.Segment(vertexcache.texcache.get(fallbacktexture), self.length, -self.width/2, 0, 0, self.width/2, 0, 1)]


UnknownDefs=['.agb','.ags']	# Known unknowns
SkipDefs = ['.bch','.net','.dcl','.voc']	# Ignore in library
KnownDefs=[ObjectDef.OBJECT, AutoGenPointDef.AGP, PolygonDef.FACADE, PolygonDef.FOREST, PolygonDef.LINE, PolygonDef.STRING, PolygonDef.DRAPED]+UnknownDefs
