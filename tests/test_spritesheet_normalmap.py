# -*- coding: utf-8 -*-
"""Testes de sincronia Source <-> NormalMap em spritesheets (sem Kivy/GPU).

Rodar na raiz do projeto:  python -m unittest discover -s tests -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from luastudio import spritesheet as sh
from luastudio import normalmap2d as nm2d
from luastudio.runtime import Runtime


def make_rt(script):
    rt = Runtime()
    assert rt.run_source(script), "script falhou"
    return rt


def img(rt, name):
    return rt.scene.by_name[name]


def uvs_of(obj):
    """UVs que o renderer usa; o stage passa ESTE mesmo valor ao Source e ao NormalMap."""
    return sh.frame_uvs_from_props(obj.props)


def frame_cell(uvs, cols, rows):
    """(coluna, linha) do frame a partir dos UVs (linha 0 = topo da imagem)."""
    u0, v0, u1, _, _, v1, _, _ = uvs
    col = int(round(u0 * cols))
    row = int(round((1.0 - v1) * rows))
    return col, row


class PureHelpers(unittest.TestCase):
    def test_frame5_cols8_rows2(self):
        uvs = sh.frame_uvs(5, 8, 2)
        self.assertEqual(frame_cell(uvs, 8, 2), (5, 0))
        uvs = sh.frame_uvs(9, 8, 2)
        self.assertEqual(frame_cell(uvs, 8, 2), (1, 1))

    def test_wrap(self):
        self.assertEqual(sh.frame_index(8, 4, 2), 0)
        self.assertEqual(sh.frame_index(-1, 4, 2), 7)

    def test_not_a_sheet_returns_none(self):
        self.assertIsNone(sh.frame_uvs(0, 1, 1))
        self.assertIsNone(sh.frame_uvs_from_props({"Frame": 3.0}))


class SpriteTests(unittest.TestCase):
    # 1. sprite estatico + NormalMap (comportamento atual: sem recorte)
    def test_1_static_with_normalmap(self):
        rt = make_rt('create.image.Tijolo{Source="t.png", NormalMap="n.png", Lit=true}')
        o = img(rt, "Tijolo")
        self.assertEqual((o.props["Columns"], o.props["Rows"]), (1.0, 1.0))
        self.assertIsNone(uvs_of(o))
        rt.update(0.1)
        self.assertEqual(o.props["Frame"], 0.0)

    # 2. spritesheet + animacao sem NormalMap
    def test_2_animation_without_normalmap(self):
        rt = make_rt('create.image.Player{Source="p.png", Columns=8, Rows=1, FrameSpeed=10}')
        o = img(rt, "Player")
        self.assertEqual(o.props["NormalMap"], "")
        rt.update(0.1)
        self.assertEqual(int(o.props["Frame"]), 1)
        self.assertEqual(frame_cell(uvs_of(o), 8, 1), (1, 0))

    # 3. spritesheet + NormalMap animando: frame N do Source == frame N do Normal
    def test_3_animation_with_normalmap(self):
        rt = make_rt('''create.image.Player{Source="p.png", NormalMap="pn.png", Columns=8, Rows=1,
                        FrameSpeed=10, Playing=true, Lit=true}''')
        o = img(rt, "Player")
        seen = []
        for _ in range(8):
            seen.append(frame_cell(uvs_of(o), 8, 1)[0])
            rt.update(0.1)
        self.assertEqual(seen, [0, 1, 2, 3, 4, 5, 6, 7])
        self.assertEqual(frame_cell(uvs_of(o), 8, 1)[0], 0)  # volta ao 0

    # 4. GotoFrame
    def test_4_gotoframe(self):
        rt = make_rt('''local s = create.image.S{Source="p.png", NormalMap="pn.png", Columns=4, Rows=1}
                        s:GotoFrame(3)''')
        o = img(rt, "S")
        self.assertEqual(frame_cell(uvs_of(o), 4, 1), (3, 0))

    # 5. Frame alterado diretamente
    def test_5_direct_frame(self):
        rt = make_rt('''local s = create.image.S{Source="p.png", NormalMap="pn.png", Columns=4, Rows=1}
                        s.Frame = 2''')
        self.assertEqual(frame_cell(uvs_of(img(rt, "S")), 4, 1), (2, 0))

    # 8. Columns > 1 e Rows > 1
    def test_8_grid(self):
        rt = make_rt('''local s = create.image.S{Source="p.png", NormalMap="pn.png", Columns=4, Rows=2}
                        s:GotoFrame(6)''')
        self.assertEqual(frame_cell(uvs_of(img(rt, "S")), 4, 2), (2, 1))

    def test_loop_false_stops_on_last_frame(self):
        rt = make_rt('''create.image.S{Source="p.png", NormalMap="pn.png", Columns=4, Rows=1,
                        FrameSpeed=100, Loop=false}''')
        o = img(rt, "S")
        rt.update(0.1)
        rt.update(0.1)
        self.assertEqual(frame_cell(uvs_of(o), 4, 1)[0], 3)
        self.assertFalse(o.props["Playing"])


class FlipTests(unittest.TestCase):
    # 6. FlipX: espelha o sprite (matriz) e a luz no espaco local; canal Y da normal intacto
    def test_6_flipx(self):
        rt = make_rt('create.image.S{Source="p.png", NormalMap="pn.png", Columns=4, Rows=1, FlipX=true}')
        o = img(rt, "S")
        asx, asy, _ = o.axis_scale()
        self.assertTrue(asx < 0 and asy > 0)
        self.assertEqual(nm2d.material_uniforms(o.props)["flip_y"], 1.0)
        self.assertEqual(nm2d.to_local(10, 5, 0, True, False), (-10, 5))
        # o flip nao muda o frame/UV
        self.assertEqual(frame_cell(uvs_of(o), 4, 1), (0, 0))

    # 7. FlipY: comportamento ATUAL preservado (espelha sprite + inverte canal verde)
    def test_7_flipy_behaviour_unchanged(self):
        rt = make_rt('create.image.S{Source="p.png", NormalMap="pn.png", Columns=4, Rows=1, FlipY=true}')
        o = img(rt, "S")
        asx, asy, _ = o.axis_scale()
        self.assertTrue(asx > 0 and asy < 0)
        self.assertEqual(nm2d.material_uniforms(o.props)["flip_y"], -1.0)
        self.assertEqual(nm2d.to_local(10, 5, 0, False, True), (10, -5))
        self.assertEqual(frame_cell(uvs_of(o), 4, 1), (0, 0))


class NoNormalMapTests(unittest.TestCase):
    # 9. NormalMap ausente: caminho antigo
    def test_9_missing_normalmap(self):
        rt = make_rt('create.image.Player{Source="player.png", Columns=8, Rows=1}')
        o = img(rt, "Player")
        self.assertEqual(o.props["NormalMap"], "")
        self.assertEqual(frame_cell(uvs_of(o), 8, 1), (0, 0))


class DifferentResolution(unittest.TestCase):
    # 10. NormalMap com resolucao diferente do Source, mesma grade 4x2
    def test_10_different_dimensions(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("PIL ausente")
        cols, rows = 4, 2
        colors = [(i * 30 + 10, 255 - i * 30, 40) for i in range(cols * rows)]

        def sheet(fw, fh):
            im = Image.new("RGB", (fw * cols, fh * rows))
            for i, c in enumerate(colors):
                im.paste(c, ((i % cols) * fw, (i // cols) * fh,
                             (i % cols + 1) * fw, (i // cols + 1) * fh))
            return im

        albedo, normal = sheet(64, 64), sheet(16, 16)   # 256x128 vs 64x32
        for frame in range(cols * rows):
            u0, v0, u1, _, _, v1, _, _ = sh.frame_uvs(frame, cols, rows)
            u, v = (u0 + u1) / 2.0, (v0 + v1) / 2.0
            def sample(im):
                return im.getpixel((int(u * im.width), int((1.0 - v) * im.height)))
            self.assertEqual(sample(albedo), colors[frame])
            self.assertEqual(sample(normal), colors[frame])

    def test_aspect_mismatch_detected(self):
        self.assertFalse(sh.aspect_mismatch((256, 128), (64, 32)))
        self.assertTrue(sh.aspect_mismatch((256, 128), (64, 64)))


class LightingAndDebug(unittest.TestCase):
    # 11. Lit = true: shader lit usa o MESMO uv para albedo e normal
    def test_11_lit_shader_shares_uv(self):
        fs = nm2d.fragment_source()
        self.assertIn("texture2D(texture0, uv)", fs)
        self.assertIn("texture2D(normal_map, uv)", fs)
        self.assertIn("vec2 uv = tex_coord0;", fs)
        self.assertEqual(fs.count("tex_coord0"), 1)  # nenhum 2o UV independente

    # 12. ViewNormal = true: debug mostra o normal do MESMO frame
    def test_12_view_normal(self):
        rt = make_rt('''create.image.S{Source="p.png", NormalMap="pn.png", Columns=4, Rows=1,
                        Lit=true, ViewNormal=true, NormalStrength=1.5}''')
        o = img(rt, "S")
        mu = nm2d.material_uniforms(o.props)
        self.assertEqual(mu["debug_normal"], 1.0)
        self.assertEqual(mu["normal_strength"], 1.5)
        self.assertIn("debug_normal > 0.5", nm2d.fragment_source())
        self.assertIn("texture2D(normal_map, uv)", nm2d.fragment_source())


class SingleSourceOfTruth(unittest.TestCase):
    def test_stage_has_no_independent_frame_math(self):
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "luastudio", "stage.py")
        with open(path, encoding="utf-8") as f:
            src = f.read()
        self.assertIn("sheet_mod.frame_uvs_from_props(obj.props)", src)
        self.assertNotIn("frame % cols", src)


if __name__ == "__main__":
    unittest.main()
