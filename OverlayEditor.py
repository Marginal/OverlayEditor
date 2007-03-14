#!/usr/bin/pythonw

from math import cos, sin, pi
from os import chdir, getenv, listdir, mkdir, walk
from os.path import abspath, basename, dirname, isdir, join, pardir, normpath
from sys import exit, argv, platform
import wx

from draw import MyGL
from files import appname, appversion, Prefs, readApt, readDsf, writeDsfs

d2r=pi/180.0

# Path validation
mypath=dirname(abspath(argv[0]))
if not isdir(mypath):
    exit('"%s" is not a folder' % mypath)
if basename(mypath)=='MacOS':
    chdir(normpath(join(mypath,pardir)))	# Starts in MacOS folder
else:
    chdir(mypath)

# constants
custom='Custom Scenery'
navdata='Earth nav data'
aptdat='apt.dat'
mainaptdat=join('Resources',navdata,aptdat)

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
        self.actcol=wx.SystemSettings_GetColour(wx.SYS_COLOUR_HIGHLIGHT)
        self.inacol=wx.SystemSettings_GetColour(wx.SYS_COLOUR_WINDOW)
        if platform=='win32':
            self.font=wx.SystemSettings_GetFont(wx.SYS_DEFAULT_GUI_FONT)

        wx.VListBox.__init__(self, parent, id, style=style)

        (x,self.height)=self.GetTextExtent("M")
        self.indent=self.height/2
        self.SetItemCount(len(choices))
        wx.EVT_SET_FOCUS(self, self.OnSetFocus)
        wx.EVT_KILL_FOCUS(self, self.OnKillFocus)
        wx.EVT_CHAR(self, self.OnChar)
        if platform!='win32':
            wx.EVT_KEY_DOWN(self, self.OnKeyDown)

    def OnSetFocus(self, event):
        self.SetSelectionBackground(self.actcol)
        
    def OnKillFocus(self, event):
        self.SetSelectionBackground(self.inacol)
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

    def OnDrawItem(self, DC, rect, n):
        #brush=DC.GetBackground()
        #DC.SetBackground(DC.GetBrush())
        #DC.Clear()
        #DC.SetBackground(brush)
        if platform=='win32': DC.SetFont(self.font)
        DC.DrawText(self.choices[n], rect.x+self.indent, rect.y)

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
        event.Skip(False)	# prevent double movement

    def OnChar(self, event):
        c=chr(event.m_keyCode).lower()
        sel=self.GetSelection()
        if sel>=0 and sel<len(self.choices)-1 and self.choices[sel][0].lower()==c and self.choices[sel+1][0].lower()==c:
            self.SetSelection(sel+1)
        else:
            for sel in range(len(self.choices)):
                if self.choices[sel][0].lower()>=c:
                    self.SetSelection(sel)
                    break


class GotoDialog(wx.Dialog):

    def __init__(self, parent, aptname, aptcode):

        self.choice=None
        self.aptname=aptname
        self.aptcode=aptcode

        wx.Dialog.__init__(self, parent, wx.ID_ANY, "Go to airport")
        wx.EVT_CLOSE(self, self.OnClose)
        grid1=wx.FlexGridSizer(0, 2, 14, 14)
        grid1.SetFlexibleDirection(wx.VERTICAL)
        grid1.AddGrowableCol(1,1)
        grid1.Add(wx.StaticText(self, wx.ID_ANY, "Airports by name:"),
                  0, wx.ALIGN_CENTER_VERTICAL)
        grid1.Add(wx.StaticText(self, wx.ID_ANY, "Airports by code:"),
                  0, wx.ALIGN_CENTER_VERTICAL)
        choices=self.aptname.keys()
        choices.sort()	# sorted() not in 2.3
        self.list1=myListBox(self,wx.ID_ANY, style=wx.LB_SINGLE, choices=choices)
        grid1.Add(self.list1, 1, wx.ALIGN_CENTER_VERTICAL|wx.ALL|wx.EXPAND, pad)
        (x,y)=self.list1.GetTextExtent("MT31 - [H] Central Montana Hospital and Nursing H")	# Maybe longest string
        self.list1.SetMinSize((x+24,15*y))	# Allow for scrollbar
        wx.EVT_LISTBOX(self, self.list1.GetId(), self.OnName)
        choices=self.aptcode.keys()
        choices.sort()
        self.list2=myListBox(self,wx.ID_ANY, style=wx.LB_SINGLE,choices=choices)
        grid1.Add(self.list2, 1, wx.ALIGN_CENTER_VERTICAL|wx.ALL|wx.EXPAND, pad)
        self.list2.SetMinSize((x+24,15*y))
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


class Palette(wx.ListBox):
    
    def __init__(self, parent, toolbar, statusbar, canvas, objects=None):
        self.parent=parent
        self.choices=[]
        self.toolbar=toolbar
        self.statusbar=statusbar
        self.canvas=canvas
        self.last=-1
        wx.ListBox.__init__(self, parent, wx.ID_ANY,
                            style=wx.LB_SINGLE|wx.LB_ALWAYS_SB|wx.LB_HSCROLL)
        wx.EVT_LISTBOX(self, self.GetId(), self.OnChoice)
        wx.EVT_KEY_DOWN(self, self.OnKeyDown)
        if objects:
            self.reload(objects)

    def OnChoice(self, event):
        if self.last!=self.GetSelection():
            self.last=self.GetSelection()
            self.canvas.clearsel()
            self.toolbar.EnableTool(wx.ID_ADD, True)
            self.toolbar.EnableTool(wx.ID_DELETE, False)
            self.statusbar.SetStatusText("", 2)
        
    def OnKeyDown(self, event):
        # Override & manually propagate
        self.parent.GetParent().OnKeyDown(event)
        event.Skip(False)

    def reload(self, objects):
        if objects:
            self.choices=objects.keys()
            self.choices.sort()
        else:
            self.choices=[]
        key=self.GetStringSelection()
        self.Set(self.choices)
        if 0:	# don't bother - selection will be wiped out later
            self.SetStringSelection(key)
            self.toolbar.EnableTool(wx.ID_ADD, True)
        #except:
        #    self.toolbar.EnableTool(wx.ID_ADD, False)

    def get(self):
        key=self.GetStringSelection()
        if not key or not key in self.choices:
            return None
        return key

    def set(self, key):
        # Causes EVT_LISTBOX event -> OnChoice
        if key==None:
            #self.SetSelection(wx.NOT_FOUND)
            if self.GetSelection()>=0:
                self.SetSelection(self.GetSelection(), False)
            self.toolbar.EnableTool(wx.ID_ADD, False)
        else:
            try:
                self.SetStringSelection(key)
                self.toolbar.EnableTool(wx.ID_ADD, True)
            except:
                self.SetSelection(wx.NOT_FOUND)
                self.toolbar.EnableTool(wx.ID_ADD, False)
        self.last=self.GetSelection()


# The app
class MainWindow(wx.Frame):
    def __init__(self, parent, id, title):

        self.loc=None
        self.hdg=0
        self.elev=45
        self.dist=3333.25
        self.aptname=self.aptcode=self.aptrunways={}	# default apt.dat
        self.goto=None	# goto dialog

        wx.Frame.__init__(self, parent, id, title)
        wx.EVT_CLOSE(self, self.OnClose)
        wx.EVT_KEY_DOWN(self, self.OnKeyDown)
        
        if platform=='win32':
            self.SetIcon(wx.Icon('win32/%s.ico' % appname, wx.BITMAP_TYPE_ICO))
        elif platform.lower().startswith('linux'):	# PNG supported by GTK
            self.SetIcon(wx.Icon('Resources/%s.png' % appname,
                                 wx.BITMAP_TYPE_PNG))
        elif platform=='darwin':
            pass	# icon pulled from Resources via Info.plist
        
        self.toolbar=self.CreateToolBar(wx.TB_HORIZONTAL|wx.STATIC_BORDER|wx.TB_FLAT)
        # Note colours>(245,245,245) get replaced by transparent
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
        self.toolbar.AddSeparator()
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
                                  'Import object into this package')
        wx.EVT_TOOL(self.toolbar, wx.ID_PASTE, self.OnImport)
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
        
	self.toolbar.Realize()
        self.toolbar.EnableTool(wx.ID_SAVE, False)
        self.toolbar.EnableTool(wx.ID_ADD, False)
        self.toolbar.EnableTool(wx.ID_DELETE, False)
        self.toolbar.EnableTool(wx.ID_PASTE, False)

        # Hack: Use zero-sized first field to hide toolbar button long help
        self.statusbar=self.CreateStatusBar(3, wx.ST_SIZEGRIP)
        #self.statusbar.SetStatusStyles([wx.SB_FLAT,wx.SB_FLAT,wx.SB_FLAT])
        (x,y)=self.statusbar.GetTextExtent("Lat: 7777.777777  Lon: 7777.777777  Hdg: 777")
        self.statusbar.SetStatusWidths([0, x+50,-1])
        
        self.canvas = MyGL(self)
        panel1 = wx.Panel(self,-1)	# Need a panel under StaticText
        self.palette = Palette(panel1, self.toolbar, self.statusbar, self.canvas)
        self.palette.SetSizeHints(240, -1, 240, -1)	# Fixed width

        box1=wx.BoxSizer(wx.VERTICAL)
        box1.Add(wx.StaticText(panel1, wx.ID_ANY, "Objects"),
                 0, wx.ALIGN_CENTER_VERTICAL|wx.EXPAND|wx.BOTTOM|wx.LEFT, 3)
        box1.Add(self.palette, 1, wx.EXPAND|wx.LEFT, 3)
        panel1.SetSizer(box1)

        box0=wx.BoxSizer(wx.HORIZONTAL)
        box0.Add(self.canvas, 1, wx.EXPAND)
        box0.Add(panel1, 0, wx.EXPAND)
        self.SetSizer(box0)

        self.SetAutoLayout(True)
        self.SetSize((800,600))
        self.SetMinSize((400,300))
        self.Show(True)


    def ShowLoc(self):
        self.statusbar.SetStatusText("Lat: %11.6f  Lon: %11.6f  Hdg: %3.0f" %(
            self.loc[0], self.loc[1], self.hdg), 1)

    def ShowSel(self, selection):
        if selection==None:
            self.palette.set(None)
            self.statusbar.SetStatusText("", 2)
            self.toolbar.EnableTool(wx.ID_DELETE, False)
        else:
            (obj, lat, lon, hdg)=selection
            self.palette.set(obj)
            self.statusbar.SetStatusText("Lat: %11.6f  Lon: %11.6f  Hdg: %3.0f" % (lat, lon, hdg), 2)
            self.toolbar.EnableTool(wx.ID_DELETE, True)

    def OnKeyDown(self, event):
        cursors=[wx.WXK_UP, wx.WXK_RIGHT, wx.WXK_DOWN, wx.WXK_LEFT,
                 ord('W'), ord('D'), ord('S'), ord('A')]
        if event.m_keyCode in cursors:
            incr=self.dist/10000000
            if incr<0.00001: incr=0.00001
            if event.m_shiftDown:
                incr=0.000001
            elif event.m_controlDown or event.m_metaDown:
                incr*=10
            hr=d2r*((self.hdg + [0,90,180,270,0,90,180,270][cursors.index(event.m_keyCode)])%360)
            if cursors.index(event.m_keyCode)<4:
                self.loc=[round(self.loc[0]+incr*cos(hr),6),
                          round(self.loc[1]+incr*sin(hr),6)]
            else:
                self.canvas.movesel(incr*cos(hr), incr*sin(hr), 0)
        elif event.m_keyCode==ord('C'):
            details=self.canvas.getsel()
            if not details: return
            (obj,lat,lon,hdg)=details
            self.loc=[lat,lon]
            if event.m_shiftDown or event.m_controlDown or event.m_metaDown:
                self.hdg=round(hdg,0)
        elif event.m_keyCode==ord('Q'):
            if event.m_controlDown or event.m_metaDown:
                self.canvas.movesel(0, 0, -10)
            else:
                self.canvas.movesel(0, 0, -1)
        elif event.m_keyCode==ord('E'):
            if event.m_controlDown or event.m_metaDown:
                self.canvas.movesel(0, 0, 10)
            else:
                self.canvas.movesel(0, 0, 1)
        elif event.m_keyCode==wx.WXK_END:
            if event.m_controlDown or event.m_metaDown:
                self.hdg=(self.hdg-10)%360
            else:
                self.hdg=(self.hdg-1)%360
        elif event.m_keyCode==wx.WXK_HOME:
            if event.m_controlDown or event.m_metaDown:
                self.hdg=(self.hdg+10)%360
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
            if self.dist>25312.0: self.dist=25312.0
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
            self.canvas.delsel()
        else:
            #print event.m_keyCode, event.m_shiftDown, event.m_controlDown, event.m_metaDown
            event.Skip(True)
            return
        self.canvas.goto(self.loc, self.hdg, self.elev, self.dist)
        self.Update()		# Let window draw first
        self.ShowLoc()
        event.Skip(True)
    
    def OnNew(self, event):
        dlg=wx.TextEntryDialog(self, "Name of new scenery package folder:",
                               "New scenery package")
        while 1:
            if dlg.ShowModal()==wx.ID_OK:
                v=dlg.GetValue().strip()
                if not v: continue
                for f in listdir(join(prefs.xplane,custom)):
                    if f.lower()==v.lower():
                        wx.MessageBox("A package called %s already exists" % v,
                                      'Error', wx.ICON_ERROR|wx.OK, None)
                        break
                else:
                    mkdir(join(prefs.xplane,custom,v))
                    mkdir(join(prefs.xplane,custom,v,navdata))
                    mkdir(join(prefs.xplane,custom,v,'objects'))
                    mkdir(join(prefs.xplane,custom,v,'textures'))
                    prefs.package=v
                    self.loc=None
                    self.hdg=0
                    self.SetTitle("%s - %s" % (prefs.package, appname))
                    self.OnReload(None)
                    self.toolbar.EnableTool(wx.ID_SAVE, True)
                    dlg.Destroy()
                    return
            else:
                return

    def OnOpen(self, event):
        dlg=wx.Dialog(self, wx.ID_ANY, "Open scenery package")
        choices=listdir(join(prefs.xplane,custom))
        if '.DS_Store' in choices: choices.remove('.DS_Store')
        list1=wx.ListBox(dlg, wx.ID_ANY, style=wx.LB_SINGLE, choices=choices)
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
            self.loc=None
            self.hdg=0
            self.SetTitle("%s - %s" % (prefs.package, appname))
            self.OnReload(None)
            self.toolbar.EnableTool(wx.ID_SAVE, True)

    def OnOpened(self, event):
        list1=event.GetEventObject()
        prefs.package=list1.GetStringSelection()
        list1.GetParent().EndModal(wx.ID_OK)

    def OnSave(self, event):
        writeDsfs(join(prefs.xplane,custom,prefs.package),
                  self.canvas.placements, self.canvas.baggage)
        
    def OnAdd(self, event):
        self.canvas.add(self.palette.get(), self.loc[0], self.loc[1], self.hdg)

    def OnDelete(self, event):
        self.canvas.delsel()

    # Load (self.loc==None) or reload current package
    def OnReload(self, event):
        progress=wx.ProgressDialog('Loading', '', 5, self, wx.PD_APP_MODAL)
        pkgnavdata=None
        if prefs.package:
            pkgdir=join(prefs.xplane,custom,prefs.package)
            for f in listdir(pkgdir):
                if f.lower()=='earth nav data':
                    pkgnavdata=join(pkgdir,f)
                    break
        progress.Update(0, 'Global nav data')
        if not self.aptname:	# Default apt.dat
            (self.aptname,self.aptcode,self.aptrunways)=readApt(join(prefs.xplane,mainaptdat))
        progress.Update(1, 'DSFs')
        if not self.loc:
            # Load, not reload
            placements={}
            baggage={}
            if pkgnavdata:
                try:
                    for path, dirs, files in walk(pkgnavdata):
                        for f in files:
                            if f.lower()[-4:]=='.dsf':
                                (tile,data,props,other)=readDsf(join(path,f))
                                placements[tile]=data
                                baggage[tile]=(props,other)
                except:	# Bad DSF - restore to unloaded state
                    self.SetTitle("%s" % appname)
                    prefs.package=None
                    pkgnavdata=None
                    placements={}
                    baggage={}
        else:
            placements=baggage=None	# keep existing
        progress.Update(1, 'Airports')
        aptname=self.aptname
        aptcode=self.aptcode
        aptrunways=self.aptrunways
        if pkgnavdata:
            # Package-specific apt.dat
            aptname=dict(self.aptname)
            aptcode=dict(self.aptcode)
            aptrunways=dict(self.aptrunways)
            (pkgaptname,pkgaptcode,pkgaptrunways)=readApt(join(pkgnavdata,aptdat))
            # Merge lists
            aptname.update(pkgaptname)
            aptcode.update(pkgaptcode)
            aptrunways.update(pkgaptrunways)
        progress.Update(2, 'Airports')
        if self.goto:
            self.goto.Close()	# Needed on wxMac 2.5
        self.goto=GotoDialog(self, aptname, aptcode)	# build only
        progress.Update(3, 'Objects')
        objects={}
        if prefs.package:
            for path, dirs, files in walk(pkgdir):
                for f in files:
                    if f.lower()[-4:]=='.obj':
                        name=join(path,f)[len(pkgdir)+1:-4].replace('\\','/')
                        if name.lower().startswith('custom objects'):
                            name=name[15:]
                        elif name.lower().startswith('objects'):
                            name=name[8:]
                        objects[name]=join(path,f)
        self.palette.reload(objects)
        self.canvas.reload(aptrunways,objects,placements,baggage)
        if not self.loc:
            # Load, not reload
            if pkgnavdata:
                if pkgaptname:	# go to first airport by name
                    self.loc=pkgaptname[pkgaptname.keys()[0]]
                else:		# go to random object
                    for p in placements.values():
                        if p:
                            (obj,lat,lon,hdg)=p[0]
                            self.loc=[lat,lon]
                            break
        if not self.loc:	# Fallback
            self.loc=[34.096694,-117.248376]	# KSBD
        self.canvas.goto(self.loc, self.hdg, self.elev, self.dist)
        self.ShowLoc()

        # redraw
        progress.Destroy()
        self.Refresh()

    def OnImport(self, event):
        #print "import"
        pass

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
        elif platform=='win32':
            if isdir('C:\\X-Plane\\Custom Scenery'):
                path='C:\\X-Plane'
            else:
                path=''
        else:
            # prompt is not displayed on Mac
            path='location of top-level X-Plane folder'
        while 1:
            dlg=wx.DirDialog(self, "Location of top-level X-Plane folder:",
                             path)
            if (dlg.ShowModal()!=wx.ID_OK and
                (not prefs.xplane or not isdir(join(prefs.xplane, custom)))):
                exit(1)		# Can't proceed without an X-Plane folder
            path=dlg.GetPath()
            dlg.Destroy()
            if isdir(join(path, custom)):
                prefs.xplane=path
                if prefs.package and not isdir(join(prefs.xplane, custom, prefs.package)):
                    prefs.package=None
                prefs.write()
                return

    def OnClose(self, event):
        self.goto.Close()
        self.Destroy()
        
    
# main
app=wx.PySimpleApp()

frame=MainWindow(None, wx.ID_ANY, appname)
app.SetTopWindow(frame)

# user prefs
prefs=Prefs()
if not prefs.xplane or not isdir(join(prefs.xplane,custom)):
    frame.OnPrefs(None)
if prefs.package and not isdir(join(prefs.xplane, custom, prefs.package)):
    prefs.package=None

# Load data files
frame.Update()		# Let window draw first
frame.OnReload(None)
if prefs.package:
    frame.SetTitle("%s - %s" % (prefs.package, appname))
    frame.toolbar.EnableTool(wx.ID_SAVE, True)
app.MainLoop()

# Save prefs
prefs.write()

