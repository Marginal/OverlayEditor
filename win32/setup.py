#!/usr/bin/python

from distutils.core import setup
from os import getcwd, listdir, name
from os.path import join
from glob import glob
import re
from tempfile import gettempdir
import numpy	# pull in dependencies

import platform
win64 = (platform.architecture()[0]=='64bit')
cpu = win64 and 'amd64' or 'x86'
crt = 'Microsoft.VC90.CRT.'+cpu

import sys
sys.path.insert(0, getcwd())

from version import appname, appversion

# bogus crud to get WinXP "Visual Styles"
manifest=('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'+
          '<assembly xmlns="urn:schemas-microsoft-com:asm.v1" manifestVersion="1.0">\n'+
          '<assemblyIdentity\n'+
          '    version="%4.2f.0.0"\n' % appversion +
          '    processorArchitecture="'+cpu+'"\n'+
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
          '            processorArchitecture="'+cpu+'"\n'+
          '            publicKeyToken="6595b64144ccf1df"\n'+
          '            language="*"\n'+
          '        />\n'+
          '    </dependentAssembly>\n'+
          '</dependency>\n'+
          '<dependency>\n'+
          '    <dependentAssembly>\n'+
          '        <assemblyIdentity\n'+
          '            type="win32"\n'+
          '            name="Microsoft.VC90.CRT"\n'+
          '            version="9.0.30729.4940"\n'+
          '            processorArchitecture="'+cpu+'"\n'+
          '            publicKeyToken="1fc8b3b9a1e18e3b"\n'+
          '            language="*"\n'+
          '        />\n'+
          '    </dependentAssembly>\n'+
          '</dependency>\n'+
          '</assembly>\n')

if sys.platform=='win32':
    # http://www.py2exe.org/  Invoke with: setup.py py2exe
    import py2exe
    platdata=[('win32',
               ['win32/DSFTool.exe',
                ]),
              ('Microsoft.VC90.CRT',
               ['win32/'+crt+'/Microsoft.VC90.CRT.manifest',
                'win32/'+crt+'/msvcp90.dll',
                'win32/'+crt+'/msvcr90.dll'
                ]),
              ]
    # Substitute Macisms in documentation
    hin = open('OverlayEditor.html', 'rU')
    hout = open(join(gettempdir(),'OverlayEditor.html'), 'wt')
    subs = { 'Cmd':     'Ctrl',
             '&#8598;': 'Home',
             '&#8600;': 'End',
             '&nbsp;&#8670;&nbsp;': 'PageUp',
             '&nbsp;&#8671;&nbsp;': 'PageDn' }
    regex = re.compile("(%s)" % "|".join(map(re.escape, subs.keys())))
    for line in hin:
        hout.write(regex.sub(lambda mo: subs[mo.string[mo.start():mo.end()]], line) +'\n')
    hin.close()
    hout.close()


elif sys.platform.lower().startswith('darwin'):
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

res=["Resources/windsock.obj",
     "Resources/screenshot.jpg",
     "Resources/800library.txt"]
for f in listdir('Resources'):
    if f[-3:]in ['png', '.vs', '.fs']: res.append('Resources/%s' % f)

setup(name='OverlayEditor',
      version=("%4.2f" % appversion),
      description='DSF overlay editor',
      author='Jonathan Harris',
      author_email='x-plane@marginal.org.uk',
      url='http://marginal.org.uk/xplanescenery',
      data_files=[('',
                   [join(gettempdir(),'OverlayEditor.html'),
                    ]),
                  ('Resources',
                   res),
                  ('Resources/previews',
                   glob('Resources/previews/*.jpg')
                   ),
                  ] + platdata,

      options = {'py2exe': {'ascii':True,	# suppresss encodings?
                            'dist_dir':'dist.'+cpu,
                            'dll_excludes':['msvcp90.dll', 'w9xpopen.exe'],
                            #'bundle_files':win64 and 3 or 2,	# don't bundle pythonX.dll - causes ctypes to fail. Bundling doesn't work on win64, or woth Intel MKL lib
                            'compressed':True,
                            'includes':['OpenGL.platform.win32',
                                        'OpenGL.arrays',
                                        'OpenGL.arrays.ctypesarrays',
                                        'OpenGL.arrays.ctypesparameters',
                                        'OpenGL.arrays.ctypespointers',
                                        'OpenGL.arrays.lists',
                                        'OpenGL.arrays.nones',
                                        'OpenGL.arrays.numbers',
                                        'OpenGL.arrays.numpymodule',
                                        'OpenGL.arrays.strings',
                                        'OpenGL.arrays.vbo'],
                            # http://www.py2exe.org/index.cgi/OptimizingSize
                            'excludes':['Carbon', 'tcl', 'Tkinter', 'mx', 'webbrowser',
                                        'curses', 'distutils', 'doctest', 'hotshot', 'inspect', 'pdb', 'setuptools', 'win32',	# Python2.5
                                        'Numeric', 'dotblas', 'numarray', 'scipy', 'nose'],	# Old Numeric stuff
                            'packages':['encodings.ascii','encodings.mbcs','encodings.latin_1','encodings.utf_8','encodings.utf_16','encodings.cp437'],
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
