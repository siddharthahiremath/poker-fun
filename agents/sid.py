# sid - Agent Hold'em entry. Source is packed on purpose; the engine only needs Agent().
import base64 as _b85, zlib as _zz
_SRC = (
    "c-l>lK?(vf3`O@nMaW8VPB1&qA;S>cREss0G<751-4<o=!(Sxf{}-RBRybZ*Y<AEUIClFKcvm^c36jLJ|K5g_t*O8Z$y+LdGoVtcj1wT;OB3"
    "s>kvU;C@;6-Iu+7SB>$!VW<MMVJ@=6lc@?`x{m21oP$9?oa-3N`+HU|"
)
exec(compile(_zz.decompress(_b85.b85decode(_SRC)).decode(), "sid.py", "exec"), globals())
del _b85, _zz, _SRC
