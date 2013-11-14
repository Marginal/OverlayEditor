import gc
from collections import defaultdict	# Requires Python 2.5
from math import atan2, cos, sin, radians
from numpy import array, arange, concatenate, cumsum, repeat, zeros, float32
from OpenGL.GL import GLuint
import time

if __debug__:
    from traceback import print_exc

from elevation import BBox, onedeg

surfaces = {0:  [0.125, 0.125],	# unknown
            1:  [0.375, 0.125],	# asphalt
            2:  [0.625, 0.125],	# concrete
            3:  [0.875, 0.125],	# grass
            4:  [0.125, 0.375],	# dirt,
            5:  [0.375, 0.375],	# gravel
            12: [0.125, 0.875],	# lakebed
            13: [0.375, 0.875],	# water
            14: [0.625, 0.875],	# ice
            15: [0.875, 0.875]}	# transparent


# Scan global airport list - assumes code is ASCII for speed
def scanApt(filename):
    airports={}	# (name, (lat,lon), fileoffset) by code
    nav=[]	# (type,lat,lon,hdg)
    h=file(filename, 'rU')	# assumes ascii
    if not h.readline().strip() in ['A','I']:
        raise IOError
    while True:	# NYEXPRO has a blank line here
        c=h.readline().split()
        if c: break
    ver=c[0]
    if not ver in ['600','703','715','810','850','1000']:
        raise IOError
    ver=int(ver)
    code=name=loc=None
    offset=0
    # mixing read and tell - http://www.thescripts.com/forum/post83277-3.html
    while True:
        line=h.readline()
        if not line: break
        c=line.split()
        if not c: continue
        id=int(c[0])
        if id in [1,16,17]:		# Airport/Seaport/Heliport
            if code and loc:
                airports[code]=(name,loc,offset)
                code=name=loc=None
            offset=long(h.tell())	# cast to long for 64bit Linux
            code=c[4]#.decode('latin1')
            name=(' '.join(c[5:])).decode('latin1')
        elif id==18 and int(c[3]):	# Beacon - goes in nav
            nav.append((id*10+int(c[3]), float(c[1]),float(c[2]), 0))
        elif id==19:	# Windsock - goes in nav
            nav.append((id, float(c[1]),float(c[2]), 0))
        elif id==21:	# VASI/PAPI - goes in nav
            nav.append((id*10+int(c[3]), float(c[1]),float(c[2]), float(c[4])))
        elif id==99:
            break
        elif loc:	# Don't bother parsing past first location
            pass
        elif id==10:	# Runway / taxiway
            loc = (float(c[1]),float(c[2]))
        elif id==100:	# 850 Runway
            loc = ((float(c[9])+float(c[18]))/2,(float(c[10])+float(c[19]))/2)
        elif id==101:	# 850 Water runway
            loc = ((float(c[4])+float(c[7]))/2, (float(c[5])+float(c[8]))/2)
        elif id==102:	# 850 Helipad
            loc = (float(c[2]),float(c[3]))
        elif id==14:	# tower
            loc = (float(c[1]),float(c[2]))
    if code and loc:	# No terminating 99
        airports[code]=(name,loc,offset)
    h.close()
    return (airports, nav)


# two modes of operation:
# - without offset, return all airports and navs (used for custom apt.dats)
# - with offset, just return data for airport at offset (used for global apt.dat)
def readApt(filename, offset=None):

    f2m = 0.3041	# 1 foot [m] (not accurate, but what X-Plane appears to use for old pre-850 style runways and taxiways)

    COL_UNKNOWN = (0.75,0.75,0.75)
    COL_ROAD    = (0.9, 0.9, 0.9 )
    COL_TAXI    = (0.9, 0.8, 0.2 )

    def col(code):
        return (0<=code<=9 and COL_TAXI) or (50<=code<=59 and COL_TAXI) or (20<=code<=22 and COL_ROAD) or None

    airports={}	# (name, (lat,lon), (taxiways, runways, markings)) by ICAO code
    nav=[]	# (type,lat,lon,hdg)
    firstcode=None
    h=open(filename, 'rU')
    if offset:
        h.seek(offset)
    else:
        if not h.readline().strip() in ['A','I']:
            raise AssertionError, "The apt.dat file in this package is invalid."
        while True:	# NYEXPRO has a blank line here
            c=h.readline().split()
            if c: break
        ver=c[0]
        if not ver in ['600','703','715','810','850','1000']:
            raise AssertionError, "The apt.dat file in this package is invalid."
        ver=int(ver)

    code = name = None
    loc = None		# airport location
    pavement = None
    surface = 0
    linear = None
    taxiways = []
    runways  = []
    markings = []
    for line in h:
        c=line.split()
        if not c or c[0].startswith('#'): continue
        id=int(c[0])

        if id==110:	# pavement
            surface = int(c[1])
            pavement = [surface]
            linear = []	# might have edge lines
            linearstart = None
            continue
        elif id==120:	# linear feature
            linear = []
            linearstart = None
            pavement = None
            continue

        elif pavement:
            if id==111:
                pavement.append((float(c[1]),float(c[2])))
            elif id==112:
                pavement.append((float(c[1]),float(c[2]),float(c[3]),float(c[4])))
            elif id==113:
                pavement.append((float(c[1]),float(c[2])))
                taxiways.append(pavement)
                pavement = [surface]	# holes just continue from previous pavement
            elif id==114:
                pavement.append((float(c[1]),float(c[2]),float(c[3]),float(c[4])))
                taxiways.append(pavement)
                pavement = [surface]	# holes just continue from previous pavement
            elif id==115 or id==116:
                # not allowed in pavement
                raise AssertionError, "The apt.dat file in this package is invalid."
            else:
                # something else
                pavement = linear = None

        if linear is not None:
            if id==111:
                if not linearstart: linearstart = (COL_UNKNOWN, float(c[1]),float(c[2]))
                color = len(c)>=4 and col(float(c[3]))
                if color:
                    linear.append((color, float(c[1]),float(c[2])))
                elif linear:
                    linear.append((COL_UNKNOWN, float(c[1]),float(c[2])))
                    # skip this segment and start a new line
                    markings.append(linear)
                    linear = []
            elif id==112:
                if not linearstart: linearstart = (COL_UNKNOWN, float(c[1]),float(c[2]),float(c[3]),float(c[4]))
                color = len(c)>=6 and col(float(c[5]))
                if color:
                    linear.append((color, float(c[1]),float(c[2]),float(c[3]),float(c[4])))
                elif linear:
                    linear.append((COL_UNKNOWN, float(c[1]),float(c[2]),float(c[3]),float(c[4])))
                    # skip this segment and start a new line
                    markings.append(linear)
                    linear = []
            elif id==113:
                color = len(c)>=4 and col(float(c[3]))
                if color:
                    linear.append((color, float(c[1]),float(c[2])))
                    if linearstart: linear.append(linearstart)	# duplicate first node to close line
                    markings.append(linear)
                elif linear:
                    linear.append((COL_UNKNOWN, float(c[1]),float(c[2])))
                    markings.append(linear)
                if pavement:		# holes just continue from previous pavement
                    linear = []
                    linearstart = None
                else:
                    linear = None
            elif id==114:
                color = len(c)>=6 and col(float(c[5]))
                if color:
                    linear.append((color, float(c[1]),float(c[2]),float(c[3]),float(c[4])))
                    if linearstart: linear.append(linearstart)	# duplicate first node to close line
                    markings.append(linear)
                elif linear:
                    linear.append((COL_UNKNOWN, float(c[1]),float(c[2]),float(c[3]),float(c[4])))
                    markings.append(linear)
                if pavement:		# holes just continue from previous pavement
                    linear = []
                    linearstart = None
                else:
                    linear = None
            elif id==115:
                if linear:
                    linear.append((COL_UNKNOWN, float(c[1]),float(c[2])))
                    markings.append(linear)
                linear = None
            elif id==116:
                if linear:
                    linear.append((COL_UNKNOWN, float(c[1]),float(c[2]),float(c[3]),float(c[4])))
                    markings.append(linear)
                linear = None
            else:
                # not allowed anything else
                raise AssertionError, "The apt.dat file in this package is invalid."

        elif id in [1,16,17]:		# Airport/Seaport/Heliport
            if offset:	# reached next airport
                if not runways: raise AssertionError, "Airport %s does not have any runways." % code
                h.close()
                return (taxiways, runways, markings)
            if code:
                if code in airports:
                    if loc: raise AssertionError, "Airport %s is listed more than once." % code
                elif not runways:
                    raise AssertionError, "Airport %s does not have any runways." % code
                else:
                    airports[code] = (name, loc, (taxiways, runways, markings))
                code=name=loc=None
                taxiways = []
                runways  = []
                markings = []
            code=c[4].decode('latin1')
            if not firstcode: firstcode=code
            name=(' '.join(c[5:])).decode('latin1')

        elif id==10:	# Old-style runway / taxiway / helipad
            # see 100 or 102 for output format
            lat=float(c[1])
            lon=float(c[2])
            if not loc: loc = (lat,lon)
            istaxiway = c[3]=='xxx'
            ishelipad = c[3][0]=='H'
            stop=c[7].split('.')
            if len(stop)<2: stop.append(0)
            if len(c)<11:
                surface=int(c[9])/1000000	# v6
            else:
                surface=int(c[10])		# v7
            if len(c)<12:
                shoulder=0
            else:
                shoulder=int(c[11])
            if ishelipad:
                runways.append( (lat, lon, float(c[4]), f2m*float(c[5]),f2m*float(c[8]), f2m*float(stop[0]), f2m*float(stop[1]), surface-5, shoulder, True))
            elif istaxiway:
                taxiways.append((lat, lon, float(c[4]), f2m*float(c[5]),f2m*float(c[8]), f2m*float(stop[0]), f2m*float(stop[1]), surface, shoulder, False))
            else:
                runways.append( (lat, lon, float(c[4]), f2m*float(c[5]),f2m*float(c[8]), f2m*float(stop[0]), f2m*float(stop[1]), surface, shoulder, False))
        elif id==100 or id==101:	# 850 Runway
            # ((lat1,lon1),(lat2,lon2),width,stop1,stop2,surface,shoulder)
            if id==100:
                (lat1,lon1,lat2,lon2,width,stop1,stop2,surface,shoulder) = (float(c[9]), float(c[10]), float(c[18]), float(c[19]), float(c[1]), float(c[12]),float(c[21]), int(c[2]), int(c[3]))
            else:
                (lat1,lon1,lat2,lon2,width,stop1,stop2,surface,shoulder) = (float(c[4]), float(c[5]), float(c[7]), float(c[8]), float(c[1]), 0,0, 13, 0)
            if not loc: loc = ((lat1+lat2)/2, (lon1+lon2)/2)
            runways.append(((lat1,lon1),(lat2,lon2),width,stop1,stop2,surface,shoulder))
        elif id==102:	# 850 Helipad
            # (lat,lon,h,length,width,stop1,stop2,surface,shoulder,ishelipad)
            lat=float(c[2])
            lon=float(c[3])
            if not loc: loc = (lat,lon)
            runways.append((lat, lon, float(c[4]), float(c[5]),float(c[6]), 0,0, int(c[7]), int(c[9]), True))

        elif id==14:	# Prefer tower location
            loc = (float(c[1]),float(c[2]))
        elif id==18 and int(c[3]):	# Beacon - goes in nav
            nav.append((id*10+int(c[3]), float(c[1]),float(c[2]), 0))
        elif id==19:	# Windsock - goes in nav
            nav.append((id, float(c[1]),float(c[2]), 0))
        elif id==21:	# VASI/PAPI - goes in nav
            nav.append((id*10+int(c[3]), float(c[1]),float(c[2]), float(c[4])))
        elif id==99:
            break

    if offset:
        if not runways: raise AssertionError, "Airport %s does not have any runways." % code
        h.close()
        return (taxiways, runways, markings)
    # last one
    if code:
        if code in airports:
            if loc: raise AssertionError, "Airport %s is listed more than once." % code
        elif not runways:
            raise AssertionError, "Airport %s does not have any runways." % code
        else:
            airports[code] = (name, loc, (taxiways, runways, markings))
    else:
        raise AssertionError, "The apt.dat file in this package is empty."
    h.close()
    return (airports, nav, firstcode)


def readNav(filename):
    nav=[]	# (type,lat,lon,hdg)
    h=open(filename, 'rU')
    if not h.readline().strip() in ['A','I']:
        raise IOError
    while True:
        c=h.readline().split()
        if c: break
    ver=c[0]
    if not ver in ['740','810']:
        raise IOError
    for line in h:
        c=line.split()
        if not c: continue
        id=int(c[0])
        if id>=2 and id<=5:
            nav.append((id, float(c[1]), float(c[2]), float(c[6])))
        elif id>=6 and id<=9:	# heading ignored
            nav.append((id, float(c[1]), float(c[2]), 0))
    h.close()
    return nav


def latlon2m(centre, lat, lon):
    return(((lon-centre[1])*onedeg*cos(radians(lat)), (centre[0]-lat)*onedeg))

def aptlatlon2m(centre, lat, lon):
    # version of the above with fudge factors for runways/taxiways
    return(((lon-centre[1])*(onedeg+8)*cos(radians(lat)), (centre[0]-lat)*(onedeg-2)))

def bez3(p, mu):
    # http://paulbourke.net/geometry/bezier/
    mum1 = 1-mu
    mu2  = mu*mu
    mum12= mum1*mum1
    return (p[0][0]*mum12 + 2*p[1][0]*mum1*mu + p[2][0]*mu2, p[0][1]*mum12 + 2*p[1][1]*mum1*mu + p[2][1]*mu2)

def bez4(p, mu):
    # http://paulbourke.net/geometry/bezier/
    mum1 = 1-mu
    mu3  = mu*mu*mu
    mum13= mum1*mum1*mum1
    return (p[0][0]*mum13 + 3*p[1][0]*mu*mum1*mum1 + 3*p[2][0]*mu*mu*mum1 + p[3][0]*mu3, p[0][1]*mum13 + 3*p[1][1]*mu*mum1*mum1 + 3*p[2][1]*mu*mu*mum1 + p[3][1]*mu3)


def layoutApt(tile, aptdatfile, airports, elev):
    gc.disable()	# work round http://bugs.python.org/issue4074 on Python<2.7
    codes = []
    svarray=[]
    tvarray=[]
    rvarray=[]
    marray =[]
    centre = [tile[0]+0.5, tile[1]+0.5]
    area = BBox(tile[0]-0.05, tile[0]+1.05, tile[1]-0.05, tile[1]+1.05)	# bounding box for including airport runways & taxiways
    tile = BBox(tile[0], tile[0]+1, tile[1], tile[1]+1)			# bounding box for displaying ICAO code
    bezpts = 6	# balance between speed and quality

    for code, (name, aptloc, apt) in airports.iteritems():
        if __debug__: clock=time.clock()	# Processor time
        if not area.inside(*aptloc):
            continue
        if tile.inside(*aptloc):
            codes.append((code,aptloc))
        runways   = defaultdict(list)
        taxiways  = defaultdict(list)
        shoulders = defaultdict(list)
        markings  = []
        thisarea=BBox()
        if isinstance(apt, long):
            # default airport
            try:
                (apttaxiways, aptrunways, aptmarkings) = thisapt = readApt(aptdatfile, apt)
                airports[code] = (name, aptloc, thisapt)
            except:
                if __debug__: print_exc()
                continue	# ignore errors in default airports
        else:
            (apttaxiways, aptrunways, aptmarkings) = apt

        # runways
        for thing in aptrunways:
            if not isinstance(thing[0], tuple):
                # old pre-850 style runway or 850 style helipad
                (lat,lon,h,length,width,stop1,stop2,surface,shoulder,ishelipad) = thing
                (cx,cz) = aptlatlon2m(centre, lat,lon)
                length1 = length/2+stop1
                length2 = length/2+stop2
                h = radians(h)
                coshdg = cos(h)
                sinhdg = sin(h)
                p1 = [cx-length1*sinhdg, cz+length1*coshdg]
                p2 = [cx+length2*sinhdg, cz-length2*coshdg]
                xinc = width/2*coshdg
                zinc = width/2*sinhdg
                if ishelipad:
                    # Don't drape helipads, of which there are loads
                    if tile.inside(lat,lon):
                        col = surfaces.get(surface, surfaces[0]) + [0]
                        rvarray.extend(array([[p2[0]+xinc, elev.height(p2[0]+xinc, p2[1]+zinc), p2[1]+zinc] + col,
                                              [p2[0]-xinc, elev.height(p2[0]-xinc, p2[1]-zinc), p2[1]-zinc] + col,
                                              [p1[0]+xinc, elev.height(p1[0]+xinc, p1[1]+zinc), p1[1]+zinc] + col,
                                              [p2[0]-xinc, elev.height(p2[0]-xinc, p2[1]-zinc), p2[1]-zinc] + col,
                                              [p1[0]-xinc, elev.height(p1[0]-xinc, p1[1]-zinc), p1[1]-zinc] + col,
                                              [p1[0]+xinc, elev.height(p1[0]+xinc, p1[1]+zinc), p1[1]+zinc] + col], float32))
                        continue
            else:
                # new 850 style runway
                ((lat1,lon1),(lat2,lon2),width,stop1,stop2,surface,shoulder)=thing
                (x1,z1) = latlon2m(centre, lat1, lon1)
                (x2,z2) = latlon2m(centre, lat2, lon2)
                h = -atan2(x1-x2,z1-z2)
                coshdg = cos(h)
                sinhdg = sin(h)
                p1 = [x1-stop1*sinhdg, z1+stop1*coshdg]
                p2 = [x2+stop2*sinhdg, z2-stop2*coshdg]
                xinc = width/2*coshdg
                zinc = width/2*sinhdg
            newthing = [[p2[0]+xinc, elev.height(p2[0]+xinc, p2[1]+zinc), p2[1]+zinc],
                        [p2[0]-xinc, elev.height(p2[0]-xinc, p2[1]-zinc), p2[1]-zinc],
                        [p1[0]-xinc, elev.height(p1[0]-xinc, p1[1]-zinc), p1[1]-zinc],
                        [p1[0]+xinc, elev.height(p1[0]+xinc, p1[1]+zinc), p1[1]+zinc]]
            runways[surface].append(newthing)
            if shoulder:
                xinc = width*0.75*coshdg
                zinc = width*0.75*sinhdg
                newthing = [[p2[0]+xinc, elev.height(p2[0]+xinc, p2[1]+zinc), p2[1]+zinc],
                            [p2[0]-xinc, elev.height(p2[0]-xinc, p2[1]-zinc), p2[1]-zinc],
                            [p1[0]-xinc, elev.height(p1[0]-xinc, p1[1]-zinc), p1[1]-zinc],
                            [p1[0]+xinc, elev.height(p1[0]+xinc, p1[1]+zinc), p1[1]+zinc]]
                shoulders[shoulder].append(newthing)
            for (x,y,z) in newthing:	# outer winding of runway or shoulder (if any)
                thisarea.include(x,z)

        # taxiways
        for thing in reversed(apttaxiways):	# draw in reverse order for some reason that I can't now remember
            if isinstance(thing, tuple):
                # old pre-850 style taxiway
                (lat,lon,h,length,width,stop1,stop2,surface,shoulder,ishelipad) = thing
                assert not shoulder		# shoulders only apply to runways
                assert not ishelipad		# should be in aptrunways
                (cx,cz) = aptlatlon2m(centre, lat,lon)
                length1 = length/2+stop1
                length2 = length/2+stop2
                h = radians(h)
                coshdg = cos(h)
                sinhdg = sin(h)
                p1 = [cx-length1*sinhdg, cz+length1*coshdg]
                p2 = [cx+length2*sinhdg, cz-length2*coshdg]
                xinc = width/2*coshdg
                zinc = width/2*sinhdg
                newthing = [[p2[0]+xinc, elev.height(p2[0]+xinc, p2[1]+zinc), p2[1]+zinc],
                            [p2[0]-xinc, elev.height(p2[0]-xinc, p2[1]-zinc), p2[1]-zinc],
                            [p1[0]-xinc, elev.height(p1[0]-xinc, p1[1]-zinc), p1[1]-zinc],
                            [p1[0]+xinc, elev.height(p1[0]+xinc, p1[1]+zinc), p1[1]+zinc]]
            else:
                # new 850 style taxiway
                surface = thing[0]
                thing = thing[1:]
                n = len(thing)
                newthing = []
                for j in range(n):
                    pt = thing[j]
                    nxt = thing[(j+1) % n]
                    if pt[0]==nxt[0] and pt[1]==nxt[1]: continue	# duplicated point - probably split bezier
                    ptloc = (x,z) = latlon2m(centre, pt[0],pt[1])
                    thisarea.include(x,z)
                    newthing.append([x, elev.height(x,z), z])
                    if len(pt)<4:
                        if len(nxt)>=4:
                            nxtloc = latlon2m(centre, nxt[0], nxt[1])
                            nxtbez = latlon2m(centre, nxt[0]*2-nxt[2],nxt[1]*2-nxt[3])
                            for u in range(1,bezpts):
                                (bx,bz) = bez3([ptloc, nxtbez, nxtloc], float(u)/bezpts)
                                thisarea.include(bx,bz)
                                newthing.append([bx, elev.height(bx,bz), bz])
                    else:
                        bezloc = latlon2m(centre, pt[2], pt[3])
                        nxtloc = latlon2m(centre, nxt[0], nxt[1])
                        if len(nxt)>=4:
                            nxtbez = latlon2m(centre, nxt[0]*2-nxt[2],nxt[1]*2-nxt[3])
                            for u in range(1,bezpts):
                                (bx,bz) = bez4([ptloc, bezloc, nxtbez, nxtloc], float(u)/bezpts)
                                thisarea.include(bx,bz)
                                newthing.append([bx, elev.height(bx,bz), bz])
                        else:
                            for u in range(1,bezpts):
                                (bx,bz) = bez3([ptloc, bezloc, nxtloc], float(u)/bezpts)
                                thisarea.include(bx,bz)
                                newthing.append([bx, elev.height(bx,bz), bz])
            taxiways[surface].append(newthing)
            for (x,y,z) in newthing:
                thisarea.include(x,z)

        # markings
        for thing in aptmarkings:
            newthing = []
            color = [0,0,0]
            n = len(thing)
            for j in range(n-1):
                pt = thing[j][1:]
                nxt = thing[j+1][1:]
                if pt[0]==nxt[0] and pt[1]==nxt[1]: continue	# duplicated point - probably split bezier
                ptloc = (x,z) = latlon2m(centre, pt[0],pt[1])
                newthing.append([x, elev.height(x,z), z] + color)
                color = list(thing[j][0])	# X-Plane specifies color on first node of each line, but OpenGL uses second node
                if len(pt)<4:
                    if len(nxt)>=4:
                        nxtloc = latlon2m(centre, nxt[0], nxt[1])
                        nxtbez = latlon2m(centre, nxt[0]*2-nxt[2],nxt[1]*2-nxt[3])
                        for u in range(1,bezpts):
                            (bx,bz) = bez3([ptloc, nxtbez, nxtloc], float(u)/bezpts)
                            newthing.append([bx, elev.height(bx,bz), bz] + color)
                else:
                    bezloc = latlon2m(centre, pt[2], pt[3])
                    nxtloc = latlon2m(centre, nxt[0], nxt[1])
                    if len(nxt)>=4:
                        nxtbez = latlon2m(centre, nxt[0]*2-nxt[2],nxt[1]*2-nxt[3])
                        for u in range(1,bezpts):
                            (bx,bz) = bez4([ptloc, bezloc, nxtbez, nxtloc], float(u)/bezpts)
                            newthing.append([bx, elev.height(bx,bz), bz] + color)
                    else:
                        for u in range(1,bezpts):
                            (bx,bz) = bez3([ptloc, bezloc, nxtloc], float(u)/bezpts)
                            newthing.append([bx, elev.height(bx,bz), bz] + color)
            # last one
            pt = thing[n-1][1:]
            ptloc = (x,z) = latlon2m(centre, pt[0],pt[1])
            newthing.append([x, elev.height(x,z), z] + color)
            marray.append(array(newthing, float32))

        if __debug__: print "%6.3f time to layout %s" % (time.clock()-clock, code)

        if not runways and not taxiways:
            continue	# didn't add anything (except helipads)

        # Find patches under this airport
        if __debug__: clock=time.clock()	# Processor time
        meshtris = elev.getbox(thisarea)

        for (kind,varray) in [(shoulders, svarray),
                              (taxiways,  tvarray),
                              (runways,   rvarray)]:
            # tessellate similar surfaces together
            for (surface, windings) in kind.iteritems():
                col = surfaces.get(surface, surfaces[0])
                varray.extend(elev.drapeapt(windings, col[0], col[1], meshtris))
        if __debug__: print "%6.3f time to tessellate %s" % (time.clock()-clock, code)

    varray=svarray+tvarray+rvarray
    shoulderlen=len(svarray)
    taxiwaylen=len(tvarray)
    runwaylen=len(rvarray)

    if marray:
        counts = array([len(chain) for chain in marray], int)	# points in each chain
        start  = cumsum(concatenate((zeros((1,), int), counts)))[:-1]
        end    = start + counts - 1
        mindices= concatenate([repeat(arange(start[i],end[i],1,GLuint), 2) for i in range(len(counts))])
        mindices[1::2] += 1
        assert (len(mindices) == (sum(counts)-len(counts))*2)
    else:
        mindices = None

    gc.enable()
    return ((varray,shoulderlen,taxiwaylen,runwaylen,marray,mindices), codes)
