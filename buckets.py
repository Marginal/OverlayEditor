from collections import defaultdict	# Requires Python 2.5
from numpy import array, zeros, float32
from OpenGL.GL import *
from OpenGL.extensions import alternate
from OpenGL.GL.EXT.multi_draw_arrays import glMultiDrawArraysEXT
glMultiDrawArrays = alternate(glMultiDrawArrays, glMultiDrawArraysEXT)

from clutterdef import ClutterDef, COL_SELECTED, COL_UNPAINTED


# one per texture per layer
class DrawBucket:

    def __init__(self):
        self.first=[]
        self.count=[]
        self.afirst = self.acount = None

    def add(self, first, count):
        self.first.append(first)
        self.count.append(count)
        self.afirst = self.acount = None

    def draw(self, glstate):
        if glstate.multi_draw_arrays:
            if self.afirst is None:
                self.afirst = array(self.first, GLint)
                self.acount = array(self.count, GLsizei)
            glMultiDrawArrays(GL_TRIANGLES, self.afirst, self.acount, len(self.count))
        else:
            for first,count in zip(self.first, self.count):
                glDrawArrays(GL_TRIANGLES, first, count)

# Like DrawBucket but for outlines
class OutlineDrawBucket(DrawBucket):

    def draw(self, glstate):
        if glstate.multi_draw_arrays:
            if self.afirst is None:
                self.afirst = array(self.first, GLint)
                self.acount = array(self.count, GLsizei)
            glMultiDrawArrays(GL_LINE_STRIP, self.afirst, self.acount, len(self.count))
        else:
            for first,count in zip(self.first, self.count):
                glDrawArrays(GL_LINE_STRIP, first, count)


# one per layer
class LayerBucket:

    class DrawBucketDict(dict):
        def __missing__(self, texture):
            x = DrawBucket()
            self[texture] = x
            return x

    def __init__(self):
        self.drawbuckets = LayerBucket.DrawBucketDict()

    def add(self, texture, first, count):
        self.drawbuckets[texture].add(first, count)

    def draw(self, glstate):
        for texture, bucket in self.drawbuckets.iteritems():
            glstate.set_texture(texture)
            bucket.draw(glstate)

# like LayerBucket but for Outlines
class OutlineLayerBucket(LayerBucket):

    def __init__(self):
        self.drawbuckets = { None: OutlineDrawBucket() }


# one
class Buckets:

    def __init__(self, vertexcache):
        self.layerbuckets  =[LayerBucket() for i in range(ClutterDef.DRAWLAYERCOUNT)]
        self.layerbuckets[ClutterDef.OUTLINELAYER] = OutlineLayerBucket()	# special handling for outlines
        self.vertexcache = vertexcache

    def flush(self):
        self.__init__()

    def add(self, layer, texture, first, count):
        self.layerbuckets[layer].add(texture, first, count)

    def draw(self, glstate, selected, aptdata={}, has_imagery=None, imagery_opacity=None):
        glstate.set_color(COL_UNPAINTED)
        glstate.set_cull(True)
        glstate.set_poly(True)
        glstate.set_depthtest(True)

        # draped layers - unselected
        for layer in range(ClutterDef.LAYERCOUNT):
            self.layerbuckets[layer].draw(glstate)	# draw per layer
            # Special handling - yuck
            if layer == ClutterDef.MARKINGSLAYER and layer in aptdata:
                (base,count) = aptdata[layer]
                glstate.set_vector(self.vertexcache)
                glstate.set_texture(None)
                glstate.set_color(None)
                glstate.set_depthtest(False)	# Need line to appear over terrain
                glShadeModel(GL_FLAT)
                glDrawElements(GL_LINES, count, GL_UNSIGNED_INT, glstate.vector_indices_vbo + base*4)
                glstate.set_dynamic(self.vertexcache)
                glstate.set_color(COL_UNPAINTED)
                glstate.set_depthtest(True)
                glShadeModel(GL_SMOOTH)
            elif layer in aptdata:
                (base, length) = aptdata[layer]
                glstate.set_instance(self.vertexcache)
                glstate.set_texture(self.vertexcache.texcache.get('Resources/surfaces.png'))
                glDrawArrays(GL_TRIANGLES, base, length)
                glstate.set_dynamic(self.vertexcache)
            if layer == ClutterDef.RUNWAYSLAYER and has_imagery:	# draw imagery out of order
                glstate.set_color(COL_SELECTED)	# trick glstate there's been a change in colour
                glColor4f(1.0, 1.0, 1.0, imagery_opacity/100.0)	# not using glstate!
                self.layerbuckets[ClutterDef.IMAGERYLAYER].draw(glstate)
                self.layerbuckets[ClutterDef.IMAGEFILELAYER].draw(glstate)	# draw file after imagery
                glstate.set_color(COL_UNPAINTED)

        # other layers - unselected
        glstate.set_poly(False)
        glstate.set_color(None)
        glstate.set_depthtest(False)		# Need line to appear over terrain
        self.layerbuckets[ClutterDef.OUTLINELAYER].draw(glstate)

        glstate.set_color(COL_UNPAINTED)
        glstate.set_depthtest(True)
        self.layerbuckets[ClutterDef.GEOMCULLEDLAYER].draw(glstate)
        glstate.set_cull(False)
        self.layerbuckets[ClutterDef.GEOMNOCULLLAYER].draw(glstate)


        # selected - last so overwrites unselected
        if selected:

            # build temporary filtered buckets
            filtered = Buckets(self.vertexcache)
            for placement in selected:
                if placement.base is not None:
                    placement.bucket_dynamic(placement.base, filtered)

            # draped layers - selected
            glstate.set_color(COL_SELECTED)
            glstate.set_cull(True)
            glstate.set_poly(True)
            for layer in range(ClutterDef.LAYERCOUNT):
                filtered.layerbuckets[layer].draw(glstate)	# draw per layer

            # other layers - selected
            glstate.set_depthtest(False)		# Need line to appear over terrain
            filtered.layerbuckets[ClutterDef.OUTLINELAYER].draw(glstate)

            glstate.set_depthtest(True)
            filtered.layerbuckets[ClutterDef.GEOMCULLEDLAYER].draw(glstate)
            glstate.set_cull(False)
            filtered.layerbuckets[ClutterDef.GEOMNOCULLLAYER].draw(glstate)
