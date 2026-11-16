"""The rules of the Linux dependency check (packaging/host-libraries.py), without needing a built bundle."""
import importlib.util
from pathlib import Path

SPEC = importlib.util.spec_from_file_location('host_libraries', Path(__file__).resolve().parent.parent / 'packaging' / 'host-libraries.py')
hl = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(hl)


def test_a_clean_bundle_has_no_problems():
    assert hl.problems({'Cairn', 'libQt6Core.so.6'}, {'libxcb.so.1': {'x'}}, 30) == []


def test_shipping_the_cxx_runtime_is_caught():
    """The bug: the build machine's libstdc++ shadowed the newer system one Mesa needs, so hardware drawing aborted with 'Could not initialize GLX'."""
    found = hl.problems({'libstdc++.so.6', 'libgcc_s.so.1', 'libQt6Core.so.6'}, {}, 30)
    assert len(found) == 1 and 'libgcc_s.so.1' in found[0] and 'libstdc++.so.6' in found[0] and 'shadows' in found[0]


def test_a_new_host_library_is_caught_unless_approved():
    assert hl.problems(set(), {'libEGL.so.1': {'x'}}, 30)[0].startswith('a desktop installed without optional packages may not have: libEGL.so.1')
    assert hl.problems(set(), {'libxcb.so.1': {'x'}}, 30) == []


def test_needing_a_newer_system_cxx_runtime_is_caught_because_it_raises_the_minimum_system():
    found = hl.problems(set(), {}, hl.MAX_GLIBCXX + 1)
    assert len(found) == 1 and 'oldest system' in found[0]
    assert hl.problems(set(), {}, hl.MAX_GLIBCXX) == []
