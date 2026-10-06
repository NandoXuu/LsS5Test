import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from luastudio.runtime import Runtime

DT = 1.0 / 60.0


def boot(script, extra=None):
    logs = []
    rt = Runtime(log=logs.append)
    ok = rt.run_project(dict({"main.lua": script}, **(extra or {})), "main.lua") if extra else rt.run_source(script)
    assert ok, "script falhou: %s %s" % (logs, rt.last_error)
    rt.running = True
    rt.logs = logs
    return rt


def run(rt, seconds):
    for _ in range(int(round(seconds / DT))):
        rt.update(DT)


def g(rt, name):
    return rt.interp.get_global(name)


def vec(t):
    return t.get("x"), t.get("y")


FLOOR = '''
Floor = create.frame.Floor{ Position = {-2000, 500}, Size = {4000, 50} }
Floor:EnablePhysics{ Type = "static" }
'''


class RigidBodyTest(unittest.TestCase):
    def test_rest_on_floor(self):
        rt = boot(FLOOR + '''
Box = create.frame.Box{ Position = {300, 100}, Size = {50, 50} }
Box:EnablePhysics{ Type = "dynamic", Mass = 2, Restitution = 0 }
Hits = 0
Box.OnCollisionEnter = function(self, other, contact)
  Hits = Hits + 1
  N = contact.Normal.y
  Imp = contact.Impulse
  Other = other.Name
end
''')
        run(rt, 3)
        b = g(rt, "Box")
        self.assertAlmostEqual(b.pos()[1], 450.0, delta=0.6)
        self.assertAlmostEqual(b.pos()[0], 300.0, delta=0.2)
        self.assertAlmostEqual(b.rot(), 0.0, delta=0.05)
        self.assertEqual(g(rt, "Hits"), 1.0)
        self.assertEqual(g(rt, "N"), -1.0)
        self.assertEqual(g(rt, "Other"), "Floor")
        self.assertGreater(g(rt, "Imp"), 1000.0)
        self.assertAlmostEqual(vec(b.lua_index("LinearVelocity"))[1], 0.0, delta=1.0)

    def test_restitution(self):
        rt = boot(FLOOR + '''
Ball = create.frame.Ball{ Position = {0, 100}, Size = {40, 40} }
Ball:EnablePhysics{ Type = "dynamic", Restitution = 0.8 }
Ball:AddCollider{ Shape = "circle" }
''')
        ball = g(rt, "Ball")
        peak = None
        bounced = False
        for _ in range(300):
            rt.update(DT)
            vy = vec(ball.lua_index("LinearVelocity"))[1]
            if vy < -50:
                bounced = True
            if bounced and vy >= 0 and peak is None:
                peak = ball.pos()[1]
        drop = 460.0 - 100.0
        rise = 460.0 - peak
        self.assertAlmostEqual(rise / drop, 0.64, delta=0.08)

    def test_torque_and_inertia(self):
        rt = boot('''
Bar = create.frame.Bar{ Position = {100, 100}, Size = {100, 40} }
Bar:EnablePhysics{ Type = "dynamic", Mass = 3, UseGravity = false }
I = Bar:GetInertia()
M = Bar:GetMass()
app.onUpdate(function(dt) Bar:ApplyTorque(50000) end)
''')
        run(rt, 1.0)
        bar = g(rt, "Bar")
        inertia = 3.0 * (100.0 ** 2 + 40.0 ** 2) / 12.0
        self.assertAlmostEqual(g(rt, "I"), inertia, delta=1.0)
        self.assertEqual(g(rt, "M"), 3.0)
        expected = math.degrees(50000.0 / inertia * 1.0)
        self.assertAlmostEqual(bar.lua_index("AngularVelocity"), expected, delta=expected * 0.03)
        self.assertGreater(bar.rot(), 0.0)

    def test_offcenter_impulse(self):
        rt = boot('''
Bar = create.frame.Bar{ Position = {100, 100}, Size = {100, 40} }
Bar:EnablePhysics{ Type = "dynamic", Mass = 2, UseGravity = false }
Bar:ApplyImpulse(0, -100, 200, 120)
''')
        run(rt, DT)
        bar = g(rt, "Bar")
        vx, vy = vec(bar.lua_index("LinearVelocity"))
        inertia = 2.0 * (100.0 ** 2 + 40.0 ** 2) / 12.0
        self.assertAlmostEqual(vy, -50.0, delta=0.01)
        self.assertAlmostEqual(math.radians(bar.lua_index("AngularVelocity")),
                               (50.0 * -100.0) / inertia, delta=1e-6)

    def test_friction_deceleration(self):
        rt = boot(FLOOR + '''
Box = create.frame.Box{ Position = {0, 450}, Size = {50, 50} }
Box:EnablePhysics{ Type = "dynamic", Restitution = 0, Friction = 0.5 }
Box.LinearVelocity = {300, 0}
''')
        run(rt, 0.3)
        vx = vec(g(rt, "Box").lua_index("LinearVelocity"))[0]
        self.assertAlmostEqual(vx, 300.0 - 0.5 * 900.0 * 0.3, delta=12.0)
        run(rt, 1.0)
        vx = vec(g(rt, "Box").lua_index("LinearVelocity"))[0]
        self.assertAlmostEqual(vx, 0.0, delta=1.0)

    def test_stack_is_stable(self):
        boxes = "\n".join(
            'B%d = create.frame.B%d{ Position = {300, %d}, Size = {50, 50} }\n'
            'B%d:EnablePhysics{ Type = "dynamic", Restitution = 0 }' % (i, i, 450 - i * 50, i)
            for i in range(5))
        rt = boot(FLOOR + boxes)
        run(rt, 4)
        for i in range(5):
            b = g(rt, "B%d" % i)
            self.assertAlmostEqual(b.pos()[0], 300.0, delta=1.5)
            self.assertAlmostEqual(b.pos()[1], 450.0 - i * 50, delta=3.0 + i)
            self.assertLess(abs(b.rot()), 1.0)

    def test_circle_rolls_down_ramp(self):
        rt = boot('''
Ramp = create.frame.Ramp{ Position = {0, 300}, Size = {600, 20}, Rotation = 20 }
Ramp:EnablePhysics{ Type = "static" }
Ball = create.frame.Ball{ Position = {40, 180}, Size = {30, 30} }
Ball:EnablePhysics{ Type = "dynamic", Friction = 0.8, Restitution = 0 }
Ball:AddCollider{ Shape = "circle" }
''')
        run(rt, 1.5)
        ball = g(rt, "Ball")
        vx, vy = vec(ball.lua_index("LinearVelocity"))
        speed = math.hypot(vx, vy)
        spin = math.radians(abs(ball.lua_index("AngularVelocity")))
        self.assertGreater(speed, 150.0)
        self.assertAlmostEqual(speed, spin * 15.0, delta=speed * 0.15)
        self.assertGreater(ball.pos()[0], 140.0)

    def test_events_enter_stay_exit(self):
        rt = boot(FLOOR + '''
Box = create.frame.Box{ Position = {0, 440}, Size = {50, 50} }
Box:EnablePhysics{ Type = "dynamic", Restitution = 0 }
E, S, X = 0, 0, 0
Box.OnCollisionEnter = function(self, other, c) E = E + 1 end
Box.OnCollisionStay = function(self, other, c) S = S + 1 end
Box.OnCollisionExit = function(self, other, c) X = X + 1 end
''')
        run(rt, 1.0)
        self.assertEqual(g(rt, "E"), 1.0)
        self.assertGreater(g(rt, "S"), 20.0)
        self.assertEqual(g(rt, "X"), 0.0)
        g(rt, "Box").m_SetLinearVelocity(None, 0, -400)
        run(rt, 0.3)
        self.assertEqual(g(rt, "X"), 1.0)

    def test_layers_and_masks(self):
        rt = boot(FLOOR + '''
Ghost = create.frame.Ghost{ Position = {100, 100}, Size = {40, 40} }
Ghost:EnablePhysics{ Type = "dynamic", CollisionLayer = 2, CollisionMask = 4 }
Solid = create.frame.Solid{ Position = {300, 100}, Size = {40, 40} }
Solid:EnablePhysics{ Type = "dynamic", CollisionLayer = 1, CollisionMask = 65535 }
''')
        run(rt, 2.0)
        self.assertGreater(g(rt, "Ghost").pos()[1], 700.0)
        self.assertAlmostEqual(g(rt, "Solid").pos()[1], 460.0, delta=1.0)

    def test_kinematic_platform_carries_box(self):
        rt = boot(FLOOR + '''
Plat = create.frame.Plat{ Position = {0, 400}, Size = {300, 20} }
Plat:EnablePhysics{ Type = "kinematic" }
Plat.LinearVelocity = {80, 0}
Box = create.frame.Box{ Position = {100, 350}, Size = {40, 40} }
Box:EnablePhysics{ Type = "dynamic", Restitution = 0, Friction = 0.9 }
''')
        run(rt, 2.0)
        plat, box = g(rt, "Plat"), g(rt, "Box")
        self.assertAlmostEqual(plat.pos()[0], 160.0, delta=1.0)
        self.assertAlmostEqual(plat.pos()[1], 400.0, delta=0.01)
        self.assertAlmostEqual(box.pos()[0], 100.0 + 160.0, delta=25.0)
        self.assertAlmostEqual(box.pos()[1], 360.0, delta=1.5)

    def test_kinematic_moved_by_code_pushes(self):
        rt = boot(FLOOR + '''
Player = create.frame.Player{ Position = {0, 450}, Size = {40, 50} }
Player:EnablePhysics{ Type = "kinematic" }
Crate = create.frame.Crate{ Position = {100, 450}, Size = {50, 50} }
Crate:EnablePhysics{ Type = "dynamic", Restitution = 0, Friction = 0.1 }
app.onUpdate(function(dt) Player:Move(120 * dt, 0) end)
''')
        run(rt, 2.0)
        player, crate = g(rt, "Player"), g(rt, "Crate")
        self.assertAlmostEqual(player.pos()[0], 240.0, delta=2.0)
        self.assertGreater(crate.pos()[0], 100.0 + 50.0)
        self.assertGreaterEqual(crate.pos()[0], player.pos()[0] + 40.0 - 3.5)

    def test_pendulum_keeps_length(self):
        rt = boot('''
Bob = create.frame.Bob{ Position = {380, 200}, Size = {20, 20} }
Bob:EnablePhysics{ Type = "dynamic", Mass = 1 }
Bob:AddCollider{ Shape = "circle" }
J = physics.joint.Revolute{ A = Bob, Anchor = {200, 100} }
''')
        bob = g(rt, "Bob")
        for _ in range(240):
            rt.update(DT)
            cx = bob.pos()[0] + 10.0
            cy = bob.pos()[1] + 10.0
            d = math.hypot(cx - 200.0, cy - 100.0)
            self.assertAlmostEqual(d, math.hypot(190.0 + 0.0, 110.0), delta=2.5)
        self.assertLess(bob.pos()[0], 380.0)

    def test_distance_joint(self):
        rt = boot('''
Anchor = create.frame.Anchor{ Position = {300, 100}, Size = {20, 20} }
Anchor:EnablePhysics{ Type = "static" }
Weight = create.frame.Weight{ Position = {300, 300}, Size = {20, 20} }
Weight:EnablePhysics{ Type = "dynamic" }
J = physics.joint.Distance{ A = Anchor, B = Weight, Length = 150 }
''')
        run(rt, 3.0)
        w = g(rt, "Weight")
        self.assertAlmostEqual(w.pos()[1] - 100.0, 150.0, delta=3.0)

    def test_spring_joint_oscillates(self):
        rt = boot('''
Anchor = create.frame.Anchor{ Position = {300, 100}, Size = {20, 20} }
Anchor:EnablePhysics{ Type = "static" }
Weight = create.frame.Weight{ Position = {300, 400}, Size = {20, 20} }
Weight:EnablePhysics{ Type = "dynamic" }
J = physics.joint.Spring{ A = Anchor, B = Weight, Length = 100, Frequency = 2, DampingRatio = 0.1 }
''')
        ys = []
        weight = g(rt, "Weight")
        for _ in range(180):
            rt.update(DT)
            ys.append(weight.pos()[1])
        self.assertLess(min(ys), 300.0)
        self.assertGreater(max(ys[60:]), min(ys[60:]) + 20.0)

    def test_polygon_capsule_and_concave(self):
        rt = boot(FLOOR + '''
Cap = create.frame.Cap{ Position = {100, 300}, Size = {30, 80} }
Cap:EnablePhysics{ Type = "dynamic", Restitution = 0 }
Cap:AddCollider{ Shape = "capsule" }
Tri = create.frame.Tri{ Position = {300, 300}, Size = {40, 40} }
Tri:EnablePhysics{ Type = "dynamic", Restitution = 0 }
Tri:AddCollider{ Shape = "polygon", Points = { {-20, 20}, {20, 20}, {0, -20} } }
Cup = create.frame.Cup{ Position = {500, 380}, Size = {120, 100} }
Cup:EnablePhysics{ Type = "static" }
Cup:AddCollider{ Shape = "mesh", Points = {
  {-60,-50}, {-40,-50}, {-40,30}, {40,30}, {40,-50}, {60,-50}, {60,50}, {-60,50} } }
Ball = create.frame.Ball{ Position = {540, 200}, Size = {30, 30} }
Ball:EnablePhysics{ Type = "dynamic", Restitution = 0 }
Ball:AddCollider{ Shape = "circle" }
''')
        run(rt, 4.0)
        cap, tri, ball = g(rt, "Cap"), g(rt, "Tri"), g(rt, "Ball")
        self.assertAlmostEqual(cap.pos()[1] + 80.0, 500.0, delta=1.0)
        self.assertAlmostEqual(tri.pos()[1] + 40.0, 500.0, delta=1.5)
        self.assertAlmostEqual(ball.pos()[1] + 15.0, 445.0, delta=2.0)
        self.assertAlmostEqual(ball.pos()[0] + 15.0, 560.0, delta=45.0)

    def test_sensor_trigger(self):
        rt = boot(FLOOR + '''
Zone = create.frame.Zone{ Position = {100, 400}, Size = {100, 100} }
Zone:EnablePhysics{ Type = "static" }
Zone:AddCollider{ Shape = "box", IsSensor = true }
Box = create.frame.Box{ Position = {130, 100}, Size = {40, 40} }
Box:EnablePhysics{ Type = "dynamic", Restitution = 0 }
In, Out = 0, 0
Zone.OnTriggerEnter = function(self, other) In = In + 1; WHO = other.Name end
Zone.OnTriggerExit = function(self, other) Out = Out + 1 end
''')
        run(rt, 3.0)
        self.assertEqual(g(rt, "In"), 1.0)
        self.assertEqual(g(rt, "WHO"), "Box")
        self.assertAlmostEqual(g(rt, "Box").pos()[1], 460.0, delta=1.0)
        g(rt, "Box").m_SetLinearVelocity(None, 0, -900)
        run(rt, 1.0)
        self.assertEqual(g(rt, "Out"), 1.0)

    def test_world_api(self):
        rt = boot('''
physics.world.Gravity = {0, 0}
physics.world.TimeScale = 1
Box = create.frame.Box{ Position = {0, 0}, Size = {10, 10} }
Box:EnablePhysics{ Type = "dynamic" }
GX = physics.world.Gravity.x
GY = physics.world.Gravity.y
''')
        self.assertEqual(g(rt, "GY"), 0.0)
        run(rt, 0.5)
        self.assertEqual(g(rt, "Box").pos()[1], 0.0)
        rt.interp.execute("physics.world.Gravity = {0, 1000}; physics.world:Pause()", "t")
        run(rt, 0.5)
        self.assertEqual(g(rt, "Box").pos()[1], 0.0)
        rt.interp.execute("physics.world:Resume()", "t")
        run(rt, 0.5)
        self.assertGreater(g(rt, "Box").pos()[1], 50.0)
        y = g(rt, "Box").pos()[1]
        rt.interp.execute("physics.world:Pause(); physics.world:Step(1/60)", "t")
        self.assertGreater(g(rt, "Box").pos()[1], y)
        rt.interp.execute("physics.world.TimeScale = 0", "t")
        rt.interp.execute("physics.world:Resume()", "t")
        y = g(rt, "Box").pos()[1]
        run(rt, 0.5)
        self.assertEqual(g(rt, "Box").pos()[1], y)

    def test_materials(self):
        rt = boot(FLOOR + '''
physics.material.Slick{ Friction = 0.01, Restitution = 0 }
A = create.frame.A{ Position = {0, 450}, Size = {50, 50} }
A:EnablePhysics{ Type = "dynamic" }
A:AddCollider{ Shape = "box", Material = physics.material.Ice }
B = create.frame.B{ Position = {0, 450}, Size = {50, 50} }
B:EnablePhysics{ Type = "dynamic" }
B:AddCollider{ Shape = "box", Material = physics.material.Sand }
A.LinearVelocity = {200, 0}
B.LinearVelocity = {200, 0}
A.CollisionLayer = 2
A.CollisionMask = 1
B.CollisionLayer = 4
B.CollisionMask = 1
R = physics.material.Rubber.Restitution
''')
        run(rt, 0.5)
        self.assertGreater(g(rt, "A").pos()[0], g(rt, "B").pos()[0] + 20.0)
        self.assertAlmostEqual(g(rt, "R"), 0.85)

    def test_debug_data(self):
        rt = boot(FLOOR + '''
Box = create.frame.Box{ Position = {0, 300}, Size = {50, 50} }
Box:EnablePhysics{ Type = "dynamic" }
physics.debug = true
''')
        run(rt, 1.0)
        d = rt.physics.rigid.debug_data
        self.assertTrue(d["shapes"])
        self.assertTrue(d["contacts"])
        rt.interp.execute("physics.debug(false)", "t")
        self.assertIsNone(rt.physics.rigid.debug)
        rt.interp.execute("physics.debug({ Colliders = true })", "t")
        self.assertEqual(list(rt.physics.rigid.debug), ["Colliders"])

    def test_legacy_physics_still_works(self):
        rt = boot('''
physics.gravity(0, 900, 0)
Chao = create.frame.Chao{ Position = {0, 520}, Size = {360, 20} }
Chao:EnablePhysics{ Static = true }
Bola = create.frame.Bola{ Position = {60, 60}, Size = {40, 40} }
Bola:EnablePhysics{ Bounce = 0.6 }
Zona = create.frame.Zona{ Position = {40, 400}, Size = {90, 90} }
Zona:MakeArea(true)
Entrou = 0
Zona.OnAreaEnter = function(self, outro) Entrou = Entrou + 1 end
Bola:ApplyImpulse(0, -100, 0)
''')
        run(rt, 3.0)
        self.assertAlmostEqual(g(rt, "Bola").pos()[1], 480.0, delta=60.0)
        self.assertGreaterEqual(g(rt, "Entrou"), 1.0)
        self.assertEqual(g(rt, "Bola").props["BodyType"], "")


ENEMY = '''
return {
    Objects = {
        { Class = "frame", Name = "Body", Position = {0, 0}, Size = {64, 64}, Color = "red" },
        { Class = "label", Name = "Tag", Text = "E", Position = {0, -20} },
    },
    Physics = {
        BodyType = "dynamic",
        Mass = 5,
        Restitution = 0,
        Collider = { Shape = "box", Size = {40, 60}, Offset = {0, 2} },
    },
}
'''


class PrefabPhysicsTest(unittest.TestCase):
    def test_declarative_scene_physics(self):
        main = FLOOR + '''
Enemy = scene.instantiate("Enemy", { Position = {400, 100} })
Hits = 0
Enemy.OnCollisionEnter = function(self, other, contact)
  Hits = Hits + 1
  SELF = self
end
'''
        rt = boot(main, {"Enemy.lua": ENEMY})
        run(rt, 3.0)
        enemy = g(rt, "Enemy")
        body = enemy.lua_index("Body")
        tag = enemy.lua_index("Tag")
        self.assertAlmostEqual(body.pos()[1] + 64.0, 500.0, delta=1.0)
        self.assertAlmostEqual(tag.pos()[1], body.pos()[1] - 20.0, delta=0.5)
        self.assertEqual(g(rt, "Hits"), 1.0)
        self.assertIs(g(rt, "SELF"), enemy)
        self.assertAlmostEqual(enemy.lua_index("Position").get("y"), body.pos()[1], delta=0.01)
        self.assertEqual(enemy.lua_index("Mass"), 5.0)

    def test_add_rigidbody_on_instance(self):
        main = FLOOR + '''
Enemy = scene.instantiate("Enemy", { Position = {400, 100}, Scale = {2, 2}, Physics = {
  Type = "dynamic", Mass = 5, Restitution = 0 } })
Enemy:AddCollider{ Shape = "box", Size = {20, 20} }
'''
        rt = boot(main, {"Enemy.lua": ENEMY.replace("Physics", "Unused")})
        run(rt, 3.0)
        body = g(rt, "Enemy").lua_index("Body")
        self.assertAlmostEqual(body.pos()[1] + 64.0 * 2, 500.0, delta=2.0 + 64.0 * 2 - 20.0 * 2 + 40.0)


class FixedCamTest(unittest.TestCase):
    def test_fast_body_does_not_tunnel(self):
        rt = boot(FLOOR + '''
Bullet = create.frame.Bullet{ Position = {0, 200}, Size = {10, 10} }
Bullet:EnablePhysics{ Type = "dynamic", Restitution = 0 }
Bullet.LinearVelocity = {0, 6000}
''')
        run(rt, 1.0)
        self.assertLess(g(rt, "Bullet").pos()[1], 500.0)


if __name__ == "__main__":
    unittest.main()
