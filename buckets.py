from collections import defaultdict	# Requires Python 2.5
from numpy import array
from OpenGL.GL import *

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

    def draw(self, glstate, selected, aptdata={}, imagery=None, imageryopacity=None):
        glstate.set_dynamic(self.vertexcache)
        glstate.set_color(selected and COL_SELECTED or COL_UNPAINTED)
        glstate.set_cull(True)
        glstate.set_poly(True)
        glstate.set_depthtest(True)

        # draped layers
        for layer in range(ClutterDef.LAYERCOUNT):
            self.layerbuckets[layer].draw(glstate)	# draw per layer
            # Special handling - yuck
            if not selected:
                if layer in aptdata:
                    (base, length) = aptdata[layer]
                    glDisableVertexAttribArray(glstate.skip_pos)
                    glVertexAttrib1f(glstate.skip_pos, 0)
                    glstate.set_instance(self.vertexcache)
                    glstate.set_texture(self.vertexcache.texcache.get('Resources/surfaces.png'))
                    glDrawArrays(GL_TRIANGLES, base, length)
                    glstate.set_dynamic(self.vertexcache)
                    if selected is not None:
                        glEnableVertexAttribArray(glstate.skip_pos)
                if layer == ClutterDef.RUNWAYSLAYER and imagery:
                    glstate.set_color(COL_SELECTED)	# trick glstate there's been a change in colour
                    glColor4f(1.0, 1.0, 1.0, imageryopacity/100.0)	# not using glstate!
                    self.layerbuckets[ClutterDef.IMAGERYLAYER].draw(glstate)	# draw out of order
                    glstate.set_color(COL_UNPAINTED)

        # other layers
        glstate.set_poly(False)
        glstate.set_color(selected and COL_SELECTED or None)
        glstate.set_depthtest(False)		# Need line to appear over terrain
        self.layerbuckets[ClutterDef.OUTLINELAYER].draw(glstate)

        glstate.set_color(selected and COL_SELECTED or COL_UNPAINTED)
        glstate.set_depthtest(True)
        self.layerbuckets[ClutterDef.GEOMCULLEDLAYER].draw(glstate)
        glstate.set_cull(False)
        self.layerbuckets[ClutterDef.GEOMNOCULLLAYER].draw(glstate)
