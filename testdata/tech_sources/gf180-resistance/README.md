Pinned source fixtures for the qualified fixed-layout GF180 resistance sensitivity tests.

- `5_General_Specification1.csv`, `5_General_Specification2.csv` and `5_Sheet_Rho_table.csv` are unchanged files from `fossi-foundation/gf180mcu-pdk` at `25ed9c64b64b8e1b93cc4d2d5cade4cd82383a9a`
- `gf180mcuD.tech` is the unchanged `gf180mcu/magic/gf180mcu-extract.tech` from `fossi-foundation/open-pdks` at `5740c4a81c42f9fe4af5ef2ee258a99151053d28`
- Full paths and SHA-256 hashes are recorded in `scripts/gen_tech_pb/corners/gf180mcuD-resistance.json` and checked against these bytes by the source-regression tests

The primary contact/via minimum cells contain `--`, meaning unspecified. The explicitly named ideal-contact scenario takes its zeros only from the maintained extraction table's `lrhc`/`lrlc` block. It does not interpret missing primary values as zero.
