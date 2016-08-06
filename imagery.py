from OpenGL.GLU import *
import PIL.Image

from email.utils import formatdate, parsedate_tz
from math import atan, cos, degrees, exp, floor, log, pi, radians, sin
from os import getenv, makedirs, unlink
from os.path import basename, exists, expanduser, isdir, join
from Queue import Queue
from sys import exit, getfilesystemencoding, platform
from tempfile import gettempdir
import threading
import time
from urllib2 import HTTPError, URLError, Request, urlopen
if __debug__:
    from traceback import print_exc

from clutter import Draped, DrapedImage, Polygon
from elevation import ElevationMeshBase
from nodes import Node
from prefs import Prefs, prefs
from version import appname, appversion


fourpi=4*pi

class Filecache:

    directory='dir.txt'
    maxage=31*24*60*60	# Max age in cache since last accessed: 1 month

    def __init__(self):
        if platform.startswith('linux'):
            # http://standards.freedesktop.org/basedir-spec/latest/ar01s03.html
            self.cachedir=(getenv('XDG_CACHE_HOME') or expanduser('~/.cache')).decode(getfilesystemencoding() or 'utf-8')
        elif platform=='darwin':
            self.cachedir=expanduser('~/Library/Caches').decode(getfilesystemencoding() or 'utf-8')
        elif platform=='win32':
            import ctypes.wintypes
            buf= ctypes.create_unicode_buffer(ctypes.wintypes.MAX_PATH)
            if not ctypes.windll.shell32.SHGetFolderPathW(0, 0x801c, 0, 0, buf):	# CSIDL_LOCAL_APPDATA
                self.cachedir=buf.value
            else:
                # can fail on 64 bit - race condition?
                self.cachedir=getenv('APPDATA', '.')
        try:
            self.cachedir=join(self.cachedir, appname)
            if not isdir(self.cachedir):
                makedirs(self.cachedir)
            open(join(self.cachedir, Filecache.directory), 'at').close()	# check writeable
        except:
            self.cachedir=join(gettempdir(), appname)
            if not isdir(self.cachedir):
                makedirs(self.cachedir)
            open(join(self.cachedir, Filecache.directory), 'at').close()	# check writeable

        self.files={}
        self.starttime=int(time.time())
        try:
            h=open(join(self.cachedir, Filecache.directory), 'rU')
            for line in h:
                (name, accessed, modified)=line.split()
                if self.starttime-int(accessed) > Filecache.maxage:
                    # Delete files not accessed recently
                    if exists(join(self.cachedir, name)):
                        unlink(join(self.cachedir, name))
                elif exists(join(self.cachedir, name)):
                    self.files[name]=(int(accessed), int(modified))
            h.close()
        except:
            if __debug__: print_exc()


    # Return a file from the cache if present and recent
    def get(self, name):
        now=int(time.time())
        filename=join(self.cachedir, name)
        if name in self.files:
            rec=self.files[name]
            if not rec:
                return False	# Failed to get file
            (accessed, modified)=rec
            if exists(filename) and (accessed>=self.starttime or self.starttime-modified<Filecache.maxage):
                # already accessed this session or downloaded recently - don't check again
                self.files[name]=(now, modified)
                return filename
        return None

    # Return a file from the cache, blocking to read it from a URL if necessary
    def fetch(self, name, url, minsize=0):
        now=int(time.time())
        filename=join(self.cachedir, name)
        if name in self.files:
            rec=self.files[name]
            if not rec:
                return False	# Failed to get file
            (accessed, modified)=rec
            if exists(filename):
                if accessed>=self.starttime or self.starttime-modified<Filecache.maxage:
                    # already accessed this session or downloaded recently - don't check again
                    self.files[name]=(now, modified)
                    return filename
                # http://www.w3.org/Protocols/rfc2616/rfc2616-sec14.html#sec14.25
                # However Bing often ignores this and serves anyway, so first check above whether downloaded recently
                request=Request(url, None, modified and {'If-Modified-Since': formatdate(modified,usegmt=True)} or {})
            else:
                request=Request(url)
        else:
            request=Request(url)
        request.add_header('User-Agent', '%s/%4.2f' % (appname, appversion))

        tries=3
        while tries:
            tries-=1
            try:
                h=urlopen(request)
                d=h.read()
                h.close()
                if h.info().getheader('X-VE-Tile-Info')=='no-tile':
                    # Bing serves a placeholder and adds this header if no imagery available at this resolution
                    raise HTTPError(url, 404, None, None, None)
                if int(h.info().getheader('Content-Length')) < minsize:
                    # ArcGIS doesn't give any indication that it's serving a placeholder. Assume small filesize = placeholder
                    raise HTTPError(url, 404, None, None, None)
                f=open(filename, 'wb')
                f.write(d)
                f.close()
                cachecontrol=h.info().getheader('Cache-Control')
                if not cachecontrol or 'public' in cachecontrol or 'private' in cachecontrol or ('max-age' in cachecontrol and 'no-cache' not in cachecontrol):
                    # http://www.w3.org/Protocols/rfc2616/rfc2616-sec14.html#sec14.9
                    self.files[name]=(now, now)	# just use time of request for modification time
                else:
                    self.files[name]=(now, 0)	# set modificaton time to epoch so will be re-fetched on next run
                if __debug__: self.writedir()
                return filename
            except HTTPError,e:
                if __debug__:
                    print request.get_full_url().split('&')[0], e.code
                if e.code==304:	# Not Modified
                    # http://www.w3.org/Protocols/rfc2616/rfc2616-sec10.html#sec10.3.5
                    self.files[name]=(now, modified)
                    return filename
                elif e.code/100==4:
                    # some kind of unrecoverable error
                    break
            except URLError,e:
                # Retry any other errors
                if __debug__:
                    print request.get_full_url().split('&')[0], request.headers, tries
                    print str(e)
            except:
                # Retry any other errors
                if __debug__:
                    print request.get_full_url().split('&')[0], request.headers, tries
                    print_exc()

        # Failed after retries
        self.files[name]=False
        return False


    def writedir(self):
        try:
            h=open(join(self.cachedir, Filecache.directory), 'wt')
            for name, rec in sorted(self.files.items()):
                if rec:
                    (accessed, modified)=rec
                    h.write('%s\t%d\t%d\n' % (name, accessed, modified))
            h.close()
        except:
            # silently fail
            if __debug__: print_exc()

class Imagery:

    # Number of simultaneous connections to imagery provider and concurrent placement layouts.
    # Limit to 1 to prevent worker threads slowing UI too much.
    connections=1	

    def __init__(self, canvas):

        self.providers = { None     : self.null_setup,
                           'Bing'   : self.bing_setup,
                           'ArcGIS' : self.arcgis_setup,
                           'Mapbox' : self.mb_setup,
        }
        self.providers[None]()
        self.canvas=canvas
        self.placementcache={}	# previously created placements from this provider (or None if image couldn't be loaded),
                                # indexed by (x, y, level). Placement may not yet have been allocated into VBO or image loaded.
        self.placementactive=[]	# active placements
        self.tile=(0,999)	# X-Plane 1x1degree tile - [lat,lon] of SW
        self.loc=None
        self.dist=0

        self.filecache=Filecache()

        # Setup a pool of worker threads
        self.workers=[]
        self.q = Queue()
        for i in range(Imagery.connections):
            t=threading.Thread(target=self.worker)
            t.daemon=True	# this doesn't appear to work for threads blocked on Queue
            t.start()
            self.workers.append(t)


    def null_setup(self):
        self.imageryprovider = None
        self.provider_base = None
        self.provider_url = None
        self.provider_logo = None	# (filename, width, height)
        self.provider_levelmin = 0
        self.provider_levelmax = 0
        self.provider_tilesize = 0


    # Worker thread
    def worker(self):
        # Each thread gets its own tessellators in thread-local storage
        tls=threading.local()
        tls.tess=gluNewTess()
        gluTessNormal(tls.tess, 0, -1, 0)
        gluTessProperty(tls.tess, GLU_TESS_WINDING_RULE, GLU_TESS_WINDING_NEGATIVE)
        gluTessCallback(tls.tess, GLU_TESS_VERTEX_DATA,  ElevationMeshBase.tessvertex)
        gluTessCallback(tls.tess, GLU_TESS_EDGE_FLAG,    ElevationMeshBase.tessedge)
        tls.csgt=gluNewTess()
        gluTessNormal(tls.csgt, 0, -1, 0)
        gluTessProperty(tls.csgt, GLU_TESS_WINDING_RULE, GLU_TESS_WINDING_ABS_GEQ_TWO)
        gluTessCallback(tls.csgt, GLU_TESS_VERTEX_DATA,  ElevationMeshBase.tessvertex)
        gluTessCallback(tls.csgt, GLU_TESS_COMBINE,      ElevationMeshBase.tesscombinetris)
        gluTessCallback(tls.csgt, GLU_TESS_EDGE_FLAG,    ElevationMeshBase.tessedge)

        while True:
            args = self.q.get()
            if not args: exit()	# Die!
            self.initplacement(tls, *args)
            self.q.task_done()


    def drain(self):
        try:
            while True:
                self.q.get(False)
                self.q.task_done()
        except:
            pass

    # Closing down
    def exit(self):
        self.drain()
        self.filecache.writedir()
	# kill workers
        for i in range(Imagery.connections):
            self.q.put(None)
        # wait for them
        for t in self.workers:
            t.join()


    def reset(self):
        # Called on reload or on new tile. Empty the cache and forget allocations since:
        # a) in the case of reload, textures have been dropped and so would need to be reloaded anyway;
        # b) try to limit cluttering up the VBO with allocations we may not need again;
        # c) images by straddle multiple tiles and these would need to be recalculated anyway.
        self.drain()
        for placement in self.placementcache.itervalues():
            if placement: placement.clearlayout()
        self.placementcache={}


    def goto(self, loc, dist, screensize):

        if self.imageryprovider != prefs.imageryprovider:
            self.imageryprovider = prefs.imageryprovider in self.providers and prefs.imageryprovider or None
            self.providers[self.imageryprovider]()	# setup
            self.reset()

        newtile=(int(floor(loc[0])),int(floor(loc[1])))
        if self.tile != newtile:
            # New tile - drop cache of Clutter
            self.tile = newtile
            self.reset()

        self.loc=loc
        self.placements(dist, screensize)	# Kick off any image loading


    # Return placements to be drawn. May allocate into vertexcache as a side effect.
    def placements(self, dist, screensize):

        if screensize.width<=0 or not self.loc or not (int(self.loc[0]) or int(self.loc[1])) or not self.provider_url:
            return []	# Don't do anything on startup. Can't do anything without a valid provider.

        # layout assumes mesh loaded
        assert (int(floor(self.loc[0])),int(floor(self.loc[1])),prefs.options&Prefs.ELEVATION) in self.canvas.vertexcache.elevation, '%s %s' % ((int(floor(self.loc[0])),int(floor(self.loc[1])),prefs.options&Prefs.ELEVATION), self.canvas.vertexcache.elevation.keys())

        # http://msdn.microsoft.com/en-us/library/bb259689.aspx
        # http://wiki.openstreetmap.org/wiki/Slippy_map_tilenames#Resolution_and_Scale
        width=dist+dist				# Width in m of screen (from glOrtho setup)
        ppm=screensize.width/width		# Pixels on screen required by 1 metre, ignoring tilt
        levelmin = max(self.provider_tilesize / 256 + (prefs.options&Prefs.ELEVATION and 11 or 9), self.provider_levelmin)	# arbitrary - tessellating out at higher levels takes too long
        level0mpp = 2 * pi * 6378137 / self.provider_tilesize  	# metres per pixel at level 0
        desired = int(round(log(ppm*level0mpp*cos(radians(self.loc[0])), 2)))	# zoom level required
        actual = max(min(desired, self.provider_levelmax), levelmin + 1)

        # ntiles = 2**desired					# number of tiles per axis at this level
        # mpp = cos(radians(self.loc[0]))*level0mpp/ntiles	# actual resolution at this level
        # coverage=width/(self.provider_tilesize * mpp)		# how many tiles to cover screen width - in practice varies between ~2.4 and ~4.8

        (cx, cy) = self.latlon2xy(self.loc[0], self.loc[1], actual)	# centre tile
        if __debug__: print "Desire imagery level", desired, actual, cx, cy

        # Display what we already have available

        placements = []
        level2 = actual - 1
        for (x2, y2) in self.zoomout2x2(cx, cy):
            # prefer desired resolution if available around the centre
            if actual > desired:
                fail1 = True	# we're already at higher resolution than we'd like to be
            else:
                fail1 = False	# Do we have any missing?
                for (x1, y1) in [(0, 0), (0, 1), (1, 0), (1, 1)]:
                    placement = self.getplacement(x2*2 + x1, y2*2 + y1, actual, False)
                    if placement and placement.islaidout():
                        placements.append(placement)
                    else:
                        fail1 = True
            if fail1:
                placement = self.getplacement(x2, y2, level2, False)
                if placement and placement.islaidout():
                    placements.insert(0, placement)	# Insert at start so drawn under desired level

        for (x2, y2) in self.margin4x4(cx, cy):
            placement = self.getplacement(x2, y2, level2, False)
            if placement and placement.islaidout():
                placements.append(placement)

        # Abandon any un-started fetches
        self.drain()

        # Initiate fetches in priority order
        # Relies on having only one worker thread, so doesn't matter if a placement being processed is re-added

        fail2 = True	# did we fail to get anything at the zoomed-out level?
        for (x2, y2) in self.zoomout2x2(cx, cy):
            if self.getplacement(x2, y2, level2, True):
                fail2 = False
        for (x2, y2) in self.margin4x4(cx, cy):
            self.getplacement(x2, y2, level2, True)
        if actual <= desired:
            for (x1,y1) in self.square4x4(cx, cy):
                self.getplacement(x1, y1, actual, True)

        # No imagery available at all zoomed out. Go up again and get 2x2 tiles around the centre tile.
        while fail2 and level2 > levelmin:
            level2 -= 1
            cx /= 2
            cy /= 2
            for (x2, y2) in self.zoomout2x2(cx, cy):
                placement = self.getplacement(x2, y2, level2, True)
                if placement:
                    fail2 = False		# Some imagery may be available at this level
                    if placement.islaidout():
                        placements.insert(0, placement)

        if __debug__:
            if level2 < actual-1: print "Actual imagery level", level2

        for placement in self.placementactive:
            if placement not in placements:
                placement.flush()			# keep layout in case we need it again but deallocate from VBO to remove from drawing
        for placement in placements:
            assert placement.islaidout(), placement	# should only see laid-out (but not necessarily allocated) placements
            if placement.base is None:
                placement.layout(self.tile)		# allocate
        self.placementactive = placements

        return bool(placements)


    # Returns the 4 tiles that take up the space of a zoomed out tile in priority order
    def square2x2(self, x, y):
        ox = x + (x % 2 and -1 or 1)
        oy = y + (y % 2 and -1 or 1)
        return [(x, y), (x, oy), (ox, y), (ox, oy)]

    # Returns the 16 adjacent tiles in priority order
    def square4x4(self, x, y):
        ox = x + (x % 2 or -1)
        oy = y + (y % 2 or -1)
        return self.square2x2(x, y) + self.square2x2(x, oy) + self.square2x2(ox, y) + self.square2x2(ox, oy)

    # Returns the 4 adjacent zoomed out tiles in priority order
    def zoomout2x2(self, x, y):
        (x2, y2) = (x/2, y/2)	# zoomed out
        ox = x2 + (x % 2 or -1)
        oy = y2 + (y % 2 or -1)
        return [(x2, y2), (x2, oy), (ox, y2), (ox, oy)]

    # Returns the 12 next adjacent zoomed out tiles in priority order
    def margin4x4(self, x, y):
        (x2, y2) = (x/2, y/2)	# zoomed out
        bx = x2 + (x % 2 and -1 or -2)
        by = y2 + (y % 2 and -1 or -2)
        return [(bx+1, by), (bx+2, by), (bx+3, by+1), (bx+3, by+2), (bx+2, by+3), (bx+1, by+3), (bx, by+2), (bx, by+1),
                (bx, by), (bx+3, by), (bx+3, by+3), (bx, by+3)]	# corners

    # Returns the 16 adjacent zoomed out tiles in priority order
    def zoomout4x4(self, x, y):
        (x2, y2) = (x/2, y/2)	# zoomed out
        ox = x % 2 and -1 or -2
        oy = y % 2 and -1 or -2
        delta = [(0,0),					# centre
                 (0,-1), (1,0), (0,1), (-1,0),		# plus
                 (-1,-1), (1,-1), (1,1), (-1,1),
                 (0, oy), (ox, 0),			# adjacent
                 (1, oy), (-1, oy), (ox, 1), (ox, -1),
                 (ox,oy)]				# far corner
        return [(x2 + dx, y2 + dy) for (dx, dy) in delta]


    # Returns a laid-out but not allocated placement if possible, or not laid-out if image is still loading, or None if not available.
    def getplacement(self,x,y,level,fetch):

        key = (x, y, level)
        if key in self.placementcache:
            # Already created
            placement = self.placementcache[key]

            # Load it if it's not loaded but is ready to be
            if placement and not placement.islaidout() and Polygon.islaidout(placement):
                try:
                    (name, url, minsize) = self.provider_url(*key)
                    assert self.filecache.get(name)	# shouldn't have created a placement if couldn't load the image for it
                    if __debug__: clock=time.clock()
                    placement.definition.texture = self.canvas.vertexcache.texcache.get(self.filecache.get(name), wrap=False, downsample=False, fixsize=True)
                    if __debug__: print "%6.3f time in imagery load   for %s" % (time.clock()-clock, placement.name)
                    assert placement.islaidout()
                except:
                    # Some failure - perhaps corrupted image?
                    if __debug__: print_exc()
                    placement.clearlayout()
                    placement = None
                    self.placementcache[(x, y, level)] = None
            return placement

        elif fetch:
            # Initiate fetch of image and do layout. Prioritise more detail.
            # We could choose  do this automatically if the image file is available, but we don't since layout is expensive.
            self.q.put((x, y, level))

        return None


    def latlon2xy(self, lat, lon, level):
        ntiles=2**level				# number of tiles per axis at this level
        sinlat=sin(radians(lat))
        x = int((lon+180) * ntiles/360.0)
        y = int( (0.5 - (log((1+sinlat)/(1-sinlat)) / fourpi)) * ntiles)
        return (x,y)


    def xy2latlon(self, x, y, level):
        ntiles=float(2**level)			# number of tiles per axis at this level
        lat = 90 - 360 * atan(exp((y/ntiles-0.5)*2*pi)) / pi
        lon = x*360.0/ntiles - 180
        return (lat,lon)


    def bing_quadkey(self, x, y, level):
        # http://msdn.microsoft.com/en-us/library/bb259689.aspx
        i=level
        quadkey=''
        while i>0:
            digit=0
            mask = 1 << (i-1)
            if (x & mask):
                digit+=1
            if (y & mask):
                digit+=2
            quadkey+=('%d' % digit)
            i-=1
        url=self.provider_base % quadkey
        name=basename(url).split('?')[0]
        return (name, url, 0)


    # Called in worker thread - don't do anything fancy since main body of code is not thread-safe
    def bing_setup(self):
        try:
            key='AhATjCXv4Sb-i_YKsa_8lF4DtHwVoicFxl0Stc9QiXZNywFbI2rajKZCsLFIMOX2'
            h=urlopen('http://dev.virtualearth.net/REST/v1/Imagery/Metadata/Aerial?key=%s' % key)
            d=h.read()
            h.close()
            info=json_decode(d)
            # http://msdn.microsoft.com/en-us/library/ff701707.aspx
            if 'authenticationResultCode' not in info or info['authenticationResultCode']!='ValidCredentials' or 'statusCode' not in info or info['statusCode']!=200:
                return
            res=info['resourceSets'][0]['resources'][0]
            # http://msdn.microsoft.com/en-us/library/ff701712.aspx
            self.provider_levelmin=int(res['zoomMin'])
            self.provider_levelmax=int(res['zoomMax'])
            assert int(res['imageWidth']) == int(res['imageHeight']), (res['imageWidth'], res['imageHeight'])
            self.provider_tilesize = int(res['imageWidth'])
            self.provider_base=res['imageUrl'].replace('{subdomain}',res['imageUrlSubdomains'][-1]).replace('{culture}','en').replace('{quadkey}','%s') + '&key=' + key	# was random.choice(res['imageUrlSubdomains']) but always picking the same server seems to give better caching
            self.provider_url=self.bing_quadkey
            if info['brandLogoUri']:
                filename=self.filecache.fetch(basename(info['brandLogoUri']), info['brandLogoUri'])
                if filename:
                    image = PIL.Image.open(filename)	# yuck. but at least open is lazy
                    self.provider_logo=(filename,image.size[0],image.size[1])
        except:
            if __debug__: print_exc()
            self.null_setup()
        self.canvas.Refresh()	# Might have been waiting on this to get imagery


    def arcgis_url(self, x, y, level):
        url=self.provider_base % ("%d/%d/%d" % (level, y, x))
        name="arcgis_%d_%d_%d.jpeg" % (level, y, x)
        return (name, url, 2560)	# Sends an unhelpful JPEG if imagery not available at this level

    # Called in worker thread - don't do anything fancy since main body of code is not thread-safe
    def arcgis_setup(self):
        try:
            h=urlopen('http://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer?f=json')
            d=h.read()
            h.close()
            info=json_decode(d)
            # http://resources.arcgis.com/en/help/rest/apiref/index.html
            # http://resources.arcgis.com/en/help/rest/apiref/mapserver.html
            self.provider_levelmin=min([lod['level'] for lod in info['tileInfo']['lods']])
            self.provider_levelmax=max([lod['level'] for lod in info['tileInfo']['lods']])
            self.provider_tilesize = 256
            self.provider_base='http://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/%s'
            self.provider_url=self.arcgis_url
            filename=self.filecache.fetch('logo-med.png', 'http://serverapi.arcgisonline.com/jsapi/arcgis/2.8/images/map/logo-med.png')
            if filename:
                image = PIL.Image.open(filename)	# yuck. but at least open is lazy
                self.provider_logo=(filename,image.size[0],image.size[1])
        except:
            if __debug__: print_exc()
            self.null_setup()
        self.canvas.Refresh()	# Might have been waiting on this to get imagery


    def mb_url(self, x, y, level):
        url=self.provider_base % ("%d/%d/%d" % (level, x, y))
        name="mb_%d_%d_%d.png" % (level, x, y)
        return (name, url, 0)

    # Called in worker thread - don't do anything fancy since main body of code is not thread-safe
    def mb_setup(self):
        # http://developer.mapquest.com/web/products/open/map
        try:
            self.provider_levelmin = 0
            self.provider_levelmax = 20
            self.provider_tilesize = 512
            self.provider_base='https://api.mapbox.com/styles/v1/mapbox/outdoors-v9/tiles/%s?access_token=pk.eyJ1IjoibWFyZ2luYWwiLCJhIjoiY2lyZTl2M2xjMDAwNGlsbTM4aXp0d243aSJ9.SK1DCngwVZhvlP4CLAyz6A'
            self.provider_url=self.mb_url
            filename=self.filecache.fetch('mapbox.ico', 'https://www.mapbox.com/img/favicon.ico')
            if filename:
                image = PIL.Image.open(filename)	# yuck. but at least open is lazy
                self.provider_logo=(filename,image.size[0],image.size[1])
        except:
            if __debug__: print_exc()
            self.null_setup()
        self.canvas.Refresh()	# Might have been waiting on this to get imagery


    # Called in worker thread - fetches image and does placement layout (which uses it's own tessellator and so is thread-safe).
    # don't do anything fancy since main body of code is not thread-safe
    def initplacement(self, tls, x, y, level):

        key = (x, y, level)
        if key in self.placementcache:
            return self.placementcache[key]	# was created while this task was queued

        (name, url, minsize) = self.provider_url(*key)
        filename = self.filecache.fetch(name, url, minsize)
        if not filename:
            self.placementcache[key] = None	# Couldn't fetch image
            return None

        # Make a new placement
        (north,west) = self.xy2latlon(x, y, level)
        (south,east) = self.xy2latlon(x+1, y+1, level)
        placement = DrapedImage(name, 65535, [[Node([west, north, 0, 1]),
                                               Node([east, north, 1, 1]),
                                               Node([east, south, 1, 0]),
                                               Node([west, south, 0, 0])]])
        placement.load(self.canvas.lookup, self.canvas.defs, self.canvas.vertexcache)
        if __debug__: clock=time.clock()
        placement.layout(self.tile, tls=tls)
        if not placement.dynamic_data.size:
            if __debug__: print "DrapedImage layout failed for %s - no tris" % placement.name
            placement = None
        else:
            if __debug__: print "%6.3f time in imagery layout for %s" % (time.clock()-clock, placement.name)
            self.canvas.Refresh()	# Probably wanting to display this - will be allocated during OnPaint
        self.placementcache[key] = placement
        return


# Python 2.5 doesn't have json module, so here's a quick and dirty decoder. Doesn't santise input.
def json_decode(s):
    null=None
    true=True
    false=False
    if not s.startswith('{'): return {}
    return eval(s.decode('utf-8').replace('\/','/'))
