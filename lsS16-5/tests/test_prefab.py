import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from luastudio.runtime import Runtime

ENEMY = '''
return {
    Objects = {
        { Class = "image", Name = "Body", Source = "Assets/enemy.png",
          Position = {0, 0}, Size = {64, 64} },
        { Class = "label", Name = "Name", Text = "Enemy", Position = {10, -20} },
    },
    Script = "Enemy_logic.lua",
}
'''
LOGIC = '''
self.Hp = 3
self.Name2 = self.Body.Name
'''
MAIN = '''
local a = scene.instantiate("Enemy", { Position = {400, 300}, Scale = {2, 2}, Speed = 7 })
local b = Instance.Enemy{ Position = {500, 200} }
scene.instantiate("Enemy", { Position = {700, 200} })
local corpo = Instance.Enemy.Body{ Position = {5, 5} }
A, B, CORPO = a, b, corpo
'''


def run(main, extra=None):
    rt = Runtime()
    scripts = {"main.lua": main, "Enemy.lua": ENEMY, "Enemy_logic.lua": LOGIC}
    scripts.update(extra or {})
    assert rt.run_project(scripts, "main.lua"), rt.last_error
    return rt


class PrefabTest(unittest.TestCase):
    def test_instantiate(self):
        rt = run(MAIN)
        a = rt.interp.get_global("A")
        self.assertEqual(a.lua_index("Position").get("x"), 400.0)
        body = a.lua_index("Body")
        self.assertEqual(body.pos()[:2], (400.0, 300.0))
        self.assertEqual(body.scale()[:2], (2.0, 2.0))
        lbl = a.lua_index("Name")
        self.assertEqual(lbl.pos()[:2], (420.0, 260.0))
        self.assertEqual(a.lua_index("Speed"), 7.0)
        self.assertEqual(a.lua_index("Hp"), 3.0)           # veio do Script
        self.assertEqual(len(rt.prefabs.live), 3)

    def test_move_and_destroy(self):
        rt = run(MAIN)
        b = rt.interp.get_global("B")
        b.lua_newindex("Position", rt.interp.get_global("A").lua_index("Position"))
        self.assertEqual(b.lua_index("Body").pos()[:2], (400.0, 300.0))
        n = len(rt.scene.objects)
        b.m_Destroy()
        self.assertEqual(len(rt.scene.objects), n - 2)
        self.assertFalse(b.lua_index("Alive"))

    def test_single_object(self):
        rt = run(MAIN)
        c = rt.interp.get_global("CORPO")
        self.assertEqual(c.cls, "image")
        self.assertEqual(c.pos()[:2], (5.0, 5.0))

    def test_unique_names(self):
        rt = run(MAIN)
        names = [o.name for o in rt.scene.objects]
        self.assertEqual(len(names), len(set(names)))

    def test_missing_scene(self):
        rt = Runtime()
        ok = rt.run_project({"main.lua": 'scene.instantiate("Nada")'}, "main.lua")
        self.assertFalse(ok)
        self.assertIn("nao encontrada", rt.last_error["message"])

    def test_script_in_lua_syntax(self):
        # script que registra update usando `self`
        rt = run('local e = scene.instantiate("Enemy")\nE = e',
                 {"Enemy_logic.lua": 'onUpdate(function(dt) self.Body:Move(10 * dt, 0) end)'})
        e = rt.interp.get_global("E")
        x0 = e.lua_index("Body").pos()[0]
        rt.running = True
        rt.update(0.1)
        self.assertAlmostEqual(e.lua_index("Body").pos()[0], x0 + 1.0, places=3)


if __name__ == "__main__":
    unittest.main()
