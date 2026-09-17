# -*- coding: utf-8 -*-
"""Vector2/Vector3: objetos "de verdade" pro Lua, em vez de tabelas soltas.

    local pos = Vector2.new(100, 200)
    player.Position = pos              -- aceito em qualquer prop vetorial
    print(pos:distance(other))
    local n = pos:normalize()
    local mid = pos:lerp(other, 0.5)
"""

import math

from .lua import LuaTable, tostring


def _num(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def coerce_xyz(v):
    """Extrai (x, y, z) de Vector2/Vector3/LuaTable/numero. None se nao der."""
    if isinstance(v, Vector2):
        return (v.x, v.y, 0.0)
    if isinstance(v, Vector3):
        return (v.x, v.y, v.z)
    if isinstance(v, LuaTable):
        arr = v.ipairs_list()
        if len(arr) >= 2:
            return (_num(arr[0]), _num(arr[1]), _num(arr[2]) if len(arr) >= 3 else 0.0)
        x = v.get("x"); y = v.get("y"); z = v.get("z")
        if x is not None or y is not None:
            return (_num(x), _num(y), _num(z))
        return None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return (float(v), float(v), float(v))
    return None


class Vector2(object):
    __slots__ = ("x", "y")

    def __init__(self, x=0.0, y=0.0):
        self.x = _num(x)
        self.y = _num(y)

    # -------- integracao Lua (campos + metodos, igual Instance) --------
    def lua_index(self, key):
        k = tostring(key)
        if k in ("x", "X"):
            return self.x
        if k in ("y", "Y"):
            return self.y
        return getattr(self, "m_" + k, None)

    def lua_newindex(self, key, value):
        k = tostring(key)
        if k in ("x", "X"):
            self.x = _num(value)
        elif k in ("y", "Y"):
            self.y = _num(value)

    def __repr__(self):
        return "Vector2(%g, %g)" % (self.x, self.y)

    def _xy(self, other):
        c = coerce_xyz(other)
        return (c[0], c[1]) if c else (0.0, 0.0)

    # -------- metodos --------
    def m_length(self, *_a):
        return float(math.hypot(self.x, self.y))
    m_Length = m_length
    m_magnitude = m_length
    m_Magnitude = m_length

    def m_distance(self, _self=None, other=None):
        ox, oy = self._xy(other)
        return float(math.hypot(self.x - ox, self.y - oy))
    m_Distance = m_distance

    def m_normalize(self, *_a):
        l = math.hypot(self.x, self.y)
        if l <= 1e-9:
            return Vector2(0.0, 0.0)
        return Vector2(self.x / l, self.y / l)
    m_Normalize = m_normalize

    def m_lerp(self, _self=None, other=None, t=0.5):
        ox, oy = self._xy(other)
        t = _num(t, 0.5)
        return Vector2(self.x + (ox - self.x) * t, self.y + (oy - self.y) * t)
    m_Lerp = m_lerp

    def m_dot(self, _self=None, other=None):
        ox, oy = self._xy(other)
        return float(self.x * ox + self.y * oy)
    m_Dot = m_dot

    def m_add(self, _self=None, other=None):
        ox, oy = self._xy(other)
        return Vector2(self.x + ox, self.y + oy)
    m_Add = m_add

    def m_sub(self, _self=None, other=None):
        ox, oy = self._xy(other)
        return Vector2(self.x - ox, self.y - oy)
    m_Sub = m_sub

    def m_scale(self, _self=None, s=1.0):
        s = _num(s, 1.0)
        return Vector2(self.x * s, self.y * s)
    m_Scale = m_scale

    def m_unpack(self, *_a):
        return [self.x, self.y]
    m_Unpack = m_unpack


class Vector3(object):
    __slots__ = ("x", "y", "z")

    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.x = _num(x)
        self.y = _num(y)
        self.z = _num(z)

    def lua_index(self, key):
        k = tostring(key)
        if k in ("x", "X"):
            return self.x
        if k in ("y", "Y"):
            return self.y
        if k in ("z", "Z"):
            return self.z
        return getattr(self, "m_" + k, None)

    def lua_newindex(self, key, value):
        k = tostring(key)
        if k in ("x", "X"):
            self.x = _num(value)
        elif k in ("y", "Y"):
            self.y = _num(value)
        elif k in ("z", "Z"):
            self.z = _num(value)

    def __repr__(self):
        return "Vector3(%g, %g, %g)" % (self.x, self.y, self.z)

    def _xyz(self, other):
        c = coerce_xyz(other)
        return c if c else (0.0, 0.0, 0.0)

    def m_length(self, *_a):
        return float(math.sqrt(self.x * self.x + self.y * self.y + self.z * self.z))
    m_Length = m_length
    m_magnitude = m_length
    m_Magnitude = m_length

    def m_distance(self, _self=None, other=None):
        ox, oy, oz = self._xyz(other)
        return float(math.sqrt((self.x - ox) ** 2 + (self.y - oy) ** 2 + (self.z - oz) ** 2))
    m_Distance = m_distance

    def m_normalize(self, *_a):
        l = math.sqrt(self.x * self.x + self.y * self.y + self.z * self.z)
        if l <= 1e-9:
            return Vector3(0.0, 0.0, 0.0)
        return Vector3(self.x / l, self.y / l, self.z / l)
    m_Normalize = m_normalize

    def m_lerp(self, _self=None, other=None, t=0.5):
        ox, oy, oz = self._xyz(other)
        t = _num(t, 0.5)
        return Vector3(self.x + (ox - self.x) * t, self.y + (oy - self.y) * t, self.z + (oz - self.z) * t)
    m_Lerp = m_lerp

    def m_dot(self, _self=None, other=None):
        ox, oy, oz = self._xyz(other)
        return float(self.x * ox + self.y * oy + self.z * oz)
    m_Dot = m_dot

    def m_cross(self, _self=None, other=None):
        ox, oy, oz = self._xyz(other)
        return Vector3(self.y * oz - self.z * oy, self.z * ox - self.x * oz, self.x * oy - self.y * ox)
    m_Cross = m_cross

    def m_add(self, _self=None, other=None):
        ox, oy, oz = self._xyz(other)
        return Vector3(self.x + ox, self.y + oy, self.z + oz)
    m_Add = m_add

    def m_sub(self, _self=None, other=None):
        ox, oy, oz = self._xyz(other)
        return Vector3(self.x - ox, self.y - oy, self.z - oz)
    m_Sub = m_sub

    def m_scale(self, _self=None, s=1.0):
        s = _num(s, 1.0)
        return Vector3(self.x * s, self.y * s, self.z * s)
    m_Scale = m_scale

    def m_unpack(self, *_a):
        return [self.x, self.y, self.z]
    m_Unpack = m_unpack


class _Vector2Ctor(object):
    """Global `Vector2`: aceita `Vector2.new(x,y)` e `Vector2(x,y)`."""

    def lua_index(self, key):
        if tostring(key) == "new":
            return self._new
        return None

    def _new(self, x=0.0, y=0.0):
        return Vector2(x, y)

    def lua_call(self, args):
        return [self._new(*args)]


class _Vector3Ctor(object):
    """Global `Vector3`: aceita `Vector3.new(x,y,z)` e `Vector3(x,y,z)`."""

    def lua_index(self, key):
        if tostring(key) == "new":
            return self._new
        return None

    def _new(self, x=0.0, y=0.0, z=0.0):
        return Vector3(x, y, z)

    def lua_call(self, args):
        return [self._new(*args)]


VECTOR2 = _Vector2Ctor()
VECTOR3 = _Vector3Ctor()
