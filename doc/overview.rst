Overview
========

pytest-bluezenv runs an ordinary Pytest test body on the upper tester and
the Bluetooth software under test on one or more VM hosts. Each VM host
has its own kernel and BlueZ instance. The plugin turns a declarative
:obj:`~pytest_bluezenv.host_config` into VM hosts, then exposes their host
plugins through RPC proxies.

.. image:: _static/overview.svg
   :alt: pytest drives several QEMU VM hosts over RPC; each host's kernel reaches its own controller, and the controllers see each other through the emulated btvirt air link.

Test layout
-----------

The upper tester is the Pytest process. It collects tests, creates the
required VM hosts, and drives them. It does not run the Bluetooth software
under test.

A VM host is a QEMU guest running the selected kernel. Its lower
tester loads host plugins and runs their code. Programs such as
``bluetoothd``, ``obexd``, and ``bluetoothctl`` remain in the VM host.

A test declares one plugin list for each VM host. The
:obj:`~pytest_bluezenv.hosts` fixture supplies a
:obj:`~pytest_bluezenv.HostProxy` for every declared host:

.. code-block:: python

   @host_config([Bluetoothd(), Bluetoothctl()], [Bluetoothd()])
   def test_discovery(hosts):
       host0, host1 = hosts
       host0.bluetoothctl.send("scan on\n")

``host0.bluetoothctl.send()`` is an RPC call. The upper tester serialises
the call, the lower tester executes it, and the result returns to the test
body. A lower-tester exception is reported as
:obj:`~pytest_bluezenv.RemoteError`. :doc:`writing_tests` describes host
configuration and plugins in detail.

VM-host channels
----------------

The plugin starts VM hosts through BlueZ's ``test-runner`` QEMU
launcher. pytest-bluezenv adds the following channels between the
upper tester and each VM host:

.. image:: _static/channels.svg
   :alt: Four channels between the upper tester and a VM host: control (RPC), log, tty, and a shared directory.

control
    The RPC connection carries plugin calls, results, and exceptions.
    ``--vm-timeout`` bounds a call's round trip.

log
    Timestamped lower-tester log records stream to the upper tester.
    VM-host loggers are named ``host.<run>.<index>``, such as
    ``host.0.1`` and service loggers as ``host.<run>.<service>``.

tty
    A serial console with a root shell, for manual debugging.
    Use `python3 -mpytest_bluezenv attach` to attach it using Tmux.

shared
    A read-write directory mounted as ``/run/shared`` in the VM host and
    created as ``/tmp/pytest-bluezenv-*/shared-*`` on the upper tester.
    Core dumps and ``btmon`` captures are collected from it before the VM
    host shuts down.

Controllers
-----------

Each VM host has one controller, driven by its kernel over HCI. By default,
one ``btvirt`` process provides the controllers and their virtual air link.
VM hosts can therefore communicate without Bluetooth hardware.

.. image:: _static/controllers.svg
   :alt: Each VM host has its own hci0 controller connected over HCI to its kernel; a single btvirt process provides the controllers and bridges a virtual air link between them.

``--usb`` and ``--pcie`` pass named physical controllers to VM hosts. In
that configuration the VM hosts communicate over the real radio rather
than through ``btvirt``. USB pass-through requires permission to open the
device. PCIe pass-through temporarily binds the controller to
``vfio-pci`` and requires root privileges, an enabled IOMMU, and an
isolated IOMMU group.

Tests use ``btvirt`` unless their :obj:`~pytest_bluezenv.host_config`
requests ``hw=True`` or ``--force-usb`` / ``--force-pcie`` is set. A
configuration can also omit a controller with ``controller=False``.

After a reset, a controller is powered off. ``bluetoothd`` powers it on
when it starts. A configuration without ``bluetoothd`` must arrange that
it is powered on.

Reusing VM hosts
----------------

VM hosts are started on demand and Pytest orders tests with matching
VM requirements together. The :obj:`~pytest_bluezenv.hosts` fixture
can therefore share VM hosts between tests;
:obj:`~pytest_bluezenv.hosts_once` reserves VM hosts for one test.

Host plugins are normally torn down after each test, even when the VM
host is shared. The lower tester also resets the previous process
group and powers the controller off.  ``reuse=True`` retains plugins
for consecutive tests with the same host setup.

Time and log ordering
---------------------

Records from several VM hosts are interleaved and sorted by timestamp by
default. ``--no-log-reorder`` preserves arrival order. ``chronyd`` keeps
the VM-host clock close to the upper tester through the KVM PTP clock. The
paravirtualisation and PTP kernel options in :doc:`requirements` are
required for this.

Timeouts
--------

The wait helpers, including :obj:`~pytest_bluezenv.wait_until` and plugin
``expect`` calls, use the configured default timeout. ``--vm-timeout``
also bounds each RPC round trip. A timeout in the VM host is reported as
:obj:`~pytest_bluezenv.rpc.RemoteTimeoutError`.

Failures and diagnostics
------------------------

When a process crashes, its core dump is written to the shared
directory and copied out before VM shutdown.  Unless
``--no-core-backtraces`` is set, a backtrace is generated and reported
as :obj:`~pytest_bluezenv.CoredumpWarning`. Kernel ``BUG`` and
``WARNING`` records produce :obj:`~pytest_bluezenv.KernelBugWarning`.
Sanitizer reports, such as ASan output, produce
:obj:`~pytest_bluezenv.SanitizerWarning`.

``--btmon`` captures controller traffic for every VM host into
``test-bluezenv-*.btsnoop`` files.

The command line options and interactive VM-host access are documented
in :doc:`running_tests`.
