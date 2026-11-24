"""3.14 Omezené prostředí pro kód (návrh 10): Python that JARVIS runs for you (run_python) gets fences.

Inside the process (a Python audit hook, installed before your code runs):
- no other programs (subprocess, os.system, os.startfile, exec / spawn)
- no network unless allowed (socket connect / bind, getaddrinfo)
- writing, deleting and renaming only inside the run's own folder (reading anywhere still works – data files)
- no native libraries loaded by hand (ctypes) and no Windows registry writes
Around the process (the operating system): a memory limit and the time limit; on Windows a Job Object that also
allows no child process and kills everything when JARVIS closes the run.

This is a strong fence against mistakes and against ordinary malicious code, not a virtual machine – code built to
break out of Python itself could still do so. It is on by default (Nastavení → Nástroje → Omezené prostředí).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

MEMORY_MB = 2048

HOOK = r'''
import os, sys
WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
PROGRAMS = {"subprocess.Popen", "os.system", "os.exec", "os.posix_spawn", "os.spawn", "os.startfile", "os.fork", "os.forkpty",
            "_winapi.CreateProcess"}
NATIVE = {"ctypes.dlopen", "winreg.CreateKey", "winreg.SetValue", "winreg.DeleteKey", "winreg.DeleteValue"}
NET_EVENTS = {"socket.connect", "socket.bind", "socket.getaddrinfo", "socket.sendto"}
LOOPBACK = {"127.0.0.1", "::1", "localhost", "0.0.0.0", ""}
PATH_EVENTS = {"os.remove", "os.unlink", "os.rename", "os.replace", "os.rmdir", "os.mkdir", "shutil.rmtree", "os.chmod",
               "os.truncate", "os.symlink", "os.link"}


def make_fence(roots, net, programs, native, why):
    roots = [os.path.realpath(r) for r in roots]

    def inside(p):
        try:
            rp = os.path.realpath(os.fsdecode(p))
        except Exception:
            return False
        return any(rp == r or rp.startswith(r + os.sep) for r in roots)

    def local(args):
        # asyncio's self-pipe on Windows is a socket pair on 127.0.0.1 – that is not "the network"
        addr = args[1] if len(args) > 1 and not isinstance(args[0], (str, bytes)) else args[0] if args else None
        host = addr[0] if isinstance(addr, tuple) and addr else addr
        if isinstance(host, bytes):
            host = host.decode("ascii", "replace")
        return isinstance(host, str) and host in LOOPBACK

    def hook(event, args):
        if not programs and event in PROGRAMS:
            raise PermissionError(f"{why}: {event} není dovolené (kód nesmí spouštět programy).")
        if not native and event in NATIVE:
            raise PermissionError(f"{why}: {event} není dovolené (kód nesmí načítat knihovny ani měnit registr).")
        if not net and event in NET_EVENTS and not local(args):
            raise PermissionError(f"{why}: síť je vypnutá (na stahování použij nástroje JARVISe).")
        if roots is None:
            return
        if event == "open" and args:
            path, mode, flags = (list(args) + [None, None, None])[:3]
            writing = (isinstance(mode, str) and any(c in mode for c in "wax+")) or (isinstance(flags, int) and flags & WRITE_FLAGS)
            if writing and isinstance(path, (str, bytes, os.PathLike)) and not inside(path):
                raise PermissionError(f"{why}: zapisovat smím jen do pracovní složky, ne do {os.fsdecode(path)}")
        if event in PATH_EVENTS and args:
            for p in args[:2]:
                if isinstance(p, (str, bytes, os.PathLike)) and not inside(p):
                    raise PermissionError(f"{why}: {event} mimo pracovní složku není dovolené.")
    return hook
'''

BOOT = HOOK + r'''
sys.addaudithook(make_fence([os.environ["JARVIS_SANDBOX_ROOT"]], os.environ.get("JARVIS_SANDBOX_NET") == "1", False, False,
                            "Omezené prostředí"))
import runpy
sys.argv = [sys.argv[1]]
runpy.run_path(sys.argv[0], run_name="__main__")
'''


def install_fence(roots: list[str] | None, net: bool, programs: bool, native: bool = True, why: str = "Oprávnění skillu") -> None:
    # 3.14: the same fence for a skill in its own process, by what its manifest allows. An audit hook cannot be removed:
    # call this only in a process that runs nothing else afterwards.
    ns: dict[str, Any] = {}
    exec(compile(HOOK, "<jarvis-fence>", "exec"), ns)       # noqa: S102 – our own constant source
    sys.addaudithook(ns["make_fence"](roots, net, programs, native, why))


def boot_file(run_dir: Path) -> Path:
    p = run_dir / ".jarvis_sandbox_boot.py"
    p.write_text(BOOT, encoding="utf-8")
    return p


def env_for(run_dir: Path, network: bool = False) -> dict[str, str]:
    tmp = run_dir / "tmp"
    tmp.mkdir(exist_ok=True)
    env = {**os.environ, "JARVIS_SANDBOX_ROOT": str(run_dir), "JARVIS_SANDBOX_NET": "1" if network else "0",
           "TMP": str(tmp), "TEMP": str(tmp), "TMPDIR": str(tmp), "MPLCONFIGDIR": str(run_dir / ".mpl"),
           "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1", "HOME": str(run_dir), "USERPROFILE": str(run_dir),
           "MPLBACKEND": "Agg", "PYTHONIOENCODING": "utf-8"}
    for k in ("PYTHONPATH", "PYTHONSTARTUP"):
        env.pop(k, None)
    return env


def command(python_cmd: list[str], script: Path, run_dir: Path) -> list[str]:
    """`python_cmd` is how JARVIS starts Python for user code: [python, script] or [JARVIS.exe, --run-python, script].
    The boot file takes the script's place and runs it under the audit hook."""
    boot = boot_file(run_dir)
    base = list(python_cmd[:-1]) if python_cmd and python_cmd[-1] == str(script) else list(python_cmd)
    return [*base, str(boot), str(script)]


def _posix_limits(seconds: int) -> Any:
    def apply() -> None:
        import resource

        mem = MEMORY_MB * 2**20
        for res, val in ((resource.RLIMIT_AS, mem), (resource.RLIMIT_CPU, max(5, seconds + 5))):
            try:
                resource.setrlimit(res, (val, val))
            except (ValueError, OSError):
                pass
    return apply


def _windows_job(pid: int) -> Any:
    """A Job Object: memory limit, no child processes, everything killed when the handle closes."""
    import ctypes
    from ctypes import wintypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]  # Windows only
    k32.CreateJobObjectW.restype = wintypes.HANDLE                         # 64-bit handles, not the default c_int
    k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]

    class IO(ctypes.Structure):
        _fields_ = [(n, ctypes.c_ulonglong) for n in ("r", "w", "o", "rb", "wb", "ob")]

    class BASIC(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]

    class EXT(ctypes.Structure):
        _fields_ = [("Basic", BASIC), ("Io", IO), ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

    job = k32.CreateJobObjectW(None, None)
    info = EXT()
    info.Basic.LimitFlags = 0x0008 | 0x0100 | 0x2000          # ACTIVE_PROCESS | PROCESS_MEMORY | KILL_ON_JOB_CLOSE
    info.Basic.ActiveProcessLimit = 1
    info.ProcessMemoryLimit = MEMORY_MB * 2**20
    k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info))   # JobObjectExtendedLimitInformation
    h = k32.OpenProcess(0x1F0FFF, False, pid)
    k32.AssignProcessToJobObject(job, h)
    k32.CloseHandle(h)
    return job


def _close_handle(h: Any) -> None:
    import ctypes
    from ctypes import wintypes

    k32 = ctypes.WinDLL("kernel32")  # type: ignore[attr-defined]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    k32.CloseHandle(h)


def run(python_cmd: list[str], script: Path, run_dir: Path, timeout: int, network: bool = False) -> subprocess.CompletedProcess:
    cmd = command(python_cmd, script, run_dir)
    env = env_for(run_dir, network)
    if sys.platform == "win32":
        p = subprocess.Popen(cmd, cwd=run_dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                             errors="replace", env=env, creationflags=0x08000000)       # no window
        job = None
        try:                       # the audit hook is installed before the user's code: the job joins a moment later
            job = _windows_job(p.pid)
        except Exception:  # noqa: BLE001 – the audit hook still applies
            job = None
        try:
            out, err = p.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            p.kill()
            out, err = p.communicate()
            raise
        finally:
            if job:
                _close_handle(job)
        return subprocess.CompletedProcess(cmd, p.returncode, out, err)
    return subprocess.run(cmd, cwd=run_dir, capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace",
                          env=env, preexec_fn=_posix_limits(timeout))
