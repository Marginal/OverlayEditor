from struct import unpack

# Takes a DSF path name.
# Returns (properties, placements, mesh), where:
#   properties = dictionary {property: string value}
#   placements = array of [object name, lon, lat, hdg, ...]
#   mesh = [(terrain name, list of points)], where
#     point = [lon, lat, height, ...]
# Exceptions:
#   IOError, IndexError

def read(path):
    baddsf=(0, "Invalid DSF file", path)

    h=file(path, 'rb')
    if h.read(8)!='XPLNEDSF' or unpack('<I',h.read(4))!=(1,) or h.read(4)!='DAEH':
        raise IOError, baddsf
    (l,)=unpack('<I', h.read(4))
    headend=h.tell()+l-8
    if h.read(4)!='PORP':
        raise IOError, baddsf
    (l,)=unpack('<I', h.read(4))
    properties={}
    c=h.read(l-9).split('\0')
    h.read(1)
    for i in range(0, len(c)-1, 2):
        properties[c[i]]=c[i+1]
    tile=[int(properties['sim/south']), int(properties[('sim/west')])]    
    centre=[tile[0]+0.5, tile[1]+0.5]
    h.seek(headend)

    # Definitions Atom
    if h.read(4)!='NFED':
        raise IOError, baddsf
    (l,)=unpack('<I', h.read(4))
    defnend=h.tell()+l-8
    terrain=objects=polygons=network=[]
    while h.tell()<defnend:
        c=h.read(4)
        (l,)=unpack('<I', h.read(4))
        if l==8:
            pass	# empty
        elif c=='TRET':
            terrain=h.read(l-9).split('\0')
            h.read(1)
        elif c=='TJBO':
            objects=h.read(l-9).split('\0')
            h.read(1)
        elif c=='YLOP':
            polygons=h.read(l-9).split('\0')
            h.read(1)
        elif c=='YLOP':
            networks=h.read(l-9).split('\0')
            h.read(1)
        else:
            h.seek(l-8, 1)

    # Geodata Atom
    if h.read(4)!='DOEG':
        raise IOError, baddsf
    (l,)=unpack('<I', h.read(4))
    geodend=h.tell()+l-8
    pool=[]
    scal=[]
    while h.tell()<geodend:
        c=h.read(4)
        (l,)=unpack('<I', h.read(4))
        if c=='LOOP':
            thispool=[]
            (n,)=unpack('<I', h.read(4))
            (p,)=unpack('<B', h.read(1))
            for i in range(p):
                thisplane=[]
                (e,)=unpack('<B', h.read(1))
                if e==0 or e==1:
                    last=0
                    for j in range(n):
                        (d,)=unpack('<H', h.read(2))
                        if e==1: d=(last+d)&65535
                        thisplane.append(d)
                        last=d
                elif e==2 or e==3:
                    last=0
                    while(len(thisplane))<n:
                        (r,)=unpack('<B', h.read(1))
                        if (r&128):
                            (d,)=unpack('<H', h.read(2))
                            for j in range(r&127):
                                if e==3:
                                    thisplane.append((last+d)&65535)
                                    last=(last+d)&65535
                                else:
                                    thisplane.append(d)
                        else:
                            for j in range(r):
                                (d,)=unpack('<H', h.read(2))
                                if e==3: d=(last+d)&65535
                                thisplane.append(d)
                                last=d
                else:
                    raise IOError, baddsf
                thispool.append(thisplane)  
            pool.append(thispool)
        elif c=='LACS':
            thisscal=[]
            for i in range(0, l-8, 8):
                d=unpack('<2f', h.read(8))
                thisscal.append(d)
            scal.append(thisscal)
        else:
            h.seek(l-8, 1)
    
    # Rescale pool and transform to one list per entry
    if len(scal)!=len(pool): raise(IOError)
    newpool=[]
    for i in range(len(pool)):
        curpool=pool[i]
        n=len(curpool[0])
        newpool=[[] for j in range(n)]
        for plane in range(len(curpool)):
            (scale,offset)=scal[i][plane]
            scale=scale/65535
            for j in range(n):
                newpool[j].append(curpool[plane][j]*scale+offset)
        pool[i]=newpool

    # Commands Atom
    if h.read(4)!='SDMC':
        raise IOError, baddsf
    (l,)=unpack('<I', h.read(4))
    cmdsend=h.tell()+l-8
    curpool=0
    idx=0
    near=0
    far=-1
    flags=0	# 1=physical, 2=overlay
    placements=[]
    mesh=[]
    curter='terrain_Water'
    curpatch=[]
    while h.tell()<cmdsend:
        (c,)=unpack('<B', h.read(1))
        if c==1:
            (curpool,)=unpack('<H', h.read(2))
        elif c==2:
            h.read(4)
        elif c==3:
            (idx,)=unpack('<B', h.read(1))
        elif c==4:
            (idx,)=unpack('<H', h.read(2))
        elif c==5:
            (idx,)=unpack('<I', h.read(4))
        elif c==6:
            h.read(1)
        elif c==7:
            (d,)=unpack('<H', h.read(2))
            placements.append([objects[idx]])
            placements[-1].extend(pool[curpool][d])
        elif c==8:
            (first,last)=unpack('<HH', h.read(4))
            for d in range(first, last):
                placements.append([objects[idx]])
                placements[-1].extend(pool[curpool][d])
        elif c==9:
            (l,)=unpack('<B', h.read(1))
            h.read(l*2)
        elif c==10:
            h.read(4)
        elif c==11:
            (l,)=unpack('<B', h.read(1))
            h.read(l*4)
        elif c==12:
            h.read(2)
            (l,)=unpack('<B', h.read(1))
            h.read(l*2)
        elif c==13:
            h.read(6)
        elif c==14:
            h.read(2)
            (l,)=unpack('<B', h.read(1))
            for i in range(l):
                (l2,)=unpack('<B', h.read(1))
                h.read(l2*2)
        elif c==15:
            h.read(2)
            (l,)=unpack('<B', h.read(1))
            h.read(l*2)
        elif c==16:
            #print "BEGIN_PATCH %d %.6f %.6f %d" % (idx, near, far, flags)
            if curpatch:
                mesh.append((curter,curpatch))
            curter=terrain[idx]
            curpatch=[]
        elif c==17:
            (flags,)=unpack('<B', h.read(1))
            #print "BEGIN_PATCH %d %.6f %.6f %d" % (idx, near, far, flags)
            if curpatch:
                mesh.append((curter,curpatch))
            curter=terrain[idx]
            curpatch=[]
        elif c==18:
            (flags,near,far)=unpack('<Bff', h.read(9))
            #print "BEGIN_PATCH %d %.6f %.6f %d" % (idx, near, far, flags)
            if curpatch:
                mesh.append((curter,curpatch))
            curter=terrain[idx]
            curpatch=[]

        elif c==23:
            (l,)=unpack('<B', h.read(1))
            if flags&1:
                points=[]
                for i in range(l):
                    (d,)=unpack('<H', h.read(2))
                    points.append(pool[curpool][d])
                curpatch.extend(points)
            else:
                h.read(2*l)
            
        elif c==24:
            (l,)=unpack('<B', h.read(1))
            if flags&1:
                points=[]
                for i in range(l):
                    (p,d)=unpack('<HH', h.read(4))
                    points.append(pool[p][d])
                curpatch.extend(points)
            else:
                h.read(4*l)

        elif c==25:
            (first,last)=unpack('<HH', h.read(4))
            if flags&1:
                curpatch.extend(pool[curpool][first:last])
            
        #elif c==26:
        #elif c==27:
        #elif c==28:
        elif c==29:
            (l,)=unpack('<B', h.read(1))
            if flags&1:
                points=[]
                for i in range(l):
                    (d,)=unpack('<H', h.read(2))
                    points.append(pool[curpool][d])
                curpatch.extend(meshfan(points))
            else:
                h.read(2*l)
            
        elif c==30:
            (l,)=unpack('<B', h.read(1))
            if flags&1:
                points=[]
                for i in range(l):
                    (p,d)=unpack('<HH', h.read(4))
                    points.append(pool[p][d])
                curpatch.extend(meshfan(points))
            else:
                h.read(4*l)

        elif c==31:
            (first,last)=unpack('<HH', h.read(4))
            if flags&1:
                curpatch.extend(meshfan(pool[curpool][first:last]))

        elif c==32:
            (l,)=unpack('<B', h.read(1))
            h.read(l)
        elif c==33:
            (l,)=unpack('<H', h.read(2))
            h.read(l)
        elif c==34:
            (l,)=unpack('<I', h.read(4))
            h.read(l)
        else:
            raise IOError, (c, "Unrecognised command", path)

    # Last one
    if curpatch:
        mesh.append((curter,curpatch))

    h.close()
    return (properties, placements, mesh)

def meshfan(points):
    tris=[]
    for i in range(1,len(points)-1):
        tris.append(points[0])
        tris.append(points[i])
        tris.append(points[i+1])
    return tris
