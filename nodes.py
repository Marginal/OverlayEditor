from math import atan2, cos, hypot, radians, sin

import copy

from elevation import minres, round2res

# Basic node with no bezier control points. e.g. Forest. Also used for Draped orthos and unknown polygon types.
class Node:

    def __init__(self, coords):
        if isinstance(coords, Node):	# being demoted
            (self.lon, self.lat) = (coords.lon, coords.lat)
            self.rest = []
        else:
            (self.lon, self.lat) = coords[:2]
            self.rest = list(coords[2:])
        self.loc = None		# (x,y,z) in local coordinates
        self.bezier = False
        self.pointidx = 0

    def clone(self):
        return copy.copy(self)	# can just do a shallow copy because our instance variables are immutable

    def setloc(self, x, y, z):
        if y is not None:
            self.loc = (x, y, z)
        else:
            self.loc = (x, self.loc[1], z)

    def move(self, dlat, dlon, tile):
        if tile:
            self.lon = max(tile[1], min(tile[1]+1, self.lon + dlon))        # points can be on upper/right boundary of tile
            self.lat = max(tile[0], min(tile[0]+1, self.lat + dlat))
        else:	# don't round, e.g. if taking a copy
            self.lon = self.lon + dlon
            self.lat = self.lat + dlat

    def rotate(self, dhdg, loc, tile):
        assert loc and tile
        (lat,lon) = loc
        h = atan2(self.lon-lon, self.lat-lat) + radians(dhdg)
        l = hypot(self.lon-lon, self.lat-lat)
        self.lon = max(tile[1], min(tile[1]+1, round2res(lon + sin(h) * l)))
        self.lat = max(tile[0], min(tile[0]+1, round2res(lat + cos(h) * l)))

    def write(self, south, west):
        # DSFTool rounds down, so round up here first
        s = 'POLYGON_POINT\t%14.9f %14.9f' % (min(west+1, self.lon+minres/4), min(south+1, self.lat+minres/4))
        for p in self.rest:
            s += ' %14.9f' % p
        return s + '\n'

    def coordcount(self):
        return 2 + len(self.rest)


class BezierNode(Node):

    def __init__(self, coords):
        if isinstance(coords, Node):	# being promoted
            coords = [coords.lon, coords.lat] + coords.rest[-2:]	# drop param if any
            assert len(coords) in [2,4], coords
        Node.__init__(self, coords[:2])
        if len(coords)==2:
            # Not actually a bezier node, but in a polygon where others are bezier nodes
            self.bezlon = self.bezlat = self.bz2lon = self.bz2lat = 0
        else:
            assert len(coords)==4, coords
            (self.lon, self.lat, self.bezlon, self.bezlat) = coords[:4]
            self.bezlon -= self.lon
            self.bezlat -= self.lat
            self.bz2lon = -self.bezlon		# backwards-pointing bezier is mirror of forwards, unless split
            self.bz2lat = -self.bezlat
            self.bezier = bool(self.bezlon or self.bezlat)	# non-beziers are encoded by repeating the location
        self.bezloc = self.bz2loc = None	# (x,y,z) in local coordinates
        self.split  = False

    def setbezloc(self, x, y, z):
        if y is not None:
            self.bezloc = (x, y, z)
        else:
            self.bezloc = (x, self.loc[1], z)

    def setbz2loc(self, x, y, z):
        if y is not None:
            self.bz2loc = (x, y, z)
        else:
            self.bz2loc = (x, self.loc[1], z)

    def swapbez(self):
        # swap bezier points. Needed when order of nodes is reversed.
        (a,b) = (self.bezlat,self.bezlon)
        (self.bezlat,self.bezlon) = (self.bz2lat,self.bz2lon)
        (self.bz2lat,self.bz2lon) = (a,b)

    def rotate(self, dhdg, loc, tile):
        Node.rotate(self, dhdg, loc, tile)
        (lat,lon) = loc
        if self.bezlon or self.bezlat:
            h = atan2(self.bezlon, self.bezlat) + radians(dhdg)
            l = hypot(self.bezlon, self.bezlat)
            self.bezlon = round2res(sin(h) * l)
            self.bezlat = round2res(cos(h) * l)
        if not self.split:
            self.bz2lon = -self.bezlon
            self.bz2lat = -self.bezlat
        elif self.bz2lon or self.bz2lat:
            h = atan2(self.bz2lon, self.bz2lat) + radians(dhdg)
            l = hypot(self.bz2lon, self.bz2lat)
            self.bz2lon = round2res(sin(h) * l)
            self.bz2lat = round2res(cos(h) * l)

    def write(self, south, west):
        # DSFTool rounds down, so round up here first
        if not self.bezier:
            return 'POLYGON_POINT\t%14.9f %14.9f %14.9f %14.9f\n' % (min(west+1, self.lon+minres/4), min(south+1, self.lat+minres/4), min(west+1, self.lon+minres/4), min(south+1, self.lat+minres/4))	# repeat location in bezier fields
        elif not self.split:
            return 'POLYGON_POINT\t%14.9f %14.9f %14.9f %14.9f\n' % (min(west+1, self.lon+minres/4), min(south+1, self.lat+minres/4), min(west+1, self.lon+self.bezlon+minres/4), min(south+1, self.lat+self.bezlat+minres/4))	# standard forward-pointing bezier
        else:
            s = 'POLYGON_POINT\t%14.9f %14.9f %14.9f %14.9f\n' % (min(west+1, self.lon+minres/4), min(south+1, self.lat+minres/4), min(west+1, self.lon-self.bz2lon + minres/4), min(south+1, self.lat-self.bz2lat + minres/4))	# mirror of backwards-pointing bezier
            s+= 'POLYGON_POINT\t%14.9f %14.9f %14.9f %14.9f\n' % (min(west+1, self.lon+minres/4), min(south+1, self.lat+minres/4), min(west+1, self.lon+minres/4), min(south+1, self.lat+minres/4))	# dummy - repeat location in bezier fields
            s+= 'POLYGON_POINT\t%14.9f %14.9f %14.9f %14.9f\n' % (min(west+1, self.lon+minres/4), min(south+1, self.lat+minres/4), min(west+1, self.lon+self.bezlon+minres/4), min(south+1, self.lat+self.bezlat+minres/4))	# standard forward-pointing bezier
            return s            

    def coordcount(self):
        return 4

    @classmethod
    def fromNodes(cls, nodes):
        # promote to a bezier polygon
        newnodes = [[cls(node) for node in w] for w in nodes]
        # detect split nodes
        for nodes in newnodes:
            j = 2
            while j < len(nodes):
                (a,b,c) = nodes[j-2:j+1]
                if (a.lat == b.lat == c.lat) and not b.bezlat and (a.lon == b.lon == c.lon) and not b.bezlon:
                    a.split = True
                    a.bezlat = c.bezlat
                    a.bezlon = c.bezlon
                    nodes.pop(j)
                    nodes.pop(j-1)
                else:
                    j += 1
        return newnodes


# Node with single integer parameter - v10 facade, v10 network
class ParamNode(Node):
    
    def __init__(self, coords):
        if isinstance(coords, Node):	# being promoted
            coords = [coords.lon, coords.lat] + coords.rest
            assert len(coords) <= 3, coords
        Node.__init__(self, coords[:2])
        if len(coords)==3:
            self.param = int(coords[2])
        else:
            assert len(coords)==2, coords	# mismatch
            self.param = 0
            Node.__init__(self, coords)

    def write(self, south, west):
        # DSFTool rounds down, so round up here first
        return 'POLYGON_POINT\t%14.9f %14.9f %5d\n' % (min(west+1, self.lon+minres/4), min(south+1, self.lat+minres/4), self.param)

    def coordcount(self):
        return 3


# Node with single integer parameter - v10 facade, v10 network
class BezierParamNode(BezierNode,ParamNode):
    
    def __init__(self, coords):
        if isinstance(coords, ParamNode):	# being promoted
            coords = [coords.lon, coords.lat, coords.param]
        elif isinstance(coords, Node):
            coords = [coords.lon, coords.lat] + coords.rest
        if len(coords) in [3,5]:
            self.param = int(coords[2])
            BezierNode.__init__(self, coords[:2]+coords[3:])
        else:
            assert len(coords) in [2,4], coords	# mismatch
            self.param = 0
            BezierNode.__init__(self, coords)

    def write(self, south, west):
        # DSFTool rounds down, so round up here first
        if not self.bezier:
            return 'POLYGON_POINT\t%14.9f %14.9f %5d %14.9f %14.9f\n' % (min(west+1, self.lon+minres/4), min(south+1, self.lat+minres/4), self.param, min(west+1, self.lon+minres/4), min(south+1, self.lat+minres/4))	# repeat location in bezier fields
        elif not self.split:
            return 'POLYGON_POINT\t%14.9f %14.9f %5d %14.9f %14.9f\n' % (min(west+1, self.lon+minres/4), min(south+1, self.lat+minres/4), self.param, min(west+1, self.lon+self.bezlon+minres/4), min(south+1, self.lat+self.bezlat+minres/4))	# standard forward-pointing bezier
        else:
            s = 'POLYGON_POINT\t%14.9f %14.9f %5d %14.9f %14.9f\n' % (min(west+1, self.lon+minres/4), min(south+1, self.lat+minres/4), self.param, min(west+1, self.lon-self.bz2lon + minres/4), min(south+1, self.lat-self.bz2lat + minres/4))	# mirror of backwards-pointing bezier
            s+= 'POLYGON_POINT\t%14.9f %14.9f %5d %14.9f %14.9f\n' % (min(west+1, self.lon+minres/4), min(south+1, self.lat+minres/4), self.param, min(west+1, self.lon+minres/4), min(south+1, self.lat+minres/4))	# dummy - repeat location in bezier fields
            s+= 'POLYGON_POINT\t%14.9f %14.9f %5d %14.9f %14.9f\n' % (min(west+1, self.lon+minres/4), min(south+1, self.lat+minres/4), self.param, min(west+1, self.lon+self.bezlon+minres/4), min(south+1, self.lat+self.bezlat+minres/4))	# standard forward-pointing bezier
            return s            

    def coordcount(self):
        return 5


class NetworkNode(BezierParamNode):

    def __init__(self, coords):
        if isinstance(coords, ParamNode):	# being promoted
            self.param = coords.param
            BezierNode.__init__(self, [coords.lon, coords.lat])
        elif isinstance(coords, Node):	# being promoted
            self.param = int(coords.rest[0])
            BezierNode.__init__(self, [coords.lon, coords.lat])
        else:
            self.param = int(coords[2])
            BezierNode.__init__(self, coords[:2])
        self.split = True	# always split

    def write(self, type_id, junction_id):
        s = ''
        if self.bezier and not type_id and (self.bz2lon or self.bz2lat):
            s += 'SHAPE_POINT\t\t\t%14.9f %14.9f %d\n' % (self.lon+self.bz2lon, self.lat+self.bz2lat, 1)
        if type_id:	# First
            s += 'BEGIN_SEGMENT\t%d %d\t%d\t%14.9f %14.9f %d\n' % (0, type_id, junction_id, self.lon, self.lat, self.param)
        elif junction_id:	# Last
            s += 'END_SEGMENT\t\t%d\t%14.9f %14.9f %d\n' % (junction_id, self.lon, self.lat, self.param)
        else:
            s += 'SHAPE_POINT\t\t\t%14.9f %14.9f %d\n' % (self.lon, self.lat, 0)
        if self.bezier and (type_id or not junction_id) and (self.bezlon or self.bezlat):
            s += 'SHAPE_POINT\t\t\t%14.9f %14.9f %d\n' % (self.lon+self.bezlon, self.lat+self.bezlat, 1)
        return s

    def coordcount(self):
        assert False	# has no meaning here
        return 3

    @classmethod
    def fromNodes(cls, nodes):
        # promote to a bezier polygon
        assert len(nodes)==1, nodes	# network segments can't have holes
        newnodes = [[NetworkNode(node) for node in w] for w in nodes]
        # detect beziers
        for nodes in newnodes:
            j = 1
            while j < len(nodes)-1:
                node = nodes[j]
                if node.param:	# bezier?
                    prv = nodes[j-1]
                    if prv.bezier:
                        # previous node already a bezier, so this is a quadratic curve. attach control point to next node
                        nxt = nodes[j+1]
                        # assert not nxt.param
                        if j<len(nodes)-2 and nodes[j+2].param:
                            # next node will be a bezier anyway
                            nxt.param = 0
                            nxt.bezier = True
                            nxt.bezlat = nodes[j+2].lat - nxt.lat
                            nxt.bezlon = nodes[j+2].lon - nxt.lon
                            nxt.bz2lat = node.lat - nxt.lat
                            nxt.bz2lon = node.lon - nxt.lon
                            nodes.pop(j+2)
                            nodes.pop(j)
                            j += 1	# skip the node we've just turned into a bezier
                        else:
                            nxt.bezier = True
                            nxt.bezlat = 0
                            nxt.bezlon = 0
                            nxt.bz2lat = node.lat - nxt.lat
                            nxt.bz2lon = node.lon - nxt.lon
                            nodes.pop(j)
                            j += 1	# skip the node we've just turned into a bezier
                    elif j<len(nodes)-2 and not nodes[j+1].param and nodes[j+2].param:
                        # next node will be a bezier so attach it to that
                        nxt = nodes[j+1]
                        nxt.bezier = True
                        nxt.bezlat = nodes[j+2].lat - nxt.lat
                        nxt.bezlon = nodes[j+2].lon - nxt.lon
                        nxt.bz2lat = node.lat - nxt.lat
                        nxt.bz2lon = node.lon - nxt.lon
                        nodes.pop(j+2)
                        nodes.pop(j)
                        j += 1	# skip the node we've just turned into a bezier
                    else:
                        prv.bezier = True
                        prv.bezlat = node.lat - prv.lat
                        prv.bezlon = node.lon - prv.lon
                        prv.bz2lat = 0
                        prv.bz2lon = 0
                        nodes.pop(j)
                else:
                    j += 1
        return newnodes
