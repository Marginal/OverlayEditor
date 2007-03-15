# Virtual class for ground clutter - ie editable stuff
#
# Derived classes expected to have following members:
# __init__
# __str__
# clone -> make a new copy
#
class Clutter:
    pass

class Object(Clutter):

    def __init__(self, name, lat, lon, hdg, height=None):
        Clutter.__init__(self)
        self.name=name
        self.lat=lat
        self.lon=lon
        self.hdg=hdg
        self.height=height

    def __str__(self):
        return '<"%s" %11.6f %10.6f %d %s>' % (
            self.name, self.lat, self.lon, self.hdg, self.height)

    def clone(self):
        return Object(self.name, self.lat, self.lon, self.hdg, self.height)


class Polygon(Clutter):
    EXCLUDE='Exclude:'
    FACADE='.fac'
    FOREST='.for'
    POLYGON='.pol'

    EXCLUDE_NAME={'sim/exclude_bch': 'Exclude: Beaches',
                  'sim/exclude_pol': 'Exclude: Draped',
                  'sim/exclude_fac': 'Exclude: Facades',
                  'sim/exclude_for': 'Exclude: Forests',
                  'sim/exclude_obj': 'Exclude: Objects',
                  'sim/exclude_net': 'Exclude: Roads',
                  'sim/exclude_str': 'Exclude: Strings'}

    def __init__(self, name, kind, param, nodes):
        Clutter.__init__(self)
        self.name=name
        self.lat=self.lon=0	# For centreing etc
        self.kind=kind		# enum, or extension if unknown type
        self.param=param
        self.nodes=nodes	# [[(lon,lat,...)]]
        self.points=[]		# list of 1st winding in world space (x,y,z)
        self.quads=[]		# list of points (x,y,z,s,t)
        self.roof=[]		# list of points (x,y,z,s,t)

    def __str__(self):
        return '<"%s" %d %f %s>' % (self.name,self.kind,self.param,self.points)

    def clone(self):
        return Polygon(self.name, self.kind, self.param,
                       [list(w) for w in self.nodes])
        


