#!/usr/bin/python

from files import appname, appversion
from distutils.core import setup
from os import listdir, name
from sys import platform


# bogus crud to get WinXP "Visual Styles"
manifest=('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'+
          '<assembly xmlns="urn:schemas-microsoft-com:asm.v1" manifestVersion="1.0">\n'+
          '<assemblyIdentity\n'+
          '    version="%4.2f.0.0"\n' % appversion +
          '    processorArchitecture="X86"\n'+
          '    name="%s"\n' % appname +
          '    type="win32"\n'+
          '/>\n'+
          '<description>DSF overlay editor.</description>\n'+
          '<dependency>\n'+
          '    <dependentAssembly>\n'+
          '        <assemblyIdentity\n'+
          '            type="win32"\n'+
          '            name="Microsoft.Windows.Common-Controls"\n'+
          '            version="6.0.0.0"\n'+
          '            processorArchitecture="X86"\n'+
          '            publicKeyToken="6595b64144ccf1df"\n'+
          '            language="*"\n'+
          '        />\n'+
          '    </dependentAssembly>\n'+
          '</dependency>\n'+
          '</assembly>\n')


if platform=='win32':
    # http://www.py2exe.org/  Invoke with: setup.py py2exe
    import py2exe
    platdata=[('win32',
               ['win32/DSFTool.exe',
                'win32/OverlayEditor.ico',
                ]),
              ]

elif platform.lower().startswith('darwin'):
    # http://undefined.org/python/py2app.html  Invoke with: setup.py py2app
    import py2app
    platdata=[('MacOS',
               ['MacOS/DSFTool',
                #'MacOS/OverlayEditor.icns',
                ]),
              # Include wxPython 2.4
              #('../Frameworks',
              # ['/usr/local/lib/libwx_mac-2.4.0.rsrc',
              #  ]),
              ]

setup(name='OverlayEditor',
      version=("%4.2f" % appversion),
      description='DSF overlay editor',
      author='Jonathan Harris',
      author_email='x-plane@marginal.org.uk',
      url='http://marginal.org.uk/xplanescenery',
      data_files=[('',
                   ['OverlayEditor.html',
                    ]),
                  ('Resources',
                   ['Resources/add.png',
                    'Resources/background.png',
                    'Resources/delete.png',
                    'Resources/goto.png',
                    'Resources/help.png',
                    'Resources/import.png',
                    'Resources/new.png',
                    'Resources/open.png',
                    'Resources/prefs.png',
                    'Resources/reload.png',
                    'Resources/save.png',
                    'Resources/undo.png',
                    'Resources/default.fac',
                    'Resources/default.obj',
                    'Resources/windsock.obj',
                    'Resources/windsock.png',
                    'Resources/exc.png',
                    'Resources/fac.png',
                    'Resources/obj.png',
                    'Resources/airport0_000.png',
                    'Resources/Sea01.png',
                    'Resources/OverlayEditor.png',
                    'Resources/screenshot.png',
                    'Resources/800library.txt',
                    ]),
                  ] + platdata,

      options = {'py2exe': {'ascii':True,
                            'dll_excludes':['w9xpopen.exe'],
                            'bundle_files':True,
                            'compressed':True,
                            'excludes':['tcl', 'Tkinter', 'mx','socket','urllib','webbrowser'],
                            'optimize':2,
                            },
                 'py2app': {'argv_emulation':False,
                            'iconfile':'MacOS/OverlayEditor.icns',
                            'includes':['wx'],
                            'packages':['wx'],
                            'frameworks':['wx'],
                            'compressed':True,
                            'optimize':2,
                            'semi_standalone':True,
                            },
                 },

      # comment out for Mac
      zipfile = None,
      
      # win32
      windows = [{'script':'OverlayEditor.py',
                  'icon_resources':[(1,'win32/OverlayEditor.ico')],
                  'other_resources':[(24,1,manifest)],
                  }],

      # mac
      #app = ['OverlayEditor.py'],
)
