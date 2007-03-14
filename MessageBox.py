from os.path import join
from sys import platform
import wx

from version import appname

# Custom MessageBox/MessageDialog to replace crappy wxMac default icons
def myMessageBox(message, caption, style=wx.OK, parent=None):

    def WrapText(textctl, width):
        # StaticText.Wrap is not in 2.5.3
        words=textctl.GetLabel().split(' ')
        message=''
        startofline=0
        for word in words:
            if '\n' in word:
                firstword=word[:word.index('\n')]
            else:
                firstword=word
            (x,y)=textctl.GetTextExtent(message[startofline:]+firstword)
            if x>width:
                if startofline!=len(message):
                    message+='\n'
                    startofline=len(message)
                else:
                    #width=x	# Grow dialog to fit long word
                    pass
            message+=word+' '
            if '\n' in word:
                startofline=len(message)-len(word)+len(firstword)
        textctl.SetLabel(message)

    def OnButton(event):
        id=event.GetId()
        if id==wx.ID_OK:
            event.GetEventObject().GetGrandParent().EndModal(wx.OK)
        elif id==wx.ID_SAVE:
            event.GetEventObject().GetGrandParent().EndModal(wx.YES)
        elif id==wx.ID_NO:
            event.GetEventObject().GetGrandParent().EndModal(wx.NO)
        else:
            event.GetEventObject().GetGrandParent().EndModal(wx.CANCEL)

    # Spacings from http://developer.apple.com/documentation/UserExperience/Conceptual/OSXHIGuidelines/XHIGLayout/chapter_19_section_2.html

    if platform!='darwin':
        return wx.MessageBox(caption+'\n\n'+message, appname, style, parent)
        
    assert (style&0xff in [wx.OK,wx.CANCEL,wx.YES_NO,wx.CANCEL|wx.YES_NO])
    txtwidth=320

    dlg=wx.Dialog(parent, style=wx.CAPTION)
    panel0 = wx.Panel(dlg)

    bitmap=wx.StaticBitmap(panel0, -1,
                           wx.Bitmap(join('Resources','%s.png' % appname),
                                     wx.BITMAP_TYPE_PNG))

    cap=wx.StaticText(panel0, -1, caption)
    font=cap.GetFont()
    font.SetWeight(wx.FONTWEIGHT_BOLD)
    cap.SetFont(font)
    WrapText(cap, txtwidth)
    
    text=wx.StaticText(panel0, -1, message)
    text.SetWindowVariant(wx.WINDOW_VARIANT_SMALL)
    WrapText(text, txtwidth)

    if style&0xff in [wx.OK,wx.CANCEL]:
        button=wx.Button(panel0, wx.ID_OK)
        button.SetDefault()
    else:
        button=wx.Button(panel0, wx.ID_SAVE)
    
    grid=wx.GridBagSizer()	# 7 rows, 8 cols
    grid.SetEmptyCellSize((0,0))
    
    grid.Add([24,15], (0,0))
    grid.Add([16,15], (0,2))
    grid.Add([txtwidth,15],(0,3), (1,4))	# Minimum size
    
    grid.Add(bitmap,  (1,1), (3,1), flag=wx.ALIGN_TOP|wx.ALIGN_LEFT)
    grid.Add(cap,     (1,3), (1,4), flag=wx.ALIGN_TOP|wx.ALIGN_LEFT)

    #grid.Add([0,8],  (2,3))
    grid.Add(text,    (3,3), (1,4), flag=wx.ALIGN_TOP|wx.ALIGN_LEFT)
    grid.Add([24,15], (4,0))
    if (style&wx.YES_NO):
        grid.Add(wx.Button(panel0, wx.ID_NO), (5,3), flag=wx.ALIGN_LEFT)
    if (style&wx.YES_NO) and (style&wx.CANCEL):
        grid.Add(wx.Button(panel0, wx.ID_CANCEL), (5,5), flag=wx.ALIGN_RIGHT|wx.RIGHT, border=4)
    grid.Add(button, (5,6), flag=wx.ALIGN_RIGHT)
    grid.Add([24,20], (6,7))
    
    panel0.SetSizerAndFit(grid)

    dlg.SetClientSize(panel0.GetMinSize())
    dlg.CenterOnParent()
    wx.EVT_BUTTON(dlg, wx.ID_OK, OnButton)
    wx.EVT_BUTTON(dlg, wx.ID_SAVE, OnButton)    
    wx.EVT_BUTTON(dlg, wx.ID_NO, OnButton)
    wx.EVT_BUTTON(dlg, wx.ID_CANCEL, OnButton)
    retval=dlg.ShowModal()
    dlg.Destroy()

    return retval


def foo():
    box1=wx.BoxSizer(wx.HORIZONTAL)
    box1.Add([24,0])
    box1.Add(cap)
