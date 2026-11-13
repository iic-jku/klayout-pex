# MIM corner reference models

These pinned upstream models are independent references for the generated device-capacitance
expressions. `sources.json` records each original URL, original file SHA-256 and excerpt scope.
Model equations, parameter values and licence text are unchanged. Trailing whitespace is normalized. Excerpts omit unrelated devices and library
includes so tests do not download a PDK. Each fixture retains its source licence.

The AC tests measure mutual capacitance from the off-diagonal admittance, at zero bias and low
frequency. Series resistance and leakage remain in the model. This checks the capacitance
observable without treating conductance as capacitance.

- `SKY130`: both MIM plate options and all four R/C styles, at 27 °C with mismatch disabled.
  Each style supplies its own dimension shifts as well as capacitance coefficients. The test
  sets resistance temperature coefficients to zero at their 27 °C reference temperature
- `GF180`: the supported 2 fF/µm² MIM option, `mimcap_ff` and `mimcap_ss`, at 25 °C with mismatch
  disabled. Both area and edge terms follow the corner factor
- `IHP SG13G2`: `cap_cmim`, `cap_bcs` and `cap_wcs`, at 27 °C with mismatch disabled. The area
  term varies while the edge term remains fixed. Tests include a nonunit multiplier

Squares and long rectangles distinguish area and edge contributions. Separate boundary tests
check positive effective dimensions and multipliers. These references do not qualify MOM, RF
capacitors, other MIM process options, or physical-stack corner correlation.

The plain MIM equations do not declare a finite geometric validity interval beyond positive
effective dimensions. The 7–75 µm interval in the IHP source belongs to the excluded `rfcmim`
model. These checks do not replace the PDK layout rules or qualify extrapolation of RF models.
