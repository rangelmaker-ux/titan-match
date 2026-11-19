"""Resolve antes da 21.1.2: a API devolve None para ExportFrame; o frame sai do arquivo."""
import cv2
import numpy as np
import pytest

from titan_match.resolve_bridge import ResolveBridge, ResolveError


class _Resolve:
    def GetVersionString(self):
        return "20.2.1"


class _MPI:
    def __init__(self, path):
        self.path = path

    ExportFrame = None  # como o fusionscript devolve uma função inexistente

    def GetClipProperty(self, key):
        return self.path if key == "File Path" else ""


class _Item:
    def __init__(self, mpi, start=0, dur=10):
        self.mpi, self.start, self.dur = mpi, start, dur

    ExportFrame = None

    def GetMediaPoolItem(self):
        return self.mpi

    def GetSourceStartFrame(self):
        return self.start

    def GetDuration(self):
        return self.dur


def _video(tmp_path, n=10):
    p = tmp_path / "clipe.avi"
    w = cv2.VideoWriter(str(p), cv2.VideoWriter_fourcc(*"MJPG"), 24, (64, 48))
    for i in range(n):
        f = np.zeros((48, 64, 3), np.uint8)
        f[:, :] = (0, 0, 25 * i)  # vermelho cresce a cada frame (BGR)
        w.write(f)
    w.release()
    return p


def test_frame_vem_do_arquivo_quando_nao_ha_exportframe(tmp_path):
    br = ResolveBridge(_Resolve())
    img = br.source_frame(_Item(_MPI(str(_video(tmp_path)))))
    assert img.ndim == 3 and img.shape[2] == 3
    r, g, b = img[..., 0].mean(), img[..., 1].mean(), img[..., 2].mean()
    assert r > 0.3 and g < 0.05 and b < 0.05  # frame do meio (5): vermelho ~125/255, em RGB


def test_graded_frame_tambem_cai_no_arquivo(tmp_path):
    br = ResolveBridge(_Resolve())
    assert br.graded_frame(_Item(_MPI(str(_video(tmp_path))))).ndim == 3


def test_still_de_imagem(tmp_path):
    p = tmp_path / "foto.png"
    cv2.imwrite(str(p), np.full((20, 30, 3), 200, np.uint8))
    img = ResolveBridge(_Resolve()).source_frame(_Item(_MPI(str(p)), dur=1))
    assert img.shape[:2] == (20, 30)


def test_arquivo_sumido_explica_versao(tmp_path):
    with pytest.raises(ResolveError, match="20.2.1"):
        ResolveBridge(_Resolve()).source_frame(_Item(_MPI(str(tmp_path / "nao_existe.mp4"))))
