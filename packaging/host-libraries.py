"""Lists what the Linux bundle asks the HOST for, and fails if it is more than the short approved list below.

    python3 packaging/host-libraries.py dist/Cairn

Every shared library in the bundle names the libraries it needs. Those the bundle carries itself are fine; the rest must already be
on the machine of whoever downloads the app. This was written after a full desktop session found the released app exiting at startup
with "libEGL.so.1: cannot open shared object file" (a desktop installed without its optional packages has no libEGL), and after the
bare-container test, which had libegl1 installed, had called that "what every desktop has". The list of what the app really needs is
now checked on every build, so a new dependency cannot slip in unnoticed.

It also enforces two rules found later, by running the packaged app against a modern Mesa:
  * the bundle must NOT ship its own libstdc++ or libgcc_s: the copy from the build machine is searched first and shadows the newer system
    one that Mesa needs, so hardware drawing (DBV_GPU=1) aborted with "Could not initialize GLX";
  * what the bundle needs from the system's libstdc++ is printed and capped (MAX_GLIBCXX), because it sets the oldest system the app runs on."""
import collections
import os
import re
import subprocess
import sys

# the C library and the loader: present on every Linux system, and never bundled
CORE = {'libc.so.6', 'libm.so.6', 'libdl.so.2', 'libpthread.so.0', 'librt.so.1', 'libutil.so.1', 'libresolv.so.2',
        'libnsl.so.1', 'libgcc_s.so.1', 'libstdc++.so.6', 'ld-linux-x86-64.so.2', 'linux-vdso.so.1'}
# what a desktop is expected to provide: the X11 client library, which any X session has
APPROVED = {'libxcb.so.1'}
# the C++ runtime comes from the system, always (see above)
MUST_NOT_SHIP = {'libstdc++.so.6', 'libgcc_s.so.1'}
# GLIBCXX_3.4.N the bundle may need from the system's libstdc++: 30 is GCC 12, Ubuntu 22.04. A higher number raises the oldest supported system.
MAX_GLIBCXX = 30


def problems(provided, wanted, glibcxx):
    """Everything wrong, as sentences. provided: file names in the bundle; wanted: libraries asked of the host beyond the C library;
    glibcxx: the highest GLIBCXX_3.4.N any file needs."""
    found = []
    shipped = sorted(MUST_NOT_SHIP & set(provided))
    if shipped:
        found.append(f'the bundle ships {", ".join(shipped)}; it must use the system\'s (a build-machine copy shadows the newer one a modern Mesa needs)')
    unexpected = sorted(set(wanted) - APPROVED)
    if unexpected:
        found.append(f'a desktop installed without optional packages may not have: {", ".join(unexpected)}. Bundle them (--add-binary), '
                     'or add them to APPROVED here with the reason')
    if glibcxx > MAX_GLIBCXX:
        found.append(f'the bundle needs GLIBCXX_3.4.{glibcxx} from the system, newer than 3.4.{MAX_GLIBCXX} (GCC 12, Ubuntu 22.04): this raises the '
                     'oldest system the app runs on. Raise MAX_GLIBCXX here and say so on the download page')
    return found


def main(root):
    provided, elf_files = set(), []
    for directory, _, names in os.walk(root):
        for name in names:
            provided.add(name)
            path = os.path.join(directory, name)
            if os.path.islink(path):
                continue
            with open(path, 'rb') as f:
                if f.read(4) == b'\x7fELF':
                    elf_files.append(path)
    wanted = collections.defaultdict(set)
    glibcxx = 0
    for path in elf_files:
        out = subprocess.run(['readelf', '-d', path], capture_output=True, text=True).stdout
        for m in re.finditer(r'\(NEEDED\)\s+Shared library: \[(.+?)\]', out):
            if m.group(1) not in provided and m.group(1) not in CORE:
                wanted[m.group(1)].add(os.path.relpath(path, root))
        versions = subprocess.run(['readelf', '-V', path], capture_output=True, text=True).stdout
        for m in re.finditer(r'GLIBCXX_3\.4\.(\d+)', versions):
            glibcxx = max(glibcxx, int(m.group(1)))
    print(f'{len(elf_files)} files checked; the bundle asks the host for {len(wanted)} library(ies) beyond the C library:')
    for lib in sorted(wanted):
        print(f'  {"approved  " if lib in APPROVED else "UNEXPECTED"} {lib}   ({len(wanted[lib])} files, e.g. {sorted(wanted[lib])[0]})')
    print(f'it needs GLIBCXX_3.4.{glibcxx} from the system C++ runtime (limit 3.4.{MAX_GLIBCXX}); ships its own libstdc++/libgcc_s: '
          f'{"YES" if MUST_NOT_SHIP & provided else "no"}')
    found = problems(provided, wanted, glibcxx)
    for line in found:
        print('FAILED:', line)
    if not found:
        print('OK: nothing is asked of the host beyond the approved list.')
    return 1 if found else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1]))
