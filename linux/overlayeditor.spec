Summary: X-Plane DSF overlay editor
Name: overlayeditor
License: Creative Commons Attribution-ShareAlike 2.5
Group: Amusements/Games
URL: http://marginal.org.uk/x-planescenery
Icon: overlayeditor.xpm
Vendor: Jonathan Harris <x-plane@marginal.org.uk>
Prefix: /usr/local
Requires: python >= 2.4, python < 2.5, wxPython >= 2.6, python-imaging >= 1.1.4, python-opengl >= 2.0, wine
#Suse: python-wxGTK provides wxPython, PyOpenGL=python-opengl

%description
This application edits DSF overlay scenery packages
for X-Plane 8.30 or later.

%files
%defattr(644,root,root,755)
%attr(755,root,root) /usr/local/bin/overlayeditor
/usr/local/lib/overlayeditor
%doc /usr/local/lib/overlayeditor/OverlayEditor.html
%attr(755,root,root) /usr/local/lib/overlayeditor/linux/DSFTool
%attr(755,root,root) /usr/local/lib/overlayeditor/win32/DSFTool.exe
# doesn't always look in /usr/local/share/applications
#/usr/share/applications/overlayeditor.desktop
#/usr/share/icons/hicolor/48x48/apps/overlayeditor.png


%post
# see http://lists.freedesktop.org/archives/xdg/2006-February/007757.html
DESKDIR=`echo $XDG_DATA_DIRS|sed -e s/:.*//`
if [ ! "$DESKDIR" ]; then
    if [ -d /usr/local/share/applications ]; then
        DESKDIR=/usr/local/share;
    else
        DESKDIR=/usr/share;
    fi;
fi
mkdir -p "$DESKDIR/applications"
cp -f "$RPM_INSTALL_PREFIX/lib/overlayeditor/overlayeditor.desktop" "$DESKDIR/applications/overlayeditor.desktop"

if [ -d /opt/kde3/share/icons/hicolor ]; then
    ICONDIR=/opt/kde3/share/icons/hicolor;	# suse
else
    ICONDIR=/usr/share/icons/hicolor;
fi
mkdir -p "$ICONDIR/48x48/apps"
cp -f "$RPM_INSTALL_PREFIX/lib/overlayeditor/Resources/OverlayEditor.png" "$ICONDIR/48x48/apps/overlayeditor.png"
gtk-update-icon-cache -q -t $ICONDIR &>/dev/null
exit 0	# ignore errors from updating icon cache


%postun
DESKDIR=`echo $XDG_DATA_DIRS|sed -e s/:.*//`
rm -f "$DESKDIR/applications/overlayeditor.desktop"
rm -f /usr/local/share/applications/overlayeditor.desktop
rm -f /usr/share/applications/overlayeditor.desktop

if [ -f /opt/kde3/share/icons/hicolor/48x48/apps/overlayeditor.png ]; then
    rm -f /opt/kde3/share/icons/hicolor/48x48/apps/overlayeditor.png
    gtk-update-icon-cache -q -t /opt/kde3/share/icons/hicolor &>/dev/null;
fi
if [ -f /usr/share/icons/hicolor/48x48/apps/overlayeditor.png ]; then
    rm -f /usr/share/icons/hicolor/48x48/apps/overlayeditor.png
    gtk-update-icon-cache -q -t /usr/share/icons/hicolor &>/dev/null;
fi
exit 0	# ignore errors from updating icon cache
