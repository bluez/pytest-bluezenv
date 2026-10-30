# -*- coding: utf-8; mode: python; eval: (blacken-mode); -*-
# SPDX-License-Identifier: GPL-2.0-or-later
"""
Functional tests: run the plugin through pytester in an isolated session.

These need neither QEMU nor a kernel; they check that options/ini values are
registered and that the fixtures resolve or skip as documented.
"""

import pytest

PLUGIN = ["-p", "pytest_bluezenv"]


# -- command line / ini registration (see doc/options.rst) ------------------


def test_options_registered(pytester):
    config = pytester.parseconfig(
        *PLUGIN, "--vm-timeout", "7.5", "--vm-mem", "512M", "--log-filter", "+a,-b"
    )

    assert config.getoption("kernel") is None
    assert config.getoption("vm_timeout") == 7.5  # type=float
    assert config.getoption("vm_mem") == "512M"
    assert config.getoption("log_filter") == ["+a,-b"]  # action=append
    assert config.getoption("kernel_build") == "use"  # default

    for flag in (
        "btmon",
        "btvirt_debug",
        "force_usb",
        "force_pcie",
        "no_log_reorder",
    ):
        assert config.getoption(flag) in (None, False)


def test_flag_options_store_true(pytester):
    config = pytester.parseconfig(*PLUGIN, "--btmon", "--btvirt-debug")
    assert config.getoption("btmon")
    assert config.getoption("btvirt_debug")


def test_ini_defaults(pytester):
    config = pytester.parseconfig(*PLUGIN)
    assert config.getini("vm_timeout") == "30"
    assert config.getini("host_plugins.rcvbuf.default") == "1048576"
    assert config.getini("kernel_branch") == "master"


# -- option and ini wiring ---------------------------------------------------


DEFAULTS_TEST = """
    from pytest_bluezenv import env, utils

    def test_defaults():
        assert utils.DEFAULT_TIMEOUT == {timeout}
        assert env.Environment.DEFAULT_MEM == {mem}
"""


@pytest.fixture
def restore_plugin_state():
    from pytest_bluezenv import env, utils

    original = (utils.DEFAULT_TIMEOUT, env.Environment.DEFAULT_MEM)
    yield
    # The inner run configures these globals; the outer session must
    # keep its own values.
    utils.DEFAULT_TIMEOUT, env.Environment.DEFAULT_MEM = original


@pytest.mark.usefixtures("restore_plugin_state")
def test_vm_timeout_option_sets_default_timeout(pytester):
    pytester.makepyfile(DEFAULTS_TEST.format(timeout=7.5, mem=repr("512M")))
    pytester.runpytest(
        *PLUGIN, "--vm-timeout", "7.5", "--vm-mem", "512M"
    ).assert_outcomes(passed=1)


@pytest.mark.usefixtures("restore_plugin_state")
def test_vm_timeout_ini_sets_default_timeout(pytester):
    pytester.makeini("[pytest]\nvm_timeout = 42\n")
    pytester.makepyfile(DEFAULTS_TEST.format(timeout=42, mem=repr("512M")))
    pytester.runpytest(*PLUGIN, "--vm-mem", "512M").assert_outcomes(passed=1)


# -- the kernel fixture (skips when no image; resolves build dirs) ----------


@pytest.fixture
def kernel_file(tmp_path):
    image = tmp_path / "bzImage"
    image.write_bytes(b"\x00")
    return image


KERNEL_TEST = """
    import os
    def test_kernel(kernel):
        assert os.path.isfile(kernel)
"""


def test_kernel_fixture_accepts_file(pytester, kernel_file):
    pytester.makepyfile(KERNEL_TEST)
    result = pytester.runpytest(
        *PLUGIN, "--kernel-build=no", "--kernel", str(kernel_file)
    )
    result.assert_outcomes(passed=1)


def test_kernel_fixture_skips_missing(pytester, tmp_path):
    pytester.makepyfile(KERNEL_TEST)
    result = pytester.runpytest(
        *PLUGIN, "--kernel-build=no", "--kernel", str(tmp_path / "nope")
    )
    result.assert_outcomes(skipped=1)


def test_kernel_fixture_skips_build_dir_without_image(pytester, tmp_path):
    (tmp_path / "arch" / "x86" / "boot").mkdir(parents=True)
    pytester.makepyfile(KERNEL_TEST)
    result = pytester.runpytest(*PLUGIN, "--kernel-build=no", "--kernel", str(tmp_path))
    result.assert_outcomes(skipped=1)


def test_kernel_fixture_skips_when_unset(pytester):
    pytester.makepyfile(KERNEL_TEST)
    result = pytester.runpytest(*PLUGIN, "--kernel-build=no")
    result.assert_outcomes(skipped=1)


# -- host fixtures skip cleanly without a kernel ----------------------------

HOSTS_TEST = """
    from pytest_bluezenv import host_config, Call

    @host_config([Call()])
    def test_hosts(hosts):
        assert hosts
"""

HOSTS_ONCE_TEST = """
    from pytest_bluezenv import host_config, Call

    @host_config([Call()], reuse=True)
    def test_hosts_once(hosts_once):
        assert hosts_once
"""


def test_hosts_skips_without_kernel(pytester):
    pytester.makepyfile(HOSTS_TEST)
    result = pytester.runpytest(*PLUGIN, "--kernel-build=no")
    result.assert_outcomes(skipped=1)


def test_hosts_once_skips_without_kernel(pytester):
    pytester.makepyfile(HOSTS_ONCE_TEST)
    result = pytester.runpytest(*PLUGIN, "--kernel-build=no")
    result.assert_outcomes(skipped=1)


def _elf(path, sections):
    """
    Write a minimal 64-bit little-endian ELF with the given section names,
    enough for the User Mode Linux detection.
    """
    import struct

    names = b"\0" + b"".join(name.encode() + b"\0" for name in sections)
    names += b".shstrtab\0"
    strtab = 64
    shoff = strtab + len(names)

    shdrs = struct.pack("<IIQQQQIIQQ", *[0] * 10)
    offset = 1
    for name in list(sections) + [".shstrtab"]:
        size = len(names) if name == ".shstrtab" else 0
        shdrs += struct.pack("<IIQQQQIIQQ", offset, 1, 0, 0, strtab, size, 0, 0, 1, 0)
        offset += len(name) + 1

    shnum = len(sections) + 2
    hdr = b"\x7fELF\x02\x01\x01" + b"\0" * 9
    hdr += struct.pack(
        "<HHIQQQIHHHHHH", 2, 62, 1, 0, 0, shoff, 0, 64, 0, 0, 64, shnum, shnum - 1
    )

    path.write_bytes(hdr + names + shdrs)


KERNEL_NAME_TEST = """
    import os
    def test_kernel(kernel):
        assert os.path.basename(kernel) == {name!r}
"""


def test_kernel_fixture_uses_uml_build(pytester, tmp_path):
    _elf(tmp_path / "linux", [".text", ".uml.setup.init"])
    pytester.makepyfile(KERNEL_NAME_TEST.format(name="linux"))
    result = pytester.runpytest(*PLUGIN, "--kernel-build=no", "--kernel", str(tmp_path))
    result.assert_outcomes(passed=1)


def test_kernel_fixture_prefers_bzimage(pytester, tmp_path):
    _elf(tmp_path / "linux", [".text", ".uml.setup.init"])
    boot = tmp_path / "arch" / "x86" / "boot"
    boot.mkdir(parents=True)
    (boot / "bzImage").write_bytes(b"\x00")
    pytester.makepyfile(KERNEL_NAME_TEST.format(name="bzImage"))
    result = pytester.runpytest(*PLUGIN, "--kernel-build=no", "--kernel", str(tmp_path))
    result.assert_outcomes(passed=1)


def test_kernel_fixture_skips_non_uml_elf(pytester, tmp_path):
    # e.g. a vmlinux: ELF, but not a User Mode Linux binary
    _elf(tmp_path / "linux", [".text", ".data"])
    pytester.makepyfile(KERNEL_TEST)
    result = pytester.runpytest(*PLUGIN, "--kernel-build=no", "--kernel", str(tmp_path))
    result.assert_outcomes(skipped=1)


def test_uml_kernel_detection(tmp_path):
    from pytest_bluezenv.env import Environment

    _elf(tmp_path / "uml", [".text", ".uml.setup.init"])
    _elf(tmp_path / "vmlinux", [".text", ".data"])
    (tmp_path / "bzImage").write_bytes(b"MZ" + b"\0" * 64)

    assert Environment.is_uml_kernel(tmp_path / "uml")
    assert not Environment.is_uml_kernel(tmp_path / "vmlinux")
    assert not Environment.is_uml_kernel(tmp_path / "bzImage")
    assert not Environment.is_uml_kernel(tmp_path / "missing")
