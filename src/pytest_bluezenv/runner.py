#!/usr/bin/python3 -P
# -*- coding: utf-8; mode: python; eval: (blacken-mode); -*-
# SPDX-License-Identifier: GPL-2.0-or-later
import ctypes
import os
import sys
import pickle
from pathlib import Path
from importlib.machinery import PathFinder
from subprocess import run


class SelfImport(PathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "pytest_bluezenv":
            path = [str(Path(__file__).parent / "..")]
        return super().find_spec(fullname, path, target)


sys.meta_path.insert(0, SelfImport())

# Mount /run/shared: 9p for QEMU, hostfs for User Mode Linux
path = Path("/run/shared")
path.mkdir()
shared = os.environ.get("BLUEZENV_SHARED")
if shared:
    # mount(2) directly: hostfs takes the host directory as raw data with
    # it, while mount(8) passes options through the new mount API or
    # mount(2) depending on its version, which hostfs parse differently
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.mount(b"none", bytes(path), b"hostfs", 0, shared.encode()) < 0:
        err = ctypes.get_errno()
        raise OSError(err, f"Failed to mount {shared}: {os.strerror(err)}")
else:
    run(["mount", "-t", "9p", "/dev/shared", str(path)], check=True)

# Early setup sys.path
with open("/run/shared/defaults", "rb") as f:
    sys.path = pickle.load(f)[0]


import pytest_bluezenv.env

sys.exit(pytest_bluezenv.env._main_runner())
