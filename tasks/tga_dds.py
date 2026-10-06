"""The game's .tga.dds texture scheme: an empty .tga with the real picture in a
DXT5 .tga.dds beside it.

Whenever the game is asked for `x.tga` it loads `x.tga.dds` if there is one,
so the .tga only has to exist - every .tga in a mod's models_strat/textures
ships as a 0-byte placeholder next to its .tga.dds, and the same works for the
ui folder (ProJYeet's TGA Optimizer, from medik's idea, does this to whole
mods). A DXT5 .tga.dds is smaller on disk and quicker for the game to load than
the TGA it replaces.

This is that tool's conversion step for one file, used wherever the addon
writes a .tga the game will read: the strat atlas and the unit/info cards.
"""
import os
import struct

from .unit_exporter import get_texconv_path, runTexconv

TGA_HEADER = struct.Struct("<BBBHHBHHHHBB")
TGA_RLE = 10
TGA_UNCOMPRESSED = 2


def gameTexturePath(tga_path):
    """The file the game actually reads for a .tga: the same name with .dds on
    the end."""
    return tga_path + ".dds" if tga_path else ''


def decodeRLE(tga_file, width, height, pixel_size):
    out = bytearray()
    wanted = width * height * pixel_size
    while len(out) < wanted:
        packet_header = tga_file.read(1)
        if not packet_header:
            break
        count = (packet_header[0] & 0x7F) + 1
        if packet_header[0] & 0x80:
            out.extend(tga_file.read(pixel_size) * count)
        else:
            out.extend(tga_file.read(pixel_size * count))
    return bytes(out[:wanted])


def uncompressTGA(tga_path):
    """Rewrite an RLE (type 10) TGA uncompressed, in place. Blender writes
    TARGA as RLE, and the optimizer found texconv cannot be trusted with it.
    Returns None or a reason string."""
    try:
        with open(tga_path, 'rb') as tga_file:
            header = tga_file.read(TGA_HEADER.size)
            if len(header) < TGA_HEADER.size:
                return "%s is not a TGA" % os.path.basename(tga_path)
            (id_length, colour_map_type, image_type, _first, colour_map_length, colour_map_depth,
             _x, _y, width, height, bits, descriptor) = TGA_HEADER.unpack(header)
            if image_type != TGA_RLE:
                return None
            tga_file.seek(id_length, 1)
            if colour_map_type == 1:
                tga_file.seek(colour_map_length * (colour_map_depth // 8), 1)
            pixels = decodeRLE(tga_file, width, height, bits // 8)
        with open(tga_path, 'wb') as tga_file:
            # the descriptor keeps the alpha depth and which corner row 0 is
            tga_file.write(TGA_HEADER.pack(0, 0, TGA_UNCOMPRESSED, 0, 0, 0, 0, 0, width, height, bits, descriptor))
            tga_file.write(pixels)
    except OSError as error:
        return "Could not uncompress %s: %s" % (os.path.basename(tga_path), error)
    return None


def writeTgaDds(tga_path):
    """Turn a freshly written .tga into the .tga.dds the game reads plus an
    empty .tga placeholder. Returns (dds path or None, reason or None).

    The .tga is only emptied once the .tga.dds is safely on disk, so a failed
    conversion leaves the picture where it was."""
    texconv = get_texconv_path()
    if texconv is None:
        return None, "texconv not found, so %s was left as a full .tga" % os.path.basename(tga_path)
    reason = uncompressTGA(tga_path)
    if reason is not None:
        return None, reason
    dds = runTexconv(texconv, tga_path, os.path.dirname(tga_path), os.path.basename(tga_path))
    if dds is None or not os.path.isfile(dds):
        return None, "texconv could not convert %s, so it was left as a full .tga" % os.path.basename(tga_path)
    try:
        open(tga_path, 'wb').close()
    except OSError as error:
        return dds, "Wrote %s but could not empty the .tga: %s" % (os.path.basename(dds), error)
    return dds, None


def viewablePath(tga_path):
    """What to open to look at a .tga this module may have emptied: the
    .tga.dds when the .tga is the placeholder, else the .tga itself."""
    dds = gameTexturePath(tga_path)
    try:
        if os.path.getsize(tga_path) == 0 and os.path.isfile(dds):
            return dds
    except OSError:
        pass
    return tga_path
