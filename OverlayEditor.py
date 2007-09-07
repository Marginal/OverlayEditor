#!/usr/bin/python

from glob import glob
from math import cos, floor, sin, pi, sqrt
import os	# for startfile
from os import chdir, getenv, listdir, mkdir, walk
from os.path import abspath, basename, curdir, dirname, exists, expanduser, isdir, join, normpath, pardir, sep
from sys import exit, argv, executable, platform, version

if platform=='win32':
    import wx
else:
    try:
        import wx
    except:
        if platform=='darwin':
            from EasyDialogs import Message
            Message("wxPython is not installed. This application\nrequires wxPython2.5.3-py%s or later." % version[:3])
        else:	# linux
            import tkMessageBox
            tkMessageBox._show("Error", "wxPython is not installed. This application\nrequires python wxgtk2.5.3 or later.", icon="error", type="ok")
        exit(1)
    try:
        import OpenGL
    except:
        if platform=='darwin':
            from EasyDialogs import Message
            Message("PyOpenGL is not installed. This application\nrequires PyOpenGL2 or later.")
        else:	# linux
            import tkMessageBox
            tkMessageBox._show("Error", "PyOpenGL is not installed. This application\nrequires PyOpenGL2 or later.", icon="error", type="ok")
        exit(1)
from wx.lib.masked import NumCtrl, EVT_NUM, NumberUpdatedEvent
#from OpenGL.GL import *

if not 'startfile' in dir(os):
    import types
    # Causes problems under py2exe & not needed
    from urllib import quote
    import webbrowser

from clutter import round2res, minres, latlondisp, Exclude	# for loading exclusions into palette
from clutterdef import KnownDefs
from draw import MyGL
from files import importObj, readApt, readNav,readLib, sortfolded
from palette import Palette
from DSFLib import readDSF, writeDSF
from MessageBox import myMessageBox, AboutBox
from prefs import Prefs
from version import appname, appversion


# Path validation
mypath=dirname(abspath(argv[0]))
if not isdir(mypath):
    exit('"%s" is not a folder' % mypath)
if basename(mypath)=='MacOS':
    chdir(normpath(join(mypath,pardir)))	# Starts in MacOS folder
else:
    chdir(mypath)

# constants
d2r=pi/180.0
zoom=sqrt(2)
zoom2=2
maxzoom=32768*zoom
gresources='[rR][eE][sS][oO][uU][rR][cC][eE][sS]'
gnavdata='[eE][aA][rR][tT][hH] [nN][aA][vV] [dD][aA][tT][aA]'
gaptdat=join(gnavdata,'[aA][pP][tT].[dD][aA][tT]')
gmainaptdat=join(gresources,gaptdat)
gmainnavdat=join(gresources,gnavdata,'[nN][aA][vV].[dD][aA][tT]')
gdefault=join(gresources,'[dD][eE][fF][aA][uU][lL][tT] [sS][cC][eE][nN][eE][rR][yY]')
gcustom='[cC][uU][sS][tT][oO][mM] [sS][cC][eE][nN][eE][rR][yY]'
glibrary='[lL][iI][bB][rR][aA][rR][yY].[tT][xX][tT]'


global prefs


if platform=='darwin':
    from Carbon import Menu
    from EasyDialogs import AskFolder
    # Hack: wxMac 2.5 requires the following to get shadows to look OK:
    # ... wx.ALIGN_CENTER_VERTICAL|wx.TOP|wx.BOTTOM, 2)
    pad=2
    browse="Choose..."
else:
    pad=0
    browse="Browse..."

class myCreateStdDialogButtonSizer(wx.BoxSizer):
    # Dialog.CreateStdDialogButtonSizer for pre 2.6
    def __init__(self, parent, style):
        assert not (style & ~(wx.OK|wx.CANCEL))
        wx.BoxSizer.__init__(self, wx.HORIZONTAL)

        ok=style&wx.OK
        no=style&wx.CANCEL
        
        # adjust order of buttons per Windows or Mac conventions
        if platform!='darwin':
            if ok: buttonok=wx.Button(parent, wx.ID_OK)
            if no: buttonno=wx.Button(parent, wx.ID_CANCEL)
            self.Add([0,0], 1)		# push following buttons to right
            if ok: self.Add(buttonok, 0, wx.ALL, pad)
            if ok and no: self.Add([6,0], 0)	# cosmetic
            if no: self.Add(buttonno, 0, wx.ALL, pad)
        else:
            if no: buttonno=wx.Button(parent, wx.ID_CANCEL)
            if ok: buttonok=wx.Button(parent, wx.ID_OK)
            self.Add([0,0], 1)		# push following buttons to right
            if no: self.Add(buttonno, 0, wx.ALL|wx.ALIGN_CENTER_VERTICAL, pad)
            if ok and no: self.Add([6,0], 0)	# cosmetic
            if ok: self.Add(buttonok, 0, wx.ALL|wx.ALIGN_CENTER_VERTICAL, pad)
            self.Add([0,0], 1)	# centre
        if ok: buttonok.SetDefault()


class myListBox(wx.VListBox):
    # regular ListBox is too slow to create esp on wxMac 2.5
    def __init__(self, parent, id, style=0, choices=[]):

        self.height=self.indent=1	# need something
        self.choices=choices
        self.actfg=wx.SystemSettings_GetColour(wx.SYS_COLOUR_HIGHLIGHTTEXT)
        self.actbg=wx.SystemSettings_GetColour(wx.SYS_COLOUR_HIGHLIGHT)
        self.inafg=wx.SystemSettings_GetColour(wx.SYS_COLOUR_MENUTEXT)
        self.inabg=wx.SystemSettings_GetColour(wx.SYS_COLOUR_MENU)
        if platform=='win32':
            self.font=wx.SystemSettings_GetFont(wx.SYS_DEFAULT_GUI_FONT)

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
        self.SetSelectionBackground(self.actbg)
        sel=self.GetSelection()
        if sel>=0: self.RefreshLine(sel)
        
    def OnKillFocus(self, event):
        self.timer.Stop()
        self.sel=''
        self.SetSelectionBackground(self.inabg)
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
        if platform=='win32': dc.SetFont(self.font)	# wtf?
        if self.GetSelection()==n and self.FindFocus()==self:
            dc.SetTextForeground(self.actfg)
        else:
            dc.SetTextForeground(self.inafg)
        dc.DrawText(self.choices[n], rect.x+self.indent, rect.y)

    def OnKeyDown(self, event):
        # wxMac 2.5 doesn't handle cursor movement
        if event.m_keyCode in [wx.WXK_UP, wx.WXK_NUMPAD_UP] and self.GetSelection()>0:
            self.SetSelection(self.GetSelection()-1)
        elif event.m_keyCode in [wx.WXK_DOWN, wx.WXK_NUMPAD_DOWN] and self.GetSelection()<len(self.choices)-1:
            self.SetSelection(self.GetSelection()+1)
        elif event.m_keyCode in [wx.WXK_HOME, wx.WXK_NUMPAD_HOME]:
            self.SetSelection(0)
        elif event.m_keyCode in [wx.WXK_END, wx.WXK_NUMPAD_END]:
            self.SetSelection(len(self.choices)-1)
        elif event.m_keyCode in [wx.WXK_PAGEUP, wx.WXK_PRIOR, wx.WXK_NUMPAD_PAGEUP, wx.WXK_NUMPAD_PRIOR]:
            self.ScrollPages(-1)
            self.SetSelection(max(0,
                                  self.GetSelection()-self.GetClientSize().y/self.height))
        elif event.m_keyCode in [wx.WXK_PAGEDOWN, wx.WXK_NEXT, wx.WXK_NUMPAD_PAGEDOWN, wx.WXK_NUMPAD_NEXT]:
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
        
        c=chr(event.m_keyCode).lower()
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

        self.choice=None

        self.aptcode={}
        self.aptname={}
        for code, stuff in airports.iteritems():
            (name, loc, run)=stuff
            self.aptcode['%s - %s' % (code, name)]=loc
            self.aptname['%s - %s' % (name, code)]=loc

        wx.Dialog.__init__(self, parent, wx.ID_ANY, "Go to")
        wx.EVT_CLOSE(self, self.OnClose)

        numid=wx.NewId()
        if platform=='darwin':
            bg=wx.Colour(254,254,254)	# Odd colours = black on wxMac !!!
        else:
            bg=wx.SystemSettings_GetColour(wx.SYS_COLOUR_WINDOW)
        fg=wx.SystemSettings_GetColour(wx.SYS_COLOUR_MENUTEXT)

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
        locbox.Add(wx.StaticText(self, -1, '  Latitude:'), 1, wx.ALIGN_CENTER_VERTICAL|wx.ALIGN_LEFT|wx.ALL, pad)
        self.lat=NumCtrl(self, numid, 0, integerWidth=3, fractionWidth=6,
                         min=-89.999999, max=89.999999, limited=True,
                         selectOnEntry=False,
                         foregroundColour=fg, signedForegroundColour=fg,
                         validBackgroundColour = bg,
                         invalidBackgroundColour = "Red")
        if platform=='darwin':	# auto-size broken - wrong font?
            (c,y)=self.lat.GetSize()
            (x,c)=self.lat.GetTextExtent("-888.8888888")
            numsize=(x,y)
        else:
            numsize=self.lat.GetSize()
        self.lat.SetMinSize(numsize)
        locbox.Add(self.lat, 1, wx.BOTTOM|wx.RIGHT|wx.EXPAND, pad)
        
        locbox.Add(wx.StaticText(self, -1, '  Longitude:'), 1, wx.ALIGN_CENTER_VERTICAL|wx.ALIGN_LEFT|wx.ALL, pad)
        self.lon=NumCtrl(self, numid, 0, integerWidth=3, fractionWidth=6,
                         min=-179.999999, max=179.999999, limited=True,
                         selectOnEntry=False,
                         foregroundColour=fg, signedForegroundColour=fg,
                         validBackgroundColour = bg,
                         invalidBackgroundColour = "Red")
        self.lon.SetMinSize(numsize)
        locbox.Add(self.lon, 1, wx.BOTTOM|wx.RIGHT|wx.EXPAND, pad)
        box3.Add(locbox, 1, wx.ALL|wx.EXPAND, pad)
        EVT_NUM(self, numid, self.OnLoc)	# All numeric fields
        grid1.Add(box3, 0, wx.LEFT|wx.BOTTOM|wx.EXPAND, 14) #
        
        box4=myCreateStdDialogButtonSizer(self, wx.OK|wx.CANCEL)
        self.ok=self.FindWindowById(wx.ID_OK)
        self.ok.Disable()
        #box0=wx.BoxSizer(wx.VERTICAL)
        #box0.Add(grid1, 1, wx.ALL|wx.EXPAND, 14)
        #box0.Add(box4, 0, wx.ALL|wx.EXPAND, 14)
        #self.SetSizerAndFit(box0)
        grid1.Add(box4, 1, wx.ALL|wx.ALIGN_RIGHT|wx.ALIGN_BOTTOM, 14)
        self.SetSizerAndFit(grid1)

    def OnClose(self, event):
        # Prevent kill focus event causing refresh on wxMac 2.5
        self.list1.SetSelection(-1)
        self.list2.SetSelection(-1)
        self.Destroy()

    def OnName(self, event):
        choice=event.GetEventObject().GetStringSelection()
        if choice:
            self.choice=self.aptname[choice]
            self.ok.Enable()
        event.Skip()

    def OnCode(self, event):
        choice=event.GetEventObject().GetStringSelection()
        if choice:
            self.choice=self.aptcode[choice]
            self.ok.Enable()
        event.Skip()

    def OnLoc(self, event):
        self.choice=(self.lat.GetValue(), self.lon.GetValue())
        self.ok.Enable()

    def show(self, loc):
        self.lat.SetValue(loc[0])
        self.lon.SetValue(loc[1])
        self.ok.Disable()
        self.choice=None
        if self.ShowModal()!=wx.ID_OK: return None
        return self.choice


class PreferencesDialog(wx.Dialog):

    def __init__(self, parent, id, title):
        wx.Dialog.__init__(self, parent, id, title)
        if platform=='darwin':	# Default is too big on Mac
            self.SetWindowVariant(wx.WINDOW_VARIANT_SMALL)
            
        panel1 = wx.Panel(self,-1)
        panel2 = wx.Panel(self,-1)
        panel3 = wx.Panel(self,-1)

        box1 = wx.StaticBoxSizer(wx.StaticBox(panel1, -1, 'X-Plane location'),
                                 wx.VERTICAL)
        self.path = wx.TextCtrl(panel1, -1, style=wx.TE_READONLY)
        self.path.SetMinSize((300, -1))
        if prefs.xplane: self.path.SetValue(prefs.xplane)
        browsebtn=wx.Button(panel1, -1, browse)
        box1.Add(self.path, 1, wx.ALIGN_CENTER|wx.ALL, 4)
        box1.Add(browsebtn, 0, wx.ALIGN_RIGHT|wx.ALL, 4)
        panel1.SetSizer(box1)

        self.display = wx.RadioBox(panel2, -1, "Terrain", style=wx.VERTICAL,
                                   choices=["No terrain", "Show terrain", "Show terrain and elevation"])
        if prefs.options&Prefs.TERRAIN:
            if prefs.options&Prefs.ELEVATION:
                self.display.SetSelection(2)
            else:
                self.display.SetSelection(1)
        box2 = wx.BoxSizer()
        box2.Add(self.display, 1)
        panel2.SetSizer(box2)

        self.latlon = wx.RadioBox(panel3, -1, "Latitude && Longitude", style=wx.VERTICAL,
                                   choices=["Decimal", u"dd\u00B0mm'ss\""])
        if prefs.options&Prefs.DMS: self.latlon.SetSelection(1)
        box3 = wx.BoxSizer()
        box3.Add(self.latlon, 1)
        panel3.SetSizer(box3)

        box4=myCreateStdDialogButtonSizer(self, wx.OK|wx.CANCEL)

        box0 = wx.BoxSizer(wx.VERTICAL)
        box0.Add(panel1, 0, wx.LEFT|wx.RIGHT|wx.TOP|wx.EXPAND, 10)
        box0.Add(panel2, 0, wx.LEFT|wx.RIGHT|wx.TOP|wx.EXPAND, 10)
        box0.Add(panel3, 0, wx.LEFT|wx.RIGHT|wx.TOP|wx.EXPAND, 10)
        box0.Add(box4, 0, wx.ALL|wx.EXPAND, 10)

        wx.EVT_BUTTON(self, browsebtn.GetId(), self.OnBrowse)
        self.SetSizerAndFit(box0)

    def OnBrowse(self, event):
        while True:
            if platform=='darwin':
                path=AskFolder('Please locate your X-Plane folder', defaultLocation=self.path.GetValue(), wanted=unicode)
                if not path: return wx.ID_CANCEL
            else:
                style=wx.DEFAULT_DIALOG_STYLE|wx.RESIZE_BORDER
                if 'DD_DIR_MUST_EXIST' in dir(wx): style|=wx.DD_DIR_MUST_EXIST
                dlg=wx.DirDialog(self, 'Please locate your X-Plane folder', self.path.GetValue(), style)
                if dlg.ShowModal()!=wx.ID_OK:
                    dlg.Destroy()
                    return wx.ID_CANCEL
                path=dlg.GetPath()
                dlg.Destroy()
            if glob(join(path, gcustom)) and glob(join(path, gmainaptdat)):
                self.path.SetValue(path.strip())
                self.FindWindowById(wx.ID_OK).Enable()
                return wx.ID_OK

class BackgroundDialog(wx.Dialog):

    def __init__(self, parent, id, title):
        wx.Dialog.__init__(self, parent, id, title)
        if platform=='darwin':	# Default is too big on Mac
            self.SetWindowVariant(wx.WINDOW_VARIANT_SMALL)
            bg=wx.Colour(254,254,254)	# Odd colours = black on wxMac !!!
        else:
            bg=wx.SystemSettings_GetColour(wx.SYS_COLOUR_WINDOW)
        fg=wx.SystemSettings_GetColour(wx.SYS_COLOUR_MENUTEXT)

        self.parent=parent
        self.prefix=glob(join(prefs.xplane,gcustom,prefs.package))[0]
        if prefs.package in prefs.packageprops:
            (self.image, plat, plon, phdg, pwidth, plength, popacity)=prefs.packageprops[prefs.package]
            if self.image[0]==curdir:
                self.image=join(self.prefix, normpath(self.image))
        else:
            self.image=None
            plat=parent.loc[0]
            plon=parent.loc[1]
            phdg=parent.hdg
            pwidth=plength=100.0
            popacity=50.0

        if platform=='darwin':
            textstyle=wx.ALIGN_RIGHT
        else:
            textstyle=0
        (x,y)=self.GetTextExtent("Length:")
        textsize=(x+pad,y+pad)
        numid=wx.NewId()

        panel1 = wx.Panel(self,-1)
        panel2 = wx.Panel(self,-1)
        panel3 = wx.Panel(self,-1)
        panel4 = wx.Panel(self,-1)

        box1 = wx.StaticBoxSizer(wx.StaticBox(panel1, -1, 'File'),
                                 wx.VERTICAL)
        self.path = wx.TextCtrl(panel1, -1, style=wx.TE_READONLY)
        self.path.SetMinSize((300, -1))
        self.clearbtn=wx.Button(panel1, wx.ID_CLEAR)
        self.browsebtn=wx.Button(panel1, -1, browse)
        grid1 = wx.FlexGridSizer()
        grid1.AddGrowableCol(0, proportion=1)
        grid1.Add([0,0], 1, wx.ALIGN_CENTER|wx.ALL, pad)
        grid1.Add(self.clearbtn, 0, wx.ALIGN_CENTER|wx.ALL, pad)
        grid1.Add([6,0], 0)	# cosmetic
        grid1.Add(self.browsebtn, 0, wx.ALIGN_CENTER|wx.ALL, pad)
        box1.Add(self.path, 1, wx.ALIGN_CENTER|wx.ALL, 4)
        box1.Add(grid1, 1, wx.LEFT|wx.RIGHT|wx.EXPAND, 4)
        self.browsebtn.SetDefault()
        panel1.SetSizer(box1)

        box2 = wx.StaticBoxSizer(wx.StaticBox(panel2, -1, 'Location'))
        self.lat=NumCtrl(panel2, numid, plat, integerWidth=3, fractionWidth=6,
                         min=-89.999999, max=89.999999, limited=True,
                         selectOnEntry=False,
                         foregroundColour=fg, signedForegroundColour=fg,
                         validBackgroundColour = bg,
                         invalidBackgroundColour = "Red")
        if platform=='darwin':	# auto-size broken - wrong font?
            (c,y)=self.lat.GetSize()
            (x,c)=self.lat.GetTextExtent("-888.8888888")
            numsize=(x,y)
        else:
            numsize=self.lat.GetSize()
        self.lat.SetMinSize(numsize)
        self.lon=NumCtrl(panel2, numid, plon, integerWidth=3, fractionWidth=6,
                         min=-179.999999, max=179.999999, limited=True,
                         selectOnEntry=False,
                         foregroundColour=fg, signedForegroundColour=fg,
                         validBackgroundColour = bg,
                         invalidBackgroundColour = "Red")
        self.lon.SetMinSize(numsize)
        self.hdg=NumCtrl(panel2, numid, phdg, integerWidth=3,
                         min=0, max=359, limited=True,
                         selectOnEntry=False,
                         foregroundColour=fg, signedForegroundColour=fg,
                         validBackgroundColour = bg,
                         invalidBackgroundColour="Red")
        self.hdg.SetMinSize(numsize)
        grid2 = wx.FlexGridSizer(2, 5, 6, 6)
        grid2.AddGrowableCol(2, proportion=1)
        grid2.Add(wx.StaticText(panel2, -1, 'Lat:', size=textsize, style=textstyle), 0, wx.ALIGN_CENTER, pad)
        grid2.Add(self.lat, 0, wx.ALIGN_CENTER_VERTICAL, pad)
        grid2.Add([0,0], 1, wx.ALIGN_CENTER|wx.ALL, pad)
        grid2.Add(wx.StaticText(panel2, -1, 'Hdg:', size=textsize, style=textstyle), 0, wx.ALIGN_CENTER, pad)
        grid2.Add(self.hdg, 0, wx.ALIGN_CENTER_VERTICAL, pad)
        grid2.Add(wx.StaticText(panel2, -1, 'Lon:', size=textsize, style=textstyle), 0, wx.ALIGN_CENTER, pad)
        grid2.Add(self.lon, 0, wx.ALIGN_CENTER_VERTICAL, pad)
        box2.Add(grid2, 1, wx.ALL|wx.EXPAND, 4)
        panel2.SetSizer(box2)

        box3 = wx.StaticBoxSizer(wx.StaticBox(panel3, -1, 'Size'))
        self.width=NumCtrl(panel3, numid, pwidth, integerWidth=4, fractionWidth=2,
                           allowNegative=False, min=0, limited=True,
                           groupDigits=False, selectOnEntry=False,
                           foregroundColour=fg, signedForegroundColour=fg,
                           validBackgroundColour = bg,
                           invalidBackgroundColour = "Red")
        self.width.SetMinSize(numsize)
        self.length=NumCtrl(panel3, numid, plength, integerWidth=4, fractionWidth=2,
                            allowNegative=False, min=0, limited=True,
                            groupDigits=False, selectOnEntry=False,
                            foregroundColour=fg, signedForegroundColour=fg,
                            validBackgroundColour = bg,
                            invalidBackgroundColour = "Red")
        self.length.SetMinSize(numsize)
        grid3 = wx.FlexGridSizer(1, 5, 6, 6)
        grid3.AddGrowableCol(2, proportion=1)
        grid3.Add(wx.StaticText(panel3, -1, 'Width:', size=textsize, style=textstyle), 1, wx.ALIGN_CENTER, pad)
        grid3.Add(self.width, 1, wx.ALIGN_CENTER_VERTICAL, pad)
        grid3.Add([0,0], 1, wx.ALIGN_CENTER|wx.ALL, pad)
        grid3.Add(wx.StaticText(panel3, -1, 'Length:', size=textsize, style=textstyle), 1, wx.ALIGN_CENTER, pad)
        grid3.Add(self.length, 1, wx.ALIGN_CENTER_VERTICAL, pad)
        box3.Add(grid3, 1, wx.ALL|wx.EXPAND, 4)
        panel3.SetSizer(box3)

        box4 = wx.StaticBoxSizer(wx.StaticBox(panel4, -1, 'Opacity'))
        self.opacity=wx.Slider(panel4, -1, popacity, 0, 100,
                               style=wx.SL_LABELS)
        #self.opacity.SetTickFreq(10, 1)
        box4.Add(self.opacity, 1, wx.ALL|wx.EXPAND, pad)
        panel4.SetSizer(box4)

        box0 = wx.BoxSizer(wx.VERTICAL)
        box0.Add(panel1, 0, wx.ALL|wx.EXPAND, 10)
        box0.Add(panel2, 0, wx.LEFT|wx.RIGHT|wx.EXPAND, 10)
        box0.Add(panel3, 0, wx.LEFT|wx.RIGHT|wx.TOP|wx.EXPAND, 10)
        box0.Add(panel4, 0, wx.ALL|wx.EXPAND, 10)
        self.SetSizerAndFit(box0)
        self.setpath()

        wx.EVT_BUTTON(self, self.clearbtn.GetId(), self.OnClear)
        wx.EVT_BUTTON(self, self.browsebtn.GetId(), self.OnBrowse)
        EVT_NUM(self, numid, self.OnUpdate)	# All numeric fields
        wx.EVT_COMMAND_SCROLL(self,self.opacity.GetId(), self.OnUpdate)
        wx.EVT_KEY_DOWN(self.path, self.OnKeyDown)
        wx.EVT_KEY_DOWN(self.clearbtn, self.OnKeyDown)
        wx.EVT_KEY_DOWN(self.browsebtn, self.OnKeyDown)
        wx.EVT_KEY_DOWN(self.lat, self.OnKeyDown)
        wx.EVT_KEY_DOWN(self.lon, self.OnKeyDown)
        wx.EVT_KEY_DOWN(self.hdg, self.OnKeyDown)
        wx.EVT_KEY_DOWN(self.width, self.OnKeyDown)
        wx.EVT_KEY_DOWN(self.length, self.OnKeyDown)
        wx.EVT_KEY_DOWN(self.opacity, self.OnKeyDown)
        wx.EVT_CLOSE(self, self.OnClose)

        # Remove selection
        self.lat.SetFocus()	# So doesn't complain
        self.parent.canvas.Refresh()

    def OnKeyDown(self, event):
        if not self.image:
            event.Skip(True)
            return
        cursors=[ord('W'), ord('D'), ord('S'), ord('A')]
        if event.m_keyCode in cursors:
            if event.m_controlDown:
                xinc=zinc=0.000001
            else:
                zinc=self.parent.dist/10000000
                if zinc<0.00001: zinc=0.00001
                if event.m_shiftDown: zinc*=10
                xinc=zinc/cos(d2r*self.lat.GetValue())
            hr=d2r*((self.parent.hdg + [0,90,180,270][cursors.index(event.m_keyCode)])%360)
            try:
                self.lat.SetValue(self.lat.GetValue()+zinc*cos(hr))
            except:
                pass
            try:
                self.lon.SetValue(self.lon.GetValue()+xinc*sin(hr))
            except:
                pass
        elif event.m_keyCode==ord('Q'):
            if event.m_shiftDown:
                self.hdg.SetValue((self.hdg.GetValue()-10)%360)
            else:
                self.hdg.SetValue((self.hdg.GetValue()-1)%360)
        elif event.m_keyCode==ord('E'):
            if event.m_shiftDown:
                self.hdg.SetValue((self.hdg.GetValue()+10)%360)
            else:
                self.hdg.SetValue((self.hdg.GetValue()+1)%360)
        elif event.m_keyCode==ord('C') or (platform=='darwin' and event.m_keyCode==ord('J') and event.m_metaDown):
            self.parent.loc=[self.lat.GetValue(),self.lon.GetValue()]
            if event.m_shiftDown:
                self.parent.hdg=self.hdg.GetValue()
            self.parent.canvas.goto(self.parent.loc, self.parent.hdg, self.parent.elev, self.parent.dist)
        else:
            if platform=='darwin' and (event.m_keyCode in range(ord('0'), ord('9')+1) or event.m_keyCode in [wx.WXK_BACK, wx.WXK_DELETE, ord('-')]):
                # Hack!!! changing value doesn't cause event so manually queue
                wx.FutureCall(10, self.OnUpdate, event)
            event.Skip(True)
            return
        if platform=='darwin':
            self.OnUpdate(event)	# SetValue() doesn't cause event
        event.Skip(False)

    def OnClear(self, event):
        self.lat.SetFocus()	# So doesn't complain
        self.image=None
        self.setpath()
        self.OnUpdate(event)

    def OnBrowse(self, event):
        self.lat.SetFocus()	# So doesn't complain
        if self.image:
            if self.image[0]==curdir:
                dir=dirname(join(self.prefix, normpath(self.image)))
            else:
                dir=dirname(self.image)
            f=basename(self.image)
        else:
            dir=self.prefix
            f=''
        dlg=wx.FileDialog(self, "Location of background image:", dir, f,
                          "Image files|*.bmp;*.jpg;*.jpeg;*.png|BMP files (*.bmp)|*.bmp|JPEG files (*.jpg, *.jpeg)|*.jpg;*.jpeg|PNG files (*.png)|*.png|All files|*.*",
                          wx.OPEN|wx.HIDE_READONLY)
        if dlg.ShowModal()==wx.ID_OK:
            self.image=dlg.GetPath()
            self.setpath()
            self.OnUpdate(event)
        dlg.Destroy()

    def OnUpdate(self, event):
        if event.GetEventType()==wx.wxEVT_SCROLL_THUMBTRACK:
            return	# Wait til user stops scrolling
        if not self.image:
            prefs.packageprops.pop(prefs.package, None)
            self.parent.canvas.setbackground(None)
            return
        f=self.image
        if f.startswith(self.prefix): f=curdir+f[len(self.prefix):]
        prefs.packageprops[prefs.package]=(f, self.lat.GetValue(), self.lon.GetValue(), self.hdg.GetValue()%360, self.width.GetValue(), self.length.GetValue(), self.opacity.GetValue())
        self.parent.canvas.setbackground((self.image, self.lat.GetValue(), self.lon.GetValue(), self.hdg.GetValue()%360, self.width.GetValue(), self.length.GetValue(), self.opacity.GetValue()), 0)

    def setpath(self):
        if not self.image:
            self.clearbtn.Disable()
            self.lat.Disable()
            self.lon.Disable()
            self.hdg.Disable()
            self.width.Disable()
            self.length.Disable()
            self.opacity.Disable()
            self.path.SetValue('')
            return

        self.clearbtn.Enable()
        self.lat.Enable()
        self.lon.Enable()
        self.hdg.Enable()
        self.width.Enable()
        self.length.Enable()
        self.opacity.Enable()
        label=self.image
        if label.startswith(self.prefix): label=label[len(self.prefix)+1:]
        (x,y)=self.path.GetClientSize()
        (x1,y1)=self.GetTextExtent(label)
        if x1<x:
            self.path.SetValue(label)
            return
        while sep in label:
            label=label[label.index(sep)+1:]
            (x1,y1)=self.GetTextExtent('...'+sep+label)
            if x1<x: break
        self.path.SetValue('...'+sep+label)

    def OnClose(self, event):
        # Prevent kill focus event causing crash on wxMac 2.5
        self.path.SetFocus()
        self.Destroy()


# The app
class MainWindow(wx.Frame):
    def __init__(self, parent, id, title):

        self.loc=None	# (lat,lon)
        self.hdg=0
        self.elev=45
        self.dist=2048*zoom
        self.airports={}	# default apt.dat, by code
        self.nav=[]
        self.goto=None	# goto dialog
        self.bkgd=None	# background bitmap dialog

        wx.Frame.__init__(self, parent, id, title)
        wx.EVT_CLOSE(self, self.OnClose)
        wx.EVT_KEY_DOWN(self, self.OnKeyDown)
        wx.EVT_MOUSEWHEEL(self, self.OnMouseWheel)
        
        if platform=='win32':
            self.SetIcon(wx.Icon(executable, wx.BITMAP_TYPE_ICO))
            self.menubar=None
        elif platform.lower().startswith('linux'):	# PNG supported by GTK
            self.SetIcon(wx.Icon('Resources/%s.png' % appname,
                                 wx.BITMAP_TYPE_PNG))
            self.menubar=None
        elif platform=='darwin':
            # icon pulled from Resources via Info.plist. Need minimal menu
            # http://developer.apple.com/documentation/UserExperience/Conceptual/OSXHIGuidelines/XHIGMenus/chapter_16_section_4.html
            self.menubar = wx.MenuBar()
            filemenu = wx.Menu()
            filemenu.Append(wx.ID_NEW, u'New\u2026\tCtrl-N')
            wx.EVT_MENU(self, wx.ID_NEW, self.OnNew)
            filemenu.Append(wx.ID_OPEN, u'Open\u2026\tCtrl-O')
            wx.EVT_MENU(self, wx.ID_OPEN, self.OnOpen)
            filemenu.Append(wx.ID_SAVE, u'Save\tCtrl-S')
            wx.EVT_MENU(self, wx.ID_SAVE, self.OnSave)
            filemenu.AppendSeparator()
            filemenu.Append(wx.ID_PASTE, u'Import\u2026')
            wx.EVT_MENU(self, wx.ID_PASTE, self.OnImport)
            # ID_EXIT moved to application menu
            filemenu.Append(wx.ID_EXIT, u'Quit %s\tCtrl-Q' % appname)
            wx.EVT_MENU(self, wx.ID_EXIT, self.OnClose)	# generates commnd evt
            self.menubar.Append(filemenu, 'File')

            editmenu = wx.Menu()
            editmenu.Append(wx.ID_UNDO, u'Undo\tCtrl-Z')
            wx.EVT_MENU(self, wx.ID_UNDO, self.OnUndo)
            editmenu.AppendSeparator()
            editmenu.Append(wx.ID_ADD, u'Add\tEnter')
            wx.EVT_MENU(self, wx.ID_ADD, self.OnAdd)
            editmenu.Append(wx.ID_DELETE, u'Delete')
            wx.EVT_MENU(self, wx.ID_DELETE, self.OnDelete)
            # ID_PREFERENCES moved to application menu
            editmenu.Append(wx.ID_PREFERENCES, u'Preferences\tCtrl-,')
            wx.EVT_MENU(self, wx.ID_PREFERENCES, self.OnPrefs)
            self.menubar.Append(editmenu, u'Edit')

            viewmenu = wx.Menu()
            viewmenu.Append(wx.ID_PREVIEW, u'Background image\u2026')
            wx.EVT_MENU(self, wx.ID_PREVIEW, self.OnBackground)
            viewmenu.Append(wx.ID_REFRESH, u'Reload')
            wx.EVT_MENU(self, wx.ID_REFRESH, self.OnReload)
            viewmenu.Append(wx.ID_FORWARD, u'Go To\u2026')
            wx.EVT_MENU(self, wx.ID_FORWARD, self.OnGoto)
            self.menubar.Append(viewmenu, u'View')

            helpmenu = wx.Menu()
            helpmenu.Append(wx.ID_HELP, u'%s Help\tCtrl-?'  % appname)
            wx.EVT_MENU(self, wx.ID_HELP, self.OnHelp)
            # ID_ABOUT moved to application menu
            helpmenu.Append(wx.ID_ABOUT, u'About %s'  % appname)
            wx.EVT_MENU(self, wx.ID_ABOUT, self.OnAbout)
            self.menubar.Append(helpmenu, u'&Help')
            self.SetMenuBar(self.menubar)

        self.toolbar=self.CreateToolBar(wx.TB_HORIZONTAL|wx.STATIC_BORDER|wx.TB_FLAT|wx.TB_NODIVIDER)
        # Note colours>~(245,245,245) get replaced by transparent
        newbitmap=wx.Bitmap("Resources/new.png", wx.BITMAP_TYPE_PNG)
        self.toolbar.SetToolBitmapSize((newbitmap.GetWidth(),
                                   newbitmap.GetHeight()))
        self.toolbar.SetToolSeparation(newbitmap.GetWidth()/4)
        self.toolbar.AddLabelTool(wx.ID_NEW, 'New',
                                  newbitmap,
                                  wx.NullBitmap, 0,
                                  'New scenery package')
        wx.EVT_TOOL(self.toolbar, wx.ID_NEW, self.OnNew)
        self.toolbar.AddLabelTool(wx.ID_OPEN, 'Open',
                                  wx.Bitmap("Resources/open.png",
                                            wx.BITMAP_TYPE_PNG),
                                  wx.NullBitmap, 0,
                                  'Open scenery package')
        wx.EVT_TOOL(self.toolbar, wx.ID_OPEN, self.OnOpen)
        self.toolbar.AddLabelTool(wx.ID_SAVE, 'Save',
                                  wx.Bitmap("Resources/save.png",
                                            wx.BITMAP_TYPE_PNG),
                                  wx.NullBitmap, 0,
                                  'Save scenery package')
        wx.EVT_TOOL(self.toolbar, wx.ID_SAVE, self.OnSave)
        self.toolbar.AddLabelTool(wx.ID_PASTE, 'Import',
                                  wx.Bitmap("Resources/import.png",
                                            wx.BITMAP_TYPE_PNG),
                                  wx.NullBitmap, 0,
                                  'Import objects from another package')
        wx.EVT_TOOL(self.toolbar, wx.ID_PASTE, self.OnImport)
        self.toolbar.AddSeparator()
        self.toolbar.AddLabelTool(wx.ID_ADD, 'Add',
                                  wx.Bitmap("Resources/add.png",
                                            wx.BITMAP_TYPE_PNG),
                                  wx.NullBitmap, 0,
                                  'Add new object')
        wx.EVT_TOOL(self.toolbar, wx.ID_ADD, self.OnAdd)
        self.toolbar.AddLabelTool(wx.ID_DELETE, 'Delete',
                                  wx.Bitmap("Resources/delete.png",
                                            wx.BITMAP_TYPE_PNG),
                                  wx.NullBitmap, 0,
                                  'Delete selected object(s)')
        wx.EVT_TOOL(self.toolbar, wx.ID_DELETE, self.OnDelete)
        self.toolbar.AddLabelTool(wx.ID_UNDO, 'Undo',
                                  wx.Bitmap("Resources/undo.png",
                                            wx.BITMAP_TYPE_PNG),
                                  wx.NullBitmap, 0,
                                  'Undo last edit')
        wx.EVT_TOOL(self.toolbar, wx.ID_UNDO, self.OnUndo)
        self.toolbar.AddSeparator()
        self.toolbar.AddLabelTool(wx.ID_PREVIEW, 'Background',
                                  wx.Bitmap("Resources/background.png",
                                            wx.BITMAP_TYPE_PNG),
                                  wx.NullBitmap, 0,
                                  'Adjust background image')
        wx.EVT_TOOL(self.toolbar, wx.ID_PREVIEW, self.OnBackground)
        self.toolbar.AddLabelTool(wx.ID_REFRESH, 'Reload',
                                  wx.Bitmap("Resources/reload.png",
                                            wx.BITMAP_TYPE_PNG),
                                  wx.NullBitmap, 0,
                                  "Reload package's objects, textures and airports")
        wx.EVT_TOOL(self.toolbar, wx.ID_REFRESH, self.OnReload)
        self.toolbar.AddLabelTool(wx.ID_FORWARD, 'Go To',
                                  wx.Bitmap("Resources/goto.png",
                                            wx.BITMAP_TYPE_PNG),
                                  wx.NullBitmap, 0,
                                  'Go to airport')
        wx.EVT_TOOL(self.toolbar, wx.ID_FORWARD, self.OnGoto)
        self.toolbar.AddSeparator()
        self.toolbar.AddLabelTool(wx.ID_PREFERENCES, 'Preferences',
                                  wx.Bitmap("Resources/prefs.png",
                                            wx.BITMAP_TYPE_PNG),
                                  wx.NullBitmap, 0,
                                  'Preferences')
        wx.EVT_TOOL(self.toolbar, wx.ID_PREFERENCES, self.OnPrefs)
        self.toolbar.AddSeparator()
        self.toolbar.AddLabelTool(wx.ID_HELP, 'Help',
                                  wx.Bitmap("Resources/help.png",
                                            wx.BITMAP_TYPE_PNG),
                                  wx.NullBitmap, 0,
                                  'Help')
        wx.EVT_TOOL(self.toolbar, wx.ID_HELP, self.OnHelp)
        
	self.toolbar.Realize()
        self.toolbar.EnableTool(wx.ID_SAVE, False)
        self.toolbar.EnableTool(wx.ID_ADD, False)
        self.toolbar.EnableTool(wx.ID_DELETE, False)
        self.toolbar.EnableTool(wx.ID_UNDO, False)
        self.toolbar.EnableTool(wx.ID_PREVIEW, False)
        self.toolbar.EnableTool(wx.ID_REFRESH, False)
        self.toolbar.EnableTool(wx.ID_PASTE, False)
        if self.menubar:
            self.menubar.Enable(wx.ID_SAVE, False)
            self.menubar.Enable(wx.ID_ADD, False)
            self.menubar.Enable(wx.ID_DELETE, False)
            self.menubar.Enable(wx.ID_UNDO, False)
            self.menubar.Enable(wx.ID_PREVIEW, False)
            self.menubar.Enable(wx.ID_REFRESH, False)
            self.menubar.Enable(wx.ID_PASTE, False)

        # Hack: Use zero-sized first field to hide toolbar button long help
        self.statusbar=self.CreateStatusBar(3, wx.ST_SIZEGRIP)
        (x,y)=self.statusbar.GetTextExtent(u'  Lat: 99\u00B099\'99.999"W  Lon: 999\u00B099\'99.999"W  Hdg: 999.9  Elv: 9999.9  ')
        self.statusbar.SetStatusWidths([0, x+50,-1])

        self.splitter=wx.SplitterWindow(self, wx.ID_ANY,
                                        style=wx.SP_3DSASH|wx.SP_NOBORDER|wx.SP_LIVE_UPDATE)
        self.splitter.SetWindowStyle(self.splitter.GetWindowStyle() & ~wx.TAB_TRAVERSAL)	# wx.TAB_TRAVERSAL is set behind our backs - this fucks up cursor keys
        self.canvas = MyGL(self.splitter, self) # needed by palette!
        self.palette = Palette(self.splitter, self)
        self.splitter.SetMinimumPaneSize(100)
        self.splitter.SplitVertically(self.canvas, self.palette)
        box0=wx.BoxSizer()
        box0.Add(self.splitter, 1, wx.EXPAND)
        self.SetSizerAndFit(box0)
        self.SetAutoLayout(True)
        self.SetSize((800,600))
        self.SetMinSize((600,400))
        self.lastwidth=self.GetSize().x
        wx.EVT_SIZE(self, self.OnSize)
        wx.EVT_SPLITTER_SASH_POS_CHANGING(self.splitter, self.splitter.GetId(), self.OnSashPositionChanging)

        self.Show(True)

        if platform=='darwin':
            # Hack! Change name on application menu. wxMac always uses id 1.
            try:
                Menu.GetMenuHandle(1).SetMenuTitleWithCFString(appname)
            except:
                pass

        self.splitter.SetSashPosition(self.canvas.GetClientSize()[1], True)
        self.canvas.glInit()	# Must be after show
        self.palette.glInit()	# Must be after show
        self.Update()


    def ShowLoc(self):
        if prefs.options&Prefs.ELEVATION:
            self.statusbar.SetStatusText("%s  Hdg: %-5.1f  Elv: %-6.1f" % (latlondisp(prefs.options&Prefs.DMS, self.loc[0], self.loc[1]), self.hdg, self.canvas.getheight()), 1)
        else:
            self.statusbar.SetStatusText("%s  Hdg: %-5.1f" % (latlondisp(prefs.options&Prefs.DMS, self.loc[0], self.loc[1]), self.hdg), 1)

    def ShowSel(self):
        (names,string,lat,lon,hdg)=self.canvas.getsel(prefs.options&Prefs.DMS)
        if names:
            for name in names:
                if name!=names[0]:
                    self.palette.set(None)
                    break
            else:
                self.palette.set(names[0])
            self.toolbar.EnableTool(wx.ID_DELETE, True)
            if self.menubar: self.menubar.Enable(wx.ID_DELETE, True)
        else:
            self.palette.set(None)
            self.toolbar.EnableTool(wx.ID_DELETE, False)
            if self.menubar: self.menubar.Enable(wx.ID_DELETE, False)
        self.statusbar.SetStatusText(string, 2)

    def OnSize(self, event):
        # emulate sash gravity = 1.0
        delta=event.GetSize().x-self.lastwidth
        #print "size", delta
        pos=self.splitter.GetSashPosition()+delta
        if pos<300: pos=300	# required for preview
        self.splitter.SetSashPosition(pos, False)
        self.lastwidth=event.GetSize().x
        event.Skip()

    def OnSashPositionChanging(self, event):
        #print "sash", event.GetSashPosition()
        if event.GetSashPosition()<300:
            # One-way minimum pane size
            event.SetSashPosition(300)

    def OnKeyDown(self, event):
        changed=False
        cursors=[wx.WXK_UP, wx.WXK_RIGHT, wx.WXK_DOWN, wx.WXK_LEFT,
                 wx.WXK_NUMPAD_UP, wx.WXK_NUMPAD_RIGHT, wx.WXK_NUMPAD_DOWN, wx.WXK_NUMPAD_LEFT,
                 ord('W'), ord('D'), ord('S'), ord('A'),
                 wx.WXK_NUMPAD8, wx.WXK_NUMPAD6, wx.WXK_NUMPAD2, wx.WXK_NUMPAD4]

        if platform=='darwin' and event.m_keyCode==ord('A') and event.m_metaDown:
            # Mac Cmd special
            self.canvas.allsel(event.m_shiftDown)
        elif event.m_keyCode in cursors:
            if event.m_controlDown:
                xinc=zinc=minres
            else:
                zinc=self.dist/10000000
                if zinc<minres: zinc=minres
                if event.m_shiftDown: zinc*=10
                xinc=zinc/cos(d2r*self.loc[0])
            hr=d2r*((self.hdg + [0,90,180,270][cursors.index(event.m_keyCode)%4])%360)
            if cursors.index(event.m_keyCode)<8:
                self.loc=(round2res(self.loc[0]+zinc*cos(hr)),
                          round2res(self.loc[1]+xinc*sin(hr)))
            else:
                changed=self.canvas.movesel(round2res(zinc*cos(hr)),
                                            round2res(xinc*sin(hr)))
        elif event.m_keyCode in [ord('C'), wx.WXK_NUMPAD5]:
            (names,string,lat,lon,hdg)=self.canvas.getsel(prefs.options&Prefs.DMS)
            if lat==None: return
            self.loc=(round2res(lat),round2res(lon))
            if hdg!=None and event.m_shiftDown:
                self.hdg=round(hdg,1)
        elif event.m_keyCode in [ord('Q'), wx.WXK_NUMPAD7]:
            if event.m_controlDown:
                changed=self.canvas.movesel(0, 0, -0.1)
            elif event.m_shiftDown:
                changed=self.canvas.movesel(0, 0, -5)
            else:
                changed=self.canvas.movesel(0, 0, -1)
        elif event.m_keyCode in [ord('E'), wx.WXK_NUMPAD1]:
            if event.m_controlDown:
                changed=self.canvas.movesel(0, 0, 0.1)
            elif event.m_shiftDown:
                changed=self.canvas.movesel(0, 0, 5)
            else:
                changed=self.canvas.movesel(0, 0, 1)
        elif event.m_keyCode in [ord('R'), wx.WXK_MULTIPLY, wx.WXK_NUMPAD_MULTIPLY, wx.WXK_NUMPAD9]:
            if event.m_shiftDown:
                changed=self.canvas.movesel(0, 0, 0, 5)
            else:
                changed=self.canvas.movesel(0, 0, 0, 1)
        elif event.m_keyCode in [ord('F'), wx.WXK_DIVIDE, wx.WXK_NUMPAD_DIVIDE, wx.WXK_NUMPAD3]:
            if event.m_shiftDown:
                changed=self.canvas.movesel(0, 0, 0, -5)
            else:
                changed=self.canvas.movesel(0, 0, 0, -1)
        elif event.m_keyCode in [wx.WXK_HOME, wx.WXK_NUMPAD_HOME]:
            if event.m_controlDown:
                self.hdg=(self.hdg+0.1)%360
            elif event.m_shiftDown:
                self.hdg=(self.hdg+5)%360
            else:
                self.hdg=(self.hdg+1)%360
        elif event.m_keyCode in [wx.WXK_END, wx.WXK_NUMPAD_END]:
            if event.m_controlDown:
                self.hdg=(self.hdg-0.1)%360
            elif event.m_shiftDown:
                self.hdg=(self.hdg-5)%360
            else:
                self.hdg=(self.hdg-1)%360
        elif event.m_keyCode in [ord('+'), ord('='), wx.WXK_ADD, wx.WXK_NUMPAD_ADD]:
            if event.m_shiftDown:
                self.dist/=zoom2
            else:
                self.dist/=zoom
            if self.dist<1.0: self.dist=1.0
        elif event.m_keyCode in [ord('-'), wx.WXK_NUMPAD_SUBTRACT]:
            if event.m_shiftDown:
                self.dist*=zoom2
            else:
                self.dist*=zoom
            if self.dist>maxzoom: self.dist=maxzoom
        elif event.m_keyCode in [wx.WXK_PAGEUP, wx.WXK_PRIOR, wx.WXK_NUMPAD_PAGEUP, wx.WXK_NUMPAD_PRIOR]:
            if event.m_shiftDown:
                self.elev+=5
            else:
                self.elev+=1
            if self.elev>90: self.elev=90
        elif event.m_keyCode in [wx.WXK_PAGEDOWN, wx.WXK_NEXT, wx.WXK_NUMPAD_PAGEDOWN, wx.WXK_NUMPAD_NEXT]:
            if event.m_shiftDown:
                self.elev-=5
            else:
                self.elev-=1
            if self.elev<2: self.elev=2	# not 1 cos clipping
        elif event.m_keyCode in [wx.WXK_INSERT, wx.WXK_RETURN, wx.WXK_NUMPAD_INSERT, wx.WXK_NUMPAD_ENTER]:
            name=self.palette.get()
            if prefs.package and name and self.canvas.add(name, self.loc[0], self.loc[1], self.hdg, self.dist, event.m_controlDown, event.m_shiftDown):
                changed=True
        elif event.m_keyCode in [wx.WXK_DELETE, wx.WXK_BACK, wx.WXK_NUMPAD_DELETE]: # wx.WXK_NUMPAD_DECIMAL]:
            changed=self.canvas.delsel(event.m_controlDown, event.m_shiftDown)
        elif event.m_keyCode==wx.WXK_SPACE:
            # not Cmd because Cmd-Space = Spotlight
            self.canvas.allsel(event.m_controlDown)
        elif event.m_keyCode==ord('N'):
            name=self.palette.get()
            if name:
                # not Cmd because Cmd-N = new
                loc=self.canvas.nextsel(name, event.m_controlDown)
                if loc:
                    self.loc=loc
                    self.ShowSel()
        elif event.m_keyCode==ord('Z') and event.CmdDown():
            loc=self.canvas.undo()
            if loc:
                self.loc=loc
                self.ShowSel()
            if not self.canvas.undostack:
                self.toolbar.EnableTool(wx.ID_UNDO, False)
                if self.menubar: self.menubar.Enable(wx.ID_UNDO, False)
        elif event.m_keyCode==wx.WXK_F1 and platform!='darwin':
            self.OnHelp(event)
        else:
            #if __debug__: print "Unknown key", event.m_keyCode
            event.Skip(True)
            return
        self.canvas.goto(self.loc, self.hdg, self.elev, self.dist)
        self.Update()		# Let window draw first
        self.ShowLoc()
        if changed:
            self.toolbar.EnableTool(wx.ID_SAVE, True)
            self.toolbar.EnableTool(wx.ID_UNDO, True)
            if self.menubar:
                self.menubar.Enable(wx.ID_SAVE, True)
                self.menubar.Enable(wx.ID_UNDO, True)
        event.Skip(True)
    
    def OnMouseWheel(self, event):
        if event.m_wheelRotation>0:
            if event.m_shiftDown:
                self.dist/=zoom2
            else:
                self.dist/=zoom
            if self.dist<1.0: self.dist=1.0
        elif event.m_wheelRotation<0:
            if event.m_shiftDown:
                self.dist*=zoom2
            else:
                self.dist*=zoom
            if self.dist>maxzoom: self.dist=maxzoom
        else:
            event.Skip(True)
            return
        self.canvas.goto(self.loc, self.hdg, self.elev, self.dist)
        self.Update()		# Let window draw first
        self.ShowLoc()
        event.Skip(True)
        
        
    def OnNew(self, event):
        if not self.SaveDialog(): return
        dlg=wx.TextEntryDialog(self, "Name of new scenery package folder:",
                               "New scenery package")
        while True:
            if dlg.ShowModal()==wx.ID_OK:
                v=dlg.GetValue().strip()
                if not v: continue
                base=glob(join(prefs.xplane,gcustom))[0]
                for f in glob(join(base,'*')):
                    if basename(f.lower())==v.lower():
                        myMessageBox("A package called %s already exists" % v,
                                     appname , wx.ICON_ERROR|wx.OK, self)
                        break
                else:
                    self.toolbar.EnableTool(wx.ID_SAVE, False)
                    self.toolbar.EnableTool(wx.ID_ADD,  False)
                    self.toolbar.EnableTool(wx.ID_UNDO, False)
                    if self.menubar:
                        self.menubar.Enable(wx.ID_SAVE, False)
                        self.menubar.Enable(wx.ID_ADD,  False)
                        self.menubar.Enable(wx.ID_UNDO, False)
                    mkdir(join(base,v))
                    mkdir(join(base,v,'Earth nav data'))
                    prefs.package=v
                    #self.loc=None
                    #self.hdg=0
                    if platform=='darwin':
                        self.SetTitle("%s" % prefs.package)
                    else:
                        self.SetTitle("%s - %s" % (prefs.package, appname))
                    self.OnReload(False)
                    dlg.Destroy()
                    return
            else:
                dlg.Destroy()
                return

    def OnOpen(self, event):
        if not self.SaveDialog(): return
        dlg=wx.Dialog(self, wx.ID_ANY, "Open scenery package")
        dirs=glob(join(prefs.xplane,gcustom,'*'))
        choices=[basename(d) for d in dirs if isdir(d)]
        sortfolded(choices)
        i=0
        x=150
        y=12
        list1=wx.ListBox(dlg, wx.ID_ANY, style=wx.LB_SINGLE, choices=choices)
        for d in choices:
            (x1,y)=list1.GetTextExtent(d)
            if x1>x: x=x1
        list1.SetMinSize((x+8+wx.SystemSettings_GetMetric(wx.SYS_VSCROLL_X),
                          12*y+2*wx.SystemSettings_GetMetric(wx.SYS_EDGE_X)))
        wx.EVT_LISTBOX(dlg, list1.GetId(), self.OnOpened)
        box1=myCreateStdDialogButtonSizer(dlg, wx.CANCEL)
        box0=wx.BoxSizer(wx.VERTICAL)
        box0.Add(list1, 1, wx.ALL|wx.EXPAND, 14)
        box0.Add(box1, 0, wx.ALL|wx.EXPAND, 14)
        dlg.SetSizerAndFit(box0)
        dlg.CenterOnParent()	# Otherwise is centred on screen
        r=dlg.ShowModal()
        dlg.Destroy()
        if r==wx.ID_OK:
            self.toolbar.EnableTool(wx.ID_SAVE, False)
            self.toolbar.EnableTool(wx.ID_ADD,  False)
            self.toolbar.EnableTool(wx.ID_UNDO, False)
            if self.menubar:
                self.menubar.Enable(wx.ID_SAVE, False)
                self.menubar.Enable(wx.ID_ADD,  False)
                self.menubar.Enable(wx.ID_UNDO, False)
            self.loc=None
            self.hdg=0
            if platform=='darwin':
                self.SetTitle("%s" % prefs.package)
            else:
                self.SetTitle("%s - %s" % (prefs.package, appname))
            self.OnReload(False)

    def OnOpened(self, event):
        list1=event.GetEventObject()
        prefs.package=list1.GetStringSelection()
        list1.GetParent().EndModal(wx.ID_OK)

    def OnSave(self, event):
        base=glob(join(prefs.xplane,gcustom))[0]
        if not glob(join(base,prefs.package)):
            mkdir(join(base,prefs.package))
        base=glob(join(prefs.xplane,gcustom,prefs.package))[0]
        if not glob(join(base,gnavdata)):
            mkdir(join(base,'Earth nav data'))
        dsfdir=glob(join(prefs.xplane,gcustom,prefs.package,gnavdata))[0]

        stuff=dict(self.canvas.unsorted)
        for (key,placements) in self.canvas.placements.iteritems():
            stuff[key]=reduce(lambda x,y: x+y, placements)
        for key in stuff.keys():
            try:
                writeDSF(dsfdir, key, stuff[key])
            except IOError, e:
                myMessageBox(str(e.strerror),
                             "Can't save %+03d%+04d.dsf." % (key[0], key[1]), 
                             wx.ICON_ERROR|wx.OK, None)
                return
            except:
                myMessageBox('',
                             "Can't save %+03d%+04d.dsf." % (key[0], key[1]),
                             wx.ICON_ERROR|wx.OK, None)
                return
        self.toolbar.EnableTool(wx.ID_SAVE, False)
        if self.menubar: self.menubar.Enable(wx.ID_SAVE, False)
        
    def OnAdd(self, event):
        # Assumes that only one object selected
        if self.canvas.add(self.palette.get(), self.loc[0], self.loc[1], self.hdg, self.dist, wx.GetKeyState(wx.WXK_CONTROL), wx.GetKeyState(wx.WXK_SHIFT)):
            self.toolbar.EnableTool(wx.ID_SAVE, True)
            self.toolbar.EnableTool(wx.ID_UNDO, True)
            if self.menubar:
                self.menubar.Enable(wx.ID_SAVE, True)
                self.menubar.Enable(wx.ID_UNDO, True)

    def OnDelete(self, event):
        if self.canvas.delsel(wx.GetKeyState(wx.WXK_CONTROL), wx.GetKeyState(wx.WXK_SHIFT)):
            self.toolbar.EnableTool(wx.ID_SAVE, True)
            self.toolbar.EnableTool(wx.ID_UNDO, True)
            if self.menubar:
                self.menubar.Enable(wx.ID_SAVE, True)
                self.menubar.Enable(wx.ID_UNDO, True)

    def OnUndo(self, event):
        loc=self.canvas.undo()
        if loc:
            self.loc=loc
            self.ShowSel()
            self.canvas.goto(self.loc, self.hdg, self.elev, self.dist)
            self.Update()		# Let window draw first
            self.ShowLoc()
        if not self.canvas.undostack:
            self.toolbar.EnableTool(wx.ID_UNDO, False)
            if self.menubar: self.menubar.Enable(wx.ID_UNDO, False)

    def OnBackground(self, event):
        self.canvas.clearsel()
        self.bkgd=BackgroundDialog(self, wx.ID_ANY, "Background image")
        self.bkgd.ShowModal()
        #self.bkgd.Destroy()	# Destroys itself
        self.bkgd=None
        self.canvas.Refresh()
        
    # Load or reload current package
    def OnReload(self, reload):
        progress=wx.ProgressDialog('Loading', '', 5, self, wx.PD_APP_MODAL)
        self.palette.flush()
        pkgnavdata=None
        if prefs.package:
            pkgdir=glob(join(prefs.xplane,gcustom,prefs.package))[0]
            if glob(join(pkgdir, gnavdata)):
                pkgnavdata=glob(join(pkgdir, gnavdata))[0]
        else:
            pkgdir=None
            self.toolbar.EnableTool(wx.ID_PREVIEW, False)
            self.toolbar.EnableTool(wx.ID_REFRESH, False)
            self.toolbar.EnableTool(wx.ID_PASTE,   False)
            if self.menubar:
                self.menubar.Enable(wx.ID_PREVIEW, False)
                self.menubar.Enable(wx.ID_REFRESH, False)
                self.menubar.Enable(wx.ID_PASTE,   False)
        self.toolbar.EnableTool(wx.ID_UNDO, False)
        if self.menubar:
            self.menubar.Enable(wx.ID_UNDO, False)
        progress.Update(0, 'Global airports')
        if not self.airports:	# Default apt.dat
            try:
                (self.airports,self.nav,foo)=readApt(glob(join(prefs.xplane, gmainaptdat))[0])
            except:
                self.nav=[]
                myMessageBox("The X-Plane global apt.dat file is invalid.", "Can't load airport data.", wx.ICON_INFORMATION|wx.OK, self)
            try:
                self.nav.extend(readNav(glob(join(prefs.xplane,gmainnavdat))[0]))
            except:
                pass
                
        progress.Update(1, 'Overlay DSFs')
        if not reload:
            # Load, not reload
            placements={}
            if pkgnavdata:
                try:
                    dsfs=glob(join(pkgnavdata, '[+-][0-9]0[+-][01][0-9]0', '[+-][0-9][0-9][+-][01][0-9][0-9].[dD][sS][fF]'))
                    if not dsfs:
                        if glob(join(pkgnavdata, '[+-][0-9]0[+-][01][0-9]0', '[+-][0-9][0-9][+-][01][0-9][0-9].[eE][nN][vV]')): raise IOError, (0, 'This package uses v7 "ENV" files')
                    for f in dsfs:
                        (lat, lon, p, foo)=readDSF(f)	#join(pkgnavdata,f)
                        tile=(lat,lon)
                        placements[tile]=p
                except IOError, e:	# Bad DSF - restore to unloaded state
                    myMessageBox(e.strerror, "Can't edit this package.",
                                 wx.ICON_ERROR|wx.OK, None)
                    self.SetTitle(appname)
                    prefs.package=None
                    pkgnavdata=None
                    placements={}
                except:		# Bad DSF - restore to unloaded state
                    myMessageBox("Failed to read %s." % basename(f), "Can't edit this package.", wx.ICON_ERROR|wx.OK, None)
                    self.SetTitle(appname)
                    prefs.package=None
                    pkgnavdata=None
                    placements={}
        else:
            placements=None	# keep existing
        progress.Update(2, 'Airports')
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
            except:
                if prefs.package and apt[:-23].endswith(sep+prefs.package):
                    myMessageBox("The apt.dat file in this package is invalid.", "Can't load airport data.", wx.ICON_INFORMATION|wx.OK, self)

        # Merge in custom airports
        airports=dict(self.airports)
        airports.update(pkgapts)

        if self.goto: self.goto.Close()	# Needed on wxMac 2.5
        self.goto=GotoDialog(self, airports)	# build only
        # According to http://scenery.x-plane.com/library.php?doc=about_lib.php&title=X-Plane+8+Library+System
        # search order is: custom libraries, default libraries, scenery package
        progress.Update(3, 'Libraries')
        lookupbylib={}	# {name: path} by libname
        lookup={}	# {name: path}
        terrain={}	# {name: path}

        clibs=glob(join(prefs.xplane, gcustom, '*', glibrary))
        clibs.sort()	# asciibetical
        glibs=glob(join(prefs.xplane, gdefault, '*', glibrary))
        glibs.sort()	# asciibetical
        libpaths=clibs+glibs
        for lib in libpaths: readLib(lib, lookupbylib, terrain)
        libs=lookupbylib.keys()
        sortfolded(libs)	# dislay order in palette
        for lib in libs: lookup.update(lookupbylib[lib])

        objects={}
        if prefs.package:
            for path, dirs, files in walk(pkgdir):
                for f in files:
                    if f[-4:].lower() in KnownDefs and f[0]!='.':
                        name=join(path,f)[len(pkgdir)+1:-4].replace('\\','/')+f[-4:].lower()
                        if name.lower().startswith('custom objects'):
                            name=name[15:]
                        #if not name in lookup:	# library takes precedence
                        objects[name]=join(path,f)
        self.palette.load('Objects', objects, pkgdir)
        lookup.update(objects)

        for lib in libs: self.palette.load(lib, lookupbylib[lib], None)

        self.palette.load('Exclusions', dict([(Exclude.NAMES[x], x) for x in Exclude.NAMES.keys()]), None)

        if prefs.package and prefs.package in prefs.packageprops:
            (image, lat, lon, hdg, width, length, opacity)=prefs.packageprops[prefs.package]
            if image[0]==curdir:
                if glob(join(prefs.xplane,gcustom,prefs.package,normpath(image))):
                    image=glob(join(prefs.xplane,gcustom,prefs.package,normpath(image)))[0]
                else:
                    image=None
            background=(image, lat, lon, hdg, width, length, opacity)
        else:
            background=None
        self.canvas.reload(prefs.options, airports, nav,
                           lookup, placements,
                           background, terrain,
                           [join(prefs.xplane, gcustom),
                            join(prefs.xplane, gdefault)])
        if not self.loc:
            # Load, not reload
            if pkgloc:	# go to first airport by name
                self.loc=pkgloc
            else:
                for p in placements.values():
                    if p:
                        self.loc=p[0].location()
                        break
                else:	# Fallback
                    self.loc=(34.096694,-117.248376)	# KSBD
        self.loc=(round2res(self.loc[0]),round2res(self.loc[1]))
        progress.Destroy()
        
        self.canvas.goto(self.loc, self.hdg, self.elev, self.dist)
        self.ShowLoc()
        if prefs.package:
            self.toolbar.EnableTool(wx.ID_PREVIEW, True)
            self.toolbar.EnableTool(wx.ID_REFRESH, True)
            self.toolbar.EnableTool(wx.ID_PASTE,   True)
            if self.menubar:
                self.menubar.Enable(wx.ID_PREVIEW, True)
                self.menubar.Enable(wx.ID_REFRESH, True)
                self.menubar.Enable(wx.ID_PASTE,   True)

        # redraw
        self.Refresh()

    def OnImport(self, event):
        dlg=wx.FileDialog(self, "Import files:", glob(join(prefs.xplane,gcustom))[0], '', "Objects, Draped, Facades, Forests|*.obj;*.pol;*.fac;*.for|Object files (*.obj)|*.obj|Draped polygon files (*.pol)|*.pol|Facade files (*.fac)|*.fac|Forest files (*.for)|*.for|All files|*.*", wx.OPEN|wx.MULTIPLE|wx.HIDE_READONLY)
        if dlg.ShowModal()!=wx.ID_OK:
            dlg.Destroy()
            return
        paths=dlg.GetPaths()
        sortfolded(paths)	# why not
        dlg.Destroy()
        
        pkgpath=glob(join(prefs.xplane,gcustom,prefs.package))[0]
        for path in paths:
            try:
                newpath=importObj(pkgpath, path)
            except IOError, e:
                msg=e.strerror
            except:
                msg=''
            else:
                name=newpath[len(pkgpath)+1:].replace(sep, '/')
                if name.lower().startswith('custom objects'):
                    name=name[15:]
                self.canvas.lookup[name]=newpath
                self.palette.add(name)
                continue
            myMessageBox(msg, "Can't import %s." % path,
                         wx.ICON_ERROR|wx.OK, self)

    def OnGoto(self, event):
        self.goto.CenterOnParent()	# Otherwise is centred on screen
        choice=self.goto.show(self.loc)
        if choice:
            self.loc=[round2res(choice[0]),
                      round2res(choice[1])]
            self.canvas.goto(self.loc, self.hdg, self.elev, self.dist)
            self.ShowLoc()

    def OnPrefs(self, event):
        dlg=PreferencesDialog(self, wx.ID_ANY, "Preferences")
        dlg.CenterOnParent()	# Otherwise is top-left on Mac
        x=dlg.ShowModal()
        if x!=wx.ID_OK:            
            if x: dlg.Destroy()
            return
        if dlg.display.GetSelection()==1:
            prefs.options=Prefs.TERRAIN
        elif dlg.display.GetSelection()==2:
            prefs.options=Prefs.TERRAIN|Prefs.ELEVATION
        else:
            prefs.options=0
        if dlg.latlon.GetSelection():
            prefs.options|=Prefs.DMS
        if dlg.path.GetValue()!=prefs.xplane:
            prefs.xplane=dlg.path.GetValue()
            prefs.package=None
            self.toolbar.EnableTool(wx.ID_SAVE,   False)
            self.toolbar.EnableTool(wx.ID_ADD,    False)
            self.toolbar.EnableTool(wx.ID_DELETE, False)
            self.toolbar.EnableTool(wx.ID_UNDO,   False)
            if self.menubar:
                self.menubar.Enable(wx.ID_SAVE,   False)
                self.menubar.Enable(wx.ID_ADD,    False)
                self.menubar.Enable(wx.ID_DELETE, False)
                self.menubar.Enable(wx.ID_UNDO,   False)
            self.SetTitle(appname)
            dlg.Destroy()
            self.airports={}	# force reload
            prefs.write()
            self.OnReload(False)
        self.canvas.goto(self.loc, options=prefs.options)
        self.ShowLoc()
        self.ShowSel()

    def OnHelp(self, evt):
        filename=abspath(appname+'.html')
        if 'startfile' in dir(os):
            os.startfile(filename)
        else:
            if type(filename)==types.UnicodeType:
                filename=filename.encode('utf-8')
            webbrowser.open("file:"+quote(filename))

    def OnAbout(self, evt):
        AboutBox(self)

    def OnClose(self, event):
        cancancel=isinstance(event, wx.CloseEvent) and event.CanVeto()
        if not self.SaveDialog(cancancel):
            event.Veto()
            return False
        prefs.write()
        if self.goto: self.goto.Close()
        self.Destroy()
        return True

    def SaveDialog(self, cancancel=True):
        # returns False if wants to cancel
        style=wx.YES_NO
        if cancancel: style|=wx.CANCEL
        if self.toolbar.GetToolEnabled(wx.ID_SAVE):
            if platform=='darwin':
                r=myMessageBox("If you don't save, your changes will be lost.",
                               'Save scenery package "%s"?' % prefs.package,
                               wx.ICON_EXCLAMATION|style, self)
            else:
                r=myMessageBox('Do you want to save the changes?',
                               '"%s" has been modified.' % prefs.package,
                               wx.ICON_EXCLAMATION|style, self)
            if r==wx.YES:
                self.OnSave(None)
            elif r==wx.CANCEL:
                return False
        return True
        
    
# main
app=wx.PySimpleApp()
if platform=='win32':
    if app.GetComCtl32Version()>=600 and wx.DisplayDepth()>=32:
        wx.SystemOptions.SetOptionInt('msw.remap', 2)
    else:
        wx.SystemOptions.SetOptionInt('msw.remap', 0)

frame=MainWindow(None, wx.ID_ANY, appname)
app.SetTopWindow(frame)

# user prefs
prefs=Prefs()
if not prefs.xplane or not glob(join(prefs.xplane,gcustom)):
    if platform.startswith('linux'):	# prompt is not displayed on Linux
        myMessageBox("OverlayEditor needs to know which folder contains your X-Plane, PlaneMaker etc applications.", "Please locate your X-Plane folder", wx.ICON_INFORMATION|wx.OK, frame)
    if platform=='win32' and glob(join('C:\\X-Plane', gcustom)) and glob(join('C:\\X-Plane', gmainaptdat)):
        prefs.xplane='C:\\X-Plane'
    elif platform=='win32':
        prefs.xplane='C:\\'
    elif isdir(join(expanduser('~'), 'X-Plane')):
        prefs.xplane=join(expanduser('~'), 'X-Plane')
    elif isdir(join(expanduser('~'), 'Desktop', 'X-Plane')):
        prefs.xplane=join(expanduser('~'), 'Desktop', 'X-Plane')
    elif isdir(join(sep, 'Applications', 'X-Plane')):
        prefs.xplane=join(sep, 'Applications', 'X-Plane')
    elif platform=='darwin':
        prefs.xplane=join(sep, 'Applications')
    else:
        prefs.xplane=expanduser('~')
    dlg=PreferencesDialog(frame, wx.ID_ANY, '')
    if dlg.OnBrowse(None)!=wx.ID_OK: exit(1)	# User cancelled
    prefs.xplane=dlg.path.GetValue()
    dlg.Destroy()
if prefs.package and not glob(join(prefs.xplane, gcustom, prefs.package)):
    prefs.package=None

# Load data files
frame.Update()		# Let window draw first
frame.OnReload(False)
if prefs.package:
    if platform=='darwin':
        frame.SetTitle("%s" % prefs.package)
    else:
        frame.SetTitle("%s - %s" % (prefs.package, appname))
app.MainLoop()

# Save prefs
prefs.write()

