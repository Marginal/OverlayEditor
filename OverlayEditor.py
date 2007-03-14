#!/usr/bin/pythonw

from glob import glob
from math import cos, sin, pi
import os	# for startfile
from os import chdir, getenv, listdir, mkdir, walk
from os.path import abspath, basename, curdir, dirname, exists, isdir, join, normpath, pardir, sep
from sys import exit, argv, platform, version
try:
    import wx
    from wx.lib.masked import NumCtrl, EVT_NUM, NumberUpdatedEvent
except:
    import Tkinter
    import tkMessageBox
    Tkinter.Tk().withdraw()	# make and suppress top-level window
    tkMessageBox._show("Error", "wxPython is not installed.\nThis application requires\nwxPython 2.5.3 (py%s) or later." % version[:3], icon="question", type="ok")
    exit(1)

from draw import MyGL
from files import appname, appversion, importObj, Prefs, readApt, readLib, readDsf, writeDsfs, sortfolded

if not 'startfile' in dir(os):
    import types
    # Causes problems under py2exe & not needed
    from urllib import quote
    import webbrowser

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
maxzoom=50624.0
custom='Custom Scenery'
navdata='Earth nav data'
aptdat='apt.dat'
mainaptdat=join('Resources',navdata,aptdat)
library='library.txt'
default=join('Resources','default scenery')
dsfdir=join(default,'DSF 820 Earth',navdata)


global prefs


if platform=='darwin':
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
        if platform=='win32':
            if ok: buttonok=wx.Button(parent, wx.ID_OK)
            if no: buttonno=wx.Button(parent, wx.ID_CANCEL)
            self.Add([0,0], 1)	# push following buttons to right
            if ok: self.Add(buttonok, 0, wx.ALL, pad)
            if no:
                self.Add([6,0], 0)	# cosmetic
                self.Add(buttonno, 0, wx.ALL, pad)
        else:
            if no: buttonno=wx.Button(parent, wx.ID_CANCEL)
            if ok: buttonok=wx.Button(parent, wx.ID_OK)
            self.Add([0,0], 1)	# push following buttons to right
            if no: self.Add(buttonno, 0, wx.ALL|wx.ALIGN_CENTER_VERTICAL, pad)
            if ok and no: self.Add([6,0], 0)	# cosmetic
            if ok: self.Add(buttonok, 0, wx.ALL|wx.ALIGN_CENTER_VERTICAL, pad)
            self.Add([0,0], 1)	# push following buttons to right
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
        if event.m_keyCode==wx.WXK_UP and self.GetSelection()>0:
            self.SetSelection(self.GetSelection()-1)
        elif event.m_keyCode==wx.WXK_DOWN and self.GetSelection()<len(self.choices)-1:
            self.SetSelection(self.GetSelection()+1)
        elif event.m_keyCode==wx.WXK_HOME:
            self.SetSelection(0)
        elif event.m_keyCode==wx.WXK_END:
            self.SetSelection(len(self.choices)-1)
        elif event.m_keyCode in [wx.WXK_PAGEUP, wx.WXK_PRIOR]:
            self.ScrollPages(-1)
            self.SetSelection(max(0,
                                  self.GetSelection()-self.GetClientSize().y/self.height))
        elif event.m_keyCode in [wx.WXK_PAGEDOWN, wx.WXK_NEXT]:
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

    def __init__(self, parent, aptname, aptcode):

        self.choice=None
        self.aptname=aptname
        self.aptcode=aptcode

        wx.Dialog.__init__(self, parent, wx.ID_ANY, "Go to airport")
        wx.EVT_CLOSE(self, self.OnClose)
        grid1=wx.FlexGridSizer(0, 2, 14, 14)
        grid1.AddGrowableCol(1,1)
        grid1.Add(wx.StaticText(self, wx.ID_ANY, "Airports by name:"),
                  0, wx.ALIGN_CENTER_VERTICAL)
        grid1.Add(wx.StaticText(self, wx.ID_ANY, "Airports by code:"),
                  0, wx.ALIGN_CENTER_VERTICAL)
        choices=self.aptname.keys()
        sortfolded(choices)
        self.list1=myListBox(self,wx.ID_ANY, style=wx.LB_SINGLE, choices=choices)
        grid1.Add(self.list1, 1, wx.ALIGN_CENTER_VERTICAL|wx.ALL|wx.EXPAND, pad)
        (x,y)=self.list1.GetTextExtent("[H] Delray Community Hosp Emergency Helist - 48FD")	# Maybe longest string
        x+=wx.SystemSettings_GetMetric(wx.SYS_VSCROLL_X)+8
        self.list1.SetMinSize((x,16*y))
        wx.EVT_LISTBOX(self, self.list1.GetId(), self.OnName)
        choices=self.aptcode.keys()
        sortfolded(choices)
        self.list2=myListBox(self,wx.ID_ANY, style=wx.LB_SINGLE,choices=choices)
        grid1.Add(self.list2, 1, wx.ALIGN_CENTER_VERTICAL|wx.ALL|wx.EXPAND, pad)
        self.list2.SetMinSize((x,16*y))
        wx.EVT_LISTBOX(self, self.list2.GetId(), self.OnCode)
        box1=myCreateStdDialogButtonSizer(self, wx.OK|wx.CANCEL)
        box0=wx.BoxSizer(wx.VERTICAL)
        box0.Add(grid1, 1, wx.ALL|wx.EXPAND, 14)
        box0.Add(box1, 0, wx.ALL|wx.EXPAND, 14)
        self.SetSizerAndFit(box0)

    def OnClose(self, event):
        # Prevent kill focus event causing refresh on wxMac 2.5
        self.list1.SetSelection(-1)
        self.list2.SetSelection(-1)
        self.Destroy()

    def OnName(self, event):
        self.choice=self.aptname[event.GetEventObject().GetStringSelection()]

    def OnCode(self, event):
        self.choice=self.aptcode[event.GetEventObject().GetStringSelection()]


class Palette(wx.Choicebook):
    
    def __init__(self, parent, frame):
        self.frame=frame
        wx.Choicebook.__init__(self, parent, wx.ID_ANY, style=wx.CHB_TOP)
        if platform=='darwin':	# Default is too big on Mac
            self.SetWindowVariant(wx.WINDOW_VARIANT_MINI)
        self.last=(-1,-1)
        self.choices=[]
        self.lists=[]
        wx.EVT_KEY_DOWN(self, self.OnKeyDown)	# appears to do nowt on Windows
        wx.EVT_MOUSEWHEEL(self, self.OnMouseWheel)
        if 'GetChoiceCtrl' in dir(self):
            wx.EVT_KEY_DOWN(self.GetChoiceCtrl(), self.OnKeyDown)
            wx.EVT_MOUSEWHEEL(self.GetChoiceCtrl(), self.OnMouseWheel)

    def OnChoice(self, event):
        l=event.GetEventObject()
        tab=l.GetParent().GetSelection()
        if self.last!=(tab,l.GetSelection()):
            self.frame.canvas.clearsel()
            self.frame.toolbar.EnableTool(wx.ID_ADD, True)
            self.frame.toolbar.EnableTool(wx.ID_DELETE, False)
            self.frame.statusbar.SetStatusText("", 2)
            # prevent clearing of selection due to set() 
            self.last=(tab,l.GetSelection())
        
    def OnKeyDown(self, event):
        # Override & manually propagate
        self.frame.OnKeyDown(event)
        event.Skip(False)

    def OnMouseWheel(self, event):
        # Override & manually propagate
        self.frame.OnMouseWheel(event)
        event.Skip(False)

    def flush(self):
        if len(self.lists): self.SetSelection(0)	# reduce flicker
        for i in range(len(self.lists)-1,-1,-1):
            self.DeletePage(i)
        self.choices=[]
        self.lists=[]
            
    def load(self, tabname, objects):
        choices=objects.keys()
        sortfolded(choices)
        self.choices.append(choices)
        l=wx.ListBox(self, wx.ID_ANY,
                     style=wx.LB_SINGLE|wx.LB_ALWAYS_SB|wx.LB_HSCROLL)
        self.AddPage(l, tabname)
        l.Set(choices)
        self.lists.append(l)
        #self.Refresh()        # Helps prevent redraw fiasco
        #self.Update()
        wx.EVT_LISTBOX(self, l.GetId(), self.OnChoice)
        wx.EVT_KEY_DOWN(l, self.OnKeyDown)
        wx.EVT_MOUSEWHEEL(l, self.OnMouseWheel)
    
    def add(self, name):
        # Add to objects tab - assumes that this is first tab
        choices=self.choices[0]
        choices.append(name)
        sortfolded(choices)
        self.lists[0].Set(choices)
        self.set(name)
        self.frame.canvas.clearsel()
        self.frame.toolbar.EnableTool(wx.ID_DELETE, False)
        self.frame.statusbar.SetStatusText("", 2)
        self.last=(0,name)

    def get(self):
        (tab,sel)=self.last
        if tab<0: return None
        key=self.lists[tab].GetStringSelection()
        if not key or not key in self.choices[tab]:
            return None
        return key

    def set(self, key):
        ontab=-1
        for tab in range(len(self.lists)):
            l=self.lists[tab]
            if key and key in self.choices[tab]:
                ontab=tab
            elif l.GetSelection()>=0:
                #self.SetSelection(wx.NOT_FOUND)	# not on wxMac 2.5
                l.SetSelection(l.GetSelection(), False)
        if ontab!=-1:
            # Setting causes EVT_NOTEBOOK_PAGE_*
            self.SetSelection(ontab)
            l=self.lists[ontab]
            # Setting causes EVT_LISTBOX event on wxMac 2.5
            l.SetStringSelection(key)
            self.frame.toolbar.EnableTool(wx.ID_ADD, True)
            self.last=(ontab, l.GetSelection())
        else:	# no key, or listed in DSF but not present!
            self.frame.toolbar.EnableTool(wx.ID_ADD, False)
            self.last=(-1, -1)


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
        self.prefix=join(prefs.xplane,custom,prefs.package)
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
            if event.m_shiftDown:
                xinc=zinc=0.000001
            else:
                zinc=self.parent.dist/10000000
                if zinc<0.00001: zinc=0.00001
                if event.m_controlDown or event.m_metaDown:
                    zinc*=10
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
            if event.m_controlDown or event.m_metaDown:
                self.hdg.SetValue((self.hdg.GetValue()-10)%360)
            else:
                self.hdg.SetValue((self.hdg.GetValue()-1)%360)
        elif event.m_keyCode==ord('E'):
            if event.m_controlDown or event.m_metaDown:
                self.hdg.SetValue((self.hdg.GetValue()+10)%360)
            else:
                self.hdg.SetValue((self.hdg.GetValue()+1)%360)
        elif event.m_keyCode==ord('C'):
            self.parent.loc=[self.lat.GetValue(),self.lon.GetValue()]
            if event.m_controlDown or event.m_metaDown:
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
                dir=dirname(join(prefix, normpath(self.image)))
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
        self.parent.canvas.setbackground((self.image, self.lat.GetValue(), self.lon.GetValue(), self.hdg.GetValue()%360, self.width.GetValue(), self.length.GetValue(), self.opacity.GetValue()))

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

        self.loc=None
        self.hdg=0
        self.elev=45
        self.dist=3333.25
        self.aptname=self.aptcode=self.aptrunways={}	# default apt.dat
        self.goto=None	# goto dialog
        self.bkgd=None	# background bitmap dialog

        wx.Frame.__init__(self, parent, id, title)
        wx.EVT_CLOSE(self, self.OnClose)
        wx.EVT_KEY_DOWN(self, self.OnKeyDown)
        wx.EVT_MOUSEWHEEL(self, self.OnMouseWheel)
        
        if platform=='win32':
            self.SetIcon(wx.Icon('win32/%s.ico' % appname, wx.BITMAP_TYPE_ICO))
        elif platform.lower().startswith('linux'):	# PNG supported by GTK
            self.SetIcon(wx.Icon('Resources/%s.png' % appname,
                                 wx.BITMAP_TYPE_PNG))
        elif platform=='darwin':
            pass	# icon pulled from Resources via Info.plist
        
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
                                  'Delete selected object')
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
        self.toolbar.AddLabelTool(wx.ID_PASTE, 'Import',
                                  wx.Bitmap("Resources/import.png",
                                            wx.BITMAP_TYPE_PNG),
                                  wx.NullBitmap, 0,
                                  'Import objects from another package')
        wx.EVT_TOOL(self.toolbar, wx.ID_PASTE, self.OnImport)
        self.toolbar.AddLabelTool(wx.ID_FORWARD, 'Go To',
                                  wx.Bitmap("Resources/goto.png",
                                            wx.BITMAP_TYPE_PNG),
                                  wx.NullBitmap, 0,
                                  'Go to airport')
        wx.EVT_TOOL(self.toolbar, wx.ID_FORWARD, self.OnGoto)
        self.toolbar.AddSeparator()
        self.toolbar.AddLabelTool(wx.ID_SETUP, 'Preferences',
                                  wx.Bitmap("Resources/prefs.png",
                                            wx.BITMAP_TYPE_PNG),
                                  wx.NullBitmap, 0,
                                  'Preferences')
        wx.EVT_TOOL(self.toolbar, wx.ID_SETUP, self.OnPrefs)
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

        # Hack: Use zero-sized first field to hide toolbar button long help
        self.statusbar=self.CreateStatusBar(3, wx.ST_SIZEGRIP)
        (x,y)=self.statusbar.GetTextExtent("  Lat: 999.999999  Lon: 9999.999999  Hdg: 999  Elv: 9999.9  ")
        self.statusbar.SetStatusWidths([0, x+50,-1])

        if platform.lower().startswith('linux'):
            # Don't know why SplitterWindow doesn't work under wxGTK
            self.splitter=wx.Panel(self)            
            self.canvas = MyGL(self.splitter, self)
            self.palette = Palette(self.splitter, self)
            box1=wx.BoxSizer(wx.HORIZONTAL)
            box1.Add(self.canvas, 1, wx.EXPAND)
            box1.Add([6,0], 0, wx.EXPAND)
            box1.Add(self.palette, 0, wx.EXPAND)
            self.palette.SetMinSize((260,-1))
            self.splitter.SetSizer(box1)
            box0=wx.BoxSizer()
            box0.Add(self.splitter, 1, wx.EXPAND)
            self.SetSizerAndFit(box0)
        else:
            self.splitter=wx.SplitterWindow(self, wx.ID_ANY,
                                            style=wx.SP_3DSASH|wx.SP_NOBORDER|wx.SP_LIVE_UPDATE)
            self.splitter.SetWindowStyle(self.splitter.GetWindowStyle() & ~wx.TAB_TRAVERSAL)	# wx.TAB_TRAVERSAL is set behind our backs - this fucks up cursor keys
            self.canvas = MyGL(self.splitter, self)
            self.palette = Palette(self.splitter, self)
            self.splitter.SplitVertically(self.canvas, self.palette, -260)
            box0=wx.BoxSizer()
            box0.Add(self.splitter, 1, wx.EXPAND)
            self.SetSizerAndFit(box0)
            self.splitter.SetMinimumPaneSize(200)
            self.splitter.SetSashPosition(534, True)	# force resize

        self.SetAutoLayout(True)
        self.SetSize((800,600))
        self.SetMinSize((400,300))
        
        if 'SplitVertically' in dir(self.splitter):	# SplitterWindow?
            if 'SetSashGravity' in dir(self.splitter):
                self.splitter.SetSashGravity(1.0)
            else:		# not on WxMac 2.5
                self.splitter.SetSashPosition(534, True)	# force resize
                self.lastwidth=self.GetSize().x
                wx.EVT_SIZE(self, self.OnSize)
        
        self.Show(True)
        self.Update()

    def ShowLoc(self):
        self.statusbar.SetStatusText("Lat: %-10.6f  Lon: %-11.6f  Hdg: %-3.0f  Elv: %-6.1f" %(self.loc[0], self.loc[1], self.hdg, self.canvas.getheight()), 1)

    def ShowSel(self):
        selection=self.canvas.getsel()
        if selection==None:
            self.palette.set(None)
            self.statusbar.SetStatusText("", 2)
            self.toolbar.EnableTool(wx.ID_DELETE, False)
        else:
            (obj, lat, lon, hdg, height)=selection
            if len(obj)==1:
                self.palette.set(obj[0])
                self.statusbar.SetStatusText("Lat: %-10.6f  Lon: %-11.6f  Hdg: %-3.0f  Elv: %-6.1f" % (lat, lon, hdg, height), 2)
            else:
                self.palette.set(None)
                self.statusbar.SetStatusText("Lat: %-10.6f  Lon: %-11.6f  (%d objects)" % (lat, lon, len(obj)), 2)
            self.toolbar.EnableTool(wx.ID_DELETE, True)

    def OnSize(self, event):
        # emulate sash gravity = 1.0
        delta=event.GetSize().x-self.lastwidth
        pos=self.splitter.GetSashPosition()+delta
        if pos<120: pos=120
        self.splitter.SetSashPosition(pos, False)
        self.lastwidth=event.GetSize().x
        event.Skip()

    def OnKeyDown(self, event):
        changed=False
        cursors=[wx.WXK_UP, wx.WXK_RIGHT, wx.WXK_DOWN, wx.WXK_LEFT,
                 ord('W'), ord('D'), ord('S'), ord('A')]
        if event.m_keyCode in cursors:
            if event.m_shiftDown:
                xinc=zinc=0.000001
            else:
                zinc=self.dist/10000000
                if zinc<0.00001: zinc=0.00001
                if event.m_controlDown or event.m_metaDown:
                    zinc*=10
                xinc=zinc/cos(d2r*self.loc[0])
            hr=d2r*((self.hdg + [0,90,180,270,0,90,180,270][cursors.index(event.m_keyCode)])%360)
            if cursors.index(event.m_keyCode)<4:
                self.loc=[round(self.loc[0]+zinc*cos(hr),6),
                          round(self.loc[1]+xinc*sin(hr),6)]
            else:
                changed=self.canvas.movesel(zinc*cos(hr), xinc*sin(hr), 0)
        elif event.m_keyCode==ord('C'):
            details=self.canvas.getsel()
            if not details: return
            (obj,lat,lon,hdg,height)=details
            self.loc=[lat,lon]
            if len(obj)==1 and (event.m_controlDown or event.m_metaDown):
                self.hdg=round(hdg,0)
        elif event.m_keyCode==ord('Q'):
            if event.m_controlDown or event.m_metaDown:
                changed=self.canvas.movesel(0, 0, -5)
            else:
                changed=self.canvas.movesel(0, 0, -1)
        elif event.m_keyCode==ord('E'):
            if event.m_controlDown or event.m_metaDown:
                changed=self.canvas.movesel(0, 0, 5)
            else:
                changed=self.canvas.movesel(0, 0, 1)
        elif event.m_keyCode==wx.WXK_END:
            if event.m_controlDown or event.m_metaDown:
                self.hdg=(self.hdg-5)%360
            else:
                self.hdg=(self.hdg-1)%360
        elif event.m_keyCode==wx.WXK_HOME:
            if event.m_controlDown or event.m_metaDown:
                self.hdg=(self.hdg+5)%360
            else:
                self.hdg=(self.hdg+1)%360
        elif event.m_keyCode in [ord('+'), ord('='), ord('5')]:	# +
            if event.m_controlDown or event.m_metaDown:
                self.dist/=2
            else:
                self.dist/=1.4142
            if self.dist<1.0: self.dist=1.0
        elif event.m_keyCode==45:	# -
            if event.m_controlDown or event.m_metaDown:
                self.dist*=2
            else:
                self.dist*=1.4142
            if self.dist>maxzoom: self.dist=maxzoom
        elif event.m_keyCode in [wx.WXK_PAGEDOWN, wx.WXK_NEXT]:
            if event.m_controlDown or event.m_metaDown:
                self.elev-=5
            else:
                self.elev-=1
            if self.elev<1: self.elev=1
        elif event.m_keyCode in [wx.WXK_PAGEUP, wx.WXK_PRIOR]:
            if event.m_controlDown or event.m_metaDown:
                self.elev+=5
            else:
                self.elev+=1
            if self.elev>90: self.elev=90
        elif event.m_keyCode==wx.WXK_DELETE:
            changed=self.canvas.delsel()
        elif event.m_keyCode==wx.WXK_SPACE:
            self.canvas.allsel(event.m_controlDown or event.m_metaDown)
        else:
            #print event.m_keyCode, event.m_shiftDown, event.m_controlDown, event.m_metaDown
            event.Skip(True)
            return
        self.canvas.goto(self.loc, self.hdg, self.elev, self.dist)
        self.Update()		# Let window draw first
        self.ShowLoc()
        if changed:
            self.toolbar.EnableTool(wx.ID_SAVE, True)
            self.toolbar.EnableTool(wx.ID_UNDO, True)
        event.Skip(True)
    
    def OnMouseWheel(self, event):
        if event.m_wheelRotation>0:
            if event.m_controlDown or event.m_metaDown:
                self.dist/=2
            else:
                self.dist/=1.4142
            if self.dist<1.0: self.dist=1.0
        elif event.m_wheelRotation<0:
            if event.m_controlDown or event.m_metaDown:
                self.dist*=2
            else:
                self.dist*=1.4142
            if self.dist>maxzoom: self.dist=maxzoom
        else:
            #print event.m_wheelRotation, event.m_shiftDown, event.m_controlDown, event.m_metaDown
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
        while 1:
            if dlg.ShowModal()==wx.ID_OK:
                v=dlg.GetValue().strip()
                if not v: continue
                for f in listdir(join(prefs.xplane,custom)):
                    if f.lower()==v.lower():
                        wx.MessageBox("A package called %s already exists" % v,
                                      'Error', wx.ICON_ERROR|wx.OK, self)
                        break
                else:
                    self.toolbar.EnableTool(wx.ID_SAVE, False)
                    self.toolbar.EnableTool(wx.ID_ADD, False)
                    self.toolbar.EnableTool(wx.ID_UNDO, False)
                    mkdir(join(prefs.xplane,custom,v))
                    mkdir(join(prefs.xplane,custom,v,navdata))
                    mkdir(join(prefs.xplane,custom,v,'objects'))
                    mkdir(join(prefs.xplane,custom,v,'textures'))
                    prefs.package=v
                    #self.loc=None
                    #self.hdg=0
                    if platform=='darwin':
                        self.SetTitle("%s" % prefs.package)
                    else:
                        self.SetTitle("%s - %s" % (prefs.package, appname))
                    self.OnReload(None)
                    dlg.Destroy()
                    return
            else:
                dlg.Destroy()
                return

    def OnOpen(self, event):
        if not self.SaveDialog(): return
        dlg=wx.Dialog(self, wx.ID_ANY, "Open scenery package")
        choices=listdir(join(prefs.xplane,custom))
        sortfolded(choices)
        i=0
        x=0
        while i<len(choices):
            if choices[i][0]=='.':
                choices.pop(i)
            else:
                i=i+1
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
            self.toolbar.EnableTool(wx.ID_ADD, False)
            self.toolbar.EnableTool(wx.ID_UNDO, False)
            self.loc=None
            self.hdg=0
            if platform=='darwin':
                self.SetTitle("%s" % prefs.package)
            else:
                self.SetTitle("%s - %s" % (prefs.package, appname))
            self.OnReload(None)

    def OnOpened(self, event):
        list1=event.GetEventObject()
        prefs.package=list1.GetStringSelection()
        list1.GetParent().EndModal(wx.ID_OK)

    def OnSave(self, event):
        writeDsfs(join(prefs.xplane,custom,prefs.package),
                  self.canvas.placements, self.canvas.baggage)
        self.toolbar.EnableTool(wx.ID_SAVE, False)
        
    def OnAdd(self, event):
        # Assumes that only one object selected
        if self.canvas.add(self.palette.get(), self.loc[0], self.loc[1], self.hdg):
            self.toolbar.EnableTool(wx.ID_SAVE, True)
            self.toolbar.EnableTool(wx.ID_UNDO, True)

    def OnDelete(self, event):
        if self.canvas.delsel():
            self.toolbar.EnableTool(wx.ID_SAVE, True)
            self.toolbar.EnableTool(wx.ID_UNDO, True)

    def OnUndo(self, event):
        if not self.canvas.undo():
            self.toolbar.EnableTool(wx.ID_UNDO, False)

    def OnBackground(self, event):
        self.bkgd=BackgroundDialog(self, wx.ID_ANY, "Background image")
        self.bkgd.ShowModal()
        #self.bkgd.Destroy()	# Destroys itself
        self.bkgd=None
        self.canvas.Refresh()
        
    # Load or reload current package
    def OnReload(self, event):
        progress=wx.ProgressDialog('Loading', '', 5, self, wx.PD_APP_MODAL)
        self.palette.flush()
        pkgnavdata=None
        if prefs.package:
            pkgdir=join(prefs.xplane,custom,prefs.package)
            for f in listdir(pkgdir):
                if f.lower()=='earth nav data':
                    pkgnavdata=join(pkgdir,f)
                    break
        else:
            self.toolbar.EnableTool(wx.ID_PREVIEW, False)
            self.toolbar.EnableTool(wx.ID_REFRESH, False)
            self.toolbar.EnableTool(wx.ID_PASTE, False)
        progress.Update(0, 'Global nav data')
        if not self.aptname:	# Default apt.dat
            (self.aptname,self.aptcode,self.aptrunways)=readApt(join(prefs.xplane,mainaptdat))
        progress.Update(1, 'Overlay DSFs')
        if not event:
            # Load, not reload
            placements={}
            baggage={}
            if pkgnavdata:
                try:
                    for f in glob(join(pkgnavdata, '[+-][0-9]0[+-][01][0-9]0', '[+-][0-9][0-9][+-][01][0-9][0-9].[dD][sS][fF]')):
                        (tile,data,props,other)=readDsf(join(pkgnavdata,f))
                        placements[tile]=data
                        baggage[tile]=(props,other)
                except:	# Bad DSF - restore to unloaded state
                    self.SetTitle("%s" % appname)
                    self.toolbar.EnableTool(wx.ID_PREVIEW, False)
                    self.toolbar.EnableTool(wx.ID_REFRESH, False)
                    self.toolbar.EnableTool(wx.ID_PASTE, False)
                    prefs.package=None
                    pkgnavdata=None
                    placements={}
                    baggage={}
        else:
            placements=baggage=None	# keep existing
        progress.Update(2, 'Airports')
        aptname=self.aptname
        aptcode=self.aptcode
        aptrunways=self.aptrunways
        pkgaptname=pkgaptcode=pkgaptrunways={}
        if pkgnavdata and exists(join(pkgnavdata,aptdat)):
            # Package-specific apt.dat
            try:
                (pkgaptname,pkgaptcode,pkgaptrunways)=readApt(join(pkgnavdata,aptdat))
                # Merge lists
                aptname=dict(self.aptname)
                aptname.update(pkgaptname)
                aptcode=dict(self.aptcode)
                aptcode.update(pkgaptcode)
                aptrunways=dict(self.aptrunways)
                aptrunways.update(pkgaptrunways)
            except:
                wx.MessageBox("The %s file in this package is invalid" %aptdat,
                              'Invalid %s' % aptdat,
                              wx.ICON_WARNING|wx.OK, self)
        if self.goto:
            self.goto.Close()	# Needed on wxMac 2.5
        self.goto=GotoDialog(self, aptname, aptcode)	# build only
        # According to http://scenery.x-plane.com/library.php?doc=about_lib.php&title=X-Plane+8+Library+System
        # search order is: custom libraries, default libraries, scenery package
        progress.Update(3, 'Libraries')
        objects={}
        if prefs.package:
            for path, dirs, files in walk(pkgdir):
                for f in files:
                    if f.lower()[-4:]=='.obj':
                        name=join(path,f)[len(pkgdir)+1:-4].replace('\\','/')
                        if name.lower().startswith('custom objects'):
                            name=name[15:]
                        if not name in objects:	# library takes precedence
                            objects[name]=join(path,f)
        self.palette.load('Objects', objects)

        objectsbylib={}	# (name, path) by libname
        terrain={}	# path by name
        for path in [join(prefs.xplane,custom),
                     join(prefs.xplane,default)]:
            for d in listdir(path):
                if d=='800 objects': continue	# mostly placeholders
                pkg=join(path,d)
                if isdir(pkg):
                    for f in listdir(pkg):
                        if f.lower()==library:
                            readLib(join(pkg,f), objectsbylib, terrain)
                            break
        libobjs={}
        libs=objectsbylib.keys()
        sortfolded(libs)
        for lib in libs:
            objs=objectsbylib[lib]
            self.palette.load(lib, objs)
            libobjs.update(objs)
        objects.update(libobjs)	# libs take precedence

        if prefs.package and prefs.package in prefs.packageprops:
            (image, lat, lon, hdg, width, length, opacity)=prefs.packageprops[prefs.package]
            if image[0]==curdir: image=join(prefs.xplane,custom,prefs.package, normpath(image))
            background=(image, lat, lon, hdg, width, length, opacity)
        else:
            background=None
        self.canvas.reload(event!=None,
                           aptrunways, objects, placements, baggage,
                           background,
                           terrain, join(prefs.xplane,dsfdir))
        if not self.loc:
            # Load, not reload
            if pkgaptname:	# go to first airport by name
                self.loc=pkgaptname[pkgaptname.keys()[0]]
            else:		# go to random object
                for p in placements.values():
                    if p:
                        (obj,lat,lon,hdg,height)=p[0]
                        self.loc=[lat,lon]
                        break
        if not self.loc:	# Fallback
            self.loc=[34.096694,-117.248376]	# KSBD
        progress.Destroy()
        
        self.canvas.goto(self.loc, self.hdg, self.elev, self.dist)
        self.toolbar.EnableTool(wx.ID_PREVIEW, True)
        self.toolbar.EnableTool(wx.ID_REFRESH, True)
        self.toolbar.EnableTool(wx.ID_PASTE, True)
        self.ShowLoc()

        # redraw
        self.Refresh()

    def OnImport(self, event):
        dlg=wx.FileDialog(self, "Import object files:", join(prefs.xplane,custom), '', "Object files|*.obj", wx.OPEN|wx.MULTIPLE|wx.HIDE_READONLY)
        if dlg.ShowModal()!=wx.ID_OK:
            dlg.Destroy()
            return
        paths=dlg.GetPaths()
        dlg.Destroy()
        
        pkgpath=join(prefs.xplane,custom,prefs.package)
        for path in paths:
            try:
                newpath=importObj(pkgpath, path)
            except IOError, e:
                msg=e.strerror
            except:
                msg=''
            else:
                name=newpath[len(pkgpath)+1:-4].replace(sep, '/')
                if name.lower().startswith('custom objects'): name=name[15:]
                self.palette.add(name)
                self.canvas.vertexcache.addObj(name, newpath)
                continue
        
            if platform=='darwin':
                wx.MessageBox(msg, "Can't import %s." % path,
                              wx.ICON_QUESTION|wx.OK, self)
            else:
                wx.MessageBox("Can't import %s.\n\n%s" % (path,msg),
                              appname, wx.ICON_EXCLAMATION|wx.OK, self)

    def OnGoto(self, event):
        self.goto.CenterOnParent()	# Otherwise is centred on screen
        if self.goto.ShowModal()==wx.ID_OK and self.goto.choice:
            self.loc=self.goto.choice
            #self.hdg=0
            #self.elev=45
            #self.dist=3000
            self.canvas.goto(self.loc, self.hdg, self.elev, self.dist)
            self.ShowLoc()

    def OnPrefs(self, event):
        if prefs.xplane:
            path=prefs.xplane
        elif platform=='win32' and isdir('C:\\X-Plane\\Custom Scenery'):
            path='C:\\X-Plane'
        else:
            path=''
        while 1:
            dlg=wx.DirDialog(self, "Please locate the X-Plane folder:", path)
            if (dlg.ShowModal()!=wx.ID_OK and
                (not prefs.xplane or not isdir(join(prefs.xplane, custom)))):
                exit(1)		# Can't proceed without an X-Plane folder
            path=dlg.GetPath()
            dlg.Destroy()
            if isdir(join(path, custom)) and exists(join(path, mainaptdat)):
                prefs.xplane=path
                if prefs.package and not isdir(join(prefs.xplane, custom, prefs.package)):
                    prefs.package=None
                prefs.write()
                return

    def OnHelp(self, evt):
        filename=abspath(appname+'.html')
        if 'startfile' in dir(os):
            os.startfile(filename)
        else:
            if type(filename)==types.UnicodeType:
                filename=filename.encode('utf-8')
            webbrowser.open("file:"+quote(filename))

    def OnClose(self, event):
        if not self.SaveDialog(event.CanVeto()):
            event.Veto()
            return False
        prefs.write()
        self.goto.Close()
        self.Destroy()
        return True

    def SaveDialog(self, cancancel=True):
        # returns False if wants to cancel
        style=wx.YES_NO
        if cancancel: style|=wx.CANCEL
        if self.toolbar.GetToolEnabled(wx.ID_SAVE):
            if platform=='darwin':
                r=wx.MessageBox('"%s" has been modified.' % prefs.package,
                                'Save scenery package?',
                                wx.ICON_QUESTION|style, self)
            else:
                r=wx.MessageBox('"%s" has been modified.\n\nDo you want to save the changes?' % prefs.package, appname,
                                wx.ICON_QUESTION|style, self)
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
if not prefs.xplane or not isdir(join(prefs.xplane,custom)):
    if platform=='darwin':	# prompt is not displayed on Mac
        wx.MessageBox("OverlayEditor needs to know which folder contains your X-Plane, PlaneMaker etc applications.", "Please locate your X-Plane folder",
                      wx.ICON_QUESTION|wx.OK, frame)
    frame.OnPrefs(None)
if prefs.package and not isdir(join(prefs.xplane, custom, prefs.package)):
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

