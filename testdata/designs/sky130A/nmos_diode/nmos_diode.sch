v {xschem version=3.4.5 file_version=1.2
}
G {}
K {}
V {}
S {}
E {}
T {nmos used 
as diode} 170 -430 0 0 0.2 0.2 {}
N 160 -350 160 -330 {
lab=VSS}
N 160 -430 160 -410 {
lab=VDD}
N 120 -420 160 -420 {
lab=VDD}
N 120 -420 120 -380 {
lab=VDD}
N 160 -330 160 -320 {
lab=VSS}
N 160 -440 160 -430 {
lab=VDD}
N 160 -380 180 -380 {
lab=VSS}
C {devices/iopin.sym} 40 -450 0 0 {name=p1 lab=VDD}
C {devices/iopin.sym} 40 -430 0 0 {name=p2 lab=VSS}
C {devices/lab_pin.sym} 160 -440 2 0 {name=l11 sig_type=std_logic lab=VDD
}
C {devices/lab_pin.sym} 160 -320 0 1 {name=l1 sig_type=std_logic lab=VSS
}
C {devices/code_shown.sym} 10 -280 0 0 {name=NGSPICE only_toplevel=false value="
* .lib /foss/pdks/sky130A/libs.tech/ngspice/sky130.lib.spice.tt.red tt
* .op
"}
C {sky130_fd_pr/nfet_01v8.sym} 140 -380 0 0 {name=M2
L=0.15
W=3
nf=1 
mult=1
ad="'int((nf+1)/2) * W/nf * 0.29'" 
pd="'2*int((nf+1)/2) * (W/nf + 0.29)'"
as="'int((nf+2)/2) * W/nf * 0.29'" 
ps="'2*int((nf+2)/2) * (W/nf + 0.29)'"
nrd="'0.29 / W'" nrs="'0.29 / W'"
sa=0 sb=0 sd=0
model=nfet_01v8
spiceprefix=X
}
C {devices/lab_pin.sym} 180 -380 2 0 {name=l2 sig_type=std_logic lab=VSS
}
