#!/usr/bin/python

from collections import defaultdict	# Requires Python 2.5
from glob import glob
from math import cos, floor, hypot, sin, pi, radians, sqrt
import numpy
import os	# for startfile
from os import chdir, environ, getenv, listdir, mkdir, walk
from os.path import abspath, basename, curdir, dirname, exists, expanduser, isdir, join, normpath, pardir, sep, splitext
import sys	# for path
from sys import exit, argv, executable, exc_info, platform, version_info
if __debug__:
    import time
    from traceback import print_exc

if platform.lower().startswith('linux') and not getenv("DISPLAY"):
    print "Can't run: DISPLAY is not set"
    exit(1)

# Path validation
mypath = sys.path[0]
if platform=='win32' and mypath.lower().endswith('.exe'):
    mypath = dirname(mypath)		# py2exe
elif platform=='darwin' and basename(mypath)=='MacOS':
    mypath = dirname(mypath)		# App starts in MacOS folder
    sys.path.insert(0, join(mypath, 'MacOS', '%d%d' % version_info[:2]))
    argv[0]=basename(argv[0])		# wx doesn't like non-ascii chars in argv[0]
chdir(mypath)

try:
    import wx
except:
    if __debug__: print_exc()
    import Tkinter, tkMessageBox
    Tkinter.Tk().withdraw()
    tkMessageBox.showerror("Error", "wxPython is not installed.\nThis application requires wxPython 2.8 or later.")
    exit(1)

try:
    import OpenGL
    if OpenGL.__version__ >= '3':
        # Not defined in PyOpenGL 2.x.
        import logging
        logging.basicConfig()
        if __debug__ and not platform.startswith('linux'):
            OpenGL.ERROR_ON_COPY =True	# force array conversion/flattening to be explicit
        else:
            OpenGL.ERROR_CHECKING=False	# don't check OGL errors for speed
            OpenGL.ERROR_LOGGING =False	# or log
            #OpenGL.WARN_ON_FORMAT_UNAVAILABLE = True	# For testing packaging
        if platform=='win32':
            # force for py2exe
            from OpenGL.platform import win32
        elif platform=='darwin':
            from OpenGL.platform import darwin
        import OpenGL.arrays.lists
        import OpenGL.arrays.nones
        import OpenGL.arrays.numbers
        import OpenGL.arrays.numpymodule
        import OpenGL.arrays.ctypesarrays
        import OpenGL.arrays.ctypesparameters
        import OpenGL.arrays.ctypespointers
        import OpenGL.arrays.strings
except:
    if __debug__: print_exc()
    import Tkinter, tkMessageBox
    Tkinter.Tk().withdraw()
    tkMessageBox.showerror("Error", "PyOpenGL is not installed.\nThis application\nrequires PyOpenGL 3.0.1 or later.")
    exit(1)

if not __debug__:
    import warnings
    warnings.simplefilter('ignore', DeprecationWarning)
    warnings.simplefilter('ignore', UserWarning)	# Glymur uses this
    if hasattr(wx,'wxPyDeprecationWarning'):
        warnings.simplefilter('ignore', wx.wxPyDeprecationWarning)
    wx.Log.SetLogLevel(wx.LOG_Error)	# wx warnings are seldom helpful
    numpy.seterr(all='ignore', divide='raise')	# default settings vary between numpy versions
else:
    numpy.seterr(all='raise')

if not 'startfile' in dir(os):
    import types
    # Causes problems under py2exe & not needed
    from urllib import quote
    import webbrowser

from apt import scanApt, readApt, readNav
from clutter import Clutter, Polygon, Exclude	# for loading exclusions into palette
from clutterdef import ClutterDef, ObjectDef, PolygonDef, KnownDefs, ExcludeDef, NetworkDef
from draw import MyGL
from elevation import minres, round2res, ElevationMesh
from files import readLib, readNet, sortfolded
from importobjs import doimport
from lock import LockDialog
from palette import Palette, PaletteEntry
from DSFLib import readDSF, writeDSF
from MessageBox import myCreateStdDialogButtonSizer, myMessageBox, AboutBox
from prefs import Prefs, prefs, gcustom, gglobal, gdefault, glibrary, gaptdat, gmain8aptdat, gmain9aptdat, gnavdata, gmain8navdat, gmain9navdat
from version import appname, appversion

# constants
zoom2=sqrt(2)
zoom=sqrt(zoom2)
maxzoom=32768*zoom2
if platform=='darwin':
    # Trackpad on Mac sends lots of messages so zoom less.
    # Can't tell if user is using an external mouse with scroll wheel (GetWheelDelta() is unhelpful).
    mousezoom2 = sqrt(sqrt(zoom2))
    mousezoom  = sqrt(mousezoom2)
else:
    mousezoom2 = zoom2
    mousezoom  = zoom


if platform=='darwin':
    # Hack: wxMac 2.5 requires the following to get shadows to look OK:
    # ... wx.ALIGN_CENTER_VERTICAL|wx.TOP|wx.BOTTOM, 2)
    pad=3
    browse="Choose..."
else:
    pad=3
    browse="Browse..."


class myListBox(wx.VListBox):
    # regular ListBox is too slow to create esp on wxMac 2.5
    def __init__(self, parent, id, style=0, choices=[]):

        self.height=self.indent=1	# need something
        self.choices=choices
        self.actfg = platform=='darwin' and wx.Colour(255,255,255) or wx.SystemSettings_GetColour(wx.SYS_COLOUR_HIGHLIGHTTEXT)
        self.inafg = wx.SystemSettings_GetColour(wx.SYS_COLOUR_WINDOWTEXT)
        self.hasfocus = False
        if platform=='win32' or platform.startswith('linux'):
            self.font=wx.SystemSettings_GetFont(wx.SYS_DEFAULT_GUI_FONT)
        else:
            self.font=None	# default font is OK on wxMac 2.5

        wx.VListBox.__init__(self, parent, id, style=style)

        (x,self.height)=self.GetTextExtent("M")
        self.indent=self.height/2	# Compromise between Mac & Windows
        self.SetItemCount(len(choices))
        self.sel=''
        self.timer=wx.Timer(self, wx.ID_ANY)
        wx.EVT_SET_FOCUS(self, self.OnSetFocus)
        wx.EVT_KILL_FOCUS(self, self.OnKillFocus)
        wx.EVT_CHAR(self, self.OnChar)
        if platform!='win32':	# Nav handled natively in 2.6
            wx.EVT_KEY_DOWN(self, self.OnKeyDown)
        wx.EVT_TIMER(self, self.timer.GetId(), self.OnTimer)

    def OnSetFocus(self, event):
        self.timer.Stop()
        self.sel=''
        self.hasfocus = True
        sel=self.GetSelection()
        if sel>=0: self.RefreshLine(sel)
        
    def OnKillFocus(self, event):
        self.timer.Stop()
        self.sel=''
        self.hasfocus = False
        sel=self.GetSelection()
        if sel>=0: self.RefreshLine(sel)

    def GetStringSelection(self):
        sel=self.GetSelection()
        if sel<0:
            return None
        else:
            return self.choices[sel]

    def OnMeasureItem(self, n):
        return self.height

    def OnDrawItem(self, dc, rect, n):
        if self.font: dc.SetFont(self.font)	# wtf?
        dc.SetTextForeground(self.hasfocus and self.GetSelection()==n and self.actfg or self.inafg)
        dc.DrawText(self.choices[n], rect.x+self.indent, rect.y)

    def OnDrawBackground(self, dc, rect, n):
        # override default so drawn with correct color on Mac and Linux
        if self.GetSelection()==n:
            wx.RendererNative.Get().DrawItemSelectionRect(self, dc, rect, self.hasfocus and wx.CONTROL_SELECTED|wx.CONTROL_FOCUSED or wx.CONTROL_SELECTED)
        elif platform=='darwin':
            # native renderer draws unselected in bizarre color on wxMac 2.8
            wx.RendererNative.GetGeneric().DrawItemSelectionRect(self, dc, rect)
        else:
            wx.RendererNative.Get().DrawItemSelectionRect(self, dc, rect)

    def OnKeyDown(self, event):
        # wxMac 2.5 doesn't handle cursor movement
        if event.GetKeyCode() in [wx.WXK_UP, wx.WXK_NUMPAD_UP] and self.GetSelection()>0:
            self.SetSelection(self.GetSelection()-1)
        elif event.GetKeyCode() in [wx.WXK_DOWN, wx.WXK_NUMPAD_DOWN] and self.GetSelection()<len(self.choices)-1:
            self.SetSelection(self.GetSelection()+1)
        elif event.GetKeyCode() in [wx.WXK_HOME, wx.WXK_NUMPAD_HOME]:
            self.SetSelection(0)
        elif event.GetKeyCode() in [wx.WXK_END, wx.WXK_NUMPAD_END]:
            self.SetSelection(len(self.choices)-1)
        elif event.GetKeyCode() in [wx.WXK_PAGEUP, wx.WXK_PRIOR, wx.WXK_NUMPAD_PAGEUP, wx.WXK_NUMPAD_PRIOR]:
            self.ScrollPages(-1)
            self.SetSelection(max(0,
                                  self.GetSelection()-self.GetClientSize().y/self.height))
        elif event.GetKeyCode() in [wx.WXK_PAGEDOWN, wx.WXK_NEXT, wx.WXK_NUMPAD_PAGEDOWN, wx.WXK_NUMPAD_NEXT]:
            self.ScrollPages(1)
            self.SetSelection(min(len(self.choices)-1,
                                  self.GetSelection()+self.GetClientSize().y/self.height))
        else:
            event.Skip()	# maybe generate char
            return
        
        # Navigation keys reset search
        self.sel=''
        self.timer.Stop()

        # Fake up a selection event
        event=wx.CommandEvent(wx.wxEVT_COMMAND_LISTBOX_SELECTED, self.GetId())
        event.SetEventObject(self)
        self.GetEventHandler().ProcessEvent(event)

        event.Skip(False)	# prevent double movement


    def OnChar(self, event):
        self.timer.Stop()
        
        c=chr(event.GetKeyCode()).lower()
        self.sel+=c
        sel=self.GetSelection()

        # Search for 1st char if search string repeats
        for i in self.sel:
            if i!=c:
                search=self.sel
                break
            else:
                search=c

        if len(self.sel)!=1 and self.choices[sel].lower().startswith(self.sel):
            pass
        elif sel>=0 and sel<len(self.choices)-1 and self.choices[sel].lower().startswith(search) and self.choices[sel+1].lower().startswith(search):
            self.SetSelection(sel+1)
        else:
            for sel in range(len(self.choices)):
                if self.choices[sel].lower().startswith(search):
                    self.SetSelection(sel)
                    break

        # Fake up a selection event
        event=wx.CommandEvent(wx.wxEVT_COMMAND_LISTBOX_SELECTED, self.GetId())
        event.SetEventObject(self)
        self.GetEventHandler().ProcessEvent(event)
        self.timer.Start(1500, True)

    def OnTimer(self, event):
        self.sel=''


class GotoDialog(wx.Dialog):

    def __init__(self, parent, airports):

        self.aptcode={}
        self.aptname={}
        for code, stuff in airports.iteritems():
            (name, loc, run)=stuff
            self.aptcode['%s - %s' % (code, name)]=loc
            self.aptname['%s - %s' % (name, code)]=loc

        wx.Dialog.__init__(self, parent, wx.ID_ANY, "Go to")
        wx.EVT_CLOSE(self, self.OnClose)

        grid1=wx.FlexGridSizer(0, 2, 0, 0)
        grid1.AddGrowableCol(1,1)
        box1 = wx.StaticBoxSizer(wx.StaticBox(self, -1, "Airports by name"),
                                 wx.VERTICAL)
        box2 = wx.StaticBoxSizer(wx.StaticBox(self, -1, "Airports by code"),
                                 wx.VERTICAL)
        box3 = wx.StaticBoxSizer(wx.StaticBox(self, -1, "Location"),
                                 wx.VERTICAL)
        choices=self.aptname.keys()
        sortfolded(choices)
        self.list1=myListBox(self,wx.ID_ANY, style=wx.LB_SINGLE, choices=choices)
        box1.Add(self.list1, 1, wx.ALL|wx.EXPAND, pad)
        grid1.Add(box1, 0, wx.TOP|wx.LEFT|wx.BOTTOM, 14) #
        (x,y)=self.list1.GetTextExtent("[H] Delray Community Hosp Emergency Helist - 48FD")	# Maybe longest string
        x+=wx.SystemSettings_GetMetric(wx.SYS_VSCROLL_X)+8
        self.list1.SetMinSize((x,16*y))
        wx.EVT_LISTBOX(self, self.list1.GetId(), self.OnName)
        wx.EVT_SET_FOCUS(self.list1, self.OnName)
        
        choices=self.aptcode.keys()
        sortfolded(choices)
        self.list2=myListBox(self,wx.ID_ANY, style=wx.LB_SINGLE,choices=choices)
        #grid1.Add(self.list2, 1, wx.ALIGN_CENTER_VERTICAL|wx.ALL|wx.EXPAND, pad)
        box2.Add(self.list2, 1, wx.ALL|wx.EXPAND, pad)
        grid1.Add(box2, 0, wx.ALL, 14) #
        self.list2.SetMinSize((x,16*y))
        wx.EVT_LISTBOX(self, self.list2.GetId(), self.OnCode)
        wx.EVT_SET_FOCUS(self.list2, self.OnCode)

        locbox=wx.GridSizer(0, 2, 6, 6)
        self.lat = wx.TextCtrl(self, -1)
        self.lon = wx.TextCtrl(self, -1)
        locbox.Add(wx.StaticText(self, -1, '  Latitude:'),  1, wx.ALIGN_CENTER_VERTICAL|wx.ALIGN_LEFT|wx.ALL, pad)
        locbox.Add(self.lat, 1, wx.BOTTOM|wx.RIGHT|wx.EXPAND, pad)
        locbox.Add(wx.StaticText(self, -1, '  Longitude:'), 1, wx.ALIGN_CENTER_VERTICAL|wx.ALIGN_LEFT|wx.ALL, pad)
        locbox.Add(self.lon, 1, wx.BOTTOM|wx.RIGHT|wx.EXPAND, pad)
        box3.Add(locbox, 1, wx.ALL|wx.EXPAND, pad)
        wx.EVT_TEXT(self, self.lat.GetId(), self.OnLoc)	# wxPython doesn't (yet) support FloatingPointValidator
        wx.EVT_TEXT(self, self.lon.GetId(), self.OnLoc)
        grid1.Add(box3, 0, wx.LEFT|wx.BOTTOM|wx.EXPAND, 14)
        
        box4=myCreateStdDialogButtonSizer(self, wx.OK|wx.CANCEL)
        self.ok=self.FindWindowById(wx.ID_OK)
        self.ok.Disable()
        wx.EVT_BUTTON(self, wx.ID_OK, self.OnClose)
        grid1.Add(box4, 1, wx.ALL|wx.ALIGN_RIGHT|wx.ALIGN_BOTTOM, 14)
        self.SetSizerAndFit(grid1)

    def OnClose(self, event):
        # Prevent kill focus event causing refresh & crash on wxMac 2.5
        # Prevent kill focus event causing EVT_LISTBOX on wxMac >= 3
        self.list1.SetSelection(-1)
        self.list2.SetSelection(-1)
        if self.IsModal(): self.EndModal(event.GetEventObject().GetId())

    def OnName(self, event):
        choice=event.GetEventObject().GetStringSelection()
        if choice:
            loc=self.aptname[choice]
            self.lat.SetValue('%11.6f' % loc[0])
            self.lon.SetValue('%11.6f' % loc[1])
            self.ok.Enable()
        event.Skip()	# Update display

    def OnCode(self, event):
        choice=event.GetEventObject().GetStringSelection()
        if choice:
            loc=self.aptcode[choice]
            self.lat.SetValue('%11.6f' % loc[0])
            self.lon.SetValue('%11.6f' % loc[1])
            self.ok.Enable()
        event.Skip()	# Update display

    def OnLoc(self, event):
        try:
            if (-90 < float(self.lat.GetValue()) < 90) and (-180 < float(self.lon.GetValue()) < 180):
                self.ok.Enable()
            else:
                self.ok.Disable()
        except:
            self.ok.Disable()

    def show(self, loc):
        self.lat.SetValue('%11.6f' % loc[0])
        self.lon.SetValue('%11.6f' % loc[1])
        self.ok.Disable()
        if self.ShowModal()!=wx.ID_OK: return None
        try:
            return (float(self.lat.GetValue()), float(self.lon.GetValue()))
        except:
            return None	# shouldn't happen


class PreferencesDialog(wx.Dialog):

    def __init__(self, parent, id, title):
        wx.Dialog.__init__(self, parent, id, title, style=wx.DEFAULT_FRAME_STYLE|wx.FRAME_FLOAT_ON_PARENT)
        if platform=='darwin':	# Default is too big on Mac
            self.SetWindowVariant(wx.WINDOW_VARIANT_SMALL)

        outersizer = wx.BoxSizer(wx.VERTICAL)	# For padding
        box0 = wx.BoxSizer(wx.VERTICAL)
        outersizer.Add(box0, 0, wx.ALL|wx.EXPAND, pad+pad)

        box1 = wx.StaticBoxSizer(wx.StaticBox(self, -1, 'X-Plane location'), wx.VERTICAL)
        box0.Add(box1, 0, wx.ALL|wx.EXPAND, pad)
        self.path = wx.TextCtrl(self, -1, style=wx.TE_READONLY)
        self.path.SetMinSize((300, -1))
        if prefs.xplane: self.path.SetValue(prefs.xplane)
        browsebtn=wx.Button(self, -1, browse)
        box1.Add(self.path, 1, wx.ALL|wx.EXPAND, 4)
        box1.Add(browsebtn, 0, wx.ALL|wx.ALIGN_RIGHT, 4)

        self.display = wx.RadioBox(self, -1, "Terrain", style=wx.VERTICAL,
                                   choices=["No terrain", "Show terrain", "Show terrain and elevation", "Show terrain and networks"])
        # "Show terrain, elevation, powerlines, railways, roads"])
        if prefs.options&Prefs.NETWORK:
            self.display.SetSelection(3)
        elif prefs.options&Prefs.ELEVATION:
            self.display.SetSelection(2)
        elif prefs.options&Prefs.TERRAIN:
            self.display.SetSelection(1)
        box0.Add(self.display, 0, wx.ALL|wx.EXPAND|wx.ALIGN_LEFT, pad)

        box2 = wx.BoxSizer()
        box0.Add(box2, 0, wx.ALL|wx.EXPAND, pad)
        self.latlon = wx.RadioBox(self, -1, "Latitude && Longitude", style=wx.VERTICAL, choices=["Decimal", u"dd\u00B0mm\u2032ss\u2033"])
        if prefs.options&Prefs.DMS: self.latlon.SetSelection(1)
        box2.Add(self.latlon, 1, wx.RIGHT|wx.EXPAND, pad)

        self.distance = wx.RadioBox(self, -1, "Distance", style=wx.VERTICAL, choices=["Metres", "Feet"])
        if prefs.options&Prefs.IMPERIAL: self.distance.SetSelection(1)
        box2.Add(self.distance, 1, wx.LEFT|wx.EXPAND, pad)

        box5=myCreateStdDialogButtonSizer(self, wx.OK|wx.CANCEL)
        box0.Add(box5, 0, wx.ALL|wx.EXPAND, pad)

        wx.EVT_BUTTON(self, browsebtn.GetId(), self.OnBrowse)
        self.SetSizerAndFit(outersizer)

    def OnBrowse(self, event):
        while True:
            dlg = wx.DirDialog(self, 'X-Plane location', self.path.GetValue(), wx.DEFAULT_DIALOG_STYLE|wx.RESIZE_BORDER|wx.DD_DIR_MUST_EXIST)
            if dlg.ShowModal()!=wx.ID_OK:
                dlg.Destroy()
                return wx.ID_CANCEL
            path=dlg.GetPath()
            dlg.Destroy()
            if glob(join(path, gcustom)) and (glob(join(path, gmain8aptdat)) or glob(join(path, gmain9aptdat))):
                self.path.SetValue(path.strip())
                self.FindWindowById(wx.ID_OK).Enable()
                return wx.ID_OK

class BackgroundDialog(wx.Frame):
    # Uses wx.Frame not wx.Dialog: http://trac.wxwidgets.org/ticket/15595

    def __init__(self, parent, id, title):
        wx.Frame.__init__(self, parent, id, title, style=wx.FRAME_TOOL_WINDOW|wx.FRAME_NO_TASKBAR|wx.CAPTION|wx.CLOSE_BOX|wx.FRAME_FLOAT_ON_PARENT)
        if platform=='darwin':	# Default is too big on Mac
            self.SetWindowVariant(wx.WINDOW_VARIANT_SMALL)

        self.parent=parent
        self.parent.palette.set(None)
        self.parent.palette.Disable()
        if self.parent.menubar:
            self.parent.menubar.Disable()
            self.parent.menubar.Enable(wx.ID_PREFERENCES, False)	# needs to be disabled individually on wxMac Carbon
        #self.parent.toolbar.Disable()	# Doesn't do anything on wxMac Carbon - do it by individual tool
        self.toolbarstate=[(id,self.parent.toolbar.GetToolEnabled(id)) for id in self.parent.toolids]
        for id in self.parent.toolids: self.parent.toolbar.EnableTool(id,False)

        if prefs.package:
            self.prefix=glob(join(prefs.xplane,gcustom,prefs.package))[0]
        else:
            self.prefix=glob(join(prefs.xplane,gcustom))[0]
        if prefs.package in prefs.packageprops:
            self.image=prefs.packageprops[prefs.package][0]
        else:
            self.image=''

        outersizer = wx.BoxSizer(wx.VERTICAL)
        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)
        outersizer.Add(panel, 0, wx.ALL|wx.EXPAND)
        panel.SetSizer(sizer)

        sizer1 = wx.StaticBoxSizer(wx.StaticBox(panel, -1, 'Mapping service'), wx.VERTICAL)
        sizer.Add(sizer1, 0, wx.ALL|wx.EXPAND, pad+pad)
        self.imgnone = wx.RadioButton(panel, -1, 'None', style=wx.RB_GROUP)
        self.imgnone.SetValue(prefs.imageryprovider not in ['Bing','ArcGIS','MapQuest'])
        self.imgbing = wx.RadioButton(panel, -1, u'Microsoft Bing\u2122 ')
        self.imgbing.SetValue(prefs.imageryprovider=='Bing')
        bingtou = wx.HyperlinkCtrl(panel, -1, 'Terms of Use', 'http://www.microsoft.com/maps/assets/docs/terms.aspx')
        self.imgarcgis = wx.RadioButton(panel, -1, u'ESRI ArcGIS Online ')
        self.imgarcgis.SetValue(prefs.imageryprovider=='ArcGIS')
        arcgistou = wx.HyperlinkCtrl(panel, -1, 'Terms of Use', 'http://www.esri.com/legal/pdfs/e-800-termsofuse.pdf')
        self.imgmapquest = wx.RadioButton(panel, -1, u'MapQuest OpenStreetMap ')
        self.imgmapquest.SetValue(prefs.imageryprovider=='MapQuest')
        mapquesttou = wx.HyperlinkCtrl(panel, -1, 'Terms of Use', 'http://info.mapquest.com/terms-of-use/')
        sizer11 = wx.FlexGridSizer(4, 3, pad, pad)
        sizer1.Add(sizer11, 0, wx.ALL|wx.EXPAND, pad)
        sizer11.Add(self.imgnone, 0, wx.LEFT|wx.RIGHT|wx.EXPAND, pad)
        sizer11.AddStretchSpacer()
        sizer11.AddStretchSpacer()
        sizer11.Add(self.imgbing, 0, wx.LEFT|wx.RIGHT|wx.EXPAND, pad)
        sizer11.Add(bingtou, 0, wx.LEFT|wx.RIGHT|wx.EXPAND, pad)
        sizer11.AddStretchSpacer()
        sizer11.Add(self.imgarcgis, 0, wx.LEFT|wx.RIGHT|wx.EXPAND, pad)
        sizer11.Add(arcgistou, 0, wx.LEFT|wx.RIGHT|wx.EXPAND, pad)
        sizer11.AddStretchSpacer()
        sizer11.Add(self.imgmapquest, 0, wx.LEFT|wx.RIGHT|wx.EXPAND, pad)
        sizer11.Add(mapquesttou, 0, wx.LEFT|wx.RIGHT|wx.EXPAND, pad)
        sizer11.AddStretchSpacer()

        sizer2 = wx.StaticBoxSizer(wx.StaticBox(panel, -1, 'File'), wx.VERTICAL)
        sizer.Add(sizer2, 0, wx.ALL|wx.EXPAND, pad+pad)

        sizer3 = wx.StaticBoxSizer(wx.StaticBox(panel, -1, 'Opacity'))
        sizer.Add(sizer3, 0, wx.ALL|wx.EXPAND, pad+pad)
        self.opacity=wx.Slider(panel, -1, prefs.imageryopacity, 0, 100, style=wx.SL_LABELS)
        sizer3.Add(self.opacity, 1, wx.ALL|wx.EXPAND, pad)

        if platform!='darwin':	# Mac users are used to dialogs withaout an OK button
            sizer4=myCreateStdDialogButtonSizer(panel, wx.OK)
            sizer.Add(sizer4, 0, wx.ALL|wx.EXPAND, pad+pad)

        self.path = wx.TextCtrl(panel, -1, style=wx.TE_READONLY)
        self.path.SetMinSize((300, -1))
        sizer2.Add(self.path, 1, wx.ALL|wx.EXPAND, pad)
        sizer22 = wx.FlexGridSizer(1, 4, pad, pad)
        sizer2.Add(sizer22, 0, wx.ALL|wx.EXPAND, pad)
        sizer22.AddGrowableCol(0, proportion=1)
        sizer22.AddStretchSpacer()
        self.clearbtn=wx.Button(panel, wx.ID_CLEAR)
        sizer22.Add(self.clearbtn, 0, wx.ALIGN_CENTER|wx.ALL, pad)
        #sizer22.AddSpacer(6)	# cosmetic
        self.browsebtn=wx.Button(panel, -1, browse)
        self.browsebtn.SetDefault()
        sizer22.Add(self.browsebtn, 0, wx.ALIGN_CENTER|wx.ALL, pad)

        self.SetSizerAndFit(outersizer)

        wx.EVT_RADIOBUTTON(self, self.imgnone.GetId(), self.OnUpdate)
        wx.EVT_RADIOBUTTON(self, self.imgbing.GetId(), self.OnUpdate)
        wx.EVT_RADIOBUTTON(self, self.imgarcgis.GetId(), self.OnUpdate)
        wx.EVT_RADIOBUTTON(self, self.imgmapquest.GetId(), self.OnUpdate)
        wx.EVT_BUTTON(self, self.clearbtn.GetId(), self.OnClear)
        wx.EVT_BUTTON(self, self.browsebtn.GetId(), self.OnBrowse)
        wx.EVT_SCROLL_THUMBRELEASE(self, self.OnUpdate)
        wx.EVT_SCROLL_CHANGED(self, self.OnUpdate)	# for keyboard changes on Windows
        wx.EVT_BUTTON(self, wx.ID_OK, self.OnClose)
        wx.EVT_BUTTON(self, wx.ID_CANCEL, self.OnClose)
        wx.EVT_CLOSE(self, self.OnClose)

        self.OnUpdate(None)


    def OnClear(self, event):
        self.image=''
        self.OnUpdate(event)

    def OnBrowse(self, event):
        if self.image:
            if self.image[0]==curdir:
                dir=dirname(join(self.prefix, normpath(self.image)))
            else:
                dir=dirname(self.image)
            f=basename(self.image)
        else:
            dir=self.prefix
            f=''
        try:
            import PIL.Jpeg2KImagePlugin
        except:
            have_jpeg2000 = False
        else:
            have_jpeg2000 = True
        dlg=wx.FileDialog(self, "Background image:", dir, f,
                          (platform=='darwin' and wx.VERSION>=(2,9) and "*.dds;*.jpg;*.jpeg;*.jp2;*.j2k;*.jpx;*.png;*.tif;*.tiff") or (have_jpeg2000 and "Image files|*.dds;*.jpg;*.jpeg;*.jp2;*.j2k;*.jpx;*.png;*.tif;*.tiff|DDS files (*.dds)|*.dds|JPEG files (*.jpg, *.jpeg)|*.jpg;*.jpeg|JPEG2000 files (*.jp2, *.j2k, *.jpx)|*.jp2;*.j2k;*.jpx|PNG files (*.png)|*.png|TIFF files (*.tif, *.tiff)|*.tif;*.tiff|All files|*.*") or "Image files|*.dds;*.jpg;*.jpeg;*.png;*.tif;*.tiff|DDS files (*.dds)|*.dds|JPEG files (*.jpg, *.jpeg)|*.jpg;*.jpeg|PNG files (*.png)|*.png|TIFF files (*.tif, *.tiff)|*.tif;*.tiff|All files|*.*",
                          wx.OPEN|wx.FD_FILE_MUST_EXIST)
        if dlg.ShowModal()==wx.ID_OK:
            img = dlg.GetPath()
            self.image = ''
            if img:
                # failure is silently ignored during display so test loading the image now
                try:
                    wx.BeginBusyCursor()	# These images tend to require lots of processing
                    self.parent.canvas.vertexcache.texcache.get(img, wrap=False, downsample=False, fixsize=True)
                    self.image = img.startswith(self.prefix) and curdir+img[len(self.prefix):] or img
                    wx.EndBusyCursor()
                except EnvironmentError, e:
                    wx.EndBusyCursor()
                    # PIL isn't very diligent about making a well-formed exception so try both strerror and message
                    myMessageBox(unicode(e.strerror or e.message), "Can't read %s" % basename(img), wx.ICON_ERROR|wx.OK, self)
                except MemoryError, e:
                    wx.EndBusyCursor()
                    myMessageBox(unicode('Out of memory. '+e.message), "Can't read %s" % basename(img), wx.ICON_ERROR|wx.OK, self)
                except:
                    wx.EndBusyCursor()
                    myMessageBox(unicode(exc_info()[1]), "Can't read %s" % basename(img), wx.ICON_ERROR|wx.OK, self)
        dlg.Destroy()
        self.OnUpdate(event)

    def OnUpdate(self, event):
        if not prefs.package:
            self.clearbtn.Disable()
            self.browsebtn.Disable()
            self.path.SetValue('')
        elif not self.image:
            self.clearbtn.Disable()
            self.browsebtn.Enable()
            self.path.SetValue('')
        else:
            self.clearbtn.Enable()
            self.browsebtn.Enable()
            label=self.image
            if prefs.package and label.startswith(self.prefix):
                label=label[len(self.prefix)+1:]
            (x,y)=self.path.GetClientSize()
            (x1,y1)=self.GetTextExtent(label)
            if x1<x:
                self.path.SetValue(label)
            else:
                while sep in label:
                    label=label[label.index(sep)+1:]
                    (x1,y1)=self.GetTextExtent('...'+sep+label)
                    if x1<x: break
                self.path.SetValue('...'+sep+label)

        imageryprovider = (self.imgbing.GetValue() and 'Bing') or (self.imgarcgis.GetValue() and 'ArcGIS') or (self.imgmapquest.GetValue() and 'MapQuest') or None
        if imageryprovider!=prefs.imageryprovider:
            self.parent.canvas.imagery.reset()			# free VBO allocations
        prefs.imageryprovider = imageryprovider
        prefs.imageryopacity=self.opacity.GetValue()
        self.parent.canvas.setbackground(prefs, self.parent.loc, self.image, True)
        self.parent.canvas.goto(self.parent.loc)		# initiate imagery provider setup & loading


    def OnClose(self, event):
        self.parent.palette.Enable()
        if self.parent.menubar:
            self.parent.menubar.Enable(wx.ID_PREFERENCES, True)	# needs to be enabled individually on wxMac Carbon
            wx.Window.Enable(self.parent.menubar)		# wx.MenuBar overrides Enable with bogusness
        for (id,state) in self.toolbarstate: self.parent.toolbar.EnableTool(id,state)
        self.parent.toolbar.ToggleTool(wx.ID_PREVIEW, False)
        self.parent.toolbar.Enable()
        self.path.SetFocus()	# Prevent kill focus event causing crash on wxMac 2.5
        self.Destroy()
        self.parent.bkgd=None
        self.parent.canvas.clearsel()
        self.parent.ShowSel()
        # Update background in prefs
        prefs.packageprops.pop(prefs.package,False)
        if self.parent.canvas.background:
            p=(self.image,)
            for n in self.parent.canvas.background.nodes[0]:
                p += (n.lon, n.lat)
            prefs.packageprops[prefs.package]=p
            if __debug__:print prefs.package, prefs.packageprops[prefs.package]


# The app
class MainWindow(wx.Frame):
    def __init__(self, parent, id, title):

        self.loc=(0.5,0.5)	# (lat,lon)
        self.hdg=0
        self.elev=45
        self.dist=2048.0
        self.airports={}	# default apt.dat, by code
        self.nav=[]
        self.defnetdefs={}	# default network definitions
        self.goto=None		# goto dialog
        self.bkgd=None		# background bitmap dialog

        wx.Frame.__init__(self, parent, id, title)
        wx.EVT_CLOSE(self, self.OnClose)
        wx.EVT_KEY_DOWN(self, self.OnKeyDown)
        wx.EVT_MOUSEWHEEL(self, self.OnMouseWheel)
        
        if platform=='win32':
            self.SetIcon(wx.Icon(executable, wx.BITMAP_TYPE_ICO))
        elif platform.lower().startswith('linux'):	# PNG supported by GTK
            icons=wx.IconBundle()
            icons.AddIconFromFile('Resources/%s.png' % appname, wx.BITMAP_TYPE_PNG)
            try:
                icons.AddIconFromFile('Resources/%s-128.png'% appname, wx.BITMAP_TYPE_PNG)
            except wx._core.PyAssertionError:
                pass	# raised if missing when running from source under wxGTK>=3
            self.SetIcons(icons)
        
        if platform=='darwin':
            # icon pulled from Resources via Info.plist (except for MessageBox icon). Need minimal menu
            # http://developer.apple.com/documentation/UserExperience/Conceptual/AppleHIGuidelines/XHIGMenus/XHIGMenus.html#//apple_ref/doc/uid/TP30000356-TPXREF103
            self.menubar = wx.MenuBar()
            filemenu = wx.Menu()
            filemenu.Append(wx.ID_NEW, u'New\u2026\tCtrl-N')
            wx.EVT_MENU(self, wx.ID_NEW, self.OnNew)
            filemenu.Append(wx.ID_OPEN, u'Open\u2026\tCtrl-O')
            wx.EVT_MENU(self, wx.ID_OPEN, self.OnOpen)
            filemenu.Append(wx.ID_SAVE, u'Save\tCtrl-S')
            wx.EVT_MENU(self, wx.ID_SAVE, self.OnSave)
            filemenu.AppendSeparator()
            filemenu.Append(wx.ID_DOWN, u'Import\u2026')
            wx.EVT_MENU(self, wx.ID_DOWN, self.OnImport)
            filemenu.Append(wx.ID_FIND, u'Import Region')
            wx.EVT_MENU(self, wx.ID_FIND, self.OnImportRegion)
            # ID_EXIT moved to application menu
            filemenu.Append(wx.ID_EXIT, u'Quit %s\tCtrl-Q' % appname)
            wx.EVT_MENU(self, wx.ID_EXIT, self.OnClose)
            self.menubar.Append(filemenu, 'File')

            editmenu = wx.Menu()
            editmenu.Append(wx.ID_UNDO, u'Undo\tCtrl-Z')
            wx.EVT_MENU(self, wx.ID_UNDO, self.OnUndo)
            editmenu.AppendSeparator()
            editmenu.Append(wx.ID_CUT, u'Cut\tCtrl-X')
            wx.EVT_MENU(self, wx.ID_CUT, self.OnCut)
            editmenu.Append(wx.ID_COPY, u'Copy\tCtrl-C')
            wx.EVT_MENU(self, wx.ID_COPY, self.OnCopy)
            editmenu.Append(wx.ID_PASTE, u'Paste\tCtrl-V')
            wx.EVT_MENU(self, wx.ID_PASTE, self.OnPaste)
            editmenu.AppendSeparator()
            editmenu.Append(wx.ID_ADD, u'Add\tEnter')
            wx.EVT_MENU(self, wx.ID_ADD, self.OnAdd)
            editmenu.Append(wx.ID_EDIT, u'Add Node/Hole\tCtrl-Enter')
            wx.EVT_MENU(self, wx.ID_EDIT, self.OnAddNode)
            editmenu.AppendCheckItem(wx.ID_ITALIC, u'Node Control Handles')
            wx.EVT_MENU(self, wx.ID_ITALIC, self.OnBezier)
            editmenu.Append(wx.ID_DELETE, u'Delete\tDelete')
            wx.EVT_MENU(self, wx.ID_DELETE, self.OnDelete)
            # ID_PREFERENCES moved to application menu
            editmenu.Append(wx.ID_PREFERENCES, u'Preferences\tCtrl-,')
            wx.EVT_MENU(self, wx.ID_PREFERENCES, self.OnPrefs)
            self.menubar.Append(editmenu, u'Edit')

            viewmenu = wx.Menu()
            viewmenu.Append(wx.ID_PREVIEW, u'Background imagery\u2026')
            wx.EVT_MENU(self, wx.ID_PREVIEW, self.OnBackground)
            viewmenu.Append(wx.ID_REFRESH, u'Reload')
            wx.EVT_MENU(self, wx.ID_REFRESH, self.OnReload)
            viewmenu.Append(wx.ID_FORWARD, u'Go To\u2026')
            wx.EVT_MENU(self, wx.ID_FORWARD, self.OnGoto)
            viewmenu.Append(wx.ID_APPLY, u'Lock\u2026')
            wx.EVT_MENU(self, wx.ID_APPLY, self.OnLock)
            self.menubar.Append(viewmenu, u'View')

            helpmenu = wx.Menu()
            helpmenu.Append(wx.ID_HELP, u'%s Help\tCtrl-?'  % appname)
            wx.EVT_MENU(self, wx.ID_HELP, self.OnHelp)
            # ID_ABOUT moved to application menu
            helpmenu.Append(wx.ID_ABOUT, u'About %s'  % appname)
            wx.EVT_MENU(self, wx.ID_ABOUT, self.OnAbout)
            self.menubar.Append(helpmenu, u'&Help')
            self.SetMenuBar(self.menubar)
        else:
            self.menubar=None

        self.toolbar=self.CreateToolBar(wx.TB_HORIZONTAL|wx.STATIC_BORDER|wx.TB_FLAT|wx.TB_NODIVIDER)
        # Note colours>~(245,245,245) get replaced by transparent on wxMac 2.5
        # names from v0.4 of http://standards.freedesktop.org/icon-naming-spec/icon-naming-spec-latest.html followed by KDE3 name
        self.iconsize=wx.DefaultSize
        newbitmap=self.icon(['folder-new', 'folder_new', 'document-new', 'filenew'], 'new.png')	# folder-new is new in 0.8 spec
        self.iconsize=(newbitmap.GetWidth(),newbitmap.GetHeight())
        self.toolbar.SetToolBitmapSize(self.iconsize)
        #self.toolbar.SetToolSeparation(self.iconsize[0]/4)
        self.toolbar.AddLabelTool(wx.ID_NEW, 'New', newbitmap, wx.NullBitmap, 0, 'New scenery package')
        wx.EVT_TOOL(self.toolbar, wx.ID_NEW, self.OnNew)
        self.toolbar.AddLabelTool(wx.ID_OPEN, 'Open', self.icon(['document-open-folder', 'folder-open', 'document-open', 'folder_open', 'fileopen'], 'open.png'), wx.NullBitmap, 0, 'Open scenery package')
        wx.EVT_TOOL(self.toolbar, wx.ID_OPEN, self.OnOpen)
        self.toolbar.AddLabelTool(wx.ID_SAVE, 'Save', self.icon(['document-save', 'filesave'], 'save.png'), wx.NullBitmap, 0, 'Save scenery package')
        wx.EVT_TOOL(self.toolbar, wx.ID_SAVE, self.OnSave)
        self.toolbar.AddSeparator()
        self.toolbar.AddLabelTool(wx.ID_DOWN, 'Import', self.icon(['folder-import'], 'import.png'), wx.NullBitmap, 0, 'Import objects from another package')
        wx.EVT_TOOL(self.toolbar, wx.ID_DOWN, self.OnImport)
        self.toolbar.AddLabelTool(wx.ID_FIND, 'Import Region', self.icon(['region-import'], 'import-region.png'), wx.NullBitmap, 0, 'Import objects from the default scenery')
        wx.EVT_TOOL(self.toolbar, wx.ID_FIND, self.OnImportRegion)
        self.toolbar.AddSeparator()
        self.toolbar.AddLabelTool(wx.ID_ADD, 'Add', self.icon(['list-add', 'add'], 'add.png'), wx.NullBitmap, 0, 'Add new object')
        wx.EVT_TOOL(self.toolbar, wx.ID_ADD, self.OnAdd)
        self.toolbar.AddLabelTool(wx.ID_EDIT, 'AddNode', self.icon(['list-add-node'], 'addnode.png'), wx.NullBitmap, 0, 'Add new polygon/network node or hole')
        wx.EVT_TOOL(self.toolbar, wx.ID_EDIT, self.OnAddNode)
        self.toolbar.AddLabelTool(wx.ID_ITALIC, 'Bezier', self.icon([], 'bezier.png'), wx.NullBitmap, wx.ITEM_CHECK, 'Add or delete curve control handles')
        wx.EVT_TOOL(self.toolbar, wx.ID_ITALIC, self.OnBezier)
        self.toolbar.AddLabelTool(wx.ID_DELETE, 'Delete', self.icon(['edit-delete', 'delete', 'editdelete'], 'delete.png'), wx.NullBitmap, 0, 'Delete selected object(s)')
        wx.EVT_TOOL(self.toolbar, wx.ID_DELETE, self.OnDelete)
        if not self.menubar:
            # Mac apps typically don't include cut/copy/paste icons
            self.toolbar.AddSeparator()
            self.toolbar.AddLabelTool(wx.ID_CUT,   'Cut',   self.icon(['edit-cut'],   'cut.png'),   wx.NullBitmap, 0, 'Cut')
            wx.EVT_TOOL(self.toolbar, wx.ID_CUT,   self.OnCut)
            self.toolbar.AddLabelTool(wx.ID_COPY,  'Copy',  self.icon(['edit-copy'],  'copy.png'),  wx.NullBitmap, 0, 'Copy')
            wx.EVT_TOOL(self.toolbar, wx.ID_COPY,  self.OnCopy)
            self.toolbar.AddLabelTool(wx.ID_PASTE, 'Paste', self.icon(['edit-paste'], 'paste.png'), wx.NullBitmap, 0, 'Paste')
            wx.EVT_TOOL(self.toolbar, wx.ID_PASTE, self.OnPaste)
        self.toolbar.AddLabelTool(wx.ID_UNDO, 'Undo', self.icon(['edit-undo', 'undo'], 'undo.png'), wx.NullBitmap, 0, 'Undo last edit')
        wx.EVT_TOOL(self.toolbar, wx.ID_UNDO, self.OnUndo)
        self.toolbar.AddSeparator()
        self.toolbar.AddLabelTool(wx.ID_PREVIEW, 'Background',
                                  self.icon(['frame_image', 'image', 'image-x-generic', 'insert-image'], 'background.png'), wx.NullBitmap, wx.ITEM_CHECK, 'Adjust background image')	# frame_image is KDE3, insert-image is 0.8
        wx.EVT_TOOL(self.toolbar, wx.ID_PREVIEW, self.OnBackground)
        self.toolbar.AddLabelTool(wx.ID_REFRESH, 'Reload', self.icon(['view-refresh', 'reload'], 'reload.png'), wx.NullBitmap, 0, "Reload package's objects, textures and airports")
        wx.EVT_TOOL(self.toolbar, wx.ID_REFRESH, self.OnReload)
        self.toolbar.AddLabelTool(wx.ID_FORWARD, 'Go To', self.icon(['goto'], 'goto.png'), wx.NullBitmap, 0, 'Go to airport')
        wx.EVT_TOOL(self.toolbar, wx.ID_FORWARD, self.OnGoto)
        self.toolbar.AddLabelTool(wx.ID_APPLY, 'Lock object types', self.icon(['object-locked', 'document-encrypt', 'stock_lock', 'security-medium'], 'padlock.png'), wx.NullBitmap, 0, 'Lock object types')
        wx.EVT_TOOL(self.toolbar, wx.ID_APPLY, self.OnLock)
        self.toolbar.AddSeparator()
        self.toolbar.AddLabelTool(wx.ID_PREFERENCES, 'Preferences', self.icon(['preferences-system', 'preferences-other', 'preferences-desktop', 'package-settings'], 'prefs.png'), wx.NullBitmap, 0, 'Preferences')
        wx.EVT_TOOL(self.toolbar, wx.ID_PREFERENCES, self.OnPrefs)
        self.toolbar.AddLabelTool(wx.ID_HELP, 'Help', self.icon(['help-contents', 'help-about', 'help-browser', 'system-help', 'khelpcenter'], 'help.png'), wx.NullBitmap, 0, 'Help')
        wx.EVT_TOOL(self.toolbar, wx.ID_HELP, self.OnHelp)
        
        self.toolbar.Realize()
        # Disable all toolbar buttons until app has loaded to prevent callbacks before app has initialised data
        self.toolids = [wx.ID_NEW,wx.ID_OPEN,wx.ID_SAVE,wx.ID_DOWN,wx.ID_FIND,wx.ID_ADD,wx.ID_EDIT,wx.ID_ITALIC,wx.ID_DELETE,wx.ID_UNDO,wx.ID_REFRESH,wx.ID_PREFERENCES,wx.ID_FORWARD,wx.ID_APPLY]
        if not self.menubar: self.toolids += [wx.ID_CUT,wx.ID_COPY,wx.ID_PASTE]
        for id in self.toolids:
            self.toolbar.EnableTool(id, False)
        if self.menubar:
            self.menubar.Enable(wx.ID_DOWN,   False)
            self.menubar.Enable(wx.ID_FIND,   False)
            self.menubar.Enable(wx.ID_CUT,    False)
            self.menubar.Enable(wx.ID_COPY,   False)
            self.menubar.Enable(wx.ID_PASTE,  False)
            self.menubar.Enable(wx.ID_ADD,    False)
            self.menubar.Enable(wx.ID_EDIT,   False)
            self.menubar.Enable(wx.ID_ITALIC, False)
            self.menubar.Enable(wx.ID_DELETE, False)
            self.menubar.Enable(wx.ID_UNDO,   False)
            self.menubar.Enable(wx.ID_REFRESH,False)

        # Hack: Use zero-sized first field to hide toolbar button long help
        self.statusbar=self.CreateStatusBar(3, wx.ST_SIZEGRIP)
        (x,y)=self.statusbar.GetTextExtent(u'  Lat: 99\u00B099\'99.999"W  Lon: 999\u00B099\'99.999"W  Hdg: 999.9  Elv: 9999.9  ')
        self.statusbar.SetStatusWidths([0, x+50,-1])

        self.splitter = wx.SplitterWindow(self, wx.ID_ANY, style=wx.SP_3DSASH|wx.SP_NOBORDER|wx.SP_LIVE_UPDATE)
        self.canvas = MyGL(self.splitter, self)
        self.palette = Palette(self.splitter, self)
        self.splitter.SetMinimumPaneSize(100)
        self.splitter.SplitVertically(self.canvas, self.palette, -ClutterDef.PREVIEWSIZE)
        box0=wx.BoxSizer()
        box0.Add(self.splitter, 1, wx.EXPAND)
        self.SetSizerAndFit(box0)
        self.SetAutoLayout(True)
        self.SetSize((1024,768))
        self.SetMinSize((800,600))
        self.lastwidth=self.GetSize().x
        wx.EVT_SIZE(self, self.OnSize)
        wx.EVT_SPLITTER_SASH_POS_CHANGING(self.splitter, self.splitter.GetId(), self.OnSashPositionChanging)
        wx.EVT_KEY_DOWN(self.splitter, self.OnKeyDown)

        self.Show(True)

        self.setmodifiedfn=None
        if platform=='darwin':
            # Change name on application menu & set up function to change "dirty" indicator on close button. Can't do either in wx.
            try:	# Carbon
                from Carbon import Menu, Win
                Menu.GetMenuHandle(1).SetMenuTitleWithCFString(appname)            # wxMac always uses id 1.
                self.setmodifiedfn=Win.WhichWindow(self.MacGetTopLevelWindowRef()).SetWindowModified
            except:
                try:	# Cocoa
                    import AppKit
                    # doesn't work: AppKit.NSApp.mainMenu().itemAtIndex_(0).submenu().setTitle_(appname)	 http://www.mail-archive.com/cocoa-dev@lists.apple.com/msg43196.html
                    AppKit.NSBundle.mainBundle().infoDictionary()['CFBundleName']=appname
                    self.setmodifiedfn=AppKit.NSApp.mainWindow().setDocumentEdited_
                except:
                    if __debug__: print_exc()

        self.splitter.SetSashPosition(self.canvas.GetClientSize()[1], True)
        self.canvas.glInit()	# Must be after show
        self.palette.glInit()	# Must be after show
        self.Update()

    def icon(self, stocklist, rsrc):
        if not platform.startswith('linux'):
            return wx.Bitmap(join('Resources',rsrc), wx.BITMAP_TYPE_PNG)
            
        # requires GTK+ >= 2.4
        for stock in stocklist:
            bmp=wx.ArtProvider.GetBitmap(stock, wx.ART_TOOLBAR, self.iconsize)
            if bmp.Ok(): return bmp
            
        if stocklist in [['folder-import'], ['region-import']]:
            # Hack - manually composite two bitmaps
            if stocklist==['folder-import']:
                for stock in ['document-open-folder', 'folder-open', 'document-open', 'folder_open', 'fileopen']:
                    bmp = wx.ArtProvider.GetBitmap(stock, wx.ART_TOOLBAR, self.iconsize)
                    if bmp.Ok(): break
            else:
                bmp = wx.Bitmap(join('Resources', 'region.png'), wx.BITMAP_TYPE_PNG)
                if bmp.Ok() and self.iconsize != (bmp.GetWidth(),bmp.GetHeight()):
                    bmp = wx.BitmapFromImage(bmp.ConvertToImage().Rescale(*self.iconsize))
            if bmp and bmp.Ok():
                size2=int(self.iconsize[0]*0.7)
                for stock in ['go-down', '1downarrow', 'down']:
                    bm2=wx.ArtProvider.GetBitmap(stock, wx.ART_TOOLBAR, (size2,size2))
                    if bm2.Ok():
                        img=bmp.ConvertToImage()
                        im2=bm2.ConvertToImage()
                        for x2 in range(size2):
                            x=x2+(self.iconsize[0]-size2)/2
                            for y in range(size2):
                                alpha=im2.GetAlpha(x2,y)/255.0
                                img.SetRGB(x,y,
                                           img.GetRed  (x,y)*(1-alpha)+im2.GetRed  (x2,y)*alpha,
                                           img.GetGreen(x,y)*(1-alpha)+im2.GetGreen(x2,y)*alpha,
                                           img.GetBlue (x,y)*(1-alpha)+im2.GetBlue (x2,y)*alpha)
                                img.SetAlpha(x,y, max(img.GetAlpha(x,y), im2.GetAlpha(x2,y)))
                        return wx.BitmapFromImage(img)
        elif stocklist==['list-add-node']:
            # Hack - manually composite two bitmaps
            for stock in ['list-add', 'add']:
                bmp=wx.ArtProvider.GetBitmap(stock, wx.ART_TOOLBAR, self.iconsize)
                if bmp.Ok():
                    bm2 = wx.Bitmap(join('Resources', 'node.png'), wx.BITMAP_TYPE_PNG)
                    if bm2.Ok():
                        size2 = bm2.GetWidth()
                        img=bmp.ConvertToImage()
                        im2=bm2.ConvertToImage()
                        for x2 in range(size2):
                            x=x2+(self.iconsize[0]-size2)/2
                            for y2 in range(size2):
                                y=y2+(self.iconsize[1]-size2)/2
                                alpha=im2.GetAlpha(x2,y2)/255.0
                                img.SetRGB(x,y,
                                           img.GetRed  (x,y)*(1-alpha)+im2.GetRed  (x2,y2)*alpha,
                                           img.GetGreen(x,y)*(1-alpha)+im2.GetGreen(x2,y2)*alpha,
                                           img.GetBlue (x,y)*(1-alpha)+im2.GetBlue (x2,y2)*alpha)
                                img.SetAlpha(x,y, max(img.GetAlpha(x,y), im2.GetAlpha(x2,y2)))
                        return wx.BitmapFromImage(img)
                    break


        bmp=wx.Bitmap(join('Resources',rsrc), wx.BITMAP_TYPE_PNG)
        if self.iconsize not in [wx.DefaultSize,
                                 (bmp.GetWidth(),bmp.GetHeight())]:
            img=bmp.ConvertToImage()
            return wx.BitmapFromImage(img.Rescale(*self.iconsize))
        else:
            return bmp

    def ShowLoc(self):
        if prefs.options&Prefs.ELEVATION:
            self.statusbar.SetStatusText(u"%s  Hdg: %.1f\u00B0  Elv: %s" % (Clutter.latlondisp(prefs.options&Prefs.DMS, self.loc[0], self.loc[1]), self.hdg, Clutter.distancedisp(prefs.options&Prefs.IMPERIAL, self.canvas.getheight())), 1)
        else:
            self.statusbar.SetStatusText(u"%s  Hdg: %.1f\u00B0" % (Clutter.latlondisp(prefs.options&Prefs.DMS, self.loc[0], self.loc[1]), self.hdg), 1)

    def ShowSel(self):
        (names,string,lat,lon,hdg)=self.canvas.getsel(prefs.options&Prefs.DMS, prefs.options&Prefs.IMPERIAL)
        if names:
            for name in names:
                if name!=names[0]:
                    self.palette.set(None)
                    break
            else:
                self.palette.set(names[0])

            self.toolbar.EnableTool(wx.ID_FIND,   False)
            self.toolbar.EnableTool(wx.ID_EDIT,   False)
            self.toolbar.EnableTool(wx.ID_ITALIC, False)
            self.toolbar.ToggleTool(wx.ID_ITALIC, False)
            self.toolbar.EnableTool(wx.ID_DELETE, True)
            if self.menubar:
                self.menubar.Enable(wx.ID_FIND,   False)
                self.menubar.Enable(wx.ID_EDIT,   False)
                self.menubar.Enable(wx.ID_ITALIC, False)
                self.menubar.Check( wx.ID_ITALIC, False)
                self.menubar.Enable(wx.ID_DELETE, True)
                if self.canvas.selectednode:	# don't support copy and paste of nodes
                    self.menubar.Enable(wx.ID_CUT,  False)
                    self.menubar.Enable(wx.ID_COPY, False)
                else:
                    self.menubar.Enable(wx.ID_CUT,  True)
                    self.menubar.Enable(wx.ID_COPY, True)
            else:
                if self.canvas.selectednode:	# don't support copy and paste of nodes
                    self.toolbar.EnableTool(wx.ID_CUT,  False)
                    self.toolbar.EnableTool(wx.ID_COPY, False)
                else:
                    self.toolbar.EnableTool(wx.ID_CUT,  True)
                    self.toolbar.EnableTool(wx.ID_COPY, True)

            if len(names)==1 and isinstance(list(self.canvas.selected)[0], Polygon):
                placement = list(self.canvas.selected)[0]
                if ((self.canvas.selectednode and not placement.fixednodes and len(placement.nodes[self.canvas.selectednode[0]]) < 255) or
                    (not self.canvas.selectednode and not placement.singlewinding)):
                    self.toolbar.EnableTool(wx.ID_EDIT, True)
                    if self.menubar: self.menubar.Enable(wx.ID_EDIT, True)
                if self.canvas.selectednode:
                    hasbez = placement.nodes[self.canvas.selectednode[0]][self.canvas.selectednode[1]].bezier
                    self.toolbar.EnableTool(wx.ID_ITALIC, placement.canbezier)
                    self.toolbar.ToggleTool(wx.ID_ITALIC, hasbez)
                    if self.menubar:
                        self.menubar.Enable(wx.ID_ITALIC, placement.canbezier)
                        self.menubar.Check( wx.ID_ITALIC, hasbez)
                if isinstance(list(self.canvas.selected)[0], Exclude):
                    self.toolbar.EnableTool(wx.ID_FIND, True)
                    if self.menubar: self.menubar.Enable(wx.ID_FIND, True)
        else:
            self.palette.set(None)
            self.toolbar.EnableTool(wx.ID_FIND,   False)
            self.toolbar.EnableTool(wx.ID_CUT,    False)
            self.toolbar.EnableTool(wx.ID_COPY,   False)
            self.toolbar.EnableTool(wx.ID_EDIT,   False)
            self.toolbar.EnableTool(wx.ID_ITALIC, False)
            self.toolbar.ToggleTool(wx.ID_ITALIC, False)
            self.toolbar.EnableTool(wx.ID_DELETE, False)
            if self.menubar:
                self.menubar.Enable(wx.ID_FIND,   False)
                self.menubar.Enable(wx.ID_CUT,    False)
                self.menubar.Enable(wx.ID_COPY,   False)
                self.menubar.Enable(wx.ID_EDIT,   False)
                self.menubar.Enable(wx.ID_ITALIC, False)
                self.menubar.Check (wx.ID_ITALIC, False)
                self.menubar.Enable(wx.ID_DELETE, False)
        self.statusbar.SetStatusText(string, 2)

    def SetModified(self, modified):
        if self.setmodifiedfn is not None:
            self.setmodifiedfn(modified)
        self.toolbar.EnableTool(wx.ID_SAVE, modified)
        if self.menubar:
            self.menubar.Enable(wx.ID_SAVE, modified)

    def OnSize(self, event):
        # emulate sash gravity = 1.0
        delta=event.GetSize().x-self.lastwidth
        #print "size", delta
        pos=self.splitter.GetSashPosition()+delta
        if pos<ClutterDef.PREVIEWSIZE: pos=ClutterDef.PREVIEWSIZE	# required for preview
        self.splitter.SetSashPosition(pos, False)
        self.lastwidth=event.GetSize().x
        wx.CallAfter(self.canvas.Refresh)	# wx.FULL_REPAINT_ON_RESIZE unreliable on wx 3
        event.Skip()

    def OnSashPositionChanging(self, event):
        #print "sash", event.GetSashPosition()
        if event.GetSashPosition()<ClutterDef.PREVIEWSIZE:
            # One-way minimum pane size
            event.SetSashPosition(ClutterDef.PREVIEWSIZE)

    def OnKeyDown(self, event):
        changed=False
        cursors=[wx.WXK_UP, wx.WXK_RIGHT, wx.WXK_DOWN, wx.WXK_LEFT,
                 wx.WXK_NUMPAD_UP, wx.WXK_NUMPAD_RIGHT, wx.WXK_NUMPAD_DOWN, wx.WXK_NUMPAD_LEFT,
                 ord('W'), ord('D'), ord('S'), ord('A'),
                 wx.WXK_NUMPAD8, wx.WXK_NUMPAD6, wx.WXK_NUMPAD2, wx.WXK_NUMPAD4]

        # Handling of Control key on Mac changed in 2.9 - http://www.wxpython.org/migrationguide.php
        controldown = event.RawControlDown() if hasattr(event, 'RawControlDown') else event.ControlDown()

        if platform=='darwin' and event.GetKeyCode()==ord('A') and event.CmdDown():
            # Mac Cmd special
            self.canvas.allsel(event.ShiftDown())
        elif event.GetKeyCode() in cursors:
            if controldown:
                xinc=zinc=minres
            else:
                zinc=self.dist/10000000
                if zinc<minres: zinc=minres
                if event.ShiftDown(): zinc*=10
                xinc=zinc/cos(radians(self.loc[0]))
            hr=radians((self.hdg + [0,90,180,270][cursors.index(event.GetKeyCode())%4])%360)
            if __debug__ and event.AltDown():
                # debug elevation mesh buckets
                if event.GetKeyCode()==ord('W'):
                    self.canvas.ei = min(self.canvas.ei+1, ElevationMesh.DIVISIONS-1)
                elif event.GetKeyCode()==ord('S'):
                    self.canvas.ei = max(self.canvas.ei-1, 0)
                elif event.GetKeyCode()==ord('A'):
                    self.canvas.ej = max(self.canvas.ej-1, 0)
                elif event.GetKeyCode()==ord('D'):
                    self.canvas.ej = min(self.canvas.ej+1, ElevationMesh.DIVISIONS-1)
            elif cursors.index(event.GetKeyCode())<8:
                self.loc=(round2res(self.loc[0]+zinc*cos(hr)),
                          round2res(self.loc[1]+xinc*sin(hr)))
            else:
                changed=self.canvas.movesel(round2res(zinc*cos(hr)),
                                            round2res(xinc*sin(hr)))
        elif event.GetKeyCode() in [ord('Q'), wx.WXK_NUMPAD7]:
            if controldown:
                changed=self.canvas.movesel(0, 0, -0.1, 0, self.loc)
            elif event.ShiftDown():
                changed=self.canvas.movesel(0, 0, -5,   0, self.loc)
            else:
                changed=self.canvas.movesel(0, 0, -1,   0, self.loc)
        elif event.GetKeyCode() in [ord('E'), wx.WXK_NUMPAD1]:
            if controldown:
                changed=self.canvas.movesel(0, 0,  0.1, 0, self.loc)
            elif event.ShiftDown():
                changed=self.canvas.movesel(0, 0,  5,   0, self.loc)
            else:
                changed=self.canvas.movesel(0, 0,  1,   0, self.loc)
        elif event.GetKeyCode() in [ord('R'), wx.WXK_MULTIPLY, wx.WXK_NUMPAD_MULTIPLY, wx.WXK_NUMPAD9]:
            if event.ShiftDown():
                changed=self.canvas.movesel(0, 0, 0, 5)
            else:
                changed=self.canvas.movesel(0, 0, 0, 1)
        elif event.GetKeyCode() in [ord('F'), wx.WXK_DIVIDE, wx.WXK_NUMPAD_DIVIDE, wx.WXK_NUMPAD3]:
            if event.ShiftDown():
                changed=self.canvas.movesel(0, 0, 0, -5)
            else:
                changed=self.canvas.movesel(0, 0, 0, -1)
        elif event.GetKeyCode() in [wx.WXK_HOME, wx.WXK_NUMPAD_HOME]:
            if controldown:
                self.hdg=(self.hdg+0.1)%360
            elif event.ShiftDown():
                self.hdg=(self.hdg+5)%360
            else:
                self.hdg=(self.hdg+1)%360
        elif event.GetKeyCode() in [wx.WXK_END, wx.WXK_NUMPAD_END]:
            if controldown:
                self.hdg=(self.hdg-0.1)%360
            elif event.ShiftDown():
                self.hdg=(self.hdg-5)%360
            else:
                self.hdg=(self.hdg-1)%360
        elif event.GetKeyCode() in [ord('+'), ord('='), wx.WXK_ADD, wx.WXK_NUMPAD_ADD]:
            if event.ShiftDown():
                self.dist/=zoom2
            else:
                self.dist/=zoom
            if self.dist<1.0: self.dist=1.0
        elif event.GetKeyCode() in [ord('-'), wx.WXK_NUMPAD_SUBTRACT]:
            if event.ShiftDown():
                self.dist*=zoom2
            else:
                self.dist*=zoom
            if self.dist>maxzoom: self.dist=maxzoom
        elif event.GetKeyCode() in [wx.WXK_PAGEUP, wx.WXK_PRIOR, wx.WXK_NUMPAD_PAGEUP, wx.WXK_NUMPAD_PRIOR]:
            if event.ShiftDown():
                if self.elev==2:
                    self.elev=5	# for symmetry
                else:
                    self.elev+=5
            else:
                self.elev+=1
            if self.elev>90: self.elev=90
        elif event.GetKeyCode() in [wx.WXK_PAGEDOWN, wx.WXK_NEXT, wx.WXK_NUMPAD_PAGEDOWN, wx.WXK_NUMPAD_NEXT]:
            if event.ShiftDown():
                self.elev-=5
            else:
                self.elev-=1
            if self.elev<2: self.elev=2	# not 1 cos clipping
        elif event.GetKeyCode() in [wx.WXK_INSERT, wx.WXK_RETURN, wx.WXK_NUMPAD_INSERT, wx.WXK_NUMPAD_ENTER]:
            if event.CmdDown():
                changed=self.canvas.addnode(self.palette.get(), self.loc[0], self.loc[1], self.hdg, self.dist)
            else:
                changed=self.canvas.add(self.palette.get(), self.loc[0], self.loc[1], self.hdg, self.dist)
        elif event.GetKeyCode() in [wx.WXK_DELETE, wx.WXK_BACK, wx.WXK_NUMPAD_DELETE]: # wx.WXK_NUMPAD_DECIMAL]:
            changed=self.canvas.delsel(event.ShiftDown())
        elif event.GetKeyCode()==ord('Z') and event.CmdDown():
            self.OnUndo(event)
            return
        elif event.GetKeyCode()==ord('X') and event.CmdDown():
            self.OnCut(event)
            return
        elif event.GetKeyCode()==ord('C') and event.CmdDown():
            self.OnCopy(event)
            return
        elif event.GetKeyCode()==ord('V') and event.CmdDown():
            self.OnPaste(event)
            return
        elif event.GetKeyCode()==wx.WXK_SPACE:
            # not Cmd because Cmd-Space = Spotlight
            self.canvas.allsel(event.GetModifiers() & wx.MOD_CONTROL)
        elif event.GetKeyCode()==ord('N'):
            name=self.palette.get()
            if name:
                # not Cmd because Cmd-N = new
                loc=self.canvas.nextsel(name, event.GetModifiers() & wx.MOD_CONTROL, event.ShiftDown())
                if loc:
                    self.loc=loc
                    self.ShowSel()
        elif event.GetKeyCode() in [ord('C'), wx.WXK_NUMPAD5]:
            (names,string,lat,lon,hdg)=self.canvas.getsel()
            if lat==None: return
            self.loc=(round2res(lat),round2res(lon))
            if hdg!=None and event.ShiftDown():
                self.hdg=round(hdg,1)
        elif event.GetKeyCode()==wx.WXK_F1 and platform!='darwin':
            self.OnHelp(event)
            return
        elif __debug__:
            if event.GetKeyCode()==ord('P'):
                print '--- Textures'
                t=0
                for k,v in self.canvas.vertexcache.texcache.stats.iteritems():
                    print '%s,\t%d' % (k,v)
                    t = t+v
                print 'Total,\t%d' % t
                print '--- VBO'
                print 'Instance,\t%d' % (self.canvas.glstate.instance_vbo.data is not None and self.canvas.glstate.instance_vbo.size or 0)
                print 'Dynamic,\t%d' % (self.canvas.glstate.dynamic_vbo.data  is not None and self.canvas.glstate.dynamic_vbo.size  or 0)
                print '---'
                from cProfile import runctx
                runctx('self.canvas.OnPaint(None)', globals(), locals(), 'onpaint.dmp')
                e=wx.MouseEvent()
                e.m_x = e.m_y = 300
                runctx('self.canvas.OnLeftDown(e)', globals(), locals(), 'select.dmp')
            if event.GetKeyCode()==ord('H'):
                print '--- Heap'
                from guppy import hpy
                h=hpy().heap()
                print h
                import code
                code.interact(local=locals())
                #import pdb
                #pdb.set_trace()
            elif event.GetKeyCode()==ord('M'):
                print '---', time.asctime(), '---'
        else:
            event.Skip(True)
            return
        self.canvas.goto(self.loc, self.hdg, self.elev, self.dist)
        self.Update()		# Let window draw first
        self.ShowLoc()
        if changed:
            self.SetModified(True)
            self.toolbar.EnableTool(wx.ID_UNDO, True)
            if self.menubar:
                self.menubar.Enable(wx.ID_UNDO, True)
        else:
            event.Skip(True)


    def OnMouseWheel(self, event):
        # print "MW:", event.GetLinesPerAction(), event.GetWheelRotation(), '/', event.GetWheelDelta()
        if event.GetX()<0 or event.GetX()>=self.Size[0] or event.GetY()<0 or event.GetY()>=self.canvas.Size[1] or not event.GetWheelRotation():
            return	# outside frame
        elif event.GetX()>self.canvas.Size[0]:
            if platform=='win32':	# manually scroll palette
                self.palette.cb.GetCurrentPage().ScrollLines(event.GetLinesPerAction() * -event.GetWheelRotation() / event.GetWheelDelta())
            return
        elif event.GetWheelRotation()>0:
            r = event.ShiftDown() and 1.0/mousezoom2 or 1.0/mousezoom
            if self.dist*r < 1.0: r = 1.0/self.dist
        elif event.GetWheelRotation()<0:
            r = event.ShiftDown() and mousezoom2 or mousezoom
            if self.dist*r > maxzoom: r = maxzoom/self.dist
        try:
            (mx,my,mz)=self.canvas.getlocalloc(event.GetX(),event.GetY())	# OpenGL coords of mouse / zoom point
            (cx,cz)=(self.canvas.x, self.canvas.z)				# OpenGL coords of cursor
            d=hypot(cx-mx, cz-mz)	# horizontal distance [m] between zoom point and cursor
            self.loc = self.canvas.xz2latlon(mx+r*(cx-mx), mz+r*(cz-mz))
            self.dist *= r
            self.canvas.goto(self.loc, self.hdg, self.elev, self.dist)
            self.Update()		# Let window draw first
            self.ShowLoc()
        except:
            if __debug__: print_exc()
        
        
    def OnNew(self, event):
        if not self.SaveDialog(): return
        package=self.NewDialog(True)
        if package:
            self.OnReload(False, package)
            self.SetModified(False)
            self.toolbar.EnableTool(wx.ID_ADD,  False)
            self.toolbar.EnableTool(wx.ID_EDIT, False)
            self.toolbar.EnableTool(wx.ID_ITALIC, False)
            self.toolbar.EnableTool(wx.ID_CUT,  False)
            self.toolbar.EnableTool(wx.ID_COPY, False)
            self.toolbar.EnableTool(wx.ID_PASTE,False)
            self.toolbar.EnableTool(wx.ID_UNDO, False)
            self.toolbar.EnableTool(wx.ID_DOWN, True)
            self.toolbar.EnableTool(wx.ID_FIND, False)
            self.toolbar.EnableTool(wx.ID_REFRESH, True)
            if self.menubar:
                self.menubar.Enable(wx.ID_UNDO,  False)
                self.menubar.Enable(wx.ID_CUT,   False)
                self.menubar.Enable(wx.ID_COPY,  False)
                self.menubar.Enable(wx.ID_PASTE, False)
                self.menubar.Enable(wx.ID_ADD,   False)
                self.menubar.Enable(wx.ID_EDIT,  False)
                self.menubar.Enable(wx.ID_ITALIC, False)
                self.menubar.Enable(wx.ID_DOWN,  True)
                self.menubar.Enable(wx.ID_FIND,  False)
                self.menubar.Enable(wx.ID_REFRESH, True)
        

    def OnOpen(self, event):
        if not self.SaveDialog(): return
        dlg=wx.Dialog(self, wx.ID_ANY, "Open scenery package")
        dirs=glob(join(prefs.xplane,gcustom,'*'))
        choices=[basename(d) for d in dirs if isdir(d) and not basename(d).lower().startswith('-global ')]
        sortfolded(choices)
        i=0
        x=200	# arbitrary
        y=12
        list1=wx.ListBox(dlg, wx.ID_ANY, style=wx.LB_SINGLE, choices=choices)
        for d in choices:
            (x1,y)=list1.GetTextExtent(d)
            if x1>x: x=x1
        list1.SetMinSize((x+16+wx.SystemSettings_GetMetric(wx.SYS_VSCROLL_X),
                          16*y+2*wx.SystemSettings_GetMetric(wx.SYS_EDGE_X)))
        wx.EVT_LISTBOX(dlg, list1.GetId(), self.OnOpened)
        box1=myCreateStdDialogButtonSizer(dlg, wx.OK|wx.CANCEL)
        box0=wx.BoxSizer(wx.VERTICAL)
        box0.Add(list1, 1, wx.LEFT|wx.RIGHT|wx.TOP|wx.EXPAND, 10)
        box0.Add(box1, 0, wx.ALL|wx.EXPAND, 10)
        dlg.SetSizerAndFit(box0)
        dlg.CenterOnParent()	# Otherwise is centred on screen
        dlg.FindWindowById(wx.ID_OK).Disable()
        r=dlg.ShowModal()
        if r==wx.ID_OK:
            package=list1.GetStringSelection()
            dlg.Destroy()
            self.OnReload(False, package)
            if prefs.package:
                self.SetModified(False)
                self.toolbar.EnableTool(wx.ID_ADD,  False)
                self.toolbar.EnableTool(wx.ID_EDIT, False)
                self.toolbar.EnableTool(wx.ID_ITALIC, False)
                self.toolbar.EnableTool(wx.ID_CUT,  False)
                self.toolbar.EnableTool(wx.ID_COPY, False)
                self.toolbar.EnableTool(wx.ID_PASTE,False)
                self.toolbar.EnableTool(wx.ID_UNDO, False)
                self.toolbar.EnableTool(wx.ID_DOWN, True)
                self.toolbar.EnableTool(wx.ID_FIND, False)
                self.toolbar.EnableTool(wx.ID_REFRESH, True)
                if self.menubar:
                    self.menubar.Enable(wx.ID_ADD,   False)
                    self.menubar.Enable(wx.ID_EDIT,  False)
                    self.menubar.Enable(wx.ID_ITALIC, False)
                    self.menubar.Enable(wx.ID_UNDO,  False)
                    self.menubar.Enable(wx.ID_CUT,   False)
                    self.menubar.Enable(wx.ID_COPY,  False)
                    self.menubar.Enable(wx.ID_PASTE, False)
                    self.menubar.Enable(wx.ID_DOWN,  True)
                    self.menubar.Enable(wx.ID_FIND,  False)
                    self.menubar.Enable(wx.ID_REFRESH, True)
        else:
            dlg.Destroy()
            
    def OnOpened(self, event):
        event.GetEventObject().GetParent().FindWindowById(wx.ID_OK).Enable()

    def OnSave(self, event):
        if not prefs.package:
            prefs.package=self.NewDialog(False)
            if not prefs.package: return False
            if platform=='darwin':
                self.SetTitle("%s" % prefs.package)
            else:
                self.SetTitle("%s - %s" % (prefs.package, appname))
            if None in prefs.packageprops:
                prefs.packageprops[prefs.package]=prefs.packageprops.pop(None)

        base=glob(join(prefs.xplane,gcustom))[0]
        if not glob(join(base,prefs.package)):
            mkdir(join(base,prefs.package))
        base=glob(join(prefs.xplane,gcustom,prefs.package))[0]
        if not glob(join(base,gnavdata)):
            mkdir(join(base,'Earth nav data'))
        dsfdir=glob(join(prefs.xplane,gcustom,prefs.package,gnavdata))[0]

        stuff=dict(self.canvas.unsorted)
        for (key,placements) in self.canvas.placements.iteritems():
            stuff[key] = placements
        for key in stuff.keys():
            try:
                writeDSF(dsfdir, key, stuff[key], self.canvas.netfile)
            except EnvironmentError, e:
                if __debug__: print_exc()
                myMessageBox(str(e.strerror),
                             "Can't save %+03d%+04d.dsf." % (key[0], key[1]), 
                             wx.ICON_ERROR|wx.OK, None)
                return False
            except:
                if __debug__: print_exc()
                myMessageBox('',
                             "Can't save %+03d%+04d.dsf." % (key[0], key[1]),
                             wx.ICON_ERROR|wx.OK, None)
                return False
        self.SetModified(False)
        self.toolbar.EnableTool(wx.ID_DOWN, True)
        self.toolbar.EnableTool(wx.ID_REFRESH, True)
        if self.menubar:
            self.menubar.Enable(wx.ID_DOWN, True)
            self.menubar.Enable(wx.ID_REFRESH, True)

        return True
        
    def OnAdd(self, event):
        if self.canvas.add(self.palette.get(), self.loc[0], self.loc[1], self.hdg, self.dist):
            self.SetModified(True)
            self.toolbar.EnableTool(wx.ID_UNDO, True)
            if self.menubar:
                self.menubar.Enable(wx.ID_UNDO, True)

    def OnAddNode(self, event):
        # Assumes that only one object selected
        if self.canvas.addnode(self.palette.get(), self.loc[0], self.loc[1], self.hdg, self.dist):
            self.SetModified(True)
            self.toolbar.EnableTool(wx.ID_UNDO, True)
            if self.menubar:
                self.menubar.Enable(wx.ID_UNDO, True)

    def OnBezier(self, event):
        if self.canvas.togglebezier():
            self.SetModified(True)
            self.toolbar.EnableTool(wx.ID_UNDO, True)
            if self.menubar:
                self.menubar.Enable(wx.ID_UNDO, True)

    def OnDelete(self, event):
        if self.canvas.delsel(wx.GetKeyState(wx.WXK_SHIFT)):
            self.SetModified(True)
            self.toolbar.EnableTool(wx.ID_UNDO, True)
            if self.menubar:
                self.menubar.Enable(wx.ID_UNDO, True)

    def OnUndo(self, event):
        loc=self.canvas.undo()
        if loc:
            self.loc=loc
            self.ShowSel()
            self.canvas.goto(self.loc, self.hdg, self.elev, self.dist)
            self.SetModified(True)
            self.Update()		# Let window draw first
            self.ShowLoc()
        if not self.canvas.undostack:
            self.toolbar.EnableTool(wx.ID_UNDO, False)
            if self.menubar: self.menubar.Enable(wx.ID_UNDO, False)

    def OnCut(self, event):
        self.OnCopy(event)
        self.OnDelete(event)

    def OnCopy(self, event):
        if self.canvas.copysel():
            self.toolbar.EnableTool(wx.ID_PASTE, True)
            if self.menubar:
                self.menubar.Enable(wx.ID_PASTE, True)

    def OnPaste(self, event):
        if self.canvas.paste(*self.loc):
            self.SetModified(True)
            self.toolbar.EnableTool(wx.ID_UNDO, True)
            if self.menubar:
                self.menubar.Enable(wx.ID_UNDO, True)
            self.ShowSel()

    def OnBackground(self, event):
        self.canvas.clearsel()
        if self.bkgd:
            self.bkgd.Close()
        else:
            self.bkgd=BackgroundDialog(self, wx.ID_ANY, "Background imagery")
            self.bkgd.CenterOnParent()	# Otherwise is top-left on Mac
            self.bkgd.Show()
            self.bkgd.Raise()
        self.canvas.Refresh()	# Show background image as selected
        
    # Load or reload current package
    def OnReload(self, reload, package=None):
        progress=wx.ProgressDialog('Loading', '', 5, self)
        if reload:
            package=prefs.package
        pkgnavdata=None
        if package:
            pkgdir=glob(join(prefs.xplane,gcustom,package))[0]
            if glob(join(pkgdir, gnavdata)):
                pkgnavdata=glob(join(pkgdir, gnavdata))[0]
        else:
            pkgdir=None

        progress.Update(1, 'Default airports')
        if prefs.xpver > 8:
            mainaptdat=glob(join(prefs.xplane, gmain9aptdat))[0]
        elif glob(join(prefs.xplane, gmain8aptdat)):
            mainaptdat=glob(join(prefs.xplane, gmain8aptdat))[0]
        else:
            mainaptdat = None
            self.nav=[]
            myMessageBox("Can't find the X-Plane global apt.dat file.", "Can't load airport data.", wx.ICON_EXCLAMATION|wx.OK, self)

        if mainaptdat and not self.airports:	# Default apt.dat
            try:
                if __debug__: clock=time.clock()	# Processor time
                (self.airports,self.nav)=scanApt(mainaptdat)
                if __debug__: print "%6.3f time in global apt" % (time.clock()-clock)
            except:
                if __debug__:
                    print "Invalid apt.dat:"
                    print_exc()
                self.nav=[]
                myMessageBox("The X-Plane global apt.dat file is invalid.", "Can't load airport data.", wx.ICON_EXCLAMATION|wx.OK, self)
            try:
                if prefs.xpver>=9:
                    self.nav.extend(readNav(glob(join(prefs.xplane,gmain9navdat))[0]))
                else:
                    self.nav.extend(readNav(glob(join(prefs.xplane,gmain8navdat))[0]))
            except:
                if __debug__:
                    print "Invalid nav.dat:"
                    print_exc()

        # According to http://scenery.x-plane.com/library.php?doc=about_lib.php&title=X-Plane+8+Library+System
        # search order is: custom libraries, default libraries, scenery package
        progress.Update(2, 'Libraries')
        lookup={}	# {name: paletteentry}
        terrain={}	# {name: path}

        if package:
            for path, dirs, files in walk(pkgdir):
                for f in files:
                    if f[-4:].lower() in KnownDefs and f[0]!='.':
                        name=join(path,f)[len(pkgdir)+1:-4].replace('\\','/')+f[-4:].lower()
                        if name.lower().startswith('custom objects') and f[-4:].lower()==ObjectDef.OBJECT:
                            name=name[15:]
                        if not name.startswith('opensceneryx/placeholder.'):	# no point adding placeholders
                            lookup[name] = PaletteEntry(join(path,f))
                    #elif f[-4:].lower()==NetworkDef.NETWORK:	# Don't support custom networks
                    #    netfile=join(path,f)

        # libraries in reverse asciibetical order = priority low to high
        clibs = sorted(glob(join(prefs.xplane, gcustom,  '*', glibrary)), reverse=True)
        glibs = sorted(glob(join(prefs.xplane, gglobal,  '*', glibrary)), reverse=True)
        dlibs = sorted(glob(join(prefs.xplane, gdefault, '*', glibrary)), reverse=True)
        if __debug__:
            print "libraries:"
            for l in reversed(dlibs+glibs+clibs): print l[len(prefs.xplane)+1:-11]
        for lib in dlibs+glibs: readLib(lib, lookup, terrain, False, False)
        for lib in clibs: readLib(lib, lookup, terrain, True, pkgdir==dirname(lib))

        # post-process into catergories for palette
        lookupbylib = defaultdict(dict)	# {name: paletteentry} by libname
        objects = {}	# in this package, and not overridden
        deprecated = {}
        for name, obj in lookup.iteritems():
            if obj.private:
                pass	# Just don't list these for now. Should probably not be in lookup at all (but we still need to display navaids)
            elif not obj.package:
                objects[name] = obj
            elif obj.deprecated:
                deprecated[name] = obj
            else:
                lib = name
                if lib.startswith('/'): lib=lib[1:]
                if lib.startswith('lib/'):
                    if obj.iscustom:
                        lib = obj.package	# separate out custom libraries (e.g. FF Library) that write new entries under lib/
                    else:
                        lib = lib[:lib.index('/',4)]
                elif lib.startswith('opensceneryx/'):
                    lib = lib[:lib.index('/',13)]
                elif lib.startswith('ruscenery/'):
                    lib = lib[:lib.index('/',10)]
                elif lib.startswith('KSEA_objects/'):
                    lib = 'KSEA_Objects'	# Hack: v10 KSEA Demo Area is inconsistent in capatilization
                elif not '/' in lib:
                    lib = "Uncategorised"
                else:
                    lib = lib[:lib.index('/')]
                lookupbylib[lib][name] = obj

        # Populate palette with library items
        self.palette.flush()	# Don't do this earlier to avoid crash on importing under wxMac 2.8
        self.palette.load('Objects in this package', objects, pkgdir)
        libnames = lookupbylib.keys()
        sortfolded(libnames)	# dislay order in palette
        for libname in libnames:
            self.palette.load(libname, lookupbylib[libname])
        if deprecated: self.palette.load('Deprecated', deprecated)

        # Networks
        # lookup and palette need to be populated with human-readable names so that networks are browsable and searchable
        # but lookup assumes each "object" maps to a file which isn't the case for netork "objects".
        # Also, networks need to be findable by type_id, not human-readable name.
        # So we make a separate lookup table and pass it to the canvas and to readDSF.
        lookup.pop('lib/g8/roads.net',None)		# Not a usable file
        netfile = None
        netdefs = {}

        # custom .net file
        if netfile:
            try:
                netdefs = readNet(netfile)
                if not netdefs: raise IOError	# empty
                netfile = netfile[len(pkgdir)+1:].replace('\\','/')
            except:
                myMessageBox("The %s file in this package is invalid." % netfile[len(pkgdir)+1:], "Can't load network data.", wx.ICON_EXCLAMATION|wx.OK, self)
                netfile = None
                netdefs = {}

        # standard v10 .net file
        defnetfile = lookup.pop(NetworkDef.DEFAULTFILE,None)
        if not netdefs:
            if defnetfile and not self.defnetdefs:
                try:
                    netdefs = self.defnetdefs = readNet(defnetfile.file)
                    netfile = NetworkDef.DEFAULTFILE
                except:
                    if __debug__:
                        print defnetfile
                        print_exc()
            else:
                netdefs = self.defnetdefs	# don't bother re-loading
                netfile = NetworkDef.DEFAULTFILE
        if netdefs:
            names={}
            for type_id,defn in netdefs.iteritems():
                names[defn.name] = PaletteEntry(defn.name)
            self.palette.load(NetworkDef.TABNAME, names)
            lookup.update(names)

        # Populate palette with final items
        self.palette.load(ExcludeDef.TABNAME, dict([(Exclude.NAMES[x], PaletteEntry(x)) for x in Exclude.NAMES.keys()]))
        self.palette.load('Search results', {})

        if not reload:
            # Load, not reload
            progress.Update(3, 'Overlay DSFs')
            self.elev=45
            self.dist=2048.0
            placements={}
            if pkgnavdata:
                try:
                    dsfs=glob(join(pkgnavdata, '[+-][0-9]0[+-][01][0-9]0', '[+-][0-9][0-9][+-][01][0-9][0-9].[dD][sS][fF]'))
                    if not dsfs:
                        if glob(join(pkgnavdata, '[+-][0-9]0[+-][01][0-9]0', '[+-][0-9][0-9][+-][01][0-9][0-9].[eE][nN][vV]')): raise IOError, (0, 'This package uses v7 "ENV" files')
                    for f in dsfs:
                        (lat, lon, p, nets, foo) = readDSF(f, netdefs, {})
                        tile=(lat,lon)
                        placements[tile]=p
                except IOError, e:	# Bad DSF - restore to unloaded state
                    progress.Destroy()
                    myMessageBox(e.strerror, "Can't edit this scenery package.",
                                 wx.ICON_ERROR|wx.OK, None)
                    return
                except:		# Bad DSF - restore to unloaded state
                    if __debug__:
                        print_exc()
                    progress.Destroy()
                    myMessageBox("Failed to read %s." % basename(f), "Can't edit this scenery package.", wx.ICON_ERROR|wx.OK, None)
                    return
            if package:
                prefs.package=package
            else:
                package='Untitled'
            if platform=='darwin':
                self.SetTitle("%s" % package)
            else:
                self.SetTitle("%s - %s" % (package, appname))
        else:
            placements=None	# keep existing
        self.toolbar.EnableTool(wx.ID_UNDO, False)
        if self.menubar:
            self.menubar.Enable(wx.ID_UNDO, False)
        progress.Update(4, 'Airports')
        if __debug__: clock=time.clock()	# Processor time
        pkgapts={}
        nav=list(self.nav)
        pkgloc=None
        apts=glob(join(prefs.xplane, gcustom, '*', gaptdat))
        for apt in apts:
            # Package-specific apt.dats
            try:
                (thisapt,thisnav,thiscode)=readApt(apt)
                # First custom airport wins
                for code, stuff in thisapt.iteritems():
                    if code not in pkgapts:
                        pkgapts[code]=stuff
                nav.extend(thisnav)
                # get start location
                if prefs.package and apt[:-23].endswith(sep+prefs.package) and thiscode and not pkgloc:
                    (name, pkgloc, run)=thisapt[thiscode]
            except AssertionError, e:
                if prefs.package and apt[:-23].endswith(sep+prefs.package):
                    myMessageBox(e.message, "Can't load airport data.", wx.ICON_EXCLAMATION|wx.OK, self)
            except:
                if __debug__:
                    print "Invalid %s" % apt
                    print_exc()
                if prefs.package and apt[:-23].endswith(sep+prefs.package):
                    myMessageBox("The apt.dat file in this package is invalid.", "Can't load airport data.", wx.ICON_EXCLAMATION|wx.OK, self)

        # Merge in custom airports
        airports=dict(self.airports)
        airports.update(pkgapts)
        if __debug__: print "%6.3f time in custom airports" % (time.clock()-clock)

        if self.goto: self.goto.Close()	# Needed on wxMac 2.5
        self.goto=GotoDialog(self, airports)	# build only

        if prefs.xpver>=9:
            dsfdirs=[join(prefs.xplane, gcustom),
                     join(prefs.xplane, gglobal),
                     join(prefs.xplane, gdefault)]
        else:
            dsfdirs=[join(prefs.xplane, gcustom),
                     join(prefs.xplane, gdefault)]
        self.canvas.reload(prefs, airports, nav, mainaptdat, netdefs, netfile, lookup, placements, terrain, dsfdirs)
        if not reload:
            # Load, not reload
            if pkgloc:	# go to first airport by name
                self.loc=pkgloc
                self.hdg=0
            else:
                for p in placements.values():
                    if p:
                        self.loc=p[0].location()
                        self.hdg=0
                        break
                else:	# Fallback / Untitled
                    pass	# keep existing
        self.loc=(round2res(self.loc[0]),round2res(self.loc[1]))
        progress.Update(5, 'Done')
        progress.Destroy()
        
        self.canvas.valid=True	# Allow goto() to do its stuff
        self.canvas.goto(self.loc, self.hdg, self.elev, self.dist)
        self.ShowLoc()

        # These buttons shouldn't be available 'til after first reload
        self.toolbar.EnableTool(wx.ID_NEW,     True)
        self.toolbar.EnableTool(wx.ID_OPEN,    True)
        self.toolbar.EnableTool(wx.ID_SAVE,    True)
        self.toolbar.EnableTool(wx.ID_PREFERENCES, True)
        self.toolbar.EnableTool(wx.ID_FORWARD, True)
        self.toolbar.EnableTool(wx.ID_APPLY,   True)

        # redraw
        self.Refresh()
        self.Raise()	# needed on Windows

    def OnImport(self, event):
        dlg=wx.FileDialog(self, "Import", glob(join(prefs.xplane,gcustom))[0], '',
                          platform=='darwin' and wx.VERSION>=(2,9) and "*.obj;*.pol;*.fac;*.for;*.lin;*.dds;*.png" or "All supported file types|*.obj;*.pol;*.fac;*.for;*.lin;*.dds;*.png|Object files (*.obj)|*.obj|Draped polygon files (*.pol)|*.pol|Facade files (*.fac)|*.fac|Forest files (*.for)|*.for|Line files (*.lin)|*.lin|Textures (*.dds, *.png)|*.dds;*.png|All files|*.*",
                          wx.OPEN|wx.MULTIPLE|wx.FILE_MUST_EXIST)
        if dlg.ShowModal()!=wx.ID_OK:
            dlg.Destroy()
            return
        paths=dlg.GetPaths()
        dlg.Destroy()

        files = doimport(paths, self.palette)
        if files is True:
            self.OnReload(True)
        elif files:
            first = None
            pkgpath = glob(join(prefs.xplane, gcustom, prefs.package))[0]
            for (src, dst) in files:
                ext=splitext(src)[1].lower()
                if ext in ['.dds', '.png']: continue
                name=dst[len(pkgpath)+1:].replace(sep, '/')
                if name.lower().startswith('custom objects') and ext==ObjectDef.OBJECT:
                    name=name[15:]
                self.canvas.lookup[name]=PaletteEntry(dst)
                self.palette.add(name)
                first = first or name
            self.palette.set(first)	# show first added

    def OnImportRegion(self, event):
        wx.BeginBusyCursor()
        if glob(join(prefs.xplane, gmain9aptdat)):
            dsfdirs=[join(prefs.xplane, gglobal),
                     join(prefs.xplane, gdefault)]
        else:
            dsfdirs=[join(prefs.xplane, gdefault)]
        if self.canvas.importregion(dsfdirs, self.defnetdefs):
            wx.EndBusyCursor()
            self.SetModified(True)
            self.toolbar.EnableTool(wx.ID_UNDO, True)
            if self.menubar:
                self.menubar.Enable(wx.ID_UNDO, True)
            self.ShowSel()
        elif len(self.canvas.selected)==1 and isinstance(list(self.canvas.selected)[0], Exclude):
            wx.EndBusyCursor()
            myMessageBox('There are no %s in this region of the default scenery'.replace('&','or') % list(self.canvas.selected)[0].name[len(PolygonDef.EXCLUDE):], "No objects found.", wx.ICON_INFORMATION|wx.OK, self)


    def OnGoto(self, event):
        self.goto.CenterOnParent()	# Otherwise is centred on screen
        choice=self.goto.show(self.loc)
        if choice:
            self.loc=[round2res(choice[0]),
                      round2res(choice[1])]
            self.canvas.goto(self.loc, self.hdg, self.elev, self.dist)
            #from cProfile import runctx
            #runctx('self.canvas.goto(self.loc, self.hdg, self.elev, self.dist)', globals(), locals(), 'profile.dmp')
            self.ShowLoc()

    def OnLock(self, event):
        dlg=LockDialog(self, wx.ID_ANY, "Lock")
        dlg.CenterOnParent()	# Otherwise is top-left on Mac
        if dlg.ShowModal()==wx.ID_OK:
            # apply to currently selected
            self.canvas.selected=set([x for x in self.canvas.selected if not x.definition.type & self.canvas.locked])
            self.canvas.Refresh()
            self.ShowSel()

    def OnPrefs(self, event):
        dlg=PreferencesDialog(self, wx.ID_ANY, "Preferences")
        dlg.CenterOnParent()	# Otherwise is top-left on Mac
        x=dlg.ShowModal()
        if x!=wx.ID_OK:
            if x: dlg.Destroy()
            return
        oldoptions = prefs.options
        if dlg.display.GetSelection()==3:
            prefs.options=Prefs.TERRAIN|Prefs.NETWORK
        elif dlg.display.GetSelection()==2:
            prefs.options=Prefs.TERRAIN|Prefs.ELEVATION
        elif dlg.display.GetSelection()==1:
            prefs.options=Prefs.TERRAIN
        else:
            prefs.options=0
        if dlg.latlon.GetSelection():
            prefs.options|=Prefs.DMS
        if dlg.distance.GetSelection():
            prefs.options|=Prefs.IMPERIAL
        if dlg.path.GetValue()!=prefs.xplane:
            # Make untitled. Has ID_SAVE enabled so can Save As.
            prefs.xplane=dlg.path.GetValue()
            prefs.package=None
            self.SetModified(False)
            self.toolbar.EnableTool(wx.ID_SAVE,   True)
            self.toolbar.EnableTool(wx.ID_DOWN,   False)
            self.toolbar.EnableTool(wx.ID_FIND,   False)
            self.toolbar.EnableTool(wx.ID_ADD,    False)
            self.toolbar.EnableTool(wx.ID_EDIT,   False)
            self.toolbar.EnableTool(wx.ID_ITALIC, False)
            self.toolbar.EnableTool(wx.ID_CUT,    False)
            self.toolbar.EnableTool(wx.ID_COPY,   False)
            self.toolbar.EnableTool(wx.ID_PASTE,  False)
            self.toolbar.EnableTool(wx.ID_DELETE, False)
            self.toolbar.EnableTool(wx.ID_UNDO,   False)
            self.toolbar.EnableTool(wx.ID_REFRESH,False)
            if self.menubar:
                self.menubar.Enable(wx.ID_SAVE,   True)
                self.menubar.Enable(wx.ID_DOWN,   False)
                self.menubar.Enable(wx.ID_FIND,   False)
                self.menubar.Enable(wx.ID_CUT,    False)
                self.menubar.Enable(wx.ID_COPY,   False)
                self.menubar.Enable(wx.ID_PASTE,  False)
                self.menubar.Enable(wx.ID_ADD,    False)
                self.menubar.Enable(wx.ID_EDIT,   False)
                self.menubar.Enable(wx.ID_ITALIC, False)
                self.menubar.Enable(wx.ID_DELETE, False)
                self.menubar.Enable(wx.ID_UNDO,   False)
                self.menubar.Enable(wx.ID_REFRESH,False)
            dlg.Destroy()
            self.airports={}	# force reload
            self.defnetdefs=[]	# force reload
            self.OnReload(False)
            prefs.write()
        self.canvas.goto(self.loc)
        self.ShowLoc()
        self.ShowSel()

    def OnHelp(self, evt):
        filename = abspath(join('Resources',appname+'.html'))
        if 'startfile' in dir(os):
            os.startfile(filename)
        else:
            if type(filename)==types.UnicodeType:
                filename=filename.encode('utf-8')
            webbrowser.open("file:"+quote(filename))

    def OnAbout(self, evt):
        AboutBox(self)

    def OnClose(self, event):
        # On wxMac Cmd-Q, LogOut & ShutDown are indistinguishable CommandEvents
        if not self.SaveDialog(isinstance(event, wx.CommandEvent) or event.CanVeto()):
            if isinstance(event, wx.CloseEvent) and event.CanVeto(): event.Veto()
            return False
        prefs.write()
        if self.goto: self.goto.Close()
        self.canvas.exit()
        self.Destroy()
        return True

    def SaveDialog(self, cancancel=True):
        # returns False if wants to cancel
        style=wx.YES_NO
        if cancancel: style|=wx.CANCEL
        # Untitled always has ID_SAVE enabled
        if self.toolbar.GetToolEnabled(wx.ID_SAVE) and (prefs.package or reduce(lambda x,y: x+y, self.canvas.placements.values())):
            package=prefs.package or 'Untitled'
            if platform=='darwin':
                r=myMessageBox("If you don't save, your changes will be lost.",
                               'Save scenery package "%s"?' % package,
                               wx.ICON_EXCLAMATION|style, self)
            else:
                r=myMessageBox('Do you want to save the changes?',
                               '"%s" has been modified.' % package,
                               wx.ICON_EXCLAMATION|style, self)
            if r==wx.YES:
                return self.OnSave(None)
            elif r==wx.CANCEL:
                return False
        return True
        
    def NewDialog(self, isnew):
        if isnew:
            dlg=wx.TextEntryDialog(self, "Name of new scenery package:",
                                   "New scenery package")
        else:
            dlg=wx.TextEntryDialog(self, "Name of scenery package:",
                                   "Save scenery package")
        while True:
            if dlg.ShowModal()==wx.ID_OK:
                v=dlg.GetValue().strip()
                if not v: continue
                ok=True
                for c in '\\/:*?"<>|':
                    if c in v: ok=False
                else:
                    try:
                        basename(v).encode('ascii')
                    except:
                        ok=False
                if not ok:
                    myMessageBox('\\ / : * ? " < > |', "Package names cannot contain accented \ncharacters nor any of the following \ncharacters:",
                                 wx.ICON_ERROR|wx.OK, self)
                    continue
                base=glob(join(prefs.xplane,gcustom))[0]
                for f in glob(join(base,'*')):
                    if basename(f.lower())==v.lower():
                        myMessageBox("A package named %s already exists" % v,
                                     "Can't create scenery package.",
                                     wx.ICON_ERROR|wx.OK, self)
                        break
                else:
                    mkdir(join(base,v))
                    mkdir(join(base,v,'Earth nav data'))
                    mkdir(join(base,v,'objects'))
                    dlg.Destroy()
                    return v
            else:
                dlg.Destroy()
                return None
            
        
# main
app=wx.App(redirect=not __debug__)
app.SetAppName(appname)
if platform=='win32':
    if app.GetComCtl32Version()>=600 and wx.DisplayDepth()>=32:
        wx.SystemOptions.SetOptionInt('msw.remap', 2)
    else:
        wx.SystemOptions.SetOptionInt('msw.remap', 0)

if __debug__:
    wx.Log.SetActiveTarget(wx.LogStderr())
frame=MainWindow(None, wx.ID_ANY, appname)
app.SetTopWindow(frame)

# user prefs
if not prefs.xplane or not (glob(join(prefs.xplane, gcustom)) and (glob(join(prefs.xplane, gmain8aptdat)) or glob(join(prefs.xplane, gmain9aptdat)))):
    try:
        # X-Plane installer defaults to the Desktop so look there
        if platform=='win32':
            from _winreg import OpenKey, QueryValueEx, HKEY_LOCAL_MACHINE, HKEY_CURRENT_USER, REG_SZ, REG_EXPAND_SZ
            handle = OpenKey(HKEY_CURRENT_USER, 'Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\User Shell Folders')
            (v,t) = QueryValueEx(handle, 'Desktop')
            handle.Close()
            if t==REG_EXPAND_SZ:
                dirs = v.rstrip('\0').decode('mbcs').strip().split('\\')
                for i in range(len(dirs)):
                    if dirs[i][0] == dirs[i][-1] == '%':
                        dirs[i] = getenv(dirs[i][1:-1],dirs[i]).decode('mbcs')
                v = '\\'.join(dirs)
            if t in [REG_SZ,REG_EXPAND_SZ] and isdir(v):
                desktop = v
        else:
            desktop = join(expanduser('~').decode(sys.getfilesystemencoding() or 'utf-8'), u'Desktop')	# Unicode so paths listed as unicode
    except:
        if __debug__: print_exc()
        desktop = u''

    myMessageBox('OverlayEditor needs to know which folder contains your X-Plane, PlaneMaker etc applications. In the next dialog please locate your X-Plane folder.\n\nIf you want the scenery packages that you create with OverlayEditor to work with older versions of X-Plane, in the next dialog please choose the oldest version of X-Plane that you want your scenery package to work with.' , 'Welcome', wx.ICON_INFORMATION|wx.OK, frame)
    dlg = wx.DirDialog(frame, 'Please locate your X-Plane folder', desktop, wx.DEFAULT_DIALOG_STYLE|wx.RESIZE_BORDER|wx.DD_DIR_MUST_EXIST)
    dlg.CenterOnParent()	# Otherwise is centred on screen
    while True:
        if dlg.ShowModal() != wx.ID_OK:	# User cancelled
            dlg.Destroy()
            exit(1)
        prefs.xplane = dlg.GetPath()
        if glob(join(prefs.xplane, gcustom)) and (glob(join(prefs.xplane, gmain8aptdat)) or glob(join(prefs.xplane, gmain9aptdat))):
            prefs.write()
            dlg.Destroy()
            break

if __debug__:
    # allow package name on command line
    if len(argv)>1 and glob(join(prefs.xplane, gcustom, basename(argv[1]))):
        prefs.package=basename(argv[1])
        frame.toolbar.EnableTool(wx.ID_SAVE,  False)
        frame.toolbar.EnableTool(wx.ID_DOWN,  True)
        frame.toolbar.EnableTool(wx.ID_REFRESH,True)
        if frame.menubar:
            frame.menubar.Enable(wx.ID_SAVE,  False)
            frame.menubar.Enable(wx.ID_DOWN,  True)
            frame.menubar.Enable(wx.ID_REFRESH,True)

# Load data files - progress dialog on Mac requires that app frame be created first, so do this by posting a reload event
wx.PostEvent(frame.toolbar, wx.PyCommandEvent(wx.EVT_TOOL.typeId, wx.ID_REFRESH))

if False:	# XXX trace
    from trace import Trace
    sys.stdout=open(appname+'.log', 'wt', 0)	# unbuffered
    Trace(count=0, trace=1,
          ignoremods=['codecs','fnmatch','glob','posixpath','_core']
          ).runfunc(app.MainLoop)
else:
    app.MainLoop()

# Save prefs
prefs.write()
if __debug__: print "Main thread done"

