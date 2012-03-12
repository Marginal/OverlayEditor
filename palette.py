from sys import platform
import wx

from os.path import dirname, exists, join

from clutterdef import ClutterDefFactory, PolygonDef, ExcludeDef, NetworkDef, KnownDefs, UnknownDefs
from MessageBox import myMessageBox


# 2.3 version of case-insensitive sort
# 2.4-only version is faster: sort(cmp=lambda x,y: cmp(x.lower(), y.lower()))
def sortfolded(seq):
    seq.sort(lambda x,y: cmp(x.lower(), y.lower()))


class PaletteEntry:

    def __init__(self, file):
        self.file=file
        self.multiple=False
    

class PaletteListBox(wx.VListBox):

    def __init__(self, parent, id, style, tabname, tabno, objects, pkgdir):
        if platform=='win32': style|=wx.ALWAYS_SHOW_SB	# fails on GTK
        wx.VListBox.__init__(self, parent, id, style=style)
        self.font=wx.SystemSettings_GetFont(wx.SYS_DEFAULT_GUI_FONT)
        if platform.startswith('linux'):
            self.font.SetPointSize(10)	# Default is too big on Linux
        self.SetFont(self.font)
        (x,self.height)=self.GetTextExtent("Mq")
        if platform.startswith('linux'):
            self.height-=1
        self.imgs=parent.imgs
        self.actfg=wx.SystemSettings_GetColour(wx.SYS_COLOUR_HIGHLIGHTTEXT)
        self.actbg=wx.SystemSettings_GetColour(wx.SYS_COLOUR_HIGHLIGHT)
        self.inafg=wx.SystemSettings_GetColour(wx.SYS_COLOUR_MENUTEXT)
        self.inabg=wx.SystemSettings_GetColour(wx.SYS_COLOUR_MENU)
        self.indent=4
        self.pkgdir=pkgdir
        self.populate(parent, tabname, tabno, objects)

    def populate(self, parent, tabname, tabno, objects):
        self.choices=[]
        names=objects.keys()
        for name,entry in objects.iteritems():
            realname=name
            ext=name[-4:].lower()
            if tabname==NetworkDef.TABNAME:
                imgno=7
            elif tabname==ExcludeDef.TABNAME:
                imgno=8
            elif ext in UnknownDefs:
                imgno=6
            elif name in parent.bad:
                imgno=16
            elif ext==PolygonDef.DRAPED:
                imgno=4
                if tabno==0 and self.pkgdir:
                    # find orthos - assume library objects aren't
                    try:
                        h=file(join(self.pkgdir,entry.file), 'rU')
                        for line in h:
                            line=line.strip()
                            if line.startswith('TEXTURE_NOWRAP') or line.startswith('TEXTURE_LIT_NOWRAP'):
                                imgno=4
                                break
                            elif line.startswith('TEXTURE'):
                                break
                        h.close()
                    except:
                        pass
            elif ext in KnownDefs:
                imgno=KnownDefs.index(ext)
            else:
                imgno=16	# wtf?
            if tabname in [NetworkDef.TABNAME, ExcludeDef.TABNAME]:
                pass
            elif not self.pkgdir:
                # library object
                if name.startswith('/'): name=name[1:]
                if name.startswith('lib/'):
                    name=name[4:]
                elif name.startswith(tabname+'/'):
                    name=name[len(tabname)+1:]
                name=name[:-4]
            elif name.lower().startswith('objects/') and name[8:] not in names:
                name=name[8:-4]
            elif name.lower().startswith('custom objects/') and name[15:] not in names:
                name=name[15:-4]
            else:
                name=name[:-4]
            if entry.multiple and imgno!=16: imgno+=9
            self.choices.append((imgno, name, realname))
        self.SetItemCount(len(self.choices))

        # sort according to display name and set up quick lookup
        self.choices.sort(lambda x,y: cmp(x[1].lower(), y[1].lower()))
        for i in range(len(self.choices)):
            (imgno, name, realname)=self.choices[i]
            if tabno==0 or realname not in parent.lookup:
                # per-package objects take precedence
                parent.lookup[realname]=(tabno,i)

    def OnMeasureItem(self, n):
        return self.height

    def OnDrawItem(self, dc, rect, n):
        if platform!='darwin':
            dc.SetFont(self.font)	# wtf?
        if self.GetSelection()==n:
            dc.SetTextForeground(self.actfg)
        else:
            dc.SetTextForeground(self.inafg)
        (imgno, name, realname)=self.choices[n]
        assert 0<=imgno<self.imgs.GetImageCount(), "Palette imgno %d out of range for %s (%s)" % (imgno, name, realname)
        self.imgs.Draw(imgno, dc, rect.x+self.indent, rect.y,
                       wx.IMAGELIST_DRAW_TRANSPARENT, True)
        dc.DrawText(name, rect.x+12+2*self.indent, rect.y)

class PaletteChoicebook(wx.Choicebook):
    
    def __init__(self, parent, frame):
        self.frame=frame
        
        wx.Choicebook.__init__(self, parent, wx.ID_ANY, style=wx.CHB_TOP)
        #if platform=='darwin':	# Default is too big on Mac
        #    self.SetWindowVariant(wx.WINDOW_VARIANT_MINI)
        self.last=(-1,None)
        self.lists=[]	# child listboxs
        self.lookup={}	# name->(tabno,index)
        self.bad={}	# name is bad
        self.imgs=wx.ImageList(12,12,True,0)
        # must be in same order as KnownDefs
        self.imgs.Add(wx.Bitmap("Resources/obj.png", wx.BITMAP_TYPE_PNG))
        self.imgs.Add(wx.Bitmap("Resources/obj.png", wx.BITMAP_TYPE_PNG))
        self.imgs.Add(wx.Bitmap("Resources/fac.png", wx.BITMAP_TYPE_PNG))
        self.imgs.Add(wx.Bitmap("Resources/for.png", wx.BITMAP_TYPE_PNG))
        self.imgs.Add(wx.Bitmap("Resources/pol.png", wx.BITMAP_TYPE_PNG))
        self.imgs.Add(wx.Bitmap("Resources/ortho.png", wx.BITMAP_TYPE_PNG))
        self.imgs.Add(wx.Bitmap("Resources/unknown.png", wx.BITMAP_TYPE_PNG))
        self.imgs.Add(wx.Bitmap("Resources/net.png", wx.BITMAP_TYPE_PNG))
        self.imgs.Add(wx.Bitmap("Resources/exc.png", wx.BITMAP_TYPE_PNG))
        self.imgs.Add(wx.Bitmap("Resources/objs.png", wx.BITMAP_TYPE_PNG))
        self.imgs.Add(wx.Bitmap("Resources/objs.png", wx.BITMAP_TYPE_PNG))
        self.imgs.Add(wx.Bitmap("Resources/facs.png", wx.BITMAP_TYPE_PNG))
        self.imgs.Add(wx.Bitmap("Resources/fors.png", wx.BITMAP_TYPE_PNG))
        self.imgs.Add(wx.Bitmap("Resources/pols.png", wx.BITMAP_TYPE_PNG))
        self.imgs.Add(wx.Bitmap("Resources/orthos.png", wx.BITMAP_TYPE_PNG))
        self.imgs.Add(wx.Bitmap("Resources/unknowns.png", wx.BITMAP_TYPE_PNG))
        self.imgs.Add(wx.Bitmap("Resources/bad.png", wx.BITMAP_TYPE_PNG))	# bad assumed below to be last
        wx.EVT_KEY_DOWN(self, self.OnKeyDown)	# appears to do nowt on Windows
        if 'GetChoiceCtrl' in dir(self):	# not available on wxMac 2.5
            if platform=='win32':
                self.GetChoiceCtrl().SetWindowVariant(wx.WINDOW_VARIANT_LARGE)
            wx.EVT_KEY_DOWN(self.GetChoiceCtrl(), self.OnKeyDown)

    def OnKeyDown(self, event):
        # Override & manually propagate
        self.frame.OnKeyDown(event)
        event.Skip(False)

    def OnChoice(self, event):
        #print "choice"
        l=event.GetEventObject()
        (imgno, name, realname)=l.choices[l.GetSelection()]
        self.frame.palette.set(realname)
        self.frame.canvas.clearsel()
        self.frame.statusbar.SetStatusText("", 2)
        self.frame.toolbar.EnableTool(wx.ID_DELETE, False)
        if self.frame.menubar: self.frame.menubar.Enable(wx.ID_DELETE, False)
        event.Skip()

    def flush(self):
        if len(self.lists): self.SetSelection(0)	# reduce flicker
        for i in range(len(self.lists)-1,-1,-1):
            self.DeletePage(i)
        self.lists=[]
        self.lookup={}
        self.bad={}
            
    def load(self, tabname, objects, pkgdir):
        #print "load", tabname
        tabno=len(self.lists)
        l=PaletteListBox(self, -1, wx.LB_SINGLE|wx.VSCROLL, tabname, tabno, objects, pkgdir)
        self.lists.append(l)
        self.AddPage(l, tabname)
        wx.EVT_LISTBOX(self, l.GetId(), self.OnChoice)
        wx.EVT_KEY_DOWN(l, self.OnKeyDown)
    
    def add(self, name, bad):
        if __debug__: print "cbadd", name, bad
        # Add to objects tab - assumes that this is first tab
        if bad:
            if name in self.bad:
                return	# already bad
            self.bad[name]=True

        l=self.lists[0]
        lookup=self.frame.canvas.lookup
        objects=dict([(realname, lookup[realname]) for (imgno, foo, realname) in l.choices])
        objects[name]=lookup[name]
        l.populate(self, 'Objects', 0, objects)
        self.Refresh()

        if not bad:
            # Select added name
            self.set(name)
            self.frame.canvas.clearsel()
            self.frame.statusbar.SetStatusText("", 2)
            self.frame.toolbar.EnableTool(wx.ID_DELETE, False)
            if self.frame.menubar:
                self.frame.menubar.Enable(wx.ID_DELETE, False)

    def get(self):
        for l in self.lists:
            if l.GetSelection()!=-1:
                #print "get", l.choices[l.GetSelection()]
                (imgno, name, realname)=l.choices[l.GetSelection()]
                return realname
        #print "get None"
        return None

    def set(self, name):
        # Called from parent Palette or from OnChoice
        #print "cbset", name
        if name in self.lookup:
            (ontab,ind)=self.lookup[name]
            for tab in range(len(self.lists)):
                if tab!=ontab: self.lists[tab].SetSelection(-1)
            # Setting causes EVT_NOTEBOOK_PAGE_*
            if self.GetSelection()!=ontab: self.SetSelection(ontab)
            l=self.lists[ontab]
            l.SetSelection(ind)
            self.frame.toolbar.EnableTool(wx.ID_ADD, True)
            if self.frame.menubar: self.frame.menubar.Enable(wx.ID_ADD, True)
        else:
            # no key, or listed in DSF but not present - eg unrecognised poly
            self.lists[self.GetSelection()].SetSelection(-1)
            self.frame.toolbar.EnableTool(wx.ID_ADD, False)
            if self.frame.menubar: self.frame.menubar.Enable(wx.ID_ADD, False)

    def markbad(self, name=None):
        # mark name as bad, or current selection if no name
        if name:
            assert name in self.lookup, "%s not in lookup" % name
            if name not in self.lookup: return
            (ontab,ind)=self.lookup[name]
            (imgno, name, realname)=self.lists[ontab].choices[ind]
            if realname in self.bad: return	# already bad
            self.bad[realname]=True
            self.lists[ontab].choices[ind]=(16, name, realname)
            return
        for l in self.lists:
            i=l.GetSelection()
            if i!=-1:
                (imgno, name, realname)=l.choices[i]
                if realname in self.bad:
                    return	# already bad
                self.bad[realname]=True
                l.choices[i]=(16, name, realname)
                self.Refresh()
                break
        else:
            assert(0)	# not found - wtf!
            return
        

class Palette(wx.SplitterWindow):
    
    def __init__(self, parent, frame):
        self.frame=frame
        self.lastkey=None
        self.previewkey=self.previewbmp=self.previewimg=self.previewsize=None
        self.sashsize=4
        wx.SplitterWindow.__init__(self, parent, wx.ID_ANY,
                                   style=wx.SP_3DSASH|wx.SP_NOBORDER|wx.SP_LIVE_UPDATE)
        self.SetWindowStyle(self.GetWindowStyle() & ~wx.TAB_TRAVERSAL)	# wx.TAB_TRAVERSAL is set behind our backs - this fucks up cursor keys
        self.cb=PaletteChoicebook(self, frame)
        self.preview=wx.Panel(self, wx.ID_ANY, style=wx.FULL_REPAINT_ON_RESIZE)
        self.SetMinimumPaneSize(1)
        self.SplitHorizontally(self.cb, self.preview, -ClutterDef.PREVIEWSIZE)
        self.lastheight=self.GetSize().y
        wx.EVT_SIZE(self, self.OnSize)
        wx.EVT_KEY_DOWN(self.preview, self.OnKeyDown)
        wx.EVT_SPLITTER_SASH_POS_CHANGING(self, self.GetId(), self.OnSashPositionChanging)
        wx.EVT_PAINT(self.preview, self.OnPaint)

    def glInit(self):
        self.sashsize=self.GetClientSize()[1]-(self.cb.GetClientSize()[1]+self.preview.GetClientSize()[1])
        #print "sashsize", self.sashsize, self.GetSashSize(), self.preview.GetClientSize()
        self.SetSashPosition(self.GetClientSize()[1]-self.preview.GetClientSize()[0]-self.sashsize, True)
        
    def OnSize(self, event):
        # emulate sash gravity = 1.0
        delta=event.GetSize().y-self.lastheight
        pos=self.GetSashPosition()+delta
        if pos<100: pos=100
        self.SetSashPosition(pos, False)
        self.lastheight=event.GetSize().y
        event.Skip()

    def OnSashPositionChanging(self, event):
        if event.GetSashPosition()<100:
            # One-way minimum pane size
            event.SetSashPosition(100)
        elif event.GetEventObject().GetClientSize()[1]-event.GetSashPosition()-self.sashsize<16:
            # Spring shut
            event.SetSashPosition(event.GetEventObject().GetClientSize()[1]-self.sashsize)

    def OnKeyDown(self, event):
        # Override & manually propagate
        self.frame.OnKeyDown(event)
        event.Skip(False)

    def flush(self):
        self.cb.flush()
        self.lastkey=None
        self.preview.Refresh()
            
    def load(self, tabname, objects, pkgdir):
        self.cb.load(tabname, objects, pkgdir)
    
    def add(self, name, bad=False):
        #print "add", name
        # Add to objects tab - assumes that this is first tab
        if not bad: self.lastkey=name
        self.cb.add(name, bad)
        self.preview.Refresh()

    def get(self):
        return self.cb.get()
    
    def set(self, key):
        #print "set", key, self.lastkey
        if key!=self.lastkey:
            self.cb.set(key)
            self.lastkey=key
            self.preview.Refresh()

    def markbad(self, key):
        return self.cb.markbad(key)

    def OnPaint(self, event):
        #print "preview", self.lastkey
        dc = wx.PaintDC(self.preview)
        if dc.GetSize().y<16 or not self.lastkey:
            if self.previewkey:
                self.previewkey=None
                self.previewbmp=None
                self.preview.SetBackgroundColour(wx.NullColour)
                self.preview.ClearBackground()
            return

        # ClearBackground causes *immediate* repaint on wxMac 2.8,
        # so hack to suppress recursion
        wx.EVT_PAINT(self.preview, None)

        if self.previewkey!=self.lastkey:
            # New
            self.previewkey=self.lastkey
            self.previewimg=self.previewbmp=None

            if not self.previewkey or self.previewkey not in self.frame.canvas.lookup:
                self.preview.SetBackgroundColour(wx.NullColour)
                self.preview.ClearBackground()
                wx.EVT_PAINT(self.preview, self.OnPaint)
                return	# unknown object - can't do anything
            
            # Look for built-in screenshot
            newfile=self.previewkey.replace('/', '_')[:-3]+'jpg'
            if newfile[0]=='_': newfile=newfile[1:]
            newfile=join('Resources', 'previews', newfile)
            try:
                if exists(newfile):
                    self.previewimg=wx.Image(newfile, wx.BITMAP_TYPE_JPEG)
            except:
                pass

            # Look for library screenshot - <object>.jpg, picture.png or screenshot.jpg
            if not self.previewimg:
                newfile=self.frame.canvas.lookup[self.previewkey].file[:-3]+'jpg'
                try:
                    if exists(newfile):
                        self.previewimg=wx.Image(newfile, wx.BITMAP_TYPE_JPEG)
                except:
                    pass

            # X-Plane v9 static aircraft
            if not self.previewimg:
                newfile=join(dirname(newfile), 'picture.png')
                try:
                    if exists(newfile):
                        self.previewimg=wx.Image(newfile, wx.BITMAP_TYPE_PNG)
                except:
                    pass

            # OpenSceneryX
            if not self.previewimg:
                newfile=join(dirname(newfile), 'screenshot.jpg')
                try:
                    if exists(newfile):
                        self.previewimg=wx.Image(newfile, wx.BITMAP_TYPE_JPEG)
                except:
                    pass

            if not self.previewimg:
                # loading clutter can be slow so clear while loading
                self.preview.SetBackgroundColour(wx.NullColour)
                self.preview.ClearBackground()

                # Display object data
                filename=self.frame.canvas.lookup[self.previewkey].file
                try:
                    if filename in self.frame.canvas.defs:
                        definition=self.frame.canvas.defs[filename]
                    else:
                        self.frame.canvas.defs[filename]=definition=ClutterDefFactory(filename, self.frame.canvas.vertexcache)
                    self.previewimg=definition.preview(self.frame.canvas, self.frame.canvas.vertexcache)
                except:
                    self.cb.markbad()

        if self.previewimg:
            # rescale if necessary
            if (dc.GetSize().x >= self.previewimg.GetWidth() and
                dc.GetSize().y >= self.previewimg.GetHeight()):
                scale=None
                newsize=(self.previewimg.GetWidth(),
                         self.previewimg.GetHeight())
            else:
                scale=min(float(dc.GetSize().x)/self.previewimg.GetWidth(),
                          float(dc.GetSize().y)/self.previewimg.GetHeight())
                newsize=(int(scale*self.previewimg.GetWidth()),
                         int(scale*self.previewimg.GetHeight()))
            if not self.previewbmp or newsize!=self.previewsize:
                self.previewsize=newsize
                self.preview.SetBackgroundColour(wx.Colour(self.previewimg.GetRed(0,0), self.previewimg.GetGreen(0,0), self.previewimg.GetBlue(0,0)))
                self.preview.ClearBackground()
                if scale:
                    if 'IMAGE_QUALITY_HIGH' in dir(wx):	# not in 2.6 or earlier
                        self.previewbmp=wx.BitmapFromImage(self.previewimg.Scale(newsize[0], newsize[1], wx.IMAGE_QUALITY_HIGH))
                    else:
                        self.previewbmp=wx.BitmapFromImage(self.previewimg.Scale(newsize[0], newsize[1]))
                else:
                    self.previewbmp=wx.BitmapFromImage(self.previewimg)
            dc.DrawBitmap(self.previewbmp,
                          (dc.GetSize().x-self.previewsize[0])/2,
                          (dc.GetSize().y-self.previewsize[1])/2, True)
        else:
            self.preview.SetBackgroundColour(wx.NullColour)
            self.preview.ClearBackground()

        wx.EVT_PAINT(self.preview, self.OnPaint)

