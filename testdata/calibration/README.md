# Saved calibration evidence

`qualification-v1.tar.xz` was captured with the version-1 writer at
`e5308620f4fa0d4ef5454a4c0cff9e5046c56228` using the two-metal test stack and
the four-axis study in `tests/calibration/qualification_test.py`.

The solver is replaced by the existing test helper, which writes a known passive
three-conductor capacitance matrix and distinct input/adaptive panel counts.
The fixture tests schema compatibility and provenance, not solver accuracy.

- The A/B grounded matrix is `[[7e-15, -1e-15], [-1e-15, 5e-15]]` in farads
- All four refinements are numerically stabilized for this constant matrix
- The original run manifests, raw reports, logs, scene files and SHA256 references are included
- Tests unpack the fixture into a temporary directory and verify that every original file remains unchanged

The archive is a fixed output of the old writer. Do not regenerate it with the
current schema or construct it by reversing the compatibility reader.
