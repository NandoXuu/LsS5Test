# -*- coding: utf-8 -*-
import math

from .lua import LuaTable, LuaError, truthy, tostring
from .api import Instance, to_vec, vec_table
from .collision import (Material, MaterialRegistry, Collider, collide, _num, _opt)

FIXED_DT = 1.0 / 60.0
MAX_STEPS = 6
MAX_SUBDIV = 4
SLOP = 0.3
BAUMGARTE = 0.2
MAX_BIAS = 500.0
REST_THRESHOLD = 60.0
MAX_SPEED = 8000.0
MAX_SPIN = 120.0

BODY_TYPES = {
    "dynamic": "dynamic", "rigid": "dynamic", "rigidbody": "dynamic",
    "static": "static", "kinematic": "kinematic",
}

DEFAULT_COLLIDER = Collider(LuaTable(), MaterialRegistry())


def normalize_type(v):
    t = BODY_TYPES.get(tostring(v).lower())
    if t is None:
        raise LuaError("BodyType '%s' invalido (use \"dynamic\", \"static\" ou \"kinematic\")" % tostring(v))
    return t


def body_kind(obj):
    bt = obj.props.get("BodyType")
    if bt:
        return BODY_TYPES.get(str(bt).lower(), "dynamic")
    if truthy(obj.props.get("Static")):
        return "static"
    return None


def owner_of(obj):
    return getattr(obj, "_owner", None) or obj


def find_callback(obj, name):
    cb = obj.props.get(name)
    if cb is None:
        ow = getattr(obj, "_owner", None)
        if ow is not None:
            cb = ow.fields.get(name)
    return cb


class CP(object):
    __slots__ = ("x", "y", "pen", "rax", "ray", "rbx", "rby", "nm", "tm", "vb",
                 "jn", "jt", "jb", "tgt", "vn0")


class Contact(object):
    __slots__ = ("sa", "sb", "ba", "bb", "nx", "ny", "pts", "friction", "restitution")


class PairInfo(object):
    __slots__ = ("ba", "bb", "nx", "ny", "px", "py", "pen", "imp", "speed")


class Body(object):
    def __init__(self, obj):
        self.obj = obj
        self.uid = id(self)
        self.kind = "dynamic"
        self.x = self.y = self.a = 0.0
        self.vx = self.vy = self.w = 0.0
        self.bvx = self.bvy = self.bw = 0.0
        self.inv_m = self.inv_i = 0.0
        self.mass = 0.0
        self.cxl = self.cyl = 0.0
        self.c = 1.0
        self.s = 0.0
        self.ox = self.oy = 0.0
        self.size = (0.0, 0.0)
        self.shapes = []
        self.sig = None
        self.fx = self.fy = self.tq = 0.0
        self.min_ext = 1e9
        self.last_pos = None
        self.kin = (0.0, 0.0, 0.0)
        self.gscale = 1.0
        self.ld = 0.0
        self.ad = 0.0
        self.gravity = None
        self.live = -1

    def signature(self, obj, kind):
        p = obj.props
        cols = getattr(obj, "_colliders", None) or ()
        return (kind, tuple(c.signature() for c in cols), obj.size(), obj.axis_scale(),
                _num(p.get("Mass"), 1.0), truthy(p.get("FixedRotation")),
                _num(p.get("Friction"), 0.5), _num(p.get("Bounce"), 0.2),
                int(_num(p.get("CollisionLayer"), 1)), int(_num(p.get("CollisionMask"), 65535)),
                truthy(p.get("Collidable", True)))

    def rebuild(self, obj, kind):
        p = obj.props
        cols = getattr(obj, "_colliders", None)
        body_f = max(0.0, _num(p.get("Friction"), 0.5))
        body_r = max(0.0, _num(p.get("Bounce"), 0.2))
        layer = int(_num(p.get("CollisionLayer"), 1))
        mask = int(_num(p.get("CollisionMask"), 65535))
        shapes = []
        if truthy(p.get("Collidable", True)):
            for col in (cols or [DEFAULT_COLLIDER]):
                for sh in col.make_shapes(obj):
                    sh.collider = col
                    sh.body = self
                    sh.sensor = col.sensor
                    if col.friction is not None:
                        sh.friction = col.friction
                    elif col.material is not None:
                        sh.friction = col.material.friction
                    else:
                        sh.friction = body_f
                    if col.restitution is not None:
                        sh.restitution = col.restitution
                    elif col.material is not None:
                        sh.restitution = col.material.restitution
                    else:
                        sh.restitution = body_r
                    sh.layer = col.layer if col.layer is not None else layer
                    sh.mask = col.mask if col.mask is not None else mask
                    shapes.append(sh)
        solid = [s for s in shapes if not s.sensor]
        w, h, _ = obj.eff_size()
        self.cxl = self.cyl = 0.0
        self.inv_m = self.inv_i = 0.0
        self.mass = 0.0
        if kind == "dynamic":
            m = _num(p.get("Mass"), 1.0)
            if m <= 0.0:
                m = 1.0
            self.mass = m
            cx = cy = 0.0
            inertia = 0.0
            if solid:
                tot = sum(s.area for s in solid)
                i0 = 0.0
                for s in solid:
                    mi = m * s.area / tot
                    cx += mi * s.centroid[0]
                    cy += mi * s.centroid[1]
                    i0 += (mi / s.area) * s.inertia
                cx /= m
                cy /= m
                inertia = i0 - m * (cx * cx + cy * cy)
            if inertia <= 1e-6:
                inertia = m * (w * w + h * h) / 12.0
                cx = cy = 0.0
            self.cxl, self.cyl = cx, cy
            self.inv_m = 1.0 / m
            self.inv_i = 0.0 if truthy(p.get("FixedRotation")) else 1.0 / max(inertia, 1e-6)
        for s in shapes:
            s.shift(-self.cxl, -self.cyl)
        self.shapes = shapes
        self.min_ext = min([s.extent() for s in solid] or [1e9])

    def pose_from(self, px, py, deg, w, h):
        self.size = (w, h)
        self.ox = px + w / 2.0
        self.oy = py + h / 2.0
        self.a = math.radians(deg)
        self.c = math.cos(self.a)
        self.s = math.sin(self.a)
        self.x = self.ox + self.c * self.cxl - self.s * self.cyl
        self.y = self.oy + self.s * self.cxl + self.c * self.cyl

    def refresh(self, kind, implied_time=None):
        obj = self.obj
        p = obj.props
        sig = self.signature(obj, kind)
        self.kind = kind
        if sig != self.sig:
            self.rebuild(obj, kind)
            self.sig = sig
        px, py, _ = obj.pos()
        deg = obj.rot()
        w, h, _ = obj.eff_size()
        vx, vy, _ = to_vec(p.get("Velocity"), (0.0, 0.0, 0.0))
        wv = math.radians(_num(p.get("AngularVelocity")))
        self.gscale = 0.0 if not truthy(p.get("UseGravity", True)) else _num(p.get("GravityScale"), 1.0)
        self.ld = max(0.0, _num(p.get("LinearDamping")))
        self.ad = max(0.0, _num(p.get("AngularDamping")))
        g = p.get("Gravity")
        if g is not None:
            gx, gy, _ = to_vec(g, (0.0, 0.0, 0.0))
            self.gravity = (gx, gy)
        else:
            self.gravity = None
        self.kin = (0.0, 0.0, 0.0)
        if kind == "dynamic":
            self.vx, self.vy, self.w = vx, vy, wv
        elif kind == "kinematic":
            kx, ky, kw = vx, vy, wv
            lp = self.last_pos
            if implied_time and lp is not None and (
                    abs(px - lp[0]) > 1e-6 or abs(py - lp[1]) > 1e-6 or abs(deg - lp[2]) > 1e-6):
                kx += (px - lp[0]) / implied_time
                ky += (py - lp[1]) / implied_time
                kw += math.radians(deg - lp[2]) / implied_time
                px, py, deg = lp
            self.vx, self.vy, self.w = kx, ky, kw
        else:
            self.vx = self.vy = self.w = 0.0
        self.pose_from(px, py, deg, w, h)

    def write_velocity(self):
        p = self.obj.props
        p["Velocity"] = vec_table(self.vx, self.vy, 0.0)
        p["AngularVelocity"] = math.degrees(self.w)

    def store(self):
        obj = self.obj
        p = obj.props
        ox = self.x - (self.c * self.cxl - self.s * self.cyl)
        oy = self.y - (self.s * self.cxl + self.c * self.cyl)
        px = ox - self.size[0] / 2.0
        py = oy - self.size[1] / 2.0
        deg = math.degrees(self.a)
        z = obj.pos()[2]
        p["Position"] = vec_table(px, py, z)
        p["Rotation"] = deg
        if self.kind == "dynamic":
            self.write_velocity()
        self.last_pos = (px, py, deg)

    def aabb(self):
        if not self.shapes:
            return None
        return (min(s.minx for s in self.shapes), min(s.miny for s in self.shapes),
                max(s.maxx for s in self.shapes), max(s.maxy for s in self.shapes))


class Joint(object):
    def __init__(self, world, kind, a_lua, a_obj, b_lua, b_obj, spec):
        self.world = world
        self.kind = kind
        self.a_lua, self.a_obj = a_lua, a_obj
        self.b_lua, self.b_obj = b_lua, b_obj
        self.alive = True
        if spec is None:
            spec = LuaTable()
        anchor = _opt(spec, "Anchor")
        if anchor is not None:
            wx, wy, _ = to_vec(anchor, (0.0, 0.0, 0.0))
            self.anchor_a = self._to_local(a_obj, wx, wy)
            self.anchor_b = self._to_local(b_obj, wx, wy) if b_obj is not None else (wx, wy)
        else:
            ax, ay, _ = to_vec(_opt(spec, "AnchorA"), (0.0, 0.0, 0.0))
            bx, by, _ = to_vec(_opt(spec, "AnchorB"), (0.0, 0.0, 0.0))
            self.anchor_a = (ax, ay)
            self.anchor_b = (bx, by)
        ln = _opt(spec, "Length")
        self.length = max(0.0, _num(ln)) if ln is not None else None
        default_freq = 4.0 if kind == "spring" else 0.0
        self.freq = max(0.0, _num(_opt(spec, "Frequency"), default_freq))
        self.zeta = max(0.0, _num(_opt(spec, "DampingRatio"), 0.5))
        self.collide_connected = truthy(_opt(spec, "CollideConnected", False))
        self.motor_speed = math.radians(_num(_opt(spec, "MotorSpeed")))
        self.max_torque = max(0.0, _num(_opt(spec, "MaxMotorTorque")))
        self.ref_angle = None
        self.acc = 0.0
        self.acc_x = self.acc_y = 0.0
        self.acc_t = 0.0
        self.acc_m = 0.0
        self.a = self.b = None
        self.rax = self.ray = self.rbx = self.rby = 0.0
        self.ux = self.uy = 0.0
        self.mass_eff = 0.0
        self.gamma = 0.0
        self.bias = 0.0
        self.k11 = self.k12 = self.k22 = 0.0
        self.m_ang = 0.0
        self.ang_bias = 0.0

    @staticmethod
    def _to_local(obj, wx, wy):
        px, py, _ = obj.pos()
        w, h, _ = obj.eff_size()
        a = math.radians(obj.rot())
        c, s = math.cos(a), math.sin(a)
        dx, dy = wx - (px + w / 2.0), wy - (py + h / 2.0)
        return (c * dx + s * dy, -s * dx + c * dy)

    def lua_index(self, key):
        k = str(key)
        if k == "Type":
            return self.kind
        if k == "A":
            return self.a_lua
        if k == "B":
            return self.b_lua
        if k == "Alive":
            return self.alive
        if k == "Length":
            return self.length
        if k == "Frequency":
            return self.freq
        if k == "DampingRatio":
            return self.zeta
        if k == "MotorSpeed":
            return math.degrees(self.motor_speed)
        if k == "MaxMotorTorque":
            return self.max_torque
        if k == "CollideConnected":
            return self.collide_connected
        if k == "Destroy":
            return self.m_Destroy
        return None

    def lua_newindex(self, key, value):
        k = str(key)
        if k == "Length":
            self.length = max(0.0, _num(value))
        elif k == "Frequency":
            self.freq = max(0.0, _num(value))
        elif k == "DampingRatio":
            self.zeta = max(0.0, _num(value))
        elif k == "MotorSpeed":
            self.motor_speed = math.radians(_num(value))
        elif k == "MaxMotorTorque":
            self.max_torque = max(0.0, _num(value))
        elif k == "CollideConnected":
            self.collide_connected = truthy(value)

    def m_Destroy(self, *_a):
        self.alive = False

    def prestep(self, h, a, b):
        self.a, self.b = a, b
        ax, ay = self.anchor_a[0] - a.cxl, self.anchor_a[1] - a.cyl
        self.rax = a.c * ax - a.s * ay
        self.ray = a.s * ax + a.c * ay
        bx, by = self.anchor_b[0] - b.cxl, self.anchor_b[1] - b.cyl
        self.rbx = b.c * bx - b.s * by
        self.rby = b.s * bx + b.c * by
        if self.kind in ("distance", "spring"):
            self._pre_distance(h)
        else:
            self._pre_point(h)

    def _apply(self, px, py):
        a, b = self.a, self.b
        a.vx -= a.inv_m * px
        a.vy -= a.inv_m * py
        a.w -= a.inv_i * (self.rax * py - self.ray * px)
        b.vx += b.inv_m * px
        b.vy += b.inv_m * py
        b.w += b.inv_i * (self.rbx * py - self.rby * px)

    def _pre_distance(self, h):
        a, b = self.a, self.b
        dx = (b.x + self.rbx) - (a.x + self.rax)
        dy = (b.y + self.rby) - (a.y + self.ray)
        ln = math.hypot(dx, dy)
        if self.length is None:
            self.length = ln
        if ln > 1e-6:
            self.ux, self.uy = dx / ln, dy / ln
        else:
            self.ux = self.uy = 0.0
        cra = self.rax * self.uy - self.ray * self.ux
        crb = self.rbx * self.uy - self.rby * self.ux
        im = a.inv_m + b.inv_m + a.inv_i * cra * cra + b.inv_i * crb * crb
        me = 1.0 / im if im > 0.0 else 0.0
        c_err = ln - self.length
        if self.freq > 0.0:
            omega = 2.0 * math.pi * self.freq
            d = 2.0 * me * self.zeta * omega
            k = me * omega * omega
            gamma = h * (d + h * k)
            gamma = 1.0 / gamma if gamma > 0.0 else 0.0
            self.bias = c_err * h * k * gamma
            self.gamma = gamma
            self.mass_eff = 1.0 / (im + gamma) if (im + gamma) > 0.0 else 0.0
        else:
            self.gamma = 0.0
            self.bias = max(-MAX_BIAS, min(MAX_BIAS, BAUMGARTE / h * c_err))
            self.mass_eff = me
        self._apply(self.acc * self.ux, self.acc * self.uy)

    def _pre_point(self, h):
        a, b = self.a, self.b
        ia, ib = a.inv_i, b.inv_i
        ma, mb = a.inv_m, b.inv_m
        self.k11 = ma + mb + self.ray * self.ray * ia + self.rby * self.rby * ib
        self.k12 = -self.ray * self.rax * ia - self.rby * self.rbx * ib
        self.k22 = ma + mb + self.rax * self.rax * ia + self.rbx * self.rbx * ib
        isum = ia + ib
        self.m_ang = 1.0 / isum if isum > 0.0 else 0.0
        if self.ref_angle is None:
            self.ref_angle = b.a - a.a
        err = (b.a - a.a) - self.ref_angle
        self.ang_bias = max(-MAX_BIAS, min(MAX_BIAS, BAUMGARTE / h * err))
        self._apply(self.acc_x, self.acc_y)
        if self.m_ang > 0.0:
            a.w -= ia * (self.acc_t + self.acc_m)
            b.w += ib * (self.acc_t + self.acc_m)

    def solve(self, h):
        if self.kind in ("distance", "spring"):
            a, b = self.a, self.b
            vax = a.vx - a.w * self.ray
            vay = a.vy + a.w * self.rax
            vbx = b.vx - b.w * self.rby
            vby = b.vy + b.w * self.rbx
            cdot = self.ux * (vbx - vax) + self.uy * (vby - vay)
            imp = -self.mass_eff * (cdot + self.bias + self.gamma * self.acc)
            self.acc += imp
            self._apply(imp * self.ux, imp * self.uy)
            return
        a, b = self.a, self.b
        if self.kind == "revolute" and self.max_torque > 0.0 and self.m_ang > 0.0:
            cdot = b.w - a.w - self.motor_speed
            imp = -self.m_ang * cdot
            mx = self.max_torque * h
            new = max(-mx, min(mx, self.acc_m + imp))
            imp = new - self.acc_m
            self.acc_m = new
            a.w -= a.inv_i * imp
            b.w += b.inv_i * imp
        if self.kind == "fixed" and self.m_ang > 0.0:
            cdot = b.w - a.w
            imp = -self.m_ang * (cdot + self.ang_bias)
            self.acc_t += imp
            a.w -= a.inv_i * imp
            b.w += b.inv_i * imp
        dvx = b.vx - b.w * self.rby - a.vx + a.w * self.ray
        dvy = b.vy + b.w * self.rbx - a.vy - a.w * self.rax
        cx = (b.x + self.rbx) - (a.x + self.rax)
        cy = (b.y + self.rby) - (a.y + self.ray)
        k = BAUMGARTE / h
        bx = max(-MAX_BIAS, min(MAX_BIAS, k * cx))
        by = max(-MAX_BIAS, min(MAX_BIAS, k * cy))
        rx, ry = -(dvx + bx), -(dvy + by)
        det = self.k11 * self.k22 - self.k12 * self.k12
        if abs(det) < 1e-12:
            return
        ix = (self.k22 * rx - self.k12 * ry) / det
        iy = (self.k11 * ry - self.k12 * rx) / det
        self.acc_x += ix
        self.acc_y += iy
        self._apply(ix, iy)


class RigidWorld(object):
    def __init__(self, physics):
        self.physics = physics
        self.materials = MaterialRegistry()
        self.time_scale = 1.0
        self.enabled = True
        self.paused = False
        self.vel_iters = 8
        self.pos_iters = 3
        self.debug = None
        self.debug_data = None
        self.ground = Body(None)
        self.ground.kind = "static"
        self.reset()

    def reset(self):
        self.acc = 0.0
        self.prev_manifolds = {}
        self.pairs = {}
        self.triggers = {}
        self.joints = []
        self.bodies = []
        self.step_id = 0
        self.debug_data = None
        self.last_contacts = []

    def set_debug(self, value):
        if value is None or value is True:
            self.debug = dict.fromkeys(("Colliders", "Mass", "Velocity", "Contacts", "Normals", "Joints"), True)
        elif value is False:
            self.debug = None
            self.debug_data = None
        elif isinstance(value, LuaTable):
            flags = {}
            for k in ("Colliders", "Mass", "Velocity", "Contacts", "Normals", "Joints"):
                v = value.get(k)
                if v is not None and truthy(v):
                    flags[k] = True
            self.debug = flags or None
        elif truthy(value):
            self.set_debug(True)
        else:
            self.set_debug(False)

    def create_joint(self, kind, spec):
        if not isinstance(spec, LuaTable):
            raise LuaError("physics.joint: o argumento precisa ser uma tabela { A = ..., B = ... }")
        a_lua = spec.get("A")
        b_lua = spec.get("B")
        a_obj = self._resolve(a_lua, "A")
        b_obj = self._resolve(b_lua, "B") if b_lua is not None else None
        if a_obj is None:
            raise LuaError("physics.joint: falta o corpo A")
        j = Joint(self, kind, a_lua, a_obj, b_lua, b_obj, spec)
        self.joints.append(j)
        return j

    @staticmethod
    def _resolve(v, label):
        if v is None:
            return None
        tgt = getattr(v, "_phys_target", None)
        if tgt is not None:
            v = tgt
        if not isinstance(v, Instance):
            raise LuaError("physics.joint: %s precisa ser um objeto com fisica" % label)
        if not v.props.get("BodyType"):
            raise LuaError("physics.joint: '%s' ainda nao tem corpo fisico (use EnablePhysics{Type=...})" % v.name)
        return v

    def collect(self):
        objs = []
        any_rigid = False
        for o in self.physics.runtime.scene.objects:
            if not o.alive:
                continue
            pr = o.props
            if not truthy(pr.get("Physics")) or truthy(pr.get("IsArea")):
                continue
            if pr.get("BodyType"):
                any_rigid = True
                objs.append(o)
            elif truthy(pr.get("Static")):
                objs.append(o)
        return objs if any_rigid else None

    def step(self, dt):
        if not self.enabled or self.paused:
            return
        self.advance(dt * self.time_scale)

    def manual_step(self, dt):
        self.advance(max(0.0, float(dt or 0.0)), manual=True)

    def advance(self, dt, manual=False):
        if dt <= 0.0:
            return
        objs = self.collect()
        if objs is None:
            self.bodies = []
            if self.pairs or self.triggers:
                self._dispatch({}, {}, "Collision")
                self._dispatch({}, {}, "Trigger")
                self.pairs, self.triggers = {}, {}
            return
        if manual:
            n = max(1, int(round(dt / FIXED_DT)))
        else:
            self.acc = min(self.acc + dt, FIXED_DT * MAX_STEPS)
            n = int(self.acc / FIXED_DT + 1e-9)
            if n <= 0:
                return
            self.acc -= n * FIXED_DT
        total = n * FIXED_DT
        self.step_id += 1
        bodies = []
        for o in objs:
            b = getattr(o, "_rb", None)
            if b is None:
                b = Body(o)
                o._rb = b
            kind = body_kind(o)
            b.refresh(kind, total)
            b.live = self.step_id
            if kind == "static":
                for s in b.shapes:
                    s.transform(b.x, b.y, b.c, b.s)
            bodies.append(b)
        self.bodies = bodies
        active = self._active_joints()
        noc = set()
        for j in active:
            if not j.collide_connected:
                u1, u2 = j.a.uid, j.b.uid
                noc.add((u1, u2) if u1 < u2 else (u2, u1))
        sub = 1
        for b in bodies:
            if b.kind == "dynamic" and b.min_ext < 1e8:
                speed = math.hypot(b.vx, b.vy) * FIXED_DT
                need = int(math.ceil(speed / max(b.min_ext * 0.5, 2.0)))
                if need > sub:
                    sub = need
        sub = min(sub, MAX_SUBDIV)
        h = FIXED_DT / sub
        pair_acc, trig_acc = {}, {}
        contacts = []
        for _ in range(n * sub):
            contacts = self._substep(h, bodies, active, noc, pair_acc, trig_acc)
        for b in bodies:
            b.fx = b.fy = b.tq = 0.0
        self.last_contacts = contacts
        for b in bodies:
            if b.kind != "static":
                b.store()
            ab = b.aabb()
            b.obj._rb_aabb = ab
        self.physics.runtime.scene.dirty = True
        self._sync_groups()
        self._dispatch(pair_acc, self.pairs, "Collision")
        self._dispatch(trig_acc, self.triggers, "Trigger")
        self.pairs = pair_acc
        self.triggers = trig_acc
        if self.debug:
            self._build_debug(bodies, active, contacts)

    def _active_joints(self):
        out = []
        keep = []
        for j in self.joints:
            if not j.alive or not j.a_obj.alive or (j.b_obj is not None and not j.b_obj.alive):
                j.alive = False
                continue
            keep.append(j)
            a = getattr(j.a_obj, "_rb", None)
            if a is None or a.live != self.step_id:
                continue
            if j.b_obj is None:
                b = self.ground
            else:
                b = getattr(j.b_obj, "_rb", None)
                if b is None or b.live != self.step_id:
                    continue
            j.a, j.b = a, b
            out.append(j)
        self.joints = keep
        return out

    def _sync_groups(self):
        for g in list(self.physics.runtime.prefabs.live):
            if g.alive and getattr(g, "_phys_target", None) is not None:
                g.physics_sync()

    def _substep(self, h, bodies, joints, noc, pair_acc, trig_acc):
        grav = self.physics.gravity
        for b in bodies:
            b.bvx = b.bvy = b.bw = 0.0
            if b.kind == "dynamic":
                gx, gy = b.gravity if b.gravity is not None else (grav[0], grav[1])
                b.vx += (gx * b.gscale + b.fx * b.inv_m) * h
                b.vy += (gy * b.gscale + b.fy * b.inv_m) * h
                b.w += b.tq * b.inv_i * h
                if b.ld:
                    f = 1.0 / (1.0 + h * b.ld)
                    b.vx *= f
                    b.vy *= f
                if b.ad:
                    b.w *= 1.0 / (1.0 + h * b.ad)
                sp = math.hypot(b.vx, b.vy)
                if sp > MAX_SPEED:
                    k = MAX_SPEED / sp
                    b.vx *= k
                    b.vy *= k
                if b.w > MAX_SPIN:
                    b.w = MAX_SPIN
                elif b.w < -MAX_SPIN:
                    b.w = -MAX_SPIN
            if b.kind != "static":
                b.c = math.cos(b.a)
                b.s = math.sin(b.a)
                for s in b.shapes:
                    s.transform(b.x, b.y, b.c, b.s)
        shapes = []
        for b in bodies:
            shapes.extend(b.shapes)
        shapes.sort(key=lambda s: s.minx)
        contacts = []
        n = len(shapes)
        for i in range(n):
            sa = shapes[i]
            ba = sa.body
            maxx, miny, maxy = sa.maxx, sa.miny, sa.maxy
            for j in range(i + 1, n):
                sb = shapes[j]
                if sb.minx > maxx:
                    break
                if sb.miny > maxy or sb.maxy < miny:
                    continue
                bb = sb.body
                if ba is bb:
                    continue
                if not ((sa.layer & sb.mask) and (sb.layer & sa.mask)):
                    continue
                sensor = sa.sensor or sb.sensor
                if sensor:
                    if ba.kind == "static" and bb.kind == "static":
                        continue
                elif ba.kind != "dynamic" and bb.kind != "dynamic":
                    continue
                if noc:
                    key = (ba.uid, bb.uid) if ba.uid < bb.uid else (bb.uid, ba.uid)
                    if key in noc:
                        continue
                x, y = (sa, sb) if sa.id < sb.id else (sb, sa)
                m = collide(x, y)
                if m is None:
                    continue
                if sensor:
                    k2 = (ba.uid, bb.uid) if ba.uid < bb.uid else (bb.uid, ba.uid)
                    if k2 not in trig_acc:
                        trig_acc[k2] = (ba, bb) if ba.uid < bb.uid else (bb, ba)
                    continue
                c = Contact()
                c.sa, c.sb = x, y
                c.ba, c.bb = x.body, y.body
                c.nx, c.ny = m[0], m[1]
                c.friction = math.sqrt(x.friction * y.friction)
                c.restitution = max(x.restitution, y.restitution)
                c.pts = []
                for px, py, pen in m[2]:
                    p = CP()
                    p.x, p.y, p.pen = px, py, pen
                    p.jn = p.jt = p.jb = 0.0
                    c.pts.append(p)
                contacts.append(c)
        self._solve(h, contacts, joints)
        for c in contacts:
            self._record(c, pair_acc)
        for b in bodies:
            if b.kind != "static":
                b.x += (b.vx + b.bvx) * h
                b.y += (b.vy + b.bvy) * h
                b.a += (b.w + b.bw) * h
        return contacts

    def _solve(self, h, contacts, joints):
        prev = self.prev_manifolds
        newm = {}
        for j in joints:
            j.prestep(h, j.a, j.b)
        for c in contacts:
            a, b = c.ba, c.bb
            nx, ny = c.nx, c.ny
            tx, ty = ny, -nx
            old = prev.get((c.sa.id, c.sb.id))
            for p in c.pts:
                p.rax, p.ray = p.x - a.x, p.y - a.y
                p.rbx, p.rby = p.x - b.x, p.y - b.y
                rna = p.rax * ny - p.ray * nx
                rnb = p.rbx * ny - p.rby * nx
                kn = a.inv_m + b.inv_m + a.inv_i * rna * rna + b.inv_i * rnb * rnb
                p.nm = 1.0 / kn if kn > 0.0 else 0.0
                rta = p.rax * ty - p.ray * tx
                rtb = p.rbx * ty - p.rby * tx
                kt = a.inv_m + b.inv_m + a.inv_i * rta * rta + b.inv_i * rtb * rtb
                p.tm = 1.0 / kt if kt > 0.0 else 0.0
                dvx = b.vx - b.w * p.rby - a.vx + a.w * p.ray
                dvy = b.vy + b.w * p.rbx - a.vy - a.w * p.rax
                vn = dvx * nx + dvy * ny
                p.vn0 = vn
                p.vb = -c.restitution * vn if (vn < -REST_THRESHOLD and c.restitution > 0.0) else 0.0
                p.tgt = min(MAX_BIAS, BAUMGARTE / h * max(p.pen - SLOP, 0.0))
                if old:
                    bd = 36.0
                    for ox, oy, jn, jt in old:
                        d = (ox - p.x) ** 2 + (oy - p.y) ** 2
                        if d < bd:
                            bd = d
                            p.jn, p.jt = jn, jt
                px = p.jn * nx + p.jt * tx
                py = p.jn * ny + p.jt * ty
                a.vx -= a.inv_m * px
                a.vy -= a.inv_m * py
                a.w -= a.inv_i * (p.rax * py - p.ray * px)
                b.vx += b.inv_m * px
                b.vy += b.inv_m * py
                b.w += b.inv_i * (p.rbx * py - p.rby * px)
        for _ in range(max(1, min(30, int(self.vel_iters)))):
            for j in joints:
                j.solve(h)
            for c in contacts:
                a, b = c.ba, c.bb
                nx, ny = c.nx, c.ny
                tx, ty = ny, -nx
                mu = c.friction
                for p in c.pts:
                    dvx = b.vx - b.w * p.rby - a.vx + a.w * p.ray
                    dvy = b.vy + b.w * p.rbx - a.vy - a.w * p.rax
                    lam = -p.tm * (dvx * tx + dvy * ty)
                    mx = mu * p.jn
                    nt = max(-mx, min(mx, p.jt + lam))
                    lam = nt - p.jt
                    p.jt = nt
                    px, py = lam * tx, lam * ty
                    a.vx -= a.inv_m * px
                    a.vy -= a.inv_m * py
                    a.w -= a.inv_i * (p.rax * py - p.ray * px)
                    b.vx += b.inv_m * px
                    b.vy += b.inv_m * py
                    b.w += b.inv_i * (p.rbx * py - p.rby * px)
                for p in c.pts:
                    dvx = b.vx - b.w * p.rby - a.vx + a.w * p.ray
                    dvy = b.vy + b.w * p.rbx - a.vy - a.w * p.rax
                    vn = dvx * nx + dvy * ny
                    lam = p.nm * (-vn + p.vb)
                    nn = max(p.jn + lam, 0.0)
                    lam = nn - p.jn
                    p.jn = nn
                    px, py = lam * nx, lam * ny
                    a.vx -= a.inv_m * px
                    a.vy -= a.inv_m * py
                    a.w -= a.inv_i * (p.rax * py - p.ray * px)
                    b.vx += b.inv_m * px
                    b.vy += b.inv_m * py
                    b.w += b.inv_i * (p.rbx * py - p.rby * px)
        for _ in range(max(0, min(20, int(self.pos_iters)))):
            for c in contacts:
                a, b = c.ba, c.bb
                nx, ny = c.nx, c.ny
                for p in c.pts:
                    if p.tgt <= 0.0 and p.jb <= 0.0:
                        continue
                    dvx = (b.bvx - b.bw * p.rby) - (a.bvx - a.bw * p.ray)
                    dvy = (b.bvy + b.bw * p.rbx) - (a.bvy + a.bw * p.rax)
                    vn = dvx * nx + dvy * ny
                    lam = p.nm * (p.tgt - vn)
                    nb = max(p.jb + lam, 0.0)
                    lam = nb - p.jb
                    p.jb = nb
                    px, py = lam * nx, lam * ny
                    a.bvx -= a.inv_m * px
                    a.bvy -= a.inv_m * py
                    a.bw -= a.inv_i * (p.rax * py - p.ray * px)
                    b.bvx += b.inv_m * px
                    b.bvy += b.inv_m * py
                    b.bw += b.inv_i * (p.rbx * py - p.rby * px)
        for c in contacts:
            newm[(c.sa.id, c.sb.id)] = [(p.x, p.y, p.jn, p.jt) for p in c.pts]
        self.prev_manifolds = newm

    @staticmethod
    def _record(c, acc):
        a, b = c.ba, c.bb
        nx, ny = c.nx, c.ny
        if a.uid > b.uid:
            a, b = b, a
            nx, ny = -nx, -ny
        key = (a.uid, b.uid)
        imp = sum(p.jn for p in c.pts)
        info = acc.get(key)
        if info is not None and info.imp > imp:
            return
        deep = max(c.pts, key=lambda q: q.pen)
        if info is None:
            info = PairInfo()
            acc[key] = info
        info.ba, info.bb = a, b
        info.nx, info.ny = nx, ny
        info.px, info.py = deep.x, deep.y
        info.pen = deep.pen
        info.imp = imp
        info.speed = max(0.0, max(-p.vn0 for p in c.pts))

    def _dispatch(self, cur, prev, prefix):
        rt = self.physics.runtime
        for key, info in list(cur.items()):
            kind = "Stay" if key in prev else "Enter"
            self._fire(rt, prefix, kind, info, key)
        for key, info in list(prev.items()):
            if key not in cur:
                self._fire(rt, prefix, "Exit", info, key)

    def _fire(self, rt, prefix, kind, info, key):
        if prefix == "Trigger":
            ba, bb = info
            sides = ((ba, bb), (bb, ba))
        else:
            sides = ((info.ba, info.bb), (info.bb, info.ba))
        for idx, (me, other) in enumerate(sides):
            mo, oo = me.obj, other.obj
            if mo is None or oo is None or not mo.alive or not oo.alive:
                continue
            names = ["On" + prefix + kind]
            if prefix == "Collision" and kind == "Enter":
                names.append("OnCollide")
            for name in names:
                cb = find_callback(mo, name)
                if cb is None:
                    continue
                if prefix == "Trigger":
                    rt.call(cb, owner_of(mo), owner_of(oo))
                else:
                    nx, ny = info.nx, info.ny
                    if idx == 0:
                        nx, ny = -nx, -ny
                    t = LuaTable()
                    t.set("Point", vec_table(info.px, info.py))
                    t.set("Normal", vec_table(nx, ny))
                    t.set("Impulse", float(info.imp))
                    t.set("Penetration", float(info.pen))
                    t.set("Speed", float(info.speed))
                    rt.call(cb, owner_of(mo), owner_of(oo), t)

    def _build_debug(self, bodies, joints, contacts):
        d = self.debug
        data = {"shapes": [], "com": [], "vel": [], "contacts": [], "joints": []}
        for b in bodies:
            if "Colliders" in d:
                for s in b.shapes:
                    if s.kind == "poly":
                        data["shapes"].append(("poly", list(s.wv), b.kind, s.sensor))
                    else:
                        data["shapes"].append(("circle", s.wc, s.r, b.kind, s.sensor))
            if b.kind == "dynamic":
                if "Mass" in d:
                    data["com"].append((b.x, b.y))
                if "Velocity" in d:
                    data["vel"].append((b.x, b.y, b.x + b.vx * 0.15, b.y + b.vy * 0.15))
        if "Contacts" in d or "Normals" in d:
            for c in contacts:
                for p in c.pts:
                    data["contacts"].append((p.x, p.y, c.nx, c.ny))
        if "Joints" in d:
            for j in joints:
                data["joints"].append((j.a.x + j.rax, j.a.y + j.ray, j.b.x + j.rbx, j.b.y + j.rby))
        data["flags"] = dict(d)
        self.debug_data = data


class DebugSwitch(object):
    def __init__(self, world):
        self.world = world

    def lua_call(self, args):
        self.world.set_debug(args[0] if args else True)
        return []


class WorldAPI(object):
    def __init__(self, physics):
        self.physics = physics

    def lua_index(self, key):
        k = str(key)
        rw = self.physics.rigid
        if k == "Gravity":
            g = self.physics.gravity
            return vec_table(g[0], g[1], g[2])
        if k == "TimeScale":
            return rw.time_scale
        if k == "VelocityIterations":
            return float(rw.vel_iters)
        if k == "PositionIterations":
            return float(rw.pos_iters)
        if k == "Enabled":
            return rw.enabled
        if k == "Paused":
            return rw.paused
        if k == "Debug":
            return rw.debug is not None
        if k == "BodyCount":
            return float(len(rw.bodies))
        return getattr(self, "m_" + k, None)

    def lua_newindex(self, key, value):
        k = str(key)
        rw = self.physics.rigid
        if k == "Gravity":
            gx, gy, gz = to_vec(value, self.physics.gravity)
            self.physics.set_gravity(gx, gy, gz)
        elif k == "TimeScale":
            rw.time_scale = max(0.0, _num(value, 1.0))
        elif k == "VelocityIterations":
            rw.vel_iters = max(1, min(30, int(_num(value, 8))))
        elif k == "PositionIterations":
            rw.pos_iters = max(0, min(20, int(_num(value, 3))))
        elif k == "Enabled":
            rw.enabled = truthy(value)
        elif k == "Debug":
            rw.set_debug(value if isinstance(value, LuaTable) else truthy(value))

    def m_Pause(self, *_a):
        self.physics.rigid.paused = True

    def m_Resume(self, *_a):
        self.physics.rigid.paused = False

    def m_Step(self, _self=None, dt=None):
        self.physics.rigid.manual_step(FIXED_DT if dt is None else dt)


class JointFactory(object):
    NAMES = {"distance": "distance", "spring": "spring", "revolute": "revolute",
             "hinge": "revolute", "pin": "revolute", "fixed": "fixed", "weld": "fixed"}

    def __init__(self, physics):
        self.physics = physics

    def lua_index(self, key):
        kind = self.NAMES.get(str(key).lower())
        if kind is None:
            return None
        return lambda spec=None: self.physics.rigid.create_joint(kind, spec)


class PhysicsAPI(object):
    def __init__(self, runtime):
        self.runtime = runtime
        self.physics = runtime.physics
        self.world = WorldAPI(self.physics)
        self.joint = JointFactory(self.physics)
        self.debug_switch = DebugSwitch(self.physics.rigid)
        self.extra = {}

    def _gravity(self, x=0, y=900, z=0):
        if isinstance(x, LuaTable):
            gx, gy, gz = to_vec(x, self.physics.gravity)
            self.physics.set_gravity(gx, gy, gz)
        else:
            self.physics.set_gravity(x, y, z)

    def _raycast(self, x1=0, y1=0, x2=0, y2=0):
        hit = self.physics.raycast(float(x1 or 0), float(y1 or 0), float(x2 or 0), float(y2 or 0))
        if hit is None:
            return [None]
        obj, hx, hy = hit
        return [obj, vec_table(hx, hy)]

    def _time_scale(self, v=None):
        rw = self.physics.rigid
        if v is None:
            return rw.time_scale
        rw.time_scale = max(0.0, _num(v, 1.0))

    def _enabled(self, v=None):
        rw = self.physics.rigid
        if v is None:
            return rw.enabled
        rw.enabled = truthy(v)

    def lua_index(self, key):
        k = str(key)
        if k in ("gravity", "setGravity"):
            return self._gravity
        if k == "getGravity":
            return lambda *a: vec_table(*self.physics.get_gravity())
        if k == "raycast":
            return self._raycast
        if k in ("timeScale", "setTimeScale"):
            return self._time_scale
        if k in ("enabled", "setEnabled"):
            return self._enabled
        if k == "world":
            return self.world
        if k == "material":
            return self.physics.rigid.materials
        if k == "joint":
            return self.joint
        if k == "debug":
            return self.debug_switch
        return self.extra.get(k)

    def lua_newindex(self, key, value):
        k = str(key)
        if k == "debug":
            self.physics.rigid.set_debug(value if isinstance(value, LuaTable) else truthy(value))
        elif k == "gravity" and isinstance(value, LuaTable):
            self._gravity(value)
        elif k == "world":
            raise LuaError("physics.world e somente leitura")
        else:
            if value is None:
                self.extra.pop(k, None)
            else:
                self.extra[k] = value


def body_for(obj):
    b = getattr(obj, "_rb", None)
    if b is None:
        b = Body(obj)
        obj._rb = b
    return b


def _ready(obj):
    kind = body_kind(obj)
    if kind is None or not truthy(obj.props.get("Physics")):
        return None
    b = body_for(obj)
    b.refresh(kind)
    return b


def add_collider(obj, spec):
    world = obj.scene.runtime.physics.rigid
    col = Collider(spec, world.materials)
    lst = getattr(obj, "_colliders", None)
    if lst is None:
        lst = []
        obj._colliders = lst
    lst.append(col)
    if not obj.props.get("BodyType"):
        obj.set_prop("Physics", True)
        obj.set_prop("BodyType", "static")
    return col


def clear_colliders(obj):
    obj._colliders = []
    obj.scene.dirty = True


def enable_physics(obj, opts, default_type=None):
    bt = None
    rest = []
    cols = []
    if isinstance(opts, LuaTable):
        for k, v in opts.items():
            if not isinstance(k, str):
                continue
            if k in ("Type", "BodyType"):
                bt = normalize_type(v)
            elif k == "Collider":
                cols.append(v)
            elif k == "Colliders":
                if isinstance(v, LuaTable):
                    cols.extend(v.ipairs_list())
            else:
                rest.append((k, v))
    obj.set_prop("Physics", True)
    if bt is None:
        bt = default_type
    if bt is not None:
        keys = [k for k, _ in rest]
        if "Friction" not in keys and "Friction" not in obj._explicit_keys:
            obj.props["Friction"] = 0.5
        if ("Restitution" not in keys and "Bounce" not in keys
                and "Bounce" not in obj._explicit_keys):
            obj.props["Bounce"] = 0.2 if bt == "dynamic" else 0.0
        obj.set_prop("BodyType", bt)
    for k, v in rest:
        obj.set_prop(k, v)
    for spec in cols:
        add_collider(obj, spec)
    return obj


def apply_force(obj, fx, fy, px=None, py=None):
    b = _ready(obj)
    if b is None or b.kind != "dynamic":
        return
    b.fx += fx
    b.fy += fy
    if px is not None and py is not None:
        b.tq += (px - b.x) * fy - (py - b.y) * fx


def apply_impulse(obj, ix, iy, px=None, py=None):
    b = _ready(obj)
    if b is None or b.kind != "dynamic":
        return
    b.vx += ix * b.inv_m
    b.vy += iy * b.inv_m
    if px is not None and py is not None:
        b.w += b.inv_i * ((px - b.x) * iy - (py - b.y) * ix)
    b.write_velocity()


def apply_torque(obj, t):
    b = _ready(obj)
    if b is None or b.kind != "dynamic":
        return
    b.tq += t


def apply_angular_impulse(obj, i):
    b = _ready(obj)
    if b is None or b.kind != "dynamic":
        return
    b.w += b.inv_i * i
    b.write_velocity()


def mass_of(obj):
    b = _ready(obj)
    return b.mass if b is not None and b.kind == "dynamic" else 0.0


def inertia_of(obj):
    b = _ready(obj)
    if b is None or b.kind != "dynamic" or b.inv_i <= 0.0:
        return 0.0
    return 1.0 / b.inv_i


def center_of_mass(obj):
    b = _ready(obj)
    if b is None:
        x, y, _ = obj.pos()
        w, h, _ = obj.eff_size()
        return x + w / 2.0, y + h / 2.0
    return b.x, b.y
