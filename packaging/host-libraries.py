"""Lists what the Linux bundle asks the HOST for, and fails if it is more than the short approved list below.

    python3 packaging/host-libraries.py dist/Cairn

Every shared library in the bundle names the libraries it needs. Those the bundle carries itself are fine; the rest must already be
on the machine of whoever downloads the app. This was written after a full desktop session found the released app exiting at startup
with "libEGL.so.1: cannot open shared object file" (a desktop installed without its optional packages has no libEGL), and after the
bare-container test, which had libegl1 installed, had called that "what every desktop has". The list of what the app really needs is
now checked on every build, so a new dependency cannot slip in unnoticed."""
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
    for path in elf_files:
        out = subprocess.run(['readelf', '-d', path], capture_output=True, text=True).stdout
        for m in re.finditer(r'\(NEEDED\)\s+Shared library: \[(.+?)\]', out):
            if m.group(1) not in provided and m.group(1) not in CORE:
                wanted[m.group(1)].add(os.path.relpath(path, root))
    print(f'{len(elf_files)} files checked; the bundle asks the host for {len(wanted)} library(ies) beyond the C library:')
    for lib in sorted(wanted):
        print(f'  {"approved  " if lib in APPROVED else "UNEXPECTED"} {lib}   ({len(wanted[lib])} files, e.g. {sorted(wanted[lib])[0]})')
    unexpected = sorted(set(wanted) - APPROVED)
    if unexpected:
        print(f'FAILED: a desktop installed without optional packages may not have: {", ".join(unexpected)}. Bundle them (--add-binary), '
              'or add them to APPROVED here with the reason.')
        return 1
    print('OK: nothing is asked of the host beyond the approved list.')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1]))
