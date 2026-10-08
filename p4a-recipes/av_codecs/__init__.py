from pythonforandroid.toolchain import Recipe


class PyAVCodecsRecipe(Recipe):
    # The stock recipe also pulls in libx264 and libvpx (video). Only the MP3
    # encoder is needed here.
    depends = ["libshine"]

    def build_arch(self, arch):
        pass


recipe = PyAVCodecsRecipe()
