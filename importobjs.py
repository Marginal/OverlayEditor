import codecs
from glob import glob
from hashlib import md5
from os import listdir
from os.path import abspath, basename, dirname, exists, isdir, join, normpath, sep, splitext
from shutil import copy2
from sys import platform
from tempfile import gettempdir

def objpaths(pkgpath, srcpath):
    # find base texture location
    if srcpath.lower().endswith(sep+'custom objects'):
        oldtexpath=srcpath[:srcpath.lower().index(sep+'custom objects')]
        for t in listdir(oldtexpath):
            if t.lower()=='custom object textures': break
        else:
            t='custom object textures'
        oldtexpath=join(oldtexpath, t)
    elif srcpath.lower().endswith(sep+'autogen objects'):
        oldtexpath=srcpath[:srcpath.lower().index(sep+'autogen objects')]
        for t in listdir(oldtexpath):
            if t.lower()=='autogen textures': break
        else:
            t='AutoGen textures'
        oldtexpath=join(oldtexpath, t)
    else:
        oldtexpath=srcpath

    # find destination
    for o in listdir(pkgpath):
        if o.lower()=='custom objects':
            newpath=join(pkgpath, o)
            for t in listdir(pkgpath):
                if t.lower()=='custom object textures': break
            else:
                t='custom object textures'
            newtexpath=join(pkgpath, t)
            newtexprefix=''
            break
    else:
        for o in listdir(pkgpath):
            if o.lower()=='objects':
                newpath=join(pkgpath, o)
                for t in listdir(pkgpath):
                    # only if "textures" folder exists
                    if t.lower()=='textures':
                        newtexpath=join(pkgpath, t)
                        newtexprefix='../'+t+'/'
                        break
                else:
                    newtexpath=newpath
                    newtexprefix=''
                break
        else:
            newpath=newtexpath=pkgpath
            newtexprefix=''
    return (srcpath, oldtexpath, newpath, newtexpath, newtexprefix)


# make a list of (src, dst). Exclude existing but unchanged textures.
def importpaths(pkgpath, paths):
    retval=[]
    (oldpath, oldtexpath, newpath, newtexpath, newtexprefix)=objpaths(pkgpath, dirname(paths[0]))

    for path in paths:
        basename(path).decode()	# names must be ASCII only - may raise UnicodeError
        (name,ext)=splitext(basename(path))
        if ext.lower() in ['.dds', '.png']:
            # Importing a texture as a draped polygon
            f=join(gettempdir(), name+'.pol')
            h=file(f, 'wt')
            h.write((platform=='darwin' and 'A\n' or 'I\n') + '850\nDRAPED_POLYGON\n\nTEXTURE_NOWRAP\t%s\nSCALE\t25 25\n' % basename(path))
            h.close()
            retval.append((f, join(newpath, name+'.pol')))
            for f in glob(join(oldpath, name+'.[DdPp][DdNn][SsGg]')):
                n=join(newtexpath, basename(f))
                if not samefile(f, n):
                    retval.append((f, n))
        else:
            # Import some kind of object
            retval.append((path, join(newpath, basename(path))))
            badobj=(0, "This is not a valid X-Plane file", path)
            h=codecs.open(path, 'rU', 'latin1')
            if not h.readline()[0] in ['I','A']: raise IOError, badobj
            c=h.readline().split()
            if not c: raise IOError, badobj
            version=c[0]
            if not version in ['2', '700', '800', '850', '1000']: raise IOError, badobj
            if version!='2':
                c=h.readline().split()
                if not c or not (c[0]=='OBJ' or
                                 (c[0]=='FOREST' and version=='800') or
                                 (c[0]=='FACADE' and version=='800') or	# can't import v10 facades yet
                                 (c[0]=='LINE_PAINT' and version=='850') or
                                 (c[0]=='DRAPED_POLYGON' and version=='850')):
                    raise IOError, (0, "I don't understand this type of file", path)
            if version in ['2','700']:
                while True:
                    line=h.readline()
                    if not line: raise IOError, badobj
                    line=line.strip()
                    if line:
                        if '//' in line:
                            tex=line[:line.index('//')].strip()
                        else:
                            tex=line.strip()
                        tex=splitext(tex.replace(':',sep).replace('\\',sep))[0]
                        for f in glob(join(oldtexpath, tex+'.[DdPp][DdNn][SsGg]')):
                            n=join(newtexpath, basename(f))
                            if (f, n) not in retval and not samefile(f, n):
                                retval.append((f, n))
                        for f in glob(join(oldtexpath, tex+'_LIT.[DdPp][DdNn][SsGg]')):
                            n=join(newtexpath, basename(f))
                            if (f, n) not in retval and not samefile(f, n):
                                retval.append((f, n))
                        break
            else: # v8.x
                while True:
                    line=h.readline()
                    if not line: break
                    c=line.split()
                    if len(c)<2:
                        pass
                    elif c[0] in ['TEXTURE', 'TEXTURE_NOWRAP', 'TEXTURE_LIT', 'TEXTURE_LIT_NOWRAP', 'TEXTURE_NORMAL', 'TEXTURE_NORMAL_NOWRAP', 'TEXTURE_DRAPED', 'TEXTURE_DRAPED_NORMAL']:
                        tex=splitext(line.strip()[len(c[0]):].strip().replace(':',sep).replace('\\',sep))[0]
                        for f in glob(join(oldtexpath, tex+'.[DdPp][DdNn][SsGg]')):
                            n=join(newtexpath, basename(f))
                            if (f, n) not in retval and not samefile(f, n):
                                retval.append((f, n))
                    elif c[0]=='VT':
                        break	# Stop at first vertex
            h.close()

    return retval


# Actually copy the files. File contents will have been validated above, so we just need to update texture paths.
def importobjs(pkgpath, files):
    (oldpath, oldtexpath, newpath, newtexpath, newtexprefix)=objpaths(pkgpath, dirname(files[0][0]))
    if not isdir(newtexpath): mkdir(newtexpath)

    for (src, dst) in files:
        if splitext(src)[1].lower() in ['.dds', '.png']:
            copy2(src, dst)
            continue

        # Preserve comments, copyrights etc
        h=file(src, 'rU')
        w=file(dst, 'wt')
        line=h.readline().strip()		# A or I
        w.write((platform=='darwin' and 'A' or 'I')+line[1:]+'\n')
        line=h.readline().strip()		# version
        w.write(line+'\n')
        version=line.split()[0]
        if version!='2':
            w.write(h.readline().strip()+'\n')	# file type
        if version in ['2','700']:
            while True:
                line=h.readline().strip()	# texture
                if not line:
                    w.write('\n')
                elif '//' in line:
                    w.write(newtexprefix+basename(line[:line.index('//')].strip().replace(':',sep).replace('\\',sep))+'\t'+line[line.index('//'):]+'\n')
                    break
                else:
                    w.write(newtexprefix+basename(line.replace(':',sep).replace('\\',sep))+'\t//\n')
                    break
        else: # v8.x
            while True:
                line=h.readline()
                if not line: break
                c=line.split()
                if len(c)<2:
                    w.write(line)
                elif c[0] in ['TEXTURE', 'TEXTURE_NOWRAP', 'TEXTURE_LIT', 'TEXTURE_LIT_NOWRAP', 'TEXTURE_NORMAL', 'TEXTURE_NORMAL_NOWRAP', 'TEXTURE_DRAPED', 'TEXTURE_DRAPED_NORMAL']:
                    w.write(c[0]+'\t'+newtexprefix+basename(line.strip()[len(c[0]):].strip().replace(':',sep).replace('\\',sep))+'\n')
                elif c[0]=='VT':
                    w.write(line)
                    break	# Stop at first vertex
                else:
                    w.write(line)
        for line in h:
            w.write(line)
        w.close()
        h.close()


# Are the contents of two files equal? Returns True if src does not exist.
def samefile(src, dst):
    # Compare by hashing. Choice of hash is unimportant so we use MD5 for speed with a low chance of collision.
    if not exists(src): return True
    try:
        digest=[]
        for f in [dst, src]:
            h=file(f, 'rb')
            d=h.read()
            h.close()
            digest.append(md5(d).hexdigest())
        return digest[0]==digest[1]
    except IOError:
        return False
