Release: 1
Summary: DSF overlay editor
Name: overlayeditor
License: Creative Commons Attribution-ShareAlike 2.5
Group: Amusements/Games
URL: http://marginal.org.uk/x-planescenery
Icon: overlayeditor.gif
Vendor: Jonathan Harris <x-plane@marginal.org.uk>
Prefix: /usr/local
Requires: python>=2.4, python<2.5, wxPython>=2.6, python-imaging>=1.1.4, python-opengl>=2.0
#Suse: python-wxGTK provides wxPython

%description
This application edits X-Plane DSF overlay scenery packages
for X-Plane 8.30 or later.

%files
%defattr(644,root,root,755)
%attr(755,root,root) /usr/local/bin/overlayeditor
/usr/local/lib/overlayeditor
%doc /usr/local/lib/overlayeditor/OverlayEditor.html
%attr(755,root,root) /usr/local/lib/overlayeditor/linux/DSFTool
%attr(755,root,root) /usr/local/lib/overlayeditor/win32/DSFTool.exe
