import PIL.Image
import PIL.BmpImagePlugin, PIL.JpegImagePlugin, PIL.PngImagePlugin, PIL.TiffImagePlugin 	# force for py2exe

import OpenGL	# for __version__
from OpenGL.GL import *
from OpenGL.GL.EXT.bgra import glInitBgraEXT, GL_BGR_EXT, GL_BGRA_EXT
from OpenGL.GL.ARB.texture_compression import glInitTextureCompressionARB, glCompressedTexImage2DARB
from OpenGL.GL.EXT.texture_compression_s3tc import glInitTextureCompressionS3TcEXT, GL_COMPRESSED_RGB_S3TC_DXT1_EXT, GL_COMPRESSED_RGBA_S3TC_DXT1_EXT, GL_COMPRESSED_RGBA_S3TC_DXT3_EXT, GL_COMPRESSED_RGBA_S3TC_DXT5_EXT
from OpenGL.GL.ARB.texture_non_power_of_two import glInitTextureNonPowerOfTwoARB

import codecs
import gc
from glob import glob
from math import cos, log, pi, radians
from numpy import array, arange, concatenate, empty, ndarray, repeat, float32, uint8, uint16, uint32
from os import listdir, mkdir
from os.path import basename, dirname, exists, join, normpath, pardir, splitext
from struct import unpack
from sys import exc_info, platform, maxint
from traceback import print_exc
import time
import wx

from buckets import Buckets
from clutter import Clutter
from clutterdef import BBox, SkipDefs, NetworkDef
from DSFLib import readDSF
from elevation import ElevationMesh, DummyElevationMesh, onedeg
from palette import PaletteEntry
from prefs import Prefs, prefs, gnavdata
from version import appname, appversion

downsamplemin=64	# Don't downsample textures this size or smalller
compressmin=64		# Don't bother compressing or generating mipmaps for textures this size or smaller

# DDS surface flags
DDSD_CAPS	= 0x00000001
DDSD_HEIGHT	= 0x00000002
DDSD_WIDTH	= 0x00000004
DDSD_PITCH	= 0x00000008
DDSD_PIXELFORMAT= 0x00001000
DDSD_MIPMAPCOUNT= 0x00020000
DDSD_LINEARSIZE	= 0x00080000
DDSD_DEPTH	= 0x00800000
# DS pixelformat flags
DDPF_ALPHAPIXELS= 0x00000001
DDPF_FOURCC	= 0x00000004
DDPF_RGB	= 0x00000040
# DDS caps1
DDSCAPS_COMPLEX	= 0x00000008
DDSCAPS_TEXTURE	= 0x00001000
DDSCAPS_MIPMAP	= 0x00400000


# 2.5-only version of case-insensitive sort for str or unicode
def sortfolded(seq):
    seq.sort(key=lambda x: x.lower())


def readLib(filename, objects, terrain, iscustom, thiscustom):
    thisfileobjs={}
    private = deprecated = False
    h=None
    path=dirname(filename)
    packagename = basename(path)
    try:
        h=codecs.open(filename, 'rU', 'latin1')
        if not h.readline().strip()[0] in ['I','A']:
            raise IOError
        if not h.readline().split()[0]=='800':
            raise IOError
        if not h.readline().split()[0]=='LIBRARY':
            raise IOError
        regionskip=False
        for line in h:
            c=line.split()
            if not c: continue
            id=c[0]
            if id=='REGION':
                regionskip=(c[1]!='all')	# we don't yet handle region-specific libraries (e.g. terrain)
            elif regionskip:
                continue
            elif id=='PUBLIC':
                private = deprecated = False
            elif id=='PRIVATE':
                private = not thiscustom	# only list PRIVATE exports if in the same scenery package
                deprecated = False
            elif id=='DEPRECATED':
                private = False
                deprecated = True
            elif id in ['EXPORT', 'EXPORT_RATIO', 'EXPORT_EXTEND', 'EXPORT_EXCLUDE']:
                # ignore EXPORT_BACKUP
                if id=='EXPORT_RATIO': c.pop(1)
                if len(c)<3 or (c[1][-4:].lower() in SkipDefs and c[1]!=NetworkDef.DEFAULTFILE): continue
                name=c[1].replace(':','/').replace('\\','/')
                # allow single spaces
                obj=' '.join(c[2:]).replace(':','/').replace('\\','/')
                if not iscustom and basename(obj).startswith('blank.'):
                    continue	# no point adding placeholders
                obj=join(path, normpath(obj))
                if name[-4:]=='.ter':
                    if name not in terrain:
                        terrain[name] =  obj
                elif name in thisfileobjs:		# already processed this name
                    p = thisfileobjs[name]
                    p.multiple = True
                    p.private = private and p.private	# shouldn't really happen in same package
                    p.deprecated = deprecated and p.deprecated	# ditto
                elif name in objects:			# already defined elsewhere
                    if private:
                        pass				# just let existing item stand
                    elif id=='EXPORT_EXTEND':
                        p = thisfileobjs[name] = objects[name]
                        p.multiple = True
                        p.private = False
                        p.deprecated = deprecated and p.deprecated
                    else:				# replacing thing in lower-priority package
                        thisfileobjs[name] = objects[name] = PaletteEntry(obj, packagename, iscustom, False, deprecated)	# override everything
                else:
                    thisfileobjs[name] = objects[name] = PaletteEntry(obj, packagename, iscustom, private, deprecated)
    except:
        if h: h.close()
        if __debug__:
            print filename
            print_exc()


# Returns dict of network info by type_id
def readNet(filename):

    class NetDef:
        def __init__(self, name, type_id, filename, texs, offset, width, length, color):
            self.name = name
            self.type_id = type_id
            self.filename = filename
            self.texs = texs
            self.offset = offset
            self.width = width
            self.length = length
            self.color = color

    path=dirname(filename)
    h=file(filename, 'rU')
    if not h.readline().strip()[0] in ['I','A']:
        raise IOError
    if not h.readline().split()[0]=='800':
        raise IOError
    if not h.readline().split()[0]=='ROADS':
        raise IOError

    currentdef=None
    comment=None
    names={}	# road names by type_id
    types={}	# preferred subtype_id by type_id
    subtypes={}	# (file location, width, length, (r, g, b)) by subtype_id
    texs=[]
    while True:
        line=h.readline()
        if not line: break
        c=line.split()
        if not c: continue
        id=c[0]
        if id=='#VROAD':
            comment = c[1]
            if comment.startswith('seconary'): comment = 'secondary'+comment[8:]	# be nice and fix spelling error
        elif id=='TEXTURE':
            texs.append(join(path,c[2]))
        elif id=='ROAD_DRAPED':		# flags? type ? ?
            currentdef = int(c[2])
            if comment:
                names[currentdef] = comment+NetworkDef.NETWORK
                comment=None
            else:
                names[currentdef] = '#%03d%s' % (currentdef, NetworkDef.NETWORK)
        elif id=='ROAD_DRAPE_CHOICE':	# max_height? subtype
            if not currentdef: raise IOError
            subtype_id=int(c[2])
            if subtype_id and currentdef not in types:
                types[currentdef] = subtype_id
        elif id=='ROAD_TYPE':		# subtype width length 0 r g b
            offset=long(h.tell())		# cast to long for 64bit Linux
            subtypes[int(c[1])] = (offset, float(c[2]), float(c[3]), (float(c[5]),float(c[6]),float(c[7])))

    h.close()
    return dict([(type_id, NetDef(names[type_id], type_id, filename, texs, *subtypes[types[type_id]])) for type_id in types])


class TexCache:
    
    def __init__(self):
        self.blank=0	#self.get(join('Resources','blank.png'))
        self.texs={}
        self.terraintexs=[]	# terrain textures will not be reloaded
        self.stats={}
        # Must be after init
        self.maxtexsize=glGetIntegerv(GL_MAX_TEXTURE_SIZE)
        self.npot=glInitTextureNonPowerOfTwoARB()
        self.compress=glInitTextureCompressionARB()
        self.s3tc=self.compress and glInitTextureCompressionS3TcEXT()
        self.bgra=glInitBgraEXT()
        if self.compress: glHint(GL_TEXTURE_COMPRESSION_HINT, GL_NICEST)	# Texture compression appears severe on Mac, but this doesn't help
        glHint(GL_GENERATE_MIPMAP_HINT, GL_FASTEST)	# prefer speed
        if glGetString(GL_VERSION) >= '1.2':
            self.clampmode=GL_CLAMP_TO_EDGE
        else:
            self.clampmode=GL_CLAMP

    def reset(self):
        a=[]
        for name in self.texs.keys():
            if self.texs[name] not in self.terraintexs:
                a.append(self.texs[name])
                self.texs.pop(name)
        if a:
            glDeleteTextures(array(a,uint32))

    def get(self, path, wrap=True, alpha=True, downsample=False, fixsize=False):
        if not path: return self.blank
        if path in self.texs:
            return self.texs[path]
        #self.texs[path]=self.blank	# don't do this - want error reported for each file that uses this texture

        #if __debug__: clock=time.clock()	# Processor time

        # X-Plane 10 will load dds or png depending on user's compression settings.
        # We always prefer DDS on the basis that a pre-compressed DDS will look better than a dynamically compressed PNG.
        (base,oldext)=splitext(path)
        for ext in ['.dds', '.DDS', '.png', '.PNG', '.bmp', 'BMP', oldext]:
            if exists(base+ext): break

        try:
            if ext.lower()=='.dds':
                # Do DDS manually
                h=file(base+ext,'rb')
                if h.read(4)!='DDS ': raise Exception, 'This is not a DDS file'
                (ssize,sflags,height,width,size,depth,mipmaps)=unpack('<7I', h.read(28))
                #print ssize,sflags,height,width,size,depth,mipmaps
                if sflags&(DDSD_CAPS|DDSD_PIXELFORMAT|DDSD_WIDTH|DDSD_HEIGHT)!=(DDSD_CAPS|DDSD_PIXELFORMAT|DDSD_WIDTH|DDSD_HEIGHT): raise Exception, 'Missing mandatory fields'
                if sflags&DDSD_DEPTH: raise Exception, 'Volume texture not supported'
                for dim in [width,height]:
                    l=log(dim,2)
                    if l!=int(l):
                        raise Exception, "Width and/or height is not a power of two"
                if sflags&(DDSD_PITCH|DDSD_LINEARSIZE)==DDSD_PITCH:
                    size*=height
                #elif sflags&(DDSD_PITCH|DDSD_LINEARSIZE)!=DDSD_LINEARSIZE:
                #    raise Exception, 'Invalid size'
                h.seek(0x4c)
                (psize,pflags,fourcc,bits,redmask,greenmask,bluemask,alphamask,caps1,caps2)=unpack('<2I4s7I', h.read(40))
                if not sflags&DDSD_MIPMAPCOUNT or not caps1&DDSCAPS_MIPMAP or not mipmaps:
                    mipmaps=1

                if pflags&DDPF_FOURCC:
                    # http://oss.sgi.com/projects/ogl-sample/registry/EXT/texture_compression_s3tc.txt
                    if not self.s3tc: raise Exception, 'This video driver does not support DXT compression'
                    if fourcc=='DXT1':
                        if not (sflags&(DDSD_PITCH|DDSD_LINEARSIZE)):
                            size=width*height/2
                        else:
                            assert size==width*height/2
                        iformat=GL_COMPRESSED_RGBA_S3TC_DXT1_EXT
                    elif fourcc=='DXT3':
                        if not (sflags&(DDSD_PITCH|DDSD_LINEARSIZE)):
                            size=width*height
                        else:
                            assert size==width*height
                        iformat=GL_COMPRESSED_RGBA_S3TC_DXT3_EXT
                    elif fourcc=='DXT5':
                        if not (sflags&(DDSD_PITCH|DDSD_LINEARSIZE)):
                            size=width*height
                        else:
                            assert size==width*height
                        iformat=GL_COMPRESSED_RGBA_S3TC_DXT5_EXT
                    else:
                        raise Exception, '%s format not supported' % fourcc

                    if downsample and mipmaps>2 and width>downsamplemin and height>downsamplemin:
                        # Downsample twice
                        h.seek(4+ssize + (size*5)/4)
                        size/=16
                        width/=4
                        height/=4
                        mipmaps-=2
                    else:	# don't downsample
                        h.seek(4+ssize)
                    if not alpha:	# discard alpha
                        if iformat==GL_COMPRESSED_RGBA_S3TC_DXT1_EXT:
                            data=h.read()
                        else:
                            data=''
                            mw=width
                            mh=height
                            for i in range(mipmaps):
                                for j in range(((mw+3)/4) * ((mh+3)/4)):
                                    data+=h.read(16)[8:]	# skip alpha
                                mw = mw/2 or 1
                                mh = mh/2 or 1
                            size=width*height/2			# without alpha
                        iformat=GL_COMPRESSED_RGB_S3TC_DXT1_EXT
                    else:
                        data=h.read()
                    h.close()
                    self.stats[path]=len(data)

                    id=glGenTextures(1)
                    glBindTexture(GL_TEXTURE_2D, id)
                    if wrap:
                        glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_S,GL_REPEAT)
                        glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_T,GL_REPEAT)
                    else:
                        glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_S,self.clampmode)
                        glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_T,self.clampmode)
                    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_BASE_LEVEL, 0);
                    if mipmaps>1:
                        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAX_LEVEL, mipmaps-1)
                    elif width>compressmin and height>compressmin:
                        glTexParameteri(GL_TEXTURE_2D, GL_GENERATE_MIPMAP, GL_TRUE)	# must be before glTexImage
                        self.stats[path]=int(self.stats[path]*4.0/3.0)
                    else:					# Don't bother generating mipmaps for smaller textures
                        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAX_LEVEL, 0)
                    for i in range(mipmaps):
                        size = (iformat in [GL_COMPRESSED_RGB_S3TC_DXT1_EXT,GL_COMPRESSED_RGBA_S3TC_DXT1_EXT] and 8 or 16) * ((width+3)/4) * ((height+3)/4)
                        glCompressedTexImage2DARB(GL_TEXTURE_2D, i, iformat, width, height, 0, size, data)
                        data = data[size:]
                        width = width/2 or 1
                        height = height/2 or 1
                    #if __debug__: print "%6.3f" % (time.clock()-clock), basename(path), wrap, alpha, downsample, fixsize

                    self.texs[path]=id
                    if downsample:
                        self.terraintexs.append(id)
                    return id
                    
                elif pflags&DDPF_RGB:	# uncompressed
                    assert size==width*height*bits/8	# pitch appears unreliable
                    if bits==24 and redmask==0xff0000 and greenmask==0x00ff00 and bluemask==0x0000ff:
                        if not self.bgra: raise Exception, 'This video driver does not support BGR format'
                        format=GL_BGR_EXT
                        iformat=GL_RGB
                    elif bits==24 and redmask==0x0000ff and greenmask==0x00ff00 and bluemask==0xff0000:
                        format=GL_RGB
                        iformat=GL_RGB
                    elif bits==32 and pflags&DDPF_ALPHAPIXELS and alphamask==0xff000000L and redmask==0x00ff0000 and greenmask==0x0000ff00 and bluemask==0x000000ff:
                        if not self.bgra: raise Exception, 'This video driver does not support BGRA format'
                        format=GL_BGRA_EXT
                        iformat=GL_RGBA
                    elif bits==32 and not pflags&DDPF_ALPHAPIXELS and redmask==0x00ff0000 and greenmask==0x0000ff00 and bluemask==0x000000ff:
                        if not self.bgra: raise Exception, 'This video driver does not support BGRA format'
                        format_GL_BGRA_EXT
                        iformat=GL_RGB
                    else:
                        raise Exception, '%dbpp format not supported' % bits

                    if downsample and mipmaps>2 and width>downsamplemin and height>downsamplemin:
                        # Downsample twice
                        h.seek(4+ssize + (size*5)/4)
                        size/=16
                        width/=4
                        height/=4
                    else:	# don't downsample
                        h.seek(4+ssize)
                    data=h.read(size)
                    h.close()
                    
                    # fall through

                else:	# wtf?
                    raise Exception, 'Invalid compression type'

            else:
                try:	# JPEG2000?
                    import xml.etree.ElementTree	# force for py2exe
                    import glymur
                    jp2 = glymur.Jp2k(base+ext)

                except:	# supported PIL formats
                    if __debug__:
                        if ext=='.jp2': print_exc()
                    image = PIL.Image.open(base+ext)
                    mode = image.mode
                    formats = {'L':GL_LUMINANCE, 'LA':GL_LUMINANCE_ALPHA, 'RGB':GL_RGB, 'RGBA':GL_RGBA}
                    if mode in formats:
                        format = formats[mode]
                    else:	# convert weird formats to RGB - http://effbot.org/imagingbook/concepts.htm
                        format, mode = 'transparency' in image.info and (GL_RGBA, 'RGBA') or (GL_RGB, 'RGB')
                        image = image.convert(mode)
                    width, height = image.size
                    data = None

                else:	# JPEG2000
                    data = jp2.read()
                    height, width = data.shape[0:2]
                    channels = len(data.shape)==2 and 1 or data.shape[2]
                    format, mode = {1:(GL_LUMINANCE,'L'), 2:(GL_LUMINANCE_ALPHA,'LA'), 3:(GL_RGB,'RGB'), 4:(GL_RGBA,'RGBA')}[channels]
                    if data.dtype!=uint8:
                        for superbox in jp2.box:
                            if isinstance(superbox, glymur.jp2box.JP2HeaderBox):
                                for box in superbox.box:
                                    if isinstance(box, glymur.jp2box.ImageHeaderBox):
                                        data = (data>>(box.bits_per_component-8)).astype(uint8)	# simple downscale
                    if data.dtype!=uint8:
                        data = data.astype(uint8)	# didn't find image header! - just truncate

                # check size
                size = [width, height]
                for i in [0,1]:
                    l=log(size[i],2)
                    if l!=int(l):
                        if not fixsize: raise Exception, "Width and/or height not a power of two"
                        size[i]=2**(1+int(l))	# expand to next power of two
                if downsample and size[0]>downsamplemin and size[1]>downsamplemin:
                    if data is not None: image = PIL.Image.frombuffer(mode, (width,height), data, "raw", mode, 0, 1)
                    image = image.resize((min(size[0]/4,self.maxtexsize),min(size[1]/4,self.maxtexsize)), PIL.Image.BICUBIC)
                    width, height = image.size
                    data = image.tostring("raw", mode)
                elif (size!=[width, height] and not self.npot) or size[0]>self.maxtexsize or size[1]>self.maxtexsize:
                    if data is not None: image = PIL.Image.frombuffer(mode, (width,height), data, "raw", mode, 0, 1)
                    image = image.resize((min(size[0],self.maxtexsize),min(size[1],self.maxtexsize)), PIL.Image.BICUBIC)
                    width, height = image.size
                    data = image.tostring("raw", mode)
                elif data is None:
                    # obtain data from Image
                    data = image.tostring("raw", mode)

            # Common code for uncompressed DDS, JPEG2000 and PIL formats.
            # variables used: data, format, iformat, width, height

            # Discard alpha?
            if alpha:
                iformat = format
            elif format == GL_RGBA:
                iformat = GL_RGB
            elif format == GL_LUMINANCE_ALPHA:
                iformat = GL_LUMINANCE
            else:
                iformat = format

            if self.compress and (width>compressmin or height>compressmin):	# Don't compress small textures, including built-ins
                if iformat==GL_LUMINANCE:
                    iformat=GL_COMPRESSED_LUMINANCE
                    self.stats[path]=width*height/2	# Assume DXT1
                elif iformat==GL_LUMINANCE_ALPHA:
                    iformat=GL_COMPRESSED_LUMINANCE_ALPHA
                    self.stats[path]=width*height/2	# Assume DXT1
                elif iformat==GL_RGB:
                    iformat=GL_COMPRESSED_RGB
                    self.stats[path]=width*height/2	# Assume DXT1
                elif iformat==GL_RGBA:
                    iformat=GL_COMPRESSED_RGBA
                    self.stats[path]=width*height	# Assume DXT3/5
            else:
                self.stats[path]=width*height*4		# Assume 4bpp even for GL_RGB

            id=glGenTextures(1)
            glBindTexture(GL_TEXTURE_2D, id)
            if wrap:
                glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_S,GL_REPEAT)
                glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_T,GL_REPEAT)
            else:
                glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_S,self.clampmode)
                glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_T,self.clampmode)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_BASE_LEVEL, 0);
            if width>compressmin and height>compressmin:
                glTexParameteri(GL_TEXTURE_2D, GL_GENERATE_MIPMAP, GL_TRUE)	# must be before glTexImage
                self.stats[path]=int(self.stats[path]*4.0/3.0)
            else:						# Don't bother generating mipmaps for smaller textures
                glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAX_LEVEL, 0)
            glTexImage2D(GL_TEXTURE_2D, 0, iformat, width, height, 0, format, GL_UNSIGNED_BYTE, data)
            #if __debug__: print "%6.3f" % (time.clock()-clock), basename(path), wrap, alpha, downsample, fixsize
                
            self.texs[path]=id
            if downsample:
                self.terraintexs.append(id)
            return id

        except:
            if __debug__: print_exc()
            raise


class VertexCache:

    def __init__(self):
        self.ter={}		# name -> physical ter
        self.mesh={}		# tile -> [patches] where patch=(texture,f,v,t)
        self.nets={}		# tile -> [(type, [points])]
        self.elevation = {}	# ElevationMesh
        self.currenttile=None
        self.meshcache=[]	# [indices] of current tile
        self.netcache=None	# networks in current tile
        self.lasttri=None	# take advantage of locality of reference

        self.texcache=TexCache()
        self.instance_data=empty((0,5),float32)	# Copy of vbo data
        self.instance_pending=[]		# Clutter not yet allocated into vbo
        self.instance_count=0			# Allocated and pending vertices
        self.instance_valid=False
        self.vector_data=empty((0,6),float32)	# Copy of vbo data
        self.vector_pending=[]			# Vector data not yet allocated into vbo
        self.vector_count=0			# Allocated and pending vertices
        self.vector_valid=False
        self.dynamic_data=empty((0,6),float32)
        self.dynamic_pending={}
        self.dynamic_valid=False
        self.buckets = Buckets(self)
        self.dsfdirs=None	# [custom, global, default]

    def reset(self, terrain, dsfdirs):
        # invalidate geometry and textures
        if dsfdirs != self.dsfdirs:
            # X-Plane location changed - invalidate loaded meshes too
            self.mesh={}
            self.nets={}
            self.elevation = {}
        self.ter=terrain
        self.dsfdirs=dsfdirs
        self.flush()
        self.texcache.reset()
    
    def flush(self):
        # invalidate array indices
        self.currenttile=None
        self.meshcache=[]
        self.netcache=None
        self.lasttri=None
        self.instance_data=empty((0,5),float32)
        self.instance_pending=[]
        self.instance_valid=False
        self.instance_count=0
        self.vector_data=empty((0,6),float32)
        self.vector_pending=[]
        self.vector_count=0
        self.vector_valid=False
        self.dynamic_data=empty((0,6),float32)
        self.dynamic_pending={}
        self.dynamic_valid=False
        self.buckets = Buckets(self)

    def allocate_instance(self, data):
        # cache geometry data, but don't update OpenGL arrays yet
        assert isinstance(data,ndarray), data
        assert len(data)		# shouldn't be empty
        base=self.instance_count
        self.instance_count+=len(data)/5
        self.instance_pending.append(data)
        self.instance_valid=False	# new geometry -> need to update OpenGL
        return base

    def realize_instance(self, instance_vbo):
        # Allocate into VBO if required. Returns True if VBO updated.
        if not self.instance_valid:
            if __debug__: clock=time.clock()
            self.instance_data=concatenate(self.instance_pending)
            self.instance_pending=[self.instance_data]	# so gets included in concatenate next time round
            self.instance_valid=True
            instance_vbo.set_array(self.instance_data)
            if __debug__: print "%6.3f time to realize instance VBO, size %dK" % (time.clock()-clock, self.instance_data.size/256)
            return True
        else:
            return False

    def allocate_vector(self, data):
        # cache geometry data, but don't update OpenGL arrays yet
        assert isinstance(data,ndarray), data
        base=self.vector_count
        self.vector_count+=len(data)/6
        self.vector_pending.append(data)
        self.vector_valid=False	# new geometry -> need to update OpenGL
        return base

    def realize_vector(self, vector_vbo):
        # Allocate into VBO if required. Returns True if VBO updated.
        if not self.vector_valid:
            if __debug__: clock=time.clock()
            self.vector_data=concatenate(self.vector_pending)
            self.vector_pending=[self.vector_data]	# so gets included in concatenate next time round
            self.vector_valid=True
            vector_vbo.set_array(self.vector_data)
            if __debug__: print "%6.3f time to realize vector VBO, size %dK" % (time.clock()-clock, self.vector_data.size/256)
            return True
        else:
            return False

    def allocate_dynamic(self, placement, alloc):
        # cache geometry data, but don't update OpenGL arrays yet
        assert isinstance(placement,Clutter)
        if not alloc:
            # Placement's layout is cleared (e.g. prior to deletion) remove from VBO on next rebuild
            self.dynamic_pending.pop(placement,False)
            placement.base=None
        else:
            assert placement.dynamic_data is not None, placement
            assert placement.dynamic_data.size, placement	# shouldn't have tried to allocate if no data
            self.dynamic_pending[placement]=True
        self.dynamic_valid=False	# new geometry -> need to update OpenGL

    def realize_dynamic(self, dynamic_vbo):
        # Allocate into VBO if required. Returns True if VBO updated.
        if not self.dynamic_valid:
            if __debug__: clock=time.clock()
            self.buckets = Buckets(self)	# reset
            data=[]
            dynamic_count=0
            for placement in self.dynamic_pending:
                thisdata = placement.bucket_dynamic(dynamic_count, self.buckets)
                dynamic_count += len(thisdata)/6
                data.append(thisdata)
            if data:
                self.dynamic_data=concatenate(data)
            else:
                self.dynamic_data=empty((0,),float32)
            self.dynamic_valid=True
            dynamic_vbo.set_array(self.dynamic_data)
            if __debug__: print "%6.3f time to realize dynamic VBO, size %dK" % (time.clock()-clock, self.dynamic_data.size/256)
            return True
        else:
            return False

    def loadMesh(self, tile, netdefs):
        key=(tile[0],tile[1],prefs.options&Prefs.TERRAIN)
        netkey=(tile[0],tile[1],prefs.options&Prefs.NETWORK)
        if key in self.mesh and netkey in self.nets:
            if __debug__: print "loadMesh: already loaded"
            return	# don't reload
        dsfs=[]
        if prefs.options&Prefs.TERRAIN:
            for path in self.dsfdirs:
                if not glob(path): continue
                pathlen=len(glob(path)[0])+1
                thisdsfs=glob(join(path, '*', gnavdata, "%+02d0%+03d0" % (int(tile[0]/10), int(tile[1]/10)), "%+03d%+04d.[dD][sS][fF]" % (tile[0], tile[1])))
                # asciibetical, except global is last
                thisdsfs.sort(lambda x,y: ((x[pathlen:].lower().startswith('-global ') and 1) or
                                           (y[pathlen:].lower().startswith('-global ') and -1) or
                                           cmp(x,y)))
                dsfs+=thisdsfs
                #print join(path, '*', '[eE][aA][rR][tT][hH] [nN][aA][vV] [dD][aA][tT][aA]', "%+02d0%+03d0" % (int(tile[0]/10), int(tile[1]/10)), "%+03d%+04d.[dD][sS][fF]" % (tile[0], tile[1]))
        if __debug__: clock=time.clock()	# Processor time
        gc.disable()	# work round http://bugs.python.org/issue4074 on Python<2.7
        for dsf in dsfs:
            try:
                (lat, lon, placements, nets, mesh)=readDSF(dsf, netdefs, self.ter)
                if mesh:
                    self.elevation[(tile[0],tile[1],Prefs.ELEVATION)] = ElevationMesh(tile, concatenate(mesh.values()))
                    self.elevation[(tile[0],tile[1],0)] = DummyElevationMesh(tile)
                    self.nets[(tile[0],tile[1],Prefs.NETWORK)] = nets
                    self.nets[(tile[0],tile[1],0)]=[]	# prevents reload on stepping down
                    self.mesh[key]=mesh
                    break
            except:
                if __debug__: print_exc()
        gc.enable()
        if __debug__: print "%6.3f time in loadMesh" % (time.clock()-clock)
        if not key in self.mesh:
            self.loadFallbackMesh(tile)

    def loadFallbackMesh(self, tile):
        key=(tile[0],tile[1],prefs.options&Prefs.TERRAIN)
        for path in self.dsfdirs[1:]:
            if glob(join(path, '*', gnavdata, "%+02d0%+03d0" % (int(tile[0]/10), int(tile[1]/10)), "%+03d%+04d.[dD][sS][fF]" % (tile[0], tile[1]))) or glob(join(path, pardir, gnavdata, "%+02d0%+03d0" % (int(tile[0]/10), int(tile[1]/10)), "%+03d%+04d.[eE][nN][vV]" % (tile[0], tile[1]))):
                # DSF or ENV exists but can't read it
                tex=join('Resources','airport0_000.png')
                break
        else:
            tex=join('Resources','Sea01.png')
        self.mesh[key] = { (tex, True): array([[-onedeg*cos(radians(tile[0]+1))/2, 0,-onedeg/2,   0,   0],
                                               [ onedeg*cos(radians(tile[0]  ))/2, 0, onedeg/2, 100, 100],
                                               [-onedeg*cos(radians(tile[0]  ))/2, 0, onedeg/2,   0, 100],
                                               [-onedeg*cos(radians(tile[0]+1))/2, 0,-onedeg/2,   0,   0],
                                               [ onedeg*cos(radians(tile[0]+1))/2, 0,-onedeg/2, 100,   0],
                                               [ onedeg*cos(radians(tile[0]  ))/2, 0, onedeg/2, 100, 100]], float32) }
        self.nets[(tile[0],tile[1],0)] = self.nets[(tile[0],tile[1],Prefs.NETWORK)] = []
        self.elevation[(tile[0],tile[1],0)] = self.elevation[(tile[0],tile[1],Prefs.ELEVATION)] = DummyElevationMesh(tile)

    # return mesh data sorted by tex and net data for drawing
    def getMesh(self, tile):

        if tile==self.currenttile:
            #if __debug__: print "getMesh: cached"
            return (self.meshcache, self.netcache)

        # add into array
        if __debug__: clock=time.clock()	# Processor time

        self.meshcache = []
        for (texture, wrap), v in self.mesh[(tile[0],tile[1],prefs.options&Prefs.TERRAIN)].iteritems():
            vdata = v.flatten()
            base=self.allocate_instance(vdata)
            texno=self.texcache.get(texture, wrap, False, True)
            self.meshcache.append((base, len(vdata)/5, texno))

        nets = self.nets[(tile[0],tile[1],prefs.options&Prefs.NETWORK)]
        if nets:
            (points, indices) = nets
            base = self.allocate_vector(points.flatten())
            self.netcache = base+indices
        else:
            self.netcache = None

        if __debug__: print "%6.3f time in getMesh" % (time.clock()-clock)
        self.currenttile=tile
        return (self.meshcache, self.netcache)

    def getElevationMesh(self, tile):
        return self.elevation[(tile[0],tile[1],prefs.options&Prefs.ELEVATION)]
