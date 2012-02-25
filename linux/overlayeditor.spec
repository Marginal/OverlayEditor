Summary: X-Plane DSF overlay editor
Name: overlayeditor
License: Creative Commons Attribution-ShareAlike 2.5
Group: Amusements/Games
URL: http://marginal.org.uk/x-planescenery
Icon: overlayeditor.xpm
Vendor: Jonathan Harris <x-plane@marginal.org.uk>
Prefix: /usr/local
#Suse: python-wxGTK provides wxPython
#Fedora: PyOpenGL provides python-opengl
Requires: bash, python >= 2.4, wxPython >= 2.6, python-imaging >= 1.1.4, python-opengl >= 2.0.1, python-opengl < 3
BuildArch: noarch

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


%post
# see http://standards.freedesktop.org/basedir-spec/latest/ar01s03.html
DESKDIR=`echo $XDG_DATA_DIRS|sed -e s/:.*//`
if [ ! "$DESKDIR" ]; then
    if [ -d /usr/local/share/applications ]; then
        DESKDIR=/usr/local/share;
    elif [ -d /usr/share/applications ]; then
        DESKDIR=/usr/share;
    elif [ -d /opt/kde3/share/applications ]; then
        DESKDIR=/opt/kde3/share;
    else
        DESKDIR=$RPM_INSTALL_PREFIX/share;
    fi;
fi
mkdir -p "$DESKDIR/applications"
cp -f "$RPM_INSTALL_PREFIX/lib/overlayeditor/overlayeditor.desktop" "$DESKDIR/applications/overlayeditor.desktop"

# KDE<3.5.5 ignores XDG_DATA_DIRS - http://bugs.kde.org/show_bug.cgi?id=97776
if [ -d /opt/kde3/share/icons/hicolor ]; then
    ICONDIR=/opt/kde3/share/icons/hicolor;	# suse
else
    ICONDIR=$DESKDIR/icons/hicolor;
fi
mkdir -p "$ICONDIR/48x48/apps"
cp -f "$RPM_INSTALL_PREFIX/lib/overlayeditor/Resources/OverlayEditor.png" "$ICONDIR/48x48/apps/overlayeditor.png"
gtk-update-icon-cache -f -q -t $ICONDIR &>/dev/null
exit 0	# ignore errors from updating icon cache


%postun
DESKDIR=`echo $XDG_DATA_DIRS|sed -e s/:.*//`
rm -f "$DESKDIR/applications/overlayeditor.desktop"
rm -f /usr/local/share/applications/overlayeditor.desktop
rm -f /usr/share/applications/overlayeditor.desktop
rm -f /opt/kde3/share/applications/overlayeditor.desktop
rm -f /usr/local/share/icons/hicolor/48x48/apps/overlayeditor.png
rm -f /usr/share/icons/hicolor/48x48/apps/overlayeditor.png
rm -f /opt/kde3/share/icons/hicolor/48x48/apps/overlayeditor.png
exit 0	# ignore errors from updating icon cache
