"""Explicitly registered video backends. Public API compatibility lives in compat."""

from .cpu import CpuBackend
from .gpu import NvidiaBackend, QsvBackend, VaapiBackend
from .registry import HardwareRegistry
from .rockchip import RockchipBackend

registry = HardwareRegistry((CpuBackend(), RockchipBackend(), NvidiaBackend(), QsvBackend(), VaapiBackend()))
