import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from luastudio import glsl as glsl_mod
from luastudio.runtime import Runtime


SCRIPT = """
create.shader.Vidro = { Screen = true, Fragment = [[
void main(void) { gl_FragColor = sampleBehind(); }
]] }
create.shader.Normal = { Fragment = [[
void main(void) { gl_FragColor = sampleContent(vLocalUV); }
]] }
B = create.button.B{ Position = {0, 0}, Size = {10, 10}, Shader = "Vidro" }
C = create.button.C{ Position = {0, 0}, Size = {10, 10}, Shader = "Normal", ShaderMode = "screen" }
"""


class ScreenShaderTest(unittest.TestCase):
    def test_flag_e_programa(self):
        logs = []
        rt = Runtime(log=logs.append)
        self.assertTrue(rt.run_source(SCRIPT), logs)
        self.assertTrue(glsl_mod.SHADERS.get("Vidro").screen)
        self.assertFalse(glsl_mod.SHADERS.get("Normal").screen)
        prog = glsl_mod.SHADERS.program_2d("Vidro")
        self.assertIn("uScreenTexture", prog.types)
        self.assertIn("sampleBehind", prog.fs)
        self.assertEqual(rt.scene.by_name["C"].props.get("ShaderMode"), "screen")

    def test_sample_content_e_object(self):
        fs = glsl_mod.SHADERS.program_2d("Vidro").fs
        self.assertIn("vec4 sampleObject", fs)
        self.assertIn("uScreenOn", fs)

    def test_fullscreen_prop(self):
        rt = Runtime(log=lambda *_a: None)
        self.assertTrue(rt.run_source("F = create.frame.F{ FullScreen = true, ShaderMode = 'screen' }"))
        self.assertTrue(rt.scene.by_name["F"].props.get("FullScreen"))

    def test_contrato_sample_content(self):
        glsl_mod.SHADERS.register("Leg", "void main(void){gl_FragColor=sampleContent(vec2(0.5));}", screen=True)
        glsl_mod.SHADERS.register("Novo", "void main(void){gl_FragColor=sampleContent(vLocalUV)*sampleBehind();}", screen=True)
        self.assertIn("#define LS_CONTENT_IS_SCREEN", glsl_mod.SHADERS.program_2d("Leg").fs)
        self.assertNotIn("#define LS_CONTENT_IS_SCREEN", glsl_mod.SHADERS.program_2d("Novo").fs)

    def test_declaracao_do_usuario_nao_duplica(self):
        glsl_mod.SHADERS.register("U", "uniform sampler2D uScreenTexture;\nvoid main(void){gl_FragColor=sampleBehind();}\n")
        fs = glsl_mod.SHADERS.program_2d("U").fs
        self.assertEqual(fs.count("uniform sampler2D uScreenTexture"), 1)


if __name__ == "__main__":
    unittest.main()
