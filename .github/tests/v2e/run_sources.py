"""Synthetic loose/packed source fixtures; no installed game data or addon registration."""
from array import array
import importlib
import os
from pathlib import Path
import struct
import sys
import tempfile
import types

SOURCE = Path(os.environ['MED2_ADDON_SOURCE']) if os.environ.get('MED2_ADDON_SOURCE') else next(
    candidate for parent in Path(__file__).resolve().parents
    for candidate in (parent/'Medieval-2-Toolkit-main',parent) if (candidate/'m2formats').is_dir())
package = types.ModuleType('source_test'); package.__path__ = [str(SOURCE)]
sys.modules[package.__name__] = package
engine = importlib.import_module(package.__name__+'.tasks.animation_engine')
ap, ca = engine.animpack, engine.casanim
PATH = 'mods/Elsewhere/data/animations/Custom/stand.cas'


def packed(marker):
    nf, nq, npb = 3, 2, 1
    data = struct.pack('<HHB',nf,nq,npb)
    data += struct.pack('<4f',0,0,0,1)*(nf*nq)
    data += struct.pack('<3f',0,marker,0)*nf
    data += struct.pack('<2f',0,0)*nf + struct.pack('<f',0)*nf
    data += struct.pack('<3f',0,marker,0)*nf
    return data + struct.pack('<8f',.1,0,0,0,0,0,0,0) + (1).to_bytes(8,'little')


def skeleton(scale):
    bones = b''
    for name, parent, pos in [('bone_pelvis',-1,(0,0,0)),('bone_head',0,(0,.5,0))]:
        bones += struct.pack('<i3fi4si12f',0,*pos,parent,b'\0'*4,-1,*([0]*12))+name.encode()+b'\0'
    slot = PATH.encode()+b'\0'+struct.pack('<h3fhfhfhh3f',0,0,0,0,0,0,0,0,0,0,0,0,0)
    slot += struct.pack('<Iih',0,0,100)
    return struct.pack('<fHf',scale,2,0)+bones+slot+b'\0'*(ap.SKELETON_SLOTS-1)+struct.pack('<3f',0,0,0)


def writePack(folder,stem,magic,items):
    folder.mkdir(parents=True,exist_ok=True)
    at, entries, payloads = ap.HEADER_SIZE, [], []
    for name,scale,data in items:
        entries.append(ap.PackEntry(name,at,len(data),scale,3 if scale is not None else None,
                                    2 if scale is not None else None,1 if scale is not None else None))
        payloads.append(data); at += len(data)
    index = ap.PackIndex(magic,entries,1,1)
    (folder/(stem+'.idx')).write_bytes(index.to_bytes())
    (folder/(stem+'.dat')).write_bytes(index.header()+b''.join(payloads))


def packs(root,scale,variants):
    folder=root/'animations'
    writePack(folder,'skeletons',ap.SKEL_MAGIC,[('Test',None,skeleton(scale))])
    writePack(folder,'pack',ap.ANIM_MAGIC,[(PATH,s,packed(marker)) for s,marker in variants])


def loose(marker):
    anim=ca.Animation(source='loose.cas',length=.1,key_times=array('f',[0,.1]),tracks=[
        ca.Track('Scene Root',-1,(0,0,0)),
        ca.Track('bone_pelvis',0,(0,0,0),pos=array('f',[0,marker,0]*2)),
        ca.Track('bone_head',1,(0,.5,0))])
    return ca.write_anim(anim)


def marker(animation):
    return animation.tracks[1].pos[1] + animation.tracks[1].pivot[1]


with tempfile.TemporaryDirectory(prefix='v2e_sources_') as temporary:
    game=Path(temporary)/'game'; mod=game/'mods/TestMod/data'; vanilla=game/'data'
    mod.mkdir(parents=True); vanilla.mkdir(parents=True)
    packs(mod,2,[(1,10),(2,20),(2,21)])
    packs(vanilla,1,[(1,80)])
    descriptor='type Test\nscale 2\nanim stand '+PATH+' -fr\n'
    (mod/'descr_skeleton.txt').write_text(descriptor)
    (vanilla/'descr_skeleton.txt').write_text(descriptor)
    vanilla_loose=vanilla/'animations/Custom/stand.cas'
    vanilla_loose.parent.mkdir(parents=True); vanilla_loose.write_bytes(loose(99))
    assert marker(engine.loadAnimation(mod,'test',slot=0))==20
    assert marker(engine.loadAnimation(mod,'TEST',action='STAND'))==20
    (mod/'descr_skeleton.txt').write_text(descriptor+'anim STAND '+PATH.upper().replace('/','\\')+' -fr\n')
    assert marker(engine.loadAnimation(mod,'TEST',action='stand'))==20
    assert marker(engine.loadAnimation(mod,'Test',path=PATH.replace('/','\\')))==20
    print('PASS named packed slots/descriptor actions/path aliases select first exact-scale entry; mod pack beats vanilla loose')
    override=mod/'animations/CUSTOM/STAND.CAS'
    override.parent.mkdir(parents=True); override.write_bytes(loose(42))
    result=engine.loadAnimation(mod,'Test',slot=0)
    assert marker(result)==42 and result.med2_source_kind=='loose'
    print('PASS case-insensitive mod loose override wins over packed entry')
    override.write_bytes(b'broken override')
    try:
        engine.loadAnimation(mod,'Test',slot=0)
        raise AssertionError('Corrupt override silently fell back')
    except ca.AnimError:
        pass
    override.write_bytes(packed(23))
    result=engine.loadAnimation(mod,'Test',slot=0)
    assert marker(result)==23 and result.med2_source_kind=='unpacked'
    override.unlink()
    packs(mod,3,[(1,10),(2,20)])
    assert abs(marker(engine.loadAnimation(mod,'Test',slot=0))-30)<1e-5
    print('PASS malformed loose overrides refuse fallback; unpacked entries decode with named skeleton; smallest scale rescales')
    other=game/'mods/Other/data'; other.mkdir(parents=True)
    assert marker(engine.loadAnimation(other,'Test',action='stand'))==99
    vanilla_loose.unlink()
    result=engine.loadAnimation(other,'Test',slot=0)
    assert marker(result)==80 and result.med2_source_kind=='vanilla-pack'
    print('PASS absent mod packs/descriptor fall back to vanilla loose/packed sources; changed files invalidate caches')
    for kwargs in ({'slot':1},{'slot':999},{'path':'missing.cas'},{'action':'missing'},{}):
        try:
            engine.loadAnimation(mod,'Test',**kwargs)
            raise AssertionError('Invalid source accepted: '+repr(kwargs))
        except (ca.AnimError,ValueError):
            pass
    (mod/'descr_skeleton.txt').write_text(descriptor+'anim stand animations/another.cas -fr\n')
    try:
        engine.loadAnimation(mod,'Test',action='stand')
        raise AssertionError('Ambiguous action accepted')
    except ca.AnimError:
        pass
    packs(mod,0,[(1,10)])
    try:
        engine.loadAnimation(mod,'Test',slot=0)
        raise AssertionError('Zero-scale skeleton accepted')
    except ca.AnimError:
        pass
    print('PASS empty/missing slots, paths, actions and ambiguous descriptors report errors')
print('PASS v2e animation sources')
