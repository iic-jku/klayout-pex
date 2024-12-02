v {xschem version=3.4.5 file_version=1.2
}
G {}
K {}
V {}
S {}
E {}
T {Testbench to determine the capacitance value.
Find the cutoff frequency of the RC filter.

Fc = 1/(2*pi*R*C)

C = 1/(2*pi*R*Fc)
} 600 -600 0 0 0.2 0.2 { layer=11}
T {(C = 200.5fF / 2.005005e-13)} 600 -510 0 0 0.25 0.25 { layer=7}
N 100 -590 120 -590 {
lab=vin}
N 260 -590 440 -590 {
lab=vout}
N 210 -590 260 -590 {
lab=vout}
N 120 -590 150 -590 {
lab=vin}
N 80 -590 100 -590 {
lab=vin}
C {devices/iopin.sym} 80 -590 2 0 {name=p1 lab=vin}
C {devices/code_shown.sym} 170 -470 0 0 {name=NGSPICE only_toplevel=false value="
*** VXXX N+ N- SINE(Voffset Vampl FREQ) AC ACMAG
V1 vin 0 SINE(0 3 1k) AC 3

.save all

.control
*** ac (DEC|LIN|OCT) N Fstart Fstop
ac lin 10000 1 200GHz
plot vdb(vout)
* plot (180/PI)*phase(vout)

let R1 = 100

** MEASURE CUTOFF FREQUENCY
meas ac vomax MAX vdb(vout)
let vdrop = vomax - 3
meas ac cutoff_freq_3db WHEN vdb(vout)=vdrop CROSS=1
let cap = 1/(2*pi*R1*cutoff_freq_3db)
print cap
.endc
"}
C {devices/iopin.sym} 440 -590 0 0 {name=p2 lab=vout}
C {devices/title.sym} 140 -40 0 0 {name=l3 author="Martin Köhler"}
C {devices/res.sym} 180 -590 3 0 {name=R1
value=100
footprint=1206
device=resistor
m=1}
C {devices/gnd.sym} 320 -530 0 0 {name=l1 lab=GND}
C {devices/code.sym} 10 -220 0 0 {name=TT_MODELS
only_toplevel=true
format="tcleval( @value )"
value="
** opencircuitdesign pdks install
.lib $::SKYWATER_MODELS/sky130.lib.spice tt

"
spice_ignore=false}
C {sky130_fd_pr/cap_mim_m3_1.sym} 320 -560 0 0 {name=C2 model=cap_mim_m3_1 W=18.9 L=5.1 MF=1 spiceprefix=X}
