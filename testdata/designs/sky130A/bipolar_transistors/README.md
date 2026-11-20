These layouts reproduce the five fixed-size SKY130 BJT models. They are copied
without geometry changes from [open-pdks-regression-tests](https://github.com/iic-jku/open-pdks-regression-tests/tree/c72ee597b6d5ba1ea50bb023aea77fbb37319bd4/sky130A/layout),
commit `c72ee597b6d5ba1ea50bb023aea77fbb37319bd4`, and compressed with gzip.

Copyright 2026 Julian Schwarz and Simon Dorrer. Apache-2.0; see `LICENSE`.

`sky130_npn_11v0_rotated.gds.gz` and
`sky130_npn_11v0_mirrored_with_poly_contact.gds.gz` are transformed derivatives
created by `tests/rcx25/sky130_bipolar_test.py`. The latter also adds an unrelated
ordinary poly-to-local-interconnect contact to verify that its resistance remains.
