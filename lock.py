from sys import platform
import wx

from MessageBox import myCreateStdDialogButtonSizer


class Locked:
    OBJ=1
    FAC=2
    FOR=4
    POL=8
    ORTHO=16
    UNKNOWN=32
    POLYGON=FAC|FOR|POL|ORTHO|UNKNOWN
    NET=64
    EXCLUSION=128

    
class LockDialog(wx.Dialog):

    def __init__(self, parent, id, title):
        wx.Dialog.__init__(self, parent, id, title)
        if platform=='darwin':	# Default is too big on Mac
            self.SetWindowVariant(wx.WINDOW_VARIANT_SMALL)

        self.canvas=parent.canvas

        panel1 = wx.Panel(self,-1)
        grid1 = wx.FlexGridSizer(0, 4, 6, 6)
        grid1.AddGrowableCol(3, proportion=1)

        self.object = wx.CheckBox(panel1, -1)
        if self.canvas.locked&Locked.OBJ: self.object.SetValue(True)
        grid1.Add(self.object)
        grid1.Add(wx.StaticBitmap(panel1, -1, wx.Bitmap("Resources/obj.png", wx.BITMAP_TYPE_PNG)))
        grid1.Add([0,0])
        grid1.Add(wx.StaticText(panel1, -1, '3D objects'))
        
        self.polygon= wx.CheckBox(panel1, -1, style=wx.CHK_3STATE)
        if self.canvas.locked&Locked.POLYGON==Locked.POLYGON:
            self.polygon.SetValue(True)
        elif self.canvas.locked&Locked.POLYGON:
            self.polygon.Set3StateValue(wx.CHK_UNDETERMINED)
        grid1.Add(self.polygon)
        grid1.Add(wx.StaticBitmap(panel1, -1, wx.Bitmap("Resources/unknown.png", wx.BITMAP_TYPE_PNG)))
        grid1.Add([0,0])
        grid1.Add(wx.StaticText(panel1, -1, 'Polygons'))

        self.facade = wx.CheckBox(panel1, -1)
        if self.canvas.locked&Locked.FAC: self.facade.SetValue(True)
        grid1.Add([0,0])
        grid1.Add(self.facade)
        grid1.Add(wx.StaticBitmap(panel1, -1, wx.Bitmap("Resources/fac.png", wx.BITMAP_TYPE_PNG)))
        grid1.Add(wx.StaticText(panel1, -1, 'Facades'))

        self.forest = wx.CheckBox(panel1, -1)
        if self.canvas.locked&Locked.FOR: self.forest.SetValue(True)
        grid1.Add([0,0])
        grid1.Add(self.forest)
        grid1.Add(wx.StaticBitmap(panel1, -1, wx.Bitmap("Resources/for.png", wx.BITMAP_TYPE_PNG)))
        grid1.Add(wx.StaticText(panel1, -1, 'Forests'))

        self.draped = wx.CheckBox(panel1, -1)
        if self.canvas.locked&Locked.POL: self.draped.SetValue(True)
        grid1.Add([0,0])
        grid1.Add(self.draped)
        grid1.Add(wx.StaticBitmap(panel1, -1, wx.Bitmap("Resources/pol.png", wx.BITMAP_TYPE_PNG)))
        grid1.Add(wx.StaticText(panel1, -1, 'Draped'))

        self.ortho  = wx.CheckBox(panel1, -1)
        if self.canvas.locked&Locked.ORTHO: self.ortho.SetValue(True)
        grid1.Add([0,0])
        grid1.Add(self.ortho)
        grid1.Add(wx.StaticBitmap(panel1, -1, wx.Bitmap("Resources/ortho.png", wx.BITMAP_TYPE_PNG)))
        grid1.Add(wx.StaticText(panel1, -1, 'Orthophotos'))

        self.unknown = wx.CheckBox(panel1, -1)
        if self.canvas.locked&Locked.UNKNOWN: self.unknown.SetValue(True)
        grid1.Add([0,0])
        grid1.Add(self.unknown)
        grid1.Add(wx.StaticBitmap(panel1, -1, wx.Bitmap("Resources/unknown.png", wx.BITMAP_TYPE_PNG)))
        grid1.Add(wx.StaticText(panel1, -1, 'Other'))

        self.network = wx.CheckBox(panel1, -1)
        if self.canvas.locked&Locked.NET: self.network.SetValue(True)
        grid1.Add(self.network)
        grid1.Add(wx.StaticBitmap(panel1, -1, wx.Bitmap("Resources/net.png", wx.BITMAP_TYPE_PNG)))
        grid1.Add([0,0])
        grid1.Add(wx.StaticText(panel1, -1, 'Networks'))

        self.exclusion= wx.CheckBox(panel1, -1)
        if self.canvas.locked&Locked.EXCLUSION: self.exclusion.SetValue(True)
        grid1.Add(self.exclusion)
        grid1.Add(wx.StaticBitmap(panel1, -1, wx.Bitmap("Resources/exc.png", wx.BITMAP_TYPE_PNG)))
        grid1.Add([0,0])
        grid1.Add(wx.StaticText(panel1, -1, 'Exclusions'))

        panel1.SetSizer(grid1)
        box2=myCreateStdDialogButtonSizer(self, wx.OK|wx.CANCEL)
        box0 = wx.BoxSizer(wx.VERTICAL)
        box0.Add(panel1, 0, wx.LEFT|wx.RIGHT|wx.TOP|wx.EXPAND, 10)
        box0.Add(box2, 0, wx.ALL|wx.EXPAND, 10)
        self.SetSizerAndFit(box0)

        wx.EVT_BUTTON(self, wx.ID_OK, self.OnOK)
        wx.EVT_CHECKBOX(self, self.polygon.GetId(), self.OnPolygons)
        wx.EVT_CHECKBOX(self, self.facade.GetId(), self.OnPolygon)
        wx.EVT_CHECKBOX(self, self.forest.GetId(), self.OnPolygon)
        wx.EVT_CHECKBOX(self, self.draped.GetId(), self.OnPolygon)
        wx.EVT_CHECKBOX(self, self.ortho.GetId(), self.OnPolygon)
        wx.EVT_CHECKBOX(self, self.unknown.GetId(), self.OnPolygon)


    def OnPolygons(self, event):
        val=event.GetEventObject().GetValue()
        self.facade.SetValue(val)
        self.forest.SetValue(val)
        self.draped.SetValue(val)
        self.ortho.SetValue(val)
        self.unknown.SetValue(val)

    def OnPolygon(self, event):
        if self.facade.GetValue() and self.forest.GetValue() and self.draped.GetValue() and self.ortho.GetValue() and self.unknown.GetValue():
            self.polygon.SetValue(True)
        elif not (self.facade.GetValue() or self.forest.GetValue() or self.draped.GetValue() or self.ortho.GetValue() or self.unknown.GetValue()):
            self.polygon.SetValue(False)
        else:
            self.polygon.Set3StateValue(wx.CHK_UNDETERMINED)

    def OnOK(self, event):
        self.canvas.locked=(0 | (self.object.GetValue() and Locked.OBJ) | (self.facade.GetValue() and Locked.FAC) | (self.forest.GetValue() and Locked.FOR) | (self.draped.GetValue() and Locked.POL) | (self.ortho.GetValue() and Locked.ORTHO) | (self.unknown.GetValue() and Locked.UNKNOWN) | (self.network.GetValue() and Locked.NET) | (self.exclusion.GetValue() and Locked.EXCLUSION))
        self.EndModal(wx.ID_OK)
