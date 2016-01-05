#!/usr/bin/python

from distutils.core import setup
from os import getcwd, listdir, name
from os.path import join
from glob import glob
import re
from struct import pack, unpack
from tempfile import gettempdir
import time
import numpy	# pull in dependencies

import platform
win64 = (platform.architecture()[0]=='64bit')
cpu = win64 and 'amd64' or 'x86'
crt = 'Microsoft.VC90.CRT.'+cpu

import sys
sys.path.insert(0, getcwd())

from version import appname, appversion

# bogus crud to get WinXP "Visual Styles"
manifest='''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<assembly xmlns="urn:schemas-microsoft-com:asm.v1" xmlns:asmv3="urn:schemas-microsoft-com:asm.v3" manifestVersion="1.0">
        <assemblyIdentity
                version="{APPVERSION:4.2f}.0.0"
                processorArchitecture="{CPU}"
                name="{APPNAME}"
                type="win32"
        />
        <description>DSF overlay editor.</description>
        <asmv3:application>
                <asmv3:windowsSettings xmlns="http://schemas.microsoft.com/SMI/2005/WindowsSettings">'
                        <dpiAware>true</dpiAware>
                </asmv3:windowsSettings>
        </asmv3:application>
        <dependency>
                <dependentAssembly>
                        <assemblyIdentity
                                type="win32"
                                name="Microsoft.Windows.Common-Controls"
                                version="6.0.0.0"
                                processorArchitecture="{CPU}"
                                publicKeyToken="6595b64144ccf1df"
                                language="*"
                        />
                </dependentAssembly>
        </dependency>
        <dependency>
                <dependentAssembly>
                        <assemblyIdentity
                                type="win32"
                                name="Microsoft.VC90.CRT"
                                version="9.0.30729.4940"
                                processorArchitecture="{CPU}"
                                publicKeyToken="1fc8b3b9a1e18e3b"
                                language="*"
                        />
                </dependentAssembly>
        </dependency>
</assembly>
'''.format(APPNAME=appname, APPVERSION=appversion, CPU=cpu)


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
    hin = open('Resources/OverlayEditor.html', 'rU')
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

res=[join(gettempdir(),'OverlayEditor.html')]
for f in listdir('Resources'):
    if f[-3:]in ['png', '.vs', '.fs', 'obj', 'jpg']: res.append('Resources/%s' % f)

setup(name='OverlayEditor',
      version=("%4.2f" % appversion),
      description='DSF overlay editor',
      author='Jonathan Harris',
      author_email='x-plane@marginal.org.uk',
      url='http://marginal.org.uk/xplanescenery',
      data_files=[('Resources',
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
                  'icon_resources':[(0,'win32/OverlayEditor.ico'),
                                    (1,'win32/fac.ico'),
                                    (2,'win32/for.ico'),
                                    (3,'win32/lin.ico'),
                                    (4,'win32/obj.ico'),
                                    (5,'win32/pol.ico'),
                                    (6,'win32/str.ico'),
                                    (7,'win32/agp.ico')],
                  'other_resources':[(24,1,manifest)],
                  }],

      # mac
      #app = ['OverlayEditor.py'],
)


# Patch the executable to add an export table containing "NvOptimusEnablement"
# http://developer.download.nvidia.com/devzone/devcenter/gamegraphics/files/OptimusRenderingPolicies.pdf

# winnt.h
IMAGE_DOS_SIGNATURE = 0x5a4d	# MZ
IMAGE_DOS_HEADER_lfanew = 0x3c	# location of PE header

# IMAGE_NT_HEADERS
IMAGE_NT_SIGNATURE = 0x00004550	# PE\0\0

# IMAGE_FILE_HEADER - http://msdn.microsoft.com/en-us/library/windows/desktop/ms680313%28v=vs.85%29.aspx
IMAGE_FILE_MACHINE_I386  = 0x014c
IMAGE_FILE_MACHINE_AMD64 = 0x8664

# IMAGE_OPTIONAL_HEADER
IMAGE_NT_OPTIONAL_HDR32_MAGIC = 0x10b
IMAGE_NT_OPTIONAL_HDR64_MAGIC = 0x20b

h = open('dist.%s/OverlayEditor.exe' % cpu, 'rb+')
assert h

# IMAGE_DOS_HEADER
(magic,) = unpack('<H', h.read(2))
assert magic == IMAGE_DOS_SIGNATURE
h.seek(IMAGE_DOS_HEADER_lfanew)
(nt_header,) = unpack('<I', h.read(4))

# IMAGE_NT_HEADERS
h.seek(nt_header)
(magic,) = unpack('<I', h.read(4))
assert magic == IMAGE_NT_SIGNATURE

# IMAGE_FILE_HEADER
(Machine, NumberOfSections, TimeDateStamp, PointerToSymbolTable, NumberOfSymbols, SizeOfOptionalHeader, Characteristics) = unpack('<HHIIIHH', h.read(20))
assert cpu=='x86' and Machine==IMAGE_FILE_MACHINE_I386 or Machine==IMAGE_FILE_MACHINE_AMD64
assert SizeOfOptionalHeader
optional_header = h.tell()
section_table = optional_header + SizeOfOptionalHeader

# IMAGE_OPTIONAL_HEADER
(Magic,MajorLinkerVersion,MinorLinkerVersion,SizeOfCode,SizeOfInitializedData,SizeOfUninitializedData,AddressOfEntryPoint,BaseOfCode,BaseOfData,ImageBase,SectionAlignment,FileAlignment) = unpack('<HBBIIIIIIIII', h.read(40))
assert cpu=='x86' and Magic==IMAGE_NT_OPTIONAL_HDR32_MAGIC or Magic==IMAGE_NT_OPTIONAL_HDR64_MAGIC
export_table_p = optional_header + (cpu=='x86' and 96 or 112)	# location of Export Directory pointer
h.seek(export_table_p)
(va,sz) = unpack('<II', h.read(8))
assert va == sz == 0	# check there isn't already an export table

# IMAGE_SECTION_HEADER
h.seek(section_table)
for section in range(NumberOfSections):
    (Name, VirtualSize, VirtualAddress, SizeOfRawData, PointerToRawData, PointerToRelocations, PointerToLinenumbers, NumberOfRelocations, NumberOfLinenumbers, Characteristics) = unpack('<8sIIIIIIHHI', h.read(40))
    if Name.rstrip('\0')=='.rdata':	# we'll put export table in .rdata, like MSVC's linker
        break
else:
    assert False

# IMAGE_EXPORT_DIRECTORY
export_table_rva = VirtualAddress + VirtualSize + 4	# leave space for DWORD const variable before export_table
export_table_raw = PointerToRawData + VirtualSize + 4
DLLName = export_table_rva + 0x32
AddressOfFunctions = export_table_rva + 0x28
AddressOfNames = export_table_rva + 0x2c
AddressOfNameOrdinals = export_table_rva + 0x30
export_directory_table = pack('<IIHHIIIIIII', 0, int(time.time()), 0, 0, DLLName, 1, 1, 1, AddressOfFunctions, AddressOfNames, AddressOfNameOrdinals)
export_address_table = pack('<I', export_table_rva - 4)	# pointer to exported variable
export_name_table = pack('<I', export_table_rva + 0x44)
export_ordinal_table = pack('<H', 0)
export_DLLname = 'OverlayEditor.exe\0'
export_names = 'NvOptimusEnablement\0'
export_directory = export_directory_table + export_address_table + export_name_table + export_ordinal_table + export_DLLname + export_names
# update .rdata section
assert VirtualSize/SectionAlignment == (VirtualSize+4+len(export_directory))/SectionAlignment	# check we won't overflow the section
VirtualSize += (4 + len(export_directory))
h.seek(section_table + section*40)
if VirtualSize <= SizeOfRawData:
    h.write(pack('<8sIIIIIIHHI', Name, VirtualSize, VirtualAddress, SizeOfRawData, PointerToRawData, PointerToRelocations, PointerToLinenumbers, NumberOfRelocations, NumberOfLinenumbers, Characteristics))
else:
    # not enough space in file on disk
    end_rdata_raw = PointerToRawData + SizeOfRawData
    SizeOfRawData += FileAlignment	# make space
    h.write(pack('<8sIIIIIIHHI', Name, VirtualSize, VirtualAddress, SizeOfRawData, PointerToRawData, PointerToRelocations and PointerToRelocations+FileAlignment or 0, PointerToLinenumbers and PointerToLinenumbers+FileAlignment or 0, NumberOfRelocations, NumberOfLinenumbers, Characteristics))

    # bump following sections up
    section +=1
    while section < NumberOfSections:
        h.seek(section_table + section*40)
        (Name, VirtualSize, VirtualAddress, SizeOfRawData, PointerToRawData, PointerToRelocations, PointerToLinenumbers, NumberOfRelocations, NumberOfLinenumbers, Characteristics) = unpack('<8sIIIIIIHHI', h.read(40))
        h.seek(section_table + section*40)
        h.write(pack('<8sIIIIIIHHI', Name, VirtualSize, VirtualAddress, SizeOfRawData, PointerToRawData+FileAlignment, PointerToRelocations and PointerToRelocations+FileAlignment or 0, PointerToLinenumbers and PointerToLinenumbers+FileAlignment or 0, NumberOfRelocations, NumberOfLinenumbers, Characteristics))
        section += 1

    # move the content of the following sections
    h.seek(end_rdata_raw)
    restoffile = h.read()
    h.seek(end_rdata_raw)
    h.write('\0' * FileAlignment)
    h.write(restoffile)

    # Update optional header with new total size
    SizeOfInitializedData += FileAlignment
    h.seek(optional_header)
    h.write(pack('<HBBIII', Magic,MajorLinkerVersion,MinorLinkerVersion,SizeOfCode,SizeOfInitializedData,SizeOfUninitializedData))


# write export directory
h.seek(export_table_raw - 4)
h.write(pack('<I', 1))	# exported variable == 1
h.write(export_directory)

# update optional header to point to it
h.seek(export_table_p)
h.write(pack('<II', export_table_rva, len(export_directory)))

h.close()
